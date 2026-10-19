"""Transactional session operations; the single write boundary for routes."""

from datetime import date, datetime, timezone
import re

from .coach_text import RECENT_LIMIT, local_today, pack_text, state_text
from .db import (
    encode_json, immediate_transaction, read_transaction, row_to_proposal, row_to_session,
)
from .feedback_validation import (
    STRENGTH_KEYS,
    FeedbackValidationError,
    validate_immediate_feedback,
    validate_next_morning_feedback,
)
from .plan_validation import plan_item_ids, validate_plan
from .summary import build_coach_summary


class WorkflowError(ValueError):
    """A stable workflow code and an Italian, data-safe public message."""

    def __init__(self, code, public_message):
        self.code = code
        super().__init__(public_message)


_ISO_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
JOURNAL_TEXT_MAX = 1000


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_session(conn, session_id):
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row_to_session(row) if row is not None else None


def get_current_session(conn):
    row = conn.execute(
        "SELECT * FROM sessions WHERE status IN (?, ?)",
        ("planned", "immediate_done"),
    ).fetchone()
    return row_to_session(row) if row is not None else None


def list_sessions(conn):
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY sequence_number DESC, imported_at DESC"
    ).fetchall()
    return [row_to_session(row) for row in rows]


def list_complete_sessions(conn):
    """Complete sessions, most recently completed first."""
    rows = conn.execute(
        "SELECT * FROM sessions WHERE status = ? ORDER BY completed_at DESC, sequence_number DESC",
        ("complete",),
    ).fetchall()
    return [row_to_session(row) for row in rows]


def _journal_since(conn, previous, now):
    """Notes created after ``previous`` was finalized (all if None), up to ``now``."""
    created_after = previous["completed_at"] if previous is not None else None
    return [entry for entry in list_journal_entries(conn, created_after) if entry["created_at"] <= now]


def coach_context(conn, now):
    """Everything the coach state text needs, read in one place."""
    completed = list_complete_sessions(conn)
    return {
        "current": get_current_session(conn),
        "completed": completed,
        "journal_since_last": _journal_since(conn, completed[0] if completed else None, now),
        "pending_proposal": get_pending_proposal(conn),
    }


def build_state_text(conn, now):
    """The coach's live state, read as one snapshot; shared by the page and the MCP tool."""
    with read_transaction(conn):
        context = coach_context(conn, now)
    return state_text(
        context["current"], context["completed"], context["journal_since_last"],
        context["pending_proposal"], now,
    )


def build_pack_text(conn, now):
    """Whole history (without replaced sessions, oldest first) plus the full diary."""
    with read_transaction(conn):
        sessions = [session for session in list_sessions(conn) if session["status"] != "superseded"]
        journal = list_journal_entries(conn)
    return pack_text(list(reversed(sessions)), journal, now)


def _require_session(conn, session_id):
    session = get_session(conn, session_id)
    if session is None:
        raise WorkflowError("not_found", "Sessione non trovata.")
    return session


def _require_operational(session, allowed_states):
    # Terminal rows always report their immutable state, including old seeds.
    if session["status"] in {"complete", "superseded"}:
        raise WorkflowError("invalid_state", "La sessione non è modificabile.")
    if session["pre_operational"]:
        raise WorkflowError("pre_operational", "La scheda pre-operativa deve essere sostituita prima di iniziare.")
    if session["status"] not in allowed_states:
        raise WorkflowError("invalid_state", "Operazione non consentita nello stato attuale.")


def is_replaceable(session):
    """A current plan that was never started can be swapped for a new one."""
    return (
        session is not None
        and session["status"] == "planned"
        and session["started_at"] is None
        and session["completion"] == []
        and session["immediate_feedback"] is None
        and session["next_morning_feedback"] is None
    )


