# Tests for the staged-success ladder helpers (2026-08-31):
#   _raw_differs_warnings — the (now non-fatal) FX-bypass comparison
#   _remove_folder_robust — cleanup that tolerates Finder droppings on exFAT
# Pure file-logic — no Logic Pro, no network.

import os
import sys
import struct
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'python'))

from stem_exporter import StemExporter, RAW_FILENAME_SUFFIX  # noqa: E402


def _wav(path, data_bytes):
    """Write a minimal valid RIFF/WAVE file with the given PCM data chunk."""
    with open(path, 'wb') as f:
        f.write(b'RIFF')
        f.write(struct.pack('<I', 36 + len(data_bytes)))
        f.write(b'WAVE')
        f.write(b'fmt ')
        f.write(struct.pack('<I', 16))
        f.write(struct.pack('<HHIIHH', 1, 2, 44100, 176400, 4, 16))
        f.write(b'data')
        f.write(struct.pack('<I', len(data_bytes)))
        f.write(data_bytes)


class StagedSuccessBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.proj = os.path.join(self.tmp, 'Song')
        self.wet = os.path.join(self.proj, '01_With_FX')
        self.raw = os.path.join(self.proj, '02_Raw')
        os.makedirs(self.wet)
        os.makedirs(self.raw)
        self.ex = StemExporter(file_path='x.logicx', output_folder=self.tmp, state={})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _pair(self, name, wet_bytes, raw_bytes):
        _wav(os.path.join(self.wet, f'{name}.wav'), wet_bytes)
        _wav(os.path.join(self.raw, f'{name}{RAW_FILENAME_SUFFIX}.wav'), raw_bytes)


class TestRawDiffersWarnings(StagedSuccessBase):
    def test_genuinely_differs_no_warning(self):
        self._pair('Kick', b'\x01\x02\x03\x04', b'\xAA\xBB\xCC\xDD')
        self.assertEqual(self.ex._raw_differs_warnings(self.proj), [])

    def test_identical_passes_warns_but_does_not_raise(self):
        # No-FX project: wet == raw. Must WARN (not raise) — the render still ships.
        self._pair('Kick', b'\x01\x02\x03\x04', b'\x01\x02\x03\x04')
        warns = self.ex._raw_differs_warnings(self.proj)
        self.assertEqual(len(warns), 1)
        self.assertEqual(warns[0]['stage'], 'raw_guard')
        self.assertIn('identical', warns[0]['message'].lower())

    def test_no_shared_names_warns(self):
        _wav(os.path.join(self.wet, 'Kick.wav'), b'\x01\x02')
        _wav(os.path.join(self.raw, f'Snare{RAW_FILENAME_SUFFIX}.wav'), b'\x03\x04')
        warns = self.ex._raw_differs_warnings(self.proj)
        self.assertEqual(len(warns), 1)
        self.assertIn('no matching', warns[0]['message'].lower())

    def test_one_of_many_differs_is_enough(self):
        self._pair('Kick', b'\x01\x02', b'\x01\x02')          # identical
        self._pair('Bass', b'\x01\x02', b'\x09\x09')          # differs
        self.assertEqual(self.ex._raw_differs_warnings(self.proj), [])


class TestTrackStates(StagedSuccessBase):
    def test_file_matches_track_naming_rules(self):
        m = StemExporter._file_matches_track
        self.assertTrue(m('A. One_1.wav', 'A. One'))
        self.assertTrue(m('Sum 6_1_raw.wav', 'Sum 6'))
        self.assertTrue(m('Kick.wav', 'Kick'))
        self.assertTrue(m('Kick_12.wav', 'Kick'))
        self.assertFalse(m('Kick_1.wav', 'Kick 2'))
        self.assertFalse(m('Kickdrum_1.wav', 'Kick'))

    def test_exclude_muted_removes_only_muted_stems(self):
        self._pair('Kick', b'\x01', b'\x02')
        self._pair('Scrap', b'\x03', b'\x04')
        removed = self.ex._exclude_muted(self.proj, '01_With_FX', ['Scrap'])
        self.assertEqual(removed, ['Scrap.wav'])
        self.assertTrue(os.path.exists(os.path.join(self.wet, 'Kick.wav')))
        self.assertFalse(os.path.exists(os.path.join(self.wet, 'Scrap.wav')))

    def test_completeness_flags_track_without_file(self):
        self._pair('Kick', b'\x01', b'\x02')
        warns = self.ex._completeness_warnings(
            self.proj, '01_With_FX', ['Kick', 'H. Eight', 'Scrap'], muted_names=['Scrap'])
        self.assertEqual(len(warns), 1)
        self.assertIn('H. Eight', warns[0]['message'])
        self.assertNotIn('Scrap', warns[0]['message'])   # muted → not expected

    def test_completeness_clean(self):
        self._pair('Kick', b'\x01', b'\x02')
        self.assertEqual(self.ex._completeness_warnings(
            self.proj, '01_With_FX', ['Kick'], []), [])


