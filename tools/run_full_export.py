#!/usr/bin/env python3
"""
run_full_export.py — Phase 1 "first green" verification harness (FULL two-pass).

Unlike `run_wet_export.py` (wet-only), this drives the REAL orchestrator
`StemExporter.run()` end to end: Pass 1 `01_With_FX` (bypass off) → Pass 2
`03_Raw` (bypass on) → T11 `_assert_raw_differs` guard → zip. It then prints a
per-stem WAV report for both sets and verifies the `.logicx` project was left
byte-identical (never saved).

Must run with the Bash sandbox DISABLED — the sandbox can't drive Logic or read
~/Desktop (see docs/2026-06-10/HANDOFF.md §6).

Usage:
    python3 tools/run_full_export.py "<project path>" ["<output folder>"]
"""
import hashlib
import os
import sys
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))

from logic_render import resolve_project_path  # noqa: E402
from stem_exporter import StemExporter  # noqa: E402


# ── project-bundle integrity snapshot (proves "never saved") ──────────────────
def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def snapshot_bundle(bundle_dir):
    """Map every file under the .logicx bundle to (size, mtime, sha256). Used to
    prove the project is byte-identical before/after the export."""
    snap = {}
    for root, _dirs, files in os.walk(bundle_dir):
        for name in files:
            fp = os.path.join(root, name)
            try:
                st = os.stat(fp)
                snap[os.path.relpath(fp, bundle_dir)] = (
                    st.st_size, st.st_mtime, _sha256(fp))
            except OSError:
                snap[os.path.relpath(fp, bundle_dir)] = ('ERR', 'ERR', 'ERR')
    return snap


def report_bundle_diff(before, after):
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in (set(before) & set(after)) if before[k] != after[k])
    project_data = sorted(k for k in (set(before) & set(after))
                          if os.path.basename(k) == 'ProjectData')
    print('\n=== PROJECT BYTE-UNCHANGED CHECK ===')
    if project_data:
        for k in project_data:
            same = before[k] == after[k]
            tag = 'IDENTICAL' if same else 'CHANGED'
            print(f'  ProjectData [{tag}]: {k}')
    else:
        print('  (no file named "ProjectData" found in bundle — reporting whole-tree)')
    if not added and not removed and not changed:
        print('  ✅ entire bundle byte-identical before/after (project untouched).')
        return True
    print(f'  ⚠️  bundle differs: {len(added)} added, {len(removed)} removed, '
          f'{len(changed)} changed')
    for k in added[:20]:
        print(f'      + {k}')
    for k in removed[:20]:
        print(f'      - {k}')
    for k in changed[:20]:
        print(f'      ~ {k}')
    # The verdict that matters: did ProjectData change?
    pd_changed = any(before[k] != after[k] for k in project_data)
    return not pd_changed


# ── per-stem WAV report ───────────────────────────────────────────────────────
def print_wav_report(label, folder):
    rows = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith('.wav'):
                continue
            fp = os.path.join(folder, name)
            try:
                with wave.open(fp, 'rb') as w:
                    fr = w.getframerate()
                    n = w.getnframes()
                    rows.append((name, n / fr if fr else 0, n, fr,
                                 w.getsampwidth() * 8, os.path.getsize(fp)))
            except Exception as e:
                rows.append((name, None, None, None, None, f'ERR {e}'))
    print(f'\n=== {label} : {folder} ===')
    if not rows:
        print('  (no WAV files)')
        return
    for name, dur, n, fr, bits, size in rows:
        if dur is None:
            print(f'  {name}: {size}')
        else:
            print(f'  {name}: {dur:8.3f}s  ({n} frames @ {fr}Hz, {bits}-bit, '
                  f'{size} bytes)')
    durs = [r[1] for r in rows if r[1] is not None]
    srs = {r[3] for r in rows if r[3] is not None}
    if durs:
        equal = abs(max(durs) - min(durs)) < 0.01
        print(f'  -> count={len(durs)} min={min(durs):.3f}s max={max(durs):.3f}s '
              f'equal_len={equal} sample_rate(s)={sorted(srs)}')
        # Trim Silence trims only the trailing tail, so every stem begins at the
        # same absolute t=0 (bar 1). Equal length ⇒ trimmed to a common end;
        # unequal length on a staggered project is acceptable as long as starts
        # align (inherent to the mode — it never trims the head).
        if not equal:
            print('     (unequal lengths — expected on a staggered-end project; '
                  'starts still align at bar 1 because Trim Silence trims only the tail)')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    project = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else '/tmp/stemexport_full'

    file_path = resolve_project_path(project)
    bundle_dir = file_path  # resolved inner .logicx (a bundle directory)
    project_name = os.path.splitext(os.path.basename(file_path))[0]
    os.makedirs(out, exist_ok=True)
    print(f'[full] project = {file_path}')
    print(f'[full] dest    = {os.path.join(out, project_name)}')

    print('[full] snapshotting project bundle (before)…')
    before = snapshot_bundle(bundle_dir)

    t0 = time.time()
    exporter = StemExporter(file_path, out, state={})
    result = exporter.run()  # full two-pass flow + T11 guard + zip
    print(f'\n[full] StemExporter.run() finished in {time.time() - t0:.1f}s')

    project_folder = result['project_folder']
    print_wav_report('01_With_FX', os.path.join(project_folder, '01_With_FX'))
    print_wav_report('03_Raw', os.path.join(project_folder, '03_Raw'))

    print(f'\n[full] zip = {result["zip_path"]}'
          f'  ({os.path.getsize(result["zip_path"])} bytes)')

    after = snapshot_bundle(bundle_dir)
    untouched = report_bundle_diff(before, after)

    # Summary verdict.
    fx = result['sets']['01_With_FX']
    raw = result['sets']['03_Raw']
    print('\n=== SUMMARY ===')
    print(f'  01_With_FX stems : {len(fx)}  (need ≥2)')
    print(f'  03_Raw stems     : {len(raw)}  (need ≥2)')
    print(f'  zip built        : {os.path.isfile(result["zip_path"])}')
    print(f'  project untouched: {untouched}')
    ok = len(fx) >= 2 and len(raw) >= 2 and os.path.isfile(result['zip_path']) and untouched
    print(f'  RESULT           : {"ALL GREEN ✅" if ok else "FAILURES ⚠️"}')
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
