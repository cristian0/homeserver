"""Strict parsing and validation for coach-plan JSON v1."""

import json
import re
from urllib.parse import parse_qsl, urlsplit


FENCED_JSON = re.compile(
    r"\A\x60{3}json[ \t]*\r?\n(?P<body>[\s\S]*?)\r?\n\x60{3}[ \t]*\Z"
)
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
YOUTUBE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{11}\Z")

ROOT_REQUIRED_KEYS = (
    "schema_version",
    "session_id",
    "sequence_number",
    "title",
    "activity_type",
    "estimated_minutes",
    "pre_operational",
    "session_notes",
    "sections",
)
ROOT_OPTIONAL_KEYS = ("replaces_session_id",)
SECTION_KEYS = ("title", "items")
ITEM_REQUIRED_KEYS = ("id", "name", "dose", "cue")
ITEM_OPTIONAL_KEYS = (
    "video_url",
    "video_label",
    "alternate_video_url",
    "video_note",
)
ACTIVITY_TYPES = frozenset({"complete", "mobility", "walk", "rest", "combined"})
ALLOWED_VIDEO_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "youtu.be",
        "functionalmovement.com",
        "www.functionalmovement.com",
    }
)
YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "youtu.be"})
FUNCTIONAL_MOVEMENT_HOSTS = frozenset(
    {"functionalmovement.com", "www.functionalmovement.com"}
)


class PlanValidationError(ValueError):
    """Validation error safe to display to the user."""

    def __init__(self, errors):
        self.errors = tuple(errors)
        super().__init__(self.errors[0] if self.errors else "$: piano non valido")


class _DuplicateKeyError(ValueError):
    pass


def _reject_constant(value):
    raise ValueError(f"costante JSON non consentita: {value}")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"chiave JSON duplicata: {key}")
        result[key] = value
    return result


