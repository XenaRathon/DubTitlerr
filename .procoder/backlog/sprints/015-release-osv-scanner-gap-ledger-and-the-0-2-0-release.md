# Release: osv-scanner gap ledger and the 0.2.0 release controller

Status: closed 2026-09-23
Created: 2026-09-23

## Goal

Close out the v0.2.0 hardening pass: make the osv-scanner/`pyproject.toml` extractor gap a
tracked, documented workaround rather than a machine-local secret — a ledger entry for the
gap, a recorded decision to scan `uv.lock` directly, and CI that does exactly that on every
push — and then let the release controller prove the release is ready (`procoder release
0.2.0`: version sync, changelog heading, clean tree, gate, suite), printing the tag command
for the owner without ever executing it. The tag, the draft GitHub release, and the
representative-media verification against the deployed worker all stay with the owner.

## Result

committed: 7
done: 5 (20260921-agents-md-documents-the-local-bin-osv-scanner-shim-as-host, 20260921-changelog-md-s-0-2-0-section-carries-a-release-date-and-the, 20260921-procoder-check-is-clean-and-the-full-suite-passes-on-the, 20260921-procoder-release-0-2-0-completes-clean-version-sync, 20260921-pyproject-toml-s-version-field-reads-0-2-0)
carried: 2 (20260921-a-tracked-issue-github-issue-or-procoder-backlog-entry, 20260921-the-release-note-records-verification-against)

## Retro

The release controller was the cheap part: it runs its five checks itself — `pyproject.toml`
version sync, the `CHANGELOG.md` `0.2.0` heading, a clean tree, `.procoder/config.toml`'s
block policies for `[lint]`, `[test]`, `[docs]` and `[ask]`, and the full suite — and stops at
the printed tag command, so "ready to tag" was provable without executing anything. The
expensive part was the ledger story. Its plan step names `gh issue create --repo
azrtydxb/procoder`, and no issue exists: #293 ("Commit gate blocks on dependency versions that
are no longer in the working tree", closed 2026-09-23) and #177 ("Workspace members are
reported as unscannable when the root lockfile covers them", closed 2026-08-26) are the only
lockfile-shaped upstream hits, `gh search issues --author @me --created >=2026-09-19` is
empty, and `XenaRathon/DubTitlerr` reports `open_issues_count` 0. `.github/workflows/ci.yml`
still cites an upstream issue that was never filed, so the gap stayed a documented workaround
on the machine that has the shim and the story was carried rather than closed.

**Blocker: this branch has diverged from `origin/main`. Clear it before tagging v0.2.0.**

```
$ git rev-list --left-right --count origin/main...HEAD
2	35
$ git rev-list --left-right --count main...HEAD
1	45
$ git rev-list --left-right --count origin/fix/published-episode-titles...HEAD
0	51
$ git merge-base --is-ancestor origin/main HEAD && echo ancestor || echo not-an-ancestor
not-an-ancestor
```

HEAD is `8acc889`; `origin/main`'s tip is `47450be` ("chore(backlog): close 8 of 9 sprint 010
stories with evidence"), preceded by the merge commit `08fa1be`. `origin/main` is _not_ an
ancestor of HEAD, so `git tag -a v0.2.0` run from this branch would tag a branch rather than
main, and v0.1.0's precedent is that releases land on main. **Merge or push this branch into
`main` first, then tag from main.** Nothing in this sprint's bookkeeping changes that: no tag
was created (`git tag -l` lists `backup/pre-attribution-strip` and `v0.1.0` only), nothing was
pushed, and no release was drafted.

What the owner still has to do, in order, none of it executed here:

```
git tag -a v0.2.0 -m "0.2.0"
git push origin v0.2.0
gh release create v0.2.0 --repo XenaRathon/DubTitlerr --draft --title "v0.2.0" \
  --notes-file <(sed -n '/^## 0.2.0/,/^## 0.1.0/p' CHANGELOG.md | sed '$d')
```

Then the OWNER/LIVE representative-media checklist from `.procoder/plans/v0-2-0-hardening.md`,
which needs SSH to the deployed worker and real episodes, so it cannot be checked from this
laptop: confirm the host with `docker ps` before trusting any note (the repo's instructions
name vm102 at `192.168.1.232`, but this worker has moved three times and the vault at
`/home/xenarathon/Documents/obsidian vaults/Xen-Server Documentation` is authoritative); run
`docker exec <worker-container> python3 -c "import common; print(common.read_stages('<stem>'));
print(common.failed_stage('<stem>'))"` against (a) an `.mp4`/`.m4v` episode with no signs
track, (b) an `.mkv` with a signs track, and (c) a One Pace episode — `failed_stage` must
return `None` for each, One Pace additionally needs its `.dubtitles.conf.json` sidecar and a
playable "Dubtitles" track; check `curl -s http://<worker-host>:8842/healthz` returns
`{"ok": true, ...}`; and record all four results in the vault note. That story stays open in
the backlog until a human has run it against live media — it was never a laptop-checkable
criterion, and it was not force-closed.

What to change next time: an "open a tracking issue" step belongs in the sprint that decides to
track the gap, not four weeks later in the sprint that writes it up, so the ledger entry and
the CI comment's reference cannot drift apart. And whatever the next release controller run
says, check the branch's ancestry against `main` before quoting a ready line — a green release
gate proves the tree is consistent with itself, not that the tag would land where the release
is supposed to live.
