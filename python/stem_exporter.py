"""
StemExporter — One-Click stem orchestration (Logic Pro).

WHAT'S DIFFERENT FROM FL / ABLETON
----------------------------------
Logic's `File ▸ Export ▸ All Tracks as Audio Files…` dialog does the heavy
lifting the other DAWs needed hacks for:

  • Per-track stems          → the dialog bounces one WAV per track natively.
  • Wet vs. dry (Raw) pass   → a single "Bypass Effect Plug-ins" CHECKBOX in the
                               SAME dialog. No Remote Script (Ableton), no
                               reg.xml editing (FL). Toggle the box and re-export.
  • Both passes, one launch  → unlike FL (whose FX flag is read at launch), Logic
                               reads the checkbox per-export, so we launch Logic
                               ONCE and run both exports in the same session.

PASSES (current scope — wet + dry, per the user decision)
  Pass 1 → 01_With_FX   All Tracks as Audio Files, Bypass Effect Plug-ins OFF
  Pass 2 → 02_Raw       All Tracks as Audio Files, Bypass Effect Plug-ins ON  → dry

  These are the only two sets produced.

SAFETY (reused, proven)
  • _validate_set       — each set must contain ≥2 WAVs (else the export was a
                          single mixdown, not per-track) → fail loudly.
  • _assert_raw_differs — 02_Raw must differ in PCM content from 01_With_FX on at
                          least one stem (the "T11 guard") → proves FX were really
                          bypassed; else don't ship.
  • try/finally         — Logic is always quit, even on failure (no leaked DAW).
  • retry-on-crash      — a pass is retried only if Logic's PROCESS actually died.

FORMAT (user decision): follow the project's NATIVE sample rate; bit depth left
at a sensible default chosen in the export dialog (see logic_render.py). Nothing
about format is forced from here.
"""
import glob
import hashlib
import os
import shutil
import struct
import time
import zipfile

from logic_render import (
    LogicRenderBridge,
    LogicCrashedError,
    dismiss_macos_crash_reporter,
    resolve_project_path,
)
from one_click_helpers import (
    sort_wavs_into_subfolder,
    zip_project_folder,
)

# How many times to retry a single pass if Logic crashes mid-export. This is for
# transient crashes — a plugin that deterministically crashes Logic will burn all
# attempts and still fail, which is intentional.
MAX_PASS_ATTEMPTS = 3


