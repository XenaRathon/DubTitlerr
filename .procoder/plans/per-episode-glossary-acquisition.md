# per-episode-glossary-acquisition — implementation plan

Status: complete
Spec: .procoder/specs/per-episode-glossary-acquisition.md

## Goal

Narrow `glossary_acquire.acquire()`'s candidate-admission title set from a
show's entire wiki to each token's own contributing episode(s), and use the
same per-episode identity to weight `repair.py`'s prompt terms, without
changing `allpages`'s role as the canonical-spelling authority anywhere
else.

## Architecture

Two new small wiki-fetch primitives in `glossary_verify.py` (Plot-section
link extraction, redirect resolution) compose into a cached per-episode
title fetch, which `glossary_acquire.py` uses as a per-**token** admission
filter (not a per-run one — the union is built from each token's own
contributing episodes, tracked via one new provenance field on harvest's
existing candidate records). `repair.py` gets a parallel per-episode
weighting tier alongside its existing (but load-bearing-broken, see Task 7)
arc-tag tier. Every new wiki call and every fallback is fail-open and
logged, matching this module's existing resilience contract.

## Constraints

- Every new HTTP call (`resolve_redirects`, `fetch_episode_titles`) must
  fail open — return the safest empty/unresolved value on any
  `Exception`, never raise past its caller, mirroring `glossary_verify.py`'s
  existing `_http_json`-call sites (`arc_page_links`, `arc_categories`,
  `fetch_arc_titles`).
- No new runtime dependencies — stdlib, `re`, `urllib`, `json`, `time`,
  `os` only, matching what `glossary_verify.py`/`glossary_acquire.py`
  already import.
- `.nfo` parsing stays regex-only, never an XML parser (untrusted
  third-party input) — matches `glossary.arc_for()`'s existing precedent.
- Every new/changed function needs a docstring one-liner in this
  codebase's existing style (a plain description, `S-<n>` tag optional)
  and must not change the byte-for-byte behavior of any _existing_ public
  function for a caller that passes none of the new optional parameters.
- Run `pytest -q`, `ruff check .`, and `procoder check` after every task;
  each task's steps end with all three green before moving on.

## Task 1: `glossary.source_episodes()` — `.nfo` range parser

Files: `glossary.py` (add function near `arc_for`, `glossary.py:142`),
`tests/test_glossary.py` (add tests near the existing `arc_for` tests).

Interfaces: `glossary.source_episodes(nfo_path: str) -> list[int]`. Pure,
no network, no XML parser. Returns `[]` on a missing file, a missing
`Covers anime episode(s):` line, or any parse failure — never raises.
Consumed by Task 9.

- [ ] Write the failing test in `tests/test_glossary.py`:
      ```python
      def test_source_episodes_parses_a_range(tmp_path):
      p = tmp_path / "ep.nfo"
      p.write_text("<plot>Dressrosa!\n\nCovers anime episode(s): 628 - 631\n</plot>")
      assert glossary.source_episodes(str(p)) == [628, 629, 630, 631]

      def test_source_episodes_parses_comma_and_single_and_mixed_forms(tmp_path):
                          p1 = tmp_path / "a.nfo"
                          p1.write_text("Covers anime episode(s): 628, 630, 645")
                          assert glossary.source_episodes(str(p1)) == [628, 630, 645]
                          p2 = tmp_path / "b.nfo"
                          p2.write_text("Covers anime episode(s): 628")
                          assert glossary.source_episodes(str(p2)) == [628]
                          p3 = tmp_path / "c.nfo"
                          p3.write_text("Covers anime episode(s): 628-630, 645")
                          assert glossary.source_episodes(str(p3)) == [628, 629, 630, 645]

                      def test_source_episodes_absent_line_and_missing_file(tmp_path):
                          p = tmp_path / "d.nfo"
                          p.write_text("<plot>No mapping here.</plot>")
                          assert glossary.source_episodes(str(p)) == []
                          assert glossary.source_episodes(str(tmp_path / "missing.nfo")) == []

                      def test_source_episodes_survives_a_truncated_file(tmp_path):
                          p = tmp_path / "e.nfo"
                          p.write_bytes(b"Covers anime episode(s): 6")  # cut mid-number, still parses as [6]
                          assert glossary.source_episodes(str(p)) == [6]
                      ```
                      Run `pytest tests/test_glossary.py -k source_episodes -q` — expect
                      FAIL with `AttributeError: module 'glossary' has no attribute
                      'source_episodes'`.

