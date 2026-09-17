"""
permissions.py — pre-flight for the two macOS grants every render depends on.

Both renderers drive their DAW through macOS accessibility (System Events).
That needs, for the RESPONSIBLE app — stemma.app when packaged, Terminal.app in
dev — an Accessibility grant and an Automation grant per scripted app. Without
them the driver cannot even see the DAW's windows, so a render used to stall
blind at "Launching…" until its ceiling (first dmg test, 2026-09-17).

check_permissions() asks macOS for the Accessibility prompt if the grant is
missing and returns a plain-language message when a render cannot proceed,
or None when all is well. It never raises.
"""
import subprocess

APP_NAME = 'stemma'

ACCESSIBILITY_MESSAGE = (
    f'{APP_NAME} needs Accessibility access to drive your DAW. Open System '
    'Settings → Privacy & Security → Accessibility, switch on '
    f'"{APP_NAME}" (or the Terminal app you launched it from), then render '
    'again. If it is already on, quit and reopen the app once.'
)
AUTOMATION_MESSAGE = (
    f'{APP_NAME} is not allowed to control System Events. Open System Settings '
    f'→ Privacy & Security → Automation, enable "System Events" under '
    f'"{APP_NAME}", then render again.'
)


def accessibility_trusted(prompt: bool = True) -> bool:
    """True when the responsible app is in the Accessibility list. With
    prompt=True, macOS shows its own "would like to control this computer
    using accessibility features" dialog when the grant is missing."""
    try:
        from ApplicationServices import (AXIsProcessTrustedWithOptions,
                                         kAXTrustedCheckOptionPrompt)
        return bool(AXIsProcessTrustedWithOptions(
            {kAXTrustedCheckOptionPrompt: bool(prompt)}))
    except Exception:
        # pyobjc unavailable (dev env without the framework): probe through
        # System Events instead — an untrusted process is refused with -25211
        # / "not allowed assistive access".
        r = subprocess.run(
            ['osascript', '-e',
             'tell application "System Events" to get name of first process'],
            capture_output=True, text=True, timeout=15)
        err = (r.stderr or '').lower()
        return not ('assistive' in err or '-25211' in err or '-1719' in err)


def automation_allowed() -> tuple:
    """(ok, error_text): whether Apple events to System Events are permitted.
    Denied automation surfaces as -1743 'Not authorized to send Apple events'."""
    try:
        r = subprocess.run(
            ['osascript', '-e',
             'tell application "System Events" to get name of first process'],
            capture_output=True, text=True, timeout=15)
    except Exception as e:
        return True, str(e)   # cannot tell — do not block the render on a probe
    err = (r.stderr or '').strip()
    if r.returncode != 0 and ('-1743' in err or 'not authorized' in err.lower()):
        return False, err
    return True, err


def check_permissions() -> str:
    """Friendly, actionable message if a render cannot proceed; None if fine."""
    try:
        if not accessibility_trusted(prompt=True):
            return ACCESSIBILITY_MESSAGE
        ok, _ = automation_allowed()
        if not ok:
            return AUTOMATION_MESSAGE
    except Exception as e:
        print(f'[Permissions] pre-flight could not run ({e}); proceeding.', flush=True)
    return None


class PermissionError_(RuntimeError):
    """Raised by the servers when check_permissions() reports a problem; carries
    user_message for the failure marker → notification + inbox."""
    def __init__(self, user_message):
        super().__init__(user_message)
        self.user_message = user_message