def _import_check(conn, plan, replace_current, expected_current_id):
    """Shared state rules for importing a schema-valid plan; never writes.

    Returns the plan to store (with ``replaces_session_id`` injected when
    ``replace_current`` asks to replace the current plan) and a list of
    ``(code, Italian message)`` problems, empty when the import is allowed.
    ``replace_current`` only targets the session the user saw: its id must be
    passed as ``expected_current_id`` and still be the current one.
    """
    plan = validate_plan(plan)
    current = get_current_session(conn)
    if replace_current:
        if current is None:
            return plan, [("invalid_replacement", "Non c'è una scheda corrente da sostituire.")]
        if expected_current_id is None or expected_current_id != current["id"]:
            return plan, [("invalid_replacement", "La sostituzione richiesta non è consentita.")]
        if "replaces_session_id" not in plan:
            plan = validate_plan(dict(plan, replaces_session_id=current["id"]))

    problems = []
    if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (plan["session_id"],)).fetchone():
        problems.append(("duplicate_session", "L'identificatore della sessione è già presente."))
    maximum = conn.execute("SELECT MAX(sequence_number) FROM sessions").fetchone()[0]
    replacement_id = plan.get("replaces_session_id")
    if replacement_id is not None:
        if current is None or current["id"] != replacement_id:
            problems.append(("invalid_replacement", "La sostituzione richiesta non è consentita."))
        elif not is_replaceable(current):
            problems.append(("invalid_replacement", "La scheda corrente è già iniziata e non può essere sostituita."))
        elif plan["sequence_number"] != current["sequence_number"] and plan["sequence_number"] <= maximum:
            problems.append(("invalid_sequence", "La sostituzione deve mantenere il numero corrente o superare quelli già presenti."))
    elif current is not None:
        problems.append(("current_session_exists", "Completa la sessione corrente prima di importarne un'altra."))
    elif maximum is not None and plan["sequence_number"] <= maximum:
        problems.append(("invalid_sequence", "Il numero della nuova sessione deve superare quelli già presenti."))
    return plan, problems


def import_problems(conn, plan, replace_current=False, expected_current_id=None):
    """Italian state messages that would block ``import_session``; empty if importable.

    Only state is checked here: callers must validate the plan schema first,
    otherwise ``PlanValidationError`` is raised.
    """
    _, problems = _import_check(conn, plan, replace_current, expected_current_id)
    return tuple(message for _, message in problems)


def import_offer(conn, plan):
    """State check of a schema-valid plan as the import preview shows it; never writes.

    When the plan declares no replacement and the current plan was never
    started, the preview offers to replace it: the problems are then those of
    that replacement path.
    """
    current = get_current_session(conn)
    declared = plan.get("replaces_session_id")
    replace_current = declared is None and is_replaceable(current)
    expected_current_id = current["id"] if replace_current else None
    problems = import_problems(conn, plan, replace_current, expected_current_id)
    replaces_current = current is not None and (replace_current or declared == current["id"])
    return dict(
        problems=problems, current=current, replaces_current=replaces_current,
        replace_current=replace_current, replace_offer=replaces_current and not problems,
    )


