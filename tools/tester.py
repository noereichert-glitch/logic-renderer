#!/usr/bin/env python3
"""
StemExport -- autonomous integration tester.

Triggers a real export of the configured .als against the running app, watches
the Flask backend's /export/progress stream, then verifies the result. Writes
a STATUS.md report at the repo root that Claude Code reads between iterations.

This is the "drag-and-drop the .als and tell Claude Code what worked" agent.
It bypasses the GUI drop zone and hits the same Flask endpoint the renderer
hits, which is more reliable than driving Electron with a synthetic drop event.

Usage:
    python3 tools/tester.py
    python3 tools/tester.py "/path/to/project.als"
    python3 tools/tester.py "/path/to/project.als" "/path/to/output"

Prereqs (set up once):
    1. In one terminal:  cd <repo> && npm start         (leave running)
    2. Ableton should be CLOSED at the start of each test -- the orchestrator
       launches it. After a previous test, this script tells you whether
       Ableton quit cleanly; if it didn't, force-quit it before re-running.
    3. StemExportBridge must be enabled in Live -> Preferences ->
       Link/Tempo/MIDI as a Control Surface. Re-tick after every
       BRIDGE_VERSION bump.

Exit codes:
    0 = all checks green
    1 = at least one check failed (see STATUS.md)
    2 = preflight failed (backend down, .als missing, etc.)
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

# -- Configuration ------------------------------------------------------------
DEFAULT_ALS = "/Users/reichertnoe/Desktop/app test 23.30.12/app test Project/app test.als"
DEFAULT_OUT = "/Users/reichertnoe/Desktop/StemExport_test_output"
BACKEND = "http://127.0.0.1:5123"
REPO_ROOT = Path(__file__).resolve().parent.parent
STATUS_PATH = REPO_ROOT / "STATUS.md"
POLL_INTERVAL = 1.0       # seconds between progress polls
EXPORT_TIMEOUT = 30 * 60  # max wall time for one export (sec)

EXPECTED_SUBFOLDERS = ("01_With_FX", "02_Raw")


# -- HTTP helpers (stdlib only -- no `requests` dependency) -------------------
def http_get(path, timeout=5.0):
    req = urllib.request.Request(BACKEND + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def http_post(path, payload, timeout=10.0):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BACKEND + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


# -- Content-hash helper ------------------------------------------------------
def sha256_zip_entry(zf, name, chunk=1024 * 1024):
    """Streaming SHA-256 of a single entry inside an open ZipFile.

    Reads in `chunk`-sized blocks so a large WAV is never fully loaded into
    memory."""
    h = hashlib.sha256()
    with zf.open(name) as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# -- Report builder -----------------------------------------------------------
class Report:
    def __init__(self):
        self.checks = []   # list of (label, passed: bool, detail: str)
        self.notes = []
        self.started_at = datetime.now()

    def check(self, label, passed, detail=""):
        self.checks.append((label, bool(passed), detail))
        icon = "OK" if passed else "FAIL"
        print(f"  [{icon}] {label}" + (f"   - {detail}" if detail else ""))

    def note(self, text):
        self.notes.append(text)
        print(f"  [..] {text}")

    @property
    def all_passed(self):
        return all(p for _, p, _ in self.checks) and bool(self.checks)

    def to_markdown(self, als_path, out_folder, progress_log):
        ended = datetime.now()
        lines = []
        lines.append(f"# StemExport Test Run -- {self.started_at.isoformat(timespec='seconds')}")
        lines.append("")
        lines.append(f"- **Source**: `{als_path}`")
        lines.append(f"- **Output folder**: `{out_folder}`")
        lines.append(f"- **Duration**: {(ended - self.started_at).total_seconds():.1f} sec")
        verdict = "ALL GREEN" if self.all_passed else "FAILURES PRESENT"
        lines.append(f"- **Overall**: {verdict}")
        lines.append("")

        passed = [(l, d) for l, p, d in self.checks if p]
        failed = [(l, d) for l, p, d in self.checks if not p]

        if passed:
            lines.append("## Passed")
            for label, detail in passed:
                lines.append(f"- {label}" + (f" -- {detail}" if detail else ""))
            lines.append("")

        if failed:
            lines.append("## Failed")
            for label, detail in failed:
                lines.append(f"- **{label}**")
                if detail:
                    lines.append(f"  - {detail}")
            lines.append("")
            lines.append("## Where to look")
            lines.append("")
            lines.append("Likely files involved (use the failure detail above to narrow it down):")
            lines.append("")
            lines.append("- `python/stem_exporter.py` -- three-pass orchestration, fail-fast paths, restore-failure handling")
            lines.append("- `python/ableton_bridge.py` -- AppleScript export driver, WAV wait, clean-quit logic")
            lines.append("- `ableton_remote_script/StemExportBridge.py` -- bypass/restore + list_devices. **If you edit this file, bump `BRIDGE_VERSION` in `electron/main.js`. The user then has to quit Live and re-tick StemExportBridge in Preferences -> Link/Tempo/MIDI before the next test run.**")
            lines.append("- `python/one_click_helpers.py` -- bridge wire protocol, WAV sorter, zip step")
            lines.append("- Backend stdout: scroll the terminal running `npm start`. Every failure path the orchestrator hits prints there.")
            lines.append("")
            lines.append("After fixing, re-run: `python3 tools/tester.py`")
            lines.append("")

        if self.notes:
            lines.append("## Notes")
            for n in self.notes:
                lines.append(f"- {n}")
            lines.append("")

        if progress_log:
            lines.append("## Progress timeline (last 15 distinct states)")
            lines.append("")
            lines.append("```")
            for entry in progress_log[-15:]:
                slim = {
                    k: entry.get(k)
                    for k in ("progress", "status_title", "status_sub", "current_track", "done", "error")
                    if entry.get(k) not in (None, "", False) or k in ("progress", "done")
                }
                lines.append(json.dumps(slim, ensure_ascii=False))
            lines.append("```")
            lines.append("")

        return "\n".join(lines)


# -- Live-process check -------------------------------------------------------
def is_ableton_running():
    """Return True/False if pgrep is available; None on failure."""
    try:
        res = subprocess.run(
            ["pgrep", "-x", "Live"],
            capture_output=True, text=True, timeout=5,
        )
        return bool(res.stdout.strip())
    except Exception:
        return None


# -- Main flow ----------------------------------------------------------------
def main():
    als = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ALS
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    os.makedirs(out, exist_ok=True)

    rep = Report()
    progress_log = []

    print()
    print("StemExport -- integration tester")
    print(f"  source : {als}")
    print(f"  output : {out}")
    print()

    # Preflight 1: source file
    if not os.path.isfile(als):
        rep.check("source .als exists", False, f"not found at {als}")
        STATUS_PATH.write_text(rep.to_markdown(als, out, []))
        print(f"\n[tester] PREFLIGHT FAILED -- see {STATUS_PATH}")
        sys.exit(2)
    rep.check("source .als exists", True, als)

    # Preflight 2: backend reachable
    code = None
    try:
        code, _ = http_get("/health", timeout=3.0)
        backend_up = code == 200
    except Exception as e:
        rep.check(
            "Flask backend reachable on :5123",
            False,
            f"{e} -- is `npm start` running in another terminal?",
        )
        STATUS_PATH.write_text(rep.to_markdown(als, out, []))
        print(f"\n[tester] PREFLIGHT FAILED -- see {STATUS_PATH}")
        sys.exit(2)
    if not backend_up:
        rep.check("Flask backend reachable on :5123", False, f"got HTTP {code}")
        STATUS_PATH.write_text(rep.to_markdown(als, out, []))
        sys.exit(2)
    rep.check("Flask backend reachable on :5123", True)

    # Preflight 3: Ableton should NOT already be running
    pre_live = is_ableton_running()
    if pre_live is True:
        rep.note(
            "Ableton was already running before the test started. The orchestrator "
            "expects to launch it itself; pre-existing Live instances can confuse "
            "the AppleScript flow. Force-quit Live before the next run if anything "
            "downstream looks off."
        )
    elif pre_live is False:
        rep.check("Ableton Live not already running at start", True)

    # Trigger export
    print()
    print("[tester] POST /export ...")
    try:
        code, body = http_post("/export", {"file_path": als, "output_folder": out})
    except Exception as e:
        rep.check("/export accepted the request", False, str(e))
        STATUS_PATH.write_text(rep.to_markdown(als, out, []))
        sys.exit(1)

    if code != 200 or not body.get("started"):
        rep.check("/export accepted the request", False, f"HTTP {code} body={body}")
        STATUS_PATH.write_text(rep.to_markdown(als, out, []))
        sys.exit(1)
    rep.check("/export accepted the request", True)

    # Poll progress
    print("[tester] polling /export/progress (Ctrl-C to abort) ...")
    print()
    deadline = time.time() + EXPORT_TIMEOUT
    last_sig = None
    final_state = {}
    timed_out = True
    while time.time() < deadline:
        try:
            code, state = http_get("/export/progress", timeout=5.0)
            if code != 200:
                time.sleep(POLL_INTERVAL)
                continue
        except Exception:
            time.sleep(POLL_INTERVAL)
            continue

        sig = (state.get("status_title"), state.get("status_sub"), state.get("progress"))
        if sig != last_sig:
            progress_log.append(state)
            last_sig = sig
            pct = state.get("progress", 0) or 0
            title = state.get("status_title", "") or ""
            sub = state.get("status_sub", "") or ""
            print(f"  [{pct:>3}%] {title} -- {sub}")

        if state.get("done"):
            final_state = state
            timed_out = False
            break
        time.sleep(POLL_INTERVAL)

    if timed_out:
        last_title = progress_log[-1].get("status_title") if progress_log else "no progress data"
        rep.check(
            "export completed within timeout",
            False,
            f"timed out after {EXPORT_TIMEOUT // 60} min -- last status: {last_title}",
        )
        STATUS_PATH.write_text(rep.to_markdown(als, out, progress_log))
        print(f"\n[tester] TIMED OUT -- see {STATUS_PATH}")
        sys.exit(1)
    rep.check("export completed within timeout", True)

    # Error reported by backend?
    if final_state.get("error"):
        rep.check("export reported no error", False, str(final_state["error"]))
    else:
        rep.check("export reported no error", True)

    # Verify zip + contents
    zip_path = final_state.get("zip_path")
    if not zip_path:
        rep.check("backend reported a zip_path", False, "zip_path was empty in /export/progress")
    elif not os.path.isfile(zip_path):
        rep.check("zip file present on disk", False, f"backend reported {zip_path}, but the file isn't there")
    else:
        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        rep.check("zip file present on disk", True, f"{zip_path} ({size_mb:.1f} MB)")

        names = []
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
            rep.check("zip is readable", True, f"{len(names)} entries")
        except Exception as e:
            rep.check("zip is readable", False, str(e))

        for sub in EXPECTED_SUBFOLDERS:
            wavs = [n for n in names if f"/{sub}/" in n and n.lower().endswith(".wav")]
            rep.check(
                f"set {sub} contains at least one WAV",
                len(wavs) > 0,
                f"{len(wavs)} WAV(s)",
            )

        # Content-diff guard (T11): at least one Raw stem must differ from its
        # With-FX twin. The bug this catches is the v11 wet-Raw regression, where
        # the device bypass never applied and EVERY Raw stem rendered the wet
        # audio. A single byte-identical pair is NOT that bug: a track with no
        # devices of its own renders identically across both passes — most
        # commonly when its only FX lives on the parent group, whose processing
        # lands on the group bounce, not on an individual child stem (and group
        # WAVs are excluded from both sets compared here). So we fail only when
        # NO pair differs, and report any identical pairs as an informational
        # note. Streaming SHA-256 so large WAVs are never fully loaded into memory.
        try:
            with zipfile.ZipFile(zip_path) as zf:
                raw_map = {
                    os.path.basename(n): n
                    for n in names
                    if "/02_Raw/" in n and n.lower().endswith(".wav")
                }
                fx_map = {
                    os.path.basename(n): n
                    for n in names
                    if "/01_With_FX/" in n and n.lower().endswith(".wav")
                }
                shared = sorted(set(raw_map) & set(fx_map))
                if not shared:
                    rep.note(
                        "content-diff guard skipped: no same-named WAV pairs across "
                        "02_Raw and 01_With_FX to compare"
                    )
                else:
                    identical = [
                        base for base in shared
                        if sha256_zip_entry(zf, raw_map[base])
                        == sha256_zip_entry(zf, fx_map[base])
                    ]
                    differing = [b for b in shared if b not in identical]
                    if differing:
                        rep.check(
                            "02_Raw differs from 01_With_FX on at least one stem",
                            True,
                            f"{len(differing)} of {len(shared)} pair(s) differ "
                            "(bypass applied)",
                        )
                        if identical:
                            rep.note(
                                f"{len(identical)} stem(s) byte-identical across "
                                "02_Raw and 01_With_FX — expected for tracks with "
                                "no devices of their own (e.g. FX only on a parent "
                                f"group): {', '.join(identical)}"
                            )
                    else:
                        rep.check(
                            "02_Raw differs from 01_With_FX on at least one stem",
                            False,
                            f"[FAIL] all {len(shared)} shared stem(s) are "
                            "byte-identical to 01_With_FX — bypass did NOT apply "
                            "anywhere (v11 wet-Raw regression)",
                        )
        except Exception as e:
            rep.check(
                "02_Raw is meaningfully different from 01_With_FX",
                False,
                f"content-diff check errored: {e}",
            )

    # Verify Ableton quit cleanly
    post_live = is_ableton_running()
    if post_live is True:
        rep.check(
            "Ableton Live quit cleanly after export",
            False,
            "process 'Live' still running -- the quit_ableton_cleanly path didn't finish. "
            "Force-quit Live before the next test.",
        )
    elif post_live is False:
        rep.check("Ableton Live quit cleanly after export", True)
    else:
        rep.note("Could not run pgrep to check Ableton state.")

    # Final report
    STATUS_PATH.write_text(rep.to_markdown(als, out, progress_log))
    print()
    print(f"[tester] Report written to {STATUS_PATH}")
    if rep.all_passed:
        print("[tester] ALL GREEN")
        sys.exit(0)
    else:
        failed_n = sum(1 for _, p, _ in rep.checks if not p)
        print(f"[tester] {failed_n} failure(s) -- Claude Code: read STATUS.md")
        sys.exit(1)


if __name__ == "__main__":
    main()
