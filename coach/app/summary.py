"""Deterministic plain-text session summary for the coach."""

from .coach_text import (
    ACTIVITY_LABELS, EXERCISE_RATING_LABELS, RED_FLAG_LABELS, RECENT_LIMIT, STATUS_LABELS, YELLOW_FLAG_LABELS,
    compact_line, days_between, duration_text, effort_text, exercise_comment_lines, format_local,
    generated_header, journal_lines, prefixed_text as _prefixed_text, previous_reference,
    selected_flags as _selected_flags, session_timestamp, text_field as _text_field,
)



ONSET_LABELS = {
    "none": "nessun fastidio",
    "during": "durante l'attività",
    "within_2h": "entro 2 ore",
    "later_same_day": "più tardi nello stesso giorno",
    "overnight": "durante la notte",
    "next_morning": "il mattino successivo",
    "unknown": "non noto",
}
DURATION_LABELS = {
    "none": "nessun fastidio",
    "under_1h": "meno di 1 ora",
    "1_to_4h": "da 1 a 4 ore",
    "half_day": "mezza giornata",
    "full_day": "un'intera giornata",
    "over_1day": "oltre 1 giorno",
    "ongoing": "ancora presente",
    "unknown": "non nota",
}


def _yes_no(value):
    return "sì" if value else "no"


def _exercise_lines(plan, completion):
    items = [item for section in plan["sections"] for item in section["items"]]
    completed = [item for item in items if item["id"] in completion]
    skipped = [item for item in items if item["id"] not in completion]
    lines = ["ESERCIZI", f"Completati: {len(completed)}/{len(items)}"]
    lines.extend(_prefixed_text("- ", f"{item['name']} — {item['dose']}") for item in completed)
    if skipped:
        lines.append("Saltati:")
        lines.extend(_prefixed_text("- ", f"{item['name']} — {item['dose']}") for item in skipped)
    return lines


def _immediate_lines(feedback, plan=None):
    """v1 block; with ``plan`` (v1.1 summary) also effort, difficulties and per-exercise comments."""
    lines = [
        "FEEDBACK IMMEDIATO",
        f"Dolore lombare: {feedback['lumbar_pain']}/10",
        f"Rigidità: {feedback['stiffness']}/10",
        f"Fatica: {feedback['fatigue']}/10",
    ]
    if plan is not None:
        lines.append(f"Sforzo percepito: {effort_text({'immediate_feedback': feedback})}")
    lines.extend([
        f"Sintomi alla gamba: {_yes_no(feedback['leg_symptoms'])}",
        _text_field("Dettaglio gamba", feedback["leg_details"], "nessuno"),
        f"Segnali gialli: {_selected_flags(feedback['yellow_flags'], YELLOW_FLAG_LABELS)}",
        f"Segnali rossi: {_selected_flags(feedback['red_flags'], RED_FLAG_LABELS)}",
        _text_field("Altra attività o carichi", feedback["additional_activity"], "nessuno"),
    ])
    if plan is not None:
        if "difficulties" in feedback:
            lines.append(_text_field("Difficoltà", feedback["difficulties"], "nessuna"))
        else:
            lines.append("Difficoltà: non registrato")
        lines.extend(exercise_comment_lines(plan, feedback))
    lines.append(_text_field("Note", feedback["notes"], "nessuna"))
    return lines


def _morning_lines(feedback):
    return [
        "CONTROLLO DEL MATTINO SUCCESSIVO",
        f"Dolore lombare: {feedback['lumbar_pain']}/10",
        f"Rigidità: {feedback['stiffness']}/10",
        f"Fatica residua: {feedback['residual_fatigue']}/10",
        f"Sintomi alla gamba: {_yes_no(feedback['leg_symptoms'])}",
        _text_field("Dettaglio gamba", feedback["leg_details"], "nessuno"),
        f"Ritorno al livello abituale: {_yes_no(feedback['back_to_baseline'])}",
        f"Comparsa del fastidio: {ONSET_LABELS[feedback['discomfort_onset']]}",
        f"Durata approssimativa: {DURATION_LABELS[feedback['approximate_duration']]}",
        f"Segnali gialli: {_selected_flags(feedback['yellow_flags'], YELLOW_FLAG_LABELS)}",
        f"Segnali rossi: {_selected_flags(feedback['red_flags'], RED_FLAG_LABELS)}",
        _text_field("Note", feedback["notes"], "nessuna"),
    ]


COACH_REQUEST = (
    "Valuta questi dati e restituisci la giornata successiva come JSON conforme allo schema v1 dell'app. "
    "Non aumentare o modificare il piano senza considerare anche i segnali riportati."
)


def _timing_lines(session, previous):
    timestamp = session_timestamp(session)
    if previous is None:
        days = "prima sessione registrata"
    else:
        days = previous_reference(previous, days_between(previous, session))
    return [
        f"Data: {format_local(timestamp) if timestamp is not None else 'non registrata'}",
        f"Durata: {duration_text(session)}",
        f"Giorni dalla sessione precedente: {days}",
    ]