def _import_session_in_tx(conn, plan, now, replace_current, expected_current_id):
    """Insert a plan inside the caller's ``immediate_transaction``."""
    plan, problems = _import_check(conn, plan, replace_current, expected_current_id)
    if problems:
        raise WorkflowError(*problems[0])
    identifier = plan["session_id"]
    replacement_id = plan.get("replaces_session_id")
    if replacement_id is not None:
        # The partial unique index allows one active row: retire it first.
        conn.execute(
            "UPDATE sessions SET status = ?, superseded_at = ? WHERE id = ?",
            ("superseded", now, replacement_id),
        )

    conn.execute(
        """INSERT INTO sessions (
            id, schema_version, sequence_number, title, activity_type,
            estimated_minutes, status, pre_operational, plan_json,
            completion_json, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (identifier, plan["schema_version"], plan["sequence_number"],
         plan["title"], plan["activity_type"], plan["estimated_minutes"],
         "planned", int(plan["pre_operational"]), encode_json(plan), encode_json([]), now),
    )
    if replacement_id is not None:
        conn.execute(
            "UPDATE sessions SET superseded_by_id = ? WHERE id = ?",
            (identifier, replacement_id),
        )
    return _require_session(conn, identifier)


def import_session(conn, plan, now, replace_current=False, expected_current_id=None):
    """Manual import; a pending coach proposal is discarded in the same transaction."""
    with immediate_transaction(conn):
        result = _import_session_in_tx(conn, plan, now, replace_current, expected_current_id)
        _discard_pending(conn, now)
    return result


# --- coach proposals ------------------------------------------------------------

def _discard_pending(conn, now):
    conn.execute(
        "UPDATE plan_proposals SET status = ?, decided_at = ? WHERE status = ?",
        ("discarded", now, "pending"),
    )


def get_pending_proposal(conn):
    row = conn.execute("SELECT * FROM plan_proposals WHERE status = ?", ("pending",)).fetchone()
    return row_to_proposal(row) if row is not None else None


def get_proposal(conn, proposal_id):
    row = conn.execute("SELECT * FROM plan_proposals WHERE id = ?", (proposal_id,)).fetchone()
    return row_to_proposal(row) if row is not None else None


def _require_pending_proposal(conn, proposal_id):
    proposal = get_proposal(conn, proposal_id)
    if proposal is None:
        raise WorkflowError("not_found", "Proposta non trovata.")
    if proposal["status"] != "pending":
        raise WorkflowError("proposal_not_pending", "La proposta non è più in attesa.")
    return proposal


def create_proposal(conn, plan, now):
    """Store a schema-valid plan as the only pending proposal; never touches sessions."""
    plan = validate_plan(plan)
    with immediate_transaction(conn):
        _discard_pending(conn, now)
        cursor = conn.execute(
            "INSERT INTO plan_proposals (created_at, plan_json, status) VALUES (?, ?, ?)",
            (now, encode_json(plan), "pending"),
        )
        proposal = get_proposal(conn, cursor.lastrowid)
    return proposal


def discard_proposal(conn, proposal_id, now):
    with immediate_transaction(conn):
        _require_pending_proposal(conn, proposal_id)
        conn.execute(
            "UPDATE plan_proposals SET status = ?, decided_at = ? WHERE id = ?",
            ("discarded", now, proposal_id),
        )


def accept_proposal(conn, proposal_id, now, replace_current=False, expected_current_id=None):
    """Import the pending proposal and mark it accepted, atomically."""
    with immediate_transaction(conn):
        proposal = _require_pending_proposal(conn, proposal_id)
        session = _import_session_in_tx(conn, proposal["plan"], now, replace_current, expected_current_id)
        conn.execute(
            "UPDATE plan_proposals SET status = ?, decided_at = ?, session_id = ? WHERE id = ?",
            ("accepted", now, session["id"], proposal_id),
        )
    return session


def _canonical_completion(plan, item_ids):
    if type(item_ids) is not list or any(type(item) is not str for item in item_ids):
        raise WorkflowError("invalid_completion", "L'elenco degli esercizi completati non è valido.")
    ordered_ids = plan_item_ids(plan)
    selected = set(item_ids)
    if not selected.issubset(ordered_ids):
        raise WorkflowError("invalid_completion", "L'elenco contiene esercizi non previsti dalla scheda.")
    return [identifier for identifier in ordered_ids if identifier in selected]


def save_completion(conn, session_id, item_ids, now):
    with immediate_transaction(conn):
        session = _require_session(conn, session_id)
        _require_operational(session, {"planned"})
        completion = _canonical_completion(session["plan"], item_ids)
        started_at = session["started_at"]
        if started_at is None and completion:
            started_at = now
        conn.execute(
            "UPDATE sessions SET completion_json = ?, started_at = ? WHERE id = ?",
            (encode_json(completion), started_at, session_id),
        )


def reset_completion(conn, session_id):
    """Reset after the calling route has obtained explicit confirmation."""
    with immediate_transaction(conn):
        session = _require_session(conn, session_id)
        _require_operational(session, {"planned"})
        conn.execute(
            "UPDATE sessions SET completion_json = ? WHERE id = ?",
            (encode_json([]), session_id),
        )


def mark_rest_started(conn, session_id, now):
    with immediate_transaction(conn):
        session = _require_session(conn, session_id)
        _require_operational(session, {"planned"})
        if session["plan"]["activity_type"] != "rest" or plan_item_ids(session["plan"]):
            raise WorkflowError("invalid_state", "L'avvio esplicito è riservato alle schede di riposo senza esercizi.")
        conn.execute(
            "UPDATE sessions SET started_at = COALESCE(started_at, ?) WHERE id = ?",
            (now, session_id),
        )


def _check_strength_context(plan, feedback):
    """Plan-dependent rules for v1.1 feedback; stored v1 feedback has no strength keys."""
    if not any(key in feedback for key in STRENGTH_KEYS):
        return
    errors = []
    if plan["activity_type"] == "rest":
        if feedback["perceived_effort"] is not None:
            errors.append("$.perceived_effort: deve essere vuoto per una giornata di riposo")
    elif feedback["perceived_effort"] is None:
        errors.append("$.perceived_effort: campo obbligatorio")
    known_ids = set(plan_item_ids(plan))
    for identifier in feedback["exercise_feedback"]:
        if identifier not in known_ids:
            errors.append(f"$.exercise_feedback.{identifier}: esercizio non previsto dalla scheda")
    if errors:
        raise FeedbackValidationError(errors)


def save_immediate_feedback(conn, session_id, feedback, now):
    with immediate_transaction(conn):
        session = _require_session(conn, session_id)
        _require_operational(session, {"planned", "immediate_done"})
        feedback = validate_immediate_feedback(feedback)
        _check_strength_context(session["plan"], feedback)
        conn.execute(
            """UPDATE sessions SET immediate_feedback_json = ?, status = ?,
                immediate_saved_at = ?, started_at = COALESCE(started_at, ?)
                WHERE id = ?""",
            (encode_json(feedback), "immediate_done", now, now, session_id),
        )


def save_next_morning_feedback(conn, session_id, feedback, now):
    with immediate_transaction(conn):
        session = _require_session(conn, session_id)
        _require_operational(session, {"immediate_done"})
        if session["immediate_feedback"] is None:
            raise WorkflowError("invalid_state", "Salva prima il feedback immediato.")
        feedback = validate_next_morning_feedback(feedback)
        conn.execute(
            "UPDATE sessions SET next_morning_feedback_json = ?, morning_saved_at = ? WHERE id = ?",
            (encode_json(feedback), now, session_id),
        )


def finalize_session(conn, session_id, now):
    with immediate_transaction(conn):
        session = _require_session(conn, session_id)
        if session["status"] == "complete":
            return session["coach_summary_text"]
        _require_operational(session, {"planned", "immediate_done"})
        if session["immediate_feedback"] is None or session["next_morning_feedback"] is None:
            raise WorkflowError("feedback_incomplete", "Entrambi i feedback sono necessari per concludere la sessione.")
        _require_operational(session, {"immediate_done"})

        # Validate persisted values as well as new input before generating output.
        session["plan"] = validate_plan(session["plan"])
        completion = _canonical_completion(session["plan"], session["completion"])
        if completion != session["completion"]:
            raise WorkflowError("invalid_completion", "Il completamento memorizzato non è valido.")
        session["immediate_feedback"] = validate_immediate_feedback(session["immediate_feedback"])
        session["next_morning_feedback"] = validate_next_morning_feedback(session["next_morning_feedback"])
        recent = list_complete_sessions(conn)[:RECENT_LIMIT]
        previous = recent[0] if recent else None
        context = {
            "now": now, "previous": previous,
            "journal": _journal_since(conn, previous, now), "recent": recent,
        }
        summary = build_coach_summary(session, context)
        conn.execute(
            "UPDATE sessions SET coach_summary_text = ?, status = ?, completed_at = ? WHERE id = ?",
            (summary, "complete", now, session_id),
        )
    return summary


def _journal_row(row):
    return {
        "id": row["id"], "entry_date": row["entry_date"],
        "created_at": row["created_at"], "text": row["text"],
    }


def add_journal_entry(conn, entry_date, text, now):
    if type(entry_date) is not str or not _ISO_DATE_RE.fullmatch(entry_date):
        raise WorkflowError("invalid_journal", "La data della nota non è valida.")
    try:
        date.fromisoformat(entry_date)
    except ValueError:
        raise WorkflowError("invalid_journal", "La data della nota non è valida.") from None
    if entry_date > local_today(now):
        raise WorkflowError("invalid_journal", "La data della nota non può essere nel futuro.")
    if type(text) is not str:
        raise WorkflowError("invalid_journal", "La nota deve contenere da 1 a 1000 caratteri.")
    text = text.replace("\r\n", "\n").strip()
    if not 1 <= len(text) <= JOURNAL_TEXT_MAX:
        raise WorkflowError("invalid_journal", "La nota deve contenere da 1 a 1000 caratteri.")
    with immediate_transaction(conn):
        cursor = conn.execute(
            "INSERT INTO journal_entries (entry_date, created_at, text) VALUES (?, ?, ?)",
            (entry_date, now, text),
        )
        row = conn.execute(
            "SELECT * FROM journal_entries WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return _journal_row(row)


def list_journal_entries(conn, created_after=None):
    if created_after is None:
        rows = conn.execute("SELECT * FROM journal_entries ORDER BY created_at, id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM journal_entries WHERE created_at > ? ORDER BY created_at, id",
            (created_after,),
        ).fetchall()
    return [_journal_row(row) for row in rows]
