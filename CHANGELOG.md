# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/). This file starts at
the public beta. `TRANSCRIBE_VERSION`/`TEXT_VERSION` in `common.py` are the pipeline's own
version history (they say what changed in the _output_, and only a stamp bump puts the fix into
already-processed files); the entries below summarize that history alongside everything else
that shipped since.

## [Unreleased]

### Optional flags (the one list; every default read from the code)

With all of them unset, the defaults decided on 2026-10-09 apply (below); setting a variable to its old value restores the old behaviour. Variables are read per call unless noted.

| Name                              | Default                                                                                  | What it does                                                                                                                                                 | Recommended                         | Caution                                                                                                                                                                                                                                                     |
| --------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VERIFY_BACKEND`                  | unset: follows `REPAIR_BACKEND`                                                          | Backend of the glossary stages: `llamacpp`, `ollama`, `openai` or `decision`                                                                                 | `decision` for verify               | Unset, it inherits only `llamacpp`/`ollama` (and `ollama` when `REPAIR_BACKEND` is unset); with `REPAIR_BACKEND=openai` (or any other value) the stage is REFUSED until `VERIFY_BACKEND` is set; acquire does NOT follow `decision` (see `ACQUIRE_BACKEND`) |
| `ACQUIRE_BACKEND`                 | unset: follows `VERIFY_BACKEND`, but the LOCAL backend when that is `decision`           | Backend of acquire's LLM calls (term pick and pair merge): `llamacpp`, `ollama`, `openai` or `decision`                                                      | unset (local)                       | `decision` opts acquire into the decision model (47% against the local model's 72% on the blind acquire pairs); hosted choices need the same URL/key/model as verify and print the same egress notice; the report says `backend`                            |
| `VERIFY_DECISION_MODEL`           | `inception/mercury-decide:free`                                                          | Decision model for verify, and for acquire only with `ACQUIRE_BACKEND=decision`                                                                              | `typesafe/jev`                      | Span models are refused; Jev (the 2026-10-08 lock-in) is paid and needs `COMMANDCODE_API_KEY`                                                                                                                                                               |
| `VERIFY_DECISION_URL`             | the provider's endpoint                                                                  | Override the decision endpoint                                                                                                                               | unset                               | https on the provider's host; loopback is also accepted                                                                                                                                                                                                     |
| `VERIFY_DECISION_KEY_ENV`         | `OPENROUTER_JEV_API_KEY` (OpenRouter models), `COMMANDCODE_API_KEY` (CommandCode models) | NAME of the env var that holds the key                                                                                                                       | default names                       | A name, never the key itself                                                                                                                                                                                                                                |
| `VERIFY_DECISION_TAU`             | `0.5` (0 to 1)                                                                           | Confidence at or above which a pick is `high` and may be written                                                                                             | default                             | Lower writes more                                                                                                                                                                                                                                           |
| `ACQUIRE_DECISION_TAU`            | `0.8` (0.5 to 1)                                                                         | Same, for acquire's same-entity question                                                                                                                     | default                             |                                                                                                                                                                                                                                                             |
| `VERIFY_DECISION_FALLBACK`        | `none`                                                                                   | `none`: a failed call leaves the term pending; `local`: the local model decides                                                                              | `none`                              | `local` sends terms to the local model after a provider outage                                                                                                                                                                                              |
| `VERIFY_DECISION_LOCAL_BACKEND`   | `REPAIR_BACKEND` if `llamacpp`/`ollama`, else `ollama`                                   | Local backend for the fallback                                                                                                                               |                                     | Only `llamacpp` or `ollama`                                                                                                                                                                                                                                 |
| `VERIFY_DECISION_BREAKER`         | `5` (0 to 1000)                                                                          | Consecutive failed terms after which the provider is not called again this run (0 = off)                                                                     | default                             |                                                                                                                                                                                                                                                             |
| `VERIFY_DECISION_WORKERS`         | `1` (1 to 16)                                                                            | Concurrent adjudications with the decision backend                                                                                                           | default                             | The provider's rate limit applies                                                                                                                                                                                                                           |
| `VERIFY_DECISION_RETRIES`         | `0` (0 to 5)                                                                             | Retries after a 429 or 5xx within one call                                                                                                                   | 0                                   | The next sweep retries anyway                                                                                                                                                                                                                               |
| `VERIFY_OPENAI_URL`               | unset                                                                                    | Chat-completions endpoint for `VERIFY_BACKEND=openai`                                                                                                        |                                     | Required with that backend; checked at start                                                                                                                                                                                                                |
| `VERIFY_OPENAI_KEY_ENV`           | unset (no default name)                                                                  | NAME of the env var that holds its key                                                                                                                       |                                     | Required with that backend; also needs `VERIFY_MODEL`                                                                                                                                                                                                       |
| `VERIFY_OPENAI_EXTRA_BODY`        | unset                                                                                    | JSON object merged into the request body                                                                                                                     |                                     | Must be a JSON object                                                                                                                                                                                                                                       |
| `WIKI_HOST_ALLOW`                 | unset                                                                                    | Comma-separated extra hosts `wiki_scope` may fetch (built in: `fandom.com`, `bulbapedia.bulbagarden.net`)                                                    |                                     | A wider list widens what a glossary can make the container fetch                                                                                                                                                                                            |
| `WIKI_ALLOW_HTTP`                 | unset                                                                                    | `1` lets `glossary_verify` fetch `http://` wikis                                                                                                             | tests only                          | `wiki_scope` is always https and ignores it (stricter, harmless)                                                                                                                                                                                            |
| `GLOSSARY_ARC_TAGS`               | `0` (read by `gen_loop.sh`)                                                              | Run `glossary_verify --tag-arcs` for each show                                                                                                               | per show                            | Fetches wiki pages; cached for `WIKI_CACHE_TTL` (30 days by default)                                                                                                                                                                                        |
| `ARC_TAGS_TIMEOUT`                | `600` s (`gen_loop.sh`)                                                                  | Time limit of one `--tag-arcs` run                                                                                                                           | default                             |                                                                                                                                                                                                                                                             |
| `ARC_MIN_TITLES`                  | `10`                                                                                     | An arc with fewer wiki titles counts as missing                                                                                                              | default                             | Takes effect at the next `--tag-arcs`                                                                                                                                                                                                                       |
| `VERIFY_ARC_GATE`                 | off                                                                                      | Flag a would-be write whose canonical is on no arc page (`not-in-arc-pages`)                                                                                 | only when the arc evidence is whole | A logged no-op until every stored arc has titles                                                                                                                                                                                                            |
| `VERIFY_COMMON_WORD_ARC_RESCUE`   | off                                                                                      | A common-word block is lifted when the canonical is on an arc page                                                                                           | off                                 | Needs `VERIFY_ARC_GATE=1`; measured to let back 58 of 99 wrong writes                                                                                                                                                                                       |
| `VERIFY_WRITE_WHOLE_WORD`         | on                                                                                       | An expansion must contain the term as a whole word to be auto-written; `0` restores the substring rule                                                       | default                             | Other canonicals (`Usop` -> `Usopp`) are flagged for review                                                                                                                                                                                                 |
| `VERIFY_SKIP_COMMON_WORDS`        | on                                                                                       | An ordinary one-word term is flagged `common-word` instead of written; `0` turns the guard off                                                               | default                             | Needs the `wamerican` word list; without it the guard runs on the 228-word bundled list, prints one `unreadable` line per run and the report says `wordlist: missing`                                                                                       |
| `WORDLIST_PATH`                   | `/usr/share/dict/american-english`                                                       | The word list behind the common-word guard (and the fuzzy tiers)                                                                                             | the `wamerican` package             | Read at start; unreadable means the 228-word bundled list and one `unreadable` log line per process                                                                                                                                                         |
| `VERIFY_QUEUE_NO_MATCH`           | `0`                                                                                      | `1`: a term with no candidate is queued (the legacy behaviour). By default it is verified and counted (`no_match`) but not queued                            | default                             |                                                                                                                                                                                                                                                             |
| `VERIFY_QUEUE_BLOCKED_EXPANSIONS` | `1`                                                                                      | `0`: a blocked expansion with MORE tokens than the term is verified and counted, not queued                                                                  | `0`                                 | Same-token-count fixes and respellings are always queued                                                                                                                                                                                                    |
| `VERIFY_REFUSE_EXIT`              | off                                                                                      | `1`: a refused run (`--tag-arcs`, verify, acquire) exits 2 instead of 0                                                                                      |                                     | `gen_loop.sh` treats any non-zero code except 124 as `verify failed (continuing)`, so in the loop it is informational                                                                                                                                       |
| `REPAIR_KEEP_NAME_PARTS`          | on                                                                                       | A name said alone stays alone and a full name stays full; adds a rule to the repair prompt when the glossary has names; `0` turns the check and the rule off | default                             | See the deploy note: the prompt text changes, stored verdicts may go stale for lines that are repaired again                                                                                                                                                |
| `REPAIR_AUTO_DISMISS_WORDS`       | `6`                                                                                      | A rejected proposal with more than N word changes is recorded but kept out of the primary review queue; `off` disables it                                    | default                             | Below 4 it hides acceptable fixes; an unusable value is logged once and means off; empty means the default                                                                                                                                                  |
| `REPAIR_ACCEPT_PUNCT_CASE_ONLY`   | off                                                                                      | Punctuation ADDITIONS (`.` `,`) and meaning-safe case changes get a relaxed layout check                                                                     | off                                 | Added commas can change meaning; audit about 50 pairs first                                                                                                                                                                                                 |
| `REPAIR_GUARD_TERMINAL_PUNCT`     | off                                                                                      | Refuse a repair that adds or removes a terminal `?`, swaps `!` and `?`, or converts a trailing ellipsis to or from `.`/`!`                                   | off until audited                   | Refused 21 of 320 accepted repairs on the 451 real Wano pairs                                                                                                                                                                                               |
| `REPAIR_TRANSPORT_RETRIES`        | `2` (0 to 5)                                                                             | Retry the openai repair backend after a failure known to happen before the request starts sending (refused, DNS, connect timeout); `0` is the single attempt | default                             | Never retries a read timeout; draws on the `REPAIR_OPENAI_RETRIES` allowance                                                                                                                                                                                |
| `REPAIR_OPENAI_RETRIES`           | `2` (0 to 5)                                                                             | Retries after HTTP 429 or 5xx (and transport retries) per line                                                                                               | default                             | `0` also disables transport retries                                                                                                                                                                                                                         |
| `GLOSSARY_LOCK_WAIT`              | `5` s                                                                                    | How long an unattended stage waits for a busy glossary before skipping it (`glossary busy: <stage> skipped`, exit 0)                                         | default                             |                                                                                                                                                                                                                                                             |
| `GLOSSARY_LOCK_WAIT_INTERACTIVE`  | `600` s                                                                                  | How long a human's `--review`, `--revert` or `--prune-no-match` waits for the final write                                                                    | default                             | `--review` answers are saved to `<glossary>.json.review-pending` on timeout                                                                                                                                                                                 |

