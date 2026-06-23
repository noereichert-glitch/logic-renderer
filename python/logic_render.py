"""
logic_render.py — the Logic Pro driver (the ONE net-new file vs. the FL renderer).

This is the macOS-automation layer. It is the equivalent of FL's `fl_render.py`
and Ableton's `ableton_bridge.py`, but Logic is friendlier than either:

  • Logic's MENU BAR is accessible to System Events (standard Cocoa).
  • `File ▸ Export ▸ All Tracks as Audio Files…` opens a STANDARD Cocoa dialog
    whose controls (checkboxes, pop-ups, Save button) are accessible — so we drive
    it by ELEMENT, never by screenshot/coordinate (no Screen Recording permission).
  • The "Bypass Effect Plug-ins" checkbox in that dialog gives us the dry/Raw pass
    for free — no Remote Script, no config-file editing.

PERMISSIONS: this uses AppleScript/System Events to control Logic → the app needs
Accessibility + Automation permission once (granted on first run). It deliberately
uses NO Screen Recording (we click elements, not pixels) and does NOT automate
Finder.

═══════════════════════════════════════════════════════════════════════════════
GROUND TRUTH (discovered 2026-06-06 on the installed Logic — see
docs/2026-06-06/DISCOVERY.md for the probes that produced these):

  • App bundle    : /Applications/Logic Pro X.app
  • Process name  : "Logic Pro X"  (NOT "Logic Pro"; pgrep -x needs the exact str)
  • Menu path     : File ▸ Export ▸ "All Tracks as Audio Files…"  (real ellipsis …)
  • Export dialog : a separate window titled "Open" (Cocoa save panel)
      - File Format pop-up  : value ∈ {AIFF, WAVE, CAF}            → want WAVE
      - Bypass checkbox     : AXCheckBox "Bypass Effect Plug-ins"  → 0 wet / 1 raw
      - Normalize pop-up    : value ∈ {Off, Overload Protection Only, On} → want Off
      - Export mode pop-up  : default "One File per Track" (= per-track stems)
      - Bit depth pop-up    : default "24-bit" (leave; native SR not in this dialog)
      - Save button         : AXButton "Export"
      The config pop-ups have NO AXTitle — we identify each by its value being a
      member of that control's known option set (robust to index shifts), and
      pop-up menus are lazy (empty until clicked open).
═══════════════════════════════════════════════════════════════════════════════
"""
import os
import subprocess
import time


LOGIC_APP_CANDIDATES = [
    '/Applications/Logic Pro X.app',
    '/Applications/Logic Pro.app',
]

# Logic's process name as seen by System Events / `pgrep -x`. On this machine it
# is "Logic Pro X"; a Logic Pro 11 install would be "Logic Pro". detect_logic_
# process_name() confirms the live value at launch; this is only the fallback.
LOGIC_PROCESS_NAME = 'Logic Pro X'

# Verbatim export menu item (confirmed by dumping the submenu — note the ellipsis).
EXPORT_MENU_ITEM = 'All Tracks as Audio Files…'

# Known option sets for the unnamed config pop-ups — used to find each pop-up by
# its current value rather than a brittle positional index.
FORMAT_OPTIONS = {'AIFF', 'WAVE', 'CAF'}
NORMALIZE_OPTIONS = {'Off', 'Overload Protection Only', 'On'}

# The range/silence pop-up (export-dialog pop-up #2). Discovery 2026-06-10 proved
# the export range is governed ENTIRELY by this accessible pop-up — not the
# playhead, not the cycle state (see docs/2026-06-10/DISCOVERY_range.md). The
# driver historically never set it, so it inherited Logic's *sticky* last value
# (e.g. "Export Cycle Range Only") → "stems start from the middle". We now force
# it every export. Product-owner decision: always "Trim Silence at File End"
# (bar 1 → end of last clip, trailing tail trimmed = the full-song deliverable);
# no UI toggle.
RANGE_OPTIONS = {'Trim Silence at File End', 'Export Cycle Range Only',
                 'Extend File Length to Project End'}
DEFAULT_RANGE_MODE = 'Trim Silence at File End'


