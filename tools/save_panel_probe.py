"""
save_panel_probe.py — P1 discovery probe for the Invisible/Background render phase.

GOAL (docs/2026-06-28/Invisible_Render_Handoff_v1.md, P1): the export driver today
TYPES the destination path (⌘⇧G → ⌘A → keystroke "<path>" → return), and macOS
keystrokes always go to the FRONTMOST app — so Logic must be brought frontmost,
stealing the user's focus. This probe answers the single question that decides the
Tier-0 shape:

    Can the export ("Open" / Cocoa save panel) DESTINATION path be set via the
    accessibility *value* of an element, with Logic NOT frontmost (no focus steal)?

It is read-mostly: it opens the export dialog, DUMPS the AX tree of window "Open"
and of the ⌘⇧G "Go to Folder" sheet, performs ONE set-value test while Logic is
backgrounded, then CANCELS and quits WITHOUT saving. It never exports, never saves.

Run with the Bash sandbox DISABLED (System Events + reading ~/Desktop need it):

    python3 tools/save_panel_probe.py "/Users/<you>/Desktop/logic test.logicx"

Writes the full dumps to docs/2026-06-28/probe_save_panel.txt and prints a summary.
Mirrors the harness style of tools/range_discovery.py and reuses LogicRenderBridge
for launch/ready/quit so behaviour matches production.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))
import logic_render as lr  # noqa: E402

OUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'docs', '2026-06-28',
                        'probe_save_panel.txt')

# A real, existing folder we try to push into the path field (we never click Go,
# so nothing navigates/exports — we only set the value and read it back).
TEST_DIR = os.path.expanduser('~/Desktop')

PROC = lr.LOGIC_PROCESS_NAME  # replaced with the live name after launch


def osa(script, timeout=30):
    """Run AppleScript; return (returncode, stdout, stderr)."""
    r = subprocess.run(['osascript', '-e', script], capture_output=True,
                       text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def frontmost_app():
    rc, out, err = osa('tell application "System Events" to '
                       'get name of first process whose frontmost is true')
    return out or f'(err: {err})'


# ── AX tree dump ────────────────────────────────────────────────────────────────
# Enumerate the interesting control classes inside a container. We deliberately do
# NOT use `entire contents` — a save panel's file browser holds hundreds of rows
# and would bury the few controls we care about. Save panels keep the accessory
# controls (pop-ups/checkboxes) and the Go-to combo box at/near the window level.
DUMP_CLASSES = ['text field', 'combo box', 'pop up button', 'checkbox',
                'button', 'sheet', 'group', 'scroll area']


def dump_container(container_expr):
    out_lines = [f'### {container_expr}']
    for cls in DUMP_CLASSES:
        script = f'''tell application "System Events" to tell process "{PROC}"
            set out to ""
            try
                set els to (every {cls} of {container_expr})
            on error errMsg
                return "ENUM_ERR:" & errMsg
            end try
            set i to 0
            repeat with e in els
                set i to i + 1
                set nm to "-"
                set vl to "-"
                set sr to "-"
                set en to "-"
                try
                    set nm to (name of e) as text
                end try
                try
                    set vl to (value of e) as text
                end try
                try
                    set sr to (subrole of e) as text
                end try
                try
                    set en to (enabled of e) as text
                end try
                set out to out & "  [" & i & "] name=" & nm & " | value=" & vl & " | subrole=" & sr & " | enabled=" & en & linefeed
            end repeat
            return out
        end tell'''
        rc, sout, serr = osa(script)
        body = sout if sout.strip() else (serr or '')
        if body.startswith('ENUM_ERR') or not body.strip():
            out_lines.append(f'{cls}: (none / {body.strip() or "empty"})')
        else:
            out_lines.append(f'{cls}:')
            out_lines.append(body.rstrip())
    return '\n'.join(out_lines)


def dump_all_windows():
    """Diagnostic: every window of the Logic process with subrole, sheet count,
    and the button names on it / its sheets — to see what (alert? sheet?) is in
    the way when the export dialog won't open."""
    rc, out, err = osa(f'''tell application "System Events" to tell process "{PROC}"
        set out to ""
        repeat with w in windows
            set nm to "-"
            set sr to "-"
            try
                set nm to (name of w) as text
            end try
            try
                set sr to (subrole of w) as text
            end try
            set out to out & "WINDOW name=" & nm & " subrole=" & sr & linefeed
            try
                repeat with b in buttons of w
                    set out to out & "   btn: " & (name of b as text) & linefeed
                end repeat
            end try
            try
                repeat with s in sheets of w
                    set out to out & "   SHEET buttons:" & linefeed
                    repeat with b in buttons of s
                        set out to out & "     btn: " & (name of b as text) & linefeed
                    end repeat
                end repeat
            end try
        end repeat
        return out
    end tell''')
    return out or f'(err: {err})'