**Decided defaults (2026-10-09).** Three guards are ON unless set to `0`: `VERIFY_WRITE_WHOLE_WORD`, `VERIFY_SKIP_COMMON_WORDS` and
`REPAIR_KEEP_NAME_PARTS`. Three defaults changed: `VERIFY_QUEUE_NO_MATCH` is `0` (a term with no candidate is not queued),
`REPAIR_AUTO_DISMISS_WORDS` is `6` (`off` disables it; whole numbers still work) and `REPAIR_TRANSPORT_RETRIES` is `2`. Unchanged and still
opt-in: `VERIFY_BACKEND=decision`, `GLOSSARY_ARC_TAGS`, `VERIFY_ARC_GATE`, `VERIFY_COMMON_WORD_ARC_RESCUE`, `REPAIR_ACCEPT_PUNCT_CASE_ONLY`,
`REPAIR_GUARD_TERMINAL_PUNCT`, `VERIFY_REFUSE_EXIT`; `VERIFY_QUEUE_BLOCKED_EXPANSIONS` stays `1`. Each flag has one default in the code
(`repair.KEEP_NAME_PARTS_DEFAULT`, `unresolved.DEFAULT_DISMISS_WORDS`, and the helpers in `glossary_verify`), and `tests/test_default_flags.py`
pins both the new default and the `0`/old value.

- **No episode is re-repaired because of these defaults.** `TEXT_VERSION` (`common.py`, pinned by `tests/test_common.py`) is a literal; the
  `.dubtitles.done` stamp records tier version numbers only, never the prompt or an environment variable, so changing a default does not make
  a stamped episode stale. Only an episode that is repaired again for another reason sees the new behaviour.
- **Stored human verdicts.** A verdict is keyed on the (original line, proposed text) pair. `REPAIR_KEEP_NAME_PARTS` adds one rule to the repair
  prompt when the glossary has names, so the model can propose different text for a line that is repaired again. For such a line an APPROVED
  verdict whose proposal no longer matches is not applied; the line is recorded as `verdict_stale_proposal` and the new proposal is judged on
  its own merits (and may now be refused as `rejected_name_part`). Rejected verdicts stay stored but stop suppressing a line whose proposal has changed. Approved and `correct` verdicts that still
  match keep applying, including when the name-part check would refuse them. Set `REPAIR_KEEP_NAME_PARTS=0` before repairing again to keep the old prompt.
- **Missing word list.** With `VERIFY_SKIP_COMMON_WORDS` on by default, an image without `wamerican` still runs verify: the guard falls back to
  the bundled list, one `word list ... unreadable` line is printed per process, and the report carries `common_word: {"wordlist": "missing"}`.
  The guard blocks far fewer wrong writes on the bundled list (6 of 119 instead of 99), so install `wamerican` or set `WORDLIST_PATH`.
- **Stored no-match flags stay.** `VERIFY_QUEUE_NO_MATCH=0` only stops NEW no-match entries: the 1,702 already stored across 11 glossaries
  (One Pace 982) stay in the queue. `glossary_acquire.py <glossary> <showdir> --review --prune-no-match` clears them.
- **Glossary verify and acquire survive a hard interruption.** Every completed adjudication (verify: one per term; acquire: one per
  tier-C pair and per tier-B term) is appended to a journal (`<WIKI_CACHE_DIR>/<show>.verify.journal.jsonl`, and
  `<glossary>.acquire.journal.jsonl` beside the glossary) as soon as it exists: one fsynced line each, safe against two writers and
  a torn last line. A rerun reuses them without calling the model and asks only what is left, and its report and glossary equal an
  uninterrupted run's. Each line records what the answer depended on (show, term, candidate-list or context hashes, backend, model,
  prompt version, the server URL (hashed; never a key), the openai `extra_body`, and for the decision model its threshold and
  `DECISION_CLIENT_VERSION`); a line whose inputs changed is ignored, not deleted. `max_tokens` is not part of it. Unavailable
  answers (nothing returned, or a reply no JSON could be decoded from), failed decision calls and the local fallback's answers are
  never journaled. A clean apply compacts the file (latest line per key). The `decision` counters in a resumed run count only the
  calls it actually made.
  - **Lifetime:** a stored answer is served for 30 days; compaction drops older lines.
  - **Busting a bad stored answer:** `glossary_verify.py --force` asks the model again for every term (the journal is not read; the
    fresh answers replace the old ones). `VERIFY_NO_JOURNAL=1` / `ACQUIRE_NO_CACHE=1` neither read nor write it. Or delete the
    file: `<WIKI_CACHE_DIR>/<show, non-alphanumerics as _>.verify.journal.jsonl` for verify. For acquire delete BOTH
    `<glossary without .json>.acquire.journal.jsonl` AND the older `<glossary without .json>.acquire-cache.json` next to it (or set
    `ACQUIRE_NO_CACHE=1`): `escalate()` consults that older cache before the journal, so an old cache shadows a fresher journal.
  - **Wiki drift:** the candidate list is keyed by the TITLES offered, so a wiki edit that keeps every title identical (a changed
    redirect target or page body) can serve an older answer until it ages out or someone runs `--force`.
