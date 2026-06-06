# Session handoff — 2026-06-06

Branch: **`logic-rend-v1`** (a `logic-renderer-v*` version branch). Nothing has
been committed — the user pushes/commits manually. Do not create/switch/push
branches.

This session took the Logic renderer from "scaffold" through a **working wet
(`01_With_FX`) export end-to-end**, and then started — but did **not finish** — an
export-range fix. Read this top to bottom before continuing.

Companion files in this folder: `DISCOVERY.md` (UI ground truth), `probes.sh`
(reusable read-only AX probes).

---

## 1. What works now ✅

### Phase 0 — scaffold verified, FL labels fixed
- `npm install` + `pip3 install -r requirements.txt` clean.
- Backend alone: `python3 python/server.py` → `curl localhost:5123/health` ok.
- `npm start` boots the window, spawns the backend, lifecycle tears down cleanly.
- Removed 4 leftover **"FL Studio" / `.flp`** strings in the reused UI
  (`electron/renderer/app.js` ×3, `electron/renderer/index.html` ×1). Grep confirms
  none remain.

### Phase 1 — Logic driver implemented (`python/logic_render.py`)
All element-level System Events (no screenshots, no coordinate clicks). Verified
against the live install:
- **`resolve_project_path()`** — §11 resolver for package vs Folder-style
  projects. Unit-tested 7 cases (package, folder+marker, single-logicx folder,
  empty→error, two-logicx→error, nonexistent→error, trailing slash). All pass.
  Wired into `stem_exporter.run()` and `server.py /parse`.
- **`detect_logic_process_name()`** — FIXED a real bug: the old substring check
  matched `"Logic Pro"` inside `"Logic Pro X"` and returned the wrong name, after
  which `pgrep -x` reported Logic as dead. Now exact-match, most-specific first.
- **`wait_for_logic_ready()`** — polls for a named `AXStandardWindow` with no
  sheet, then a short settle (adaptive; floor = settle, ceiling = timeout).
- **`export_stems()`** — opens `File ▸ Export ▸ All Tracks as Audio Files…`,
  sets destination via ⌘⇧G, Format→WAVE, Bypass→param (reads AXValue, clicks only
  if differs), Normalize→Off, clicks `Export`; handles a stray Replace sheet.
- **`wait_for_export_complete()`** — WAV file-size stability (N identical
  snapshots); raises `LogicCrashedError` if Logic exits mid-wait.
- **`quit_logic()`** — ⌘Q → "Don't Save" sheet handling (straight + curly
  apostrophe + "Delete") → escalate to `tell app quit` → `pkill` → `pkill -9`.
- Electron: `main.js` picker now accepts a `.logicx` package OR a project folder
  (`openFile`+`openDirectory`); `app.js` drop accepts folders too (backend
  resolves/validates).

### Wet pass — GREEN end-to-end (pre-range-fix)
Ran `tools/run_wet_export.py "~/Desktop/logic test.logicx" "/tmp/stemexport_out"`:
- **4 stems** → `01_With_FX/`, `_validate_set` OK (≥2), **zip 14.4 MB** created.
- Logic quit cleanly (not alive after).
- **Project NOT modified**: `…/logic test.logicx/Alternatives/000/ProjectData`
  mtime was **19:24:05**, the export ran ~**20:22** → on-disk project untouched.
- Timings: ready **3.3 s**, export+bounce **14.5 s**, quit **33.6 s** (slow — see
  Risks), total **61.9 s**.

### §6a stack behavior — observed
Fixture `logic test` has **4 top-level tracks**:
1. `Sum 1` — a **Summing Stack**
2. `breaks_toploop_135_bitlevel`
3. `DS_BF_130_bass_reese_hipnose_Cmin`
4. `FSS_FDE2_128_synth_stab_time_Cmin`

Export produced **4 WAVs**, including a single `Sum 1_1.wav` → **a Summing Stack
exports as ONE combined file** (confirms §6a). Stem count (4) == top-level track
count (4). No standalone Folder Stack in this fixture to test that half.

---

## 2. What's in progress / BLOCKED ⛔ — the export-range fix

**Why:** On the user's first run the stems were wrong because the export
inherited whatever transport/cycle/playhead state the project opened with ("the
cursor was not at the beginning"). `export_stems()` currently does nothing to the
transport. The "Trim Silence" pop-up (default `Trim Silence at File End`) is also
never set.

**User's requested approach** (approved plan —
`~/.claude/plans/there-was-a-problem-federated-bachman.md`), do this before each
export, NO `.logicx` parsing:
1. Press **Return** → playhead to start.
2. Read **Cycle** state:
   - Cycle **OFF** → `⌘A` then **"Set Locators by Regions"** (span first→last clip).
   - Cycle **ON** → keep the existing loop range.

