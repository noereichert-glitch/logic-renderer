# Session handoff — 2026-06-10

Branch: **`logic-rend-v1`** (a `logic-renderer-v*` version branch). Nothing
committed — the user commits/pushes manually. Do not create/switch/push branches.

---

## ⚠️ SEE LATER — FUTURE PHASE: fully headless / zero focus-grab render

**Flagged for the next person (you) to design in, not bolt on.**

Today the renderer is: **no mouse** (element-level System Events only — no pixel
clicks), **silent** (Export/Bounce is an offline render, nothing plays out loud),
and **background during the heavy lifting** (the bounce + the file-size-watch wait
need no focus; Logic can be minimized while the client keeps working). The ONLY
focus grabs are the **brief export-trigger and the quit** — a few seconds each.

**Why the brief grab exists:** the driver *types* in two places — the destination
path (⌘⇧G "Go to Folder") and bar positions (the modal `Go To ▸ Position…`). macOS
`keystroke`/`key code` always go to the **frontmost** app, so Logic must be frontmost
for those few seconds, and the client must not be typing elsewhere at that instant.
This matches the current spec ("Logic minimized; only the brief export-trigger grabs
focus").

**If "client cannot have focus pulled even for two seconds" becomes a real
requirement, that's a dedicated phase. Two routes (also in Handoff_v1 PROMPT 5):**

1. **Kill the keystrokes → direct AX value-setting.** `set value of text field …`
   does NOT require the app to be frontmost. CHECK whether (a) the export dialog's
   destination/path field and (b) the position field are settable this way. If yes,
   the trigger no longer needs focus. NOTE from 2026-06-10 discovery: the control-bar
   LCD locator/position fields are `AXSlider`s with encoded values (NOT settable) —
   but the **modal dialog** text fields may differ; verify on the real fields, don't
   assume. This is the cheaper route and worth a discovery probe first.
2. **Separate macOS login session / VM per DAW.** Logic runs in its own session and
   never shares the client's foreground at all. Heaviest, fully isolates focus.
   Scoped in `docs/Logic_Renderer_Handoff_v1.md` PROMPT 5.

**Action when you pick this up:** start with route 1 (a 10-minute AX probe of the
export dialog's path field + the Go-To position field tells you if it's even
possible). Only fall to route 2 if the modal fields are also slider-encoded.

---

This session ran **PROMPT 1.5a (export-range DISCOVERY)** end to end and **solved
the export-range mystery**. It did **not** implement the fix — we stopped for the
product owner's go-ahead (two open decisions, §4). `logic_render.py` was **not
modified** this session.

Companion files in this folder: `DISCOVERY_range.md` (full ground truth + table),
`PLAN_export_range_fix.md` (the plan we executed PROMPT 1.5a from). New harness:
`tools/range_discovery.py`.

---

## 1. The headline result ✅

**The export range is controlled entirely by pop-up #2 in the export dialog**
(the "silence/range" pop-up) — NOT by the playhead and NOT by the project's cycle
state. This is none of the original Case A/B/C (those assumed the range came from
the project transport); it's closest to **Case A** (transport irrelevant) but with
a clean, **accessible dialog control** for the range.

Verified live (4 stems, equal length, native 44.1 kHz, `~/Desktop/logic test.logicx`):

| Pop-up #2 mode | Stem length | Meaning |
|---|---|---|
| `Trim Silence at File End` (default) | **16.364 s** | bar 1 → end of last clip = the "full song" spec |
| `Export Cycle Range Only` | **16.000 s** | the loop/cycle range exactly |
| `Extend File Length to Project End` | **256.000 s** | padded to the project-end marker |

- **Playhead does NOT matter** (T2): playhead moved to bar 5 (confirmed via the
  Go-To-Position readout) → byte-identical full-song export. The user's "cursor not
  at the beginning" hypothesis was a red herring.
- **Cycle is ignored in the default mode**: `Trim Silence` (16.364 s) is *longer*
  than the cycle (16.000 s), so it bounces full project content, not the loop.
  Cycle only matters under `Export Cycle Range Only`.

## 2. Root cause of the original mid-start bug ⛔→💡

`export_stems()` sets Format / Bypass / Normalize but **never sets pop-up #2**, so
it inherits Logic's *sticky* last value. If that sticky value was
`Export Cycle Range Only` and the project had a mid-project loop, every automated
run silently bounced that loop → "stems start from the middle." Matches the report.

## 3. Important secondary finding — the old plan's primitive is dead, but we don't need it

The original plan's transport primitive (⌘A → "Set Locators by Selection and Enable
Cycle" → toggle cycle → Return) is **NOT implementable on this install**:

- The **Tracks editing pane cannot be made first responder** via element-level AX.
  `Edit ▸ Select All` is disabled; `⌘A` selects nothing; `Return` (go-to-start) and
  `Navigate ▸ Go To ▸ Left/Right Locator` are **no-ops**; `set AXFocused` and
  `AXPress` on the canvas don't transfer editing focus (AXPress destabilised the
  Edit menu).