- [ ] Implement in `glossary.py`, directly above `arc_for` (matching that
      function's regex-only, size-capped-read, never-raise contract):
      ```python
      _SOURCE_EPISODES_RE = re.compile(r"Covers anime episode\(s\):\s*([^\n<]+)")

      def source_episodes(nfo_path: str) -> list[int]:
                          """Absolute source-episode numbers from a re-cut show's per-episode .nfo,
                          e.g. "Covers anime episode(s): 628 - 631" -> [628, 629, 630, 631].
                          Regex-only, no XML parser -- third-party .nfo files are untrusted input,
                          matching arc_for's precedent. [] on any absence or malformed line."""
                          try:
                              with open(nfo_path, encoding="utf-8", errors="replace") as f:
                                  text = f.read(64 * 1024)
                          except OSError:
                              return []
                          m = _SOURCE_EPISODES_RE.search(text)
                          if not m:
                              return []
                          out: list[int] = []
                          for part in m.group(1).split(","):
                              part = part.strip()
                              if not part:
                                  continue
                              rng = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
                              if rng:
                                  lo, hi = int(rng.group(1)), int(rng.group(2))
                                  if lo <= hi:
                                      out.extend(range(lo, hi + 1))
                                  continue
                              if part.isdigit():
                                  out.append(int(part))
                          return out
                      ```

- [ ] Run `pytest tests/test_glossary.py -k source_episodes -q` — expect
      PASS.
- [ ] Run `ruff check glossary.py tests/test_glossary.py` — expect 0
      findings. Commit: `feat(glossary): parse a re-cut episode's .nfo source-episode mapping`.

## Task 2: `glossary_verify.plot_section_links()` + shared link-extraction helper

Files: `glossary_verify.py` (extract `_extract_links` from `arc_page_links`
at `glossary_verify.py:289-326`, add `plot_section_links`),
`tests/test_glossary_verify.py`.

Interfaces: `glossary_verify.plot_section_links(wikitext: str) -> set[str]`
— pure, no network. `glossary_verify._extract_links(wt: str) -> set[str]`
— private, shared by `arc_page_links` and `plot_section_links`. Consumed by
Task 4.

- [ ] Write the failing tests in `tests/test_glossary_verify.py`, next to
      `test_arc_page_links_supply_the_names_categories_miss`:
      ```python
      def test_plot_section_links_extracts_only_the_plot_section():
      wt = (
      "{{Infobox|junk=[[Navbox Junk]]}}\n"
      "== Plot ==\n"
      "[[Kirito]] and [[Asuna]] fight. <ref>[[Reference Junk]]</ref>\n"
      "== Trivia ==\n"
      "[[Should Not Appear]] is mentioned here.\n"
      )
      links = gv.plot_section_links(wt)
      assert {"Kirito", "Asuna"} <= links
      assert "Should Not Appear" not in links
      assert "Reference Junk" not in links
      assert "Navbox Junk" not in links

      def test_plot_section_links_filters_file_and_image_links():
                          wt = "== Plot ==\n[[Kirito]] draws [[File:Sword.png]] and [[Image:Map.png]].\n"
                          links = gv.plot_section_links(wt)
                          assert links == {"Kirito"}

                      def test_plot_section_links_is_empty_with_no_plot_heading():
                          assert gv.plot_section_links("No headings here, just [[Kirito]].") == set()

                      def test_plot_section_links_is_case_insensitive_on_the_heading():
                          wt = "==PLOT==\n[[Kirito]] appears.\n"
                          assert gv.plot_section_links(wt) == {"Kirito"}
                      ```
                      Run `pytest tests/test_glossary_verify.py -k plot_section_links -q`
                      — expect FAIL with `AttributeError: module 'glossary_verify' has no
                      attribute 'plot_section_links'`.

- [ ] Refactor `arc_page_links` (`glossary_verify.py:289-326`): extract
      lines 312-325 (the template/ref-strip and link-filter body, from
      `for _ in range(4):` through `return out`) into a new private
      function placed directly above `arc_page_links`:
      `python
def _extract_links(wt: str) -> set[str]:
  """[[...]] links from wikitext with templates/refs stripped and non-entity
  links (Category:/File:/Image:/w:, lowercase-first, bare Chapter/Episode/
  Volume N) dropped. Shared by arc_page_links (whole page) and
  plot_section_links (one section) so the filter cannot drift between them."""
  for _ in range(4):  # nested templates
      wt = re.sub(r"\{\{[^{}]*\}\}", " ", wt)
  wt = re.sub(r"<ref[^>]*>.*?</ref>", " ", wt, flags=re.S)
  wt = re.sub(r"<[^>]+>", " ", wt)
  out = set()
  for link in re.findall(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", wt):
      link = link.strip()
      if not link or link[:1].islower():
          continue
      if link.startswith(("Category:", "File:", "Image:", "w:")):
          continue
      if re.match(r"^(Chapter|Episode|Volume)\s+\d+$", link):
          continue
      out.add(link)
  return out
`
      Then replace `arc_page_links`'s body from `for _ in range(4):`
      onward with `return _extract_links(wt)`.
- [ ] Add, directly below `_extract_links`:
      ```python
      _PLOT_SECTION_RE = re.compile(r"==\s*Plot\s*==(.*?)(?=\n==[^=]|\Z)", re.S | re.I)

      def plot_section_links(wikitext: str) -> set[str]:
                          """Entity links from a wiki EPISODE page's Plot section only -- the
                          per-episode candidate primitive [S-2]. Measured 2026-08-29: 26-30 correct
                          links per episode versus 1,281+ franchise-wide, zero navbox pollution.
                          Pure/no network; the caller supplies wikitext already fetched."""
                          m = _PLOT_SECTION_RE.search(wikitext)
                          if not m:
                              return set()
                          return _extract_links(m.group(1))
                      ```

- [ ] Run `pytest tests/test_glossary_verify.py -q` (the WHOLE file, not
      just the new tests — confirms the `arc_page_links` refactor changed
      nothing) — expect PASS, including every pre-existing
      `test_arc_page_links_*` test unchanged.
- [ ] Run `ruff check glossary_verify.py tests/test_glossary_verify.py` —
      expect 0 findings. Commit:
      `feat(glossary_verify): extract Plot-section links, sharing arc_page_links' filter`.

## Task 3: `glossary_verify.resolve_redirects()`

Files: `glossary_verify.py`, `tests/test_glossary_verify.py`.

Interfaces: `glossary_verify.resolve_redirects(wiki_api: str, titles:
set[str]) -> set[str]`. Consumed by Task 4.

- [ ] Write the failing tests, using this codebase's `monkeypatch.setattr(gv,
"_http_json", ...)` convention (see
      `test_arc_titles_unions_the_categories_and_follows_continuation`):
      ```python
      def test_resolve_redirects_follows_an_input_redirect_to_its_target(): # "Kirito" is itself a redirect page; the API reports it under query.redirects.
      def fake(url):
      assert "redirects=1" in url and "prop=redirects" in url
      return {
      "query": {
      "redirects": [{"from": "Kirito", "to": "Kirigaya Kazuto"}],
      "pages": {"1": {"title": "Kirigaya Kazuto"}},
      }
      }

          titles = gv.resolve_redirects.__wrapped__(fake, "https://x/api.php", {"Kirito"}) \
                              if hasattr(gv.resolve_redirects, "__wrapped__") else None
                      ```
                      The wrapper line above is scaffolding only for illustrating intent;
                      write the REAL test using `monkeypatch`, matching this file's actual
                      convention:
                      ```python
                      def test_resolve_redirects_follows_an_input_redirect_to_its_target(monkeypatch):
                          def fake(url):
                              return {
                                  "query": {
                                      "redirects": [{"from": "Kirito", "to": "Kirigaya Kazuto"}],
                                      "pages": {"1": {"title": "Kirigaya Kazuto", "redirects": []}},
                                  }
                              }

                          monkeypatch.setattr(gv, "_http_json", fake)
                          out = gv.resolve_redirects("https://x/api.php", {"Kirito"})
                          assert "Kirigaya Kazuto" in out

                      def test_resolve_redirects_pulls_in_incoming_redirects_of_a_direct_link(monkeypatch):
                          # "Kirigaya Kazuto" linked directly; other pages ("Kirito") redirect TO it.
                          def fake(url):
                              return {
                                  "query": {
                                      "pages": {
                                          "1": {
                                              "title": "Kirigaya Kazuto",
                                              "redirects": [{"title": "Kirito"}],
                                          }
                                      }
                                  }
                              }

                          monkeypatch.setattr(gv, "_http_json", fake)
                          out = gv.resolve_redirects("https://x/api.php", {"Kirigaya Kazuto"})
                          assert {"Kirigaya Kazuto", "Kirito"} <= out

                      def test_resolve_redirects_fails_open_to_the_input_set(monkeypatch):
                          def boom(url):
                              raise OSError("network down")

                          monkeypatch.setattr(gv, "_http_json", boom)
                          assert gv.resolve_redirects("https://x/api.php", {"Kirito", "Asuna"}) == {"Kirito", "Asuna"}

                      def test_resolve_redirects_chunks_over_fifty_titles(monkeypatch):
                          calls = []

                          def fake(url):
                              calls.append(url)
                              return {"query": {"pages": {}}}

                          monkeypatch.setattr(gv, "_http_json", fake)
                          gv.resolve_redirects("https://x/api.php", {f"T{i}" for i in range(120)})
                          assert len(calls) == 3  # ceil(120 / 50)
                      ```
                      Delete the illustrative `__wrapped__` scaffold above before running
                      — it is not real test code. Run
                      `pytest tests/test_glossary_verify.py -k resolve_redirects -q` —
                      expect FAIL with `AttributeError`.

- [ ] Implement in `glossary_verify.py`, below `_extract_links`:
      ``python
def resolve_redirects(wiki_api: str, titles: set[str]) -> set[str]:
  """Both redirect directions in one MediaWiki call per chunk of <=50 titles:
  an input title that is itself a redirect resolves to its target
  (query.redirects), and other pages redirecting TO a resolved target are
  pulled in too (each page's own "redirects" list). Fails open to the
  unresolved input set on any error -- never drops a title outright."""
  if not titles:
      return set()
  out = set(titles)
  items = sorted(titles)
  for i in range(0, len(items), 50):
      chunk = items[i : i + 50]
      url = (
          wiki_api
          + "?action=query&redirects=1&prop=redirects&rdlimit=500&format=json&titles="
          + urllib.parse.quote("|".join(chunk))
      )
      try:
          resp = _http_json(url)
      except Exception:
          continue  # this chunk's titles stay unresolved, already in `out`
      q = resp.get("query", {})
      for r in q.get("redirects", []):
          frm, to = r.get("from"), r.get("to")
          if frm and to:
              out.discard(frm)
              out.add(to)
      for page in q.get("pages", {}).values():
          title = page.get("title")
          if not title:
              continue
          out.add(title)
          for inc in page.get("redirects", []):
              inc_title = inc.get("title")
              if inc_title:
                  out.add(inc_title)
  return out
``
- [ ] Run `pytest tests/test_glossary_verify.py -k resolve_redirects -q`
      — expect PASS.
- [ ] **Manual step, not automated**: before this task is considered done,
      run one live call against a real Fandom wiki (e.g.
      `https://onepiece.fandom.com/api.php`) with a known redirect pair,
      confirm the response shape matches what the tests assume, and paste
      the captured JSON as a comment above the test file's redirect tests
      or as a new fixture file `tests/fixtures/mediawiki_redirects_sample.json`
      referenced from a comment (per Luna review 2026-09-01, F5 — a mocked
      test alone must not be the only evidence this parses real API
      output).
- [ ] Run `ruff check glossary_verify.py tests/test_glossary_verify.py` —
      expect 0 findings. Commit:
      `feat(glossary_verify): resolve wiki redirects both directions in one call`.

## Task 4: `glossary_verify.fetch_episode_titles()` — per-show/per-page TTL cache

Files: `glossary_verify.py`, `tests/test_glossary_verify.py`.