# ── discovery ──────────────────────────────────────────────────────────────────
def find_logic() -> str:
    for p in LOGIC_APP_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError('Logic Pro not found in /Applications.')


def detect_logic_process_name(timeout: float = 5.0) -> str:
    """Return the running Logic process name, confirmed against the live process
    list so menu-bar scripting targets the right process.

    IMPORTANT: match EXACTLY, most-specific first. The old substring check matched
    "Logic Pro" inside "Logic Pro X" and returned the wrong name, after which
    `pgrep -x "Logic Pro"` reported Logic as dead. We test exact `exists process`.
    """
    candidates = ['Logic Pro X', 'Logic Pro']  # most specific first
    end = time.time() + timeout
    while time.time() < end:
        for c in candidates:
            try:
                r = subprocess.run(
                    ['osascript', '-e',
                     f'tell application "System Events" to return (exists process "{c}")'],
                    capture_output=True, text=True, timeout=5)
                if r.stdout.strip() == 'true':
                    return c
            except Exception:
                pass
        time.sleep(0.3)
    return LOGIC_PROCESS_NAME


# ── project-path resolver (Handoff §11) ─────────────────────────────────────────
def resolve_project_path(path: str) -> str:
    """Given a dropped/selected path, return the inner `.logicx` to open.

    Handles BOTH Logic save styles:
      • Package: `name.logicx` is itself a bundle (a directory on disk whose name
        ends in .logicx). Opened directly.
      • Folder : a regular folder containing a hidden `.musicapps-project-folder`
        marker, an external `Audio Files/` folder, and the real `name.logicx`
        inside it. We resolve to that inner `.logicx`.

    Raises ValueError if the path is neither.
    """
    if not path:
        raise ValueError('No project path given.')
    p = path.rstrip('/') or path
    if not os.path.exists(p):
        raise ValueError(f'Path does not exist: {p}')

    # Package (or an already-resolved inner .logicx) — use as-is.
    if p.lower().endswith('.logicx'):
        return p

    # Folder-style project: look for the inner .logicx at the top level.
    if os.path.isdir(p):
        marker = os.path.join(p, '.musicapps-project-folder')
        inner = [f for f in os.listdir(p) if f.lower().endswith('.logicx')]
        if os.path.exists(marker) and inner:
            return os.path.join(p, inner[0])
        if len(inner) == 1:
            return os.path.join(p, inner[0])
        if len(inner) > 1:
            raise ValueError(
                f'Folder contains multiple .logicx projects ({inner}); '
                f'open the specific one.')

    raise ValueError(f'Not a Logic project (.logicx package or project folder): {p}')


# ── crash-reporter dismissal (reused concept from fl_render) ───────────────────
def dismiss_macos_crash_reporter():
    """Click the safe button on macOS's 'Logic Pro quit unexpectedly' dialog so it
    can't steal focus mid-export. Never clicks 'Reopen'. Idempotent, non-fatal."""
    script = r'''
    tell application "System Events"
        if exists (process "Problem Reporter") then
            tell process "Problem Reporter"
                repeat with b in buttons of front window
                    if name of b is in {"OK", "Ignore"} then
                        click b
                        exit repeat
                    end if
                end repeat
            end tell
        end if
    end tell
    '''
    try:
        subprocess.run(['osascript', '-e', script], timeout=10,
                       capture_output=True)
    except Exception:
        pass  # best-effort


class LogicCrashedError(RuntimeError):
    """Raised when Logic's process dies mid-export — signals the orchestrator to
    relaunch and retry."""


# ── helpers ────────────────────────────────────────────────────────────────────
def _osascript(script: str, timeout: float = 60.0) -> str:
    r = subprocess.run(['osascript', '-e', script], capture_output=True,
                       text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f'osascript failed: {r.stderr.strip()}')
    return r.stdout.strip()


def _as_str(s: str) -> str:
    """Escape a Python string for embedding inside an AppleScript double-quoted
    string literal."""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def _process_alive(name: str) -> bool:
    try:
        out = subprocess.check_output(['pgrep', '-x', name], text=True)
        return bool(out.strip())
    except subprocess.CalledProcessError:
        return False


