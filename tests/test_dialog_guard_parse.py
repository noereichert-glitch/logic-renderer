"""
BOUNDARY tests for the DialogGuard DETECTOR parse + match chain (6b regression).

These are deliberately NOT clean synthetic dicts — that blind spot is exactly what
let the two C9 bugs ship. We exercise the REAL I/O boundary:

  • the Python parse inside `_scan_blocking_dialogs` is fed the ACTUAL \x1e/\x1f-
    delimited bytes the detector's osascript emits (captured from the live C9 alert),
    by stubbing only the `_osascript` seam — then the parsed dialog flows into the
    real `decide()`; and
  • the AppleScript `flat1` field-sanitizer is run through a REAL osascript process
    (UTF-8 temp-file in, to preserve curly quotes) on multi-line bodies and bodies
    carrying embedded separators, then assembled + parsed + decided end-to-end.

The two regressions these guard:
  1. PARSE: the detector used \x1e as the field delimiter, but str.splitlines()
     treats \x1e (RS) as a line boundary, so every record shattered before the
     field-split → `_scan_blocking_dialogs()` always returned []. (Fixed: split on
     '\n' only; flat1 guarantees no field carries a '\n'.)
  2. MATCH: the detector joined static texts with " / " while the anchors store
     newlines; _normalize collapsed the anchor newlines but left the live " / ", so
     C9 never matched → fail-safe PAUSE → OK never clicked. (Fixed: flat1 collapses
     all CR/LF/RS/US to spaces; _normalize collapses whitespace runs on both sides.)

Run:  python3 tests/test_dialog_guard_parse.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'python'))

import logic_render                                              # noqa: E402
from logic_render import LogicRenderBridge                       # noqa: E402
from dialog_guard import DialogGuard, Decision                   # noqa: E402

RS = '\x1e'   # field separator (Record Separator) — str.splitlines() BREAKS on this
US = '\x1f'   # button separator (Unit Separator)   — str.splitlines()-safe

# The real static-text values + buttons captured from the live C9 audio-interface
# alert (see the diagnosis run). The fixed detector space-joins the static texts
# and flat1-flattens, emitting one record terminated by '\n' (which _osascript then
# strips). This is the on-the-wire form decide() must handle.
C9_BODY = ('The last selected audio interface is not available. '
           'The previously selected interface “MacBook Pro Speakers” '
           'will be used instead for this session.')
C9_BUTTONS = ['Open Settings', 'OK']
RAW_C9 = f'{RS}{C9_BODY}{RS}Open Settings{US}OK'   # title empty; post-strip (no \n)

# flat1 handler — kept byte-identical to the one embedded in
# LogicRenderBridge._scan_blocking_dialogs. Mirror any change there.
_FLAT1 = '''on flat1(s)
    set d to AppleScript's text item delimiters
    set AppleScript's text item delimiters to {return, linefeed, character id 30, character id 31}
    set parts to text items of (s as text)
    set AppleScript's text item delimiters to " "
    set s to parts as text
    set AppleScript's text item delimiters to d
    return s
end flat1
set p to system attribute "FLAT1FILE"
return flat1(read (POSIX file p) as «class utf8»)'''

_HAS_OSASCRIPT = shutil.which('osascript') is not None


def osa_flat1(s):
    """Run the REAL flat1 handler over `s` in a fresh osascript process. Input is
    handed over via a UTF-8 temp file so curly quotes / non-ASCII survive intact
    (env-var passing mangles them)."""
    fd, p = tempfile.mkstemp(prefix='flat1_')
    try:
        os.write(fd, s.encode('utf-8'))
        os.close(fd)
        r = subprocess.run(['osascript', '-e', _FLAT1], capture_output=True,
                           text=True, env={**os.environ, 'FLAT1FILE': p}, timeout=20)
    finally:
        try:
            os.unlink(p)
        except OSError:
            pass
    out = r.stdout
    return out[:-1] if out.endswith('\n') else out


def make_bridge():
    b = LogicRenderBridge.__new__(LogicRenderBridge)   # no __init__ → no Logic dep
    b.headless = True
    b.process_name = 'Logic Pro X'
    return b


class _ScanPatch:
    """Context manager: stub the live-AX seam so `_scan_blocking_dialogs` runs its
    REAL parse against bytes we supply (exactly what osascript would have returned)."""
    def __init__(self, raw):
        self.raw = raw
    def __enter__(self):
        self._orig = logic_render._osascript
        # Signature must mirror the real _osascript (incl. the strip kwarg the scan
        # now passes); we return the supplied raw bytes verbatim (they already are the
        # final wire form the scan must parse — leading \x1e and all).
        logic_render._osascript = lambda script, timeout=15, strip=True: self.raw
        return self
    def __exit__(self, *a):
        logic_render._osascript = self._orig
        return False


class ParseBoundaryTests(unittest.TestCase):
    """Pure-Python: real detector bytes → real parse → real decide(). No osascript."""

    def setUp(self):
        self.b = make_bridge()
        self.guard = DialogGuard()

    def test_live_c9_raw_bytes_parse_then_click_ok(self):
        # The exact bytes the fixed detector emits for the live C9 alert.
        with _ScanPatch(RAW_C9):
            dialogs = self.b._scan_blocking_dialogs()
        self.assertEqual(len(dialogs), 1, 'C9 must parse to exactly one dialog')
        self.assertEqual(dialogs[0]['buttons'], ['Open Settings', 'OK'])
        self.assertEqual(dialogs[0]['title'], '')
        self.assertIn('audio interface', dialogs[0]['body'])
        dec = self.guard.decide(dialogs[0], locale='en')
        self.assertEqual(dec.action, Decision.CLICK)
        self.assertEqual(dec.button, 'OK')                 # not "Open Settings"
        self.assertEqual(dec.rule_id, 'audio_interface_unavailable')

    def test_splitlines_would_shatter_but_parse_survives(self):
        # Regression sentinel: the record DOES contain \x1e, so str.splitlines()
        # fragments it — proving why the parser must split on '\n' only.
        self.assertGreater(len(RAW_C9.splitlines()), 1,
                           'precondition: \\x1e makes splitlines() shatter the record')
        with _ScanPatch(RAW_C9):
            self.assertEqual(len(self.b._scan_blocking_dialogs()), 1)

    def test_two_dialogs_one_batch(self):
        # Two records, '\n'-separated, as the detector emits when two blockers are up.
        failed = 'The export operation failed.'
        raw = RAW_C9 + '\n' + f'{RS}{failed}{RS}OK'
        with _ScanPatch(raw):
            dialogs = self.b._scan_blocking_dialogs()
        self.assertEqual(len(dialogs), 2)
        d0 = self.guard.decide(dialogs[0], locale='en')
        d1 = self.guard.decide(dialogs[1], locale='en')
        self.assertEqual((d0.action, d0.button), (Decision.CLICK, 'OK'))
        self.assertEqual((d1.action, d1.rule_id, d1.terminal),
                         (Decision.CLICK, 'export_failed', True))

    def test_blank_and_short_lines_skipped(self):
        # Blank lines and any malformed (<3 field) line are skipped, not crashed.
        raw = '\n' + RAW_C9 + '\n' + 'garbage-no-separators\n'
        with _ScanPatch(raw):
            dialogs = self.b._scan_blocking_dialogs()
        self.assertEqual(len(dialogs), 1)
        self.assertEqual(dialogs[0]['buttons'], ['Open Settings', 'OK'])

    def test_scan_swallows_osascript_error(self):
        def boom(script, timeout=15):
            raise RuntimeError('transient AX error')
        orig = logic_render._osascript
        logic_render._osascript = boom
        try:
            self.assertEqual(self.b._scan_blocking_dialogs(), [])   # best-effort → []
        finally:
            logic_render._osascript = orig


@unittest.skipUnless(_HAS_OSASCRIPT, 'osascript not available')
class Flat1SanitizerBoundaryTests(unittest.TestCase):
    """Run the REAL AppleScript flat1 sanitizer + real parse + real decide()."""

    def setUp(self):
        self.b = make_bridge()
        self.guard = DialogGuard()

    def _wire(self, title, static_texts, buttons):
        """Reproduce the detector's record exactly: each field flat1'd via osascript,
        static texts space-joined first, fields RS-joined, buttons US-joined."""
        body = osa_flat1(' '.join(static_texts))
        btns = US.join(osa_flat1(x) for x in buttons)
        return f'{osa_flat1(title)}{RS}{body}{RS}{btns}'

    def test_flat1_collapses_newlines_and_separators(self):
        out = osa_flat1('line one\n\nline two\rline three' + RS + 'x' + US + 'y')
        for bad in ('\n', '\r', RS, US):
            self.assertNotIn(bad, out)
        # words survive, just space-separated
        for w in ('line', 'one', 'two', 'three', 'x', 'y'):
            self.assertIn(w, out)

    def test_multiline_body_pipeline_clicks_ok(self):
        # The C9 body delivered as a SINGLE multi-line static text (the exact shape
        # that shattered the old parser). flat1 must flatten it; decide() → CLICK OK.
        single = ('The last selected audio interface is not available.\n\n'
                  'The previously selected interface “Focusrite Scarlett” '
                  'will be used instead for this session.')
        raw = self._wire('', [single], ['Open Settings', 'OK'])
        self.assertNotIn('\n', raw.split(RS)[1])            # body carries no newline
        with _ScanPatch(raw):
            dialogs = self.b._scan_blocking_dialogs()
        self.assertEqual(len(dialogs), 1)
        dec = self.guard.decide(dialogs[0], locale='en')
        self.assertEqual((dec.action, dec.button, dec.rule_id),
                         (Decision.CLICK, 'OK', 'audio_interface_unavailable'))

    def test_embedded_separators_in_body_cannot_break_record(self):
        # A body literally containing the RS/US separators must not inject extra
        # fields/records — flat1 neutralizes them, so it stays one dialog.
        nasty = f'Some alert body with {RS} and {US} bytes embedded in it.'
        raw = self._wire('Title', [nasty], ['OK'])
        with _ScanPatch(raw):
            dialogs = self.b._scan_blocking_dialogs()
        self.assertEqual(len(dialogs), 1)
        self.assertEqual(dialogs[0]['buttons'], ['OK'])
        self.assertEqual(dialogs[0]['title'], 'Title')


@unittest.skipUnless(_HAS_OSASCRIPT, 'osascript not available')
class OsascriptStripSeamTests(unittest.TestCase):
    """The test that would have caught the live bug: exercise the REAL
    _osascript→strip seam (a fresh osascript process), NOT a stub returning constant
    bytes. A titleless alert (e.g. C9) emits a record beginning with the RS field
    separator; because Python counts \\x1e as whitespace, _osascript's default
    .strip() ate it → 3-field record collapsed to 2 → dropped. _scan_blocking_dialogs
    must request strip=False so the empty leading field survives."""

    def setUp(self):
        self.b = make_bridge()
        self.guard = DialogGuard()

    # Tiny AppleScript emitting ONE record whose TITLE field is EMPTY → the output
    # begins with the RS separator, exactly like the real C9 alert. Body uses the
    # real C9 wording (straight quotes via `quote`) so decide() can match.
    _EMITTER = '''set rs to (character id 30)
        set us to (character id 31)
        set b to "The last selected audio interface is not available. The previously selected interface " & quote & "MacBook Pro Speakers" & quote & " will be used instead for this session."
        return "" & rs & b & rs & "Open Settings" & us & "OK" & linefeed'''

    def test_strip_seam_keeps_empty_leading_field_and_clicks_ok(self):
        orig = logic_render._osascript

        def routed(script, timeout=60.0, strip=True):
            # Ignore the AX-scan `script`; run our emitter through the REAL _osascript,
            # HONORING the strip flag production passed. If production ever regresses
            # to the default strip=True, the leading \x1e is eaten here and the record
            # drops to 2 fields → 0 dialogs → this test fails (exactly the live bug).
            return orig(self._EMITTER, timeout=timeout, strip=strip)

        logic_render._osascript = routed
        try:
            dialogs = self.b._scan_blocking_dialogs()
        finally:
            logic_render._osascript = orig

        self.assertEqual(len(dialogs), 1, 'titleless record must survive the strip seam')
        self.assertEqual(dialogs[0]['title'], '')                  # empty leading field
        self.assertEqual(dialogs[0]['buttons'], ['Open Settings', 'OK'])
        dec = self.guard.decide(dialogs[0], locale='en')
        self.assertEqual((dec.action, dec.button, dec.rule_id),
                         (Decision.CLICK, 'OK', 'audio_interface_unavailable'))

    def test_default_osascript_still_strips(self):
        # Guard the low-blast-radius promise: default behavior is unchanged for every
        # other caller (still strips surrounding whitespace).
        self.assertEqual(logic_render._osascript('return "  hi  "'), 'hi')
        # strip=False preserves everything verbatim, incl. osascript's trailing '\n'.
        self.assertEqual(logic_render._osascript('return "  hi  "', strip=False), '  hi  \n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
