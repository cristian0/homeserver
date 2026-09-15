"""Strict validation and form adaptation for the two feedback payloads."""

from copy import deepcopy


RED_FLAG_KEYS = (
    "radiating_pain",
    "tingling_or_numbness",
    "weakness",
    "altered_gait",
    "dizziness",
    "chest_pain",
    "unusual_breathlessness",
)
IMMEDIATE_KEYS = (
    "lumbar_pain",
    "stiffness",
    "fatigue",
    "leg_symptoms",
    "leg_details",
    "yellow_flags",
    "red_flags",
    "additional_activity",
    "notes",
)
MORNING_KEYS = (
    "lumbar_pain",
    "stiffness",
    "residual_fatigue",
    "leg_symptoms",
    "leg_details",
    "yellow_flags",
    "red_flags",
    "back_to_baseline",
    "discomfort_onset",
    "approximate_duration",
    "notes",
)
IMMEDIATE_YELLOW_KEYS = ("local_discomfort_more_than_usual",)
MORNING_YELLOW_KEYS = (
    "local_discomfort_more_than_usual",
    "stiffness_still_present",
)
ONSET_VALUES = frozenset(
    {"none", "during", "within_2h", "later_same_day", "overnight", "next_morning", "unknown"}
)
DURATION_VALUES = frozenset(
    {"none", "under_1h", "1_to_4h", "half_day", "full_day", "over_1day", "ongoing", "unknown"}
)


class FeedbackValidationError(ValueError):
    """Validation error safe to display to the user."""

    def __init__(self, errors):
        self.errors = tuple(errors)
        super().__init__(self.errors[0] if self.errors else "$: feedback non valido")


def _add_object_keys(errors, value, keys, path):
    if type(value) is not dict:
        errors.append(f"{path}: deve essere un oggetto")
        return False
    for key in keys:
        if key not in value:
            errors.append(f"{path}.{key}: campo obbligatorio mancante")
    for key in sorted(value, key=str):
        if key not in keys:
            errors.append(f"{path}.{key}: chiave non consentita")
    return True


def _validate_boolean(errors, value, path):
    if type(value) is not bool:
        errors.append(f"{path}: deve essere booleano")


def _validate_rating(errors, value, path):
    if type(value) is not int or not 0 <= value <= 10:
        errors.append(f"{path}: deve essere un intero da 0 a 10")


def _validate_text(errors, value, path, maximum, required=False):
    if not isinstance(value, str):
        errors.append(f"{path}: deve essere una stringa")
    elif not ((1 if required else 0) <= len(value) <= maximum):
        minimum = 1 if required else 0
        errors.append(f"{path}: deve contenere da {minimum} a {maximum} caratteri")


def _validate_flags(errors, value, path, keys):
    if not _add_object_keys(errors, value, keys, path):
        return
    for key in keys:
        if key in value:
            _validate_boolean(errors, value[key], f"{path}.{key}")


def _validate_enum(errors, value, path, allowed):
    if type(value) is not str or value not in allowed:
        errors.append(f"{path}: valore non consentito")
        return False
    return True


def _validate_common(errors, data, rating_keys, yellow_keys, root_keys):
    if not _add_object_keys(errors, data, root_keys, "$"):
        return
    for key in rating_keys:
        if key in data:
            _validate_rating(errors, data[key], f"$.{key}")
    if "leg_symptoms" in data:
        _validate_boolean(errors, data["leg_symptoms"], "$.leg_symptoms")
    if "leg_details" in data:
        requires_detail = data.get("leg_symptoms") is True
        _validate_text(errors, data["leg_details"], "$.leg_details", 500, requires_detail)
        if data.get("leg_symptoms") is False and data["leg_details"] != "":
            errors.append("$.leg_details: deve essere vuota se non ci sono sintomi alla gamba")
    if "yellow_flags" in data:
        _validate_flags(errors, data["yellow_flags"], "$.yellow_flags", yellow_keys)
    if "red_flags" in data:
        _validate_flags(errors, data["red_flags"], "$.red_flags", RED_FLAG_KEYS)