- **A re-verify that affirms a term keeps its earlier proposal in the queue.** `verify --force` revisits verified terms; if the new
  answer is the term itself, an older `respelling-needs-review` flag for it (say `Raftel -> Ratel`) is left in the review queue, not
  cleared, so accepting it later would still write that hard fix. This is deliberate for now (a fresh answer must not erase another
  stage's evidence), but the queue does not show the conflict; check the term before accepting an old flag after a forced re-verify.
- **More respellings are flagged.** `VERIFY_WRITE_WHOLE_WORD` on means a canonical that only contains the term as a substring (`Usop` -> `Usopp`)
  is flagged `respelling-needs-review` instead of written, so the review queue gains those entries and the written count falls.
- **`tools/glossary_consequences.py` adds a production-policy mode** (`policy="production"`) calling the real guard path (`glossary_verify.write_decision` / `apply_results`) and reporting per-outcome counts (`WRITTEN`, `QUEUED`, `RECORDED-NOT-QUEUED`), while keeping the old substring rule available as `LEGACY`.

Combinations to avoid:

- `VERIFY_ARC_GATE=1` with `VERIFY_QUEUE_BLOCKED_EXPANSIONS=0` hides names that miss an arc page from every human: they are neither
  written nor queued.
- `REPAIR_AUTO_DISMISS_WORDS` below 4 hides acceptable fixes from the primary queue (they stay in the sidecar and under `--all`).
- `VERIFY_QUEUE_NO_MATCH=0` together with `VERIFY_QUEUE_BLOCKED_EXPANSIONS=0` means the glossary queue only ever shows real
  decisions: a candidate to accept or reject, or a respelling. That is the point, but nothing else is ever surfaced.

**Deploy note.** `compose.yaml` passes an explicit environment allowlist, so none of the variables above reaches the container
until they are added to its `environment:` block (and to the second half of the nightly window, the cron host, if it runs these
stages).

- **Mux temp files are unique per run.** `mux.py` now uses `<stem>.<pid>.<token>.muxtmp.mkv` to prevent collision between concurrent writers, verifies the source file is unchanged (size, mtime, inode, device) before replacing the original, and updates recovery/sweep checks to match both legacy and new temp files.

- **A saved review answer applies only to the proposal you saw.** Pending answers now carry the canonical (and the reason) of the
  flag you answered; on replay one whose flag now proposes a different canonical (after `--revert` and a new verify) is skipped and
  logged (`the proposal changed since you answered`), as is an entry from an older pending file that has no canonical to check.

- **`REPAIR_GUARD_TERMINAL_PUNCT=1` (default off) refuses the punctuation changes that change tone or meaning.** A repair that adds or
  removes a terminal `?` (question <-> statement, `!` <-> `?`), or turns a trailing ellipsis (`...`, `…`) into `.` or `!` or the
  reverse (`Damn...` -> `Damn!`), is refused with the guard name `terminal_punct`; the summary counts them as
  `rejected_terminal_punct` while the flag is on. Comma <-> period, `.` <-> `!` and `?!` -> `?` still pass. On the 451 real Wano
  pairs it would refuse 21 of the 320 repairs the ordinary guards accept (6.6%); a general "no removed or substituted punctuation"
  guard would refuse about half. Also: the card-initial capital rule is now tested through `repair.process`, and the glossary
  case rule gives no leniency when the word list is missing (it used to fall back to a 228-word list and let `rain` -> `Rain` ship).

- **Saved review answers are safe to replay.** An answer saved while the glossary was busy is applied only to a term that is still
  flagged; one decided meanwhile is skipped and logged, and `record_decision` leaves an unflagged term alone, so a stale `n` or `y`
  can no longer delete a hard fix or add the term to `known`. Answers are written to `<glossary>.json.review-pending` before the
  wait and removed after the glossary is written, so a kill while waiting loses nothing, and every read-modify-write of that file
  holds a small lock (`<glossary>.json.review-pending.lock`).

- **`REPAIR_ACCEPT_PUNCT_CASE_ONLY` now covers punctuation ADDITIONS only.** A word-identical proposal gets the relaxed layout check
  only when the punctuation between its words differs from the original's by added `.` and `,` (the old marks all survive, in order;
  nothing removed, replaced or reordered, hyphens, brackets, quotes, `?`, `!` and musical notes included; an added `...` or `…` is not
  an addition). Anything else meets the ordinary guards. Case changes: a glossary spelling is lenient only for a single-word entry
  that is not an ordinary word (`luffy` -> `Luffy`, not `law` -> `Law`) or when the changed words complete a whole multi-word entry in
  sequence (`devil fruit` -> `Devil Fruit`, not a lone `line` -> `Line`); the card's first word counts as a sentence start only when
  the previous card ended in `.`, `!` or `?` (or there is none), and `...`/`…` never end a sentence.
  **Known limit of the ordinary guards (flag off, today):** a critic's list of 60 meaning-changing punctuation and case edits had 33
  that the guards admit (`Let's eat, Grandma.` -> `Let's eat Grandma.`, `.` -> `?`, removed hyphens, possessive apostrophes, brackets,
  quotes, ellipses). Whether the gate should refuse removed or substituted punctuation for everyone is a decision for the maintainer.

- **Glossary review answers survive a busy glossary; wiki redirects are guarded.** `glossary_acquire --review --apply`, `--revert` and
  `--prune-no-match` wait up to `GLOSSARY_LOCK_WAIT_INTERACTIVE` seconds (default 600) for the glossary, printing `waiting for
<stage> to finish...`. If it stays busy, your `--review` answers are saved atomically to `<glossary>.json.review-pending` and
  applied at the start of the next `--review`; the summary's `pending` is read from the file on disk, plus `saved` when answers
  are waiting. The lock now names its holder, is documented as not reentrant, and an unwritable glossary directory logs once that the
  stage runs unlocked. A wiki redirect to a scheme that is not allowed (https to http or ftp) is refused before the request is made.
- **`REPAIR_TRANSPORT_RETRIES` no longer re-sends a request the server already has.** Only failures before the request is out
  (connection refused, DNS, a connect timeout, a reset while connecting or sending) are retried; a read timeout, RemoteDisconnected
  or IncompleteRead is not, since the provider is usually still generating (and billing) it. The backoff is spent from
  `REPAIR_RETRY_SLEEP_BUDGET`, the retries stop at the episode deadline, and transport retries share the `REPAIR_OPENAI_RETRIES`
  allowance (at most that many plus one POSTs per line).
- **`VERIFY_QUEUE_BLOCKED_EXPANSIONS=0` only drops real expansions.** A blocked canonical with more tokens than the term (`D` ->
  `Monkey D. Luffy`, `Castle` -> `Hancock Castle`) is verified and counted but not queued; a canonical with the same number of tokens
  (`Usop` -> `Usopp`, `Burn` -> `Coburn`) is a spelling fix and is always queued under its legacy reason.

- **`REPAIR_ACCEPT_PUNCT_CASE_ONLY` is safer, still off by default.** "Only case and punctuation changed" now compares the words as a
  sequence (a reorder is a change); the relaxed layout check lets an already-bad card grow by at most 2 characters (and the matching
  cps), so a 70-character over-cps card cannot become 82; and only case changes that cannot change meaning count: a sentence or card
  start, `i` -> `I`, `ok` -> `OK`, and a glossary spelling (narrowed again by the additions-only entry above). `us` -> `US`, `march` -> `March` and `turkey` -> `Turkey` count
  as word changes. An unusable `REPAIR_AUTO_DISMISS_WORDS` (`abc`, `4.0`, `-1`) is logged once instead of silently turning the rule
  off, and only the three rejection reasons can be dismissed from the queue.

  **Limit of the repair gate, flag on or off:** it does not guard punctuation that changes MEANING. `Let's eat, Grandma` ->
  `Let's eat Grandma`, a moved comma, or `?` -> `.` all pass. Keep `REPAIR_ACCEPT_PUNCT_CASE_ONLY` off unless a human audits a sample
  first: take the episodes' `accepted_punct_case_only` repairs (the summary counts them), read about 50 old/new pairs side by side, and
  turn the flag on only if none of them changes who is doing what to whom.