def build_coach_summary(session, context=None):
    """Format a complete decoded session as stable text ending in one newline.

    Without ``context`` the original v1 text is produced. With
    ``context = {"now", "previous", "journal", "recent"}`` (previous complete
    session or None, diary notes since it, up to five recent complete
    sessions, newest first) the v1.1 text adds timings, diary and history.
    """
    plan = session["plan"]
    completion = session["completion"]
    immediate = session["immediate_feedback"]
    morning = session["next_morning_feedback"]
    if immediate is None or morning is None:
        raise ValueError("Entrambi i feedback sono obbligatori per il riepilogo.")

    if context is None:
        header = ["FEEDBACK SESSIONE PER IL COACH — v1"]
    else:
        header = ["FEEDBACK SESSIONE PER IL COACH — v1.1", generated_header(context["now"])]
    lines = [
        *header,
        _prefixed_text(f"Sessione: {plan['sequence_number']} — ", plan["title"]),
        f"ID: {plan['session_id']}",
        f"Tipo: {ACTIVITY_LABELS[plan['activity_type']]}",
        *(_timing_lines(session, context["previous"]) if context is not None else []),
        f"Durata stimata: {plan['estimated_minutes']} minuti",
        f"Pre-operativa: {_yes_no(plan['pre_operational'])}",
        "",
        *_exercise_lines(plan, completion),
        "",
        *_immediate_lines(immediate, plan if context is not None else None),
        "",
        *_morning_lines(morning),
        "",
    ]
    if context is not None:
        recent = [f"- {compact_line(item)}" for item in context["recent"][:RECENT_LIMIT]]
        lines.extend([
            "DIARIO",
            *journal_lines(context["journal"]),
            "",
            f"STORICO RECENTE (ultime {RECENT_LIMIT})",
            *(recent or ["nessuna sessione precedente"]),
            "",
        ])
    lines.extend(["RICHIESTA AL COACH", COACH_REQUEST])
    return "\n".join(lines) + "\n"


def _moment(value):
    return format_local(value) if value is not None else "non registrato"


def session_detail_text(session, now):
    """Everything stored about one session, for the coach's ``dettaglio_sessione``.

    Old (v1) rows lack ``morning_saved_at`` and the v1.1 feedback keys: they
    read "non registrato", like a feedback not given yet.
    """
    plan = session["plan"]
    immediate = session.get("immediate_feedback")
    morning = session.get("next_morning_feedback")
    lines = [
        generated_header(now),
        "DETTAGLIO SESSIONE",
        _prefixed_text(f"Sessione: {plan['sequence_number']} — ", plan["title"]),
        f"ID: {session['id']}",
        f"Tipo: {ACTIVITY_LABELS[plan['activity_type']]}",
        f"Stato: {STATUS_LABELS[session['status']]}",
        f"Pre-operativa: {_yes_no(session['pre_operational'])}",
        f"Durata stimata: {plan['estimated_minutes']} minuti",
        f"Durata: {duration_text(session)}",
        "",
        "TEMPI",
        f"Importata: {_moment(session.get('imported_at'))}",
        f"Prima spunta: {_moment(session.get('started_at'))}",
        f"Feedback immediato: {_moment(session.get('immediate_saved_at'))}",
        f"Controllo del mattino: {_moment(session.get('morning_saved_at'))}",
        f"Conclusa: {_moment(session.get('completed_at'))}",
    ]
    if session["status"] == "superseded":
        lines.append(f"Sostituita: {_moment(session.get('superseded_at'))} da {session.get('superseded_by_id') or '-'}")
    if session["status"] == "skipped":
        lines.append(f"Non eseguita: {_moment(session.get('skipped_at'))}")
    lines.extend(["", "NOTE DELLA SCHEDA"])
    lines.extend([_prefixed_text("- ", note) for note in plan["session_notes"]] or ["nessuna"])
    lines.extend(["", *_exercise_lines(plan, session["completion"]), ""])
    lines.extend(_immediate_lines(immediate, plan) if immediate is not None else ["FEEDBACK IMMEDIATO", "non registrato"])
    lines.append("")
    lines.extend(_morning_lines(morning) if morning is not None else ["CONTROLLO DEL MATTINO SUCCESSIVO", "non registrato"])
    lines.extend(["", "RIEPILOGO SALVATO"])
    summary = session.get("coach_summary_text")
    if summary is None:
        lines.append({
            "superseded": "nessuno: la sessione è stata sostituita.",
            "skipped": "nessuno: la sessione non è stata eseguita.",
        }.get(session["status"], "non ancora generato: la sessione non è conclusa."))
        return "\n".join(lines) + "\n"
    return "\n".join(lines) + "\n" + summary
