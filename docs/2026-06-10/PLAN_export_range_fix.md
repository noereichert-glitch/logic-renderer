# PLAN — Export-range fix (Claude Code prompts, run in order)

Date: 2026-06-10 · Branch: `logic-rend-v1` (a `logic-renderer-v*` branch)
Status going in: wet pass (`01_With_FX`) is GREEN end-to-end. The only open
Phase-1 item is the **export-range bug** + then the **Raw pass**.

Read first: `docs/2026-06-06/HANDOFF.md` (§2/§3 = the blocker) and
`docs/2026-06-06/DISCOVERY.md` (UI ground truth). Reuse `docs/2026-06-06/probes.sh`.

---

## The behaviour we want (from the product owner)

On the first bad run the playhead/locators were **mid-project**, so the export
started from the middle. Desired range logic, in priority order:

1. **If an intact loop (cycle) exists -> export the loop.** Always prefer the loop.
2. **Otherwise -> full song:** playhead to the **beginning (bar 1)**, range running
   to the **end of the last clip**.

So `_prepare_export_range()` must guarantee that *with no loop set*, stems start at
bar 1 and span the whole song; and *with a loop set*, the loop is honoured and
never overwritten.

## Why this isn't a 10-line fix (two live-verified blockers)

- **Cycle on/off is NOT readable via accessibility** on this install: no transport
  buttons in the AX tree, no `AXMenuItemMarkChar` checkmark on a Cycle menu item,
  and nothing named "Cycle" anywhere in `entire contents`. So we **cannot branch on
  cycle state** as the original plan assumed.
- **`Set Locators by Regions` does not exist** here. Only
  `Navigate > Set Locators by Selection and Enable Cycle` (and the "Rounded"
  variant) -- **both force cycle ON**.
- **Unknown:** does `File > Export > All Tracks as Audio Files...` even honour the
  cycle/locators, or always bounce full project length? **Untested -- this decides
  the whole design.**

---

## PROMPT 1.5a — DISCOVERY (read-only-ish, resolve the unknowns FIRST)

```
Confirm the logic-renderer-v* branch. DO NOT modify logic_render.py yet -- this is
discovery only. Use docs/2026-06-06/probes.sh and element-level System Events.
Open ~/Desktop/"logic test.logicx". For each test, set state manually via menu
items / key commands (no coordinate clicks), run ONE export to a temp folder, then
read the resulting WAV durations with python3's wave module. Report a table.

T1 — Does export honour CYCLE?  Enable a short mid-project loop (e.g. Cmd-A then
     "Set Locators by Selection and Enable Cycle", then shrink it). Export.
     -> stems == loop length  => export HONOURS cycle.
     -> stems == full song    => export IGNORES cycle.

T2 — Does the PLAYHEAD matter?  Cycle OFF, move playhead to the middle (do NOT
     press Return). Export. -> do stems start at bar 1 & run full length, or start
     at the playhead?

T3 — Does export honour LOCATORS with cycle OFF?  Set locators mid-project but
     turn cycle OFF, export. -> stems == locator span, or == full song?

Also: enumerate the SECOND pop-up in the export dialog (the "Trim Silence" one) --
list every option string exactly (probes.sh popups).

Write findings to docs/2026-06-10/DISCOVERY_range.md as a table, then STOP and
summarise which case below we're in. Quit Logic (Don't Save).
```

### Decision matrix (which case the discovery puts us in)

- **Case A — export always full song (ignores cycle+locators+playhead).**
  "Prefer the loop" is then impossible via this command; the mid-start bug must
  have another cause -- re-examine. Likely fix = no transport prep at all. (Unlikely
  given the reported bug, but rule it out.)
- **Case B — export honours CYCLE (loop when on, full song when off).**
  This matches intent *for free if we never touch cycle*: loop-on -> loop, loop-off
  -> full song. `_prepare_export_range()` then only presses **Return** (playhead ->
  start) as a harmless safety and leaves cycle/locators alone. Best outcome.
- **Case C — export honours LOCATORS (regardless of cycle).**
  The mid-start bug = stale locators. We must set full-song locators before each
  export *unless a loop is intended* -- and we can't read cycle state. This is the
  hard case; resolve via PROMPT 1.5b's "loop intent" decision.