- **Fewer glossary flags, and a repair transport retry (both opt-in).** `VERIFY_QUEUE_BLOCKED_EXPANSIONS=0` (default `1`) leaves an
  expansion that a write guard blocked (common-word, not-in-arc-pages, or the whole-word guard) out of `flagged` when its canonical
  has MORE tokens than the term (`D` -> `Monkey D. Luffy`, `Castle` -> `Hancock Castle`): it is still verified and counted
  (`blocked_expansions`, `blocked_expansions_by_reason`). Every same-token-count fix (`Usop` -> `Usopp`, `Burn` -> `Coburn`) and every
  real respelling (`Raftel` -> `Ratel`) is always queued. Expansions are additive (the short form stays), and on the audited writes
  about 75% of what the guards send to review was wrong. `REPAIR_TRANSPORT_RETRIES=N` (default `0`, at most 5; **recommended 2**)
  retries the openai repair backend only after a failure BEFORE the request was sent (a refused connection, DNS, a connect timeout, a
  reset while connecting or sending), with a 0.5 s, 1 s, ... backoff; a read timeout, RemoteDisconnected or IncompleteRead is never
  retried, and HTTP answers keep their own retry rules (see the later entry). The summary counts `transport_retries`.
  A tool fix: the scorer no longer calls rule (d) "within noise" for an arm far below a perfect floor.

  **Recommended write profile** (nothing here is on by default): `VERIFY_BACKEND=decision`, `VERIFY_WRITE_WHOLE_WORD=1`,
  `VERIFY_SKIP_COMMON_WORDS=1`, `VERIFY_QUEUE_NO_MATCH=0`, `VERIFY_QUEUE_BLOCKED_EXPANSIONS=0`, and `REPAIR_TRANSPORT_RETRIES=2` for
  the repair stage.

- **Glossary hardening.** Wiki fetches speak https only (`WIKI_ALLOW_HTTP=1` allows http, for tests): a glossary's `wiki` value or an
  override such as `file:///...` or `ftp://...` is refused instead of reaching `urlopen`, and `normalize_api` returns None for it.
  Every stage that rewrites a glossary (verify, `--tag-arcs`, `acquire --apply`, `mine_glossary`, `--review --apply`, `--revert
--apply`) takes one advisory lock, `<glossary>.json.lock`; a stage that finds it busy (waits `GLOSSARY_LOCK_WAIT`, default 5 s)
  logs `glossary busy: <stage> skipped` and exits 0, so a manual run during the nightly pass no longer loses one side's updates.
  `--review --apply` applies your decisions to the freshly re-read file. A malformed adjudication (a list, a non-string canonical)
  is a counted no-match (`malformed` in the verify report); the common-word guard ignores punctuation around a term. A
  `no-match` flag that carries a candidate is no longer collapsed in `--review`, and `glossary_acquire --review --prune-no-match
[--apply]` removes the stored candidate-less no-match flags of verified terms.

- **A smaller repair review queue (both opt-in).** `REPAIR_AUTO_DISMISS_WORDS=N` (unset = off) marks a rejected repair whose
  proposal changed more than N words (added plus dropped, case and punctuation ignored) as `dismissed: large_change`. It is still
  written to the sidecar (the audit trail, with `changes`), but the review page and `unresolved.py` skip it; the page's
  all-reasons view and `unresolved.py --all` show it, and the repair summary counts `dismissed_large_change`. Measured on a blind
  sample of 100 rejected Wano repairs judged by two models: with N=6 it dismisses 24 and loses none that either judge would
  accept (N=4 loses one). **Recommended: N=6.** `REPAIR_ACCEPT_PUNCT_CASE_ONLY=1` lets a proposal that changes only case or
  punctuation past the "nothing changed" and card-fit guards when it creates no NEW kind of layout fault (7 of the 100 rejected
  proposals changed no word; the guard was `fits_card`: one added period makes an already over-cps card "worse"); the summary
  counts `accepted_punct_case_only`. Every other guard still applies. New rejected entries record the `guard` that fired
  (empty, unchanged, invents_name, name_part, vouched_name, length_ratio, fits_card, ref_borrow).

- **A smaller glossary review queue.** On a One Pace rebuild verify flagged 687 terms, 578 of them `no-match`: nothing to accept or
  reject. `VERIFY_QUEUE_NO_MATCH=0` (default `1`, the old behaviour) leaves such a term out of `flagged`; it is still marked
  verified and counted in the report as `no_match`. `glossary_acquire.py --review` now lists the entries that carry a decision
  first (respelling-needs-review, common-word, not-in-arc-pages, low-confidence, possessive_floor_crossing, then the rest) and
  prints one line for the stored `no-match` entries; `--review --all` walks those too. (109 items instead of 687 on that rebuild.)
  Glossary flags are not shown on the review page, which lists the repair queue only.

  **Recommended profile for a hosted-decision-model rebuild** (nothing here is on by default): `VERIFY_BACKEND=decision`,
  `VERIFY_WRITE_WHOLE_WORD=1`, `VERIFY_SKIP_COMMON_WORDS=1`, `VERIFY_QUEUE_NO_MATCH=0`, and `VERIFY_ARC_GATE=1` only for a show
  whose arcs are all covered (`GLOSSARY_ARC_TAGS=1` first; One Pace needs `arc_aliases` / `arc_waived` before the gate can turn
  on, see the arc entry below).

- **Shows without arc names get a wiki scope (opt-in).** A glossary with a `wiki_scope` block (see `wiki_scope.py` for the shape
  and the Naruto / Pokemon / whole-wiki examples) makes `--tag-arcs` (`GLOSSARY_ARC_TAGS=1`) resolve one scope per library season,
  or one for the whole wiki, and store the titles beside the arc titles under `scope:<rung>:<season or all>`, only when the
  result is complete. The verify gate's universe is the union of the arc and scope titles, still a logged no-op unless every
  expected scope is covered; a whole-wiki scope is left out of it (it would contain every page verify can propose) and tags no
  names. `arc_index` reads the index page per part (`part` / `season_parts`; each part numbers its own episodes from 1) and
  needs an SxxExx tag in the video file names. No new environment variable.

- **The arc gate only turns on when its evidence is whole.** `VERIFY_ARC_GATE=1` is a logged no-op unless every stored arc has a
  coverage record (a glossary tagged by an older version needs `--tag-arcs` again), no arc's redirect step is unfinished and no
  arc is missing. An arc with fewer than `ARC_MIN_TITLES` (default 10) titles counts as missing. The arc cache is versioned
  (version-1 files are ignored). Two hand-edited, per-glossary keys close gaps the code must not guess: `arc_aliases`
  (`{"Water Seven": "Water 7"}`: the wiki page to fetch for a season's arc) and `arc_waived` (`["Gaimon"]`: seasons accepted as
  covered by the other arcs). Without them the gate cannot turn on for One Pace; nothing is added to any glossary by code.
- **Arc tags and an arc gate for verify (both opt-in).** `GLOSSARY_ARC_TAGS=1` makes `gen_loop.sh` run
  `glossary_verify.py <glossary> --tag-arcs <show dir>` before VERIFY: one cached wiki fetch per distinct `season.nfo` arc tags
  the glossary's names (repair weights its prompt by them) and stores each arc's page titles (links normalised to page titles,
  redirect targets included). Only COMPLETE fetches are stored or cached; the arcs that returned nothing are recorded in
  `arc_titles_missing`. `VERIFY_ARC_GATE=1` then flags a would-be auto-write whose canonical is on no arc page as
  `not-in-arc-pages`; it does nothing (and says so once) unless every arc of the show has stored titles. The gate covers verify's
  auto-writes only: acquire's own writes (`ACQUIRE_APPLY`) are not gated. `--tag-arcs` exits 0 whatever happened (the `note` in
  its JSON line is the signal) unless `VERIFY_REFUSE_EXIT=1`, which makes a load failure, an unresolved wiki or a failed write
  exit 2.

