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


# ── focus masking (P3) ───────────────────────────────────────────────────────────
# Almost everything on the export path is element-driven and works against a
# BACKGROUNDED Logic (verified P3: menu-item click, Show Options, pop-up
# open+select, checkbox click, Export button — see docs/2026-06-28/
# P3_DISCOVERY_background.md). The ONLY actions that require Logic to be frontmost
# are the two fixed keystroke chords ⌘⇧G (summon the Go-to-Folder field) and Return
# (confirm it) — macOS keystrokes always go to the frontmost app. We mask those:
# wait for an input-idle gap, snapshot the user's frontmost app, flick Logic
# frontmost for that instant, send the keys, then restore the prior app. The cursor
# is never moved (no coordinate/cliclick anywhere — keystrokes & app activation
# don't move it).
def _input_idle_seconds() -> float:
    """Seconds since the last HID (keyboard/mouse) event, system-wide. Reads
    IOHIDSystem's HIDIdleTime (nanoseconds). Returns 0.0 if it can't be read (so we
    fail SAFE toward 'user is active' → caller waits)."""
    try:
        out = subprocess.check_output(['ioreg', '-c', 'IOHIDSystem'], text=True,
                                      timeout=5)
    except Exception:
        return 0.0
    for line in out.splitlines():
        if 'HIDIdleTime' in line:
            try:
                return int(line.rsplit('=', 1)[1].strip()) / 1_000_000_000.0
            except (ValueError, IndexError):
                return 0.0
    return 0.0


def _frontmost_app_name() -> str:
    try:
        return _osascript('tell application "System Events" to get name of first '
                          'process whose frontmost is true', timeout=8)
    except Exception:
        return ''


def _set_app_frontmost(name: str):
    if not name:
        return
    try:
        _osascript(f'tell application "System Events" to set frontmost of process '
                   f'"{_as_str(name)}" to true', timeout=8)
    except Exception:
        pass