def read_and_dismiss_alerts():
    """Capture, then SAFELY dismiss, any free-floating alert/AXDialog blocking the
    project (e.g. the launch-time 'Open Settings / OK' dialog). Reads each alert's
    static-text body + buttons (for the future DialogGuard catalog), then clicks a
    SAFE dismiss button — never 'Open Settings' / destructive verbs. Returns the
    captured descriptions. Best-effort, idempotent."""
    rc, out, err = osa(f'''tell application "System Events" to tell process "{PROC}"
        set report to ""
        repeat with w in windows
            set sr to "-"
            try
                set sr to (subrole of w) as text
            end try
            if sr is "AXDialog" then
                set report to report & "ALERT name=" & (name of w as text) & linefeed
                try
                    repeat with t in static texts of w
                        set report to report & "  text: " & (value of t as text) & linefeed
                    end repeat
                end try
                set btns to {{}}
                try
                    repeat with b in buttons of w
                        set end of btns to (name of b as text)
                    end repeat
                end try
                set report to report & "  buttons: " & (btns as text) & linefeed
                -- click a SAFE dismiss button (never 'Open Settings'/destructive)
                repeat with b in buttons of w
                    set bn to (name of b as text)
                    if bn is in {{"OK", "Continue", "Close", "Cancel", "Ignore", "Later", "Not Now"}} then
                        click b
                        set report to report & "  -> clicked: " & bn & linefeed
                        exit repeat
                    end if
                end repeat
            end if
        end repeat
        return report
    end tell''')
    return out or (f'(err: {err})' if err else '')


def open_export_dialog(bridge):
    bridge._dismiss_conflict_sheet()
    read_and_dismiss_alerts()
    rc, out, err = osa(f'''tell application "System Events" to tell process "{PROC}"
        set frontmost to true
        delay 0.4
        click menu item "{lr.EXPORT_MENU_ITEM}" of menu "Export" of menu item "Export" of menu "File" of menu bar 1
        return "clicked"
    end tell''', timeout=20)
    print(f'[probe] menu-click rc={rc} out={out!r} err={err!r}')
    if not bridge._wait_for_open_dialog(timeout=30):
        diag = dump_all_windows()
        print('[probe] DIAG windows when dialog failed to open:\n' + diag)
        raise RuntimeError('Export dialog ("Open" window) never appeared.\n'
                           f'menu-click err: {err!r}\nwindows:\n{diag}')
    bridge._dismiss_conflict_sheet()
    # Reveal accessory options (pop-ups/checkboxes) so they're in the dump.
    osa(f'''tell application "System Events" to tell process "{PROC}"
        if exists button "Show Options" of window "Open" then
            click button "Show Options" of window "Open"
            delay 0.3
        end if
    end tell''')


def open_goto_sheet():
    """Open the ⌘⇧G "Go to Folder" sheet (needs Logic frontmost for the keystroke
    — that's exactly the focus-grab we're trying to characterise). Returns True if
    a sheet appeared on window "Open"."""
    osa(f'''tell application "System Events" to tell process "{PROC}"
        set frontmost to true
        delay 0.3
        keystroke "g" using {{command down, shift down}}
        delay 0.6
    end tell''')
    rc, out, err = osa(f'tell application "System Events" to tell process '
                       f'"{PROC}" to return (exists sheet 1 of window "Open")')
    return out == 'true'


def set_value_backgrounded(target_expr, value):
    """Make Finder frontmost, then — WITHOUT touching Logic's frontmost — try to
    set `value` on `target_expr` and read it back. Returns a dict describing what
    happened, including whether focus stayed off Logic."""
    osa('tell application "Finder" to activate')
    time.sleep(0.6)
    front_before = frontmost_app()
    script = f'''tell application "System Events" to tell process "{PROC}"
        try
            set value of {target_expr} to "{lr._as_str(value)}"
        on error errMsg
            return "SET_ERR:" & errMsg
        end try
        delay 0.3
        try
            return "OK:" & ((value of {target_expr}) as text)
        on error errMsg2
            return "READ_ERR:" & errMsg2
        end try
    end tell'''
    rc, out, err = osa(script)
    time.sleep(0.3)
    front_after = frontmost_app()
    return {
        'target': target_expr,
        'front_before': front_before,
        'result': out or err,
        'front_after': front_after,
        'focus_kept_off_logic': front_after not in (PROC, 'Logic Pro X', 'Logic Pro'),
    }