- **Repair can keep names as the dub says them (opt-in).** `REPAIR_KEEP_NAME_PARTS=1` makes the repair stage refuse a
  repair that adds or removes a part of a multi-word glossary name next to a name token the line already had
  (`Momonosuke` -> `Kouzuki Momonosuke`, `Zorro` -> `Roronoa Zoro`, and back). Misheard single tokens (`Kojuki` ->
  `Kouzuki`, `Odin` -> `Oden`) are still fixed. A refusal is queued as `rejected_name_part` (visible in the review page, with
  force / reject / correct) and counted in the repair summary. Off by default until a live measurement exists. The repair
  prompt also gained one rule (write each name exactly as the line says it), only when the glossary has reference
  spellings and only while the flag is on. **Changing the prompt changes model output**: on the next repair of an episode,
  stored human accept / correct / force verdicts (keyed on the original and the model's proposal) will no longer match and come
  back as `verdict_stale_proposal` entries, the same effect a `REPAIR_MODEL` change has. With the flag unset nothing changes.
- **A common-word guard for verify (opt-in).** `VERIFY_SKIP_COMMON_WORDS=1` flags a single-token term for review, instead of
  writing its expansion, when the system word list spells it in lowercase (`castle`, `government`; names such as `Hancock` are
  capitalised in the list and are not words). On the 163 blind-audited writes it blocks 99 of 119 wrong ones and 11 of 42
  correct ones. `VERIFY_COMMON_WORD_ARC_RESCUE=1` (needs `VERIFY_ARC_GATE=1`) lets the ones on an arc page through. A missing
  word list is logged once and shows as `common_word.wordlist: missing` in the verify report. In `glossary_acquire --review`, a
  `y` on a flagged expansion (`common-word`, `not-in-arc-pages`, `respelling-needs-review`) now writes it, as verify would have.

- **Repair and the bake-off can call any OpenAI-compatible chat API.** `REPAIR_BACKEND=openai`
  (with `REPAIR_OPENAI_URL`, `REPAIR_OPENAI_KEY_ENV` naming the env var that holds the key,
  `REPAIR_MAX_TOKENS`, optional `REPAIR_EXTRA_BODY` JSON) works against OpenRouter, Kilo,
  CommandCode, NVIDIA, Cerebras and the like. Only `message.content` is read, never
  `reasoning_content`; a missing key or a transport failure counts as unreachable and the key
  value is never logged. `tools/bakeoff.py` gains `--openai-url`, `--key-env` and `--extra-body`,
  reports HTTP 429 as rate-limited (one retry, `Retry-After` capped at 60 s) instead of an empty
  reply, takes `--delay SECONDS` (a pause between consecutive calls in every mode, outside the recorded
  latency, and the floor of the 429 retry wait) so a rate-limited free tier doesn't score its own throttling as
  model failures, and writes token counts to `--json`. The default llamacpp/ollama paths are unchanged.
  A malformed `REPAIR_EXTRA_BODY` is checked on each call, not at import: the stage logs the
  variable name and reports the backend unreachable, so nothing ships and the run is retried.
  The key is stripped of a trailing CR/LF (CRLF `.env` files) and a key with spaces or control
  characters is a config error that names only the variable; failures log a fixed text with the
  exception class or HTTP status, never the exception text or response body. An empty reply that hit
  `max_tokens` (`finish_reason=length`) counts as unreachable, not "no repair", so raw ASR is not
  shipped silently. An unreachable second-pass model is counted as `unreachable_secondary` (the
  first-pass repair stands, as before). The bake-off refuses redirects, only trusts a `Retry-After`
  of 0 to 60 s (else 5 s), no longer counts the sleep as model latency, tolerates odd `usage`
  shapes, takes `--max-tokens`, and refuses `--openai-url` without an explicit `--models`.
- **Bake-off can test the anchored prompt.** `tools/bakeoff.py --dump-refs OUT.json --video V`
  (no model calls) records each target's fansub reference, chosen the way `repair.process` does;
  `--refs OUT.json` then runs the models with those references and neighbouring lines, scores each
  target against its own reference, skips targets with no reference (as production does, unless
  `--include-unanchored` or the glossary sets `unanchored_repair`), and adds a `borrow` column for
  outputs that copy words from the fansub. The dump uses the raw conf text exactly as
  `repair.process` does (no glossary pass) and records the episode key and arc, so `--refs` prompts
  are identical to production's (a differential test runs the real `process` to prove it); `--refs`
  needs `--glossary` and exits on a refs file that is for another conf, has a different card count,
  a retimed card, a duplicate or bad `idx`, or changed text (`--allow-conf-mismatch` for a renamed
  conf). Model replies are now passed through `glossary.correct` before the ship gate, as
  production does, so glossary-only scores change slightly with this fix (a reply that only needed
  a glossary fix is no longer penalised).
- **Repair refuses an episode when the backend is down for a meaningful share of it.** If the
  backend failed `REPAIR_UNREACHABLE_REFUSE_PCT` percent (default 10) or more of the targets that
  reached it (cards skipped for want of a fansub line don't count), or `REPAIR_MAX_CONSECUTIVE_UNREACHABLE`
  (default 5) in a row, the episode is refused with `backend-unreachable` and the shipped srt is
  kept, instead of being rebuilt from raw ASR. A stray bad line (a few percent) still ships. A run
  of consecutive failures stops the loop early. `REPAIR_RETRY_SLEEP_BUDGET` (default 600 s) caps the
  total retry sleep per episode; once it is spent each remaining target gets one attempt.
- **Repair honours the soft stop.** Between targets it checks the stop flag; when set it leaves the
  srt untouched, records the new failed stage outcome `stopped`, and exits 0. The failed outcome keeps
  `merge_pass.sh` from assembling or muxing the episode, and the next pass re-runs repair.
- **Failure handling applies to every backend, the default llamacpp/ollama ones included.** The
  failure-rate refusal, the consecutive-failure cut-off and the narrowed (reached-the-backend-only)
  refusal replace the old "every target unreachable" test for all of them. An episode whose backend
  failed 10% or more of its targets (or 5 in a row) is refused with `backend-unreachable` and the
  shipped srt is kept; the loop stops as soon as the refusal is certain. A stray bad line still ships.
  HTTP 400/404/409/413/422 from the openai backend are per-line (no repair for that line, counted as
  `rejected_4xx`, queued as `llm_empty`); if 3 or more requests are all rejected that way the episode is
  refused as a wrong model id or URL (at any episode size, so a wrong model id can no longer rebuild a
  small episode as raw ASR). The same request-scoped statuses are treated per line on the llamacpp and
  ollama backends too, so llama.cpp answering 400 "context size exceeded" on one line of a small
  episode no longer refuses it on every pass; 401/403/408/429/5xx and transport errors still count as
  the backend being down. `REPAIR_REQUEST_DEADLINE` bounds one HTTP request in total
  (a trickling server no longer holds it open) and `REPAIR_EPISODE_DEADLINE` bounds an episode. The
  3600 s default is measured: across 1631 production episodes the median repair took 52 s, p99 256 s,
  max 897 s, so it is about 4x the slowest real episode. The refusal log gives the elapsed seconds, how many targets were reached and
  the limit, and the secondary-model call is skipped once the deadline has passed. A soft stop also ends retries at once.
- **New stage outcome `stopped`** (a failed outcome): repair honoured the soft stop, left the srt alone,
  and `merge_pass.sh` holds the episode back until the next pass re-runs repair.
- **Environment variables added (defaults):** `REPAIR_OPENAI_URL`, `REPAIR_OPENAI_KEY_ENV`,
  `REPAIR_EXTRA_BODY` (none); `REPAIR_MAX_TOKENS` 1024; `REPAIR_OPENAI_RETRIES` 2;
  `REPAIR_UNREACHABLE_REFUSE_PCT` 10; `REPAIR_MAX_CONSECUTIVE_UNREACHABLE` 5;
  `REPAIR_RETRY_SLEEP_BUDGET` 600 (s); `REPAIR_REQUEST_DEADLINE` 300 (s, min 10);
  `REPAIR_EPISODE_DEADLINE` 3600 (s, 0 disables). All are documented in the header of `repair.py`.
- **The openai backend retries HTTP 429 and 5xx** up to `REPAIR_OPENAI_RETRIES` times (default 2),
  waiting a finite `Retry-After` (at most 30 s) or 2 s then 4 s, then reports the backend
  unreachable. Other 4xx errors do not retry.
  Each retry is logged (status only), retry sleeps are not counted in the latency stats, and a
  refused redirect is a clean `HTTP 3xx` failure. A bad `REPAIR_MAX_TOKENS` (or
  `REPAIR_OPENAI_RETRIES`) logs one warning naming the variable and falls back to the default
  instead of crashing `import repair`. `--refs` also exits if a card's source window moved or the
  glossary file differs from the one the refs were cut with (`--allow-glossary-mismatch`).
- **mux verification measures the video track itself.** When the video stream carries neither a
  duration nor a DURATION tag, `video_duration()` now takes the end of the last video packet
  (scanning the final minute) instead of the container duration, which in Matroska is the longest
  track. Three episodes whose dropped foreign subtitle tracks made the remux look 11-31 s short, and
  so failed verification on every pass, will now mux. A truly truncated output is still rejected.
- **README shows table is generated at publish time.** New `tools/render_readme_table.py` rewrites
  the region between `<!-- shows-table:start -->` and `<!-- shows-table:end -->` from the
  `manifest/` files (counts, sorted, `{tvdb-N}` stripped); no markers means no change.
  The table (and its date) changes only when the numbers or rows change, so publishing makes no
  daily noise commit; with no loadable manifest it leaves the README alone. A missing or odd
  `status` counts as unreviewed. `tools/publish_subtitles.sh` calls it before the change check,
  and a failure there never blocks publishing.
- **README table lead line reworded.** It now reads "Last updated <date>: ... this table is rebuilt
  from `manifest/` with each update" instead of calling itself a snapshot. A block still holding the
  old "As of" wording is rewritten once; after that only a change in the numbers rewrites it.
- **Glossary steps stop between units on a soft stop.** `mine_glossary.py` (between episodes),
  `glossary_verify.py` (between terms) and `glossary_acquire.py` (between escalation pairs, tier-B
  terms and admission episodes) check the stop flag, log `stop requested: leaving <step> after <n>
<unit>s` and exit 0 instead of running past the docker stop grace into a SIGKILL. Verify writes
  its completed terms atomically; acquire keeps finished escalation pairs in its cache; mine and
  acquire write nothing on a stop.

## 0.2.2 - 2026-10-08

Hardening pass from a whole-repository review of `main`: no failed stage is muxed and stamped as done any
more, no failure path deletes the only copy of an episode, and the nightly `docker stop` no longer kills the
container mid-transcription. 0.2.1 was prepared (its entry is below) but never tagged or published; everything
in it ships in this release. Every change below was written test first and has run in production.

### Fixed

- The container now exits softly on SIGTERM. `container_run.sh` stays as a supervisor instead of handing PID 1 to a bare `sh`, which ignored the signal: on `docker stop` it only raises a stop flag, the generate, merge and review loops start no new episode, the one in flight finishes, and the container exits 0. Before, the container kept starting new episodes for the whole stop grace period and was then killed mid-transcription.
- That nightly kill used to poison episodes: a transcription killed part-way leaves a permanent `.dubtitles.fail` marker and the episode is skipped forever (seven were affected). The stop flag is only ever read between episodes, so no marker is written by a stop. A stop also skips the per-show MINE, ACQUIRE and VERIFY steps that have not started yet, and a merge pass cut short by a stop now says `MERGE PASS STOPPED` instead of `COMPLETE`.
- `mux.py`: a failed stamp write on an `.mkv` episode deleted the only copy of the episode
  (the rollback removed the freshly replaced file, which was also the original). The stamp
  is now written from the temp file before it replaces the episode, so a stamp failure
  leaves the original untouched and the next sweep retries. A stamp is only removed again
  if the rename into place did not complete.
- `mux.py`: when the cross-device copy in `_finalize` fails partway, the complete temp
  output is kept as `<episode>.muxtmp.mkv.recovered` (not deleted, and not touched by later
  sweeps) and mux writes `<episode>.dubtitles.mux-recovery`. It then refuses to re-mux that
  episode (`recovery-pending`; the stage stays `crashed`, so the pass reports INCOMPLETE)
  until a human restores the kept file over the episode and deletes the marker. A plain
  rename failure (for example a permission error) does NOT trigger this: nothing was
  copied, so the stamp and temp output are removed and the next sweep retries.
- `mux.py`: known remaining limitation (tracked separately): the cross-device fallback
  still overwrites the original in place.
- `mux.py`: failures in the post-stamp cleanup (removing the old mp4 link, writing
  `.dubtitles.mux.log`) no longer record the episode as `crashed`. The episode is already
  muxed and stamped, and the next sweep returns `already-muxed` before any stage write, so
  the bogus record was never cleared and `merge_pass.sh` reported MERGE PASS INCOMPLETE
  forever. Cleanup errors now log a warning and the stage records `ok`.
- Changelog: the 0.2.1 entry for `merge_pass.sh` wrongly says the episode stem is passed
  via an environment variable; it is actually passed as argv (`sys.argv[1]`, `sys.argv[2]`).
- `merge_pass.sh` no longer runs mux after a failed repair or a failed signs step. The
  episode is skipped with a `skip mux: ... failed (<outcome>)` line and retried next pass.
  Records from older runs are cleared before repair and before mux, and an episode that
  already has its `.ass` is muxed as before whatever old records say.
- A refused repair (it would have overwritten repairs already shipped with raw ASR) is now
  recorded as `refused`, which counts as a failure, instead of the passing `no-reference`.
- A missing `conf.json` (or `.srt`) is no longer recorded as `no-video`. It is recorded as
  `ok` with detail `no-conf` / `no-srt`; `no-video` now means there is no video.
- A failed signs build no longer leaves an `.ass` behind for `merge_pass.sh` to trust and mux
  to prefer. The build goes to `<episode>.eng.dubtitles.ass.part` and replaces the `.ass`
  only when it succeeds, so a good earlier `.ass` also survives a failed rebuild. If every
  English subtitle stream fails to extract, signs is now `build-error` / `extract-failed`
  instead of "no signs".
- A broken failed-stage scan at the end of `merge_pass.sh` no longer prints `MERGE PASS
COMPLETE`. It prints `MERGE PASS INCOMPLETE: failed-stage scan error`. Counts from several
  scan batches are now added up instead of breaking the comparison.
- `common.failed_stage` reads stages in pipeline order (repair, signs, mux) as its docstring
  says, not in file order, and takes an optional `only=` list of stages.
- The `.dubtitles.done` stamp and repair's `.srt`, audit `.csv` and summary `.json` are now
  written through a temp file and renamed into place (`common.atomic_write`, shared with
  `generate.py`). A crash mid-write no longer truncates the previous stamp, which used to
  trigger a re-mux of the episode on every sweep, or the shipped `.srt`.
- A failing ffmpeg no longer produces a truncated transcription: `extract_wav` now checks the
  exit code, deletes the partial wav and reports `extract-failed`, so the episode is retried
  instead of getting subtitles for only part of the audio.
- The publish unit (`deploy/dubtitlerr-publish.service`) no longer puts the GitHub token on
  the docker command line, where `ps`, the journal and `systemctl status` showed it. It now
  passes `-e GITHUB_USER -e GITHUB_PAT` without values. Copying the unit to the host is a
  manual step.
- `merge_pass.sh` no longer runs mux when repair or signs crashed and the crash record could
  not be written either (for example an unwritable stage file): that stem is skipped as
  `<stage> crashed (no record)`. A crash after a stage already recorded `ok` does not block it.
- A stale `<episode>.eng.dubtitles.ass.part` (left if the pipeline was killed while installing
  the signs file) is now removed when the episode is muxed.

### Added

- `deploy/dubtitlerr-window-{open,close}.{service,timer}`: the nightly window units, until now only on the
  host, with `tests/test_deploy_units.py`, which parses them, unescapes the `ExecStart` lines the way systemd
  does and runs the muxtmp sweep against a fake library. The close unit stops the container with
  `docker stop -t 900` (the soft exit needs the grace period to cover the longest single episode or mux),
  logs the container's exit code (0 is a soft exit, 137 is a SIGKILL) and its sweep skips any stem that has a
  `.dubtitles.mux-recovery` marker. Copy the units to `/etc/systemd/system/` and run `systemctl daemon-reload`;
  raise the stop grace only together with this release's image, because an older image ignores SIGTERM and
  would simply keep working for the longer grace.

## 0.2.1 - 2026-09-24

Release-integrity and fail-closed hardening driven by the v0.2.0 adversarial release review
(findings B1–B9; the original review file is missing — a labeled reconstruction plus a
post-review evidence log in `docs/Adversarial Reviews/` document the findings and this
remediation).

### Fixed

- `mux.py`: every failure exit path now writes a real stage record using an outcome from
  `common.STAGE_OUTCOMES`. Mux verification failures record `build-error` with a
  `verify:<reason>` detail, signs-regression refusals are recorded as a visible failure
  instead of a silent return, and unexpected exceptions record a sanitized `crashed`
  detail. Previously these paths wrote no record (or an invalid one), so `failed_stage()`
  could not see the failure and the episode could look current.
- `merge_pass.sh`: the crash-classification fallbacks receive the episode stem via an
  environment variable instead of inline `'$stem'` interpolation — stems containing
  apostrophes (e.g. `JoJo's Bizarre Adventure`) no longer raise `SyntaxError` or write
  bogus crash records.

### Changed

- `release.yml`: image build/push is gated behind a reusable `ci-gate` workflow that
  re-runs the CI matrix for the tagged commit and skips the image job on any red
  conclusion — image push cannot follow failed CI (proven on a disposable failed-tag
  run, see Verification).
- `uv.lock` resynced to the `pyproject.toml` version; the sprint-015 retro carries a
  dated correction (the upstream `azrtydxb/procoder#301` issue now exists); stale
  CHANGELOG sentences and test docstrings fixed.

### Verification

Sanitized evidence recorded 2026-09-24/25 (no secrets; no live mutation accompanied it):

- **CI gate proof (release integrity):** a disposable failed-tag run (temporary branch
  and annotated tag, both deleted afterwards) went red on the Python 3.11/3.13 tests
  while lint and osv-scan passed, and the image job was **skipped** as designed. No
  image build/push or release publication followed the red CI conclusion. The public
  `v0.2.0` tag was not moved.
- **Deployment host, read-only audit:** the worker container runs
  `dubtitle-builder:0.1.3` while the deployed publish service pins `0.1.0` — a pin
  mismatch is observed, its causal effect unproven, and alignment is tracked separately.
  Representative media (One Pace S33, sampled 5 of 39 episodes) all carry nonempty
  `.done` stamps and mux logs with no fail stamps, exactly one default SubRip
  `Dubtitles` stream each, no external subtitle sidecars, and the sampled episodes
  decoded cleanly with hundreds of positive subtitle packets and none empty. A full
  39-file sweep is not proven; conclusions are limited to the sample.
- **Known open item:** the owner-reported playback symptom (One Pace S33 dubtitle tracks
  render nothing) is **not root-caused**. Ranked hypotheses and the smallest safe next
  diagnostic (a bounded read-only probe on the actual player/server host) are recorded
  in the homelab documentation vault; no causation is claimed.

## 0.2.0 - 2026-09-23

Scope boundary for the v0.2.0 hardening pass, set 2026-09-21. The scope ids S-1 through
S-22 are defined in `.procoder/specs/v0-2-0-hardening.md`; the tasks that deliver them are
in `.procoder/plans/v0-2-0-hardening.md` (sprints 010-015).

### Included

- S-1 through S-5 (sprint 010, Ground truth): get main's CI green again (ruff check . was
  failing on tests/test_gen_loop_set_e.py since 2026-09-05); commit compose.yaml and
  .env.example for the first time and fix the review server's auth default so an empty
  REVIEW_TOKEN no longer silently disables auth; clear the untracked/modified hygiene
  ledger; take a read-only production snapshot; this scope declaration.
- S-6 through S-9 (sprint 011, Fail closed): a durable per-episode stage-status artifact
  with typed outcomes so a failed repair/signs/mux stage can never produce a
  current-looking .done stamp; merge_pass.sh captures and classifies exit codes; a
  transient signs-extraction failure is distinguished from a genuinely signs-free episode;
  the MP4-to-MKV conversion's stamp-before-remove ordering gets crash/failure tests and a
  documented recovery policy.
- S-10 through S-13 (sprint 012, Provenance and policy): words.json schema v2 persists
  compute_type and beam_size and read_words() compares model/initial_prompt/compute_type/
  beam_size against the current config, counting mismatches instead of only checking
  transcribe_version (S-10); the unanchored-repair rollout is reconciled against the
  3-episode human review that justified it, including the 4 outstanding S31 verdicts
  recorded through the actual decision store (S-11); the phonetic-name-guard issue is
  closed as resolved by a different design (S-12); the REPAIR_BACKEND_SECONDARY
  recommendation is retired from IMPROVEMENTS.md and REVIEW.md (S-13).
- S-14 through S-16 (sprint 013, Posture and liveness): every data surface of the review
  server — the /api/ routes and the rendered pages — is gated behind the same token as
  writes, and REQUIRE_TOKEN=1 hard-fails startup if auth ends up disabled anyway (S-14);
  a real-socket HTTP integration test covers auth, slow reads and the concurrency bound
  (S-15); a heartbeat file, a GET /healthz route and a Docker HEALTHCHECK let liveness be
  checked without inferring it from an idle-looking container (S-16).
- S-17 through S-20 (sprint 014, Measurement): tools/timing_compare.py's real-media
  validation (T12) runs on 3 representative shows with a written go/no-go report, and
  specs/timing-compare/tasks.md's stale checklist is reconciled with what already shipped
  on main (S-17); the queue/publish operational checklist (timers, order-file drift,
  manifest policy) is verified live (S-18); the storage/host checklist is closed and
  FFMPEG_TIMEOUT's default is raised from 600 s to 1800 s, measured too short against a
  556 MB episode on the production NFS mount (S-19); the signs/songs-extraction prototype
  (tools/sns_extract.py) is built read-only with a false-positive inventory (S-20).
- S-21 and S-22 (sprint 015, Release): the osv-scanner/pyproject extractor gap is
  tracked and the uv.lock scanning decision recorded (S-21); the 0.2.0 release itself
  (S-22).

### Deferred

Carried forward from the 2026-09-21 weekly plan's "Beyond v0.2.0 / visible backlog" — not
silently promoted into this release:

- Web UI dashboard expansion, glossary editor, community glossary auto-fetch/push.
- Full decoder/config fingerprint migration if not taken as S-10 through S-13 this release.
- Full cross-host locking/claim mechanism beyond the current "never run two workers"
  operational rule.
- Full ASS coordinate transformation for mismatched PlayResX/PlayResY; the current
  timing/signs work only warns.
- Card splitting as a broader automatic feature; card_split.py stays deliberately limited
  to human corrections.
- Automatic subtitle-repository reopen sweep; the beta design explicitly chose manual
  reopen.
- Full CI/workflow consolidation if the current GitHub beta workflows are green; do not
  relitigate launch mechanics unless a concrete failure is found.
- V1/V2 polish backlog items: style-collision logs, WrapStyle audit, font MIME warnings,
  mux.partners() optimization, extra data-file extraction, and broad observability
  polish, unless promoted by evidence from post-beta checks.
- Phase-1 timing gating (using the timing-compare signal to drop/flag/snap cards): a
  separate spec, written only if S-17's go/no-go says GO.

### Fixed

- `gen_loop.sh`: a verify pass that ran past `VERIFY_TIMEOUT` (1200s) took the container
  down with exit code 124. The wrapper `timeout ...; rc=$?` was a _standalone_ command under
  "verify TIMED OUT … (continuing)" message that was already written to handle exactly this
  case — the message's `[ $rc -eq 124 ] && echo …` never got a chance to run because the
  shell had already exited. Same `&& rc=0 || rc=$?` pattern `generate.py` (line 96) already
  uses to keep crash-resume alive: the compound's last subcommand is always 0, so `set -e`
  cannot trip on the `timeout`'s 124, and the real rc is captured for the message. Measured
  on vm102 across the 14h ending 2026-09-05 14:00 EDT: every container restart in the
  window exited with code 124 (journal-confirmed via `journalctl -u docker … exitCode=124`),
  and `VERIFY_TIMEOUT` firing on One Pace (the WATCH_QUEUE_PIN show, run first) lands
  within 2s of every measured exit. After the fix, a timed-out verify logs the existing
  "verify TIMED OUT … (continuing; terms stay unverified)" line and the sweep continues.
- `gen_loop.sh`: the ACQUIRE `timeout` (line 64) was already guarded with `|| echo …`, so
  it was never the trigger — kept the existing wording and added a one-line cross-reference
  comment so the next reader does not "fix" the asymmetry by removing the ACQUIRE guard.

- `export_subtitles`: the public repository publishes `Show - SxxExx - Episode Title`, not
  the media filename. The encode's provenance (`[WEBDL-1080p][8bit][AAC 2.0][x264]-VARYG`,
  and the unbracketed `1080p 6ch x265` shape) is meaningful in a library and is noise on a
  subtitle download. Measured against the production library: 386 of 845 completed episodes
  are renamed, 459 already matched and are untouched — including all 48 episodes already
  published, so nothing in the repository moves for this.