Interfaces: `glossary_verify.fetch_episode_titles(wiki_api: str, show_key:
str, page_title: str) -> list[str]`. Consumed by Task 5.

- [ ] Write the failing tests:
      ```python
      def test_fetch_episode_titles_caches_a_positive_result(monkeypatch, tmp_path):
      monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path))
      calls = []

          def fake(url):
                              calls.append(url)
                              return {"parse": {"wikitext": {"*": "== Plot ==\n[[Kirito]]\n"}}}

                          monkeypatch.setattr(gv, "_http_json", fake)
                          first = gv.fetch_episode_titles("https://x/api.php", "SAO", "Episode 05")
                          second = gv.fetch_episode_titles("https://x/api.php", "SAO", "Episode 05")
                          assert first == second == ["Kirito"]
                          assert len(calls) == 1  # second call hit the cache

                      def test_fetch_episode_titles_does_not_cache_a_negative_result(monkeypatch, tmp_path):
                          monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path))
                          calls = []

                          def fake(url):
                              calls.append(url)
                              return {"parse": {"wikitext": {"*": "no plot section here"}}}

                          monkeypatch.setattr(gv, "_http_json", fake)
                          gv.fetch_episode_titles("https://x/api.php", "SAO", "Episode 99")
                          gv.fetch_episode_titles("https://x/api.php", "SAO", "Episode 99")
                          assert len(calls) == 2  # retried, not cached-empty

                      def test_fetch_episode_titles_expires_past_the_ttl(monkeypatch, tmp_path):
                          monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path))
                          monkeypatch.setattr(gv, "WIKI_TTL", 0)  # expire immediately
                          calls = []

                          def fake(url):
                              calls.append(url)
                              return {"parse": {"wikitext": {"*": "== Plot ==\n[[Kirito]]\n"}}}

                          monkeypatch.setattr(gv, "_http_json", fake)
                          gv.fetch_episode_titles("https://x/api.php", "SAO", "Episode 05")
                          gv.fetch_episode_titles("https://x/api.php", "SAO", "Episode 05")
                          assert len(calls) == 2
                      ```
                      Run `pytest tests/test_glossary_verify.py -k fetch_episode_titles -q`
                      — expect FAIL with `AttributeError`.

- [ ] Implement in `glossary_verify.py`, below `resolve_redirects`:
      `python
def fetch_episode_titles(wiki_api: str, show_key: str, page_title: str) -> list[str]:
  """Cached Plot-section entity titles for one wiki episode page. One JSON
  cache file per SHOW (not per page), each page entry independently
  WIKI_TTL-gated -- mirrors fetch_titles' TTL-file pattern. Only positive
  results are cached, mirroring fetch_titles' own asymmetry: a missing page
  is retried every call rather than cached empty forever."""
  os.makedirs(CACHE_DIR, exist_ok=True)
  cache_path = os.path.join(CACHE_DIR, re.sub(r"[^A-Za-z0-9]+", "_", show_key) + "_episodes.json")
  try:
      doc = json.load(open(cache_path))
  except (OSError, ValueError):
      doc = {}
  pages = doc.get("pages", {}) if doc.get("api") == wiki_api else {}
  entry = pages.get(page_title)
  if entry and (time.time() - entry.get("fetched_at", 0)) < WIKI_TTL:
      return entry["titles"]
  url = wiki_api + "?action=parse&prop=wikitext&format=json&page=" + urllib.parse.quote(page_title)
  try:
      wt = _http_json(url)["parse"]["wikitext"]["*"]
  except Exception:
      return []
  links = resolve_redirects(wiki_api, plot_section_links(wt))
  titles = sorted(links)
  if titles:
      pages[page_title] = {"fetched_at": time.time(), "titles": titles}
      json.dump({"api": wiki_api, "pages": pages}, open(cache_path, "w"))
  return titles
`
- [ ] Run `pytest tests/test_glossary_verify.py -k fetch_episode_titles -q`
      — expect PASS.
- [ ] Run `ruff check glossary_verify.py tests/test_glossary_verify.py` —
      expect 0 findings. Commit:
      `feat(glossary_verify): cache per-episode wiki title fetches`.

## Task 5: `glossary_verify.episode_page_titles()` — orchestrator

Files: `glossary_verify.py`, `tests/test_glossary_verify.py`.

Interfaces: `glossary_verify.episode_page_titles(wiki_api: str, show_key:
str, page_titles: list[str]) -> tuple[set[str], list[str], list[str]]` —
`(union, resolved_pages, failed_pages)`. Consumed by Task 9.

- [ ] Write the failing test:
      ```python
      def test_episode_page_titles_splits_resolved_and_failed(monkeypatch, tmp_path):
      monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path))

          def fake(url):
                              if "Episode+629" in url or "Episode%20629" in url:
                                  return {"parse": {"wikitext": {"*": "no plot section"}}}
                              return {"parse": {"wikitext": {"*": "== Plot ==\n[[Rebecca]]\n"}}}

                          monkeypatch.setattr(gv, "_http_json", fake)
                          union, resolved, failed = gv.episode_page_titles(
                              "https://x/api.php", "One Pace", ["Episode 628", "Episode 629"]
                          )
                          assert union == {"Rebecca"}
                          assert resolved == ["Episode 628"]
                          assert failed == ["Episode 629"]
                      ```
                      Run `pytest tests/test_glossary_verify.py -k episode_page_titles -q`
                      — expect FAIL with `AttributeError`.

- [ ] Implement in `glossary_verify.py`, below `fetch_episode_titles`:
      `python
def episode_page_titles(wiki_api: str, show_key: str, page_titles: list[str]) -> tuple[set[str], list[str], list[str]]:
  """Union Plot-section titles across several wiki pages, reporting which
  pages resolved and which didn't -- the split S-13's partial-mapping
  status needs, without a second pass over the same pages."""
  union: set[str] = set()
  resolved: list[str] = []
  failed: list[str] = []
  for title in page_titles:
      titles = fetch_episode_titles(wiki_api, show_key, title)
      if titles:
          union |= set(titles)
          resolved.append(title)
      else:
          failed.append(title)
  return union, resolved, failed
`
- [ ] Run `pytest tests/test_glossary_verify.py -k episode_page_titles -q`
      — expect PASS.
- [ ] Run `ruff check glossary_verify.py tests/test_glossary_verify.py` —
      expect 0 findings. Commit:
      `feat(glossary_verify): union episode-page titles, reporting resolved vs failed pages`.

## Task 6: `harvest_candidates()` gains `contributing_stems`

Files: `glossary_acquire.py` (`_candidate` at `:246-260`,
`harvest_candidates` at `:263-294`), `tests/test_glossary_acquire.py`
(including a fix to the existing exact-set test named below).

Interfaces: `_candidate()`'s returned dict gains key `"contributing_stems":
set()`. Consumed by Task 10 (admission union) and Task 11 (episode
tagging).

- [ ] First, fix the EXISTING test that will break:
      `test_candidate_record_carries_source_and_forms`
      (`tests/test_glossary_acquire.py:1158-1174`) asserts
      `set(c) == {"variant", "source", "raw_forms", "normalized_forms",
"settled_target", "occurrence_count", "episode_count", "contexts"}`.
      Add `"contributing_stems"` to that literal set now, so running the
      test suite BEFORE implementing shows this one exact-set assertion
      newly failing once the field is added (confirms the test is
      actually checking the field set, not a false pass).
- [ ] Write the new failing test, next to
      `test_harvest_scope_is_recorded_with_the_counts`:
      ```python
      def test_harvest_candidates_tracks_contributing_stems(tmp_path):
      _write_conf(tmp_path, "Ep01", ["We fought Hazzard here."])
      _write_conf(tmp_path, "Ep02", ["Hazzard returned."])
      cands, _mid, _scope = ga.harvest_candidates(str(tmp_path))
      c = cands["Hazzard"]
      stems = {s.rsplit("/", 1)[-1] for s in c["contributing_stems"]}
      assert stems == {"Ep01", "Ep02"}

      def test_harvest_candidates_single_episode_token_has_one_stem(tmp_path):
                          _write_conf(tmp_path, "Ep01", ["Only here: Marigold."])
                          cands, _mid, _scope = ga.harvest_candidates(str(tmp_path))
                          stems = {s.rsplit("/", 1)[-1] for s in cands["Marigold"]["contributing_stems"]}
                          assert stems == {"Ep01"}
                      ```
                      Run `pytest tests/test_glossary_acquire.py -k "contributing_stems or carries_source_and_forms" -q`
                      — expect the new tests to FAIL with `KeyError: 'contributing_stems'`
                      and the fixed exact-set test to FAIL (field missing) until the
                      implementation lands.

- [ ] In `_candidate()` (`glossary_acquire.py:246-260`), add one field to
      the returned dict:
      `python
