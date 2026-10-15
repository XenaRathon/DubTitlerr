# ruff: noqa: E501
"""The settings registry (specs/webui-full-settings, S-1): the single source for validation, the API and the UI.

One entry per setting the pipeline reads from the environment. An entry carries its category, label, help text, type, range,
default, `advanced` flag, when a change `applies`, and its `scope`: the process that reads it (gen: gen_loop.sh and its children;
merge: merge_pass.sh and its children; server: review_server.py; container: container_run.sh). A key read by two processes lists
both scopes. `first_wave` entries are editable in v0.3.0; the rest are listed read-only. `managed_by` names who owns a key that is
not edited as a plain value: "connections" (derived from a Connection), "bootstrap" (needed before the store can be read) or
"retired" (the code stopped reading it).

Stdlib only and import-cheap: the shell loops import it through review_settings_write.py on every sweep.
"""

import math
import re
import urllib.parse

URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!&*+,=%-]{1,512}")
MODEL_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}")

CATEGORIES = [
    {"id": "general", "label": "General", "summary": "Web server, sign-in and the bootstrap values the container needs first."},
    {"id": "library", "label": "Library", "summary": "Which episodes and languages the builder works on."},
    {"id": "transcription", "label": "Transcription", "summary": "Whisper model, precision and device."},
    {"id": "glossary", "label": "Glossary", "summary": "Name mining, acquisition and wiki verification."},
    {"id": "repair", "label": "Repair", "summary": "How low-confidence lines are repaired and reviewed."},
    {"id": "connections", "label": "Connections", "summary": "The LLM servers each stage talks to."},
    {"id": "output", "label": "Output", "summary": "Merged subtitle styling, review gate and merge pace."},
    {"id": "schedule", "label": "Schedule", "summary": "When the builder runs and what it queues."},
    {"id": "connect", "label": "Connect", "summary": "Plex, WatchState and webhook access."},
]
CATEGORY_IDS = tuple(c["id"] for c in CATEGORIES)
APPLIES = ("next_sweep", "next_show", "next_merge_pass", "next_episode", "restart")
SCOPES = ("gen", "merge", "server", "container")
TYPES = ("bool", "int", "float", "enum", "string", "url", "path_list", "secret")
BOOL_TRUE = ("1", "true", "yes", "on")
BOOL_FALSE = ("0", "false", "no", "off", "dry-run")


class Invalid(ValueError):
    """A value the registry refuses; the message is shown under the field."""


REGISTRY: dict = {}


def _add(
    key, category, label, help, type_, default, scope, applies, *, advanced=False, first_wave=False, managed_by=None, **rules
):
    scope = [scope] if isinstance(scope, str) else list(scope)
    assert key not in REGISTRY, key
    assert category in CATEGORY_IDS and type_ in TYPES and applies in APPLIES and set(scope) <= set(SCOPES), key
    REGISTRY[key] = {
        "key": key,
        "category": category,
        "label": label,
        "help": help,
        "type": type_,
        "default": default,
        "advanced": advanced,
        "applies": applies,
        "scope": scope,
        "first_wave": first_wave,
        "editable": first_wave,
        "secret": type_ == "secret",
        "managed_by": managed_by,
        **rules,
    }


def _wave(key, category, label, help, type_, default, scope, applies, **kw):
    _add(key, category, label, help, type_, default, scope, applies, first_wave=True, **kw)


