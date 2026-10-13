# Webhook fixtures (hand-written, not captured)

These payloads are hand-written for `tests/test_review_webhooks.py`. They were not
captured from a live Sonarr/Radarr instance. Field names follow the spec
(`specs/arr-webhooks/spec.md`) and the Sonarr v4 / Radarr v5 Connect > Webhook shape
(`eventType`, `isUpgrade`, `series{title,path,tvdbId}`,
`episodes[]{seasonNumber,episodeNumber}`, `episodeFiles[]{relativePath,path}` or the
older singular `episodeFile{}`, `movie{title,folderPath,tmdbId}`,
`movieFile{relativePath,path}`), with a few realistic extras (`quality`,
`downloadClient`, `release`) that the receiver ignores.

- `sonarr_download.json` — Download of One Pace S31E05 (plural `episodeFiles`).
- `sonarr_upgrade.json` — Upgrade of a two-episode file `S01E01E02` (singular `episodeFile`).
- `sonarr_rename.json` — Rename; must enqueue nothing.
- `sonarr_test.json` — Test; must answer that the hook works and enqueue nothing.
- `sonarr_health.json` — Health; must enqueue nothing.
- `radarr_download.json` — Movie Download under the anime root.
- `radarr_test.json` — Test; must answer that the hook works and enqueue nothing.
- `sonarr_v5_download.json` — Sonarr v5 Download: the v4 Download plus `series{malIds,
  aniListIds,originalCountry}`, `episodes[].finaleType`, and `indexerFlags` on the
  release and the file. Must enqueue exactly like the v4 one.
- `sonarr_v5_upgrade.json` — Sonarr v5 Upgrade: the v4 Upgrade plus the same new fields.
- `radarr_v6_download.json` — Radarr v6 Download: the v5 Download plus `indexerFlags`.
  Radarr's upstream webhook payload classes did not change between v5.28 and v6.4.4,
  so the shape is otherwise identical and must enqueue exactly like the v5 one.
