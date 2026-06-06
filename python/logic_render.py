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
STATUS: SCAFFOLD. The class/contract below is complete and is what stem_exporter
imports. The AppleScript bodies marked `TODO(real-machine)` MUST be written and
verified against a real Logic Pro install — element names/indexes can only be
confirmed by dumping Logic's accessibility tree on the actual machine. See
docs/Logic_Renderer_ClaudeCode_Prompts_v1.md (Phase 1 & 2) for exactly how.
═══════════════════════════════════════════════════════════════════════════════
"""
import os
import subprocess
import time


LOGIC_APP_CANDIDATES = [
    '/Applications/Logic Pro.app',
    '/Applications/Logic Pro X.app',
]

# Logic's process name as seen by System Events / `pgrep`. Confirm on the real
# machine (`osascript -e 'tell app "System Events" to name of every process'`).
LOGIC_PROCESS_NAME = 'Logic Pro'


# ── discovery ──────────────────────────────────────────────────────────────────
def find_logic() -> str:
    for p in LOGIC_APP_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError('Logic Pro not found in /Applications.')


def detect_logic_process_name(timeout: float = 5.0) -> str:
    """Return the running Logic process name. Logic *should* be 'Logic Pro'; this
    confirms it against the live process list so menu-bar scripting targets the
    right process. TODO(real-machine): verify the exact string."""
    end = time.time() + timeout
    script = ('tell application "System Events" to get name of every process '
              'whose background only is false')
    while time.time() < end:
        try:
            out = subprocess.check_output(['osascript', '-e', script], text=True)
            for candidate in ('Logic Pro', 'Logic Pro X'):
                if candidate in out:
                    return candidate
        except subprocess.CalledProcessError:
            pass
        time.sleep(0.3)
    return LOGIC_PROCESS_NAME


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
        """Open the .logicx project. `open -a` lets Logic own its own process; we
        track liveness via pgrep rather than a child handle."""
        subprocess.run(['open', '-a', self.app_path, project_path], check=True)
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

    def wait_for_logic_ready(self, timeout: float = 180.0) -> bool:
        """Wait until Logic's project window is up and plugin-load CPU has tapered.
        TODO(real-machine): the robust signal is 'the main project window exists
        AND no modal sheet is open'. Start with a window-exists poll + a small
        settle margin; tune like fl_render.wait_for_fl_ready (adaptive, with a
        proven floor and a hard ceiling)."""
        end = time.time() + timeout
        # Wait for the process to register first.
        while time.time() < end and not self.is_alive():
            time.sleep(0.5)
        # TODO(real-machine): replace the fixed settle with a window-exists poll:
        #   tell application "System Events" to tell process "<name>"
        #       return (exists window 1)
        #   end tell
        # plus a CPU-taper check for plugin-heavy projects.
        time.sleep(20.0)
        return self.is_alive()

    # — the export —
    def export_stems(self, output_folder: str, file_stem: str = 'stem',
                     bypass_fx: bool = False):
        """Drive ONE 'All Tracks as Audio Files' export into `output_folder`.
        WAVs land loose in output_folder; the orchestrator sorts them afterwards.

        STEPS (implement + verify on the real machine — see Phase 1/2 prompts):
          1. Bring Logic frontmost.
          2. Menu: File ▸ Export ▸ "All Tracks as Audio Files…".
             TODO(real-machine): confirm the EXACT menu item title and submenu
             path for the installed Logic version (it has varied: "All Tracks as
             Audio Files" vs "…Audio File"). Dump the menu with System Events.
          3. In the export dialog (a Cocoa Save panel + accessory controls):
             a. Navigate to `output_folder` via ⌘⇧G "Go to Folder", type the path,
                Return. (Keeps us off Finder automation.)
             b. Set File Format → WAVE.
                TODO(real-machine): find the pop-up button's element name.
             c. Set "Bypass Effect Plug-ins" checkbox to `bypass_fx`.
                TODO(real-machine): read the checkbox's current AXValue and only
                click if it differs (don't blind-toggle).
             d. Normalize → Off.  Bit depth → leave default / 24-bit (user wants
                native rate; sample rate isn't in this dialog, it follows project).
             e. Click "Save"/"Export".
          4. Logic may prompt to replace existing files on the 2nd pass if names
             collide — but since we SORT pass 1's WAVs into 01_With_FX before pass
             2 runs, the root is empty, so collisions shouldn't occur. Handle a
             stray "Replace" sheet defensively anyway.
          5. Wait for completion (see wait_for_export_complete).
        Raise LogicCrashedError if Logic dies at any point."""
        if not self.is_alive():
            raise LogicCrashedError('Logic not running at export start.')

        # ── TODO(real-machine): the AppleScript export driver goes here. ──
        # A coordinate-click fallback is explicitly NOT used (no Screen Recording).
        raise NotImplementedError(
            'logic_render.export_stems: implement the AppleScript export driver — '
            'see the Phase 1 prompt in docs/Logic_Renderer_ClaudeCode_Prompts_v1.md')

    def wait_for_export_complete(self, output_folder: str,
                                 timeout: float = 1800.0) -> None:
        """Primary 'done' signal: Logic's progress/bounce window closing after it
        was seen open; WAV file-size stability is the backstop. Raise
        LogicCrashedError if Logic exits mid-wait.
        TODO(real-machine): implement both signals (mirror
        fl_render.wait_for_export_complete: required_stable consecutive identical
        file-size snapshots)."""
        raise NotImplementedError('implement wait_for_export_complete — Phase 1')

    def quit_logic(self, save: bool = False, force: bool = False):
        """Quit Logic WITHOUT saving (the export must never write the project).
        Short ⌘Q, poll the process for exit, one bounded 'Don't Save' if a sheet
        blocks it, escalate to terminate/kill. Mirror fl_render.quit_fl_cleanly."""
        if not self.is_alive():
            return
        # TODO(real-machine): ⌘Q + 'Don't Save' sheet handling. For now, terminate.
        try:
            _osascript(f'tell application "{self.process_name}" to quit', timeout=15)
        except Exception:
            pass
        end = time.time() + 20
        while time.time() < end and self.is_alive():
            time.sleep(0.5)
        if self.is_alive():
            subprocess.run(['pkill', '-x', self.process_name], capture_output=True)

    # — context manager —
    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.quit_logic(force=True)
        except Exception:
            pass
