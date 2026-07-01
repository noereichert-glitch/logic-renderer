"""
Integration tests for the DialogGuard EXECUTOR wired into LogicRenderBridge (6b).

No Logic, no AX, no AppleScript. We build a bridge WITHOUT __init__ (so no Logic
install is required), inject the real decision engine, and STUB the two live-AX
seams — `_scan_blocking_dialogs` (detector) and `_click_dialog_button` (executor
click) — so we can feed synthetic {title, body, buttons} through `_handle_dialogs`
and assert it performs ONLY the decided action:

  • CLICK  → clicked exactly the decided button, no raise
  • IGNORE → nothing clicked, no raise
  • PAUSE  → raises DialogGuardPause, NOTHING clicked (clean abort)
  • fail_job/terminal → clicks OK, THEN raises DialogGuardPause(terminal=True)
  • unknown dialog with a destructive button → PAUSE, never clicked (fail-safe)

Run:  python3 tests/test_dialog_guard_executor.py   (or python3 -m pytest tests/)
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'python'))

from dialog_guard import DialogGuard, Decision, _TOKEN_RE       # noqa: E402
from logic_render import LogicRenderBridge, DialogGuardPause    # noqa: E402


def fill(guard, key, locale, *vals):
    s = guard._loc(key, locale)
    it = iter(vals)
    return _TOKEN_RE.sub(lambda m: next(it, m.group(0)), s)


def body_key(guard, rule_id, idx=0):
    for r in guard.rules['rules']:
        if r['id'] == rule_id:
            return r['body_keys'][idx]
    raise KeyError(rule_id)


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        # Build a bridge WITHOUT running __init__ (avoids find_logic / Logic dep).
        self.b = LogicRenderBridge.__new__(LogicRenderBridge)
        self.b.headless = True
        self.b.process_name = 'Logic Pro X'
        self.guard = DialogGuard()
        self.b._guard = self.guard
        self.b._guard_loaded = True
        # Stub the live-AX seams.
        self.clicks = []
        self.b._click_dialog_button = lambda label: (self.clicks.append(label) or True)
        self.b._active_locale = lambda: 'en'
        self._queue = []
        self.b._scan_blocking_dialogs = lambda: list(self._queue)

    def feed(self, *dialogs):
        self._queue = list(dialogs)

    def dlg(self, body, buttons, title=''):
        return {'title': title, 'body': body, 'buttons': buttons}

    # ---- CLICK ----
    def test_click_audio_interface_clicks_ok_only(self):
        b = fill(self.guard, body_key(self.guard, 'audio_interface_unavailable'),
                 'en', 'Focusrite')
        self.feed(self.dlg(b, ['Open Settings', 'OK']))
        handled = self.b._handle_dialogs(context=None)
        self.assertEqual(self.clicks, ['OK'])          # clicked OK
        self.assertNotIn('Open Settings', self.clicks)  # never the never-click one
        self.assertEqual(handled[0][1].action, Decision.CLICK)

    # ---- IGNORE ----
    def test_ignore_empty_dialog_no_click_no_raise(self):
        self.feed({'title': '', 'body': '', 'buttons': []})
        handled = self.b._handle_dialogs()
        self.assertEqual(self.clicks, [])              # nothing clicked
        self.assertEqual(handled[0][1].action, Decision.IGNORE)

    # ---- PAUSE ----
    def test_pause_missing_audio_raises_no_click(self):
        b = fill(self.guard, body_key(self.guard, 'missing_audio_files'),
                 'en', 'Strings', 'vln.wav')
        self.feed(self.dlg(b, ['Ignore', 'Locate', 'Skip']))
        with self.assertRaises(DialogGuardPause) as cm:
            self.b._handle_dialogs()
        self.assertEqual(self.clicks, [])              # never clicked on PAUSE
        self.assertFalse(cm.exception.terminal)
        self.assertEqual(cm.exception.rule_id, 'missing_audio_files')
        self.assertEqual(cm.exception.dialog['buttons'], ['Ignore', 'Locate', 'Skip'])

    def test_pause_unknown_dialog_with_destructive_button(self):
        self.feed(self.dlg('Permanently erase all takes from disk?', ['Delete', 'Cancel']))
        with self.assertRaises(DialogGuardPause):
            self.b._handle_dialogs()
        self.assertEqual(self.clicks, [])              # Delete never clicked

    # ---- fail_job / terminal ----
    def test_terminal_export_failed_clicks_ok_then_raises(self):
        b = fill(self.guard, body_key(self.guard, 'export_failed'), 'en')
        self.feed(self.dlg(b, ['OK']))
        with self.assertRaises(DialogGuardPause) as cm:
            self.b._handle_dialogs()
        self.assertEqual(self.clicks, ['OK'])          # cleared the modal
        self.assertTrue(cm.exception.terminal)         # then flagged terminal
        self.assertEqual(cm.exception.rule_id, 'export_failed')

    # ---- ordering: a CLICK dialog ahead of a PAUSE dialog ----
    def test_click_then_pause_in_same_pass(self):
        ok = fill(self.guard, body_key(self.guard, 'audio_interface_unavailable'),
                  'en', 'Focusrite')
        pause = fill(self.guard, body_key(self.guard, 'missing_audio_files'),
                     'en', 'Strings', 'vln.wav')
        self.feed(self.dlg(ok, ['OK']), self.dlg(pause, ['Ignore', 'Skip']))
        with self.assertRaises(DialogGuardPause):
            self.b._handle_dialogs()
        self.assertEqual(self.clicks, ['OK'])          # first handled, then aborted

    # ---- legacy guard: not headless → no-op ----
    def test_not_headless_is_noop(self):
        self.b.headless = False
        self.feed(self.dlg('anything at all', ['Delete']))
        self.assertEqual(self.b._handle_dialogs(), [])
        self.assertEqual(self.clicks, [])


class PostExportScanTests(unittest.TestCase):
    """Real-seam test for the post-Export gap fix: wait_for_export_complete must run
    the DialogGuard each poll tick so a dialog appearing AFTER the Export click is
    handled at once instead of hanging to the ~1800s timeout. Exercises the REAL
    wait_for_export_complete loop + REAL engine + REAL _handle_dialogs; only the
    live-AX scan/click seams are stubbed (no Logic). Without the gap fix, the
    export_failed case would never raise and would run to the (here short) timeout."""

    def setUp(self):
        self.b = LogicRenderBridge.__new__(LogicRenderBridge)
        self.b.headless = True
        self.b.process_name = 'Logic Pro X'
        self.guard = DialogGuard()
        self.b._guard = self.guard
        self.b._guard_loaded = True
        self.clicks = []
        self.b._click_dialog_button = lambda label: (self.clicks.append(label) or True)
        self.b._active_locale = lambda: 'en'
        self.b.is_alive = lambda: True
        # wait_for_export_complete now records inert dialog-scan timing; this
        # __new__-built fixture bypasses __init__, so provide the counters it uses.
        self.b._scan_count = 0
        self.b._scan_ms_total = 0.0
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wav(self, name='a.wav', size=1000):
        with open(os.path.join(self.tmp, name), 'wb') as f:
            f.write(b'\x00' * size)

    def test_export_failed_caught_midwait_not_hang(self):
        # export_failed (fail_job) appears on the 2nd tick → click OK + terminal raise,
        # well before the 5s timeout would fire.
        failed = fill(self.guard, body_key(self.guard, 'export_failed'), 'en')
        calls = {'n': 0}

        def scan():
            calls['n'] += 1
            return ([] if calls['n'] < 2
                    else [{'title': '', 'body': failed, 'buttons': ['OK']}])
        self.b._scan_blocking_dialogs = scan
        t0 = time.time()
        with self.assertRaises(DialogGuardPause) as cm:
            self.b.wait_for_export_complete(self.tmp, timeout=5,
                                            required_stable=2, poll=0.01)
        self.assertTrue(cm.exception.terminal)            # fail_job → terminal
        self.assertEqual(cm.exception.rule_id, 'export_failed')
        self.assertIn('OK', self.clicks)                  # cleared the modal
        self.assertLess(time.time() - t0, 4)              # caught fast, not at timeout

    def test_unknown_postexport_dialog_failsafe_pause(self):
        # An unrecognized post-export dialog (e.g. the macOS permission alert seen in
        # the live C7 run) → fail-safe PAUSE, nothing clicked.
        self.b._scan_blocking_dialogs = lambda: [{
            'title': '', 'buttons': ['OK'],
            'body': "The file couldn’t be saved because you don’t have permission."}]
        with self.assertRaises(DialogGuardPause) as cm:
            self.b.wait_for_export_complete(self.tmp, timeout=5,
                                            required_stable=2, poll=0.01)
        self.assertIsNone(cm.exception.rule_id)           # fail-safe (no rule)
        self.assertFalse(cm.exception.terminal)           # PAUSE, not fail_job
        self.assertEqual(self.clicks, [])                 # never clicked

    def test_healthy_bounce_no_dialog_returns_normally(self):
        # No blocking dialog (scan []), a stable WAV set → returns, nothing clicked.
        self.b._scan_blocking_dialogs = lambda: []
        self._wav()
        self.b.wait_for_export_complete(self.tmp, timeout=5,
                                        required_stable=2, poll=0.01)
        self.assertEqual(self.clicks, [])

    def test_legacy_not_headless_never_scans(self):
        # Legacy path must NOT call the guard during the bounce wait.
        self.b.headless = False
        scanned = {'n': 0}
        self.b._scan_blocking_dialogs = lambda: (scanned.__setitem__('n', scanned['n'] + 1) or [])
        self._wav()
        self.b.wait_for_export_complete(self.tmp, timeout=5,
                                        required_stable=2, poll=0.01)
        self.assertEqual(scanned['n'], 0)                 # never scanned on legacy


if __name__ == '__main__':
    unittest.main(verbosity=2)
