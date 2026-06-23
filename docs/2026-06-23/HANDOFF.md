# Session handoff — 2026-06-23

Branch: **`logic-rend-v1`** (a `logic-renderer-v*` version branch). Nothing
committed — the user commits/pushes manually. Do not create/switch/push branches.

This session implemented the agreed **export-range fix** + **conflict-sheet
dismissal**, added a full two-pass verification harness, and took Phase 1 to
**"first green"**. Spec executed: `docs/2026-06-23/CLAUDE_CODE_PROMPT_finish_trim_silence.md`
(Tasks 1–4). Builds directly on the 2026-06-10 discovery
(`docs/2026-06-10/HANDOFF.md` + `DISCOVERY_range.md`).

---

## 1. Headline result ✅

Phase 1 is **green** on the real machine. A real multitrack `.logicx` now exports
both stem sets, the raw guard passes, the zip builds, Logic quits clean, and the
project is left byte-identical.

The original "stems start from the middle" bug is **fixed at the root**:
`export_stems()` now sets the export dialog's range pop-up (#2) explicitly on every
run, so it can never inherit Logic's sticky last value.

---

## 2. What changed (working tree — left dirty for review)

### `python/logic_render.py` (the only production file touched)

**Task 1 — force the export range (root-cause fix).**
- New module constants next to `FORMAT_OPTIONS` / `NORMALIZE_OPTIONS`:
  ```python
  RANGE_OPTIONS = {'Trim Silence at File End', 'Export Cycle Range Only',
                   'Extend File Length to Project End'}
  DEFAULT_RANGE_MODE = 'Trim Silence at File End'
  ```
- In the export AppleScript block in `export_stems()`, **before** `click button
  "Export"`, a new range block sets pop-up #2 to `Trim Silence at File End` using
  the same robust **value-membership** pattern already used for Format/Normalize
  (read value, click only if it differs). The three option sets
  (format/normalize/range) are disjoint, so there is no cross-match. A comment
  documents the positional fallback (`pop up button 2 of w`, as used by
  `tools/range_discovery.py → export_with_range_mode`) if value-membership ever
  proves ambiguous.
- Product-owner decision honoured: **hardcoded to `Trim Silence at File End`, no UI
  toggle.**

**Task 2 — fold in the conflict-sheet dismissal.**
- New `_dismiss_conflict_sheet(self)` method on `LogicRenderBridge`, mirroring
  `_dismiss_replace_sheet` (best-effort, try/except, non-fatal). Clicks any button
  named `Ignore` across both `windows` and their `sheets` — same logic as
  `dismiss_conflicts()` in `tools/range_discovery.py`.
- Called defensively **right before** opening the Export menu and **right after**
  the dialog is confirmed open (`_wait_for_open_dialog`).

### `tools/run_full_export.py` (new — verification only, not wired into the app)

Runs the real two-pass orchestrator `StemExporter.run()` end to end (Pass 1
`01_With_FX` bypass off → Pass 2 `03_Raw` bypass on → T11 `_assert_raw_differs` →
zip), then prints a per-stem WAV report and a **project byte-unchanged** check
(snapshots every file in the `.logicx` bundle before/after; calls out `ProjectData`
specifically). Mirrors the wet-only `tools/run_wet_export.py`.

```
python3 tools/run_full_export.py "<project path>" ["<output folder>"]
```
Must run with the Bash sandbox **disabled** (the sandbox can't drive Logic / read
~/Desktop — see `docs/2026-06-10/HANDOFF.md` §6).

### NOT modified
- `python/stem_exporter.py`, `electron/renderer/*`, `python/one_click_helpers.py`,
  and all other production code — untouched.

---

## 3. Verification performed

### Live run — `~/Desktop/logic test.logicx` (equal-length, 4 tracks) → ALL GREEN
- `01_With_FX/` and `03_Raw/`: **4 WAVs each**, all bar-1 aligned, equal length
  **16.364 s** (= the discovery doc's full-song figure → confirms the range fix
  took effect), native **44.1 kHz** preserved, 24-bit.
- **T11 green:** Raw guard OK — **3/4** shared stems differ in PCM. The 4th
  (`Sum 1`) is byte-identical, expected for a track with no FX of its own.
- **Project untouched:** `Alternatives/000/ProjectData` byte-identical before/after;
  whole bundle unchanged. Logic quit cleanly (~3 s).
- Zip built (~26.8 MB). Total run ~81 s.

