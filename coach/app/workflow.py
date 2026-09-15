"""Transactional session operations; the single write boundary for routes."""

from datetime import datetime, timezone

from .db import encode_json, immediate_transaction, row_to_session
from .feedback_validation import (
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


def import_session(conn, plan, now):
    with immediate_transaction(conn):
        plan = validate_plan(plan)
        identifier = plan["session_id"]
        if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (identifier,)).fetchone():
            raise WorkflowError("duplicate_session", "L'identificatore della sessione è già presente.")

        current = get_current_session(conn)
        replacement_id = plan.get("replaces_session_id")
        if replacement_id is not None:
            if (
                current is None
                or current["id"] != replacement_id
                or current["status"] != "planned"
                or not current["pre_operational"]
                or current["started_at"] is not None
            ):
                raise WorkflowError("invalid_replacement", "La sostituzione richiesta non è consentita.")
            maximum = conn.execute("SELECT MAX(sequence_number) FROM sessions").fetchone()[0]
            if (
                plan["sequence_number"] != current["sequence_number"]
                and plan["sequence_number"] <= maximum
            ):
                raise WorkflowError("invalid_sequence", "La sostituzione deve mantenere il numero corrente o superare quelli già presenti.")
            conn.execute(
                "UPDATE sessions SET status = ?, superseded_at = ? WHERE id = ?",
                ("superseded", now, replacement_id),
            )
        else:
            if current is not None:
                raise WorkflowError("current_session_exists", "Completa la sessione corrente prima di importarne un'altra.")
            maximum = conn.execute("SELECT MAX(sequence_number) FROM sessions").fetchone()[0]
            if maximum is not None and plan["sequence_number"] <= maximum:
                raise WorkflowError("invalid_sequence", "Il numero della nuova sessione deve superare quelli già presenti.")

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
        result = _require_session(conn, identifier)
    return result


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


def save_immediate_feedback(conn, session_id, feedback, now):
    with immediate_transaction(conn):
        session = _require_session(conn, session_id)
        _require_operational(session, {"planned", "immediate_done"})
        feedback = validate_immediate_feedback(feedback)
        conn.execute(
            """UPDATE sessions SET immediate_feedback_json = ?, status = ?,
                immediate_saved_at = ?, started_at = COALESCE(started_at, ?)
                WHERE id = ?""",
            (encode_json(feedback), "immediate_done", now, now, session_id),
        )


def save_next_morning_feedback(conn, session_id, feedback):
    with immediate_transaction(conn):
        session = _require_session(conn, session_id)
        _require_operational(session, {"immediate_done"})
        if session["immediate_feedback"] is None:
            raise WorkflowError("invalid_state", "Salva prima il feedback immediato.")
        feedback = validate_next_morning_feedback(feedback)
        conn.execute(
            "UPDATE sessions SET next_morning_feedback_json = ? WHERE id = ?",
            (encode_json(feedback), session_id),
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
        summary = build_coach_summary(session)
        conn.execute(
            "UPDATE sessions SET coach_summary_text = ?, status = ?, completed_at = ? WHERE id = ?",
            (summary, "complete", now, session_id),
        )
    return summary