def validate_immediate_feedback(data):
    """Validate immediate feedback and return a detached deep copy."""
    errors = []
    _validate_common(
        errors,
        data,
        ("lumbar_pain", "stiffness", "fatigue"),
        IMMEDIATE_YELLOW_KEYS,
        IMMEDIATE_KEYS,
    )
    if type(data) is dict:
        if "additional_activity" in data:
            _validate_text(errors, data["additional_activity"], "$.additional_activity", 1000)
        if "notes" in data:
            _validate_text(errors, data["notes"], "$.notes", 2000)
    if errors:
        raise FeedbackValidationError(errors)
    return deepcopy(data)


def validate_next_morning_feedback(data):
    """Validate next-morning feedback and return a detached deep copy."""
    errors = []
    _validate_common(
        errors,
        data,
        ("lumbar_pain", "stiffness", "residual_fatigue"),
        MORNING_YELLOW_KEYS,
        MORNING_KEYS,
    )
    if type(data) is dict:
        if "back_to_baseline" in data:
            _validate_boolean(errors, data["back_to_baseline"], "$.back_to_baseline")
        onset_valid = (
            _validate_enum(errors, data["discomfort_onset"], "$.discomfort_onset", ONSET_VALUES)
            if "discomfort_onset" in data
            else False
        )
        duration_valid = (
            _validate_enum(
                errors,
                data["approximate_duration"],
                "$.approximate_duration",
                DURATION_VALUES,
            )
            if "approximate_duration" in data
            else False
        )
        if "notes" in data:
            _validate_text(errors, data["notes"], "$.notes", 2000)
        if onset_valid and duration_valid:
            onset = data["discomfort_onset"]
            duration = data["approximate_duration"]
            if onset == "none" and duration != "none":
                errors.append("$.approximate_duration: deve essere none quando non c'è fastidio")
            elif onset != "none" and duration == "none":
                errors.append("$.approximate_duration: non può essere none quando c'è fastidio")
    if errors:
        raise FeedbackValidationError(errors)
    return deepcopy(data)


def _form_value(form, key):
    return form.get(key, "")


def _form_rating(form, key):
    value = _form_value(form, key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _form_radio(form, key):
    value = _form_value(form, key)
    if value == "yes":
        return True
    if value == "no":
        return False
    return value


def _form_checkbox(form, key):
    return key in form


def _form_red_flags(form):
    return {key: _form_checkbox(form, f"red_{key}") for key in RED_FLAG_KEYS}


def immediate_payload_from_form(form):
    """Construct the complete immediate-feedback schema from form data."""
    return {
        "lumbar_pain": _form_rating(form, "lumbar_pain"),
        "stiffness": _form_rating(form, "stiffness"),
        "fatigue": _form_rating(form, "fatigue"),
        "leg_symptoms": _form_radio(form, "leg_symptoms"),
        "leg_details": _form_value(form, "leg_details"),
        "yellow_flags": {
            "local_discomfort_more_than_usual": _form_checkbox(form, "yellow_local_discomfort"),
        },
        "red_flags": _form_red_flags(form),
        "additional_activity": _form_value(form, "additional_activity"),
        "notes": _form_value(form, "notes"),
    }


def next_morning_payload_from_form(form):
    """Construct the complete next-morning-feedback schema from form data."""
    return {
        "lumbar_pain": _form_rating(form, "lumbar_pain"),
        "stiffness": _form_rating(form, "stiffness"),
        "residual_fatigue": _form_rating(form, "residual_fatigue"),
        "leg_symptoms": _form_radio(form, "leg_symptoms"),
        "leg_details": _form_value(form, "leg_details"),
        "yellow_flags": {
            "local_discomfort_more_than_usual": _form_checkbox(form, "yellow_local_discomfort"),
            "stiffness_still_present": _form_checkbox(form, "yellow_stiffness_present"),
        },
        "red_flags": _form_red_flags(form),
        "back_to_baseline": _form_radio(form, "back_to_baseline"),
        "discomfort_onset": _form_value(form, "discomfort_onset"),
        "approximate_duration": _form_value(form, "approximate_duration"),
        "notes": _form_value(form, "notes"),
    }
