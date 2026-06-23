# Export-range discovery — ground truth (2026-06-10, PROMPT 1.5a)

Probed live against the installed Logic Pro X with `~/Desktop/logic test.logicx`
open. Element-level System Events only (no screenshots, no coordinate clicks).
Harness: `tools/range_discovery.py`. **`logic_render.py` was NOT modified.**

## TL;DR — the range is a DIALOG setting, not a transport state

The export range is governed **entirely by pop-up #2 in the export dialog** (the
"silence/range" pop-up), NOT by the playhead and NOT by the project's cycle state.
The driver currently **never sets pop-up #2**, so it inherits Logic's *sticky* last
value — that is almost certainly the cause of the original mid-project bug.

This does not fit the A/B/C matrix as written (which assumed the range comes from
the project's cycle/locators/playhead). The real answer is closest to **Case A —
the transport state is irrelevant in the default mode** — but with the crucial
addition that **an accessible dialog pop-up selects the range**, so we get clean,
deterministic control without touching the transport at all.

---

## The decisive table (all exports, native 44.1 kHz, 4 stems, equal length)

| Test | State set | Result | Conclusion |
|------|-----------|--------|------------|
| Baseline | default pop-up #2 (`Trim Silence at File End`), playhead bar 1 | **16.364 s** ×4, audio | full song = bar 1 → end of last clip |
| **T2 — playhead** | playhead moved to **bar 5** (verified via Go-To-Position readout), default mode | **16.364 s**, byte-identical | **PLAYHEAD does NOT affect export** |
| Cycle probe ×2 | toggled cycle (`c`) on/off, default mode | **16.364 s**, byte-identical | cycle state irrelevant *in the default mode* |
| **pop-up #2 = `Trim Silence at File End`** | (default) | **16.364 s** | bar 1 → last clip, trailing silence trimmed |
| **pop-up #2 = `Export Cycle Range Only`** | — | **16.000 s** | the cycle/loop range exactly |
| **pop-up #2 = `Extend File Length to Project End`** | — | **256.000 s** | bar 1 → project-end marker (silence-padded) |

Key inference: `Trim Silence at File End` (16.364 s) is **longer** than
`Export Cycle Range Only` (16.000 s). So "Trim Silence" does **not** restrict to the
cycle — it bounces the full project content (bar 1 → last audio) and trims only the
*trailing* tail. That is exactly the product owner's "full song" definition.

## Pop-up #2 — the range control (verbatim option strings)

Dialog pop-up #2 (Options shown), in order:
```
Trim Silence at File End          ← default; full project content, trims tail
Export Cycle Range Only           ← the loop/cycle range
Extend File Length to Project End ← full project to the project-end marker (padded)
```
(For reference, the other dialog pop-ups: #1 `Where`, #5 bit depth
`8-bit / 16-bit / 24-bit / 32-bit float`. Pop-ups #3/#4/#6 are lazy and threw
`Invalid index` when probed un-opened — unchanged from the 2026-06-06 dump.)

## Why nothing in the transport mattered (and why the bug happened)

- The export does **not** read the playhead (T2 proven: playhead at bar 5 →
  byte-identical full-song export).
- In `Trim Silence at File End` mode the export does **not** read the cycle either
  (cycle-toggle probes byte-identical; the 16.364 s result exceeds the 16.000 s
  cycle).
- The driver's `export_stems()` sets Format / Bypass / Normalize but **never sets
  pop-up #2**, so it uses whatever value is *sticky* from the last manual export.
  If that sticky value was `Export Cycle Range Only` and the project had a
  mid-project cycle, every automated export would silently bounce that loop →
  **stems "start from the middle."** That matches the reported first-run symptom.

---

## Hard accessibility limits found (relevant to the original plan)

The original plan's primitive (⌘A → "Set Locators by Selection and Enable Cycle" →
toggle cycle → Return) is **NOT implementable on this install**, because the Tracks
editing pane cannot be made first responder via element-level AX:

- `Edit ▸ Select All` is **disabled** and `⌘A` selects nothing unless the Tracks
  canvas has keyboard focus. `set AXFocused` on the tracks group and `AXPress` on
  the canvas split-groups did **not** transfer editing focus (AXPress instead
  destabilised the Edit menu).
- The tracks/regions canvas is **opaque** to AX — no named track headers or region
  elements to AXPress (so no region selection, no single-region loop).
- `Return` (go-to-start) and `Navigate ▸ Go To ▸ Left/Right Locator` are **no-ops**
  in our context (verified: jumping to the right locator from bar 2 vs bar 6
  returned the *parking* positions, not a consistent locator) — they are
  focus-dependent too.
- There is **no Cycle button** in this (customised, narrow) control bar and the
  control-bar / LCD locator + position fields are exposed only as `AXSlider`s with
  encoded values — **not readable or settable**. So cycle on/off and locator values
  remain unreadable/unsettable, as the 2026-06-06 session found.

What *does* work without canvas focus: **menu items that open dialogs**, **typing
into the modal `Go To ▸ Position…` dialog** (moves the playhead reliably — used to
prove T2), **global window keystrokes** (`x` toggled the Mixer), and **the export
dialog's accessible pop-ups** (Format/Normalize/**#2 range**).

Good news: because the range is pop-up #2, **we never need any of the broken
transport primitives.**

---

## Recommendation (for PROMPT 1.5c)

1. **Immediate fix — set pop-up #2 explicitly every export.** In `export_stems()`,
   identify pop-up #2 by value-membership in
   `{Trim Silence at File End, Export Cycle Range Only, Extend File Length to Project End}`
   (same robust pattern already used for Format/Normalize) and set it. This kills
   the sticky-value bug.
2. **Full-song deliverable (priority #2) → `Trim Silence at File End`.** Verified to
   give bar 1 → end of last clip (16.364 s), 4 equal-length, bar-1-aligned stems,
   independent of any stale cycle or playhead. This is exactly the spec.
   - Alignment caveat to verify on a staggered project: here all 4 stems came out
     equal length, i.e. trimmed to a *common* end, not per-file. Confirm this holds
     when tracks end at different bars; if not, `Extend File Length to Project End`
     guarantees identical length but over-pads (256 s here).
3. **"Prefer the loop" (priority #1) → `Export Cycle Range Only`.** This is now a
   clean either/or pop-up choice, not a cycle/locator manipulation. We still cannot
   *auto-detect* "is a loop intended" (cycle state is unreadable), so this needs a
   product decision — the simplest is the additive UI control from PROMPT 1.5b
   option 2 ("Export range: Full song / Cycle range"), mapping directly to pop-up #2.
   Flag the additive UI for sign-off (hard constraint: reuse UI 100%).

**Suggested default if you want one decision now:** always set
`Trim Silence at File End`. Deterministic, fully accessible, eliminates the bug, and
matches the "full song, bar 1 → last clip" spec. Add the Full-song/Cycle-range UI
toggle later if "prefer the loop" must be automatic.

## Defensive note (already added to the discovery harness)
A modal **"Key Command Assignment Conflicts"** sheet (buttons `Show Conflicts` /
`Ignore`) can appear and block the main window. The harness dismisses it by clicking
`Ignore` (same pattern as `_dismiss_replace_sheet`) before/after transport prep and
before opening the export dialog. Fold this into `logic_render.py` when implementing.

## Artifacts
- Harness: `tools/range_discovery.py` (steps: baseline, t2_playhead, cycle_probe,
  range_mode `<mode>`, popups, quit). Reuses `LogicRenderBridge` for export/quit.
- WAV outputs: `/tmp/stemexport_range/<test>/`.