# ── the bridge ──────────────────────────────────────────────────────────────────
class LogicRenderBridge:
    """launch → wait_for_logic_ready → export_stems(bypass_fx) → quit_logic.
    Mirrors FLRenderBridge so the orchestrator reads the same. Context-manager
    capable."""

    def __init__(self):
        self.app_path = find_logic()
        self.process_name = LOGIC_PROCESS_NAME
        self._proc = None

    # — lifecycle —
    def launch(self, project_path: str):
        """Open the .logicx project. Resolves package/folder styles first. `open -a`
        lets Logic own its own process; we track liveness via pgrep, not a child
        handle. Idempotent if Logic already has the project open (open just focuses)."""
        resolved = resolve_project_path(project_path)
        subprocess.run(['open', '-a', self.app_path, resolved], check=True)
        self.process_name = detect_logic_process_name()

    def relaunch(self, project_path: str):
        try:
            self.quit_logic(force=True)
        except Exception:
            pass
        time.sleep(1.0)
        self.launch(project_path)

    def is_alive(self) -> bool:
        return _process_alive(self.process_name)

    def wait_for_logic_ready(self, timeout: float = 180.0,
                             settle: float = 3.0) -> bool:
        """Wait until Logic's project window is up, then a short settle.

        Adaptive: returns as soon as a STANDARD window with a real title and no
        blocking sheet exists (the project finished opening) plus `settle` seconds
        for plugin load to taper — proven floor = `settle`, hard ceiling = `timeout`.
        Logic can be running with zero/untitled windows while a project loads, so
        we poll for a *named* AXStandardWindow.
        """
        end = time.time() + timeout
        while time.time() < end and not self.is_alive():
            time.sleep(0.5)
        if not self.is_alive():
            return False

        proc = self.process_name
        script = f'''tell application "System Events" to tell process "{_as_str(proc)}"
            set wins to (every window whose subrole is "AXStandardWindow")
            if (count of wins) is 0 then return "no"
            repeat with w in wins
                set nm to name of w
                if nm is not missing value and nm is not "" then
                    if (count of sheets of w) is 0 then return "ready"
                end if
            end repeat
            return "no"
        end tell'''
        while time.time() < end:
            try:
                if _osascript(script, timeout=10) == 'ready':
                    time.sleep(settle)
                    return self.is_alive()
            except Exception:
                pass
            time.sleep(0.7)
        return False

    # — the export —
    def export_stems(self, output_folder: str, file_stem: str = 'stem',
                     bypass_fx: bool = False):
        """Drive ONE 'All Tracks as Audio Files' export into `output_folder`.
        WAVs land loose in output_folder; the orchestrator sorts them afterwards.

        Element-level only (no screenshots / coordinate clicks):
          1. Bring Logic frontmost, open File ▸ Export ▸ All Tracks as Audio Files…
          2. ⌘⇧G → type output_folder → Return  (off-Finder path entry).
          3. File Format → WAVE; Bypass Effect Plug-ins → bypass_fx (read AXValue,
             click only if it differs); Normalize → Off. Bit depth + One-File-per-
             Track left at defaults.
          4. Click "Export".
          5. Wait for completion (wait_for_export_complete).
        Raises LogicCrashedError if Logic dies at any point.
        """
        if not self.is_alive():
            raise LogicCrashedError('Logic not running at export start.')

        os.makedirs(output_folder, exist_ok=True)
        proc = self.process_name

        # Defensive: clear a modal "Key Command Assignment Conflicts" sheet that can
        # block the main window before we try to open the Export menu.
        self._dismiss_conflict_sheet()

        # 1. Open the export dialog.
        _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
            set frontmost to true
            delay 0.4
            click menu item "{_as_str(EXPORT_MENU_ITEM)}" of menu "Export" of menu item "Export" of menu "File" of menu bar 1
        end tell''', timeout=20)

        # Poll for the dialog window to appear.
        if not self._wait_for_open_dialog(timeout=30):
            if not self.is_alive():
                raise LogicCrashedError('Logic died while opening the export dialog.')
            raise RuntimeError('Export dialog did not open.')

        # Defensive again: the conflict sheet can also surface as the dialog opens.
        self._dismiss_conflict_sheet()

        # 2 + 3 + 4. Set destination, controls, and export — one scripted block.
        desired_bypass = 1 if bypass_fx else 0
        script = f'''tell application "System Events" to tell process "{_as_str(proc)}"
            set w to window "Open"

            -- Make sure the accessory options (the pop-ups/checkboxes) are visible.
            if exists button "Show Options" of w then
                click button "Show Options" of w
                delay 0.3
            end if

            -- Destination via ⌘⇧G "Go to Folder" (keeps us off Finder automation).
            keystroke "g" using {{command down, shift down}}
            delay 0.5
            keystroke "a" using {{command down}}
            delay 0.1
            keystroke "{_as_str(output_folder)}"
            delay 0.3
            keystroke return
            delay 0.8

            -- File Format → WAVE (find the pop-up whose value is a format option).
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

            -- Bypass Effect Plug-ins → desired (read value, click only if differs).
            set cb to checkbox "Bypass Effect Plug-ins" of w
            if (value of cb as integer) is not {desired_bypass} then
                click cb
                delay 0.2
            end if

            -- Normalize → Off (find the pop-up whose value is a normalize option).
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

            -- Range/silence pop-up (#2) → "Trim Silence at File End" (full song,
            -- bar 1 → last clip). ROOT-CAUSE FIX: set it explicitly every export so
            -- we never inherit Logic's sticky last value (which caused mid-project
            -- starts). Found by value-membership in the range option set (the three
            -- option sets — format/normalize/range — are disjoint, so no cross-match).
            -- Fallback if value-membership ever proves ambiguous: it is positionally
            -- "pop up button 2 of w" (as used by tools/range_discovery.py →
            -- export_with_range_mode).
            repeat with p in (every pop up button of w)
                set v to ""
                try
                    set v to (value of p) as text
                end try
                if v is in {{"Trim Silence at File End", "Export Cycle Range Only", "Extend File Length to Project End"}} then
                    if v is not "{_as_str(DEFAULT_RANGE_MODE)}" then
                        click p
                        delay 0.3
                        click menu item "{_as_str(DEFAULT_RANGE_MODE)}" of menu 1 of p
                        delay 0.2
                    end if
                    exit repeat
                end if
            end repeat

            -- Go.
            click button "Export" of w
        end tell'''
        _osascript(script, timeout=60)

        # 4b. Defensive: a stray "Replace existing files?" sheet (shouldn't occur —
        # we sort between passes so the root is empty — but handle it).
        self._dismiss_replace_sheet()

        # 5. Wait for the bounce to finish.
        self.wait_for_export_complete(output_folder)

    def _wait_for_open_dialog(self, timeout: float = 30.0) -> bool:
        end = time.time() + timeout
        proc = self.process_name
        while time.time() < end:
            if not self.is_alive():
                return False
            try:
                if _osascript(
                    f'tell application "System Events" to tell process '
                    f'"{_as_str(proc)}" to return (exists window "Open")',
                    timeout=10) == 'true':
                    return True
            except Exception:
                pass
            time.sleep(0.4)
        return False

    def _dismiss_conflict_sheet(self):
        """If Logic shows the modal "Key Command Assignment Conflicts" sheet
        (buttons `Show Conflicts` / `Ignore`), click `Ignore` so it can't block the
        main window or hang the export flow. Clicks any `Ignore` across both windows
        and their sheets. Best-effort, non-fatal (mirrors `_dismiss_replace_sheet`;
        same logic as `dismiss_conflicts()` in tools/range_discovery.py)."""
        try:
            _osascript(f'''tell application "System Events" to tell process "{_as_str(self.process_name)}"
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
            end tell''', timeout=10)
        except Exception:
            pass

    def _dismiss_replace_sheet(self):
        """If Logic asks to replace existing files, click Replace (we intend to
        overwrite the loose root WAVs). Best-effort, non-fatal."""
        try:
            _osascript(f'''tell application "System Events" to tell process "{_as_str(self.process_name)}"
                if exists window "Open" then
                    repeat with s in sheets of window "Open"
                        repeat with b in buttons of s
                            if name of b is in {{"Replace", "Replace All", "OK"}} then
                                click b
                                exit repeat
                            end if
                        end repeat
                    end repeat
                end if
            end tell''', timeout=10)
        except Exception:
            pass

    def wait_for_export_complete(self, output_folder: str,
                                 timeout: float = 1800.0,
                                 required_stable: int = 4,
                                 poll: float = 1.0) -> None:
        """Block until the bounce is finished.

        Primary done-signal here is WAV file-size STABILITY: once ≥1 .wav exists in
        `output_folder` and the {name→size} snapshot is byte-for-byte unchanged for
        `required_stable` consecutive polls (and every size > 0), the bounce is
        complete. A growing/just-appeared file resets the counter, so we never
        return mid-write. (Logic's bounce-progress window closing is the documented
        secondary signal; file-size stability is the robust primary and also covers
        instant offline bounces where the progress window barely flashes.)

        Raises LogicCrashedError if Logic exits mid-wait.
        """
        end = time.time() + timeout
        last = None
        stable = 0
        saw_files = False
        while time.time() < end:
            if not self.is_alive():
                raise LogicCrashedError('Logic exited during export.')
            snap = {}
            try:
                for name in os.listdir(output_folder):
                    if name.lower().endswith('.wav'):
                        fp = os.path.join(output_folder, name)
                        try:
                            snap[name] = os.path.getsize(fp)
                        except OSError:
                            pass
            except OSError:
                pass
            if snap:
                saw_files = True
            if saw_files and snap == last and snap and all(v > 0 for v in snap.values()):
                stable += 1
                if stable >= required_stable:
                    return
            else:
                stable = 0
            last = snap
            time.sleep(poll)
        raise RuntimeError(
            f'Export did not complete within {timeout:.0f}s (no stable WAV set).')

    def quit_logic(self, save: bool = False, force: bool = False):
        """Quit Logic WITHOUT saving (the export must never write the project).
        ⌘Q → handle a 'Don't Save' sheet → poll for exit → escalate to terminate /
        kill. `save` is accepted for signature parity but we never save."""
        if not self.is_alive():
            return
        proc = self.process_name

        # Polite ⌘Q.
        try:
            _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
                set frontmost to true
                delay 0.2
                keystroke "q" using command down
            end tell''', timeout=10)
        except Exception:
            pass

        # Poll for exit, clearing any 'Don't Save' sheet each tick.
        end = time.time() + 20
        while time.time() < end and self.is_alive():
            self._click_dont_save()
            time.sleep(0.5)

        # Escalate: ask the app to quit, then SIGTERM, then SIGKILL.
        if self.is_alive():
            try:
                _osascript(f'tell application "{_as_str(proc)}" to quit', timeout=10)
            except Exception:
                pass
            end = time.time() + 8
            while time.time() < end and self.is_alive():
                self._click_dont_save()
                time.sleep(0.5)
        if self.is_alive():
            subprocess.run(['pkill', '-x', proc], capture_output=True)
            time.sleep(1.5)
        if self.is_alive():
            subprocess.run(['pkill', '-9', '-x', proc], capture_output=True)

    def _click_dont_save(self):
        """Click 'Don't Save' on any save-prompt sheet/dialog so a ⌘Q can finish
        without writing the project. Handles straight + curly apostrophe and the
        'Delete' wording some Logic prompts use."""
        try:
            _osascript(f'''tell application "System Events" to tell process "{_as_str(self.process_name)}"
                set targets to {{"Don't Save", "Don’t Save", "Delete"}}
                repeat with w in windows
                    repeat with s in sheets of w
                        repeat with b in buttons of s
                            if name of b is in targets then
                                click b
                                return
                            end if
                        end repeat
                    end repeat
                    repeat with b in buttons of w
                        if name of b is in targets then
                            click b
                            return
                        end if
                    end repeat
                end repeat
            end tell''', timeout=10)
        except Exception:
            pass

    # — context manager —
    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.quit_logic(force=True)
        except Exception:
            pass