def cancel_everything():
    """Dismiss the Go-to sheet and the Open dialog by CLICKING Cancel buttons
    (element clicks work backgrounded — no keystroke, no frontmost)."""
    osa(f'''tell application "System Events" to tell process "{PROC}"
        try
            if exists sheet 1 of window "Open" then
                repeat with b in buttons of sheet 1 of window "Open"
                    if name of b is "Cancel" then click b
                end repeat
            end if
        end try
        delay 0.3
        try
            if exists window "Open" then
                if exists button "Cancel" of window "Open" then click button "Cancel" of window "Open"
            end if
        end try
    end tell''')


def package_signature(path):
    """Newest mtime found anywhere inside the .logicx package — to prove we never
    saved (signature must be identical before/after)."""
    newest = 0.0
    for root, _dirs, files in os.walk(path):
        for n in [*files, *_dirs]:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, n)))
            except OSError:
                pass
    try:
        newest = max(newest, os.path.getmtime(path))
    except OSError:
        pass
    return newest


def main():
    global PROC
    if len(sys.argv) < 2:
        print('usage: python3 tools/save_panel_probe.py "<path to .logicx>"')
        sys.exit(2)
    project = sys.argv[1]
    resolved = lr.resolve_project_path(project)
    sig_before = package_signature(resolved)

    bridge = lr.LogicRenderBridge()
    print(f'[probe] launching Logic with: {resolved}')
    bridge.launch(resolved)
    PROC = bridge.process_name
    if not bridge.wait_for_logic_ready():
        raise RuntimeError('Logic did not become ready.')
    lr.dismiss_macos_crash_reporter()
    # Clear any launch-time alert/AXDialog (e.g. 'Open Settings / OK') that floats
    # in front of the project and would block the Export menu. Capture its text.
    time.sleep(1.0)
    alerts = read_and_dismiss_alerts()
    if alerts.strip():
        print('[probe] launch-time alert captured + dismissed:\n' + alerts)
    time.sleep(0.5)

    report = []
    report.append('# P1 save-panel probe — ' + time.strftime('%Y-%m-%d %H:%M:%S'))
    report.append(f'project (resolved): {resolved}')
    report.append(f'process name      : {PROC}')
    report.append(f'frontmost at start: {frontmost_app()}')
    if alerts.strip():
        report.append('')
        report.append('== LAUNCH-TIME ALERT(S) captured + dismissed ==')
        report.append(alerts.rstrip())
    report.append('')

    try:
        print('[probe] opening export dialog…')
        open_export_dialog(bridge)
        report.append('== DUMP: window "Open" (accessory options shown) ==')
        report.append(dump_container('window "Open"'))
        report.append('')

        print('[probe] opening ⌘⇧G Go-to-Folder sheet…')
        had_sheet = open_goto_sheet()
        report.append(f'== ⌘⇧G Go-to-Folder sheet present: {had_sheet} ==')
        if had_sheet:
            report.append(dump_container('sheet 1 of window "Open"'))
        report.append('')

        # Decisive test(s): set the path field by VALUE while backgrounded.
        report.append('== SET-VALUE-WHILE-BACKGROUNDED TESTS ==')
        candidates = []
        if had_sheet:
            candidates += [
                'combo box 1 of sheet 1 of window "Open"',
                'text field 1 of sheet 1 of window "Open"',
            ]
        candidates += [
            'combo box 1 of window "Open"',
            'text field 1 of window "Open"',
        ]
        for expr in candidates:
            res = set_value_backgrounded(expr, TEST_DIR)
            print(f'[probe] {expr} -> {res["result"]} '
                  f'(front_after={res["front_after"]})')
            report.append(
                f'- target   : {res["target"]}\n'
                f'  set TEST_DIR={TEST_DIR}\n'
                f'  result    : {res["result"]}\n'
                f'  front before/after: {res["front_before"]} -> {res["front_after"]}\n'
                f'  focus kept off Logic: {res["focus_kept_off_logic"]}')
        report.append('')
    finally:
        print('[probe] cancelling dialog + quitting Logic (no save)…')
        cancel_everything()
        time.sleep(0.5)
        bridge.quit_logic()

    time.sleep(1.0)
    sig_after = package_signature(resolved)
    report.append('== NEVER-SAVED CHECK ==')
    report.append(f'package newest-mtime before: {sig_before}')
    report.append(f'package newest-mtime after : {sig_after}')
    report.append(f'unchanged (never saved)    : {sig_before == sig_after}')

    text = '\n'.join(report) + '\n'
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w') as f:
        f.write(text)
    print('\n' + '=' * 70)
    print(text)
    print('=' * 70)
    print(f'[probe] wrote {OUT_PATH}')


if __name__ == '__main__':
    main()