- `export_subtitles`: an episode this run could not export is not thereby unpublished. The
  manifest was rebuilt from what a single run managed to export, so a library gone stale
  against a `TEXT_VERSION` bump qualified nothing and emptied a manifest describing 48
  episodes whose 96 files were sitting untouched beside it -- reached the public repository
  on 2026-09-04 and was reverted. An entry is now carried forward while its files are still
  in the repository, and dropped only once they are gone.
- `export_subtitles`: a show that publishes nothing no longer has a manifest file created
  for it. The file's existence is the claim "this show is published", and the publish script
  runs the exporter over every directory in the library -- 95 of them on 2026-09-04, all
  with nothing to ship. An existing manifest is still rewritten, so a set that shrinks to
  zero is recorded rather than left stale.
- `publish_subtitles.sh`: `GITHUB_PAT`/`GITHUB_USER`, when the deployment supplies them,
  authenticate the push through a credential helper that reads them from the environment.
  The token is never written into the checkout's remote URL and never passed as an
  argument, so it cannot leak through `.git/config` or `ps`. Unset, the push uses whatever
  credentials the environment already carries.
- `publish_subtitles.sh`: the subtitle checkout is declared a safe directory before it is
  read. It is a bind mount into a container running as root, so git refused the host-owned
  repository as "dubious ownership" -- verified on the real deployment, where every
  scheduled run would have died at `git status`. The missing-git check also moved to the
  top of the script: the library walk takes minutes, and a run that discovers its missing
  tool at the end has already spent them.
