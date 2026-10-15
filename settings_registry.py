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

import json
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

# --- the rest: listed read-only until a later release ---------------------------------------------------------------------
# key|category|type|default (JSON)|scope(,)|applies|managed_by|label|help. Advanced unless bootstrap or connection-managed.
_TAIL = r"""
REVIEW_MAX_CONCURRENT^general^int^16^server^restart^-^Concurrent requests^Most requests the review server handles at once.
REVIEW_STEMS_TTL^general^float^30^server^restart^-^Episode list cache (s)^How long the episode list is reused before the library is walked again.
REVIEW_STEMS_TTL_FACTOR^general^float^20^server^restart^-^Episode list cache factor^Multiplier on the measured walk time that stretches the cache lifetime.
REVIEW_RESTART^general^int^15^container^restart^-^Server restart delay (s)^Wait before the supervisor restarts a review server that exited.
REVIEW_AUTH^general^string^""^server^restart^bootstrap^Authentication mode^Only the value off disables authentication; set in the container environment.
REQUIRE_TOKEN^general^bool^false^server^restart^bootstrap^Refuse to start without auth^When 1 the server refuses to start with authentication off.
REVIEW_TOKEN^general^secret^^server^restart^bootstrap^Review token^Shared review token from the container environment.
REVIEW_ADMIN_TOKEN^general^secret^^server^restart^bootstrap^Admin token^Admin token from the container environment.
REVIEW_ADMIN_TOKEN_FILE^general^string^""^server^restart^bootstrap^Admin token file^File holding the admin token.
REVIEW_USERNAME^general^string^""^server^restart^bootstrap^Initial user name^User name imported as the first admin.
REVIEW_PASSWORD^general^secret^^server^restart^bootstrap^Initial password^Password imported as the first admin.
REVIEW_PASSWORD_FILE^general^string^""^server^restart^bootstrap^Initial password file^File holding the initial password.
CONFIG_DIR^general^string^"/config"^container^restart^bootstrap^Config folder^Where settings, requests and reports live.
APP_DIR^general^string^"/app"^container^restart^bootstrap^App folder^Where the builder code lives in the container.
RUNTIME_ENV_FILE^general^string^""^container^restart^bootstrap^Old runtime file^The pre-0.3.0 runtime.env path; read once by the migration.
EFFECTIVE_ENV_FILE^general^string^""^container^restart^bootstrap^Effective report file^Where the generate loop reports what it runs with.
STOP_FLAG^general^string^"/tmp/dubtitlerr.stop"^container^restart^bootstrap^Soft stop flag^File whose presence asks the loops to stop between units.
PYTHONPATH^general^string^""^container^restart^bootstrap^Python path^Module search path inside the container.
MEDIA_UID^general^int^1000^container^restart^bootstrap^Media user id^Owner id for files the builder writes.
MEDIA_GID^general^int^100^container^restart^bootstrap^Media group id^Group id for files the builder writes.
MEDIA_ROOT^general^string^"/media"^container^restart^bootstrap^Media root^Mount root of the media library.
OUTPUT_ROOT^general^string^""^container^restart^bootstrap^Output root^Redirects writes onto another disk.
ANIME_ROOT^general^string^"/media/Anime Library"^container^restart^bootstrap^Anime library^Folder holding the shows.
MUX_ROOTS^general^path_list^"/data/Media/Anime Library"^container^restart^bootstrap^Mux roots^Library folders the muxer may write in.
MERGE_ROOTS^general^path_list^"/data/Media/Anime Library"^container^restart^bootstrap^Merge roots^Library folders the merge pass walks.
HARDLINK_ROOTS^general^path_list^""^container^restart^bootstrap^Hardlink roots^Folders where hardlinks are followed.
GLOSSARY_DIR^general^string^"/config/glossaries"^container^restart^bootstrap^Glossary folder^Where per-show glossaries live.
MODEL_DIR^general^string^"/subgen/models"^container^restart^bootstrap^Model folder^Where speech models are stored.
DUBTITLERR_TAG^general^string^"latest"^container^restart^bootstrap^Image tag^Compose image tag.
CONFIG_ROOT^general^string^"./dubtitlerr-config"^container^restart^bootstrap^Config mount^Host folder mounted as the config folder.
SUBS_REPO^general^string^""^container^restart^bootstrap^Subtitle repo^Publish tool: local clone of the subtitle repository.
GITHUB_PAT^general^secret^^container^restart^bootstrap^GitHub token^Publish tool credential.
GITHUB_USER^general^string^"x-access-token"^container^restart^bootstrap^GitHub user^Publish tool user name.
GITHUB_WIKI^general^url^""^container^restart^bootstrap^GitHub wiki^Publish tool wiki remote.
FORGEJO_WIKI^general^url^""^container^restart^bootstrap^Forgejo wiki^Publish tool wiki remote.
PUBLISH_APPLY^general^bool^false^container^restart^bootstrap^Publish for real^Publish tool: push instead of a dry run.
SHOWS^general^string^""^container^restart^bootstrap^Publish shows^Publish tool: shows to publish.
DECISIONS_DIR^general^string^"/config/decisions"^server^restart^-^Decisions folder^Where review verdicts are stored.
REQUESTS_DIR^general^string^"/config/requests"^server^restart^-^Requests folder^Where run requests are queued.
SCHEDULE_FILE^general^string^"/config/schedule.json"^server^restart^-^Schedule file^Where the run window is stored.
HEARTBEAT_PATH^general^string^"/config/heartbeat.json"^server^restart^-^Heartbeat file^Where the builder reports progress.
GLOSSARY_LOCK_WAIT^general^float^5^gen,merge,server^next_show^-^Lock wait (s)^How long a background writer waits for a busy glossary.
GLOSSARY_LOCK_WAIT_INTERACTIVE^general^float^600^server^restart^-^Interactive lock wait (s)^How long a person waits for a busy glossary.
REPAIR_PROFILES^general^string^""^server^restart^retired^Repair profiles (retired)^Imported once as Connections; no longer read.
RUNTIME_VERIFY_BACKENDS^general^string^""^server^restart^retired^Allowed verify backends (retired)^No longer read; Connections replace it.
RUNTIME_DECISION_MODELS^general^string^""^server^restart^retired^Allowed decision models (retired)^No longer read; Connections replace it.
FFMPEG_TIMEOUT^transcription^int^1800^gen^next_show^-^ffmpeg timeout (s)^Wall-clock limit for one audio decode.
FFPROBE_TIMEOUT^transcription^int^60^gen^next_show^-^ffprobe timeout (s)^Wall-clock limit for one probe.
WHISPER_AUDIO_FILTER^transcription^string^"highpass=f=80,compand=attacks=0.001:decays=0.2:points=-80/-80|-30/-15|0/-3|20/-3"^gen^next_show^-^Audio filter^ffmpeg filter applied before transcription; empty disables it.
SEASON_PRIORITY_FILE^transcription^string^""^gen^next_show^-^Season priority file^File ordering seasons within a show.
SEASON_START^transcription^int^0^gen^next_show^-^First season^Season the sweep starts from.
DUR_TOL^output^float^2^merge^next_merge_pass^-^Duration tolerance (s)^Largest length difference allowed between video and subtitles.
DUB_SUFFIX^output^string^".eng.dubtitles.srt"^merge^next_merge_pass^-^Sidecar suffix^File suffix of the dubtitle sidecar.
MINE_EXTRACT_TIMEOUT^glossary^float^600^gen^next_show^-^Mining extract timeout (s)^Limit for extracting one embedded track.
MINE_MAX_LOWER_SHARE^glossary^float^0.6^gen^next_show^-^Mining lowercase share^Names mostly written in lowercase are dropped above this share.
MINE_MIN_LOWER_EVIDENCE^glossary^int^3^gen^next_show^-^Mining lowercase evidence^Occurrences needed before the lowercase share applies.
ACQUIRE_CONTEXT_LINES^glossary^int^4^gen^next_show^-^Acquire context lines^Transcript lines quoted per name.
ACQUIRE_DECISION_TAU^glossary^float^0.8^gen^next_show^-^Acquire decision floor^Confidence floor for the decision model during acquisition.
ACQUIRE_GROWTH_MAX^glossary^int^2^gen^next_show^-^Acquire growth limit^Largest growth of a name in words.
ACQUIRE_MIN_COUNT^glossary^int^3^gen^next_show^-^Acquire minimum count^Occurrences needed for an acquired name.
ACQUIRE_MIN_SHARE^glossary^float^0.8^gen^next_show^-^Acquire minimum share^Share of occurrences that must agree.
ACQUIRE_NEAR_MISS_MIN_COUNT^glossary^int^2^gen^next_show^-^Acquire near-miss count^Occurrences needed for a near-miss spelling.
ACQUIRE_NO_CACHE^glossary^bool^false^gen^next_show^-^Acquire without cache^Any value turns the adjudication cache off.
ACQUIRE_TIMEOUT^glossary^int^1800^gen^next_show^-^Acquire timeout (s)^Wall-clock limit for one show's acquisition.
ACQUIRE_UNSEEN_SIM^glossary^float^0.98^gen^next_show^-^Acquire unseen similarity^Similarity needed for a name never seen in the transcript.
ARC_MIN_TITLES^glossary^int^10^gen^next_show^-^Arc minimum titles^Arc titles needed before arc gating applies.
ARC_TAGS_TIMEOUT^glossary^int^600^gen^next_show^-^Arc tag timeout (s)^Wall-clock limit for arc tagging.
VERIFY_COMMON_WORD_ARC_RESCUE^glossary^bool^false^gen^next_show^-^Rescue common words by arc^Let an arc match rescue a common word.
VERIFY_DECISION_BREAKER^glossary^int^5^gen^next_show^-^Decision breaker^Consecutive failures before the decision model is skipped.
VERIFY_DECISION_FALLBACK^glossary^string^"none"^gen^next_show^-^Decision fallback^none or local: what to do when the decision model fails.
VERIFY_DECISION_LOCAL_BACKEND^glossary^string^""^gen^next_show^-^Decision local backend^Local backend used by the fallback.
VERIFY_DECISION_RETRIES^glossary^int^0^gen^next_show^-^Decision retries^Retries per decision request.
VERIFY_DECISION_WORKERS^glossary^int^1^gen^next_show^-^Decision workers^Parallel decision requests.
VERIFY_MAX_TOKENS^glossary^int^512^gen^next_show^-^Verify token budget^Largest reply the verify step asks for.
VERIFY_NO_JOURNAL^glossary^bool^false^gen^next_show^-^Verify without journal^Any value turns the adjudication journal off.
VERIFY_QUEUE_BLOCKED_EXPANSIONS^glossary^bool^true^gen^next_show^-^Queue blocked expansions^Send blocked name expansions to review.
VERIFY_QUEUE_NO_MATCH^glossary^bool^false^gen^next_show^-^Queue unmatched names^Send names with no wiki match to review.
VERIFY_REFUSE_EXIT^glossary^bool^false^gen^next_show^-^Fail on refusal^Exit non-zero when verify refuses to run.
VERIFY_SKIP_COMMON_WORDS^glossary^bool^true^gen^next_show^-^Skip common words^Do not adjudicate ordinary words.
VERIFY_TIMEOUT^glossary^int^1200^gen^next_show^-^Verify timeout (s)^Wall-clock limit for one show's verification.
VERIFY_WORKERS^glossary^int^4^gen^next_show^-^Verify workers^Parallel adjudications.
VERIFY_WRITE_WHOLE_WORD^glossary^bool^true^gen^next_show^-^Write whole words^Only write whole-word glossary changes.
WIKI_ALLOW_HTTP^glossary^bool^false^gen^next_show^-^Allow plain-http wikis^Allow a wiki over http instead of https.
WIKI_CACHE_DIR^glossary^string^"/config/wiki_cache"^gen^next_show^-^Wiki cache folder^Where fetched wiki indexes are cached.
WIKI_CACHE_TTL^glossary^int^2592000^gen^next_show^-^Wiki cache lifetime (s)^How long a cached wiki index is reused.
WIKI_HOST_ALLOW^glossary^string^""^gen^next_show^-^Allowed wiki hosts^Comma-separated extra wiki hosts.
WIKI_HTTP_TIMEOUT^glossary^int^20^gen^next_show^-^Wiki request timeout (s)^Limit for one wiki request.
WORDLIST_PATH^glossary^string^"/usr/share/dict/american-english"^gen,merge^next_show^-^Word list file^Dictionary used to spot ordinary words.
LEN_RATIO_MAX^repair^float^1.5^merge^next_merge_pass^-^Longest repair ratio^Longest allowed repaired line relative to the original.
LEN_RATIO_MIN^repair^float^0.6^merge^next_merge_pass^-^Shortest repair ratio^Shortest allowed repaired line relative to the original.
LOGPROB_MIN^repair^float^-0.4^merge^next_merge_pass^-^Confidence floor^Average log probability below which a line is repaired.
MAX_REF_BORROW^repair^int^3^merge^next_merge_pass^-^Reference borrow limit^Most words a repair may borrow from the reference.
NSP_MAX^repair^float^0.5^merge^next_merge_pass^-^No-speech ceiling^Highest no-speech probability still repaired.
REPAIR_ACCEPT_PUNCT_CASE_ONLY^repair^bool^false^merge^next_merge_pass^-^Accept punctuation-only repairs^Accept repairs that only change punctuation or case.
REPAIR_GUARD_TERMINAL_PUNCT^repair^bool^false^merge^next_merge_pass^-^Guard terminal punctuation^Reject repairs that change the final punctuation.
REPAIR_MAX_CONSECUTIVE_UNREACHABLE^repair^int^5^merge^next_merge_pass^-^Unreachable streak limit^Consecutive unreachable calls before repair stops.
REPAIR_MAX_TOKENS^repair^int^1024^merge^next_merge_pass^-^Repair token budget^Largest reply repair asks for.
REPAIR_OPENAI_RETRIES^repair^int^2^merge^next_merge_pass^-^Hosted retries^Retries per request on a hosted backend.
REPAIR_PHONETIC_MIN^repair^float^0.75^merge^next_merge_pass^-^Phonetic floor^Phonetic similarity needed for a name fix.
REPAIR_REQUEST_DEADLINE^repair^int^300^merge^next_merge_pass^-^Request deadline (s)^Wall-clock limit for one repair request.
REPAIR_RETRY_SLEEP_BUDGET^repair^int^600^merge^next_merge_pass^-^Retry sleep budget (s)^Total back-off time per episode.
REPAIR_TRANSPORT_RETRIES^repair^int^2^merge^next_merge_pass^-^Transport retries^Retries after a network failure.
REPAIR_UNREACHABLE_REFUSE_PCT^repair^int^10^merge^next_merge_pass^-^Unreachable refusal percent^Share of unreachable calls that makes repair refuse the episode.
RESTORE_MAX_TOKENS^repair^int^2048^merge^next_merge_pass^-^Restore token budget^Largest reply punctuation restoration asks for.
RESTORE_MIN_RUN^repair^int^2^merge^next_merge_pass^-^Restore minimum run^Shortest unpunctuated run that is restored.
LLM_TIMEOUT_CONNECT^connections^float^10^gen,merge^next_show^-^LLM connect timeout (s)^Connect timeout for the shared LLM client.
LLM_TIMEOUT_READ^connections^float^120^gen,merge^next_show^-^LLM read timeout (s)^Read timeout for the shared LLM client.
REPAIR_BACKEND^connections^enum^"llamacpp"^merge^next_merge_pass^connections^Repair backend^Derived from the repair Connection.
REPAIR_LLAMACPP_URL^connections^url^"http://127.0.0.1:8090/v1/chat/completions"^merge^next_merge_pass^connections^Repair llama.cpp URL^Derived from the repair Connection.
REPAIR_OPENAI_URL^connections^url^""^merge^next_merge_pass^connections^Repair hosted URL^Derived from the repair Connection.
REPAIR_OPENAI_KEY_ENV^connections^string^""^merge^next_merge_pass^connections^Repair key variable^Name of the variable holding the repair key.
REPAIR_MODEL^connections^string^"qwen3-4b-instruct"^gen,merge^next_merge_pass^connections^Repair model^Derived from the repair Connection.
REPAIR_MODEL_SECONDARY^connections^string^""^merge^next_merge_pass^connections^Repair second model^Second model for repair retries.
REPAIR_EXTRA_BODY^connections^string^""^merge^next_merge_pass^connections^Repair extra body^JSON merged into hosted repair requests.
REPAIR_TIMEOUT_CONNECT^connections^float^10^merge^next_merge_pass^connections^Repair connect timeout (s)^Derived from the repair Connection.
REPAIR_TIMEOUT_READ^connections^float^120^merge^next_merge_pass^connections^Repair read timeout (s)^Derived from the repair Connection.
OLLAMA_URL^connections^url^"http://127.0.0.1:11434/api/generate"^gen,merge^next_merge_pass^connections^Ollama URL^Derived from an Ollama Connection.
RESTORE_BACKEND^connections^string^""^merge^next_merge_pass^connections^Restore backend^Derived from the restore Connection.
RESTORE_MODEL^connections^string^""^merge^next_merge_pass^connections^Restore model^Derived from the restore Connection.
RESTORE_LLAMACPP_URL^connections^url^""^merge^next_merge_pass^connections^Restore llama.cpp URL^Derived from the restore Connection.
VERIFY_BACKEND^connections^enum^""^gen,merge^next_show^connections^Verify backend^Derived from the verify Connection.
VERIFY_MODEL^connections^string^"qwen3:8b"^gen,merge^next_show^connections^Verify model^Derived from the verify Connection.
VERIFY_LLAMACPP_URL^connections^url^""^gen,merge^next_show^connections^Verify llama.cpp URL^Derived from the verify Connection.
VERIFY_OPENAI_URL^connections^url^""^gen,merge^next_show^connections^Verify hosted URL^Derived from the verify Connection.
VERIFY_OPENAI_KEY_ENV^connections^string^""^gen,merge^next_show^connections^Verify key variable^Name of the variable holding the verify key.
VERIFY_OPENAI_EXTRA_BODY^connections^string^""^gen,merge^next_show^connections^Verify extra body^JSON merged into hosted verify requests.
VERIFY_DECISION_MODEL^connections^string^"inception/mercury-decide:free"^gen,merge^next_show^connections^Decision model^Derived from the decision Connection.
VERIFY_DECISION_URL^connections^url^""^gen,merge^next_show^connections^Decision URL^Derived from the decision Connection.
VERIFY_DECISION_KEY_ENV^connections^string^""^gen,merge^next_show^connections^Decision key variable^Name of the variable holding the decision key.
ACQUIRE_BACKEND^connections^enum^""^gen,merge^next_show^connections^Acquire backend^Derived from the acquire Connection.
OPENROUTER_JEV_API_KEY^connections^secret^^gen,merge^next_show^bootstrap^OpenRouter key^Key variable read by name from the container environment.
COMMANDCODE_API_KEY^connections^secret^^gen,merge^next_show^bootstrap^CommandCode key^Key variable read by name from the container environment.
LONGCATAI_API_KEY^connections^secret^^gen,merge^next_show^bootstrap^LongCat key^Key variable read by name from the container environment.
IDLE_CHECK_INTERVAL^schedule^int^60^gen^next_sweep^-^Idle check interval (s)^How often the idle wait looks for requests.
REQUEST_POLL_INTERVAL^schedule^int^60^gen^next_sweep^-^Request poll interval (s)^How often the idle wait looks for run requests.
RESCAN_INTERVAL^schedule^int^21600^gen^next_sweep^-^Rescan interval (s)^Idle time after a full sweep before the next one.
SCHEDULE_CHECK_INTERVAL^schedule^int^60^gen^next_sweep^-^Window check interval (s)^How often a closed window is re-checked.
PLEX_PATH^connect^string^""^gen,merge^next_show^-^Plex path prefix^Path prefix Plex sees for the library.
WATCH_QUEUE_TIMEOUT^connect^int^30^gen^next_sweep^-^Watch queue timeout (s)^Limit for one watch-history request.
TIMING_COMPARE_MIN_CUES^output^int^^container^restart^-^Timing compare minimum cues^Tool only: fewest cues a timing comparison needs.
TIMING_COMPARE_MIN_PLAIN_SHARE^output^float^^container^restart^-^Timing compare plain share^Tool only: smallest plain-dialogue share a timing comparison needs.
"""


