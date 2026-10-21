"""Public routes for the current guided session."""

import json
import re

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, url_for

from .coach_text import STATUS_LABELS, format_local, local_today
from .db import get_db
from .feedback_validation import (
    FeedbackValidationError,
    immediate_payload_from_form,
    next_morning_payload_from_form,
    validate_immediate_feedback,
    validate_next_morning_feedback,
)
from .plan_validation import PlanValidationError, parse_plan_input, plan_item_ids, validate_plan, youtube_embed_url
from .summary import (
    DURATION_LABELS, EXERCISE_RATING_LABELS, ONSET_LABELS, RED_FLAG_LABELS, YELLOW_FLAG_LABELS,
)
from .workflow import (
    TERMINAL_STATUSES,
    WorkflowError,
    accept_proposal,
    add_journal_entry,
    build_pack_text,
    build_state_text,
    discard_proposal,
    finalize_session,
    get_current_session,
    get_pending_proposal,
    get_proposal,
    get_session,
    import_offer,
    import_session,
    is_started,
    list_sessions,
    reset_completion,
    save_completion,
    save_immediate_feedback,
    skip_problem,
    save_next_morning_feedback,
    skip_session,
    utc_now_iso,
)


main = Blueprint("main", __name__)


def _local_time(value):
    if value is None:
        return None
    return format_local(value)


_DURATION_RE = re.compile(r"(\d+)(?:\s*[–-]\s*(\d+))?\s*(secondi|secondo|minuti|minuto)", re.IGNORECASE)


def _timer_seconds(dose):
    """Best-effort duration hint for the optional focus-mode timer; None when the dose is a rep count."""
    match = _DURATION_RE.search(dose)
    if not match:
        return None
    numbers = [int(match.group(1))]
    if match.group(2):
        numbers.append(int(match.group(2)))
    seconds = max(numbers)
    return seconds * 60 if match.group(3).lower().startswith("minut") else seconds


def _current_item(session, plan, ordered_ids):
    if session["status"] != "planned" or session["pre_operational"]:
        return None, None, None
    completed = set(session["completion"])
    for index, identifier in enumerate(ordered_ids, start=1):
        if identifier not in completed:
            name = next(
                item["name"]
                for section in plan["sections"]
                for item in section["items"]
                if item["id"] == identifier
            )
            return identifier, name, index
    return None, None, None


def _present_session(session):
    if session is None:
        return None
    plan = session["plan"]
    sections = []
    for section in plan["sections"]:
        items = []
        for item in section["items"]:
            presented = dict(item)
            presented["embed_url"] = youtube_embed_url(item["video_url"]) if "video_url" in item else None
            presented["timer_seconds"] = _timer_seconds(item["dose"])
            items.append(presented)
        sections.append({"title": section["title"], "items": items})
    ordered_ids = plan_item_ids(plan)
    current_item_id, current_item_name, current_item_index = _current_item(session, plan, ordered_ids)
    return {
        "id": session["id"],
        "title": session["title"],
        "type": {
            "complete": "Completa",
            "mobility": "Mobilità",
            "walk": "Camminata",
            "rest": "Riposo",
            "combined": "Combinata",
        }[session["activity_type"]],
        "estimated_minutes": session["estimated_minutes"],
        "pre_operational": bool(session["pre_operational"]),
        "status": session["status"],
        "sequence_number": session["sequence_number"],
        "notes": plan["session_notes"],
        "sections": sections,
        "completion": set(session["completion"]),
        "total": len(plan_item_ids(plan)),
        "imported_at": _local_time(session["imported_at"]),
        "started_at": _local_time(session["started_at"]),
        "immediate_saved_at": _local_time(session["immediate_saved_at"]),
        "completed_at": _local_time(session["completed_at"]),
        "superseded_at": _local_time(session["superseded_at"]),
        "skipped_at": _local_time(session["skipped_at"]),
        "is_started": is_started(session),
        "is_terminal": session["status"] in TERMINAL_STATUSES,
        "status_label": STATUS_LABELS[session["status"]],
        "is_empty_rest": session["activity_type"] == "rest" and not plan_item_ids(plan),
        "current_item_id": current_item_id,
        "current_item_name": current_item_name,
        "current_item_index": current_item_index,
    }


def _workflow_status(error):
    if error.code == "not_found":
        return 404
    if error.code in {"invalid_state", "pre_operational", "proposal_not_pending"}:
        return 409
    return 400


def _form_error(message, status):
    return render_template("error.html", error_message=message, status=status), status


@main.get("/import")
def import_plan_form():
    return render_template("import_plan.html", raw_plan="", errors=())


