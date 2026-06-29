"""
Unit tests for the DialogGuard decision engine (Step 6a).

Pure logic — no AX, no Logic launch. Realistic dialog bodies are built by
substituting runtime values into the REAL localized strings from
python/dialog_rules.yaml (so the test inputs match what Logic actually shows,
without hand-typing fragile Unicode), then we assert the engine's INDEPENDENT
decision (which button / pause / ignore), exercising rule priority, never_click,
the C2 gate, token-wildcarding, locale resolution, and the fail-safe.

Run:  python3 tests/test_dialog_guard.py        (or: python3 -m pytest tests/)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'python'))

from dialog_guard import DialogGuard, Decision, _TOKEN_RE  # noqa: E402


def fill(guard, key, locale, *vals):
    """Take the REAL localized string for `key` and replace its runtime tokens
    (%@ ^C %ld …) left-to-right with vals — i.e. simulate what the live dialog
    text looks like after Logic substitutes them."""
    s = guard._loc(key, locale)
    it = iter(vals)

    def repl(m):
        try:
            return next(it)
        except StopIteration:
            return m.group(0)
    return _TOKEN_RE.sub(repl, s)


def body_key(guard, rule_id, idx=0):
    for r in guard.rules['rules']:
        if r['id'] == rule_id:
            return r['body_keys'][idx]
    raise KeyError(rule_id)


# Per-job context where the C2 gate PASSES (G1∧G2∧G3).
GATE_OK = dict(pass_number=1,
               expected_dest_root='/Users/x/out/MyProject',
               actual_dest_root='/Users/x/out/MyProject',
               colliding_filename='Drums.wav')


class DialogGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = DialogGuard()

    # ---- helpers ----
    def dlg(self, body, buttons, title=''):
        return {'title': title, 'body': body, 'buttons': buttons}

    def assertClick(self, decision, label, terminal=None):
        self.assertEqual(decision.action, Decision.CLICK,
                         msg=f'expected CLICK got {decision}')
        self.assertEqual(decision.button, label, msg=f'{decision}')
        if terminal is not None:
            self.assertEqual(decision.terminal, terminal, msg=f'{decision}')

    def assertPause(self, decision):
        self.assertEqual(decision.action, Decision.PAUSE,
                         msg=f'expected PAUSE got {decision}')
        self.assertIsNone(decision.button)

    # ===================== C1 — save-changes on quit =====================
    def test_C1_save_en(self):
        b = fill(self.g, body_key(self.g, 'save_changes_on_quit'), 'en', 'My Song')
        d = self.g.decide(self.dlg(b, ['Save', 'Don’t Save', 'Cancel']), 'en')
        self.assertClick(d, 'Don’t Save')

    def test_C1_save_de(self):
        b = fill(self.g, body_key(self.g, 'save_changes_on_quit'), 'de', 'Mein Lied')
        d = self.g.decide(self.dlg(b, ['Sichern', 'Nicht sichern', 'Abbrechen']), 'de')
        self.assertClick(d, 'Nicht sichern')

    def test_C1_save_never_clicks_Save_when_no_dont_save(self):
        # Only Save/Cancel present → Don’t Save absent, Save is never_click → PAUSE.
        b = fill(self.g, body_key(self.g, 'save_changes_on_quit'), 'en', 'My Song')
        d = self.g.decide(self.dlg(b, ['Save', 'Cancel']), 'en')
        self.assertPause(d)

    # ===================== C2 — export overwrite (gated) =====================
    def test_C2_overwrite_en_gate_pass(self):
        b = fill(self.g, body_key(self.g, 'export_overwrite'), 'en', 'Drums.wav')
        d = self.g.decide(self.dlg(b, ['Replace', 'Cancel']), 'en', GATE_OK)
        self.assertClick(d, 'Replace')

    def test_C2_overwrite_de_gate_pass(self):
        b = fill(self.g, body_key(self.g, 'export_overwrite'), 'de', 'Drums.wav')
        d = self.g.decide(self.dlg(b, ['Ersetzen', 'Abbrechen']), 'de', GATE_OK)
        self.assertClick(d, 'Ersetzen')

    def test_C2_gate_fail_pass2(self):
        b = fill(self.g, body_key(self.g, 'export_overwrite'), 'en', 'Drums.wav')
        ctx = dict(GATE_OK, pass_number=2)
        self.assertPause(self.g.decide(self.dlg(b, ['Replace', 'Cancel']), 'en', ctx))

    def test_C2_gate_fail_collider_not_wav(self):
        b = fill(self.g, body_key(self.g, 'export_overwrite'), 'en', 'notes.txt')
        ctx = dict(GATE_OK, colliding_filename='notes.txt')
        self.assertPause(self.g.decide(self.dlg(b, ['Replace', 'Cancel']), 'en', ctx))

    def test_C2_gate_fail_dest_mismatch(self):
        b = fill(self.g, body_key(self.g, 'export_overwrite'), 'en', 'Drums.wav')
        ctx = dict(GATE_OK, actual_dest_root='/Users/x/Music/SomewhereElse')
        self.assertPause(self.g.decide(self.dlg(b, ['Replace', 'Cancel']), 'en', ctx))

    def test_C2_gate_pass_but_replace_missing(self):
        b = fill(self.g, body_key(self.g, 'export_overwrite'), 'en', 'Drums.wav')
        self.assertPause(self.g.decide(self.dlg(b, ['Cancel']), 'en', GATE_OK))

    # ===================== C3 — sample rate =====================
    def test_C3_sample_rate_en_pause(self):
        b = fill(self.g, body_key(self.g, 'sample_rate_change'), 'en', '48 kHz')
        d = self.g.decide(self.dlg(b, ['Change', 'Don’t Change', 'Cancel']), 'en')
        self.assertPause(d)

    # ===================== C4 — missing/incompatible plug-in =====================
    def test_C4_missing_plugin_en_pause(self):
        b = fill(self.g, body_key(self.g, 'missing_plugin'), 'en', 'FabFilter', 'UAD-2')
        self.assertPause(self.g.decide(self.dlg(b, ['OK']), 'en'))

    def test_C4_frozen_track_never_unfreeze(self):
        b = fill(self.g, body_key(self.g, 'missing_plugin', 2), 'en', 'Bass')
        d = self.g.decide(self.dlg(b, ['Unfreeze', 'Cancel']), 'en')
        self.assertPause(d)

    # ===================== C5 — missing audio (never Ignore/Locate) =====================
    def test_C5_missing_audio_en_pause(self):
        b = fill(self.g, body_key(self.g, 'missing_audio_files'), 'en', 'Strings', 'vln.wav')
        d = self.g.decide(self.dlg(b, ['Ignore', 'Locate', 'Skip']), 'en')
        self.assertPause(d)  # must NOT click Ignore or Locate

    def test_C5_missing_audio_de_pause(self):
        b = fill(self.g, body_key(self.g, 'missing_audio_files'), 'de', 'Strings', 'vln.wav')
        d = self.g.decide(self.dlg(b, ['Ignorieren', 'Suchen', 'Überspringen']), 'de')
        self.assertPause(d)

    # ===================== C6 — newer-version project =====================
    def test_C6_blocking_en_clicks_ok_terminal(self):
        b = fill(self.g, body_key(self.g, 'newer_version_blocking'), 'en')
        d = self.g.decide(self.dlg(b, ['OK']), 'en')
        self.assertClick(d, 'OK', terminal=True)

    def test_C6_warning_en_pause(self):
        b = fill(self.g, body_key(self.g, 'newer_version_warning'), 'en')
        self.assertPause(self.g.decide(self.dlg(b, ['OK', 'Cancel']), 'en'))

    # ===================== C7 — export failed =====================
    def test_C7_export_failed_en(self):
        b = fill(self.g, body_key(self.g, 'export_failed'), 'en')
        d = self.g.decide(self.dlg(b, ['OK']), 'en')
        self.assertClick(d, 'OK', terminal=True)

    def test_C7_export_failed_de(self):
        b = fill(self.g, body_key(self.g, 'export_failed'), 'de')
        d = self.g.decide(self.dlg(b, ['OK']), 'de')
        self.assertClick(d, 'OK', terminal=True)

    # ===================== C8 — crash recovery / revert =====================
    def test_C8_revert_en_pause(self):
        b = fill(self.g, body_key(self.g, 'crash_recovery_revert'), 'en', '14:02')
        d = self.g.decide(self.dlg(b, ['Recover', 'Cancel']), 'en')
        self.assertPause(d)  # never Recover

    # ===================== C9 / entry#1 — audio interface =====================
    def test_C9_audio_interface_en_clicks_ok_not_settings(self):
        b = fill(self.g, body_key(self.g, 'audio_interface_unavailable'), 'en', 'Focusrite')
        d = self.g.decide(self.dlg(b, ['Open Settings', 'OK']), 'en')
        self.assertClick(d, 'OK')

    def test_C9_audio_interface_de(self):
        b = fill(self.g, body_key(self.g, 'audio_interface_unavailable'), 'de', 'Focusrite')
        d = self.g.decide(self.dlg(b, ['OK']), 'de')
        self.assertClick(d, 'OK')

    def test_C9_audio_interface_builtin_variant_with_C_token(self):
        # second anchor uses ^C (device) → token wildcard must still match.
        b = fill(self.g, body_key(self.g, 'audio_interface_unavailable', 1), 'en',
                 'MacBook Pro Speakers')
        d = self.g.decide(self.dlg(b, ['Use MacBook Pro Speakers', 'OK', 'Open Settings']), 'en')
        self.assertClick(d, 'OK')

    # ===================== Adversarial =====================
    def test_ADV_unknown_dialog_with_destructive_button_pauses(self):
        d = self.g.decide(self.dlg('Permanently erase all takes from disk?',
                                   ['Delete', 'Cancel']), 'en')
        self.assertPause(d)  # unknown body → fail-safe, Delete never clicked

    def test_ADV_never_click_overrides_matching_rule(self):
        # audio-interface rule matches, but ONLY a never_click button is present.
        b = fill(self.g, body_key(self.g, 'audio_interface_unavailable'), 'en', 'Focusrite')
        d = self.g.decide(self.dlg(b, ['Open Settings']), 'en')
        self.assertPause(d)

    def test_ADV_token_substituted_body_still_matches(self):
        # A fully-substituted overwrite body (no literal %@) must still match.
        b = ('An item named "Lead Vox.wav" already exists in this location. '
             'Do you want to replace it with the one you are exporting?')
        d = self.g.decide(self.dlg(b, ['Replace', 'Cancel']), 'en', GATE_OK)
        self.assertClick(d, 'Replace')

    def test_ADV_empty_dialog_is_ignore(self):
        d = self.g.decide({'title': '', 'body': '', 'buttons': []}, 'en')
        self.assertEqual(d.action, Decision.IGNORE)

    def test_ADV_unknown_but_has_buttons_pauses_not_ignore(self):
        d = self.g.decide(self.dlg('Some Logic dialog we have never catalogued.',
                                   ['OK']), 'en')
        self.assertPause(d)

    def test_ADV_straight_quotes_body_matches_curly_anchor(self):
        # AX sometimes returns straight quotes; anchor uses curly. Must still match.
        b = ('Do you want to save the changes you made to "My Song"?')
        d = self.g.decide(self.dlg(b, ['Save', "Don't Save", 'Cancel']), 'en')
        # note: button uses straight apostrophe; normalization folds it to match.
        self.assertEqual(d.action, Decision.CLICK)
        self.assertEqual(d.rule_id, 'save_changes_on_quit')


if __name__ == '__main__':
    unittest.main(verbosity=2)