- `publish_subtitles.sh`: an environment without `git` is refused (exit 3) instead of
  reading as "nothing changed - no commit". Observed 2026-09-04 on vm102: the container
  image carried no git, so a full library sweep reported success and published nothing.
  `git` is now installed in `Dockerfile.builder`, which is where the publish path runs.
- `export_subtitles`: two encodes of one episode (they differ only by a release tag, e.g. a
  `[JA+EN]` re-release — 19 titles across 38 files in the library) now publish once and are
  counted as `duplicate-encode`. Previously the second silently overwrote the first's files
  and the manifest carried two entries under one key, which republished the pair on every
  sweep as the winner alternated.

## 0.1.0 - 2026-09-04

The first public beta. Everything below shipped before the first tag; the pipeline's own
output versions (v2-v8) are listed at the end, since they are what decides whether an
episode already in your library is stale.

### Added

- Per-show glossary acquisition, arc/episode-scoped: wiki-mined proper nouns admitted per
  episode rather than per franchise, with per-token provenance and a repair-weighting pass
  by episode/arc tags.
- Review page: user-selectable sort order (chronological, queue order, longest-first,
  alongside the measured risk-first default) on both the episode and shared-lines pages.
- `tools/export_reviewed.py` / `tools/export_subtitles.py` — publish dubtitles to a public
  subtitle repository, gated on full human review or (separately) on pipeline completion.
