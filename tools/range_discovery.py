#!/usr/bin/env python3
"""PROMPT 1.5a discovery harness (DISCOVERY ONLY — does NOT modify logic_render.py).

Answers: does `File ▸ Export ▸ All Tracks as Audio Files…` honour CYCLE / LOCATORS /
PLAYHEAD?  Drives Logic with element-level System Events only (no screenshots, no
coordinate clicks). Reuses LogicRenderBridge for the export + quit.

Deterministic state primitives available on this install (see HANDOFF/DISCOVERY):
  • Return                                          → playhead to bar 1
  • ⌘A                                              → select all regions
  • Navigate ▸ Set Locators by Selection and Enable Cycle  → locators = full span, cycle ON
  • Navigate ▸ Move Locators Forward by Cycle Length       → shift loop one span forward
  • key "c"                                         → toggle cycle (no menu item exists)
  • Navigate ▸ Go To ▸ Position…                    → move playhead numerically

Cycle on/off is NOT readable via AX here, so we make state KNOWN by construction
(Set Locators…Enable Cycle => cycle ON; one "c" after => cycle OFF).

Usage:  python3 tools/range_discovery.py <step>
  steps: dismiss | baseline | t2_playhead | t1_loop_on | t1_loop_off | popups | quit
Each export writes WAVs to its own temp folder and prints per-stem durations.
"""
import os
import subprocess
import sys
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))
import logic_render as lr  # noqa: E402

PROC = lr.LOGIC_PROCESS_NAME
OUT_ROOT = '/tmp/stemexport_range'


