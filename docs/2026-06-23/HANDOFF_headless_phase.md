# Handoff — START OF THE HEADLESS PHASE (for a fresh chat / new session)

**Read this first if you're picking the project up cold.** It tells you exactly
where the project is and how to start the next phase (fully-headless / zero
focus-grab render) the right way. Companion docs:
`docs/2026-06-23/HANDOFF.md` (Phase 1 completion), `docs/2026-06-10/HANDOFF.md`
+ `docs/2026-06-10/DISCOVERY_range.md` (export-range ground truth), `CLAUDE.md`
(rules), `docs/CLAUDE_CODE_START_HERE.md`.

---

## 0. What this project is (one paragraph)

macOS **Logic Pro** stem renderer. Electron UI → Flask backend → stem export →
zip. Deliverable = two stem sets per project: `01_With_FX` (plugins on) and
`03_Raw` (plugins bypassed). Logic is driven entirely by macOS **accessibility
automation** (AppleScript / System Events) — there is NO Logic scripting API. The
one net-new file is `python/logic_render.py`; everything else (UI, Flask server,
`StemExporter` orchestrator, safety guards) is reused from the FL/Ableton
renderers. `02_With_Returns_And_Master` is a documented later phase.

**Hard constraints (never violate):** reuse the Electron UI 100% (don't redesign
`electron/renderer/*`); drive Logic by accessible UI **elements** only — no Screen
Recording, no coordinate/pixel clicks, no Finder automation; render at the
project's **native sample rate**; **never save** the project (always quit in
try/finally); background-friendly.

---

## 1. Current status — Phase 1 is DONE and GREEN ✅

The core renderer works and the original "stems start from the middle" bug is
fixed at the root. As of 2026-06-23:

- `export_stems()` now explicitly sets the export dialog's **range pop-up (#2)** to
  `Trim Silence at File End` on every run (value-membership pattern, same as
  Format/Normalize), so it can never inherit Logic's sticky last value. Product
  owner decided: hardcoded, **no UI toggle**.
- `_dismiss_conflict_sheet()` added (clicks `Ignore` on the "Key Command Assignment
  Conflicts" modal), called before opening the Export menu and after the dialog
  opens.
- Live-verified on `~/Desktop/logic test.logicx` (4 equal-length tracks): both sets
  = 4 WAVs each, all bar-1 aligned, native 44.1 kHz, T11 raw-guard green (3/4 stems
  differ in PCM), project byte-identical before/after, Logic quit clean, zip built.
- Hardening (retry / crash paths / non-fatal dismissals) reviewed green.

Committed locally as `443ac93 "Force export range to Trim Silence + dismiss
conflict sheet"` on branch `logic-rend-v1`.

### Open loose ends from Phase 1 (do before / independent of headless)
1. **PUSH:** `logic-rend-v1` is **1 commit ahead of `origin/main`** — Phase 1 is
   committed locally but NOT on GitHub yet. The user pushes manually.
2. **Staggered-end verification (optional, unverified):** Trim Silence was only
   tested on an equal-length project. The unequal-end case (tracks ending at
   different bars — the normal case for real songs) is unconfirmed. It's *probably*
   fine (Trim Silence trims only the trailing tail, so every stem still starts at
   bar 1; only lengths differ). To close it: save a ≥2-track project with staggered
   ends as `~/Desktop/staggered test.logicx` and run
   `python3 tools/run_full_export.py "<path>"` (sandbox disabled). Fallback if it
   ever misbehaves: switch pop-up #2 to `Extend File Length to Project End` (equal
   length, but over-pads to the project-end marker).

---

## 2. Branch discipline (applies to the assistant, every session)

- The USER creates the next version branch manually in Terminal
  (`logic-rend-v2`) and pushes. The assistant only **confirms** the active branch.
- The assistant must NOT create/switch/delete branches and must **never
  `git push`**. It may `git add`/`git commit` only when explicitly asked.
- **For the headless phase the user should `git checkout -b logic-rend-v2` first**
  (after pushing v1), so headless work lands on its own branch.

---

## 3. THE HEADLESS PHASE — what it is and how to start