- `docs/wiki/` — the wiki content lives in this repository now and mirrors to both GitHub
  and the self-hosted Forgejo wiki via `tools/sync_wiki.sh`.
- [XenaRathon/DubTitlerr-glossaries](https://github.com/XenaRathon/DubTitlerr-glossaries) —
  the community glossary repository.
- `decisions.locked()` — a cross-process file lock around a show's decision-store
  load-modify-save, closing a race between the review server and the `unresolved.py` CLI.
- `tools/asr_bakeoff.py` — the ASR bakeoff harness: runs faster-whisper, NeMo (Parakeet,
  Canary) and Qwen3-ASR entrants over the same episodes on one card, and scores them against
  a real reference transcript rather than against each other. Measured results for a 6GB
  GTX 1060 and an 8GB RTX 2070 Super are in `docs/asr-bakeoff/`, and the reasoning behind the
  `WHISPER_MODEL`/`COMPUTE_TYPE` defaults is now written down in the wiki's
  _Choosing an ASR model_ rather than assumed.

### Fixed

- `dub_signs_merge`: a style-name guess (e.g. a style named like a dialogue track) now
  yields to an unambiguous keep-tag (positioned, karaoke, drawing, animated) — previously
  such signs/song events were silently dropped from the merged track.
- `dub_signs_merge`: whisper's transcription of a sung OP/ED is dropped from the dub track
  and the fansub's own song translation is kept instead. Whisper does not transcribe
  Japanese singing, it hallucinates over it (`avg_logprob` -1.7 to -4.1 against -0.3/-0.7
  for ordinary dialogue), and the fansub translation it displaced was being discarded. A
  song's Kanji/Japanese/English sibling styles are now recognised by their shared
  `Opening-`/`ED<N>-` prefix rather than by keyword, so half of each song's on-screen text
  is no longer missing. Only releases whose signs track carries song-family styles are
  affected; a track without them is untouched. Measured 2026-09-02 against the production
  library: SAO, JUJUTSU KAISEN, SPY x FAMILY and Reborn as a Vending Machine as expected,
  and also One Pace seasons 17 and 27 (25-26 dropped cards per S27 episode), which earlier
  notes in this repository wrongly described as having no OP/ED at all. Most other One Pace
  seasons do produce no spans.
  **Forward-only, with a targeted re-open.** This changes the merge stage, not the words or
  the text, so `TEXT_VERSION` does not cover it and an already-muxed episode has no sidecar
  left for the merge to rebuild — it keeps its hallucinated song cards. To correct an
  existing library, point `tools/reopen_for_signs.py` at the shows that have an OP/ED
  (dry run first) and let the next `merge_pass.sh` sweep re-merge and re-mux them. A
  `TEXT_VERSION` bump would also work and would re-mux every episode in the library,
  including the many with no song styles at all.
- `generate.py`: a delayed audio stream's start offset is now carried onto the video
  timeline (measured up to +1745ms on one show), instead of shipping every cue early by
  that delay. **Forward-only.** The offset is applied to the word timestamps before they
  are persisted, so an episode transcribed before this fix has the uncorrected times baked
  into its `words.json` and no text-tier rebuild can recover them — only a re-transcribe
  can, which is why `TRANSCRIBE_VERSION` was deliberately NOT bumped (it would put the
  whole library back through the GPU). Episodes already in your library keep the old
  timing; new ones get the fix.
- `repair.py`: a card the repair stage skips (no fansub anchor, or an unreachable LLM
  backend) no longer discards a human's stored `correct`/`force` verdict for that line —
  it ships the human's text instead of reverting to raw ASR.
- `repair.py`: a merge pass that would strip every repair from an already-repaired episode
  (e.g. a misconfigured backend) now aborts that episode instead of silently reverting it.
- `review_apply`: saving a verdict against an already-muxed episode now re-opens it so the
  correction actually reaches the video, instead of only updating the decision store.
- `export_subtitles`: no manifest entry is written for an episode whose `.ass` extraction
  failed.
- Docs: the `COMPUTE_TYPE` reference row claimed `float16` was the quality setting. The
  bakeoff disproved it — on Pascal cards `float16` does not load at all, and where both load
  the transcripts are equivalent. Precision is a compatibility knob here, not a quality one.

### Pipeline output-version history (see `common.py` for the authoritative log)

- **v9** (2026-09-02) — the hallucination gate drops a card carrying Japanese script: in an
  English dub that is whisper falling back to the Japanese it heard under a song, not a
  low-confidence English line. 1,240 of 395,671 cards across 24 shows, every sampled one an
  OP/ED lyric. Unlike the signs-track song drop, this reaches releases that caption no song
  lyrics at all — and unlike that fix, a `TEXT_VERSION` bump DOES carry it into episodes
  already in your library, on CPU, without re-transcribing.
- **v8** (2026-08-29) — two reflow character-welding fixes (thousands separators, decimal
  points wrongly joined to the previous word).
- **v7** (2026-08-26) — the phonetic name guard widens from substitutions to any gained
  (fabricated) name.
- **v6** (2026-08-26) — repair gains the phonetic name guard: rejects an LLM repair that
  substitutes a proper noun found in neither the glossary nor the original.
- **v5** (2026-08-24) — the single version splits into `TRANSCRIBE_VERSION`/`TEXT_VERSION`,
  so a text-only fix no longer forces a full re-transcribe.
- **v4** (2026-08-21) — hyphenated words no longer ship with a stray space
  ("Gas -Gas" → "Gas-Gas"); 9 One Pace glossary hard-fixes added.
- **v3** (2026-08-20) — sub-`MIN_DUR` cards repaired, multi-line cue wrapping restored,
  sentence punctuation restored before card splitting.
- **v2** (2026-07-27) — fixed a signs-merge bug that rendered captions as solid black
  and duplicated signs across tracks.

[0.2.1]: https://github.com/XenaRathon/DubTitlerr/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/XenaRathon/DubTitlerr/compare/v0.1.0...v0.2.0
[Unreleased]: https://github.com/XenaRathon/DubTitlerr/compare/v0.2.1...HEAD
