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
import re
import subprocess
import threading
import time

# DialogGuard decision engine (step 6a). Imported defensively so the driver still
# loads if the engine/PyYAML are ever absent — the headless path then logs and
# skips auto-handling (legacy path never touches it). See python/dialog_guard.py.
try:
    from dialog_guard import DialogGuard, Decision
except Exception:  # pragma: no cover - engine always present in this repo
    DialogGuard = None
    Decision = None


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


class DialogGuardPause(RuntimeError):
    """Raised (headless only) when the DialogGuard decides a live dialog must STOP
    the job:
      • PAUSE — an unknown/never-safe dialog → we never guess (no click); or
      • fail_job/terminal — a recognized terminal dialog (export failed, project
        created by a newer Logic) → we click its safe OK to clear the modal, THEN
        raise so the job stops.
    The orchestrator's try/finally quits Logic cleanly (never saving); the server's
    error handler surfaces this to the user. Carries the verbatim dialog so the
    notification layer can show {title, body, buttons} (learn-loop / inbox)."""

    def __init__(self, dialog, decision):
        self.dialog = dict(dialog or {})
        self.decision = decision
        self.rule_id = getattr(decision, 'rule_id', None)
        self.terminal = bool(getattr(decision, 'terminal', False))
        # Plain-language, actionable reason for the client (rule's user_message, or the
        # generic fallback). The server surfaces this as the notification reason.
        self.user_message = getattr(decision, 'user_message', '') or ''
        title = self.dialog.get('title') or ''
        body = self.dialog.get('body') or ''
        buttons = self.dialog.get('buttons') or []
        kind = 'job-failed' if self.terminal else 'paused'
        super().__init__(
            f'DialogGuard {kind} [rule={self.rule_id}]: '
            f'{(title or body)[:120]!r} buttons={buttons} — '
            f'{getattr(decision, "reason", "")}')