# --- first wave (editable in v0.3.0) -------------------------------------------------------------------------------------
# fmt: off
_wave('REVIEW_PORT', 'general', 'Web UI port', 'TCP port the review server listens on.', 'int', 8842, 'server', 'restart', min=1, max=65535)
_wave('REVIEW_BIND', 'general', 'Web UI bind address', 'Address the review server binds to; 0.0.0.0 listens on every interface.', 'string', '0.0.0.0', 'server', 'restart', pattern=r"[A-Za-z0-9.:\-\[\]]{1,253}", pattern_help='must be a host name or IP address')
_wave('REQUIRE_ENG', 'library', 'Require English audio', 'Only transcribe episodes that carry an English audio track.', 'bool', True, 'gen', 'next_show')
_wave('SKIP_IF_SRT', 'library', 'Skip finished episodes', 'Skip an episode that already has a dubtitles file; turn off to force a fresh transcription.', 'bool', True, 'gen', 'next_show')
_wave('KEEP_LANGS', 'library', 'Languages kept when muxing', 'Comma-separated language codes kept in the muxed file, besides the original language.', 'string', 'eng,en,dut,nld,nl,und,', 'merge', 'next_merge_pass', pattern=r"[A-Za-z,]{0,128}", pattern_help='use comma-separated language codes')
_wave('SUB_LANGS', 'library', 'Subtitle languages accepted', 'Comma-separated language codes treated as usable embedded subtitles.', 'string', 'eng,en,und,', ['gen', 'merge'], 'next_show', pattern=r"[A-Za-z,]{0,128}", pattern_help='use comma-separated language codes')
_wave('MIN_FREE_GB', 'library', 'Minimum free space (GB)', 'A remux is skipped when the disk has less free space than this.', 'float', 5.0, 'merge', 'next_merge_pass', min=0, max=100000)
_wave('REMOTE_PATH_MAPPINGS', 'library', 'Remote path mappings', 'Maps paths a Sonarr or Radarr webhook reports onto library paths (remote=local pairs).', 'string', '', 'server', 'restart')
_wave('WHISPER_MODEL', 'transcription', 'Whisper model', 'Speech-to-text model; a model missing from the model folder is downloaded at the next show.', 'string', 'large-v3-turbo', 'gen', 'next_show', pattern=r"[A-Za-z0-9][A-Za-z0-9._/\-]{0,127}", pattern_help='must be a model name such as large-v3-turbo')
_wave('COMPUTE_TYPE', 'transcription', 'Compute precision', 'Numeric precision faster-whisper runs at.', 'enum', 'int8', 'gen', 'next_show', enum=['int8', 'int8_float16', 'int8_float32', 'int8_bfloat16', 'int16', 'float16', 'float32', 'bfloat16', 'default', 'auto'])
_wave('WHISPER_BEAM_SIZE', 'transcription', 'Beam size', 'Candidate transcriptions kept at each step; higher is slower and can be more accurate.', 'int', 7, 'gen', 'next_show', min=1, max=20)
_wave('ASR_DEVICE', 'transcription', 'Transcription device', 'Device faster-whisper runs on.', 'enum', 'cuda', 'gen', 'next_show', enum=['cuda', 'cpu', 'auto'])
_wave('ACQUIRE', 'glossary', 'Acquire missing names', 'Fill glossary names from the wiki for shows without an embedded fansub track.', 'bool', True, 'gen', 'next_show')
_wave('ACQUIRE_APPLY', 'glossary', 'Apply acquired names', 'On: acquisition writes the names it finds. Off: it only logs proposals.', 'bool', True, 'gen', 'next_show')
_wave('GLOSSARY_ARC_TAGS', 'glossary', 'Tag glossary arcs', "Fetch each season's story arc titles from the wiki and tag glossary names with them.", 'bool', False, 'gen', 'next_show')
_wave('VERIFY_ARC_GATE', 'glossary', 'Arc gate on verify', "Only accept glossary writes that match the show's stored arc titles.", 'bool', False, 'gen', 'next_show')
_wave('MINE_MIN_COUNT', 'glossary', 'Mining repeat threshold', 'How many times a name must appear before mining adds it.', 'int', 3, 'gen', 'next_show', min=1, max=1000)
_wave('ACQUIRE_MIN_SIM', 'glossary', 'Acquire similarity floor', 'Minimum similarity for an acquired name to count as a match.', 'float', 0.72, 'gen', 'next_show', advanced=True, min=0, max=1)
_wave('VERIFY_DECISION_TAU', 'glossary', 'Decision confidence floor', 'Confidence a decision-model verdict needs before it is trusted.', 'float', 0.5, 'gen', 'next_show', advanced=True, min=0, max=1)
_wave('DECISIONS_APPLY', 'repair', 'Apply stored decisions', 'Use the rulings you already made when repairing.', 'bool', True, 'merge', 'next_merge_pass')
_wave('REPAIR_UNANCHORED', 'repair', 'Unanchored repair', 'Let repair fix lines that no glossary entry anchors; changes many more lines.', 'bool', False, 'merge', 'next_merge_pass')
_wave('RESTORE_PUNCTUATION', 'repair', 'Restore punctuation', 'Run the pass that puts punctuation back into transcribed dialogue.', 'bool', True, 'merge', 'next_merge_pass')
_wave('REPAIR_AUTO_DISMISS_WORDS', 'repair', 'Auto-dismiss word change', 'Word-change size above which a rejected repair is hidden from the review queue.', 'int', 6, 'merge', 'next_merge_pass', min=0, max=1000)
_wave('REPAIR_KEEP_NAME_PARTS', 'repair', 'Keep name parts', 'Stop repair from dropping part of a multi-word name the glossary knows.', 'bool', True, 'merge', 'next_merge_pass')
_wave('REPAIR_EPISODE_DEADLINE', 'repair', 'Episode repair deadline (s)', 'Seconds repair may spend on one episode before giving up; 0 disables the limit.', 'int', 3600, 'merge', 'next_merge_pass', advanced=True, min=0, max=604800)
_wave('DUB_FANSUB_FONT', 'output', 'Match the fansub font', 'Reuse the font the original fansub track asked for on merged signs.', 'bool', True, 'merge', 'next_merge_pass')
_wave('SIGNS_CROSS_TRACK_DEDUP', 'output', 'Drop duplicate signs across tracks', 'Remove a sign that two fansub tracks both carry.', 'bool', True, 'merge', 'next_merge_pass')
_wave('REVIEW_GATE_SHOWS', 'output', 'Shows held for review', 'Colon-separated show folder names whose episodes wait for review before muxing.', 'string', '', 'merge', 'next_merge_pass', pattern=r"[^,]{0,512}", pattern_help='use colon-separated show folder names')
_wave('REVIEW_GATE_STALE_DAYS', 'output', 'Review gate stale after (days)', 'Days after which a held episode only gets a log line; it stays held.', 'float', 7.0, 'merge', 'next_merge_pass', min=0, max=3650)
_wave('MERGE_INTERVAL', 'output', 'Merge interval (s)', 'Seconds between merge passes.', 'int', 600, 'container', 'restart', min=1, max=604800)
_wave('MERGE_WINDOW', 'schedule', 'Merge window', 'Hours in which a merge pass may run, HH:MM-HH:MM; empty means always.', 'string', '', 'container', 'restart', pattern=r"|(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d", pattern_help='use HH:MM-HH:MM or leave empty')
_wave('WATCH_QUEUE_WINDOW_DAYS', 'schedule', 'Watch queue window (days)', 'Queue only shows watched within this many days; empty turns the watch queue off.', 'int', None, 'gen', 'next_sweep', min=1, max=3650)
_wave('WATCH_QUEUE_PIN', 'schedule', 'Always-queued show', 'A show queued however long since it was watched.', 'string', '', 'gen', 'next_sweep')
_wave('PLEX_URL', 'connect', 'Plex URL', 'Address of your Plex server.', 'url', '', ['gen', 'merge'], 'next_show')
_wave('PLEX_TOKEN', 'connect', 'Plex token', 'Token the builder uses to refresh Plex and read watch history.', 'secret', None, ['gen', 'merge'], 'next_show')
_wave('PLEX_SECTION', 'connect', 'Plex library section', 'Plex library section id to refresh.', 'string', '7', ['gen', 'merge'], 'next_show', pattern=r"[A-Za-z0-9_-]{1,32}", pattern_help='must be a section id')
_wave('WATCHSTATE_URL', 'connect', 'WatchState URL', 'Address of your WatchState server.', 'url', '', 'gen', 'next_show')
_wave('WATCHSTATE_API_KEY', 'connect', 'WatchState API key', 'API key for WatchState.', 'secret', None, 'gen', 'next_show')
_wave('WEBHOOK_TOKEN', 'connect', 'Webhook token', 'Secret in the Sonarr and Radarr webhook URL.', 'secret', None, 'server', 'restart')
# Read-only in v0.3.0 (not first wave per binding review fix)
_add('ANIME_ORDER', 'schedule', 'Show order file', 'File listing the shows in the order the builder sweeps them.', 'string', '/config/anime_order.txt', 'gen', 'next_sweep', pattern=r"/[^\x00-\x1f]{0,500}", pattern_help='must be an absolute path')
# fmt: on