# ── the bridge ──────────────────────────────────────────────────────────────────
class LogicRenderBridge:
    """launch → wait_for_logic_ready → export_stems(bypass_fx) → quit_logic.
    Mirrors FLRenderBridge so the orchestrator reads the same. Context-manager
    capable."""

    def __init__(self, headless: bool = True):
        self.app_path = find_logic()
        self.process_name = LOGIC_PROCESS_NAME
        self._proc = None
        # headless (default on): drive the export by AX element VALUE + backgrounded
        # element clicks (no `set frontmost`, cursor never moves). The destination's
        # two irreducible keystroke chords (⌘⇧G / Return) are focus-MASKED: fired
        # during an input-idle gap with the user's frontmost app restored after. The
        # legacy keystroke+frontmost path is kept behind `if not self.headless:` as a
        # fallback. Invisible-render phase, Tier 0 (docs/2026-06-28/
        # Invisible_Render_Handoff_v1.md, P2/P3).
        self.headless = headless
        # Idle-mask tunables (P3): require this many seconds since the last HID event
        # before stealing focus for the masked chords, waiting up to _idle_timeout
        # for such a gap (then proceed best-effort so a render never hangs forever).
        self._idle_min = 0.7
        self._idle_timeout = 60.0
        # Measurement-only flick instrumentation (inert by default — changes NO
        # delays or behavior). When _instrument_flick is True, _run_masked_keys
        # prints its activation/body/restore deltas; _last_flick_timings always
        # holds the most recent masked-step timing dict (cheap time.time() stamps).
        self._instrument_flick = False
        self._last_flick_timings = None
        # Measurement-only: per-phase wall-clock durations for a whole headless
        # export (inert unless _instrument_flick). list of (label, seconds).
        self._phases = []
        self._bounce_start = None   # set just after the Export click, for bounce timing
        self._quit_focus_pulled = None   # measurement-only: did quit pull Logic frontmost?

    # — lifecycle —
    def launch(self, project_path: str):
        """Open the .logicx project. Resolves package/folder styles first. `open`
        lets Logic own its own process; we track liveness via pgrep, not a child
        handle. Idempotent if Logic already has the project open.

        Headless: `open -g` opens Logic in the BACKGROUND so the launch never steals
        focus — essential, otherwise Logic is frontmost from the start and the
        focus-masking would only ever restore focus to Logic. Legacy: plain `open -a`
        (activates Logic), kept behind `if not self.headless:`."""
        resolved = resolve_project_path(project_path)
        cmd = ['open', '-g', '-a', self.app_path, resolved] if self.headless \
            else ['open', '-a', self.app_path, resolved]
        subprocess.run(cmd, check=True)
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
        # Headless: a blocking free-floating AXDialog (e.g. the audio-interface
        # alert) must NOT count as "ready" (catalog requirement #2). We refuse ready
        # while one is present and clear it via _auto_dismiss_dialogs() each tick.
        dialog_guard = ('if (count of (windows whose subrole is "AXDialog")) > 0 '
                        'then return "no"\n            ' if self.headless else '')
        script = f'''tell application "System Events" to tell process "{_as_str(proc)}"
            {dialog_guard}set wins to (every window whose subrole is "AXStandardWindow")
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
                if self.headless:
                    self._auto_dismiss_dialogs()   # clear blockers before judging ready
                if _osascript(script, timeout=10) == 'ready':
                    time.sleep(settle)
                    return self.is_alive()
            except Exception:
                pass
            time.sleep(0.7)
        return False

    # — focus-masked keystrokes (P3) —
    def _wait_input_idle(self) -> bool:
        """Block until the user has been idle for >= self._idle_min seconds, up to
        self._idle_timeout. Returns True if an idle gap was found, False if we timed
        out (caller proceeds best-effort either way so a render can't hang)."""
        end = time.time() + self._idle_timeout
        while time.time() < end:
            if _input_idle_seconds() >= self._idle_min:
                return True
            time.sleep(0.15)
        return False

    def _run_masked_keys(self, body_script: str):
        """Run an AppleScript `body_script` (the keystroke chords) with Logic
        frontmost ONLY for that instant, restoring the user's prior frontmost app
        afterwards. Gated on an input-idle gap. The cursor is never moved.

        body_script is the inside of a `tell process "<proc>"` block (it may use
        `w` = window "Open" — we bind it). Used only on the headless path."""
        proc = self.process_name
        self._wait_input_idle()                 # best-effort idle gap
        prior = _frontmost_app_name()
        # Cheap wall-clock stamps for measurement only (no behavior change). All
        # initialised to t0 so the finally block is safe even if the body raises.
        t0 = time.time()
        t1 = t2 = t3 = t0
        try:
            _set_app_frontmost(proc)
            t1 = time.time()                    # after activation
            time.sleep(0.15)
            t2 = time.time()                    # after the fixed post-activation sleep
            flick_msg = _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
                set w to window "Open"
{body_script}
            end tell''', timeout=30)
            t3 = time.time()                    # after the chord body
            # A poll fallback fired (sheet didn't appear/vanish in ~3s) — always
            # log it so we can see if polls ever time out in practice.
            if flick_msg:
                print(f'[masked-keys] {flick_msg}')
        finally:
            # Always hand focus back to the user's app, even if the body errored.
            t4 = time.time()                    # before restore
            if prior and prior != proc:
                _set_app_frontmost(prior)
            t5 = time.time()                    # after restore
            self._last_flick_timings = {
                'activation': t1 - t0,
                'post_activation_sleep': t2 - t1,
                'body': t3 - t2,
                'pre_restore_gap': t4 - t3,
                'restore': t5 - t4,
                'total_t0_t5': t5 - t0,
                'abs': {'t0': t0, 't1': t1, 't2': t2,
                        't3': t3, 't4': t4, 't5': t5},
            }
            if self._instrument_flick:
                print(f'[flick] activation={t1 - t0:.3f}s '
                      f'sleep={t2 - t1:.3f}s body={t3 - t2:.3f}s '
                      f'pre_restore={t4 - t3:.3f}s restore={t5 - t4:.3f}s '
                      f'total={t5 - t0:.3f}s')

    # — measurement-only phase recorder (inert unless _instrument_flick) —
    def _rec_phase(self, label: str, dt: float):
        """Record a phase duration. Cheap; only stores/prints when instrumenting,
        so production behavior and output are unchanged."""
        if self._instrument_flick:
            self._phases.append((label, dt))
            print(f'[phase] {label}: {dt * 1000:.0f} ms')

    def _control_segments_for(self, desired_bypass: int):
        """MEASUREMENT-ONLY decomposition of `controls_body` into individually
        timeable AppleScript segments (Format / Bypass / Normalize / Range / Export
        click). Each segment is self-contained (no cross-segment variables), so
        running them as separate osascripts is functionally identical to the single
        production block — the ONLY difference is one extra osascript spawn per
        segment (~30-40 ms), which is why these per-pop-up numbers are upper bounds
        vs the single-block production path. Used solely when _instrument_flick is
        set; the production path still runs the original single `controls_body`."""
        fmt = '''
            repeat with p in (every pop up button of w)
                set v to ""
                try
                    set v to (value of p) as text
                end try
                if v is in {"AIFF", "WAVE", "CAF"} then
                    if v is not "WAVE" then
                        click p
                        delay 0.3
                        click menu item "WAVE" of menu 1 of p
                        delay 0.2
                    end if
                    exit repeat
                end if
            end repeat'''
        byp = f'''
            set cb to checkbox "Bypass Effect Plug-ins" of w
            if (value of cb as integer) is not {desired_bypass} then
                click cb
                delay 0.2
            end if'''
        nrm = '''
            repeat with p in (every pop up button of w)
                set v to ""
                try
                    set v to (value of p) as text
                end try
                if v is in {"Off", "Overload Protection Only", "On"} then
                    if v is not "Off" then
                        click p
                        delay 0.3
                        click menu item "Off" of menu 1 of p
                        delay 0.2
                    end if
                    exit repeat
                end if
            end repeat'''
        rng = f'''
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
            end repeat'''
        return [('format', fmt), ('bypass', byp), ('normalize', nrm),
                ('range', rng), ('export_click', 'click button "Export" of w')]

    # — the export —
    def export_stems(self, output_folder: str, file_stem: str = 'stem',
                     bypass_fx: bool = False):
        """Drive ONE 'All Tracks as Audio Files' export into `output_folder`.
        WAVs land loose in output_folder; the orchestrator sorts them afterwards.

        Element-level only (no screenshots / coordinate clicks; cursor never moves):
          1. Open File ▸ Export ▸ All Tracks as Audio Files… — headless: menu-bar
             element click against a BACKGROUNDED Logic (no frontmost); legacy:
             frontmost flick first.
          2. Destination: headless → focus-MASKED ⌘⇧G + AX set-value + Return (the
             only frontmost moment, idle-gated, prior app restored); legacy →
             frontmost ⌘⇧G + ⌘A + keystroke output_folder + Return.
          3. File Format → WAVE; Bypass Effect Plug-ins → bypass_fx (read AXValue,
             click only if it differs); Normalize → Off; Range → Trim Silence. All
             backgrounded element clicks on the headless path. Bit depth + One-File-
             per-Track left at defaults.
          4. Click "Export" (backgrounded element click on the headless path).
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
        # Headless: also clear any blocking free-floating AXDialog / sheet (e.g. the
        # audio-interface alert) right before opening the Export menu (catalog
        # requirement #1) — safe whitelisted buttons only, cursor never moves.
        if self.headless:
            self._auto_dismiss_dialogs()

        # 1. Open the export dialog. Headless: the menu-bar element click works
        # against a BACKGROUNDED Logic (P3 probe TEST A) — no `set frontmost`, no
        # focus steal. Legacy: keep the frontmost flick.
        _t_menu = time.time()
        if self.headless:
            _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
                click menu item "{_as_str(EXPORT_MENU_ITEM)}" of menu "Export" of menu item "Export" of menu "File" of menu bar 1
            end tell''', timeout=20)
        else:
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
        self._rec_phase('menu_click_to_dialog', time.time() - _t_menu)

        # Defensive again: the conflict sheet can also surface as the dialog opens.
        self._dismiss_conflict_sheet()

        # 2 + 3 + 4. Set destination, controls, and export.
        desired_bypass = 1 if bypass_fx else 0

        # The accessory controls (Format/Bypass/Normalize/Range) and the Export
        # button are ELEMENT actions that all work against a BACKGROUNDED Logic
        # (P3). Pop-ups can NOT be set by AXValue (verified P3) — we click them open
        # and select the menu item, which also works backgrounded. This control
        # logic is identical for both modes, so it's built once and reused. The
        # range root-cause note is preserved from Phase 1.
        controls_body = f'''
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
            click button "Export" of w'''

        # The destination path field lives ONLY inside the ⌘⇧G "Go to Folder" sheet
        # (window "Open" has no path field — just a search field + the "Where:"
        # pop-up; P1/P2 probes, docs/2026-06-28/probe_save_panel.txt). The sheet has
        # no accessible "Go" button (only Close), so Return is required to confirm.
        if self.headless:
            # HEADLESS: backgrounded element actions + a single focus-MASKED moment
            # for the two irreducible chords (⌘⇧G, Return). No path typing; the
            # destination is set by AX value. Cursor never moves.
            _t_so = time.time()
            _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
                set w to window "Open"
                if exists button "Show Options" of w then
                    click button "Show Options" of w
                    delay 0.3
                end if
            end tell''', timeout=20)
            self._rec_phase('show_options', time.time() - _t_so)
            # Two sheet-waits are POLLED (proceed the instant the sheet
            # appears/vanishes) instead of fixed sleeps — this shrinks the masked
            # flick and returns focus to the user as soon as the Go-to sheet is
            # actually gone. Each poll caps at ~3s (60 × 50ms) and, on timeout,
            # falls back to the ORIGINAL fixed delay so it is never worse than
            # before. The other delays (the 0.15 post-activation sleep in
            # _run_masked_keys and the 0.3 after set-value) are unchanged. The body
            # returns a marker string when a fallback fires so _run_masked_keys can
            # log it.
            self._run_masked_keys(f'''
                keystroke "g" using {{command down, shift down}}
                -- Poll for the Go-to-Folder sheet to APPEAR (was: delay 0.5).
                set fb1 to true
                repeat 60 times
                    try
                        if (exists text field 1 of sheet 1 of w) then
                            set fb1 to false
                            exit repeat
                        end if
                    end try
                    delay 0.05
                end repeat
                if fb1 then delay 0.5
                set value of text field 1 of sheet 1 of w to "{_as_str(output_folder)}"
                delay 0.3
                keystroke return
                -- Poll for the Go-to-Folder sheet to DISMISS (was: delay 0.8).
                set fb2 to true
                repeat 60 times
                    try
                        if not (exists sheet 1 of w) then
                            set fb2 to false
                            exit repeat
                        end if
                    end try
                    delay 0.05
                end repeat
                if fb2 then delay 0.8
                set flickMsg to ""
                if fb1 then set flickMsg to flickMsg & "FALLBACK sheet-appear poll timed out (~3s) -> used delay 0.5; "
                if fb2 then set flickMsg to flickMsg & "FALLBACK sheet-gone poll timed out (~3s) -> used delay 0.8; "
                return flickMsg''')
            if self._last_flick_timings:
                self._rec_phase('masked_flick_total',
                                self._last_flick_timings['total_t0_t5'])
            # Controls + Export click. PRODUCTION runs the original single
            # `controls_body` osascript (unchanged). MEASUREMENT (_instrument_flick)
            # runs each control as its own timed osascript for per-pop-up numbers —
            # functionally identical, costs one extra osascript spawn per segment.
            if self._instrument_flick:
                for _label, _snip in self._control_segments_for(desired_bypass):
                    _t_c = time.time()
                    _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
                set w to window "Open"
{_snip}
            end tell''', timeout=60)
                    self._rec_phase(f'controls:{_label}', time.time() - _t_c)
            else:
                _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
                set w to window "Open"
{controls_body}
            end tell''', timeout=60)
        else:
            # LEGACY (not headless): one frontmost-held script that TYPES the
            # destination path char-by-char (⌘⇧G + ⌘A + keystroke "<path>"). Kept as
            # the pre-headless fallback.
            _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
                set w to window "Open"
                if exists button "Show Options" of w then
                    click button "Show Options" of w
                    delay 0.3
                end if

                -- Destination via ⌘⇧G "Go to Folder" + keystroke typing.
                keystroke "g" using {{command down, shift down}}
                delay 0.5
                keystroke "a" using {{command down}}
                delay 0.1
                keystroke "{_as_str(output_folder)}"
                delay 0.3
                keystroke return
                delay 0.8
{controls_body}
            end tell''', timeout=60)

        # Bounce starts the instant Export was clicked (last action above).
        self._bounce_start = time.time()

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

    # — minimal safe dialog auto-dismiss (headless DialogGuard seed, P6) —
    # Whitelist of SAFE dismiss buttons we may click. Anything else is left alone;
    # in particular we NEVER click a destructive verb or "Open Settings" (those are
    # never in this set, so they can't be clicked by construction). Buttons starting
    # with "Use " (e.g. "Use MacBook Pro Speakers") are also safe (accept default).
    _SAFE_DISMISS = ('OK', 'Continue', 'Close')
    _NEVER_CLICK = ('Delete', 'Discard', 'Overwrite', 'Replace', 'Move to Trash',
                    'Open Settings', 'Reopen', 'Save')  # documentation / guard

    def _auto_dismiss_dialogs(self):
        """Scan the Logic process for BLOCKING pop-ups — free-floating AXDialogs AND
        sheets — read each one's buttons, and click a SAFE whitelisted button only
        (`_SAFE_DISMISS` or a "Use …" button). NEVER clicks a destructive verb
        (Delete/Discard/Overwrite/Replace/Move to Trash) or "Open Settings"; if a
        dialog has no safe button it is left untouched (fail safe). Element clicks
        only → works against a BACKGROUNDED Logic, cursor never moves. Logs every
        dialog it clears. Best-effort, non-fatal. Headless only. Returns the list of
        cleared dialogs (dicts with title/body/clicked) — also used by the catalog
        learn-loop (docs/2026-06-28/logic_dialog_catalog.md)."""
        proc = self.process_name
        script = f'''tell application "System Events"
            if not (exists process "{_as_str(proc)}") then return ""
            tell process "{_as_str(proc)}"
                set containers to {{}}
                repeat with w in windows
                    try
                        if ((subrole of w) as text) is "AXDialog" then set end of containers to w
                    end try
                    try
                        repeat with s in sheets of w
                            set end of containers to s
                        end repeat
                    end try
                end repeat
                set report to ""
                repeat with c in containers
                    set theTitle to ""
                    try
                        set theTitle to (name of c) as text
                    end try
                    set oldD to AppleScript's text item delimiters
                    set AppleScript's text item delimiters to " / "
                    set theBody to ""
                    try
                        set theBody to (value of (every static text of c)) as text
                    end try
                    set AppleScript's text item delimiters to oldD
                    set clicked to ""
                    repeat with b in buttons of c
                        set bn to ""
                        try
                            set bn to (name of b) as text
                        end try
                        if (bn is "OK" or bn is "Continue" or bn is "Close" or bn starts with "Use ") then
                            click b
                            set clicked to bn
                            exit repeat
                        end if
                    end repeat
                    if clicked is not "" then
                        set report to report & "title=" & theTitle & "||body=" & theBody & "||clicked=" & clicked & linefeed
                    end if
                end repeat
                return report
            end tell
        end tell'''
        try:
            out = _osascript(script, timeout=15)
        except Exception:
            return []
        cleared = []
        for line in out.splitlines():
            if not line.strip():
                continue
            d = {}
            for part in line.split('||'):
                if '=' in part:
                    k, v = part.split('=', 1)
                    d[k] = v
            cleared.append(d)
            print(f'[DialogGuard] cleared: title={d.get("title", "")!r} '
                  f'button={d.get("clicked", "")!r} body={d.get("body", "")!r}')
        return cleared

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
        # Measurement-only (inert unless _instrument_flick): split Logic's real
        # render work from our stability-detection tail.
        _t_entry = time.time()
        _base = self._bounce_start or _t_entry
        _first_wav_at = None
        _last_change_at = None
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
                if _first_wav_at is None:
                    _first_wav_at = time.time()
                if snap != last:
                    _last_change_at = time.time()   # last time any WAV size changed
            if saw_files and snap == last and snap and all(v > 0 for v in snap.values()):
                stable += 1
                if stable >= required_stable:
                    if _first_wav_at:
                        self._rec_phase('bounce:export_to_first_wav',
                                        _first_wav_at - _base)
                    if _last_change_at:
                        self._rec_phase('bounce:export_to_last_write',
                                        _last_change_at - _base)
                    self._rec_phase('bounce:export_to_stable_return',
                                    time.time() - _base)
                    return
            else:
                stable = 0
            last = snap
            time.sleep(poll)
        raise RuntimeError(
            f'Export did not complete within {timeout:.0f}s (no stable WAV set).')

    def quit_logic(self, save: bool = False, force: bool = False):
        """Quit Logic WITHOUT saving (the export must never write the project).
        Trigger quit → handle a 'Don't Save' sheet by ELEMENT → poll for exit →
        escalate to terminate / kill. `save` is accepted for signature parity but we
        never save.

        Headless (P4): an Apple-event quit (`tell application … to quit`) lets Logic
        quit while it stays BACKGROUNDED — no focus flick — and the save prompt is
        cleared by `_click_dont_save()` (an element click, works backgrounded).
        Legacy: the old frontmost + ⌘Q, kept behind `if not self.headless:`."""
        if not self.is_alive():
            return
        proc = self.process_name
        _t_quit = time.time()   # measurement-only

        # Trigger the quit.
        if self.headless:
            # P4 quit fix: fire the Apple-event quit WITHOUT blocking, then dismiss
            # the "Don't Save" prompt the instant it appears and restore the user's
            # app. The old path blocked ~10s on the quit osascript because Logic
            # withholds the quit reply until the save prompt is answered — and we
            # only answered it AFTER that osascript timed out. ~10s pure waste/render.
            prior = _frontmost_app_name()
            # Fire-and-forget — must NOT wait on this (it blocks until the prompt is
            # answered); we answer it concurrently in the poll below.
            quitter = subprocess.Popen(
                ['osascript', '-e', f'tell application "{_as_str(proc)}" to quit'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            focus_pulled = False
            clicked_any = False
            end = time.time() + 10   # hard safety cap — never slower than before
            while time.time() < end and self.is_alive():
                # Click ONLY "Don't Save" (reuses _click_dont_save()'s whitelist —
                # element click, backgrounded, cursor never moves; never Save/Cancel).
                # An unknown/unexpected dialog matches nothing → left untouched.
                clicked = self._click_dont_save()
                if clicked:
                    # The click landed → Logic has released the modal and is now
                    # tearing down, so we no longer need it frontmost. Restore focus
                    # to the user's app IMMEDIATELY (not after process-gone) to shrink
                    # the ~2.5s frontmost-during-quit leak to near zero. Re-fires if a
                    # later teardown prompt pulls Logic forward again.
                    clicked_any = True
                    focus_pulled = True
                    if prior and prior != proc:
                        _set_app_frontmost(prior)
                elif not focus_pulled and _frontmost_app_name() == proc:
                    focus_pulled = True
                time.sleep(0.05)
            try:
                quitter.terminate()   # reap the fire-and-forget helper (Logic gone/capped)
            except Exception:
                pass
            if self.is_alive():
                # Don't Save not resolved within the cap (an unexpected/unknown
                # dialog or a hang) — do NOT guess: leave the dialog and let the
                # SIGTERM/SIGKILL fallback below guarantee no orphan (kill never saves).
                print('[quit] Logic still alive after 10s Don\'t-Save poll — leaving '
                      'any unexpected dialog untouched, escalating to terminate.')
            # Fallback restore: focus was pulled by a dialog-less frontmost flick
            # (no Don't-Save click ever landed to trigger the immediate restore above).
            if focus_pulled and not clicked_any and prior and prior != proc:
                _set_app_frontmost(prior)
            self._quit_focus_pulled = focus_pulled       # measurement-only
            self._rec_phase('quit:trigger_to_process_gone', time.time() - _t_quit)
        else:
            # LEGACY (not headless) — UNCHANGED: polite frontmost ⌘Q, then the
            # original 0.5s Don't-Save sweep (cap 20s).
            try:
                _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
                    set frontmost to true
                    delay 0.2
                    keystroke "q" using command down
                end tell''', timeout=10)
            except Exception:
                pass
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

    def _click_dont_save(self) -> bool:
        """Click 'Don't Save' on any save-prompt sheet/dialog so a ⌘Q can finish
        without writing the project. Handles straight + curly apostrophe and the
        'Delete' wording some Logic prompts use.

        Returns True if it actually clicked a whitelisted button this call, else
        False (no matching prompt present, or error). The clicking behavior is
        unchanged — only a signal is surfaced (callers that ignore it, e.g. the
        legacy quit sweep, are unaffected)."""
        try:
            out = _osascript(f'''tell application "System Events" to tell process "{_as_str(self.process_name)}"
                set targets to {{"Don't Save", "Don’t Save", "Delete"}}
                repeat with w in windows
                    repeat with s in sheets of w
                        repeat with b in buttons of s
                            if name of b is in targets then
                                click b
                                return "clicked"
                            end if
                        end repeat
                    end repeat
                    repeat with b in buttons of w
                        if name of b is in targets then
                            click b
                            return "clicked"
                        end if
                    end repeat
                end repeat
                return ""
            end tell''', timeout=10)
            return out == 'clicked'
        except Exception:
            return False

    # — context manager —
    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.quit_logic(force=True)
        except Exception:
            pass