**Blockers found during live discovery (this is where we stopped):**
- ❌ **"Set Locators by Regions" does not exist** in this Logic. Closest:
  `Navigate ▸ Set Locators by Selection and Enable Cycle` and
  `…Set Rounded Locators by Selection and Enable Cycle` — **both ENABLE cycle**.
- ❌ **Cycle on/off state is NOT readable via accessibility on this install:**
  - No transport buttons (Play/Cycle/Record) appear anywhere in the AX tree.
  - No "Cycle" toggle menu item carries a checkmark (`AXMenuItemMarkChar`).
  - Searching every window's `entire contents` by name/description/help for
    "Cycle" returns **nothing**. The Tracks window has **0 toolbars, 3 groups**;
    the control-bar transport cluster simply doesn't publish per-button AX.

So the "read Cycle state and branch" design **cannot be implemented as written**
until we find a cycle-state signal or change the approach. **No range-fix code has
been written yet** — only investigation.

---

## 3. Recommended next steps (for the range fix)

1. **Clarify the actual first-run symptom with the user** (decides everything):
   were the bad stems *truncated*, *offset / leading silence*, or *wrong length*?
   It's possible **pressing Return alone** (playhead to start) already fixes it and
   the locator/cycle dance is unnecessary.
2. **Test whether `All Tracks as Audio Files` even honors the cycle/locators.**
   Set locators to a sub-range, export, and see if stems shorten. If the export
   always uses full project length, the range fix reduces to "playhead → start"
   (+ maybe the silence pop-up) and the cycle branch is moot.
3. **If cycle state is genuinely needed**, options to evaluate:
   - Re-probe for a cycle indicator (the LCD/ruler `AXValueIndicator`, or enabling
     an accessible control-bar layout). May not exist.
   - Deterministic alternative: `⌘A` + `Set Locators by Selection and Enable
     Cycle` forces a full-song cycle — but this **overwrites an existing user
     loop**, violating "keep loop if Cycle ON". Only acceptable if we decide stems
     are always full-song.
4. **Decide the "Trim Silence" pop-up.** For aligned, full-length stems it likely
   should be set to **"No Change"** (the driver currently leaves it at
   `Trim Silence at File End`). Enumerate that pop-up's options (it's pop-up #2 in
   the dialog; `probes.sh popups`) and set it in `export_stems()`.
5. Implement `_prepare_export_range()` accordingly, call it at the top of
   `export_stems()`, then re-run `tools/run_wet_export.py` and verify each stem
   starts at bar 1 with full song length (parse WAV durations; all equal).

---

## 4. Files touched this session

**Modified**
- `python/logic_render.py` — major: resolver, process-name fix, all bridge
  methods implemented. (Range fix NOT added.)
- `python/stem_exporter.py` — import + call `resolve_project_path` in `run()`.
- `python/server.py` — `/parse` resolves + validates package/folder.
- `electron/main.js` — picker accepts folders.
- `electron/renderer/app.js` — drop accepts folders; FL→Logic labels.
- `electron/renderer/index.html` — placeholder label.

**Created**
- `docs/2026-06-06/DISCOVERY.md`, `docs/2026-06-06/probes.sh`
- `docs/2026-06-06/HANDOFF.md` (this file)
- `tools/run_wet_export.py` — wet-only Phase-1 verification harness (does NOT run
  the Raw pass or the T11 guard; those are the next prompt).

**Not started**
- Raw pass (`bypass_fx=True` → `03_Raw`) + T11 `_assert_raw_differs` on real audio
  (next prompt). Note: `export_stems(bypass_fx=True)` is already coded — only the
  full two-pass run + guard remain to be exercised.
- The export-range fix (§2/§3 above).

---

## 5. Environment notes / gotchas
- App bundle: `/Applications/Logic Pro X.app`; process name **`Logic Pro X`**.
- The sandboxed Bash tool **cannot read `~/Desktop`** (TCC "Operation not
  permitted") — but `osascript`/System Events and `python3` both can, so the
  driver path works. Run shell probes with sandbox disabled when they touch the
  Desktop or drive Logic.
- `quit_logic` took **33.6 s** in the wet run (likely a Save-prompt sheet + the
  escalation ladder). Functional but slow — worth tightening (clear the sheet
  faster / shorten the polite-quit window) when next in the file.
- **Current Logic state:** I left **Logic Pro X OPEN** with `logic test` (reopened
  during range-fix probing; unsaved but unmodified — safe to ⌘Q → Don't Save).
- Real Folder-style fixture `~/Desktop/logic test folder` does **not** exist;
  resolver was unit-tested synthetically. Ask the user for a folder-style fixture
  to test that path live.
