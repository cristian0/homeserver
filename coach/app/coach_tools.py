"""The coach's MCP tools as plain functions ``(conn, ..., now) -> str``, free of any transport.

Each tool answers with Italian text: a result starts with ``generated_header(now)``,
a refused input with ``Errore: `` and a fixed message (or the validator's
``$.campo: messaggio`` lines). Nothing raises: unreadable data becomes a fixed
message, never a traceback nor the submitted text. ``now`` is always the
server's ``utc_now_iso()``, never a time sent by the client. The only write is
``proponi_scheda``, which stores a pending proposal; sessions are never touched.
"""

from datetime import date
import functools
import logging
import re

from .coach_text import (
    STATUS_LABELS, compact_line, generated_header, journal_lines, local_date, prefixed_text, session_date,
)
from .db import read_transaction
from .plan_validation import PlanValidationError, parse_plan_input, validate_plan
from .summary import session_detail_text
from .workflow import (
    build_state_text, create_proposal, get_session, import_offer, list_journal_entries, list_sessions,
)


logger = logging.getLogger(__name__)

UNAVAILABLE = "Errore: dati non disponibili al momento. Riprova più tardi.\n"
BAD_DATE = "Errore: le date devono essere nel formato AAAA-MM-GG.\n"
BAD_RANGE = "Errore: la data iniziale è successiva alla data finale.\n"
NOT_FOUND = "Errore: Sessione non trovata.\n"
INVALID_PLAN = "Errore: la scheda non è valida."
IMPORTABLE = "Scheda valida e importabile."
NOT_IMPORTABLE = "La scheda non è importabile nello stato attuale."
CONFIRM_IN_APP = "Conferma l'importazione dall'app, pagina Oggi."
SESSION_LINE_FORMAT = (
    "Formato riga: n.<numero> <gg/mm> · <tipo> · <completati>/<totale> · lomb. <immediato>→<mattino> · "
    "sforzo <0-10> · <stato> · id: <id>; \"-\" indica un dato non registrato."
)

_ISO_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class _Refused(Exception):
    """Input the tool refuses; ``text`` is the whole answer."""

    def __init__(self, text):
        super().__init__(text)
        self.text = text


def _tool(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except _Refused as refused:
            return refused.text
        except Exception as error:
            # Only the type: the exception text could carry stored or submitted data.
            logger.error("tool=%s exception=%s", function.__name__, type(error).__name__)
            return UNAVAILABLE
    return wrapper


def _text(lines):
    return "\n".join(lines) + "\n"


# --- dates -----------------------------------------------------------------

def _parse_day(value):
    if value is None or value == "":
        return None
    if type(value) is not str or not _ISO_DATE_RE.fullmatch(value):
        raise _Refused(BAD_DATE)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _Refused(BAD_DATE) from None


def _parse_range(da, a):
    start, end = _parse_day(da), _parse_day(a)
    if start is not None and end is not None and start > end:
        raise _Refused(BAD_RANGE)
    return start, end


def _in_range(day, start, end):
    return (start is None or day >= start) and (end is None or day <= end)


def _range_line(start, end):
    if start is None and end is None:
        return "Intervallo: tutte le date"
    if end is None:
        return f"Intervallo: dal {start:%d/%m/%Y}"
    if start is None:
        return f"Intervallo: fino al {end:%d/%m/%Y}"
    return f"Intervallo: dal {start:%d/%m/%Y} al {end:%d/%m/%Y}"


# --- plans -----------------------------------------------------------------

def _parse_plan(scheda):
    try:
        return validate_plan(parse_plan_input(scheda))
    except PlanValidationError as error:
        raise _Refused(_text([INVALID_PLAN, *(f"- {message}" for message in error.errors)])) from None


def _state_lines(conn, plan):
    """What would happen on import, as the app's preview shows it; empty problems = importable."""
    with read_transaction(conn):
        offer = import_offer(conn, plan)
    lines = []
    current = offer["current"]
    if offer["replace_current"]:
        lines.append(prefixed_text(
            f"La scheda corrente n.{current['plan']['sequence_number']} — ",
            f"{current['plan']['title']} non è mai stata avviata: "
            "all'importazione l'app proporrà all'utente di sostituirla.",
        ))
    elif offer["replace_offer"]:
        lines.append(prefixed_text(
            f"La scheda sostituisce la scheda corrente n.{current['plan']['sequence_number']} — ",
            f"{current['plan']['title']}: l'utente conferma la sostituzione nell'app.",
        ))
    if offer["problems"]:
        lines.append("Problemi per l'importazione:")
        lines.extend(f"- {message}" for message in offer["problems"])
    return lines, offer["problems"]


def _plan_line(prefix, plan):
    return prefixed_text(f"{prefix}n.{plan['sequence_number']} — ", plan["title"])


# --- tools -----------------------------------------------------------------

@_tool
def stato_attuale(conn, now):
    return build_state_text(conn, now)


@_tool
def elenco_sessioni(conn, da, a, now):
    start, end = _parse_range(da, a)
    with read_transaction(conn):
        sessions = list(reversed(list_sessions(conn)))
    lines = []
    for session in sessions:
        day = session_date(session) or local_date(session["imported_at"])
        if not _in_range(day, start, end):
            continue
        lines.append(f"- {compact_line(session)} · {STATUS_LABELS[session['status']]} · id: {session['id']}")
        lines.append(prefixed_text("  Titolo: ", session["plan"]["title"], "    "))
    return _text([
        generated_header(now),
        "ELENCO SESSIONI",
        _range_line(start, end),
        "Data della sessione: prima spunta o feedback; per le sessioni mai avviate, data di importazione.",
        SESSION_LINE_FORMAT,
        "",
        *(lines or ["nessuna sessione nell'intervallo"]),
    ])


@_tool
def dettaglio_sessione(conn, session_id, now):
    if type(session_id) is not str:
        raise _Refused(NOT_FOUND)
    session = get_session(conn, session_id)
    if session is None:
        raise _Refused(NOT_FOUND)
    return session_detail_text(session, now)


@_tool
def diario(conn, da, a, now):
    start, end = _parse_range(da, a)
    entries = [
        entry for entry in list_journal_entries(conn)
        if _in_range(date.fromisoformat(entry["entry_date"]), start, end)
    ]
    return _text([
        generated_header(now),
        "DIARIO",
        _range_line(start, end),
        "",
        *journal_lines(entries, "%d/%m/%Y"),
    ])


@_tool
def valida_scheda(conn, scheda, now):
    plan = _parse_plan(scheda)
    lines, problems = _state_lines(conn, plan)
    return _text([
        generated_header(now),
        "VALIDAZIONE SCHEDA",
        _plan_line("Scheda: ", plan),
        *lines,
        NOT_IMPORTABLE if problems else IMPORTABLE,
    ])


@_tool
def proponi_scheda(conn, scheda, now):
    plan = _parse_plan(scheda)
    proposal = create_proposal(conn, plan, now)
    lines, _problems = _state_lines(conn, proposal["plan"])
    return _text([
        generated_header(now),
        _plan_line("Proposta inviata: ", proposal["plan"]),
        *lines,
        CONFIRM_IN_APP,
    ])