# ── osascript helpers ───────────────────────────────────────────────────────────
def osa(script, timeout=60):
    r = subprocess.run(['osascript', '-e', script], capture_output=True,
                       text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def dismiss_conflicts():
    """Click 'Ignore' on a modal 'Key Command Assignment Conflicts' sheet/window so
    it can't block transport prep or the export dialog. Same pattern as
    _dismiss_replace_sheet. Best-effort, non-fatal. (To be folded into
    logic_render.py after discovery.)"""
    osa(f'''tell application "System Events" to tell process "{PROC}"
        try
            repeat with w in windows
                repeat with b in buttons of w
                    try
                        if (name of b) is "Ignore" then click b
                    end try
                end repeat
                repeat with s in sheets of w
                    repeat with b in buttons of s
                        try
                            if (name of b) is "Ignore" then click b
                        end try
                    end repeat
                end repeat
            end repeat
        end try
    end tell''', timeout=10)


def menu_click(*path):
    """Click a nested menu item. path = (top_menu, item) or (top, sub, item) ..."""
    top = path[0]
    leaf = path[-1]
    # Build the AppleScript reference from the leaf outward.
    ref = f'menu item "{leaf}" of menu "{top}" of menu bar 1'
    if len(path) == 3:  # top > sub(menu) > leaf
        sub = path[1]
        ref = (f'menu item "{leaf}" of menu 1 of menu item "{sub}" '
               f'of menu "{top}" of menu bar 1')
    osa(f'''tell application "System Events" to tell process "{PROC}"
        set frontmost to true
        delay 0.25
        click {ref}
    end tell''', timeout=15)


def keystroke(ch, mods=None):
    using = ''
    if mods:
        using = ' using {' + ', '.join(m + ' down' for m in mods) + '}'
    osa(f'''tell application "System Events" to tell process "{PROC}"
        set frontmost to true
        delay 0.2
        keystroke "{ch}"{using}
    end tell''', timeout=10)


def key_return():
    osa(f'''tell application "System Events" to tell process "{PROC}"
        set frontmost to true
        delay 0.2
        key code 36
    end tell''', timeout=10)


# ── transport prep primitives ────────────────────────────────────────────────────
def select_all():
    keystroke('a', ['command'])
    time.sleep(0.3)


def set_locators_cycle_on():
    """Cmd-A then Set Locators by Selection and Enable Cycle => locators = full span,
    cycle KNOWN-ON."""
    dismiss_conflicts()
    select_all()
    menu_click('Navigate', 'Set Locators by Selection and Enable Cycle')
    time.sleep(0.4)
    dismiss_conflicts()


def move_locators_forward():
    menu_click('Navigate', 'Move Locators Forward by Cycle Length')
    time.sleep(0.3)
    dismiss_conflicts()


def toggle_cycle():
    keystroke('c')
    time.sleep(0.3)
    dismiss_conflicts()


def playhead_to_start():
    key_return()
    time.sleep(0.3)


def goto_position(bar):
    """Open Navigate ▸ Go To ▸ Position…, type the bar number, confirm with OK.

    Logic's position field is exposed via AX as AXSliders with encoded values (not
    settable), but the dialog accepts TYPED input: typing a number replaces the
    (pre-selected) bar segment of the 'New' field, then OK commits. Verified: typing
    "5" + OK moves the playhead to bar 5 (Current reads `5 1 1 1` afterward)."""
    menu_click('Navigate', 'Go To', 'Position…')
    time.sleep(0.6)
    osa(f'''tell application "System Events" to tell process "{PROC}"
        if exists window "Go To Position" then
            keystroke "{bar}"
            delay 0.2
            click button "OK" of window "Go To Position"
        end if
    end tell''', timeout=10)
    time.sleep(0.4)


# ── WAV inspection ────────────────────────────────────────────────────────────────
def wav_report(folder):
    rows = []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith('.wav'):
            continue
        fp = os.path.join(folder, name)
        try:
            with wave.open(fp, 'rb') as w:
                fr = w.getframerate()
                n = w.getnframes()
                dur = n / fr if fr else 0
                rows.append((name, dur, n, fr, w.getsampwidth() * 8,
                             os.path.getsize(fp)))
        except Exception as e:
            rows.append((name, None, None, None, None, f'ERR {e}'))
    return rows


def print_report(label, folder):
    rows = wav_report(folder)
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
    if durs:
        print(f'  -> count={len(durs)} min={min(durs):.3f}s max={max(durs):.3f}s '
              f'equal={abs(max(durs)-min(durs))<0.01}')


# ── export (reuse the proven bridge path) ─────────────────────────────────────────
def export_to(subfolder, bypass=False):
    folder = os.path.join(OUT_ROOT, subfolder)
    # fresh folder so wait_for_export_complete sees only this run's files
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            try:
                os.remove(os.path.join(folder, f))
            except OSError:
                pass
    os.makedirs(folder, exist_ok=True)
    b = lr.LogicRenderBridge()
    b.process_name = lr.detect_logic_process_name()
    dismiss_conflicts()
    b.export_stems(folder, bypass_fx=bypass)
    return folder


# ── export with an explicit range mode set on pop-up #2 ───────────────────────────
def export_with_range_mode(subfolder, mode):
    """Like the bridge export, but explicitly set dialog pop-up #2 (the range/silence
    pop-up) to `mode` before clicking Export. mode ∈ {'Trim Silence at File End',
    'Export Cycle Range Only', 'Extend File Length to Project End'}."""
    folder = os.path.join(OUT_ROOT, subfolder)
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            try:
                os.remove(os.path.join(folder, f))
            except OSError:
                pass
    os.makedirs(folder, exist_ok=True)

    dismiss_conflicts()
    # open export dialog
    osa(f'''tell application "System Events" to tell process "{PROC}"
        set frontmost to true
        delay 0.3
        click menu item "{lr.EXPORT_MENU_ITEM}" of menu "Export" of menu item "Export" of menu "File" of menu bar 1
    end tell''', timeout=20)
    time.sleep(1.5)
    dismiss_conflicts()
    # set destination + format + bypass off + normalize off + range mode, then Export
    osa(f'''tell application "System Events" to tell process "{PROC}"
        set w to window "Open"
        if exists button "Show Options" of w then
            click button "Show Options" of w
            delay 0.3
        end if
        keystroke "g" using {{command down, shift down}}
        delay 0.5
        keystroke "a" using {{command down}}
        delay 0.1
        keystroke "{folder}"
        delay 0.3
        keystroke return
        delay 0.8
        -- range/silence pop-up (#2)
        set v2 to (value of pop up button 2 of w) as text
        if v2 is not "{mode}" then
            click pop up button 2 of w
            delay 0.3
            click menu item "{mode}" of menu 1 of pop up button 2 of w
            delay 0.2
        end if
        -- format -> WAVE
        repeat with p in (every pop up button of w)
            set v to ""
            try
                set v to (value of p) as text
            end try
            if v is in {{"AIFF", "WAVE", "CAF"}} then
                if v is not "WAVE" then
                    click p
                    delay 0.3
                    click menu item "WAVE" of menu 1 of p
                    delay 0.2
                end if
                exit repeat
            end if
        end repeat
        -- normalize -> Off
        repeat with p in (every pop up button of w)
            set v to ""
            try
                set v to (value of p) as text
            end try
            if v is in {{"Off", "Overload Protection Only", "On"}} then
                if v is not "Off" then
                    click p
                    delay 0.3
                    click menu item "Off" of menu 1 of p
                    delay 0.2
                end if
                exit repeat
            end if
        end repeat
        click button "Export" of w
    end tell''', timeout=60)
    # handle a possible replace sheet
    b = lr.LogicRenderBridge()
    b.process_name = PROC
    b._dismiss_replace_sheet()
    b.wait_for_export_complete(folder)
    return folder


# ── popups: enumerate the Trim Silence pop-up (dialog pop-up #2) ──────────────────
def enumerate_popups():
    dismiss_conflicts()
    # open the export dialog
    osa(f'''tell application "System Events" to tell process "{PROC}"
        set frontmost to true
        delay 0.3
        click menu item "{lr.EXPORT_MENU_ITEM}" of menu "Export" of menu item "Export" of menu "File" of menu bar 1
    end tell''', timeout=20)
    time.sleep(1.5)
    dismiss_conflicts()
    # make sure options are visible
    osa(f'''tell application "System Events" to tell process "{PROC}"
        if exists window "Open" then
            if exists button "Show Options" of window "Open" then
                click button "Show Options" of window "Open"
                delay 0.4
            end if
        end if
    end tell''', timeout=15)
    # dump value of every pop-up + open menu items
    for i in range(1, 7):
        rc, out, err = osa(f'''tell application "System Events" to tell process "{PROC}"
            if not (exists window "Open") then return "NO DIALOG"
            if not (exists pop up button {i} of window "Open") then return "NO POPUP {i}"
            set v to (value of pop up button {i} of window "Open") as text
            click pop up button {i} of window "Open"
            delay 0.5
            set m to name of every menu item of menu 1 of pop up button {i} of window "Open"
            key code 53
            return "val=[" & v & "]  menu=" & (m as text)
        end tell''', timeout=20)
        print(f'pop up {i}: {out or err}')
    # cancel
    osa(f'''tell application "System Events" to tell process "{PROC}"
        if exists window "Open" then
            if exists button "Cancel" of window "Open" then click button "Cancel" of window "Open"
        end if
    end tell''', timeout=10)


# ── steps ─────────────────────────────────────────────────────────────────────────
def main():
    step = sys.argv[1] if len(sys.argv) > 1 else 'help'
    if step == 'dismiss':
        dismiss_conflicts()
        print('dismissed (if present)')

    elif step == 'baseline':
        # full song: cycle KNOWN-OFF, playhead bar 1, locators = full span
        set_locators_cycle_on()   # cycle ON, locators = full span
        toggle_cycle()            # cycle OFF (known)
        playhead_to_start()       # playhead bar 1
        f = export_to('baseline')
        print_report('BASELINE full song (cycle OFF, playhead bar1)', f)

    elif step == 't2_playhead':
        # cycle OFF, locators full, playhead moved mid-project (NO Return before export)
        set_locators_cycle_on()
        toggle_cycle()            # cycle OFF
        playhead_to_start()
        goto_position(int(sys.argv[2]) if len(sys.argv) > 2 else 3)  # playhead -> bar N
        f = export_to('t2_playhead')
        print_report('T2 playhead mid-project (cycle OFF)', f)

    elif step == 't1_loop_on':
        # cycle ON, locators shifted OFF content -> honoured? => empty/silent
        set_locators_cycle_on()   # cycle ON, locators full span
        move_locators_forward()   # locators now past all content, cycle STILL ON
        f = export_to('t1_loop_on')
        print_report('T1 loop ON, locators off-content', f)

    elif step == 't1_loop_off':
        # same off-content locators but cycle OFF -> distinguishes B vs C
        set_locators_cycle_on()   # cycle ON, locators full span
        move_locators_forward()   # locators past content, cycle ON
        toggle_cycle()            # cycle OFF (known)
        f = export_to('t1_loop_off')
        print_report('T3 locators off-content, cycle OFF', f)

    elif step == 'cycle_probe':
        # Only global keystrokes work here (Cmd-A / Return / Go-To-Locator are dead
        # without Tracks-pane focus, which AX can't grab). "c" is a GLOBAL transport
        # toggle (like "x" for Mixer, proven to reach the window). We can't read cycle
        # state, so toggle+export twice: one of the two has cycle ON. If either export
        # differs from the 16.364s full-song baseline => export HONOURS cycle.
        toggle_cycle()           # flip cycle once
        fa = export_to('cycle_a')
        print_report('CYCLE PROBE A (one "c" toggle from open state)', fa)
        toggle_cycle()           # flip back
        fb = export_to('cycle_b')
        print_report('CYCLE PROBE B (second "c" toggle)', fb)

    elif step == 'range_mode':
        mode = sys.argv[2] if len(sys.argv) > 2 else 'Extend File Length to Project End'
        f = export_with_range_mode('range_' + mode.split()[0].lower(), mode)
        print_report(f'RANGE MODE = "{mode}"', f)

    elif step == 'popups':
        enumerate_popups()

    elif step == 'quit':
        b = lr.LogicRenderBridge()
        b.process_name = lr.detect_logic_process_name()
        b.quit_logic()
        print('quit issued; alive=', b.is_alive())

    else:
        print(__doc__)


if __name__ == '__main__':
    main()
