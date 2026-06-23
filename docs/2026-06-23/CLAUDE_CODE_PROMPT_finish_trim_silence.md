# Claude Code prompt — finish the Logic renderer (Trim Silence range fix + hardening)

> Paste everything below the line into Claude Code, run on the real Mac with Logic installed.

---

You are finishing the Logic Pro stem renderer. Read `CLAUDE.md`,
`docs/CLAUDE_CODE_START_HERE.md`, and the full June-10 handoff
`docs/2026-06-10/HANDOFF.md` + `docs/2026-06-10/DISCOVERY_range.md` before touching code.
The export-range mystery is already solved; your job is to implement the agreed fix and
take Phase 1 to "first green". **The product owner has decided: the export range is
hardcoded to `Trim Silence at File End` — no UI toggle.**

## Branch discipline (hard rules — do not violate)
- First, CONFIRM the active branch is a `logic-rend-v*` / `logic-renderer-v*` branch and
  print it. Do **not** create, switch, or delete branches. **Never `git push`.**
- Do **not** `git add`/`git commit` unless I explicitly ask. Leave the working tree dirty
  for me to review and commit/push myself.

## Constraints (unchanged, non-negotiable)
- Drive Logic by **accessible UI elements** (System Events) only — no Screen Recording,
  no coordinate/pixel clicks, no Finder automation.
- Render at the project's **native sample rate**. **Never save** the project; always quit
  in `try/finally`.
- Reuse the Electron UI 100% — do not edit `electron/renderer/*`.

## Task 1 — Set the export range (dialog pop-up #2) in `export_stems()`
In `python/logic_render.py`:
1. Add a module constant next to `FORMAT_OPTIONS` / `NORMALIZE_OPTIONS`:
   `RANGE_OPTIONS = {'Trim Silence at File End', 'Export Cycle Range Only', 'Extend File Length to Project End'}`
   and `DEFAULT_RANGE_MODE = 'Trim Silence at File End'`.
2. In the export AppleScript block in `export_stems()`, **before** clicking "Export",
   set the range pop-up to `DEFAULT_RANGE_MODE` using the same robust value-membership
   pattern already used for Format/Normalize (read value, click only if it differs):
   iterate `every pop up button of w`, match the one whose current value is in
   `RANGE_OPTIONS`, and if it isn't already `Trim Silence at File End`, open it and pick
   that item. Prefer value-membership over positional indexing; the discovery harness used
   `pop up button 2 of w` (see `tools/range_discovery.py` `export_with_range_mode`) — keep
   that as a documented fallback in a comment if value-membership proves ambiguous.
3. This is the root-cause fix: today `export_stems()` never sets pop-up #2, so it inherits
   Logic's sticky last value (e.g. `Export Cycle Range Only`) -> "stems start from the
   middle". Setting it explicitly every run kills that bug.

## Task 2 — Fold in the conflict-sheet dismissal
The "Key Command Assignment Conflicts" modal (buttons `Show Conflicts` / `Ignore`) can
block the main window. The working routine lives only in the discovery harness right now
(`tools/range_discovery.py` -> `dismiss_conflicts()`).
1. Add a `_dismiss_conflict_sheet(self)` method to `LogicRenderBridge`, mirroring the
   existing `_dismiss_replace_sheet` (best-effort, non-fatal, wrapped in try/except).
   It must click any button named `Ignore` across both `windows` and their `sheets`.
2. Call it defensively **right before** opening the export menu and **right after** the
   dialog is confirmed open (`_wait_for_open_dialog`).

## Task 3 — Real wet+raw verification (Phase 1 "first green")
Using a real multitrack `.logicx` fixture (>=2 tracks), run the full
`StemExporter` two-pass flow (it already does Pass 1 `01_With_FX` bypass off -> Pass 2
`03_Raw` bypass on, plus the T11 `_assert_raw_differs` guard). Confirm:
- `01_With_FX/` and `03_Raw/` each contain one WAV per track (>=2), zip is created.
- All stems in a set **start at bar 1** and align; note lengths (Trim Silence trims each
  file at its own content end — unequal lengths across staggered tracks are acceptable as
  long as starts align). Verify on a **staggered-end** project if you can build/find one.
- `03_Raw` differs in PCM from `01_With_FX` on at least one stem (T11 passes).
- Logic quit cleanly (Don't Save); the `.logicx` ProjectData mtime is **byte-identical**
  before/after (project untouched).
- Native sample rate preserved (don't set bit depth / SR in the dialog).

## Task 4 — Hardening (PROMPT 3)
- Crash/retry paths exercised (`LogicCrashedError`, `_run_pass_with_retry`,
  `_cleanup_stale_wavs` between passes).
- `dismiss_macos_crash_reporter` and both dismissal helpers are non-fatal.
- Stale-lock / dialog-not-open / Logic-died errors fail loudly with clear messages.

## Out of scope (do NOT start)
- The fully-headless / zero-focus-grab render (route 1 AX value-setting vs route 2 VM) —
  it's flagged in the June-10 handoff as a dedicated future phase.
- `02_With_Returns_And_Master` — later phase.
- Any UI redesign or a Full-song/Cycle range toggle.

## Definition of done
Range pop-up forced to `Trim Silence at File End` every export; conflict sheet auto-
dismissed; a real fixture produces `01_With_FX` + `03_Raw` (>=2 WAVs each, bar-1 aligned),
zip built, T11 green, Logic quit clean, project byte-unchanged. Report results, leave the
tree dirty, and tell me exactly what to review before I commit and push.