class TestLiveChecks(StagedSuccessBase):
    def test_silent_wav_detected(self):
        _wav(os.path.join(self.wet, 'Empty.wav'), b'\x00' * 64)
        _wav(os.path.join(self.wet, 'Loud.wav'), b'\x00\x01' * 32)
        warns = self.ex._silence_warnings(self.proj, '01_With_FX')
        self.assertEqual(len(warns), 1)
        self.assertIn('Empty.wav', warns[0]['message'])
        self.assertNotIn('Loud.wav', warns[0]['message'])

    def test_no_silent_no_warning(self):
        _wav(os.path.join(self.wet, 'Loud.wav'), b'\x07\x07')
        self.assertEqual(self.ex._silence_warnings(self.proj, '01_With_FX'), [])

    def test_pass_symmetry_clean(self):
        self._pair('Kick', b'\x01', b'\x02')
        self._pair('Snare', b'\x03', b'\x04')
        self.assertEqual(self.ex._pass_symmetry_warnings(self.proj), [])

    def test_pass_symmetry_missing_raw_stem(self):
        # Sum-8 shape: With-FX produced a stem the Raw pass silently lacks.
        self._pair('Kick', b'\x01', b'\x02')
        _wav(os.path.join(self.wet, 'Sum 8.wav'), b'\x05')
        warns = self.ex._pass_symmetry_warnings(self.proj)
        self.assertEqual(len(warns), 1)
        self.assertIn('missing', warns[0]['message'])
        self.assertIn('Sum 8.wav', warns[0]['message'])

    def test_warn_mirrors_into_state_immediately(self):
        # Layer 1 contract: a warning is visible in shared state the moment it
        # is recorded — not only at render end.
        self.ex._warnings = []
        self.ex._warn({'stage': 't', 'message': 'live!'})
        self.assertEqual(self.ex.state['warnings'][0]['message'], 'live!')


class TestCleanupCancelled(StagedSuccessBase):
    def test_removes_all_partial_output_and_empty_folder(self):
        # Loose root WAVs + both partial sets must vanish; per-render folder too
        # (it ends up empty). The user's output folder above it is untouched.
        _wav(os.path.join(self.proj, 'loose.wav'), b'\x01')
        self._pair('Kick', b'\x01', b'\x02')
        self.ex._cleanup_cancelled(self.proj)
        self.assertFalse(os.path.exists(self.proj))
        self.assertTrue(os.path.isdir(self.tmp))

    def test_leaves_foreign_files_and_folder_alone(self):
        # A non-WAV foreign file in the render folder is NOT ours to delete —
        # cleanup removes our sets but keeps the folder (rmdir refuses: not empty).
        with open(os.path.join(self.proj, 'notes.txt'), 'w') as f:
            f.write('user file')
        self._pair('Kick', b'\x01', b'\x02')
        self.ex._cleanup_cancelled(self.proj)
        self.assertTrue(os.path.exists(os.path.join(self.proj, 'notes.txt')))
        self.assertFalse(os.path.exists(self.wet))


class TestRemoveFolderRobust(StagedSuccessBase):
    def test_plain_delete(self):
        self._pair('Kick', b'\x01', b'\x02')
        self.assertTrue(self.ex._remove_folder_robust(self.proj))
        self.assertFalse(os.path.exists(self.proj))

    def test_scrubs_finder_droppings_then_deletes(self):
        # Simulate exFAT: a .DS_Store the first rmtree would trip on. The scrub
        # pass must remove it and the retry must then succeed.
        self._pair('Kick', b'\x01', b'\x02')
        with open(os.path.join(self.wet, '.DS_Store'), 'wb') as f:
            f.write(b'\x00\x00')
        with open(os.path.join(self.proj, '._Song'), 'wb') as f:
            f.write(b'\x00')
        self.assertTrue(self.ex._remove_folder_robust(self.proj))
        self.assertFalse(os.path.exists(self.proj))


if __name__ == '__main__':
    unittest.main(verbosity=2)