### Why it exists
Today the render is already **background-friendly**: no mouse, silent (offline
bounce), Logic can be minimized during the heavy lifting. The ONLY times it grabs
foreground focus are two brief moments — the **export trigger** and the **quit** (a
few seconds each). The grab exists because the driver *types* (macOS
`keystroke`/`key code` always go to the frontmost app) in two places:
1. the destination path — `⌘⇧G` "Go to Folder" then types the path;
2. (only if used) bar positions — typing into the modal `Go To ▸ Position…`.

So during those few seconds Logic must be frontmost and the user must not be typing
elsewhere. **If "the client cannot have focus pulled even for two seconds" becomes a
real requirement, that's this phase.**

### Two routes (start with route 1 — it's cheap and decides everything)

**Route 1 — kill the keystrokes via direct AX value-setting (CHEAP, ~10 min probe
first).** `set value of text field …` does NOT require the app to be frontmost.
The question: can the driver set, via AX value (no keystrokes, no focus):
  - (a) the export dialog's **destination/path** field, and
  - (b) the modal **Go-To position** field (only needed if playhead moves are ever
    required — Phase 1 doesn't need them).
If (a) is settable this way, the export trigger no longer needs focus → headless is
essentially solved for the export path. **Run a discovery probe BEFORE building.**

⚠️ Known caution from 2026-06-10 discovery: Logic's **control-bar LCD
locator/position fields are `AXSlider`s with encoded values — NOT settable.** BUT
the **modal dialog** text fields may differ — verify on the real export-dialog path
field and the modal Go-To field; do NOT assume they behave like the control bar.

**Route 2 — separate macOS login session / VM per DAW (HEAVY).** Logic runs in its
own login session and never shares the client's foreground at all. Only fall back to
this if route 1's modal fields are also slider-encoded / not settable. Scoped in
`docs/Logic_Renderer_Handoff_v1.md` PROMPT 5.

### First action for this phase — a discovery probe, not a build
Open the export dialog on a real project and dump/test the path field:
- Enumerate the dialog's text fields; identify the destination/path field.
- Try `set value of <that text field> to "<a real folder>"` with Logic NOT
  frontmost; confirm the dialog's destination actually updates (and that Export then
  writes there).
- Report: is the path field AX-settable without focus? (yes → route 1 viable; no →
  evaluate route 2). Touch no production code until this is answered.

---

## 4. Key ground truth / gotchas carried forward (still true)
- App bundle `/Applications/Logic Pro X.app`; process name **`Logic Pro X`** (exact
  string matters for `pgrep -x` / System Events).
- Export menu: `File ▸ Export ▸ "All Tracks as Audio Files…"` (real ellipsis).
  Dialog window title is **"Open"** (a Cocoa save panel). Config pop-ups have NO
  AXTitle — identified by value-membership in their option sets
  (`FORMAT_OPTIONS` / `NORMALIZE_OPTIONS` / `RANGE_OPTIONS`).
- The **sandboxed Bash tool cannot read `~/Desktop` or drive Logic** — run those
  steps with the sandbox **disabled** (osascript / System Events + python3 work).
- The **Tracks canvas is opaque to AX** (no named track/region elements); editing
  focus can't be grabbed; `⌘A`, `Return`, `Go To ▸ Left/Right Locator` are no-ops
  without it. None of this is needed for the export — the range is the accessible
  export-dialog pop-up #2.
- Reserved AppleScript words that bit us as variable names: `before`, `log`.
- Always leave Logic **QUIT (Don't Save)**; verify the `.logicx` ProjectData is
  byte-identical before/after.

---

## 5. The one file you touch
`python/logic_render.py` — the Logic driver. `python/stem_exporter.py` (two-pass
orchestrator + T11 raw guard), the Electron UI, and the Flask server are reused and
should not be redesigned. Verification harnesses live in `tools/`
(`run_full_export.py` = full two-pass; `run_wet_export.py` = wet only;
`range_discovery.py` = the 2026-06-10 discovery harness, contains a working
`goto_position` that types into the modal — useful reference for the route-1 probe).

---

## 6. Out of scope for the headless phase (do NOT start without sign-off)
- `02_With_Returns_And_Master` (later phase).
- Any UI redesign or a Full-song/Cycle-range toggle.
- Don't bolt headless onto Phase 1 as a quick hack — design it; route 1 probe first.