@main.post("/import/preview")
def import_preview():
    raw_plan = request.form.get("raw_plan", "")
    try:
        plan = validate_plan(parse_plan_input(raw_plan))
    except PlanValidationError as error:
        return render_template("import_plan.html", raw_plan=raw_plan, errors=error.errors), 400
    normalized_plan = json.dumps(plan, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return render_template(
        "import_preview.html", normalized_plan=normalized_plan, proposal=None,
        **_preview_context(get_db(), plan),
    )


def _preview_context(conn, plan):
    """Shared by manual import and coach proposals: state problems and replacement offer."""
    return dict(plan=plan, **import_offer(conn, plan))


@main.post("/import/confirm")
def import_confirm():
    raw_plan = request.form.get("normalized_plan", "")
    try:
        plan = validate_plan(parse_plan_input(raw_plan))
    except PlanValidationError as error:
        return render_template("import_plan.html", raw_plan=raw_plan, errors=error.errors), 400
    replace_current = request.form.get("replace_current") == "yes"
    supersedes = replace_current or plan.get("replaces_session_id") is not None
    if supersedes and request.form.get("confirm") != "yes":
        return _form_error("Conferma la sostituzione della scheda corrente.", 400)
    expected_current_id = request.form.get("expected_current_id") if replace_current else None
    try:
        import_session(
            get_db(), plan, utc_now_iso(),
            replace_current=replace_current, expected_current_id=expected_current_id,
        )
    except WorkflowError as error:
        return _form_error(str(error), 409)
    flash("Scheda importata.")
    return redirect(url_for("main.today"))


@main.get("/proposals/<int:proposal_id>")
def proposal_preview(proposal_id):
    conn = get_db()
    proposal = get_proposal(conn, proposal_id)
    if proposal is None:
        return _form_error("Proposta non trovata.", 404)
    if proposal["status"] != "pending":
        return _form_error("La proposta non è più in attesa.", 409)
    if proposal["kind"] == "skip":
        return render_template(
            "proposal_skip.html", proposal=proposal,
            proposal_created_at=_local_time(proposal["created_at"]),
            target=_present_session(proposal["target"]),
            problem=(skip_problem(proposal["target"]) or (None, None))[1],
        )
    return render_template(
        "import_preview.html", proposal=proposal, proposal_created_at=_local_time(proposal["created_at"]),
        **_preview_context(conn, proposal["plan"]),
    )


@main.post("/proposals/<int:proposal_id>/accept")
def proposal_accept(proposal_id):
    if request.form.get("confirm") != "yes":
        return _form_error("Conferma l'importazione della proposta.", 400)
    replace_current = request.form.get("replace_current") == "yes"
    expected_current_id = request.form.get("expected_current_id") if replace_current else None
    try:
        accepted = accept_proposal(
            get_db(), proposal_id, utc_now_iso(),
            replace_current=replace_current, expected_current_id=expected_current_id,
        )
    except WorkflowError as error:
        return _form_error(str(error), 404 if error.code == "not_found" else 409)
    flash("Sessione segnata come non eseguita." if accepted["status"] == "skipped" else "Proposta importata.")
    return redirect(url_for("main.today"))


@main.post("/proposals/<int:proposal_id>/discard")
def proposal_discard(proposal_id):
    if request.form.get("confirm") != "yes":
        return _form_error("Conferma lo scarto della proposta.", 400)
    try:
        discard_proposal(get_db(), proposal_id, utc_now_iso())
    except WorkflowError as error:
        return _form_error(str(error), _workflow_status(error))
    flash("Proposta scartata.")
    return redirect(url_for("main.today"))


@main.get("/history")
def history():
    sessions = [_present_session(session) for session in list_sessions(get_db())]
    return render_template("history.html", sessions=sessions)


@main.get("/coach/state")
def coach_state():
    return render_template("coach_state.html", state_text=build_state_text(get_db(), utc_now_iso()))


@main.get("/coach/pack")
def coach_pack():
    now = utc_now_iso()
    response = Response(build_pack_text(get_db(), now), content_type="text/markdown; charset=utf-8")
    response.headers["Content-Disposition"] = f'attachment; filename="pacchetto-coach-{local_today(now)}.md"'
    return response


def _render_today(error_message=None, status=200):
    conn = get_db()
    current = get_current_session(conn)
    session = _present_session(current)
    proposal = get_pending_proposal(conn)
    # A plan proposal that would replace the current session is a modification of it.
    modifies = (
        proposal is not None and proposal["kind"] == "plan"
        and import_offer(conn, proposal["plan"])["replaces_current"]
    )
    return render_template(
        "today.html", session=session, error_message=error_message,
        pending_proposal=proposal, proposal_modifies=current["sequence_number"] if modifies else None,
        journal_today=local_today(utc_now_iso()),
    ), status


@main.get("/")
def today():
    return _render_today()


@main.post("/journal")
def journal():
    try:
        add_journal_entry(
            get_db(), request.form.get("entry_date"), request.form.get("text"), utc_now_iso()
        )
    except WorkflowError as error:
        return _render_today(str(error), _workflow_status(error))
    flash("Nota salvata.")
    return redirect(url_for("main.today"))


@main.post("/sessions/<session_id>/completion")
def completion(session_id):
    payload = request.get_json(silent=True)
    if type(payload) is not dict:
        return jsonify(error="Richiesta non valida."), 400
    item_ids = payload.get("completed_item_ids")
    try:
        save_completion(get_db(), session_id, item_ids, utc_now_iso())
    except WorkflowError as error:
        return jsonify(error=str(error)), _workflow_status(error)

    session = get_current_session(get_db())
    return jsonify(ok=True, completed=len(session["completion"]), total=len(plan_item_ids(session["plan"])))


@main.post("/sessions/<session_id>/reset-completion")
def reset_completion_route(session_id):
    if request.form.get("confirm") != "yes":
        return _form_error("Conferma l'azzeramento delle spunte.", 400)
    try:
        reset_completion(get_db(), session_id)
    except WorkflowError as error:
        return _form_error(str(error), _workflow_status(error))
    return redirect(url_for("main.today"))


@main.post("/sessions/<session_id>/skip")
def skip_session_route(session_id):
    if request.form.get("confirm") != "yes":
        return _form_error("Conferma che la sessione non è stata eseguita.", 400)
    try:
        skip_session(get_db(), session_id, utc_now_iso())
    except WorkflowError as error:
        return _form_error(str(error), _workflow_status(error))
    flash("Sessione segnata come non eseguita.")
    return redirect(url_for("main.today"))


FEEDBACK_LABELS = {
    "lumbar_pain": "Dolore lombare", "stiffness": "Rigidità", "fatigue": "Fatica",
    "residual_fatigue": "Fatica residua", "leg_symptoms": "Sintomi alla gamba",
    "leg_details": "Dettaglio dei sintomi alla gamba", "back_to_baseline": "Ritorno al livello abituale",
    "additional_activity": "Altra attività o carichi", "notes": "Note",
    "discomfort_onset": "Comparsa del fastidio", "approximate_duration": "Durata approssimativa",
    "perceived_effort": "Sforzo percepito della sessione (0–10)", "difficulties": "Difficoltà generali",
    "exercise_feedback": "Come sono andati gli esercizi",
}
YELLOW_FORM_KEYS = {
    "yellow_local_discomfort": "local_discomfort_more_than_usual",
    "yellow_stiffness_present": "stiffness_still_present",
}


def _feedback_context():
    return dict(labels=FEEDBACK_LABELS, red_labels=RED_FLAG_LABELS,
                yellow_labels=YELLOW_FLAG_LABELS, yellow_form_keys=YELLOW_FORM_KEYS,
                onset_labels=ONSET_LABELS, duration_labels=DURATION_LABELS,
                rating_labels=EXERCISE_RATING_LABELS)


def _plan_exercises(session):
    """Plan items in order, flagged as completed or skipped."""
    completed = set(session["completion"])
    return [
        {"id": item["id"], "name": item["name"], "completed": item["id"] in completed}
        for section in session["plan"]["sections"]
        for item in section["items"]
    ]


def _form_field_for_error(path):
    """Map `exercise_feedback.<id>[.rating|.note]` validator paths to the form field names."""
    if not path.startswith("exercise_feedback."):
        return path
    _, identifier, *rest = path.split(".")
    return f"rating_{identifier}" if rest == ["rating"] else f"note_{identifier}"


def _saved_form_values(feedback):
    values = {}
    for key, value in (feedback or {}).items():
        if key == "exercise_feedback":
            for identifier, entry in value.items():
                values.update({f"{field}_{identifier}": text for field, text in entry.items()})
        elif value is None:
            continue
        elif key == "red_flags":
            values.update({f"red_{flag}": checked for flag, checked in value.items()})
        elif key == "yellow_flags":
            values.update({form_key: value.get(flag, False) for form_key, flag in YELLOW_FORM_KEYS.items()})
        elif type(value) is bool:
            values[key] = "yes" if value else "no"
        else:
            values[key] = value
    return values


def _detail_response(session, error_message=None, status=200):
    can_finalize = False
    if session["status"] == "immediate_done" and not session["pre_operational"]:
        try:
            validate_immediate_feedback(session["immediate_feedback"])
            validate_next_morning_feedback(session["next_morning_feedback"])
            can_finalize = True
        except FeedbackValidationError:
            pass
    red_selected = any(
        any(feedback["red_flags"].values())
        for feedback in (session["immediate_feedback"], session["next_morning_feedback"])
        if feedback
    )
    exercise_names = {item["id"]: item["name"] for item in _plan_exercises(session)}
    return render_template("session_detail.html", session=session, presented=_present_session(session),
                           can_finalize=can_finalize, red_selected=red_selected, exercise_names=exercise_names,
                           error_message=error_message, **_feedback_context()), status


@main.get("/sessions/<session_id>")
def session_detail(session_id):
    session = get_session(get_db(), session_id)
    if session is None:
        return _form_error("Sessione non trovata.", 404)
    return _detail_response(session)


def _feedback_route(session_id, morning):
    session = get_session(get_db(), session_id)
    if session is None:
        return _form_error("Sessione non trovata.", 404)
    if session["status"] in TERMINAL_STATUSES:
        if request.method == "GET":
            return redirect(url_for("main.session_detail", session_id=session_id))
        return _detail_response(session, "La sessione non è modificabile.", 409)
    if session["pre_operational"]:
        return _detail_response(session, "La scheda pre-operativa deve essere sostituita prima di iniziare.", 409)
    if morning and (session["status"] != "immediate_done" or session["immediate_feedback"] is None):
        return _detail_response(session, "Salva prima il feedback immediato.", 409)

    feedback_key = "next_morning_feedback" if morning else "immediate_feedback"
    values = _saved_form_values(session[feedback_key])
    errors = {}
    if request.method == "POST":
        values = request.form
        try:
            if morning:
                save_next_morning_feedback(
                    get_db(), session_id, next_morning_payload_from_form(values), utc_now_iso()
                )
            else:
                payload = immediate_payload_from_form(values, plan_item_ids(session["plan"]))
                save_immediate_feedback(get_db(), session_id, payload, utc_now_iso())
        except FeedbackValidationError as error:
            for item in error.errors:
                field, _, message = item.partition(": ")
                errors.setdefault(_form_field_for_error(field.removeprefix("$.")), []).append(message)
        except WorkflowError as error:
            return _detail_response(get_session(get_db(), session_id), str(error), _workflow_status(error))
        else:
            flash("Feedback del mattino salvato." if morning else "Feedback immediato salvato. Le spunte sono bloccate.")
            return redirect(url_for("main.session_detail", session_id=session_id))
    total = len(plan_item_ids(session["plan"]))
    exercises = [] if morning else _plan_exercises(session)
    exercise_labels = {}
    for exercise in exercises:
        exercise_labels[f"rating_{exercise['id']}"] = f"Valutazione: {exercise['name']}"
        exercise_labels[f"note_{exercise['id']}"] = f"Nota: {exercise['name']}"
    return render_template(
        "next_morning_feedback.html" if morning else "immediate_feedback.html",
        session=session, values=values, errors=errors, morning=morning,
        exercises=exercises, exercise_labels=exercise_labels,
        show_effort=not morning and session["activity_type"] != "rest",
        red_selected=any(values.get(f"red_{key}") for key in RED_FLAG_LABELS),
        completed_count=len(session["completion"]), total_count=total,
        skipped_count=total - len(session["completion"]),
        **_feedback_context(),
    ), 400 if errors else 200


@main.route("/sessions/<session_id>/feedback/immediate", methods=["GET", "POST"])
def immediate_feedback(session_id):
    return _feedback_route(session_id, morning=False)


@main.route("/sessions/<session_id>/feedback/next-morning", methods=["GET", "POST"])
def next_morning_feedback(session_id):
    return _feedback_route(session_id, morning=True)


@main.post("/sessions/<session_id>/finalize")
def finalize(session_id):
    wants_json = request.is_json or request.accept_mimetypes["application/json"] > request.accept_mimetypes["text/html"]
    payload = request.get_json(silent=True) if request.is_json else request.form
    try:
        if not hasattr(payload, "get") or payload.get("confirm") != "yes":
            raise WorkflowError("confirmation_required", "Conferma la finalizzazione del feedback.")
        summary = finalize_session(get_db(), session_id, utc_now_iso())
    except (WorkflowError, FeedbackValidationError) as error:
        status = _workflow_status(error) if isinstance(error, WorkflowError) else 400
        message = str(error) if isinstance(error, WorkflowError) else "Correggi i feedback prima di concludere la sessione."
        if wants_json:
            return jsonify(error=message), status
        session = get_session(get_db(), session_id)
        return _detail_response(session, message, status) if session else _form_error(message, status)
    if wants_json:
        return jsonify(summary=summary, status="complete")
    return _detail_response(get_session(get_db(), session_id))