# --- reading the registry -------------------------------------------------------------------------------------------------


def public(entry):
    """The schema form of an entry: everything the UI needs, nothing internal."""
    return {k: v for k, v in entry.items() if k != "first_wave"}


def schema():
    return {"categories": [dict(c) for c in CATEGORIES], "settings": [public(e) for e in REGISTRY.values()]}


def keys_for_scope(scope):
    """The registry keys a process of this scope reads. A merge pass also receives the gen keys, as it always has."""
    wanted = {"gen"} if scope == "gen" else {"gen", "merge"} if scope == "merge" else {scope}
    return [key for key, entry in REGISTRY.items() if wanted & set(entry["scope"])]


# --- values ---------------------------------------------------------------------------------------------------------------


def url_problem(url):
    """Why ``url`` may not be stored, or "" when it may: http(s), no spaces or shell characters, no user name or password."""
    if not URL_RE.fullmatch(url):
        return "must be an http(s) URL without spaces, quotes or shell characters"
    parts = urllib.parse.urlsplit(url)
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return "must not contain a user name or password"
    if not parts.hostname:
        return "needs a host"
    return ""


def _in_range(entry, value):
    low, high = entry.get("min"), entry.get("max")
    if low is not None and high is not None and not low <= value <= high:
        raise Invalid(f"must be between {low} and {high}")
    if low is not None and value < low:
        raise Invalid(f"must be at least {low}")
    if high is not None and value > high:
        raise Invalid(f"must be at most {high}")
    return value


