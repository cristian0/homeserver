"""Pure plain-text helpers for the coach, built from sessions and notes already read.

Everything here is deterministic: the same input always gives the same text.
Timestamps are stored in UTC (``...Z``) and shown in Europe/Rome.
"""

from datetime import date, datetime, timedelta

from zoneinfo import ZoneInfo

from .plan_validation import plan_item_ids


ROME = ZoneInfo("Europe/Rome")
MAX_PLAUSIBLE_MINUTES = 180
RECENT_LIMIT = 5

ACTIVITY_LABELS = {
    "complete": "completa",
    "mobility": "mobilità",
    "walk": "camminata",
    "rest": "riposo",
    "combined": "combinata",
}
STATUS_LABELS = {
    "planned": "da fare", "immediate_done": "feedback immediato inserito",
    "complete": "conclusa", "superseded": "sostituita",
}
YELLOW_FLAG_LABELS = {
    "local_discomfort_more_than_usual": "Fastidio locale più del solito",
    "stiffness_still_present": "Rigidità ancora presente",
}
RED_FLAG_LABELS = {
    "radiating_pain": "Dolore irradiato",
    "tingling_or_numbness": "Formicolio o intorpidimento",
    "weakness": "Debolezza",
    "altered_gait": "Alterazione della camminata",
    "dizziness": "Capogiri",
    "chest_pain": "Dolore al petto",
    "unusual_breathlessness": "Fiato corto insolito",
}
EXERCISE_RATING_LABELS = {
    "easy": "Troppo facile",
    "right": "Giusto",
    "hard": "Troppo impegnativo",
}
FINALIZE_STEP = "conclusione con Copia feedback per il coach"


# --- time ------------------------------------------------------------------

