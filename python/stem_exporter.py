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
import re
import shutil
import struct
import time
import zipfile

from logic_render import (
    LogicRenderBridge,
    LogicCrashedError,
    RenderCancelled,
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
    def __init__(self, file_path, output_folder, state, headless=True,
                 cancel_event=None):
        self.file_path = file_path
        self.output_folder = output_folder
        self.state = state
        # headless (default on): run the whole export invisibly/backgrounded — no
        # focus steal, cursor never moves (Tier 0, docs/2026-06-28/). Pass
        # headless=False to fall back to the legacy frontmost+keystroke path.
        self.headless = headless
        # Cooperative cancel (threading.Event from /export/cancel). Checked between
        # steps here and once per tick inside the bridge's long waits.
        self.cancel_event = cancel_event

    def _check_cancel(self, where):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RenderCancelled(f'cancelled {where}')

    # ── state helpers ────────────────────────────────────────────────────────
    def _set_status(self, title, sub='', progress=None):
        self.state['status_title'] = title
        self.state['status_sub'] = sub
        if progress is not None:
            self.state['progress'] = progress
        print(f'[Exporter] {title} — {sub}')

    def _warn(self, w):
        """Record one warning dict {'stage', 'message', ...} — LIVE: it lands in
        the shared state immediately (the UI polls /export/progress every second),
        not bundled at render end. Owner design 2026-09-10: warnings surface AS
        THEY BECOME KNOWABLE, while cancelling is still cheap."""
        self._warnings.append(w)
        self.state['warnings'] = list(self._warnings)
        print(f'[Exporter] WARNING: {w["message"]}', flush=True)

    # ── main entrypoint ──────────────────────────────────────────────────────
    def run(self):
        # Resolve package- vs folder-style projects to the inner .logicx (§11) so
        # both the launch and the project-name derivation use the real project.
        self.file_path = resolve_project_path(self.file_path)
        project_name = os.path.splitext(os.path.basename(self.file_path))[0]
        project_folder = os.path.join(self.output_folder, project_name)
        os.makedirs(project_folder, exist_ok=True)

        # Live warnings channel — filled via _warn as findings appear, mirrored
        # into shared state each time so the UI shows them mid-render.
        self._warnings = []
        self.state['warnings'] = []

        self._set_status('Launching Logic Pro…', 'Opening project', progress=5)
        bridge = LogicRenderBridge(headless=self.headless,
                                   cancel_event=self.cancel_event)
        bridge.launch(self.file_path)

        # ONE Logic session for BOTH passes. Inner try/finally guarantees a clean
        # quit; the outer except turns a user cancel into a tidy exit — Logic is
        # already quit by the finally, then the attempt's partial output is removed
        # and RenderCancelled propagates (its own outcome, not a failure).
        try:
            try:
                if not bridge.wait_for_logic_ready():
                    raise RuntimeError('Logic Pro did not finish loading in time.')

                # Clear any leftover macOS crash-reporter dialog so it can't steal focus.
                dismiss_macos_crash_reporter()

                self._check_cancel('before Pass 1')

                # Track states (owner decisions 2026-09-14): read every header's
                # mute/solo/name while Logic is idle. SOLO is cleared in-session
                # (never saved) — a lit solo silences stack/DMD tracks and Trim
                # Silence then erases them from the export entirely (the Sum 8 /
                # Eleven ghost). MUTED tracks are left out of the delivery after
                # each pass. Names also power the completeness check.
                self._set_status('Checking tracks…', 'Reading mute/solo state', progress=10)
                tracks = bridge.read_track_states()
                self._track_names = [t['name'] for t in tracks]
                self._muted_names = [t['name'] for t in tracks if t['muted']]
                soloed = [t['name'] for t in tracks if t['soloed']]
                if soloed:
                    cleared, still = bridge.clear_solos(tracks)
                    shown = ', '.join(soloed[:5]) + ('…' if len(soloed) > 5 else '')
                    if still:
                        self._warn({'stage': 'solo', 'message':
                            f'Solo is active on {", ".join(still[:5])} and could NOT be '
                            f'cleared — stack/DMD tracks may be dropped from this export. '
                            f'Un-solo and save, then re-render.'})
                    else:
                        self._warn({'stage': 'solo', 'message':
                            f'Solo was active on {shown} — cleared for the export '
                            f'(Solo Off for All); your project file is untouched.'})
                if self._muted_names:
                    shown = ', '.join(self._muted_names[:5]) + ('…' if len(self._muted_names) > 5 else '')
                    self._warn({'stage': 'muted', 'message':
                        f'{len(self._muted_names)} muted track(s) will be left out of '
                        f'the delivery: {shown}.'})
                if tracks:
                    print(f'[Exporter] tracks: {len(tracks)} read, '
                          f'{len(self._muted_names)} muted, {len(soloed)} solo\'d.', flush=True)

                # Pass 1 — 01_With_FX (Bypass Effect Plug-ins OFF → wet)
                self._set_status('Pass 1/2 — With FX',
                                 'Exporting all tracks with plugins', progress=15)
                self._run_pass_with_retry(bridge, project_folder, project_name,
                                          bypass_fx=False, pass_label='Pass 1/2 — With FX')
                sort_wavs_into_subfolder(
                    src_folder=project_folder, subfolder_name='01_With_FX',
                    exclude_group_wavs=False, group_track_names=[],
                )
                self._exclude_muted(project_folder, '01_With_FX', self._muted_names)
                self._validate_set(project_folder, '01_With_FX')
                self.state['progress'] = 50
                for w in self._completeness_warnings(project_folder, '01_With_FX',
                                                     self._track_names, self._muted_names):
                    self._warn(w)
                # Halfway checkpoint (owner design 2026-09-10): silent stems are
                # knowable NOW — surface them while cancelling still saves Pass 2
                # and the packaging. Warning only, never a failure.
                for w in self._silence_warnings(project_folder, '01_With_FX'):
                    self._warn(w)

                self._check_cancel('between the passes')
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
                self._exclude_muted(project_folder, '02_Raw', self._muted_names)
                self._validate_set(project_folder, '02_Raw')
                self.state['progress'] = 85
                # Second checkpoint: Raw-set silence + PASS SYMMETRY (Pass 1 is
                # the prediction for Pass 2 — a count/name mismatch is a
                # Sum-8-shaped anomaly, caught with no parser needed).
                for w in self._silence_warnings(project_folder, '02_Raw'):
                    self._warn(w)
                for w in self._pass_symmetry_warnings(project_folder):
                    self._warn(w)
            finally:
                self._set_status('Closing Logic Pro…', 'Quitting cleanly')
                t_quit = time.time()
                try:
                    bridge.quit_logic()
                except Exception as e:
                    print(f'[Exporter] WARNING: clean quit failed: {e}')
                print(f'[Exporter] Logic quit in {time.time()-t_quit:.1f}s.')
            # Last cancel window: after the passes, before packaging begins.
            self._check_cancel('before packaging')
        except RenderCancelled:
            self._cleanup_cancelled(project_folder)
            raise

        # ── Post-render staged-success ladder ─────────────────────────────────
        # BORDER: everything below here is past the point where the deliverable
        # (the stems) provably exists — both passes rendered and each _validate_set
        # passed above (a <2-stem set already raised → hard failure, correctly
        # BELOW the border). From here nothing FAILS the render: problems become
        # warnings (via the LIVE _warn channel) and the flow continues. Outcome =
        # 'ok' | 'ok_warnings'; genuine failures only ever come from exceptions
        # raised above the border.

        # ② Raw-differs — quality flag, NO LONGER fatal. Identical passes ⇒ either
        # the project has no effects (fine) or FX bypass didn't take (a real bug we
        # can't yet distinguish without a project parser). Warn and continue.
        self._set_status('Verifying raw pass…', 'Confirming FX were bypassed', progress=88)
        for w in self._raw_differs_warnings(project_folder):
            self._warn(w)

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
            self._warn({'stage': 'zip', 'message':
                f'Stems rendered, but zipping failed ({e}). The stems are in the '
                f'project folder.', 'path': project_folder})
            return self._finish('ok_warnings', self._warnings, sets, None, project_folder)

        # ④ Verify the zip is a COMPLETE, valid copy BEFORE deleting the source.
        # If verify fails we SKIP the delete (folder is the only other copy), so
        # the un-zipped stems stay intact — success-with-warnings pointing at them.
        self._set_status('Verifying zip…', 'Confirming the archive is complete', progress=97)
        try:
            self._verify_zip(zip_path, sets)
        except Exception as e:
            self._warn({'stage': 'zip_verify', 'message':
                f'Stems rendered, but the zip could not be verified ({e}). The '
                f'un-zipped stems in the project folder are intact.',
                'path': project_folder})
            return self._finish('ok_warnings', self._warnings, sets, zip_path, project_folder)

        # ⑤ Verified → delete the source folder, leaving only <project>.zip.
        # Purely janitorial — never fails the render.
        self._set_status('Cleaning up…', 'Removing the un-zipped stem folder', progress=99)
        if not self._remove_folder_robust(project_folder):
            self._warn({'stage': 'cleanup', 'message':
                'Render complete and zipped. Could not remove the leftover stem '
                'folder — safe to delete by hand.', 'path': project_folder})

        status = 'ok_warnings' if self._warnings else 'ok'
        # Source folder gone (or left as a noted leftover); point "Open Folder" at
        # the folder that now holds the zip.
        return self._finish(status, self._warnings, sets, zip_path, self.output_folder)

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
        (seen live 2026-09-07 on a Seagate). Scrub and retry once; return True on
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

    def _cleanup_cancelled(self, project_folder):
        """After a user cancel (Logic already quit): remove everything this
        attempt created so no debris remains — loose WAVs in the render root,
        the partial 01_With_FX / 02_Raw sets, and the per-render folder itself
        if that leaves it empty. Only ever touches the per-render folder we
        created; never the user's output folder or any zip from a previous run."""
        removed = 0
        for w in glob.glob(os.path.join(project_folder, '*.wav')):
            try:
                os.remove(w)
                removed += 1
            except OSError:
                pass
        for sub in ('01_With_FX', '02_Raw'):
            d = os.path.join(project_folder, sub)
            if os.path.isdir(d):
                removed += len(glob.glob(os.path.join(d, '*.wav')))
                shutil.rmtree(d, ignore_errors=True)
        try:
            os.rmdir(project_folder)  # only succeeds if now empty — by design
        except OSError:
            pass
        print(f'[Exporter] Cancelled — cleaned up {removed} partial WAV(s); '
              f'no debris left behind.', flush=True)

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

    # ── track-state handling (mute / solo / completeness), parser-free ───────
    @staticmethod
    def _file_matches_track(filename, track_name):
        """Does an exported WAV belong to `track_name`? Logic names exports
        '<track>_<n>.wav' (and our Raw pass appends RAW_FILENAME_SUFFIX):
        strip .wav, the raw suffix, then ONE trailing _<digits>, and compare."""
        base, _ = os.path.splitext(filename)
        if base.endswith(RAW_FILENAME_SUFFIX):
            base = base[:-len(RAW_FILENAME_SUFFIX)]
        base = re.sub(r'_\d+$', '', base)
        return base == track_name

    def _exclude_muted(self, project_folder, subfolder, muted_names):
        """Owner decision 2026-09-14: muted tracks are left OUT of the delivery.
        Logic's export ignores mute (renders them anyway), so remove their stems
        from the set after the sort. Returns the list of removed filenames."""
        removed = []
        for p in sorted(glob.glob(os.path.join(project_folder, subfolder, '*.wav'))):
            fn = os.path.basename(p)
            if any(self._file_matches_track(fn, t) for t in muted_names):
                try:
                    os.remove(p)
                    removed.append(fn)
                except OSError:
                    pass
        return removed

    def _completeness_warnings(self, project_folder, subfolder, track_names, muted_names):
        """Every non-muted track in the header list should have produced a stem.
        A track with no file = an EMPTY track (Logic exports only tracks with
        regions), a type its export skips (folder stack, VCA…), or a genuine
        drop (the Sum 8 / Eleven class). Informational, never fatal."""
        files = [os.path.basename(p)
                 for p in glob.glob(os.path.join(project_folder, subfolder, '*.wav'))]
        missing = [t for t in track_names
                   if t not in muted_names
                   and not any(self._file_matches_track(f, t) for f in files)]
        if not missing:
            return []
        shown = ', '.join(missing[:5]) + ('…' if len(missing) > 5 else '')
        return [{'stage': f'completeness_{subfolder}',
                 'message': f'{len(missing)} track(s) produced no stem ({shown}) — '
                            f'empty tracks and folder stacks/VCAs never export; '
                            f'anything else here deserves a look.'}]

    # ── live mid-render checks (parser-free; warnings, never failures) ────────
    @staticmethod
    def _is_silent_wav(wav_path):
        """True if the WAV's data chunk is entirely zero bytes (digital silence —
        what Logic bounces for an empty/muted track). Hand-parsed RIFF like
        _pcm_fingerprint; early-exits on the first non-zero byte. Unreadable or
        non-RIFF files count as NOT silent (no false alarms)."""
        try:
            with open(wav_path, 'rb') as f:
                riff = f.read(12)
                if len(riff) < 12 or riff[0:4] != b'RIFF' or riff[8:12] != b'WAVE':
                    return False
                while True:
                    hdr = f.read(8)
                    if len(hdr) < 8:
                        return True  # no data chunk found → nothing non-zero seen
                    cid, size = hdr[0:4], struct.unpack('<I', hdr[4:8])[0]
                    if cid == b'data':
                        remaining = size
                        while remaining > 0:
                            chunk = f.read(min(1 << 20, remaining))
                            if not chunk:
                                return True
                            if any(chunk):
                                return False
                            remaining -= len(chunk)
                        return True
                    f.seek(size + (size & 1), 1)
        except OSError:
            return False

    def _silence_warnings(self, project_folder, subfolder):
        """Scan one rendered set for all-silent stems. INFORMATIONAL without a
        project parser (we can't yet tell expected silence — an empty scratch
        track — from wrong silence); the point is the user sees it mid-render,
        while cancelling still saves time. Returns a list of warning dicts."""
        silent = [os.path.basename(p)
                  for p in sorted(glob.glob(os.path.join(project_folder, subfolder, '*.wav')))
                  if self._is_silent_wav(p)]
        if not silent:
            return []
        shown = ', '.join(silent[:5]) + ('…' if len(silent) > 5 else '')
        # NOTE (owner-observed 2026-09-14): Logic's per-track export IGNORES the
        # mute button — muted tracks bounce with full audio. So silence here
        # means an EMPTY track (no regions) or something genuinely wrong; mute
        # is never the explanation. (The reverse surprise — muted scrap shipping
        # WITH audio — is a parser-era pre-flight warning candidate.)
        return [{'stage': f'silence_{subfolder}',
                 'message': f'{subfolder}: {len(silent)} stem(s) rendered silent '
                            f'({shown}) — expected only for empty tracks; '
                            f'otherwise check before delivering.'}]

    def _pass_symmetry_warnings(self, project_folder):
        """Pass 2's stems should mirror Pass 1's names exactly (the _raw suffix
        aside) — Pass 1 IS the prediction for Pass 2, no parser needed. A
        mismatch is a Sum-8-shaped anomaly: Logic silently skipped or added a
        track between the passes. Returns a list of warning dicts."""
        wet = {os.path.basename(p)
               for p in glob.glob(os.path.join(project_folder, '01_With_FX', '*.wav'))}
        raw = set()
        for p in glob.glob(os.path.join(project_folder, '02_Raw', '*.wav')):
            base, ext = os.path.splitext(os.path.basename(p))
            if base.endswith(RAW_FILENAME_SUFFIX):
                base = base[:-len(RAW_FILENAME_SUFFIX)]
            raw.add(base + ext)
        missing = sorted(wet - raw)   # in With-FX, absent from Raw
        extra = sorted(raw - wet)     # in Raw, absent from With-FX
        out = []
        if missing:
            out.append({'stage': 'pass_symmetry',
                        'message': f'Raw pass is missing {len(missing)} stem(s) '
                                   f'that With-FX produced: {", ".join(missing[:5])}'
                                   f'{"…" if len(missing) > 5 else ""}'})
        if extra:
            out.append({'stage': 'pass_symmetry',
                        'message': f'Raw pass produced {len(extra)} stem(s) With-FX '
                                   f'did not: {", ".join(extra[:5])}'
                                   f'{"…" if len(extra) > 5 else ""}'})
        return out

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
