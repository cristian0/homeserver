"""Deterministic plain-text session summary for the coach."""


ACTIVITY_LABELS = {
    "complete": "completa",
    "mobility": "mobilità",
    "walk": "camminata",
    "rest": "riposo",
    "combined": "combinata",
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


def _normalise_text(value):
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(character if character in {"\n", "\t"} or ord(character) >= 32 else " " for character in value)
    return value.strip()


def _text_field(label, value, empty):
    text = _normalise_text(value)
    if not text:
        return f"{label}: {empty}"
    return "\n".join([f"{label}:", *(f"  {line}" for line in text.split("\n"))])


def _prefixed_text(prefix, value):
    text = _normalise_text(value)
    first, *continuations = text.split("\n")
    return "\n".join([f"{prefix}{first}", *(f"  {line}" for line in continuations)])


def _selected_flags(flags, labels):
    selected = [label for key, label in labels.items() if flags.get(key) is True]
    return "; ".join(selected) if selected else "nessuno"


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


def _immediate_lines(feedback):
    return [
        "FEEDBACK IMMEDIATO",
        f"Dolore lombare: {feedback['lumbar_pain']}/10",
        f"Rigidità: {feedback['stiffness']}/10",
        f"Fatica: {feedback['fatigue']}/10",
        f"Sintomi alla gamba: {_yes_no(feedback['leg_symptoms'])}",
        _text_field("Dettaglio gamba", feedback["leg_details"], "nessuno"),
        f"Segnali gialli: {_selected_flags(feedback['yellow_flags'], YELLOW_FLAG_LABELS)}",
        f"Segnali rossi: {_selected_flags(feedback['red_flags'], RED_FLAG_LABELS)}",
        _text_field("Altra attività o carichi", feedback["additional_activity"], "nessuno"),
        _text_field("Note", feedback["notes"], "nessuna"),
    ]


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


def build_coach_summary(session):
    """Format a complete decoded session as stable text ending in one newline."""
    plan = session["plan"]
    completion = session["completion"]
    immediate = session["immediate_feedback"]
    morning = session["next_morning_feedback"]
    if immediate is None or morning is None:
        raise ValueError("Entrambi i feedback sono obbligatori per il riepilogo.")

    lines = [
        "FEEDBACK SESSIONE PER IL COACH — v1",
        _prefixed_text(f"Sessione: {plan['sequence_number']} — ", plan["title"]),
        f"ID: {plan['session_id']}",
        f"Tipo: {ACTIVITY_LABELS[plan['activity_type']]}",
        f"Durata stimata: {plan['estimated_minutes']} minuti",
        f"Pre-operativa: {_yes_no(plan['pre_operational'])}",
        "",
        *_exercise_lines(plan, completion),
        "",
        *_immediate_lines(immediate),
        "",
        *_morning_lines(morning),
        "",
        "RICHIESTA AL COACH",
        "Valuta questi dati e restituisci la giornata successiva come JSON conforme allo schema v1 dell'app. Non aumentare o modificare il piano senza considerare anche i segnali riportati.",
    ]
    return "\n".join(lines) + "\n"