def _candidate(variant: str, source: str) -> dict:
  return {
      "variant": variant,
      "source": source,
      "raw_forms": {},
      "normalized_forms": [],
      "settled_target": None,
      "occurrence_count": 0,
      "episode_count": 0,
      "contexts": [],
      "contributing_stems": set(),
  }
`
- [ ] In `harvest_candidates()`'s per-episode loop
      (`glossary_acquire.py:280-291`), add one line inside the `for tok in
set(bare) | set(poss):` loop, alongside the existing
      `c["episode_count"] += 1`:
      `python
c["contributing_stems"].add(stem)
`
- [ ] Run `pytest tests/test_glossary_acquire.py -q` (the whole file) —
      expect PASS, including the fixed exact-set test and every other
      existing test in the file (confirms nothing else reads `_candidate`'s
      key set exhaustively and broke).
- [ ] Run `ruff check glossary_acquire.py tests/test_glossary_acquire.py`
      — expect 0 findings. Commit:
      `feat(glossary_acquire): track which episodes contributed each harvested token`.

## Task 7: `glossary.load_dict()` propagates `arc_tags`/`episode_tags`

Files: `glossary.py` (`load_dict` at `:66-84`), `tests/test_glossary.py`.

Interfaces: `glossary.load_dict()`'s returned dict gains keys `"arc_tags"`
and `"episode_tags"` (each `{}` when absent from the input). No signature
change. Consumed by Task 11, Task 12.

- [ ] Write the failing test in `tests/test_glossary.py`:
      ```python
      def test_load_dict_propagates_arc_and_episode_tags():
      cfg = {
      "show": "One Piece",
      "names": ["Doflamingo"],
      "arc_tags": {"doflamingo": ["Dressrosa"]},
      "episode_tags": {"doflamingo": ["S31E01"]},
      }
      out = glossary.load_dict(cfg)
      assert out["arc_tags"] == {"doflamingo": ["Dressrosa"]}
      assert out["episode_tags"] == {"doflamingo": ["S31E01"]}

      def test_load_dict_defaults_tags_to_empty_when_absent():
                          out = glossary.load_dict({"show": "X"})
                          assert out["arc_tags"] == {}
                          assert out["episode_tags"] == {}

                      def test_load_reaches_repair_glossary_terms_through_the_real_load_path(tmp_path):
                          """The regression this task exists to fix: _glossary_terms must see
                          arc_tags/episode_tags written by glossary.load(path), not only a
                          hand-built test dict."""
                          import repair

                          p = tmp_path / "Show.json"
                          p.write_text(json.dumps({
                              "show": "Show",
                              "names": ["Doflamingo", "Zoro"],
                              "arc_tags": {"doflamingo": ["Dressrosa"]},
                          }))
                          gloss = glossary.load(str(p))
                          terms = repair._glossary_terms(gloss, arc="Dressrosa").split(", ")
                          assert terms.index("Doflamingo") < terms.index("Zoro")
                      ```
                      Run `pytest tests/test_glossary.py -k "load_dict_propagates or load_reaches_repair" -q`
                      — expect FAIL: the first two with `KeyError`, the third with the
                      terms NOT prioritising `Doflamingo` (proving today's `load()` ->
                      `_glossary_terms` path is broken).

- [ ] In `load_dict()` (`glossary.py:66-84`), add two keys to the returned
      dict:
      `python
return {
  "show": cfg.get("show", ""),
  "names": list(cfg.get("names") or []),
  "phrases": list(cfg.get("phrases") or []),
  "token_fixes": token_fixes,
  "phrase_fixes": phrase_fixes,
  "initial_prompt": cfg.get("initial_prompt") or "",
  "unanchored_repair": bool(cfg.get("unanchored_repair")),
  "arc_tags": dict(cfg.get("arc_tags") or {}),
  "episode_tags": dict(cfg.get("episode_tags") or {}),
}
`
- [ ] Run `pytest tests/test_glossary.py tests/test_repair.py -q` (both
      files — this touches a shared data shape) — expect PASS, including
      every existing `_tagged_gloss()`-based arc-tag test in
      `test_repair.py` (they hand-build `gloss` with `arc_tags` already
      present, so adding keys to `load_dict`'s output does not affect
      them).
- [ ] Run `ruff check glossary.py tests/test_glossary.py` — expect 0
      findings. Commit:
      `fix(glossary): load_dict was silently dropping arc_tags, making repair's arc weighting unreachable in production`.

## Task 8: `ordering.episode_key()`

Files: `ordering.py`, `tests/test_ordering.py`.

Interfaces: `ordering.episode_key(path: str) -> str | None`. Consumed by
Task 9, Task 11, Task 12.

- [ ] Write the failing test in `tests/test_ordering.py`, next to the
      `season_ep` tests:
      ```python
      def test_episode_key_formats_zero_padded_season_and_episode():
      assert o.episode_key(paths("20:1")[0]) == "S20E01"
      assert o.episode_key(paths("1:10")[0]) == "S01E10"

      def test_episode_key_is_none_with_no_season_tag():
                          assert o.episode_key("/media/Anime Library/One Pace/Specials/A Movie.mkv") is None
                      ```
                      Run `pytest tests/test_ordering.py -k episode_key -q` — expect FAIL
                      with `AttributeError: module 'ordering' has no attribute
                      'episode_key'`.

- [ ] Implement in `ordering.py`, directly below `season_ep`:
      `python
def episode_key(path: str) -> str | None:
  """"SxxExx" identity for an episode, or None with no SxxExx in the
  filename. One canonical stringification of season_ep(), shared by
  repair.py's per-episode prompt weighting and glossary_acquire.py's
  episode-tag writes so the two cannot disagree about a key's spelling."""
  s, e = season_ep(path)
  if s == NO_SEASON:
      return None
  return f"S{s:02d}E{e:02d}"
`
- [ ] Run `pytest tests/test_ordering.py -q` — expect PASS.
- [ ] Run `ruff check ordering.py tests/test_ordering.py` — expect 0
      findings. Commit: `feat(ordering): a canonical SxxExx episode key`.

## Task 9: `glossary_acquire.episode_admission_titles()`

Files: `glossary_acquire.py` (new function, placed above `acquire()` at
`:829`), `tests/test_glossary_acquire.py`.

Interfaces:

```python
def episode_admission_titles(
    video: str, gloss: dict, wiki_api: str, show: str, source_episodes_fn=glossary.source_episodes,
) -> tuple[set[str] | None, str, dict]
```

Returns `(titles_or_None, method, detail)`. `method` is one of
`"absolute"`, `"relative"`, `"fallback-allpages"`, `"unscoped"`,
`"no-episode-tag"`. `detail` is `{"nfo_present": bool, "nfo_parsed": bool,
"partial_pages": list[str]}`. `source_episodes_fn` is injectable for
testing without a real `.nfo` file. Consumed by Task 10.