def parse_plan_input(raw):
    """Parse raw or exactly fenced JSON without accepting JSON extensions."""
    if not isinstance(raw, str):
        raise PlanValidationError(("$: l'input deve essere testo JSON",))

    content = raw.strip()
    if content.startswith("```"):
        match = FENCED_JSON.fullmatch(content)
        if match is None:
            raise PlanValidationError(("$: il blocco JSON recintato non è nel formato ammesso",))
        content = match.group("body")

    if len(content.encode("utf-8")) > 65536:
        raise PlanValidationError(("$: il blocco JSON supera 64 KiB",))

    try:
        return json.loads(
            content,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (json.JSONDecodeError, _DuplicateKeyError, RecursionError, ValueError):
        raise PlanValidationError(("$: JSON non valido",)) from None


def _string_error(value, minimum, maximum):
    if not isinstance(value, str):
        return "deve essere una stringa"
    if not minimum <= len(value) <= maximum:
        return f"deve contenere da {minimum} a {maximum} caratteri"
    return None


def _add_unknown_keys(errors, value, allowed, path):
    if type(value) is not dict:
        return
    for key in sorted(value.keys(), key=lambda candidate: str(candidate)):
        if key not in allowed:
            errors.append(f"{path}.{key}: chiave non consentita")


def _add_missing_keys(errors, value, required, path):
    if type(value) is not dict:
        return
    for key in required:
        if key not in value:
            errors.append(f"{path}.{key}: campo obbligatorio mancante")


def _url_details(value):
    """Return (reason, YouTube id or None) for an imported video URL."""
    if not isinstance(value, str):
        return "deve essere una stringa", None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "URL non valido", None

    if parsed.scheme != "https":
        return "deve usare HTTPS", None
    if not parsed.netloc or parsed.username is not None or parsed.password is not None:
        return "non deve contenere credenziali", None
    if ":" in parsed.netloc:
        return "non deve contenere una porta esplicita", None
    try:
        port = parsed.port
    except ValueError:
        return "non deve contenere una porta esplicita", None
    if port is not None:
        return "non deve contenere una porta esplicita", None
    if "#" in value:
        return "non deve contenere frammenti", None

    host = parsed.hostname
    if host not in ALLOWED_VIDEO_HOSTS:
        return "dominio non consentito", None
    if host in FUNCTIONAL_MOVEMENT_HOSTS:
        return None, None

    if host in {"youtube.com", "www.youtube.com"}:
        parameters = parse_qsl(parsed.query, keep_blank_values=True)
        if parsed.path != "/watch" or len(parameters) != 1 or parameters[0][0] != "v":
            return "deve indicare una pagina video YouTube", None
        video_id = parameters[0][1]
    else:
        if parsed.query or not parsed.path.startswith("/") or parsed.path.count("/") != 1:
            return "deve indicare un link breve YouTube", None
        video_id = parsed.path[1:]

    if not YOUTUBE_ID_PATTERN.fullmatch(video_id):
        return "identificatore YouTube non valido", None
    return None, video_id


def _validate_video_url(errors, value, path):
    reason, _ = _url_details(value)
    if reason is not None:
        errors.append(f"{path}: {reason}")


def _validate_item(errors, item, path, seen_ids):
    if type(item) is not dict:
        errors.append(f"{path}: deve essere un oggetto")
        return

    allowed = frozenset(ITEM_REQUIRED_KEYS + ITEM_OPTIONAL_KEYS)
    _add_missing_keys(errors, item, ITEM_REQUIRED_KEYS, path)
    _add_unknown_keys(errors, item, allowed, path)

    for key, maximum in (("id", 64), ("name", 120), ("dose", 120), ("cue", 400)):
        if key in item:
            reason = _string_error(item[key], 1, maximum)
            if reason:
                errors.append(f"{path}.{key}: {reason}")

    identifier = item.get("id")
    if isinstance(identifier, str) and not ID_PATTERN.fullmatch(identifier):
        errors.append(f"{path}.id: deve rispettare il formato dell'identificatore")
    if isinstance(identifier, str) and ID_PATTERN.fullmatch(identifier):
        if identifier in seen_ids:
            errors.append(f"{path}.id: identificatore duplicato")
        else:
            seen_ids.add(identifier)

    has_video_url = "video_url" in item
    for key, maximum in (("video_label", 80), ("video_note", 400)):
        if key in item:
            reason = _string_error(item[key], 1, maximum)
            if reason:
                errors.append(f"{path}.{key}: {reason}")
            if not has_video_url:
                errors.append(f"{path}.{key}: ammesso solo insieme a video_url")
    if "alternate_video_url" in item:
        if not has_video_url:
            errors.append(f"{path}.alternate_video_url: ammesso solo insieme a video_url")
        _validate_video_url(errors, item["alternate_video_url"], f"{path}.alternate_video_url")
    if has_video_url:
        _validate_video_url(errors, item["video_url"], f"{path}.video_url")


def _validate_section(errors, section, path, seen_ids):
    if type(section) is not dict:
        errors.append(f"{path}: deve essere un oggetto")
        return 0
    _add_missing_keys(errors, section, SECTION_KEYS, path)
    _add_unknown_keys(errors, section, frozenset(SECTION_KEYS), path)

    if "title" in section:
        reason = _string_error(section["title"], 1, 80)
        if reason:
            errors.append(f"{path}.title: {reason}")

    items = section.get("items")
    if type(items) is not list:
        errors.append(f"{path}.items: deve essere un array")
        return 0
    if not 1 <= len(items) <= 30:
        errors.append(f"{path}.items: deve contenere da 1 a 30 elementi")
    for item_index, item in enumerate(items):
        _validate_item(errors, item, f"{path}.items[{item_index}]", seen_ids)
    return len(items)


def validate_plan(plan):
    """Validate a plan dictionary and return a detached canonical JSON copy."""
    errors = []
    if type(plan) is not dict:
        raise PlanValidationError(("$: il piano deve essere un oggetto JSON",))

    root_allowed = frozenset(ROOT_REQUIRED_KEYS + ROOT_OPTIONAL_KEYS)
    _add_missing_keys(errors, plan, ROOT_REQUIRED_KEYS, "$")
    _add_unknown_keys(errors, plan, root_allowed, "$")

    if "schema_version" in plan:
        if type(plan["schema_version"]) is not int or plan["schema_version"] != 1:
            errors.append("$.schema_version: deve essere l'intero 1")
    for key in ("session_id", "replaces_session_id"):
        if key in plan:
            reason = _string_error(plan[key], 1, 64)
            if reason:
                errors.append(f"$.{key}: {reason}")
            elif not ID_PATTERN.fullmatch(plan[key]):
                errors.append(f"$.{key}: deve rispettare il formato dell'identificatore")
    if "sequence_number" in plan:
        if type(plan["sequence_number"]) is not int or plan["sequence_number"] < 1:
            errors.append("$.sequence_number: deve essere un intero maggiore o uguale a 1")
    if "title" in plan:
        reason = _string_error(plan["title"], 1, 120)
        if reason:
            errors.append(f"$.title: {reason}")
    if "activity_type" in plan:
        if not isinstance(plan["activity_type"], str) or plan["activity_type"] not in ACTIVITY_TYPES:
            errors.append("$.activity_type: tipo di attività non consentito")
    if "estimated_minutes" in plan:
        if type(plan["estimated_minutes"]) is not int or not 0 <= plan["estimated_minutes"] <= 180:
            errors.append("$.estimated_minutes: deve essere un intero da 0 a 180")
    if "pre_operational" in plan and type(plan["pre_operational"]) is not bool:
        errors.append("$.pre_operational: deve essere booleano")

    notes = plan.get("session_notes")
    if type(notes) is not list:
        errors.append("$.session_notes: deve essere un array")
    else:
        if not 0 <= len(notes) <= 10:
            errors.append("$.session_notes: deve contenere da 0 a 10 note")
        for index, note in enumerate(notes):
            reason = _string_error(note, 1, 200)
            if reason:
                errors.append(f"$.session_notes[{index}]: {reason}")

    sections = plan.get("sections")
    if type(sections) is not list:
        errors.append("$.sections: deve essere un array")
    else:
        if not 0 <= len(sections) <= 8:
            errors.append("$.sections: deve contenere da 0 a 8 sezioni")
        if not sections and plan.get("activity_type") != "rest":
            errors.append("$.sections: può essere vuoto soltanto per activity_type rest")
        seen_ids = set()
        item_count = 0
        for section_index, section in enumerate(sections):
            item_count += _validate_section(errors, section, f"$.sections[{section_index}]", seen_ids)
        if item_count > 30:
            errors.append("$.sections: la sessione non può contenere più di 30 elementi")

    if errors:
        raise PlanValidationError(errors)
    return json.loads(json.dumps(plan, ensure_ascii=False, allow_nan=False))


def youtube_embed_url(url):
    """Return the privacy-enhanced embed URL for an accepted YouTube URL."""
    reason, video_id = _url_details(url)
    if reason is not None:
        raise PlanValidationError((f"$.video_url: {reason}",))
    if video_id is None:
        return None
    return f"https://www.youtube-nocookie.com/embed/{video_id}"


def plan_item_ids(plan):
    """Return item identifiers in their section and item rendering order."""
    return [
        item["id"]
        for section in plan["sections"]
        for item in section["items"]
    ]
