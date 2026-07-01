#!/usr/bin/env python3
"""
StemExport -- autonomous integration tester (Logic Pro, Tier 0 certification).

Triggers a real headless export of the configured .logicx against the running
Flask backend (the same endpoint the Electron renderer hits), watches
/export/progress, then asserts the CURRENT pipeline end-to-end and writes the
"Latest certification run" section of STATUS.md.

What it certifies (the P8 Tier-0 contract):
  (a) OUTPUT = a single <project>.zip and the un-zipped <project>/ source folder
      is GONE (verify-then-delete deliverable).
  (b) the zip CONTAINS 01_With_FX + 02_Raw, each with the expected stems (>=2).
  (c) 02_Raw really DIFFERS from 01_With_FX (FX were bypassed).
  (d) the project was NEVER SAVED (ProjectData size+mtime byte-unchanged).
  (e) FOCUS ends on the user's own frontmost app (not Logic).
  (f) Logic quit cleanly; the backend reported no error (healthy => silent, i.e.
      no [[EXPORT_FAILURE]] marker was emitted).

Backend-stdout-only signals (NOT visible to this HTTP client) — read them in the
`npm start` terminal, per the run instructions printed at the end:
  • C9 (audio-interface-unavailable) auto-handled:  [DialogGuard] ... rule=audio_interface_unavailable -> click button='OK'
  • absence of any                                  [[EXPORT_FAILURE]] line
  • dialog-scan overhead totals:                    [SCAN] load ... / [SCAN] export ...

Usage (certification):
    1. In one terminal:  npm start           (leave running; Logic CLOSED first)
    2. From your normal frontmost app, in another terminal:
                         python3 tools/tester.py
       (optionally: python3 tools/tester.py "/path/project.logicx" "/path/out")

Static / preflight-only (no backend, no render — validates this script's checks):
    python3 tools/tester.py --preflight

Exit codes: 0 = all green | 1 = a check failed (see STATUS.md) | 2 = preflight failed.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))
try:
    from logic_render import resolve_project_path  # noqa: E402
except Exception:  # pragma: no cover - repo always has it
    resolve_project_path = None

# -- Configuration ------------------------------------------------------------
DEFAULT_PROJECT = os.path.expanduser("~/Desktop/logic test.logicx")
DEFAULT_OUT = os.path.expanduser("~/Desktop/StemExport_test_output")
BACKEND = "http://127.0.0.1:5123"
STATUS_PATH = REPO_ROOT / "STATUS.md"
POLL_INTERVAL = 1.0        # seconds between progress polls
EXPORT_TIMEOUT = 30 * 60   # max wall time for one export (sec)

EXPECTED_SUBFOLDERS = ("01_With_FX", "02_Raw")
LOGIC_PROCESS_NAMES = ("Logic Pro X", "Logic Pro")

# STATUS.md is hand-authored ABOVE this marker (Tier-0 state + residuals); this
# tester regenerates only the certification-run section BELOW it, so a cert run
# never clobbers the narrative.
CERT_MARKER = "<!-- CERTIFICATION-RUN: auto-generated below by tools/tester.py; edit above this line -->"


# -- HTTP helpers (stdlib only) -----------------------------------------------
def http_get(path, timeout=5.0):
    req = urllib.request.Request(BACKEND + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def http_post(path, payload, timeout=10.0):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BACKEND + path, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


# -- macOS helpers ------------------------------------------------------------
def frontmost_app():
    """Name of the current frontmost process (System Events), or '' on error."""
    try:
        r = subprocess.run(
            ["osascript", "-e",
             "tell application \"System Events\" to get name of first process whose frontmost is true"],
            capture_output=True, text=True, timeout=8)
        return r.stdout.strip()
    except Exception:
        return ""


def logic_running():
    """True/False if any Logic process is alive; None if pgrep unavailable."""
    try:
        for name in LOGIC_PROCESS_NAMES:
            res = subprocess.run(["pgrep", "-x", name],
                                 capture_output=True, text=True, timeout=5)
            if res.stdout.strip():
                return True
        return False
    except Exception:
        return None


# -- never-saved: ProjectData fingerprint -------------------------------------
def find_projectdata(bundle_dir):
    for root, _dirs, files in os.walk(bundle_dir):
        if "ProjectData" in files:
            return os.path.join(root, "ProjectData")
    return None


def stat_fingerprint(path):
    st = os.stat(path)
    return (st.st_size, st.st_mtime_ns)


# -- zip content hashing ------------------------------------------------------
def sha256_zip_entry(zf, name, chunk=1024 * 1024):
    h = hashlib.sha256()
    with zf.open(name) as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# -- Report builder -----------------------------------------------------------
class Report:
    def __init__(self):
        self.checks = []   # (label, passed, detail)
        self.notes = []
        self.started_at = datetime.now()

    def check(self, label, passed, detail=""):
        self.checks.append((label, bool(passed), detail))
        print(f"  [{'OK' if passed else 'FAIL'}] {label}" + (f"   - {detail}" if detail else ""))

    def note(self, text):
        self.notes.append(text)
        print(f"  [..] {text}")

    @property
    def all_passed(self):
        return bool(self.checks) and all(p for _, p, _ in self.checks)

    def run_markdown(self, project, out, progress_log, scan_hint):
        ended = datetime.now()
        L = []
        L.append("## Latest certification run")
        L.append("")
        L.append(f"- **When**: {self.started_at.isoformat(timespec='seconds')}")
        L.append(f"- **Project**: `{project}`")
        L.append(f"- **Output**: `{out}`")
        L.append(f"- **Duration**: {(ended - self.started_at).total_seconds():.1f}s")
        L.append(f"- **Overall**: {'ALL GREEN ✅' if self.all_passed else 'FAILURES ⚠️'}")
        L.append("")
        passed = [(l, d) for l, p, d in self.checks if p]
        failed = [(l, d) for l, p, d in self.checks if not p]
        if passed:
            L.append("### Passed")
            L += [f"- {l}" + (f" — {d}" if d else "") for l, d in passed]
            L.append("")
        if failed:
            L.append("### Failed")
            for l, d in failed:
                L.append(f"- **{l}**" + (f"\n  - {d}" if d else ""))
            L.append("")
        if self.notes:
            L.append("### Notes")
            L += [f"- {n}" for n in self.notes]
            L.append("")
        L.append("### Read these in the `npm start` terminal (backend stdout)")
        L.append("")
        L.append("- **C9 auto-handled**: a `[DialogGuard] ... rule=audio_interface_unavailable -> click button='OK'` line.")
        L.append("- **Healthy => silent**: NO `[[EXPORT_FAILURE]]` line anywhere in the run.")
        L.append(f"- **Scan-timing totals**: `[SCAN] load ...` and `[SCAN] export ...` lines. {scan_hint}")
        L.append("")
        if progress_log:
            L.append("### Progress timeline (last 12 distinct states)")
            L.append("")
            L.append("```")
            for e in progress_log[-12:]:
                slim = {k: e.get(k) for k in
                        ("progress", "status_title", "status_sub", "done", "error")
                        if e.get(k) not in (None, "", False) or k in ("progress", "done")}
                L.append(json.dumps(slim, ensure_ascii=False))
            L.append("```")
            L.append("")
        return "\n".join(L)


def write_status(run_md):
    """Preserve everything up to and including CERT_MARKER; regenerate below it."""
    header = None
    if STATUS_PATH.exists():
        txt = STATUS_PATH.read_text()
        i = txt.find(CERT_MARKER)
        if i >= 0:
            header = txt[:i + len(CERT_MARKER)]
    if header is None:
        header = ("# StemExport — Logic Tier 0 status\n\n"
                  "_(hand-authored header missing; regenerate it — see docs.)_\n\n"
                  + CERT_MARKER)
    STATUS_PATH.write_text(header + "\n\n" + run_md + "\n")


# -- preflight ----------------------------------------------------------------
def preflight(rep, project, require_backend):
    """Local, mostly no-backend checks. Returns (ok, resolved_path, projectdata_fp,
    known_app). With require_backend False (--preflight) a down backend is a NOTE."""
    ok = True

    # Source project exists + resolves.
    if not os.path.exists(project):
        rep.check("source .logicx exists", False, f"not found: {project}")
        return False, None, None, None
    rep.check("source .logicx exists", True, project)

    resolved = project
    if resolve_project_path is not None:
        try:
            resolved = resolve_project_path(project)
            rep.check("project resolves to inner .logicx", True, resolved)
        except Exception as e:
            rep.check("project resolves to inner .logicx", False, str(e))
            ok = False
    else:
        rep.note("resolve_project_path unavailable (python/ import failed)")

    # ProjectData present (needed for the never-saved check).
    pd_fp = None
    pd = find_projectdata(resolved) if os.path.isdir(resolved) else None
    if pd:
        pd_fp = (pd, stat_fingerprint(pd))
        rep.check("ProjectData located (for never-saved check)", True, pd)
    else:
        rep.note("ProjectData not found in bundle — never-saved check will be skipped")

    # Logic must NOT already be running (the orchestrator launches it).
    lr = logic_running()
    if lr is True:
        rep.check("Logic Pro not already running", False,
                  "a Logic process is alive — quit it before certifying")
        ok = False
    elif lr is False:
        rep.check("Logic Pro not already running", True)
    else:
        rep.note("could not run pgrep to check Logic state")

    # Frontmost readable (needed for the focus check).
    fm = frontmost_app()
    if fm:
        rep.check("can read frontmost app (System Events)", True, f"currently {fm!r}")
    else:
        rep.note("could not read frontmost app — focus check will be a NOTE")

    # Backend reachable.
    up = False
    try:
        code, _ = http_get("/health", timeout=3.0)
        up = code == 200
    except Exception as e:
        if require_backend:
            rep.check("Flask backend reachable on :5123", False,
                      f"{e} — is `npm start` running?")
            ok = False
        else:
            rep.note(f"backend not reachable (expected for --preflight): {e}")
    if up:
        rep.check("Flask backend reachable on :5123", True)
    elif require_backend and up is False:
        # already recorded failure above if exception; if reached HTTP but not 200:
        pass

    return ok, resolved, pd_fp, fm


# -- main flow ----------------------------------------------------------------
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    preflight_only = "--preflight" in sys.argv[1:]
    project = args[0] if len(args) > 0 else DEFAULT_PROJECT
    out = args[1] if len(args) > 1 else DEFAULT_OUT
    os.makedirs(out, exist_ok=True)

    rep = Report()
    print("\nStemExport — Logic Tier 0 certification tester")
    print(f"  project : {project}")
    print(f"  output  : {out}")
    print(f"  mode    : {'PREFLIGHT ONLY' if preflight_only else 'FULL CERTIFICATION'}\n")

    ok, resolved, pd_fp, known_app = preflight(
        rep, project, require_backend=not preflight_only)

    if preflight_only:
        print("\n[tester] preflight-only complete "
              f"({'OK' if ok and rep.all_passed else 'ISSUES'}).")
        sys.exit(0 if ok else 2)

    if not ok:
        write_status(rep.run_markdown(project, out, [], ""))
        print(f"\n[tester] PREFLIGHT FAILED — see {STATUS_PATH}")
        sys.exit(2)

    project_name = os.path.splitext(os.path.basename(resolved))[0]
    source_folder = os.path.join(out, project_name)

    # Trigger the export (headless — the path we certify; it is the server default).
    print("\n[tester] POST /export ...")
    try:
        code, body = http_post("/export", {"file_path": project, "output_folder": out})
    except Exception as e:
        rep.check("/export accepted the request", False, str(e))
        write_status(rep.run_markdown(project, out, [], ""))
        sys.exit(1)
    if code != 200 or not body.get("started"):
        rep.check("/export accepted the request", False, f"HTTP {code} body={body}")
        write_status(rep.run_markdown(project, out, [], ""))
        sys.exit(1)
    rep.check("/export accepted the request", True)

    # Poll progress.
    print("[tester] polling /export/progress (Ctrl-C to abort) ...\n")
    deadline = time.time() + EXPORT_TIMEOUT
    last_sig = None
    progress_log = []
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
            print(f"  [{state.get('progress', 0) or 0:>3}%] "
                  f"{state.get('status_title', '')} — {state.get('status_sub', '')}")
        if state.get("done"):
            final_state = state
            timed_out = False
            break
        time.sleep(POLL_INTERVAL)

    if timed_out:
        last = progress_log[-1].get("status_title") if progress_log else "no data"
        rep.check("export completed within timeout", False,
                  f"timed out after {EXPORT_TIMEOUT // 60} min — last: {last}")
        write_status(rep.run_markdown(project, out, progress_log, ""))
        print(f"\n[tester] TIMED OUT — see {STATUS_PATH}")
        sys.exit(1)
    rep.check("export completed within timeout", True)

    # (f) healthy => silent (proxy for zero [[EXPORT_FAILURE]] markers).
    if final_state.get("error"):
        rep.check("backend reported NO error (healthy => no failure marker)", False,
                  str(final_state["error"]))
    else:
        rep.check("backend reported NO error (healthy => no failure marker)", True)

    zip_path = final_state.get("zip_path")

    # (a) single <project>.zip present AND source folder deleted.
    if zip_path and os.path.isfile(zip_path):
        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        rep.check("output is a single <project>.zip on disk", True,
                  f"{zip_path} ({size_mb:.1f} MB)")
    else:
        rep.check("output is a single <project>.zip on disk", False,
                  f"backend zip_path={zip_path!r} not present")
    if os.path.exists(source_folder):
        rep.check("un-zipped source folder was deleted", False,
                  f"still present: {source_folder}")
    else:
        rep.check("un-zipped source folder was deleted", True, f"gone: {source_folder}")

    # (b)+(c) zip contents + Raw differs — all from the ZIP (folder is gone).
    if zip_path and os.path.isfile(zip_path):
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                rep.check("zip is a readable archive", True, f"{len(names)} entries")
                for sub in EXPECTED_SUBFOLDERS:
                    wavs = [n for n in names
                            if f"/{sub}/" in n and n.lower().endswith(".wav")]
                    rep.check(f"zip set {sub} has >=2 stems", len(wavs) >= 2,
                              f"{len(wavs)} WAV(s)")
                raw = {os.path.basename(n): n for n in names
                       if "/02_Raw/" in n and n.lower().endswith(".wav")}
                fx = {os.path.basename(n): n for n in names
                      if "/01_With_FX/" in n and n.lower().endswith(".wav")}
                shared = sorted(set(raw) & set(fx))
                if not shared:
                    rep.check("02_Raw differs from 01_With_FX (FX bypassed)", False,
                              "no same-named stems to compare")
                else:
                    differ = [b for b in shared
                              if sha256_zip_entry(zf, raw[b]) != sha256_zip_entry(zf, fx[b])]
                    rep.check("02_Raw differs from 01_With_FX (FX bypassed)",
                              len(differ) > 0,
                              f"{len(differ)}/{len(shared)} shared stems differ")
                    identical = [b for b in shared if b not in differ]
                    if identical:
                        rep.note(f"{len(identical)} stem(s) byte-identical across sets "
                                 f"(expected for tracks whose only FX is on a parent group): "
                                 f"{', '.join(identical)}")
        except Exception as e:
            rep.check("zip is a readable archive", False, str(e))

    # (d) never saved — ProjectData byte-unchanged (size + mtime).
    if pd_fp:
        pd_path, before = pd_fp
        try:
            after = stat_fingerprint(pd_path)
            rep.check("project never saved (ProjectData size+mtime unchanged)",
                      before == after,
                      "identical" if before == after else f"changed {before} -> {after}")
        except Exception as e:
            rep.check("project never saved (ProjectData size+mtime unchanged)", False,
                      f"could not re-stat ProjectData: {e}")
    else:
        rep.note("never-saved check skipped (no ProjectData located)")

    # (e) focus ends on the user's app, not Logic.
    end_app = frontmost_app()
    if not end_app or not known_app:
        rep.note(f"focus check inconclusive (start={known_app!r} end={end_app!r})")
    else:
        on_logic = end_app in LOGIC_PROCESS_NAMES
        rep.check("focus ended on the user's app (not Logic)",
                  (end_app == known_app) and not on_logic,
                  f"start={known_app!r} end={end_app!r}")

    # Logic quit cleanly.
    lr = logic_running()
    if lr is True:
        rep.check("Logic quit cleanly after export", False, "a Logic process is still alive")
    elif lr is False:
        rep.check("Logic quit cleanly after export", True)
    else:
        rep.note("could not pgrep Logic post-run")

    scan_hint = "(the last [SCAN] line is the cumulative total across load + both passes)"
    write_status(rep.run_markdown(project, out, progress_log, scan_hint))
    print(f"\n[tester] Report written to {STATUS_PATH}")
    if rep.all_passed:
        print("[tester] ALL GREEN ✅  — also eyeball the npm terminal for C9 / no-[[EXPORT_FAILURE]] / [SCAN] totals.")
        sys.exit(0)
    n = sum(1 for _, p, _ in rep.checks if not p)
    print(f"[tester] {n} failure(s) — read STATUS.md")
    sys.exit(1)


if __name__ == "__main__":
    main()