class StemExporter:
    def __init__(self, file_path, output_folder, state, headless=True):
        self.file_path = file_path
        self.output_folder = output_folder
        self.state = state
        # headless (default on): run the whole export invisibly/backgrounded — no
        # focus steal, cursor never moves (Tier 0, docs/2026-06-28/). Pass
        # headless=False to fall back to the legacy frontmost+keystroke path.
        self.headless = headless

    # ── state helpers ────────────────────────────────────────────────────────
    def _set_status(self, title, sub='', progress=None):
        self.state['status_title'] = title
        self.state['status_sub'] = sub
        if progress is not None:
            self.state['progress'] = progress
        print(f'[Exporter] {title} — {sub}')

    # ── main entrypoint ──────────────────────────────────────────────────────
    def run(self):
        # Resolve package- vs folder-style projects to the inner .logicx (§11) so
        # both the launch and the project-name derivation use the real project.
        self.file_path = resolve_project_path(self.file_path)
        project_name = os.path.splitext(os.path.basename(self.file_path))[0]
        project_folder = os.path.join(self.output_folder, project_name)
        os.makedirs(project_folder, exist_ok=True)

        self._set_status('Launching Logic Pro…', 'Opening project', progress=5)
        bridge = LogicRenderBridge(headless=self.headless)
        bridge.launch(self.file_path)

        # ONE Logic session for BOTH passes. try/finally guarantees a clean quit.
        try:
            if not bridge.wait_for_logic_ready():
                raise RuntimeError('Logic Pro did not finish loading in time.')

            # Clear any leftover macOS crash-reporter dialog so it can't steal focus.
            dismiss_macos_crash_reporter()

            # Pass 1 — 01_With_FX (Bypass Effect Plug-ins OFF → wet)
            self._set_status('Pass 1/2 — With FX',
                             'Exporting all tracks with plugins', progress=15)
            self._run_pass_with_retry(bridge, project_folder, project_name,
                                      bypass_fx=False, pass_label='Pass 1/2 — With FX')
            sort_wavs_into_subfolder(
                src_folder=project_folder, subfolder_name='01_With_FX',
                exclude_group_wavs=False, group_track_names=[],
            )
            self._validate_set(project_folder, '01_With_FX')
            self.state['progress'] = 50

            # Pass 2 — 02_Raw (Bypass Effect Plug-ins ON → dry). Same Logic session.
            self._set_status('Pass 2/2 — Raw',
                             'Exporting dry stems (plugins bypassed)', progress=55)
            self._run_pass_with_retry(bridge, project_folder, project_name,
                                      bypass_fx=True, pass_label='Pass 2/2 — Raw')
            sort_wavs_into_subfolder(
                src_folder=project_folder, subfolder_name='02_Raw',
                exclude_group_wavs=False, group_track_names=[],
            )
            self._validate_set(project_folder, '02_Raw')
            self.state['progress'] = 85
        finally:
            self._set_status('Closing Logic Pro…', 'Quitting cleanly')
            t_quit = time.time()
            try:
                bridge.quit_logic()
            except Exception as e:
                print(f'[Exporter] WARNING: clean quit failed: {e}')
            print(f'[Exporter] Logic quit in {time.time()-t_quit:.1f}s.')

        # T11 guard (REQUIRED): 02_Raw must differ in PCM from 01_With_FX.
        self._set_status('Verifying raw pass…', 'Confirming FX were bypassed', progress=88)
        self._assert_raw_differs(project_folder)

        # Zip.
        self._set_status('Zipping…', 'Packaging the sets', progress=94)
        zip_path = zip_project_folder(project_folder)

        sets = {
            '01_With_FX': sorted(glob.glob(os.path.join(project_folder, '01_With_FX', '*.wav'))),
            '02_Raw': sorted(glob.glob(os.path.join(project_folder, '02_Raw', '*.wav'))),
        }

        # Verify the zip is a COMPLETE, valid copy BEFORE deleting the source
        # folder — that folder holds the ONLY other copy of the stems, so the
        # check must be solid. _verify_zip raises on any problem; if it raises we
        # skip the delete and the failure propagates to server.py's terminal
        # except (critical-failure notification/inbox), folder left intact.
        self._set_status('Verifying zip…', 'Confirming the archive is complete', progress=97)
        self._verify_zip(zip_path, sets)

        # Verified → delete the source folder we just zipped, leaving only
        # <project>.zip. We only ever remove the per-job folder we created above.
        self._set_status('Cleaning up…', 'Removing the un-zipped stem folder', progress=99)
        shutil.rmtree(project_folder)
        print(f'[Exporter] Source folder removed after verified zip: {project_folder}')

        result = {
            # Source folder is gone; point the UI's "Open Folder" at the folder
            # that now holds the zip so it opens a real path.
            'project_folder': self.output_folder,
            'zip_path': zip_path,
            'sets': sets,
        }
        self.state['zip_path'] = zip_path
        self.state['project_folder'] = self.output_folder
        return result

    # ── zip verification (must pass before deleting the only other copy) ───────
    def _verify_zip(self, zip_path, sets):
        """Prove <project>.zip is a complete, valid archive of the exported stems
        BEFORE the caller deletes the source folder. Raises RuntimeError on ANY
        failure so the caller keeps the folder and the failure surfaces.

        Checks, in order:
          1. the zip file exists and is non-zero,
          2. it opens as a valid zip archive with no corrupt entries (CRC check),
          3. every exported WAV from 01_With_FX + 02_Raw is present in the archive
             under its expected path (count/paths match what was exported)."""
        if not os.path.isfile(zip_path):
            raise RuntimeError(f'Zip verification failed: {zip_path} was not created.')
        if os.path.getsize(zip_path) == 0:
            raise RuntimeError(f'Zip verification failed: {zip_path} is empty (0 bytes).')
        if not zipfile.is_zipfile(zip_path):
            raise RuntimeError(f'Zip verification failed: {zip_path} is not a valid zip archive.')

        # Expected arcnames: relpath of each exported WAV against the zip's parent,
        # exactly how zip_project_folder wrote its entries (relpath(full, parent)).
        parent = os.path.dirname(os.path.abspath(zip_path))
        expected = set()
        for wavs in sets.values():
            for w in wavs:
                expected.add(os.path.relpath(os.path.abspath(w), parent))
        if not expected:
            raise RuntimeError('Zip verification failed: no exported stems to verify.')

        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()  # returns the first corrupt entry, or None if all OK
            if bad is not None:
                raise RuntimeError(
                    f'Zip verification failed: corrupt entry {bad!r} in {zip_path}.')
            names = set(zf.namelist())

        missing = sorted(expected - names)
        if missing:
            raise RuntimeError(
                f'Zip verification failed: {len(missing)} of {len(expected)} expected '
                f'stem(s) missing from the archive (e.g. {missing[:3]}). Keeping source folder.')
        print(f'[Exporter] Zip verified: {len(expected)} stem(s) present, archive intact.')

    # ── one export pass, with crash-retry ─────────────────────────────────────
    def _run_pass_with_retry(self, bridge, project_folder, file_stem,
                             bypass_fx, pass_label):
        """Drive ONE 'All Tracks as Audio Files' export. Retry ONLY if Logic's
        process actually died (LogicCrashedError); any other error propagates.
        Between attempts, stale partial WAVs in the project root are cleared so a
        retry starts clean. WAVs land in the project root and are sorted out by
        the caller after this returns."""
        attempt = 0
        while True:
            attempt += 1
            try:
                bridge.export_stems(
                    output_folder=project_folder,
                    file_stem=file_stem,
                    bypass_fx=bypass_fx,
                )
                return
            except LogicCrashedError as e:
                if attempt >= MAX_PASS_ATTEMPTS:
                    raise RuntimeError(
                        f'{pass_label}: Logic crashed {attempt}× — giving up.') from e
                print(f'[Exporter] {pass_label}: Logic crashed (attempt {attempt}); '
                      f'relaunching and retrying.')
                self._cleanup_stale_wavs(project_folder)
                bridge.relaunch(self.file_path)
                if not bridge.wait_for_logic_ready():
                    raise RuntimeError('Logic did not reload after a crash.')
                dismiss_macos_crash_reporter()

    def _cleanup_stale_wavs(self, project_folder):
        """Remove loose WAVs in the project root (partial output from a crashed
        attempt). Sorted sub-folders are left untouched."""
        for w in glob.glob(os.path.join(project_folder, '*.wav')):
            try:
                os.remove(w)
            except OSError:
                pass

    # ── output validation ─────────────────────────────────────────────────────
    def _validate_set(self, project_folder, subfolder):
        """REQUIRED per-set check. A real per-track export yields ≥2 WAVs. Fewer
        than 2 ⇒ Logic produced a single mixdown (wrong export item / dialog
        misfired) ⇒ fail loudly BEFORE zipping."""
        wavs = sorted(glob.glob(os.path.join(project_folder, subfolder, '*.wav')))
        if len(wavs) < 2:
            raise RuntimeError(
                f'{subfolder}: expected ≥2 stems, found {len(wavs)}. The export '
                f'likely produced a single mixdown instead of per-track stems.')
        return wavs

    # ── T11 raw-differs guard ──────────────────────────────────────────────────
    def _assert_raw_differs(self, project_folder):
        """At least one stem present in BOTH 01_With_FX and 02_Raw must differ in
        PCM audio content — proof the 'Bypass Effect Plug-ins' box actually took
        effect. If every shared stem is byte-identical, FX were NOT bypassed →
        raise, do not ship."""
        wet_dir = os.path.join(project_folder, '01_With_FX')
        raw_dir = os.path.join(project_folder, '02_Raw')
        wet = {os.path.basename(p): p for p in glob.glob(os.path.join(wet_dir, '*.wav'))}
        raw = {os.path.basename(p): p for p in glob.glob(os.path.join(raw_dir, '*.wav'))}
        shared = sorted(set(wet) & set(raw))
        if not shared:
            raise RuntimeError('Raw guard: no stems with matching names in both '
                               'sets to compare — cannot verify FX bypass.')
        differs = 0
        for name in shared:
            if self._pcm_fingerprint(wet[name]) != self._pcm_fingerprint(raw[name]):
                differs += 1
        if differs == 0:
            raise RuntimeError('Raw guard: 02_Raw is identical to 01_With_FX on '
                               'every shared stem — FX were NOT bypassed. Not shipping.')
        print(f'[Exporter] Raw guard OK: {differs}/{len(shared)} shared stems differ.')

    @staticmethod
    def _pcm_fingerprint(wav_path):
        """Hash ONLY the WAV's audio `data` chunk (hand-parsed RIFF, so it works
        on 32-bit-float files the stdlib `wave` module rejects, and ignores
        metadata/timestamps that would cause a false 'differs')."""
        with open(wav_path, 'rb') as f:
            riff = f.read(12)
            if len(riff) < 12 or riff[0:4] != b'RIFF' or riff[8:12] != b'WAVE':
                # Not a RIFF/WAVE we understand — fall back to whole-file hash.
                f.seek(0)
                return hashlib.sha256(f.read()).hexdigest()
            h = hashlib.sha256()
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                cid, size = hdr[0:4], struct.unpack('<I', hdr[4:8])[0]
                if cid == b'data':
                    remaining = size
                    while remaining > 0:
                        chunk = f.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        h.update(chunk)
                        remaining -= len(chunk)
                    break
                f.seek(size + (size & 1), 1)  # chunks are word-aligned
            return h.hexdigest()