def validate(key, value):
    """The canonical typed value for a plain setting, or Invalid. Secrets are never validated here (they are write-only)."""
    entry = REGISTRY.get(key)
    if entry is None:
        raise Invalid("unknown setting")
    kind = entry["type"]
    if kind == "secret":
        raise Invalid("a secret is set through its secret field")
    if kind == "bool":
        if type(value) is not bool:
            raise Invalid("must be true or false")
        return value
    if kind == "int":
        if type(value) is not int:
            raise Invalid("must be a whole number")
        return _in_range(entry, value)
    if kind == "float":
        if type(value) not in (int, float) or not math.isfinite(value):
            raise Invalid("must be a number")
        return _in_range(entry, float(value))
    if kind == "enum":
        if value not in entry["enum"]:
            raise Invalid("must be one of " + ", ".join(entry["enum"]))
        return value
    if not isinstance(value, str):
        raise Invalid("must be text")
    text = value.strip()
    if len(text) > 512 or any(ch in text for ch in "\n\r\x00"):
        raise Invalid("must be one line of at most 512 characters")
    if kind == "url" and text:
        why = url_problem(text)
        if why:
            raise Invalid(why)
    if kind == "path_list" and text and not all(part.startswith("/") for part in text.split(":")):
        raise Invalid("must be absolute paths separated by colons")
    pattern = entry.get("pattern")
    if pattern and not re.fullmatch(pattern, text):
        raise Invalid(entry.get("pattern_help") or "has the wrong format")
    return text


def to_env(value):
    """The environment string for a canonical value: booleans are 1/0, which every consumer's own rule reads correctly."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return ""
    return str(value)


def from_env(key, raw):
    """(value, ok) for a container-environment string. Empty means unset: (None, True). An unparseable string comes back raw
    with ok False, so the page can show what the container really holds."""
    entry = REGISTRY[key]
    text = (raw or "").strip()
    if not text:
        return None, True
    kind = entry["type"]
    try:
        if kind == "bool":
            if text.lower() in BOOL_TRUE:
                return True, True
            if text.lower() in BOOL_FALSE:
                return False, True
            return raw, False
        if kind == "int":
            return int(text), True
        if kind == "float":
            number = float(text)
            return (number, True) if math.isfinite(number) else (raw, False)
        if kind == "enum":
            return (text, True) if text in entry["enum"] else (raw, False)
    except ValueError:
        return raw, False
    return text, True