- [ ] Write the failing tests:
      ```python
      def test_admission_titles_unscoped_when_no_pattern_declared(tmp_path):
      video = str(tmp_path / "S01E05.mkv")
      open(video, "w").close()
      titles, method, detail = ga.episode_admission_titles(video, {}, "https://x/api.php", "Show")
      assert titles is None and method == "unscoped"

      def test_admission_titles_absolute_wins_when_it_resolves(tmp_path, monkeypatch):
                          video = str(tmp_path / "S31E01.mkv")
                          open(video, "w").close()
                          nfo = str(tmp_path / "S31E01.nfo")
                          open(nfo, "w").write("Covers anime episode(s): 628")
                          gloss = {"episode_page_pattern_absolute": "Episode {n}", "episode_page_pattern_relative": "Rel {e}"}
                          monkeypatch.setattr(ga.glossary_verify, "episode_page_titles", lambda api, show, pages: ({"Rebecca"}, pages, []))
                          titles, method, detail = ga.episode_admission_titles(video, gloss, "https://x/api.php", "Show")
                          assert titles == {"Rebecca"} and method == "absolute"

                      def test_admission_titles_falls_back_and_reports_nfo_health(tmp_path, monkeypatch):
                          video = str(tmp_path / "S31E02.mkv")
                          open(video, "w").close()
                          # no .nfo file at all
                          gloss = {"episode_page_pattern_absolute": "Episode {n}"}
                          monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda api, show: ["A", "B"])
                          titles, method, detail = ga.episode_admission_titles(video, gloss, "https://x/api.php", "Show")
                          assert method == "fallback-allpages"
                          assert detail["nfo_present"] is False

                      def test_admission_titles_partial_mapping_keeps_resolved_pages(tmp_path, monkeypatch):
                          video = str(tmp_path / "S31E01.mkv")
                          open(video, "w").close()
                          nfo = str(tmp_path / "S31E01.nfo")
                          open(nfo, "w").write("Covers anime episode(s): 628-629")
                          gloss = {"episode_page_pattern_absolute": "Episode {n}"}
                          monkeypatch.setattr(
                              ga.glossary_verify, "episode_page_titles",
                              lambda api, show, pages: ({"Rebecca"}, ["Episode 628"], ["Episode 629"]),
                          )
                          titles, method, detail = ga.episode_admission_titles(video, gloss, "https://x/api.php", "Show")
                          assert titles == {"Rebecca"} and method == "absolute"
                          assert detail["partial_pages"] == ["Episode 629"]
                      ```
                      Run `pytest tests/test_glossary_acquire.py -k admission_titles -q` —
                      expect FAIL with `AttributeError`.

- [ ] Implement in `glossary_acquire.py`, above `acquire()`:
      ```python
      import ordering # add to the existing import block near the top of the file

      def _format_episode_page(pattern: str, **kw) -> str | None:
                          """pattern.format(**kw), or None on a malformed hand-edited pattern --
                          must never crash a sweep."""
                          try:
                              return pattern.format(**kw)
                          except (KeyError, IndexError, ValueError):
                              return None

                      def episode_admission_titles(
                          video: str, gloss: dict, wiki_api: str, show: str, source_episodes_fn=None,
                      ) -> tuple[set[str] | None, str, dict]:
                          """The per-episode wiki title set (S-7), or None ("unscoped") when
                          neither pattern field is declared -- today's behaviour, unchanged.
                          Falls back to the franchise-wide allpages set, logged via `method`,
                          when no per-episode set resolves at all."""
                          source_episodes_fn = source_episodes_fn or glossary.source_episodes
                          detail = {"nfo_present": False, "nfo_parsed": False, "partial_pages": []}
                          pat_abs = gloss.get("episode_page_pattern_absolute")
                          pat_rel = gloss.get("episode_page_pattern_relative")
                          if not pat_abs and not pat_rel:
                              return None, "unscoped", detail
                          ek = ordering.episode_key(video)
                          if pat_abs:
                              nfo_path = os.path.splitext(video)[0] + ".nfo"
                              detail["nfo_present"] = os.path.exists(nfo_path)
                              numbers = source_episodes_fn(nfo_path) if detail["nfo_present"] else []
                              detail["nfo_parsed"] = bool(numbers)
                              if numbers:
                                  pages = [p for p in (_format_episode_page(pat_abs, n=n) for n in numbers) if p]
                                  union, resolved, failed = glossary_verify.episode_page_titles(wiki_api, show, pages)
                                  if union:
                                      detail["partial_pages"] = failed
                                      return union, "absolute", detail
                          if pat_rel and ek:
                              s, e = ordering.season_ep(video)
                              page = _format_episode_page(pat_rel, s=s, e=e)
                              if page:
                                  union, resolved, failed = glossary_verify.episode_page_titles(wiki_api, show, [page])
                                  if union:
                                      return union, "relative", detail
                          if not ek:
                              return set(glossary_verify.fetch_titles(wiki_api, show)), "no-episode-tag", detail
                          return set(glossary_verify.fetch_titles(wiki_api, show)), "fallback-allpages", detail
                      ```

- [ ] Run `pytest tests/test_glossary_acquire.py -k admission_titles -q` —
      expect PASS.
- [ ] Run `ruff check glossary_acquire.py tests/test_glossary_acquire.py`
      — expect 0 findings. Commit:
      `feat(glossary_acquire): resolve one episode's admission title set, with a logged fallback`.

## Task 10: wire per-token admission filtering into `acquire()`

Files: `glossary_acquire.py` (`acquire()` at `:829-960`, specifically
lines 840, 861, 880, 911, 932-948 — see anchors below),
`tests/test_glossary_acquire.py`.

Interfaces: every proposal dict gains `"admission_method"`. `acquire()`'s
return dict gains `"nfo_present"`, `"nfo_parsed"`, `"nfo_missing"`,
`"nfo_parse_failed"` (ints) and `"fallback_episodes"` (list of episode
stems that hit `fallback-allpages`/`no-episode-tag`). Consumes Task 6's
`contributing_stems` and Task 9's `episode_admission_titles`.

