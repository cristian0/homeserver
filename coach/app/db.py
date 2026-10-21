import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

from .plan_validation import PlanValidationError, parse_plan_input, validate_plan


def encode_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


@contextmanager
def immediate_transaction(conn):
    """Serialize a workflow's state read and writes as one atomic operation."""
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


@contextmanager
def read_transaction(conn):
    """One consistent snapshot for several reads; takes no write lock.

    BEGIN stays outside the try: if it fails (e.g. already in a transaction)
    the caller's outer transaction must not be rolled back.
    """
    conn.execute("BEGIN")
    try:
        yield
    finally:
        if conn.in_transaction:
            conn.rollback()


def open_connection(path):
    """An autocommit connection with the app's PRAGMAs; usable without Flask."""
    connection = sqlite3.connect(str(path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def get_db():
    if "db" not in g:
        g.db = open_connection(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def _migration_statements():
    """The v1.2 rebuild of sessions and plan_proposals, one statement each.

    The file holds no ';' inside literals or comments, so a plain split is safe.
    """
    text = Path(__file__).with_name("migrate_v12.sql").read_text(encoding="utf-8")
    return [statement.strip() for statement in text.split(";") if statement.strip()]


def _needs_v12_migration(conn):
    sessions_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'sessions'"
    ).fetchone()[0]
    proposal_columns = {row[1] for row in conn.execute("PRAGMA table_info(plan_proposals)")}
    return "'skipped'" not in sessions_sql or "kind" not in proposal_columns


def init_database(conn=None):
    """Create a fresh schema, or bring a v1/v1.1 database to v1.2 atomically.

    CREATE ... IF NOT EXISTS leaves older tables untouched; the rebuild then
    runs in one immediate transaction (never executescript, which commits).
    foreign_keys must be switched off outside a transaction for the rebuild.
    """
    schema_path = Path(__file__).with_name("schema.sql")
    if conn is None:
        conn = get_db()
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # v1 databases predate morning_saved_at.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            if "morning_saved_at" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN morning_saved_at TEXT")
            if _needs_v12_migration(conn):
                for statement in _migration_statements():
                    conn.execute(statement)
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Migrazione del database non riuscita.")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def seed_initial_session(conn, seed_path, now):
    """Insert the canonical session into an empty database once."""
    try:
        if conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]:
            return False
        raw = Path(seed_path).read_text(encoding="utf-8")
        plan = validate_plan(parse_plan_input(raw))
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]:
            conn.rollback()
            return False
        conn.execute(
            """
            INSERT INTO sessions (
                id, schema_version, sequence_number, title, activity_type,
                estimated_minutes, status, pre_operational, plan_json,
                completion_json, immediate_feedback_json,
                next_morning_feedback_json, coach_summary_text, imported_at,
                started_at, immediate_saved_at, completed_at, superseded_at,
                superseded_by_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan["session_id"],
                plan["schema_version"],
                plan["sequence_number"],
                plan["title"],
                plan["activity_type"],
                plan["estimated_minutes"],
                "planned",
                int(plan["pre_operational"]),
                encode_json(plan),
                encode_json([]),
                None,
                None,
                None,
                now,
                None,
                None,
                None,
                None,
                None,
            ),
        )
        conn.commit()
    except (OSError, UnicodeError, PlanValidationError, ValueError, TypeError, RecursionError):
        conn.rollback()
        raise RuntimeError("Scheda iniziale non valida.") from None
    except Exception:
        conn.rollback()
        raise
    return True


def _decode_stored_json(value):
    if not isinstance(value, str):
        raise ValueError("JSON persistito non testuale")

    def reject_constant(constant):
        raise ValueError(f"costante JSON non consentita: {constant}")

    return json.loads(value, parse_constant=reject_constant)


def row_to_session(row):
    if row is None:
        raise RuntimeError("Riga della sessione mancante.")

    try:
        session = {
            key: row[key]
            for key in row.keys()
            if not key.endswith("_json")
        }
        session["plan"] = validate_plan(parse_plan_input(row["plan_json"]))

        completion = _decode_stored_json(row["completion_json"])
        if type(completion) is not list or any(type(item) is not str for item in completion):
            raise ValueError("completamento persistito non valido")
        session["completion"] = completion

        for column, key in (
            ("immediate_feedback_json", "immediate_feedback"),
            ("next_morning_feedback_json", "next_morning_feedback"),
        ):
            feedback = row[column]
            if feedback is not None:
                feedback = _decode_stored_json(feedback)
                if type(feedback) is not dict:
                    raise ValueError("feedback persistito non valido")
            session[key] = feedback
    except Exception:
        raise RuntimeError("Dati della sessione non leggibili.") from None
    return session


def row_to_proposal(row):
    """A stored proposal; a plan proposal's plan is validated again, like a session's."""
    if row is None:
        raise RuntimeError("Riga della proposta mancante.")
    try:
        kind = row["kind"]
        if kind == "plan":
            plan, target = validate_plan(parse_plan_input(row["plan_json"])), None
        elif kind == "skip":
            plan, target = None, row["target_session_id"]
            if not isinstance(target, str):
                raise ValueError("sessione della proposta mancante")
        else:
            raise ValueError("tipo di proposta sconosciuto")
        return {
            "id": row["id"], "created_at": row["created_at"], "status": row["status"],
            "kind": kind, "plan": plan, "target_session_id": target,
        }
    except Exception:
        raise RuntimeError("Dati della proposta non leggibili.") from None


def ensure_secret_file(path):
    path = os.fspath(path)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        with open(path, "rb") as secret_file:
            value = secret_file.read()
    else:
        value = secrets.token_bytes(48)
        with os.fdopen(fd, "wb") as secret_file:
            secret_file.write(value)

    if len(value) < 32:
        raise RuntimeError("secret file must contain at least 32 bytes")
    return value


def ensure_token_file(path):
    """The MCP bearer token: created once (0600, exclusive), then read back."""
    path = os.fspath(path)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        with open(path, encoding="ascii") as token_file:
            value = token_file.read().strip()
    else:
        value = secrets.token_urlsafe(32)
        with os.fdopen(fd, "w", encoding="ascii") as token_file:
            token_file.write(value)

    if len(value) < 32:
        raise RuntimeError("token file must contain at least 32 characters")
    return value
