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

# Shown on the library row (amber, not a red failure) and in the inbox, so it
# is the fix itself, in one line (owner wording 2026-09-19). The dev-mode
# detail (the grant belongs to Terminal.app there) goes to the log instead.
ACCESSIBILITY_MESSAGE = (
    f'Enable Accessibility access for {APP_NAME} in System Settings › Privacy & '
    f'Security › Accessibility, then relaunch {APP_NAME}.'
)
AUTOMATION_MESSAGE = (
    f'Allow {APP_NAME} to control System Events in System Settings › Privacy & '
    f'Security › Automation, then relaunch {APP_NAME}.'
)
DEV_HINT = ('[Permissions] In development the grant belongs to the app stemma was '
            'launched from (Terminal.app), not to "stemma".')


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


def check_permissions():
    """A PermissionProblem (which grant, one-line fix) if a render cannot
    proceed; None if fine. Never raises."""
    try:
        if not accessibility_trusted(prompt=True):
            print(DEV_HINT, flush=True)
            return PermissionProblem('accessibility', ACCESSIBILITY_MESSAGE)
        ok, _ = automation_allowed()
        if not ok:
            print(DEV_HINT, flush=True)
            return PermissionProblem('automation', AUTOMATION_MESSAGE)
    except Exception as e:
        print(f'[Permissions] pre-flight could not run ({e}); proceeding.', flush=True)
    return None


class PermissionProblem(str):
    """The pre-flight's verdict: a str (the message, so older callers and
    f-strings keep working) that also knows which grant is missing."""
    def __new__(cls, which, message):
        obj = super().__new__(cls, message)
        obj.which = which
        obj.message = message
        return obj


class PermissionError_(RuntimeError):
    """Raised by the servers when check_permissions() reports a problem. Carries
    user_message for the row / notification / inbox and code='permissions' so
    the app renders it as an amber to-do rather than a failed render."""
    code = 'permissions'

    def __init__(self, problem):
        super().__init__(str(problem))
        self.user_message = str(problem)
        self.which = getattr(problem, 'which', None)
