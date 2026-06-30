#!/usr/bin/env python3
"""
LIVE 3-run verify for the DialogGuard 6b C9 fix (headless path).

Throwaway verification harness — NOT committed. Reproduces the exact regression
signal that was 0/3 before the fix: with the audio-interface (C9) alert up on
launch, does the headless guard now DETECT it, decide CLICK OK, click the real
OK button, and clear it so `wait_for_logic_ready()` returns ready?

Per run it:
  1. force-quits any orphan Logic (never saves),
  2. launches Logic BACKGROUNDED with the test project (the C9 alert appears),
  3. waits for the C9 AXDialog to show,
  4. runs the real headless readiness path (which calls the fixed detector →
     decide() → executor); records which buttons the executor clicked,
  5. confirms the AXDialog is gone (C9 cleared) and readiness succeeded,
  6. quits Logic cleanly WITHOUT saving and confirms it exited.

C9_ok for a run := executor clicked exactly 'OK' (never 'Open Settings')
                   AND the AXDialog cleared AND wait_for_logic_ready() == True.

Safe: never saves, never clicks a destructive/Open-Settings button, quits
backgrounded, no export is performed. Exit 0 iff C9_ok == 3/3.

Run (Logic must be CLOSED at start; leave the Mac otherwise idle):
    python3 tools/verify_c9_live.py
    python3 tools/verify_c9_live.py "/path/to/some other.logicx"
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'python'))

import logic_render as L                       # noqa: E402
from logic_render import LogicRenderBridge, DialogGuardPause   # noqa: E402

PROJECT = sys.argv[1] if len(sys.argv) > 1 else \
    os.path.expanduser('~/Desktop/logic test.logicx')
RUNS = 3
READY_TIMEOUT = 120.0
LOGIC_MAIN = 'Logic Pro X.app/Contents/MacOS/Logic'


def logic_pids():
    return subprocess.run(['pgrep', '-f', LOGIC_MAIN],
                          capture_output=True, text=True).stdout.split()


def axdialog_count(proc):
    try:
        out = L._osascript(
            f'tell application "System Events" to tell process "{proc}" to '
            f'return (count of (windows whose subrole is "AXDialog"))', timeout=10)
        return int(out or '0')
    except Exception:
        return -1


def force_quit_orphan():
    if not logic_pids():
        return
    print('  [pre] orphan Logic detected — quitting without saving...')
    b = LogicRenderBridge.__new__(LogicRenderBridge)
    b.headless = True
    b.process_name = 'Logic Pro X'
    try:
        b.quit_logic(force=True)
    except Exception as e:
        print(f'  [pre] quit error: {e!r}')
    time.sleep(2)


def one_run(i):
    force_quit_orphan()
    bridge = LogicRenderBridge(headless=True)

    # Instrument the executor's click so we can SEE what it clicked, while still
    # performing the real click.
    clicks = []
    real_click = bridge._click_dialog_button
    bridge._click_dialog_button = lambda label: (clicks.append(label),
                                                  real_click(label))[1]

    print(f'\n=== RUN {i}/{RUNS} ===')
    print(f'  launch (bg): {PROJECT}')
    bridge.launch(PROJECT)
    proc = bridge.process_name

    # Wait for the C9 AXDialog.
    end = time.time() + 90
    c9_present = False
    while time.time() < end:
        if axdialog_count(proc) >= 1:
            c9_present = True
            break
        time.sleep(1.0)
    print(f'  C9 alert present at launch: {c9_present}')

    ready = False
    paused = None
    try:
        ready = bridge.wait_for_logic_ready(timeout=READY_TIMEOUT, settle=2.0)
    except DialogGuardPause as e:
        paused = str(e)
    except Exception as e:
        paused = f'unexpected: {e!r}'

    cleared = axdialog_count(proc) == 0
    print(f'  executor clicked: {clicks}')
    print(f'  AXDialog cleared: {cleared} | wait_for_logic_ready: {ready}')
    if paused:
        print(f'  DialogGuardPause/err: {paused}')

    # Always quit cleanly without saving.
    try:
        bridge.quit_logic()
    except Exception as e:
        print(f'  quit error: {e!r}')
    time.sleep(2)
    gone = not logic_pids()
    print(f'  Logic exited cleanly: {gone}')

    c9_ok = (clicks == ['OK']) and cleared and bool(ready) and (paused is None)
    print(f'  --> C9_ok: {c9_ok}')
    return {'c9_present': c9_present, 'clicks': clicks, 'cleared': cleared,
            'ready': bool(ready), 'paused': paused, 'gone': gone, 'c9_ok': c9_ok}


def main():
    print('DialogGuard 6b — LIVE C9 verify')
    print('project:', PROJECT, '| exists:', os.path.exists(PROJECT))
    if logic_pids():
        print('NOTE: Logic is already running; it will be force-quit (no save) first.')
    rows = []
    for i in range(1, RUNS + 1):
        rows.append(one_run(i))
    ok = sum(1 for r in rows if r['c9_ok'])
    print('\n================ SUMMARY ================')
    for i, r in enumerate(rows, 1):
        print(f'  run {i}: C9_ok={r["c9_ok"]} clicked={r["clicks"]} '
              f'cleared={r["cleared"]} ready={r["ready"]} quit={r["gone"]}'
              + (f' PAUSE={r["paused"]}' if r['paused'] else ''))
    print(f'  C9_ok = {ok}/{RUNS}')
    print('========================================')
    sys.exit(0 if ok == RUNS else 1)


if __name__ == '__main__':
    main()