### Task 4 — hardening (pure-Python fault injection + static review) → green
- `_run_pass_with_retry` fault-injected (no Logic needed):
  1. Transient crash → `_cleanup_stale_wavs` + `relaunch` + `wait_for_logic_ready` +
     `dismiss_macos_crash_reporter`, then retries and succeeds.
  2. Persistent crash → burns `MAX_PASS_ATTEMPTS` (3) → raises a loud
     `RuntimeError('… Logic crashed 3× — giving up.')`.
  3. Non-crash error → propagates immediately, **not** retried.
- Static review confirmed: `dismiss_macos_crash_reporter`, `_dismiss_replace_sheet`,
  and the new `_dismiss_conflict_sheet` are all non-fatal (try/except, never raise);
  `_wait_for_open_dialog` failure distinguishes `LogicCrashedError` (process dead)
  from a loud `RuntimeError('Export dialog did not open.')`; `wait_for_export_complete`
  raises `LogicCrashedError` on death and a clear timeout `RuntimeError`; quit is
  always in `try/finally`.
- Note: there is **no stale-lock file path** in this driver — Logic's own project
  lock isn't something the code touches, so that hardening item is N/A here.

---

## 4. ⚠️ Open / unverified — staggered-end alignment

**Not verified this session.** Task 3 asks to confirm bar-1 alignment on a project
with **staggered track ends** (tracks ending at different bars). No such fixture
exists on disk, and a Logic project cannot be built programmatically (no scripting
API; AX can't create regions — see `DISCOVERY_range.md` §"accessibility limits").
The only fixture, `~/Desktop/logic test.logicx`, trims all stems to a *common* end
(equal length), so it cannot exercise unequal ends.

- **Why it's probably fine:** `Trim Silence at File End` trims only the **trailing**
  tail, never the head, so every stem still begins at the same absolute t=0 (bar 1)
  regardless of where its content ends. Starts align; only lengths may differ.
- **Fallback if it ever misbehaves** (`DISCOVERY_range.md` recommendation): switch
  pop-up #2 to `Extend File Length to Project End` — guarantees identical length but
  over-pads to the project-end marker (256 s in the test fixture).
- **To close it:** save a real ≥2-track project with tracks ending at different bars
  (e.g. `~/Desktop/staggered test.logicx`) and run
  `python3 tools/run_full_export.py "<path>"`. The harness already reports unequal
  lengths as acceptable and flags the bar-1-start reasoning.

---

## 5. Files this session

**Created**
- `docs/2026-06-23/HANDOFF.md` — this file.
- `tools/run_full_export.py` — full two-pass verification harness.

**Modified**
- `python/logic_render.py` — range fix (Task 1) + conflict-sheet dismissal (Task 2).

**Verification artifacts**
- WAV outputs + zip under `/tmp/stemexport_full/logic test/`. Safe to delete.

---

## 6. Environment notes / gotchas (carried forward, still true)
- App bundle `/Applications/Logic Pro X.app`; process **`Logic Pro X`**.
- The sandboxed Bash tool can't read `~/Desktop` or drive Logic — run those with the
  sandbox disabled (osascript / System Events + python3 work fine).
- Modal **"Key Command Assignment Conflicts"** sheet (`Show Conflicts` / `Ignore`)
  can block the main window — now auto-dismissed in `logic_render.py` (Task 2).
- Logic's **position/locator fields are `AXSlider`s with encoded values** — not
  readable/settable; `Return`, `⌘A`, `Go To ▸ Left/Right Locator` are no-ops without
  Tracks-pane focus, which AX can't grab. None of this is needed: the range is the
  accessible export-dialog pop-up #2.
- Reserved AppleScript words to avoid as variable names: `before`, `log`.
- **Current Logic state:** QUIT (Don't Save) at end of session; `~/Desktop/logic
  test.logicx` ProjectData byte-identical before/after. Safe.

---

## 7. Where to go next

1. **Close the staggered-end verification** (§4) when a staggered fixture exists.
2. **Out of scope this session (do NOT start without sign-off):**
   - Fully-headless / zero-focus-grab render (route 1 AX value-setting vs route 2 VM)
     — dedicated future phase, scoped in `docs/2026-06-10/HANDOFF.md` §top.
   - `02_With_Returns_And_Master` — later phase.
   - Any UI redesign or a Full-song/Cycle-range toggle.
3. **Review checklist before commit/push** (user does this manually):
   - `git diff python/logic_render.py` — range constants + block, `_dismiss_conflict_sheet`
     + its two call sites.
   - `tools/run_full_export.py` — new harness.
   - The ALL-GREEN console output / this handoff §3.