def _load_tail():
    for line in _TAIL.strip().splitlines():
        key, category, type_, default, scope, applies, managed, label, help_ = line.split("^", 8)
        managed_by = None if managed == "-" else managed
        _add(
            key,
            category,
            label,
            help_,
            type_,
            json.loads(default) if default else None,
            scope.split(","),
            applies,
            advanced=managed_by != "bootstrap",
            managed_by=managed_by,
        )


_load_tail()

# Enumerations and formats for the connection-managed keys, and the three that an old runtime.env could carry: those stay storable
# (the one-time migration writes them) and resettable, but are changed through Connections, never edited as plain values.
for _key, _values in (
    ("REPAIR_BACKEND", ["llamacpp", "ollama", "openai"]),
    ("VERIFY_BACKEND", ["llamacpp", "ollama", "openai", "decision"]),
    ("ACQUIRE_BACKEND", ["llamacpp", "ollama", "openai", "decision"]),
):
    REGISTRY[_key]["enum"] = _values
for _key in ("REPAIR_MODEL", "VERIFY_DECISION_MODEL"):
    REGISTRY[_key]["pattern"] = MODEL_RE.pattern
    REGISTRY[_key]["pattern_help"] = "must look like qwen3-4b-instruct"
for _key in ("REPAIR_MODEL", "VERIFY_BACKEND", "VERIFY_DECISION_MODEL"):
    REGISTRY[_key]["legacy_override"] = True

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