- The tracks/regions **canvas is opaque** to AX (no named track/region elements).
- **No Cycle button** in this control bar; control-bar/LCD locator & position fields
  are `AXSlider`s with encoded values — **not readable or settable**.

What DOES work without canvas focus: menu items that open dialogs, **typing into the
modal `Go To ▸ Position…`** (reliable playhead move — used to prove T2), **global
window keystrokes** (`x` toggled the Mixer), and the **export dialog's accessible
pop-ups** (Format / Normalize / **#2 range**). Because the range is pop-up #2, we
never touch any of the broken transport primitives. 🎉

## 4. Where to go next — DECISIONS NEEDED before implementing (PROMPT 1.5c)

Two open questions for the product owner (asked at end of session, not yet answered):

1. **Range default:** always `Trim Silence at File End` (full song; deterministic,
   accessible, kills the bug, matches "bar 1 → last clip"), **or** add the additive
   UI toggle now ("Export range: Full song / Cycle range" → maps to pop-up #2,
   PROMPT 1.5b option 2; flag for sign-off re: "reuse UI 100%")? We cannot
   auto-detect "is a loop intended" (cycle state unreadable), so automatic
   loop-preference *requires* the UI toggle.
2. **Alignment caveat:** in this fixture `Trim Silence` trimmed all 4 stems to a
   *common* end (equal length, bar-1 aligned). Confirm this holds on a project with
   **staggered track ends**; if not, `Extend File Length to Project End` guarantees
   identical length but over-pads (256 s here). Decide: find/build a staggered
   fixture to verify, or accept the risk.

### Implementation sketch once decided (PROMPT 1.5c)
- In `export_stems()`, set **pop-up #2** by value-membership in
  `{Trim Silence at File End, Export Cycle Range Only, Extend File Length to Project End}`
  (same robust pattern already used for Format/Normalize: read value, click only if
  it differs). Default → `Trim Silence at File End`; loop path → `Export Cycle Range
  Only`. **No transport prep, no `_prepare_export_range()` cycle/locator dance** —
  the plan's primitive is moot.
- **Fold in the conflict-dialog dismissal** (see §6): add a `_dismiss_conflict_sheet()`
  that clicks `Ignore` on a modal "Key Command Assignment Conflicts" sheet, called
  before/after the export-dialog open (mirrors `_dismiss_replace_sheet`). Currently
  it lives only in the discovery harness.
- Re-run a wet export and verify all stems equal length, bar-1 aligned; project
  byte-unchanged; Logic quit clean. Then resume the existing sequence: **PROMPT 2**
  (Raw pass `bypass_fx=True` → `03_Raw` + T11 `_assert_raw_differs`) and **PROMPT 3**
  (hardening).

## 5. Files this session

**Created**
- `docs/2026-06-10/DISCOVERY_range.md` — full findings, the decisive table, verbatim
  pop-up #2 option strings, accessibility limits, recommendation.
- `docs/2026-06-10/HANDOFF.md` — this file.
- `tools/range_discovery.py` — discovery harness (DISCOVERY ONLY; reuses
  `LogicRenderBridge` for export/quit). Steps: `baseline`, `t2_playhead [bar]`,
  `cycle_probe`, `range_mode "<mode>"`, `popups`, `quit`. Contains the
  conflict-dialog dismissal and a working `goto_position` (types into the modal).

**NOT modified**
- `python/logic_render.py` — untouched (discovery only). The range fix + conflict
  dismissal still need to be added here (PROMPT 1.5c).

**Verification artifacts**
- WAV outputs under `/tmp/stemexport_range/<test>/` (baseline, t2_playhead, cycle_a,
  cycle_b, range_trim, range_export, range_extend). Safe to delete.

## 6. Environment notes / gotchas
- App bundle `/Applications/Logic Pro X.app`; process **`Logic Pro X`**.
- The sandboxed Bash tool can't read `~/Desktop` or drive Logic — run those commands
  with the sandbox disabled (osascript/System Events + python3 work fine).
- **Modal "Key Command Assignment Conflicts"** sheet (buttons `Show Conflicts` /
  `Ignore`) can pop up and block the main window / hang an osascript probe. The
  harness clicks `Ignore` defensively; fold the same into `logic_render.py`.
- Logic's **position/locator fields are `AXSlider`s with encoded values** — read/set
  the playhead only via the modal `Go To ▸ Position…` (type a bar number + OK).
  `Return`, `⌘A`, `Go To ▸ Left/Right Locator` are no-ops without Tracks-pane focus,
  which AX can't grab — **don't rely on them.**
- **Current Logic state:** QUIT (Don't Save) at end of session. `~/Desktop/logic
  test.logicx` ProjectData mtime was **byte-identical before/after** — project
  untouched. Safe.
- Reserved AppleScript words that bit us while scripting: `before`, `log` — avoid as
  variable names.
- The fixture's project end is set far out (256 s) vs ~16.4 s of content — that's why
  `Extend File Length to Project End` over-pads.