# ── helpers ────────────────────────────────────────────────────────────────────
def _osascript(script: str, timeout: float = 60.0, strip: bool = True) -> str:
    r = subprocess.run(['osascript', '-e', script], capture_output=True,
                       text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f'osascript failed: {r.stderr.strip()}')
    # strip=False preserves the raw stdout. Needed by the dialog scanner: its records
    # are delimited by RS(0x1e)/US(0x1f), and Python counts \x1c-\x1f as whitespace,
    # so .strip() would eat a LEADING separator (an empty title field begins with one)
    # and silently drop the record. Default True keeps every other caller unchanged.
    return r.stdout.strip() if strip else r.stdout


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
        # DialogGuard engine (lazy-loaded once on first use, headless only).
        self._guard = None
        self._guard_loaded = False
        # Focus tracking (headless only). The focus-restore target is the user's most
        # recent REAL working window — an app that is neither Logic nor our own
        # launcher (the send-stems Electron app is frontmost at trigger, so a single
        # capture at launch grabs 'Electron', which is wrong). We instead track the
        # latest real frontmost continuously via a lightweight background sampler, so
        # switching to Claude mid-render makes 'Claude' the target.
        #   _user_app          — latest REAL user app seen (None until one appears)
        #   _launcher_apps     — process names that are OUR launcher, to exclude
        #   _launcher_frontmost— exact launcher name seen frontmost at launch (the
        #                        only fallback, used if the user NEVER left the app)
        self._user_app = None
        self._launcher_apps = self._detect_launcher_apps()
        self._launcher_frontmost = None
        self._focus_sampler = None
        self._focus_sampler_stop = None
        # Scan-timing (headless only, inert): accumulates the wall-cost of the
        # per-tick DialogGuard scans in wait_for_logic_ready + wait_for_export_complete
        # so a run can report ms/scan + total overhead. Pure measurement — changes no
        # behaviour. See _timed_handle_dialogs / _scan_report.
        self._scan_count = 0
        self._scan_ms_total = 0.0

    # — focus tracking (headless only) —
    def _detect_launcher_apps(self) -> set:
        """Process names that are OUR launcher (the send-stems Electron app), to be
        excluded as a focus-restore target. main.js passes them via the env var
        STEMEXPORT_LAUNCHER_APPS on spawn (newline-separated: dev='Electron',
        production=the packaged app's name); we ALSO derive the parent process name
        as a fallback so exclusion works even if the env is missing. We never
        hardcode only 'Electron'."""
        names = set()
        for n in os.environ.get('STEMEXPORT_LAUNCHER_APPS', '').split('\n'):
            n = n.strip()
            if n:
                names.add(n)
        # Fallback/augment: our parent process (Electron main / packaged app binary).
        try:
            out = subprocess.check_output(
                ['ps', '-o', 'comm=', '-p', str(os.getppid())],
                text=True, timeout=5).strip()
            base = os.path.basename(out)
            if base.lower().endswith('.app'):
                base = base[:-4]
            if base:
                names.add(base)
        except Exception:
            pass
        return names

    def _is_launcher(self, name: str) -> bool:
        return bool(name) and name in self._launcher_apps

    def _is_real_user_app(self, name: str) -> bool:
        """A genuine user window: non-empty, not Logic, not our launcher."""
        return bool(name) and name != self.process_name and not self._is_launcher(name)

    def _restore_target(self) -> str:
        """Where a mid-render restore should send focus: the tracked real user app if
        we've ever seen one, else the launcher we started from (user never left the
        send-stems app). Never Logic."""
        return self._user_app or self._launcher_frontmost

    def _sample_user_app_once(self) -> str:
        """Read the current frontmost; if it's a REAL user app, adopt it as the
        restore target. Returns the raw frontmost read (for logging)."""
        cur = _frontmost_app_name()
        if self._is_real_user_app(cur) and cur != self._user_app:
            self._user_app = cur
            print(f'[FOCUS] sampler: tracked user app -> {cur!r}', flush=True)
        return cur

    def _start_focus_sampler(self):
        """Start a daemon thread that samples the frontmost app every ~0.5s and keeps
        _user_app pointed at the latest REAL user window. Read-only (never changes
        focus, never moves the cursor); harmless alongside the export osascripts."""
        if not self.headless or self._focus_sampler is not None:
            return
        self._focus_sampler_stop = threading.Event()

        def _loop():
            while not self._focus_sampler_stop.is_set():
                try:
                    self._sample_user_app_once()
                except Exception:
                    pass
                self._focus_sampler_stop.wait(0.5)

        self._focus_sampler = threading.Thread(target=_loop, daemon=True,
                                               name='focus-sampler')
        self._focus_sampler.start()

    def _stop_focus_sampler(self):
        if self._focus_sampler_stop is not None:
            self._focus_sampler_stop.set()
        self._focus_sampler = None

    # — scan-timing (headless only, inert) —
    def _timed_handle_dialogs(self, context=None):
        """Wrap one per-tick DialogGuard scan and accumulate its wall-cost. Behaves
        EXACTLY like _handle_dialogs (same return value; a DialogGuardPause still
        propagates) — the finally records timing on both the normal and raise paths."""
        t0 = time.time()
        try:
            return self._handle_dialogs(context)
        finally:
            self._scan_count += 1
            self._scan_ms_total += (time.time() - t0) * 1000.0

    def _scan_report(self, phase: str) -> dict:
        """Emit + return the cumulative dialog-scan overhead so the run can report
        ms/scan + total. Printed to stdout → visible in the `npm start` terminal."""
        n = self._scan_count
        total = self._scan_ms_total
        avg = (total / n) if n else 0.0
        print(f'[SCAN] {phase}: dialog-scan ticks={n} total={total:.0f}ms '
              f'avg={avg:.1f}ms/scan', flush=True)
        return {'ticks': n, 'total_ms': round(total, 1), 'avg_ms': round(avg, 2)}

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
        # Begin tracking the user's REAL working window BEFORE `open` starts Logic.
        # The frontmost at trigger is usually our own launcher (the send-stems app),
        # which must NOT become the restore target — so we only adopt a real user app
        # and let the background sampler keep it current as the user switches windows
        # during the render. Headless only; the legacy path leaves this untouched.
        if self.headless:
            self._start_focus_sampler()
            read = _frontmost_app_name()
            if self._is_real_user_app(read):
                self._user_app = read
            elif self._is_launcher(read) and self._launcher_frontmost is None:
                # Remember the exact launcher name so we can restore to it IF the user
                # never leaves the send-stems app (the only time the launcher is a
                # valid restore target).
                self._launcher_frontmost = read
            print(f'[FOCUS] launch(): frontmost={read!r} '
                  f'launcher_apps={sorted(self._launcher_apps)} '
                  f'-> _user_app={self._user_app!r} '
                  f'launcher_frontmost={self._launcher_frontmost!r}', flush=True)
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
        # while one is present and let the DialogGuard handle it each tick.
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
            # DialogGuard runs OUTSIDE the broad try below so a DialogGuardPause
            # (unknown/terminal dialog) propagates and aborts the wait instead of
            # being swallowed. Transient scan errors are handled inside _handle_dialogs.
            if self.headless:
                self._timed_handle_dialogs()
            try:
                if _osascript(script, timeout=10) == 'ready':
                    time.sleep(settle)
                    if self.headless:
                        self._scan_report('load')
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
        # Restore to the tracked REAL user app (or the launcher only if the user never
        # left it) — NOT a mid-flight snapshot, which reads Logic once it self-
        # activates and would no-op the restore, stranding focus on Logic.
        restore_to = self._restore_target()
        print(f'[FOCUS] masked-keys: prior(mid-flight)={prior!r} '
              f'_user_app={self._user_app!r} launcher_frontmost={self._launcher_frontmost!r} '
              f'-> restore_to={restore_to!r} (proc={proc!r})', flush=True)
        try:
            _set_app_frontmost(proc)
            time.sleep(0.15)
            flick_msg = _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
                set w to window "Open"
{body_script}
            end tell''', timeout=30)
            # A poll fallback fired (sheet didn't appear/vanish in ~3s) — always
            # log it so we can see if polls ever time out in practice.
            if flick_msg:
                print(f'[masked-keys] {flick_msg}')
        finally:
            # Always hand focus back to the user's app, even if the body errored.
            if restore_to and restore_to != proc:
                _set_app_frontmost(restore_to)
                print(f'[FOCUS] masked-keys: restored frontmost -> {restore_to!r}',
                      flush=True)
            else:
                print(f'[FOCUS] masked-keys: restore SKIPPED — restore_to={restore_to!r} '
                      f'is empty or == proc {proc!r}', flush=True)

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
        # Headless: run the DialogGuard right before opening the Export menu (catalog
        # requirement #1) — engine decides per dialog; element clicks only, cursor
        # never moves. Context carries the pass # + destination for the C2 gate. May
        # raise DialogGuardPause (propagates → orchestrator quits Logic cleanly).
        if self.headless:
            self._handle_dialogs(self._dialog_context(bypass_fx=bypass_fx,
                                                      dest=output_folder))

        # 1. Open the export dialog. Headless: the menu-bar element click works
        # against a BACKGROUNDED Logic (P3 probe TEST A) — no `set frontmost`, no
        # focus steal. Legacy: keep the frontmost flick.
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
            _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
                set w to window "Open"
                if exists button "Show Options" of w then
                    click button "Show Options" of w
                    delay 0.3
                end if
            end tell''', timeout=20)
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
            # Controls + Export click — the single `controls_body` osascript.
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

    # — DialogGuard: detector + decision + executor (headless only, step 6b) —
    # Replaces the old hardcoded safe-button whitelist with the catalog-driven
    # engine (python/dialog_guard.py + dialog_rules.yaml). The detector READS every
    # blocking dialog (free AXDialogs + sheets) → {title, body, buttons}; the engine
    # DECIDES (CLICK / PAUSE / IGNORE, fail-safe); the executor does ONLY that — it
    # never improvises a click. All element reads/clicks → backgrounded, cursor never
    # moves. Legacy (not headless) never calls any of this.
    _LOCALE_PREFIXES = (('de', 'de'), ('es', 'es'), ('fr', 'fr'), ('ja', 'ja'),
                        ('ko', 'ko'), ('zh', 'zh_CN'))

    def _dialog_guard(self):
        """Lazy-load the decision engine once. On failure (engine/YAML missing) log
        and return None → the headless path then skips auto-handling rather than
        crash; the readiness AXDialog gate still refuses to call a blocked Logic
        'ready'."""
        if not self._guard_loaded:
            self._guard_loaded = True
            if DialogGuard is None:
                print('[DialogGuard] WARNING: engine not importable; dialogs will '
                      'not be auto-handled this run.')
                self._guard = None
            else:
                try:
                    self._guard = DialogGuard()
                except Exception as e:
                    print(f'[DialogGuard] WARNING: rules failed to load ({e!r}); '
                          f'dialogs will not be auto-handled this run.')
                    self._guard = None
        return self._guard

    def _active_locale(self):
        """Logic renders in the system UI language (no per-app override). Map the
        first preferred language to one of the 7 shipped .lproj codes; default 'en'.
        The engine also falls back to English, so an imperfect guess is safe."""
        try:
            out = subprocess.check_output(['defaults', 'read', '-g', 'AppleLanguages'],
                                          text=True, timeout=5)
        except Exception:
            return 'en'
        m = re.search(r'"([A-Za-z\-]+)"', out)
        code = (m.group(1) if m else 'en').lower()
        for prefix, lproj in self._LOCALE_PREFIXES:
            if code.startswith(prefix):
                return lproj
        return 'en'

    def _dialog_context(self, bypass_fx=None, dest=None):
        """Context for the engine: pass # (wet=1 / raw=2) + destination root for the
        C2 (overwrite) gate. bypass_fx None → pass unknown (readiness tick)."""
        pass_number = None if bypass_fx is None else (2 if bypass_fx else 1)
        return {'pass_number': pass_number,
                'expected_dest_root': dest,
                'actual_dest_root': dest,
                'colliding_filename': None}

    def _scan_blocking_dialogs(self):
        """DETECTOR (read-only): every blocking pop-up on the Logic process — free
        AXDialog windows AND sheets — as a list of {title, body, buttons[]}. Element
        reads only; NO clicks here. Best-effort: transient AX errors → [].

        Only ACTIONABLE windows are returned: a candidate with no real (named)
        button is skipped, because that is a not-yet-initialized window (the splash /
        mid-load project window, whose AX names read `missing value`) rather than a
        clickable modal — emitting it made decide() fail-safe PAUSE and abort a
        healthy load. `missing value` is treated as absent for title and buttons.

        Wire format (one record per dialog, terminated by LINEFEED \\n):
            title <RS 0x1e> body <RS 0x1e> btn1 <US 0x1f> btn2 …
        Every field is first run through AppleScript `flat1`, which collapses any
        embedded CR/LF/RS/US to single spaces. That guarantees (a) no field can
        contain the record terminator or a separator, so records split cleanly, and
        (b) a multi-line body is flattened the SAME way the engine normalizes its
        anchors (all whitespace runs → one space) — so a body whose static texts are
        joined here is matched regardless of join style (the old " / " join broke
        the C9 match; the old \\x1e + str.splitlines() parse shattered every record,
        because splitlines() treats RS/GS/FS as line boundaries — we split on '\\n'
        EXPLICITLY for exactly that reason). Multiple static texts are joined with a
        space before flattening so adjacent sentences stay separated."""
        proc = self.process_name
        script = f'''on flat1(s)
            set d to AppleScript's text item delimiters
            set AppleScript's text item delimiters to {{return, linefeed, character id 30, character id 31}}
            set parts to text items of (s as text)
            set AppleScript's text item delimiters to " "
            set s to parts as text
            set AppleScript's text item delimiters to d
            return s
        end flat1
        tell application "System Events"
            if not (exists process "{_as_str(proc)}") then return ""
            set fieldSep to (character id 30)
            set btnSep to (character id 31)
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
                        if (name of c) is not missing value then set theTitle to (name of c) as text
                    end try
                    set oldD to AppleScript's text item delimiters
                    set AppleScript's text item delimiters to " "
                    set theBody to ""
                    try
                        set theBody to (value of (every static text of c)) as text
                    end try
                    set AppleScript's text item delimiters to oldD
                    set theTitle to my flat1(theTitle)
                    set theBody to my flat1(theBody)
                    set btns to ""
                    repeat with b in buttons of c
                        set bn to ""
                        try
                            if (name of b) is not missing value then set bn to my flat1((name of b) as text)
                        end try
                        if bn is not "" then
                            if btns is "" then
                                set btns to bn
                            else
                                set btns to btns & btnSep & bn
                            end if
                        end if
                    end repeat
                    -- Skip not-yet-initialized / non-actionable windows: a candidate
                    -- with NO real (named, non-`missing value`) button is the splash or
                    -- the mid-load project window whose AX element names haven't
                    -- populated yet (title "Logic Pro", every button/label reads
                    -- `missing value`) — NOT a clickable modal. Emitting it made
                    -- decide() fail-safe PAUSE and abort an otherwise-healthy load. A
                    -- real dialog always exposes ≥1 named button; meanwhile the
                    -- readiness AXDialog gate still refuses "ready" until the window
                    -- clears, so a genuine blocker is caught once its buttons appear.
                    if btns is not "" then
                        set report to report & theTitle & fieldSep & theBody & fieldSep & btns & linefeed
                    end if
                end repeat
                return report
            end tell
        end tell'''
        try:
            # strip=False: keep the RAW stdout. The record format starts with the
            # title field, which is EMPTY for a titleless alert (e.g. C9) — so the
            # output begins with the RS(0x1e) separator. .strip() counts \x1e as
            # whitespace and would eat that leading separator, collapsing the 3-field
            # record to 2 and dropping it. We split records on '\n' and skip blanks
            # below, so the trailing '\n\n' is harmless without any strip.
            out = _osascript(script, timeout=15, strip=False)
        except Exception:
            return []
        dialogs = []
        # Split on the LINEFEED record terminator ONLY — never str.splitlines(),
        # which would also break on the RS(0x1e) field separator and shatter every
        # record (the 6b C9 parse regression). flat1 above guarantees no field
        # carries a '\n', so one '\n'-line == one dialog record. Note: we split the
        # UNSTRIPPED `line` on '\x1e' (the `line.strip()` below is only a blank-line
        # test and does not mutate `line`), so an empty leading field survives as
        # parts[0]==''.
        for line in out.split('\n'):
            if not line.strip():
                continue
            parts = line.split('\x1e')
            if len(parts) < 3:
                continue
            title, body, btnblob = parts[0], parts[1], parts[2]
            buttons = [b for b in btnblob.split('\x1f') if b]
            dialogs.append({'title': title, 'body': body, 'buttons': buttons})
        return dialogs

    def _click_dialog_button(self, label):
        """Click the button with EXACTLY this (localized) name in any AXDialog window
        or sheet on the Logic process. Element click only → backgrounded, cursor
        never moves. Returns True if it clicked."""
        if not label:
            return False
        proc = self.process_name
        lbl = _as_str(label)
        try:
            out = _osascript(f'''tell application "System Events" to tell process "{_as_str(proc)}"
                repeat with w in windows
                    try
                        if ((subrole of w) as text) is "AXDialog" then
                            repeat with b in buttons of w
                                try
                                    if (name of b) is "{lbl}" then
                                        click b
                                        return "clicked"
                                    end if
                                end try
                            end repeat
                        end if
                    end try
                    repeat with s in sheets of w
                        repeat with b in buttons of s
                            try
                                if (name of b) is "{lbl}" then
                                    click b
                                    return "clicked"
                                end if
                            end try
                        end repeat
                    end repeat
                end repeat
                return ""
            end tell''', timeout=10)
            return out == 'clicked'
        except Exception:
            return False

    def _log_dialog(self, dlg, locale, decision):
        """Learn-loop: log every dialog the engine sees + its decision, so unknowns
        (→ PAUSE) can be added to the catalog (docs/2026-06-28/logic_dialog_catalog.md)."""
        btn = f' button={decision.button!r}' if decision.button else ''
        print(f'[DialogGuard] locale={locale} '
              f'title={dlg.get("title", "")!r} body={dlg.get("body", "")[:160]!r} '
              f'buttons={dlg.get("buttons", [])} -> {decision.action}{btn} '
              f'rule={decision.rule_id} reason={decision.reason!r}')

    def _handle_dialogs(self, context=None):
        """EXECUTOR (headless only). Detect → decide() → do ONLY what it returns:
          • IGNORE → leave it.
          • CLICK <button> → element-click that exact button (backgrounded). If the
            decision is fail_job/terminal, click its OK then raise DialogGuardPause.
          • PAUSE → raise DialogGuardPause WITHOUT clicking (safe abort).
        Returns the list of (dialog, decision) handled this call. Transient scan
        errors are swallowed (no dialogs); only DialogGuardPause is raised."""
        if not self.headless:
            return []
        guard = self._dialog_guard()
        if guard is None:
            return []
        locale = self._active_locale()
        handled = []
        for dlg in self._scan_blocking_dialogs():
            decision = guard.decide(dlg, locale=locale, context=context)
            self._log_dialog(dlg, locale, decision)
            handled.append((dlg, decision))
            if decision.action == Decision.IGNORE:
                continue
            if decision.action == Decision.PAUSE:
                raise DialogGuardPause(dlg, decision)
            if decision.action == Decision.CLICK:
                self._click_dialog_button(decision.button)
                if decision.terminal:
                    # fail_job: modal cleared, now stop the job.
                    raise DialogGuardPause(dlg, decision)
        return handled

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
            # Headless: also run the DialogGuard each tick so a blocking dialog that
            # appears AFTER the Export click — "The export operation failed.",
            # disk-full, etc. — is detected → decided → handled the instant it shows
            # (fail_job → click OK then raise DialogGuardPause(terminal); PAUSE /
            # unrecognized → raise DialogGuardPause) instead of letting the bounce
            # never arrive and the loop hang to its ~1800s timeout. Element reads/
            # clicks only (backgrounded, cursor never moves); _handle_dialogs swallows
            # transient scan errors and returns [] when nothing blocks, so a healthy
            # bounce (no AXDialog/sheet) is untouched. Legacy path never calls this.
            if self.headless:
                self._timed_handle_dialogs()
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
                    if self.headless:
                        self._scan_report('export')
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

        # Trigger the quit.
        if self.headless:
            # P4 quit fix: fire the Apple-event quit WITHOUT blocking, then dismiss
            # the "Don't Save" prompt the instant it appears and restore the user's
            # app. The old path blocked ~10s on the quit osascript because Logic
            # withholds the quit reply until the save prompt is answered — and we
            # only answered it AFTER that osascript timed out. ~10s pure waste/render.
            prior = _frontmost_app_name()
            # Restore target is the pre-launch user app, not `prior` (which reads
            # 'Logic Pro X' == proc when Logic is frontmost at quit → no-op). See
            # _run_masked_keys.
            restore_to = self._restore_target()
            print(f'[FOCUS] quit_logic: prior(mid-flight)={prior!r} '
                  f'_user_app={self._user_app!r} launcher_frontmost={self._launcher_frontmost!r} '
                  f'-> restore_to={restore_to!r} (proc={proc!r})', flush=True)
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
                    if restore_to and restore_to != proc:
                        _set_app_frontmost(restore_to)
                        print(f"[FOCUS] quit_logic: immediate restore after "
                              f"Don't-Save -> {restore_to!r}", flush=True)
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
            if focus_pulled and not clicked_any and restore_to and restore_to != proc:
                _set_app_frontmost(restore_to)
                print(f'[FOCUS] quit_logic: fallback restore (focus pulled, no '
                      f"Don't-Save click) -> {restore_to!r}", flush=True)
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

        # Deterministic end-of-job focus restore (headless only). Stop the sampler
        # first so the decision is made against a frozen target, then:
        #   • already on a REAL user app  → skip (that's exactly where the user wants
        #     to be — including the case where they stayed in the send-stems app).
        #   • on Logic / our launcher / nowhere, and a real user app is known → pull
        #     that app forward (never leave focus stranded on Logic).
        #   • no real user app ever seen (user never left the send-stems app) → only
        #     rescue from Logic by falling back to the launcher; otherwise leave it.
        # App activation only — cursor never moves; project is never saved.
        if self.headless:
            self._stop_focus_sampler()
            try:
                cur = _frontmost_app_name()
            except Exception:
                cur = ''
            if self._is_real_user_app(cur):
                print(f'[FOCUS] quit_logic: belt-and-braces SKIPPED — already on real '
                      f'user app {cur!r}', flush=True)
            elif self._user_app:
                _set_app_frontmost(self._user_app)
                print(f'[FOCUS] quit_logic: belt-and-braces RESTORED -> '
                      f'{self._user_app!r} (was {cur!r})', flush=True)
            elif cur in (proc, '') and self._launcher_frontmost:
                # No real user app was ever seen → user stayed in the send-stems app;
                # only act to avoid being stranded on Logic.
                _set_app_frontmost(self._launcher_frontmost)
                print(f'[FOCUS] quit_logic: belt-and-braces fell back to launcher '
                      f'{self._launcher_frontmost!r} (was {cur!r}; no real user app seen)',
                      flush=True)
            else:
                print(f'[FOCUS] quit_logic: belt-and-braces left focus as-is '
                      f'(cur={cur!r}, no real user app tracked)', flush=True)
            try:
                print(f'[FOCUS] quit_logic: JOB-END frontmost = '
                      f'{_frontmost_app_name()!r} (_user_app={self._user_app!r}, '
                      f'launcher_frontmost={self._launcher_frontmost!r})', flush=True)
            except Exception:
                pass

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