---

## PROMPT 1.5b — (only if Case C) decide how to know "is there a loop to prefer"

We can't read cycle state via AX. Three ways to get the signal -- evaluate top-down,
recommend one to the product owner, DO NOT build until they pick:

```
Confirm the branch. Read docs/2026-06-10/DISCOVERY_range.md. We're in Case C.
Investigate, in order, and report feasibility (no implementation):

1. RE-PROBE for a cycle/locator signal we missed: the control bar's LCD locator
   fields (left/right locator as AXValue/AXTextField), any ruler AXValueIndicator,
   or the control bar with accessibility descriptions enabled. If the left/right
   locator VALUES are readable, we can detect "a sub-song range is set" without
   needing the on/off bit.
2. EXPLICIT UI INTENT: add ONE additive control to the Electron UI -- "Export
   range: Full song (default) / Keep current loop". Removes the need to read state.
   NOTE the hard constraint "reuse the UI 100%": this is additive, not a redesign,
   but flag it for sign-off before adding.
3. ALWAYS FULL SONG (simplest, deterministic, drops requirement #1): see primitive
   below. Only if the owner accepts that loops are never preferred.

Recommend one. Stop for go-ahead.
```

**Deterministic "full-song locators, cycle left OFF" primitive** (for the full-song
path in Case C -- no `Set Locators by Regions` needed):

```
Cmd-A                                           -- select all regions
Navigate > "Set Locators by Selection and Enable Cycle"   -- locators = first->last region; cycle now ON (KNOWN)
Toggle Cycle once                               -- cycle now OFF (deterministic: we just turned it on)
press Return                                    -- playhead -> bar 1
```

This is safe because we *know* the state right after we set it, so the single
toggle reliably lands cycle OFF. (Skip this whole block when intent = keep loop.)

---

## PROMPT 1.5c — implement `_prepare_export_range()` + Trim Silence

```
Confirm the branch. Implement per the case from discovery (and the loop-intent
decision if Case C). Element-level System Events only.

1. Add LogicAutomation._prepare_export_range() and call it at the TOP of
   export_stems(), BEFORE opening the export dialog.
   - Case B: press Return (playhead -> start); do not touch cycle/locators.
   - Case C / full-song: run the full-song-locators primitive above.
   - Case C / keep-loop: press Return only; leave locators untouched.
2. In export_stems(), set the Trim Silence pop-up (dialog pop-up #2) to the option
   that leaves audio intact/aligned (likely "No Change" -- use the exact string from
   DISCOVERY_range.md). Mirror the existing Format/Normalize pop-up pattern: read
   value, click only if it differs.
3. Re-run tools/run_wet_export.py "~/Desktop/logic test.logicx" "/tmp/stemexport_out".
   VERIFY: parse every WAV with wave; all stems equal length; length matches the
   project's full song (or the loop, if keep-loop). Confirm Logic quit clean and the
   .logicx is byte-unchanged. Paste durations. Commit only if I ask.
```

---

## After the range fix: resume the existing prompt sequence

- **PROMPT 2** (existing doc) — the **Raw pass** (`bypass_fx=True` -> `03_Raw`) plus
  the **T11 `_assert_raw_differs`** content guard on a project with audible insert
  FX. `export_stems(bypass_fx=True)` is already coded; only the full two-pass run +
  guard remain.
- **PROMPT 3** — Harden (crash-retry, stray sheets, event-driven waits, STATUS.md).

## Side note (optional, not blocking)
`quit_logic` took 33.6 s in the wet run (Save-prompt sheet + escalation ladder).
Functional but slow -- tighten the polite-quit window / clear the sheet faster when
next in that file.

## Conventions reminder (every prompt)
- Confirm the `logic-renderer-v*` branch first; never create/switch/push branches.
- Element-level System Events only -- no Screen Recording, no coordinate clicks, no
  Finder automation.
- Never save the Logic project; always quit it (try/finally).
- Render at the project's native sample rate.
- Commit only when explicitly asked.