- [ ] Write the failing tests. This task is the SAO regression test the
      whole spec exists for:
      ```python
      def test_acquire_admission_scoping_removes_the_sao_noise(tmp_path, monkeypatch):
      """Re-run of the 2026-08-29 SAO measurement: What->Whale, Whose->Horse
      must no longer be proposed once admission is scoped per episode."""
      _write_conf(tmp_path, "S01E05", ["What happened to Yolko and Schmitt?"] * 200)
      gp = tmp_path / "SAO.json"
      gp.write_text(json.dumps({"show": "SAO", "episode_page_pattern_relative": "SAO Episode {e:02d}"}))
      monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda show, override=None: "https://x/api.php")
      monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda api, show: ["Whale", "Horse", "Yolko", "Schmitt"])
      monkeypatch.setattr(
      ga.glossary_verify, "episode_page_titles",
      lambda api, show, pages: ({"Yolko", "Schmitt"}, pages, []),
      )
      out = ga.acquire(str(gp), str(tmp_path))
      variants = {p["variant"] for p in out.get("_debug_proposals", [])} # "What"/"Whose" must not resolve to Whale/Horse once those titles are # outside E05's admission set -- they simply never reach propose()'s output.
      assert "What" not in variants and "Whose" not in variants

      def test_acquire_per_token_union_does_not_leak_across_tokens(tmp_path, monkeypatch):
                          """The bug found during design: an unmapped episode's fallback must widen
                          admission only for TOKENS THAT APPEAR THERE, not every token in the sweep."""
                          _write_conf(tmp_path, "S01E05", ["Yolko appears here."] * 10)
                          _write_conf(tmp_path, "S01E99", ["Caesar appears here too."] * 10)  # unmapped
                          gp = tmp_path / "SAO.json"
                          gp.write_text(json.dumps({"show": "SAO", "episode_page_pattern_relative": "SAO Episode {e:02d}"}))
                          monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda show, override=None: "https://x/api.php")
                          monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda api, show: ["Yolko", "Whale", "Caesar"])

                          def fake_pages(api, show, pages):
                              if pages == ["SAO Episode 05"]:
                                  return {"Yolko"}, pages, []
                              return set(), [], pages  # S01E99's pattern never resolves -> fallback

                          monkeypatch.setattr(ga.glossary_verify, "episode_page_titles", fake_pages)
                          out = ga.acquire(str(gp), str(tmp_path))
                          proposals = out.get("_debug_proposals", [])
                          yolko = next(p for p in proposals if p["variant"] == "Yolko")
                          assert yolko["admission_method"] == "tight"
                          # "Whale" was never harvested from either episode's transcript in this
                          # fixture, so it cannot appear as a proposal at all -- this asserts the
                          # thing that matters: Yolko's own admission is untouched by S01E99's
                          # unrelated fallback.

                      def test_acquire_admission_method_tight_fallback_mixed(tmp_path, monkeypatch):
                          gp = tmp_path / "S.json"
                          gp.write_text(json.dumps({"show": "S", "episode_page_pattern_relative": "S Episode {e:02d}"}))
                          _write_conf(tmp_path, "S01E01", ["Caesar seen here."] * 5)
                          _write_conf(tmp_path, "S01E02", ["Caesar seen here too."] * 5)
                          monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda show, override=None: "https://x/api.php")
                          monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda api, show: ["Caesar"])

                          def fake_pages(api, show, pages):
                              if pages == ["S Episode 01"]:
                                  return {"Caesar"}, pages, []
                              return set(), [], pages  # E02 unmapped

                          monkeypatch.setattr(ga.glossary_verify, "episode_page_titles", fake_pages)
                          out = ga.acquire(str(gp), str(tmp_path))
                          caesar = next(p for p in out.get("_debug_proposals", []) if p["variant"] == "Caesar")
                          assert caesar["admission_method"] == "mixed"

                      def test_acquire_admission_rejected_token_still_reaches_tier_b(tmp_path, monkeypatch):
                          """The corrected S-8 claim: an admission-rejected token must reach
                          unmatched()/adjudicate(), not silently vanish."""
                          _write_conf(tmp_path, "S01E05", ["Exclusivename appears here."] * 5)
                          gp = tmp_path / "S.json"
                          gp.write_text(json.dumps({"show": "S", "episode_page_pattern_relative": "S Episode {e:02d}"}))
                          monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda show, override=None: "https://x/api.php")
                          # "Exclusivename" resolves against allpages but is NOT in E05's admitted set.
                          monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda api, show: ["Exclusivename"])
                          monkeypatch.setattr(ga.glossary_verify, "episode_page_titles", lambda api, show, pages: (set(), pages, []))
                          adjudicated = []
                          monkeypatch.setattr(
                              ga.glossary_verify, "adjudicate",
                              lambda term, cands, show: adjudicated.append(term) or {"confidence": "none", "canonical": ""},
                          )
                          ga.acquire(str(gp), str(tmp_path))
                          assert "Exclusivename" in adjudicated

                      def test_acquire_partial_mapping_exclusive_name_reaches_unmatched(tmp_path, monkeypatch):
                          """S-13's specific scenario: a name exclusive to a missing source page's
                          Plot section, in an otherwise-partially-resolved episode. Two variants
                          are checked, per the spec's requirement that these are separate claims:
                          one that still fuzzy-resolves against allpages (reaches adjudicate via
                          the admission-rejected path, same mechanism as the test above), and one
                          that resolves to NOTHING against allpages at all (the ordinary unmatched
                          path, unaffected by admission)."""
                          _write_conf(tmp_path, "S31E01", ["Missingpagename and Neverinwiki appear."] * 5)
                          nfo = str(tmp_path / "S31E01.nfo")
                          open(nfo, "w").write("Covers anime episode(s): 628-629")
                          gp = tmp_path / "Show.json"
                          gp.write_text(json.dumps({"show": "Show", "episode_page_pattern_absolute": "Episode {n}"}))
                          monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda show, override=None: "https://x/api.php")
                          # "Missingpagename" IS on allpages (so it can fuzzy-resolve); "Neverinwiki" is not.
                          monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda api, show: ["Missingpagename"])

                          def fake_pages(api, show, pages):
                              if pages == ["Episode 628"]:
                                  return {"SomeOtherName"}, ["Episode 628"], []
                              return set(), [], pages  # 629 (the page Missingpagename lives on) never resolves

                          monkeypatch.setattr(ga.glossary_verify, "episode_page_titles", fake_pages)
                          adjudicated = []
                          monkeypatch.setattr(
                              ga.glossary_verify, "adjudicate",
                              lambda term, cands, show: adjudicated.append(term) or {"confidence": "none", "canonical": ""},
                          )
                          out = ga.acquire(str(gp), str(tmp_path))
                          assert out["fallback_episodes"] == [] or "S31E01" not in out["fallback_episodes"]  # partial, not fallback
                          assert "Missingpagename" in adjudicated  # resolved-but-rejected -> tier-B
                          assert "Neverinwiki" in adjudicated  # never resolved at all -> tier-B, unaffected by admission

                      def test_acquire_warns_when_nfo_present_but_none_parse(tmp_path, monkeypatch, capsys):
                          """S-14: nfo_present > 0 and nfo_parsed == 0 must emit a warning distinct
                          from the ordinary per-episode fallback log line -- the signature of a
                          wrong .nfo filename convention, not a genuine unmapped population."""
                          _write_conf(tmp_path, "S31E01", ["Text here."] * 3)
                          nfo = str(tmp_path / "S31E01.nfo")
                          open(nfo, "w").write("no mapping line in this file at all")
                          gp = tmp_path / "Show.json"
                          gp.write_text(json.dumps({"show": "Show", "episode_page_pattern_absolute": "Episode {n}"}))
                          monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda show, override=None: "https://x/api.php")
                          monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda api, show: ["X"])
                          out = ga.acquire(str(gp), str(tmp_path))
                          assert out["nfo_present"] == 1 and out["nfo_parsed"] == 0
                          captured = capsys.readouterr()
                          assert "WARNING" in captured.out and ".nfo" in captured.out
                      ```
                      These reference `out.get("_debug_proposals", [])` and
                      `ga.glossary_verify.adjudicate` — confirm both exist on the real
                      `acquire()` return shape and `glossary_verify` module before relying
                      on them; if `acquire()`'s return dict does not already expose its
                      full proposal list under some key, add one (`"_debug_proposals":
                      proposals`) as part of this task's implementation step below, since
                      the tests need it and no existing key currently exposes the raw
                      list end to end.
                      Run `pytest tests/test_glossary_acquire.py -k "admission_method or per_token_union or tier_b or exclusive_name or warns_when_nfo" -q`
                      — expect FAIL (new behavior not implemented; some tests may error on
                      the missing `_debug_proposals` key until that's added in the next
                      step).

