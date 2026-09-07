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

# Appended to every 02_Raw stem's filename during the post-pass sort
# ('Kick.wav' -> 'Kick_raw.wav'). The T11 raw-differs guard strips it again to
# pair raw stems with their 01_With_FX counterparts.
RAW_FILENAME_SUFFIX = '_raw'

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
                filename_suffix=RAW_FILENAME_SUFFIX,
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

        # ── Post-render staged-success ladder ─────────────────────────────────
        # BORDER: everything below here is past the point where the deliverable
        # (the stems) provably exists — both passes rendered and each _validate_set
        # passed above (a <2-stem set already raised → hard failure, correctly
        # BELOW the border). From here nothing FAILS the render: problems become
        # warnings and the flow continues. Outcome = 'ok' | 'ok_warnings'; genuine
        # failures only ever come from the exceptions raised above the border.
        warnings = []

        # ② Raw-differs — quality flag, NO LONGER fatal. Identical passes ⇒ either
        # the project has no effects (fine) or FX bypass didn't take (a real bug we
        # can't yet distinguish without a project parser). Warn and continue.
        self._set_status('Verifying raw pass…', 'Confirming FX were bypassed', progress=88)
        for w in self._raw_differs_warnings(project_folder):
            warnings.append(w)
            print(f'[Exporter] WARNING: {w["message"]}')

        sets = {
            '01_With_FX': sorted(glob.glob(os.path.join(project_folder, '01_With_FX', '*.wav'))),
            '02_Raw': sorted(glob.glob(os.path.join(project_folder, '02_Raw', '*.wav'))),
        }

        # ③ Zip. If it fails, the un-zipped stems ARE the deliverable — keep the
        # folder and report success-with-warnings pointing at it.
        self._set_status('Zipping…', 'Packaging the sets', progress=94)
        try:
            zip_path = zip_project_folder(project_folder)
        except Exception as e:
            warnings.append({'stage': 'zip', 'message':
                f'Stems rendered, but zipping failed ({e}). The stems are in the '
                f'project folder.', 'path': project_folder})
            print(f'[Exporter] WARNING: zipping failed: {e}')
            return self._finish('ok_warnings', warnings, sets, None, project_folder)

        # ④ Verify the zip is a COMPLETE, valid copy BEFORE deleting the source.
        # If verify fails we SKIP the delete (folder is the only other copy), so
        # the un-zipped stems stay intact — success-with-warnings pointing at them.
        self._set_status('Verifying zip…', 'Confirming the archive is complete', progress=97)
        try:
            self._verify_zip(zip_path, sets)
        except Exception as e:
            warnings.append({'stage': 'zip_verify', 'message':
                f'Stems rendered, but the zip could not be verified ({e}). The '
                f'un-zipped stems in the project folder are intact.',
                'path': project_folder})
            print(f'[Exporter] WARNING: zip verify failed: {e}')
            return self._finish('ok_warnings', warnings, sets, zip_path, project_folder)

        # ⑤ Verified → delete the source folder, leaving only <project>.zip.
        # Purely janitorial — never fails the render.
        self._set_status('Cleaning up…', 'Removing the un-zipped stem folder', progress=99)
        if not self._remove_folder_robust(project_folder):
            warnings.append({'stage': 'cleanup', 'message':
                'Render complete and zipped. Could not remove the leftover stem '
                'folder — safe to delete by hand.', 'path': project_folder})

        status = 'ok_warnings' if warnings else 'ok'
        # Source folder gone (or left as a noted leftover); point "Open Folder" at
        # the folder that now holds the zip.
        return self._finish(status, warnings, sets, zip_path, self.output_folder)

    def _finish(self, status, warnings, sets, zip_path, project_folder):
        """Assemble the render result and mirror it into shared state."""
        self.state['zip_path'] = zip_path
        self.state['project_folder'] = project_folder
        self.state['warnings'] = warnings
        self.state['status'] = status
        return {
            'status': status,
            'warnings': warnings,
            'project_folder': project_folder,
            'zip_path': zip_path,
            'sets': sets,
        }

    def _remove_folder_robust(self, folder):
        """Delete `folder`, tolerating Finder droppings (.DS_Store / ._*) that
        external (exFAT) volumes collect and that can re-appear between the
        recursive walk and the final rmdir → Errno 66 'Directory not empty'
        (seen live 2026-08-31 on a Seagate). Scrub and retry once; return True on
        success, False if it still won't go (caller downgrades to a warning)."""
        for attempt in (1, 2):
            try:
                shutil.rmtree(folder)
                print(f'[Exporter] Source folder removed after verified zip: {folder}')
                return True
            except OSError as e:
                if attempt == 2:
                    print(f'[Exporter] WARNING: could not remove {folder}: {e}')
                    return False
                for junk in (glob.glob(os.path.join(folder, '**', '.DS_Store'), recursive=True)
                             + glob.glob(os.path.join(folder, '**', '._*'), recursive=True)):
                    try:
                        os.remove(junk)
                    except OSError:
                        pass

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
    def _raw_differs_warnings(self, project_folder):
        """Compare 01_With_FX vs 02_Raw in PCM content. Returns a list of warning
        dicts (empty when the sets genuinely differ, proving 'Bypass Effect
        Plug-ins' took effect). NON-FATAL by design (staged-success border sits
        above this): the stems are the deliverable and already exist on disk, so a
        failed comparison is a caveat, not a reason to bin a good render.

        Two caveat cases, both surfaced as warnings:
          • no shared names  → can't verify bypass at all.
          • zero differ      → identical sets: EITHER the project has no effects
            (fine) OR bypass silently didn't take (a real bug). We can't tell which
            without a project parser, so we ask the user to eyeball one raw stem."""
        wet_dir = os.path.join(project_folder, '01_With_FX')
        raw_dir = os.path.join(project_folder, '02_Raw')
        wet = {os.path.basename(p): p for p in glob.glob(os.path.join(wet_dir, '*.wav'))}
        # Raw stems carry RAW_FILENAME_SUFFIX ('Kick_raw.wav'); strip it so they
        # pair with their 01_With_FX counterparts ('Kick.wav').
        raw = {}
        for p in glob.glob(os.path.join(raw_dir, '*.wav')):
            base, ext = os.path.splitext(os.path.basename(p))
            if base.endswith(RAW_FILENAME_SUFFIX):
                base = base[:-len(RAW_FILENAME_SUFFIX)]
            raw[base + ext] = p
        shared = sorted(set(wet) & set(raw))
        if not shared:
            return [{'stage': 'raw_guard', 'message':
                'Could not verify FX bypass: no matching stem names in both sets.'}]
        differs = sum(1 for n in shared
                      if self._pcm_fingerprint(wet[n]) != self._pcm_fingerprint(raw[n]))
        if differs == 0:
            return [{'stage': 'raw_guard', 'message':
                'The With-FX and Raw sets came out identical. Either this project '
                'has no effects (fine to ship) or FX bypass did not take — check '
                'one raw stem before delivering.'}]
        print(f'[Exporter] Raw guard OK: {differs}/{len(shared)} shared stems differ.')
        return []

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
