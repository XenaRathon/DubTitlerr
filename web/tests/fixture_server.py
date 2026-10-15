"""Isolated browser-test server. Never discovers or processes a real media library."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="dubtitlerr-ui-test-") as scratch:
        base = Path(scratch)
        media = base / "media"
        glossary_dir = base / "glossaries"
        glossary_dir.mkdir()
        ddir = base / "decisions"
        ddir.mkdir()
        os.environ["REVIEW_TOKEN"] = "browser-fixture-token"
        os.environ["REVIEW_USERNAME"] = "reviewer"
        os.environ["REVIEW_PASSWORD"] = "browser-fixture-password"
        os.environ.pop("REVIEW_AUTH", None)
        # The new pages' backends: admin-guarded run requests, a settings read and two backend probes.
        os.environ["ANIME_ROOT"] = str(media)
        os.environ["REQUESTS_DIR"] = str(base / "requests")
        os.environ["SCHEDULE_FILE"] = str(base / "schedule.json")
        os.environ["REPAIR_LLAMACPP_URL"] = "http://127.0.0.1:18842/healthz"  # this very server: the probe succeeds
        os.environ["VERIFY_LLAMACPP_URL"] = "http://127.0.0.1:9/"  # nothing listens here: the probe fails
        # Settings writes (settings.json, secrets.json) land in this directory.
        (base / "config").mkdir()
        os.environ["CONFIG_DIR"] = str(base / "config")
        os.environ["STOP_FLAG"] = str(base / "stop")  # a restart request lands here, never in /tmp
        os.environ["DT_CONTAINER_BOOT_ID"] = "fixture-boot-1"
        os.environ["REPAIR_PROFILES"] = "{}"  # retired: the General page lists it
        os.environ["LONGCATAI_API_KEY"] = "fixture-secret-key-value"  # must show as "set", never as a value
        os.environ.pop("COMMANDCODE_API_KEY", None)
        os.environ.pop("WEBHOOK_TOKEN", None)
        os.environ["HEARTBEAT_PATH"] = str(base / "heartbeat.json")
        os.environ["GLOSSARY_DIR"] = str(glossary_dir)
        os.environ["DECISIONS_DIR"] = str(ddir)
        import common
        import decisions
        import review_auth
        import review_server as rs
        import review_settings
        import unresolved

        common.heartbeat(last_sweep_end=time.time(), roots_readable=True, order_file_present=True)
        review_settings.EFFECTIVE_ENV_PATH = str(base / "no-effective.env")  # absent: settings come from the environment
        review_auth.import_env_admin()  # REVIEW_USERNAME/REVIEW_PASSWORD become the browser tests' admin account
        rs.ROOTS = [str(media)]
        decisions.GLOSSARY_DIR = str(glossary_dir)
        decisions.DECISIONS_DIR = str(ddir)
        fixtures = [
            (
                "Neon Harbor",
                "S01E01",
                [
                    (
                        "We're looking for a factory.",
                        "We're looking for a needle.",
                        "repair_applied",
                        "accepted",
                        "We need to find the factory.",
                    ),
                    ("meet me at the harbor", "Meet me at the harbor.", "repair_applied", "accepted", "Meet at the port."),
                    (
                        "The blue compass is ours.",
                        "The compass is ours.",
                        "repair_applied",
                        "accepted",
                        "That blue compass belongs to us.",
                    ),
                    ("Wait for me!", "Weigh four me!", "repair", "rejected_guard", "Wait!"),
                ],
            ),
            (
                "Neon Harbor",
                "S01E02",
                [
                    ("meet me at the harbor", "Meet me at the harbor.", "repair_applied", "accepted", "Meet at the port."),
                    ("we can do this", "We can do this.", "repair_applied", "accepted", "We can manage."),
                ],
            ),
            (
                "Paper Moon",
                "S02E03",
                [
                    ("The stars are bright.", "The scars are bright.", "repair_applied", "accepted", "Bright stars."),
                    (
                        "<img src=x onerror=alert(1)>",
                        "<script>bad</script>",
                        "repair_applied",
                        "accepted",
                        "Untrusted subtitle text.",
                    ),
                ],
            ),
            (
                "Paper Moon",
                "S02E04",
                [
                    ("Stop there!", "Shop where!", "repair", "rejected_guard", ""),
                ],
            ),
        ]
        for show, ep, rows in fixtures:
            (glossary_dir / f"{show}.json").write_text(json.dumps({"show": show}))
            season = "Season 01" if "S01" in ep else "Season 02"
            folder = media / show / season
            folder.mkdir(parents=True, exist_ok=True)
            stem = str(folder / f"{show} - {ep}")
            cards = [{"start": 2 + i * 3, "end": 4 + i * 3, "text": row[0]} for i, row in enumerate(rows)]
            Path(stem + rs.CONF_SUFFIX).write_text(json.dumps(cards))
            for orig, prop, stage, reason, ref in rows:
                unresolved.record(stem, stage, reason, original_text=orig, proposed_text=prop, reference=ref)
            # A sine wave, not copyrighted dialogue. One tagged English audio stream.
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=330:duration=18",
                    "-metadata:s:a:0",
                    "language=eng",
                    "-c:a",
                    "pcm_s16le",
                    "-y",
                    stem + ".mkv",
                ],
                check=True,
                timeout=15,
                stdin=subprocess.DEVNULL,
            )

        class FixtureHandler(rs.Handler):
            def do_POST(self):
                if self.path == "/__test/reset" and self.headers.get("X-Api-Key") == "browser-fixture-token":
                    for file in ddir.glob("*.json"):
                        file.unlink()
                    for file in media.rglob("*.dubtitles.unresolved.jsonl"):
                        records = [json.loads(line) for line in file.read_text().splitlines()]
                        for record in records:
                            record["resolved"] = False
                        file.write_text("".join(json.dumps(r) + "\n" for r in records))
                    rs._QUEUE_CACHE.clear()
                    for file in (base / "requests").glob("*") if (base / "requests").is_dir() else []:
                        file.unlink()
                    for stale in ("settings.json", "settings.json.prev", "secrets.json", "secrets.json.prev"):
                        (base / "config" / stale).unlink(missing_ok=True)
                    (base / "stop").unlink(missing_ok=True)
                    (base / "schedule.json").unlink(missing_ok=True)
                    for show in ("Neon Harbor", "Paper Moon"):
                        (glossary_dir / f"{show}.json").write_text(json.dumps({"show": show}))
                    return self._send(200, {"ok": True})
                return super().do_POST()

        srv = rs.BoundedHTTPServer(("127.0.0.1", 18842), FixtureHandler)
        print("Synthetic review fixture ready on 127.0.0.1:18842", flush=True)
        try:
            srv.serve_forever()
        finally:
            srv.server_close()


if __name__ == "__main__":
    main()