- [ ] Implement in `glossary_acquire.py`'s `acquire()`:
  - After line 840 (`cands, mid, scope = harvest_candidates(show_dir)`),
    no change needed there.
  - After line 861 (`resolved = _resolve_tokens(counts, titles)`), insert
    the per-token admission-union step and the nfo/fallback aggregation:
    ```python
    admission_union: dict[str, set[str] | None] = {}
    nfo_present = nfo_parsed = nfo_missing = nfo_parse_failed = 0
    fallback_episodes: list[str] = []
    stem_to_video = {s: common.find_video(s) for s in scope}
    admission_active = bool(gloss.get("episode_page_pattern_absolute") or gloss.get("episode_page_pattern_relative"))
    stem_admission: dict[str, tuple[set[str] | None, str, dict]] = {}
    if admission_active:
        for s in scope:
            video = stem_to_video.get(s)
            if not video:
                continue
            stem_admission[s] = episode_admission_titles(video, gloss, api, show)
            _, method, detail = stem_admission[s]
            if detail["nfo_present"]:
                nfo_present += 1
                if detail["nfo_parsed"]:
                    nfo_parsed += 1
                else:
                    nfo_parse_failed += 1
            else:
                nfo_missing += 1
            if method in ("fallback-allpages", "no-episode-tag"):
                fallback_episodes.append(s)

        def _token_admission(tok: str) -> tuple[set[str] | None, str]:
            stems = cands.get(tok, {}).get("contributing_stems", set())
            methods = {stem_admission[s][1] for s in stems if s in stem_admission}
            if not stems or not methods:
                return None, "unscoped"
            union: set[str] = set()
            for s in stems:
                titles_for_s = stem_admission.get(s, (None, "unscoped", {}))[0]
                if titles_for_s:
                    union |= titles_for_s
            tight = methods <= {"absolute", "relative"}
            fell = methods <= {"fallback-allpages", "no-episode-tag"}
            admission_method = "tight" if tight else ("fallback" if fell else "mixed")
            return union, admission_method

        resolved_admitted = {}
        for tok, (canon, score) in resolved.items():
            union, admission_method = _token_admission(tok)
            if union is None or normalize_title(canon) in {normalize_title(t) for t in union}:
                resolved_admitted[tok] = (canon, score)
    else:
        resolved_admitted = resolved
    ```
    (`normalize_title` and `cands` are already local names in `acquire()`;
    `common` needs `import common` added near the top of
    `glossary_acquire.py` if not already imported — check first, as
    `common.find_video` is the only new external reference this task
    adds.)
  - Change line 880 from
    `proposals = propose(counts, mid, titles, settled, resolved=resolved, candidates=cands, anchors=anchors)`
    to
    `proposals = propose(counts, mid, titles, settled, resolved=resolved_admitted, candidates=cands, anchors=anchors)`.
  - Change line 911 from
    `for term in unmatched(counts, mid, titles, resolved=resolved):`
    to
    `for term in unmatched(counts, mid, titles, resolved=resolved_admitted):`
    — this is the corrected S-8 behavior (see spec's S-8 note): both
    `propose()` and `unmatched()` must receive the SAME filtered dict, or
    an admission-rejected token satisfies neither function's inclusion
    test and disappears entirely.
  - After each proposal dict is built inside `propose()`'s own loop
    (`glossary_acquire.py:595-624`, the `out.append({...})` call), add
    `"admission_method": _token_admission(tok)[1] if admission_active else None`
    to the dict literal — this requires `propose()` to accept the new
    `_token_admission` callable or `admission_active`/`stem_admission`
    state as an optional parameter (`admission_fn=None`), since `propose`
    is a separate top-level function from `acquire`. Add
    `admission_fn: callable | None = None` to `propose()`'s signature,
    call it as `admission_fn(tok)[1] if admission_fn else None`, and pass
    `admission_fn=_token_admission if admission_active else None` from
    `acquire()`'s call site at line 880.
  - In `apply_proposals()` (used later at line 934) and in the
    `flagged`/`acquired` dict literals it builds, thread
    `"admission_method": p.get("admission_method")` into both — add this
    key to the two dict literals at the lines identified in Task 11's
    reading of `apply_proposals` (do not duplicate that edit if Task 11 is
    done first; whichever task lands first adds the key, the other
    confirms it's already there).
  - In `acquire()`'s final `return {...}` (line 955), add:
    `"nfo_present": nfo_present, "nfo_parsed": nfo_parsed, "nfo_missing": nfo_missing, "nfo_parse_failed": nfo_parse_failed, "fallback_episodes": fallback_episodes, "_debug_proposals": proposals` —
    the `nfo_present > 0 and nfo_parsed == 0` warning check and log call
    goes directly above this `return`:
    ```python
    if nfo_present and not nfo_parsed:
        log(f"  WARNING {show}: {nfo_present} .nfo file(s) found, 0 parsed -- check the per-episode .nfo naming convention")
    ```
- [ ] Run `pytest tests/test_glossary_acquire.py -q` (whole file) —
      expect PASS, including every pre-existing test (confirms
      `admission_active=False`, i.e. no pattern fields declared, is
      byte-identical to today for every show without them).
- [ ] Run `ruff check glossary_acquire.py tests/test_glossary_acquire.py`
      — expect 0 findings. Commit:
      `feat(glossary_acquire): scope wiki admission per token, report fallback/partial provenance and .nfo health`.

## Task 11: `glossary.add_episode_tag()` + `apply_proposals` episode tagging

Files: `glossary.py` (new function near `tag_names_by_arc`),
`glossary_acquire.py` (`apply_proposals` at `:657-715`, `acquire()`'s
apply block at `:932-948`), `tests/test_glossary.py`,
`tests/test_glossary_acquire.py`.

Interfaces: `glossary.add_episode_tag(gloss: dict, term: str, episode_keys:
set[str]) -> None` (mutates in place). `apply_proposals()` gains parameter
`episode_keys_by_stem: dict[str, str] | None = None`.

- [ ] Write the failing tests:
      ```python # tests/test_glossary.py
      def test_add_episode_tag_writes_sorted_unioned_keys():
      g = {}
      glossary.add_episode_tag(g, "Doflamingo", {"S31E02", "S31E01"})
      assert g["episode_tags"]["doflamingo"] == ["S31E01", "S31E02"]
      glossary.add_episode_tag(g, "Doflamingo", {"S31E03"})
      assert g["episode_tags"]["doflamingo"] == ["S31E01", "S31E02", "S31E03"]

      # tests/test_glossary_acquire.py
                      def test_apply_proposals_tags_episodes_keyed_on_canonical():
                          gloss = {"show": "One Pace"}
                          props = [{
                              "variant": "Dothamingo", "canonical": "Doflamingo", "variant_count": 3,
                              "canonical_count": 0, "score": 0.9, "verdict": "apply", "reason": "canonical-unseen",
                              "bound": 0.0, "contributing_stems": {"/a/S31E01", "/a/S31E02"},
                          }]
                          g = ga.apply_proposals(
                              gloss, props, run_id="run1",
                              episode_keys_by_stem={"/a/S31E01": "S31E01", "/a/S31E02": "S31E02"},
                          )
                          assert g["episode_tags"]["doflamingo"] == ["S31E01", "S31E02"]
                          assert "dothamingo" not in g.get("episode_tags", {})  # keyed on canonical, not variant

                      def test_apply_proposals_dry_run_omits_episode_tags():
                          # apply_proposals is only ever called from acquire()'s `if apply and ...`
                          # block, so "dry run omits tags" is verified in acquire()'s own test
                          # below rather than here -- apply_proposals itself has no apply/dry
                          # distinction, only its caller does.
                          pass
                      ```
                      Run `pytest tests/test_glossary.py tests/test_glossary_acquire.py -k "add_episode_tag or tags_episodes_keyed" -q`
                      — expect FAIL with `AttributeError`/`TypeError`.

- [ ] Implement `add_episode_tag` in `glossary.py`, directly below
      `tag_names_by_arc`:
      `python
def add_episode_tag(gloss: dict, term: str, episode_keys) -> None:
  """Record which episode(s) an ACQUIRED term's canonical came from.
  Unlike tag_names_by_arc, this does not discover membership -- the caller
  already knows exactly which episodes produced this proposal (S-9). Keyed
  on the term AS PASSED: callers must pass the canonical spelling, since
  that is what repair._glossary_terms iterates via token_fixes/
  phrase_fixes' values, not the harvested variant."""
  if not episode_keys:
      return
  tags = gloss.setdefault("episode_tags", {})
  existing = set(tags.get(term.lower(), []))
  tags[term.lower()] = sorted(existing | set(episode_keys))
`
- [ ] In `glossary_acquire.py`, change `apply_proposals`'s signature
      (`:657`) to
      `def apply_proposals(gloss: dict, proposals: list, run_id: str, scope: int = 0, episode_keys_by_stem: dict | None = None) -> dict:`.
      Inside the `if p["verdict"] == "apply":` branch (after
      `known.discard(term)`), add:
      `python
if episode_keys_by_stem:
  stems = p.get("contributing_stems", ())
  keys = {episode_keys_by_stem[s] for s in stems if s in episode_keys_by_stem}
  glossary.add_episode_tag(g, p["canonical"], keys)
`
- [ ] In `acquire()`, before the `if apply and (proposals or tier_b):`
      block (`:932`), build the stem-to-key map (reusing `stem_to_video`
      from Task 10 if that task landed first; otherwise build it fresh
      here — `import ordering` must be present in this file, added in
      Task 9):
      `python
episode_keys_by_stem = {
  s: k for s in scope
  for v in [common.find_video(s)]
  if v for k in [ordering.episode_key(v)]
  if k
}
`
      Change the call at `:934` from
      `out = apply_proposals(gloss, proposals, run_id, files)` to
      `out = apply_proposals(gloss, proposals, run_id, files, episode_keys_by_stem)`.
- [ ] Run `pytest tests/test_glossary.py tests/test_glossary_acquire.py -q`
      — expect PASS, including
      `test_apply_proposals_writes_hard_fixes_and_provenance` and every
      other pre-existing `apply_proposals` test unchanged (confirms the
      new parameter is additive and optional).
- [ ] Run `ruff check glossary.py glossary_acquire.py tests/test_glossary.py tests/test_glossary_acquire.py`
      — expect 0 findings. Commit:
      `feat(glossary,glossary_acquire): tag an acquired term's canonical with the episodes that produced it`.

## Task 12: `repair._glossary_terms()` 3-tier partition

Files: `repair.py` (`_glossary_terms` at `:151-193`, `build_prompt` at
`:226`, `process()` at `:700-801`), `tests/test_repair.py`.

Interfaces: `_glossary_terms(gloss, arc=None, episode=None)`.
`build_prompt(asr, sub, gloss, prev_text="", next_text="", arc=None,
episode=None)`.

- [ ] Write the failing tests, next to the existing `_tagged_gloss`-based
      tests (~`tests/test_repair.py:1520-1560`):
      ```python
      def _episode_tagged_gloss():
      g = _tagged_gloss() # already has arc_tags: Doflamingo/Rebecca -> Dressrosa, etc.
      g["episode_tags"] = {"rebecca": ["S31E01"]}
      return g

      def test_glossary_terms_episode_tag_outranks_arc_tag():
                          g = _episode_tagged_gloss()
                          terms = repair._glossary_terms(g, arc="Dressrosa", episode="S31E01").split(", ")
                          # Rebecca is BOTH arc- and episode-tagged for S31E01; Doflamingo is
                          # arc-tagged only. Episode tier must rank Rebecca ahead of Doflamingo.
                          assert terms.index("Rebecca") < terms.index("Doflamingo")

                      def test_glossary_terms_untagged_term_still_appears():
                          g = _episode_tagged_gloss()
                          terms = repair._glossary_terms(g, arc="Dressrosa", episode="S99E99").split(", ")
                          assert "Oimo" in terms  # untagged for both dimensions, still included

                      def test_glossary_terms_episode_none_matches_today_2tier_behavior():
                          g = _tagged_gloss()
                          with_episode_none = repair._glossary_terms(g, arc="Dressrosa", episode=None)
                          # Must be byte-identical to calling the function with no episode kwarg
                          # at all, for every existing caller that doesn't pass one.
                          assert with_episode_none == repair._glossary_terms(g, arc="Dressrosa")
                      ```
                      Run `pytest tests/test_repair.py -k "episode_tag_outranks or untagged_term_still or episode_none_matches" -q`
                      — expect FAIL with `TypeError: _glossary_terms() got an unexpected
                      keyword argument 'episode'`.

- [ ] Implement in `repair.py`. Change the signature at `:151` to
      `def _glossary_terms(gloss, arc=None, episode=None):` and replace
      the single-tier partition block (`:175-184`) with:
      `python
arc_tags = gloss.get("arc_tags") or {}
episode_tags = gloss.get("episode_tags") or {}
episode_first = []
if episode and episode_tags:
  episode_first = [t for t in out if episode in (episode_tags.get(t.lower()) or ())]
remaining = [t for t in out if t not in set(episode_first)]
arc_first = []
if arc and arc_tags:
  arc_first = [t for t in remaining if arc in (arc_tags.get(t.lower()) or (arc,))]
out = episode_first + arc_first + [t for t in remaining if t not in set(arc_first)]
`
      Note the deliberate asymmetry versus the arc tier: episode
      membership does NOT default a term IN the episode-first tier the
      way `(arc,)` defaults an untagged term into the arc tier — an
      episode-untagged term simply isn't promoted by episode, and falls
      through to the (unchanged) arc-tier logic, which still defaults it
      in for arc purposes. This preserves
      `test_glossary_terms_episode_none_matches_today_2tier_behavior`'s
      requirement exactly: with `episode=None`, `episode_first == []`
      always, and the rest of the logic is byte-identical to today's
      2-tier partition.
- [ ] Change `build_prompt`'s signature (`:226`) to
      `def build_prompt(asr, sub, gloss, prev_text="", next_text="", arc=None, episode=None):`
      and its call to `_glossary_terms` (`:251`) to
      `names = _glossary_terms(gloss, arc, episode)`.
- [ ] In `process()`, add `episode = ordering.episode_key(video)` directly
      below the existing `arc = glossary.arc_for(video)` at `:702` (add
      `import ordering` near the top of `repair.py` if not already
      present — check first). Change the `build_prompt` call at `:801`
      from `build_prompt(c["text"], ref, gloss, prev_text, next_text,
arc)` to `build_prompt(c["text"], ref, gloss, prev_text, next_text,
arc, episode)`.
- [ ] Run `pytest tests/test_repair.py -q` (whole file) — expect PASS,
      including every pre-existing `_glossary_terms`/`build_prompt` test
      unchanged.
- [ ] Run `ruff check repair.py tests/test_repair.py` — expect 0
      findings. Commit:
      `feat(repair): weight the repair prompt by episode tags ahead of arc tags`.

## Task 13: end-to-end integration fixture

Files: `tests/test_glossary_acquire.py` (new test, exercising
`glossary_acquire`, `glossary_verify`, `glossary`, and `repair` together).

Interfaces: none new — this task adds test coverage only, no production
code changes.

- [ ] Write the integration test:
      ```python
      def test_end_to_end_admission_tagging_and_repair_weighting(tmp_path, monkeypatch): # Two mapped episodes sharing a token, one unmapped episode, one # partial mapping, one redirect pair.
      _write_conf(tmp_path, "S31E01", ["Rebecca and Kirito fight."] * 5)
      _write_conf(tmp_path, "S31E02", ["Rebecca returns."] * 5)
      _write_conf(tmp_path, "S31E03", ["Unmapped Caesar shows up."] * 5) # no .nfo
      for stem, cov in (("S31E01", "628"), ("S31E02", "629-630")):
      open(str(tmp_path / f"{stem}.nfo"), "w").write(f"Covers anime episode(s): {cov}")
      for stem in ("S31E01", "S31E02", "S31E03"):
      open(str(tmp_path / f"{stem}.mkv"), "w").close()
      gp = tmp_path / "Show.json"
      gp.write_text(json.dumps({"show": "Show", "episode_page_pattern_absolute": "Episode {n}"}))

          monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda show, override=None: "https://x/api.php")
                          monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda api, show: ["Rebecca", "Kirito", "Caesar"])

                          def fake_pages(api, show, pages):
                              if pages == ["Episode 628"]:
                                  return {"Rebecca", "Kirito"}, pages, []
                              if pages == ["Episode 629", "Episode 630"]:
                                  return {"Rebecca"}, ["Episode 629"], ["Episode 630"]  # partial
                              return set(), [], pages

                          monkeypatch.setattr(ga.glossary_verify, "episode_page_titles", fake_pages)
                          monkeypatch.setattr(ga.glossary_verify, "adjudicate", lambda term, cands, show: {"confidence": "none", "canonical": ""})

                          # dry run
                          dry = ga.acquire(str(gp), str(tmp_path), apply=False)
                          assert not json.loads(gp.read_text()).get("episode_tags")

                          # apply run
                          applied = ga.acquire(str(gp), str(tmp_path), apply=True)
                          on_disk = json.loads(gp.read_text())
                          assert "episode_tags" in on_disk
                          assert applied["nfo_missing"] >= 1  # S31E03 has no .nfo
                          assert applied.get("fallback_episodes")

                          # warm-cache second run must not re-fetch pages (asserted via a
                          # sentinel that raises if _http_json is called with a page URL)
                          def boom_if_page(url):
                              if "action=parse" in url:
                                  raise AssertionError("warm cache should not re-fetch a page")
                              return {"query": {"pages": {}}}

                          monkeypatch.setattr(ga.glossary_verify, "_http_json", boom_if_page)
                          ga.acquire(str(gp), str(tmp_path), apply=True)

                          # reload feeds repair._glossary_terms
                          gloss = glossary.load(str(gp))
                          terms_e01 = repair._glossary_terms(gloss, episode="S31E01").split(", ")
                          terms_e99 = repair._glossary_terms(gloss, episode="S99E99").split(", ")
                          assert terms_e01 != terms_e99 or not gloss.get("episode_tags")
                      ```
                      This is written expecting FAIL initially only insofar as any of
                      Tasks 1-12 are incomplete; if all prior tasks are done and green,
                      this test should largely pass on the first run — treat any failure
                      here as a real cross-task integration bug (per Luna review
                      2026-09-01, F8), not a fixture-authoring mistake to paper over. Run
                      `pytest tests/test_glossary_acquire.py -k end_to_end -q` and debug
                      any failure against the actual call chain, not by loosening the
                      assertions.

- [ ] Once passing, run the FULL suite: `pytest -q` — expect PASS, 0
      failures, 0 errors.
- [ ] Run `ruff check .` — expect 0 findings.
- [ ] Run `procoder check` — expect 0 blocking findings.
- [ ] Commit: `test(glossary_acquire): end-to-end fixture for per-episode admission and repair weighting`.