def _parse_utc(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def format_local(ts):
    """``dd/mm/YYYY HH:MM`` in Europe/Rome for a UTC ISO 8601 timestamp."""
    return _parse_utc(ts).astimezone(ROME).strftime("%d/%m/%Y %H:%M")


def local_date(ts):
    return _parse_utc(ts).astimezone(ROME).date()


def local_today(now):
    """Europe/Rome calendar date (YYYY-MM-DD) of a UTC ISO 8601 timestamp."""
    return local_date(now).isoformat()


def generated_header(now):
    return f"Generato il {format_local(now)}"


def session_timestamp(session):
    """When the session happened: first tick, else immediate feedback, else completion."""
    for key in ("started_at", "immediate_saved_at", "completed_at"):
        if session.get(key) is not None:
            return session[key]
    return None


def session_date(session):
    timestamp = session_timestamp(session)
    return local_date(timestamp) if timestamp is not None else None


def duration_text(session):
    """Ticks-to-feedback time; a feedback saved without ticks has start == end."""
    if session["plan"]["activity_type"] == "rest":
        return "non applicabile"
    start, end = session.get("started_at"), session.get("immediate_saved_at")
    if start is None or end is None:
        return "non registrata"
    seconds = (_parse_utc(end) - _parse_utc(start)).total_seconds()
    if seconds == 0:
        return "non stimabile"
    minutes = int((seconds + 30) // 60) if seconds >= 0 else -1
    if minutes < 0 or minutes > MAX_PLAUSIBLE_MINUTES:
        return "non stimabile"
    return f"circa {minutes} min"


def days_between(prev, session):
    if prev is None:
        return None
    first, second = session_date(prev), session_date(session)
    if first is None or second is None:
        return None
    return (second - first).days


def _day_month(value):
    return value.strftime("%d/%m") if value is not None else "-"


def _entry_date(entry):
    return date.fromisoformat(entry["entry_date"])


# --- text ------------------------------------------------------------------

def normalise_text(value):
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(character if character in {"\n", "\t"} or ord(character) >= 32 else " " for character in value)
    return value.strip()


def prefixed_text(prefix, value, indent="  "):
    text = normalise_text(value)
    first, *continuations = text.split("\n")
    return "\n".join([f"{prefix}{first}", *(f"{indent}{line}" for line in continuations)])


def text_field(label, value, empty, indent=""):
    text = normalise_text(value)
    if not text:
        return f"{indent}{label}: {empty}"
    return "\n".join([f"{indent}{label}:", *(f"{indent}  {line}" for line in text.split("\n"))])


def selected_flags(flags, labels):
    selected = [label for key, label in labels.items() if flags.get(key) is True]
    return "; ".join(selected) if selected else "nessuno"


def effort_text(session):
    """Perceived effort of the immediate feedback; v1 feedback never recorded it."""
    feedback = session.get("immediate_feedback")
    if feedback is None or "perceived_effort" not in feedback:
        return "non registrato"
    if feedback["perceived_effort"] is None:
        return "non applicabile"
    return f"{feedback['perceived_effort']}/10"


def exercise_comment_lines(plan, feedback, indent=""):
    """Only the exercises that received a rating or a note, in plan order."""
    comments = (feedback or {}).get("exercise_feedback") or {}
    lines = []
    for section in plan["sections"]:
        for item in section["items"]:
            entry = comments.get(item["id"])
            if not entry:
                continue
            parts = []
            if "rating" in entry:
                parts.append(EXERCISE_RATING_LABELS[entry["rating"]])
            if "note" in entry:
                parts.append(entry["note"])
            lines.append(prefixed_text(f"{indent}- ", f"{item['name']}: {' — '.join(parts)}", indent + "  "))
    if not lines:
        return []
    return [f"{indent}Commenti per esercizio:", *lines]


def journal_lines(journal, date_format="%d/%m"):
    """Notes in calendar order (then by creation), one ``- <data>: testo`` each."""
    if not journal:
        return ["nessuna nota"]
    ordered = sorted(journal, key=lambda entry: (entry["entry_date"], entry["created_at"], entry["id"]))
    return [
        prefixed_text(f"- {_entry_date(entry).strftime(date_format)}: ", entry["text"])
        for entry in ordered
    ]


def compact_line(session):
    plan = session["plan"]
    immediate = session.get("immediate_feedback")
    morning = session.get("next_morning_feedback")
    effort = immediate.get("perceived_effort") if immediate is not None else None
    return " · ".join([
        f"n.{plan['sequence_number']} {_day_month(session_date(session))}",
        ACTIVITY_LABELS[plan["activity_type"]],
        f"{len(session['completion'])}/{len(plan_item_ids(plan))}",
        "lomb. {}→{}".format(
            immediate["lumbar_pain"] if immediate is not None else "-",
            morning["lumbar_pain"] if morning is not None else "-",
        ),
        f"sforzo {effort if effort is not None else '-'}",
    ])


def previous_reference(prev, days):
    """``N (n. X, gg/mm)`` for a previous complete session ``days`` local days ago."""
    reference = f"n. {prev['plan']['sequence_number']}"
    prev_date = session_date(prev)
    if prev_date is not None:
        reference += f", {_day_month(prev_date)}"
    return f"{days if days is not None else 'non registrato'} ({reference})"


# --- state -----------------------------------------------------------------

def _missing_steps(current):
    if current["pre_operational"]:
        return ["sostituire la scheda pre-operativa con una scheda nuova"]
    steps = []
    if current["status"] == "planned":
        total = len(plan_item_ids(current["plan"]))
        if total and len(current["completion"]) < total:
            steps.append("esercizi")
        steps.append("feedback immediato")
    if current.get("next_morning_feedback") is None:
        steps.append("controllo del mattino")
    steps.append(FINALIZE_STEP)
    return steps


def _next_step(current, now):
    """What the user can do next, and when: the morning check waits for the day after."""
    if current["pre_operational"]:
        return "sostituire la scheda pre-operativa con una scheda nuova."
    if current["status"] == "planned":
        return "eseguire la sessione e salvare il feedback immediato."
    if current.get("next_morning_feedback") is not None:
        return "concludere con Copia feedback per il coach per ottenere il riepilogo."
    day = session_date(current)
    morning_after = day + timedelta(days=1) if day is not None else None
    if morning_after is not None and local_date(now) < morning_after:
        return (f"controllo del mattino, da compilare il mattino del {_day_month(morning_after)}. "
                "Fino ad allora il riepilogo non è disponibile.")
    return "controllo del mattino, da compilare ora; poi concludere con Copia feedback per il coach."


def _current_lines(current, last, now):
    lines = ["SESSIONE CORRENTE"]
    if current is None:
        lines.append("Nessuna sessione corrente: serve una nuova scheda.")
    else:
        plan = current["plan"]
        lines.extend([
            prefixed_text(f"Sessione: {plan['sequence_number']} — ", plan["title"]),
            f"ID: {current['id']}",
            f"Tipo: {ACTIVITY_LABELS[plan['activity_type']]}",
            f"Stato: {STATUS_LABELS[current['status']]}",
            f"Pre-operativa: {'sì' if current['pre_operational'] else 'no'}",
            f"Esercizi spuntati: {len(current['completion'])}/{len(plan_item_ids(plan))}",
            f"Manca: {', '.join(_missing_steps(current))}",
            f"Prossimo passo: {_next_step(current, now)}",
        ])
    if last is None:
        lines.append("Giorni dall'ultima sessione conclusa: nessuna sessione conclusa")
    else:
        last_date = session_date(last)
        days = (local_date(now) - last_date).days if last_date is not None else None
        lines.append(f"Giorni dall'ultima sessione conclusa: {previous_reference(last, days)}")
    return lines


def _proposal_lines(proposal):
    lines = ["PROPOSTA IN ATTESA"]
    if proposal is None:
        return lines + ["nessuna"]
    plan = proposal["plan"]
    return lines + [prefixed_text(
        f"n.{plan['sequence_number']} — ",
        f"{plan['title']} (inviata il {format_local(proposal['created_at'])})",
    )]


def state_text(current, completed_desc, journal, pending_proposal, now):
    """Live state for the coach: current session, recent history, diary, proposal."""
    last = completed_desc[0] if completed_desc else None
    recent = [f"- {compact_line(item)}" for item in completed_desc[:RECENT_LIMIT]]
    lines = [
        generated_header(now),
        "STATO PER IL COACH",
        "",
        *_current_lines(current, last, now),
        "",
        f"ULTIME SESSIONI CONCLUSE (ultime {RECENT_LIMIT})",
        *(recent or ["nessuna sessione conclusa"]),
        "",
        "DIARIO DALL'ULTIMA SESSIONE CONCLUSA",
        *journal_lines(journal),
        "",
        *_proposal_lines(pending_proposal),
    ]
    return "\n".join(lines) + "\n"


# --- pack ------------------------------------------------------------------

def _pack_session_lines(session, previous_complete):
    plan = session["plan"]
    immediate = session.get("immediate_feedback")
    morning = session.get("next_morning_feedback")
    lines = [
        f"- {compact_line(session)}",
        prefixed_text("  Titolo: ", plan["title"], "    "),
        f"  Stato: {STATUS_LABELS[session['status']]}",
    ]
    timestamp = session_timestamp(session)
    lines.append(f"  Data: {format_local(timestamp) if timestamp is not None else 'non registrata'}")
    lines.append(f"  Durata: {duration_text(session)}")
    if session["status"] == "complete" and previous_complete is not None:
        days = days_between(previous_complete, session)
        lines.append(f"  Giorni dalla precedente: {days if days is not None else 'non registrato'}")
    if immediate is not None:
        lines.extend([
            f"  Sforzo percepito: {effort_text(session)}",
            f"  Segnali gialli (immediato): {selected_flags(immediate['yellow_flags'], YELLOW_FLAG_LABELS)}",
            f"  Segnali rossi (immediato): {selected_flags(immediate['red_flags'], RED_FLAG_LABELS)}",
        ])
        if "difficulties" in immediate:
            lines.append(text_field("Difficoltà", immediate["difficulties"], "nessuna", indent="  "))
        else:
            lines.append("  Difficoltà: non registrato")
        lines.extend(exercise_comment_lines(plan, immediate, indent="  "))
    if morning is not None:
        lines.extend([
            f"  Ritorno al livello abituale: {'sì' if morning['back_to_baseline'] else 'no'}",
            f"  Segnali gialli (mattino): {selected_flags(morning['yellow_flags'], YELLOW_FLAG_LABELS)}",
            f"  Segnali rossi (mattino): {selected_flags(morning['red_flags'], RED_FLAG_LABELS)}",
        ])
    return lines


def pack_text(sessions_asc, journal, now):
    """Whole compact history plus the whole diary, for the coach's project files."""
    session_lines = []
    previous_complete = None
    for session in sessions_asc:
        session_lines.extend(_pack_session_lines(session, previous_complete))
        if session["status"] == "complete":
            previous_complete = session
    lines = [
        generated_header(now),
        "",
        "# Pacchetto per il coach",
        "",
        "Formato riga: n.<numero> <gg/mm> · <tipo> · <completati>/<totale> · "
        "lomb. <immediato>→<mattino> · sforzo <0-10>; \"-\" indica un dato non registrato.",
        "",
        f"## Sessioni ({len(sessions_asc)})",
        "",
        *(session_lines or ["nessuna sessione registrata"]),
        "",
        f"## Diario ({len(journal)})",
        "",
        *journal_lines(journal, "%d/%m/%Y"),
    ]
    return "\n".join(lines) + "\n"
