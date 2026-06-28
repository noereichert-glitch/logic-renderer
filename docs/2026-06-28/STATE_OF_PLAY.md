# Logic Renderer — State of Play (invisible/headless work)

**Date:** 2026-06-28
**Purpose:** Single pickup point for a fresh chat/session. Read this first, then
the companion docs in this folder.

## Companion docs (this folder, `docs/2026-06-28/`)
- `Invisible_Render_Handoff_v1.md` — the full tiered plan (Tier 0/1/2), DialogGuard
  spec, popup-research plan, ordered prompts. **The master plan.**
- `logic_dialog_catalog.md` — popup catalog + DialogGuard rules (entry #1
  AUTO-HANDLED).
- `probe_save_panel.txt` — P1/P2 save-panel AX probe.
- `P3_DISCOVERY_background.md` — backgrounded-action table, masking design,
  staging-folder dead-end, within-session stickiness.
- `P3_gate_load_visibility.md` *(if present)* — the load-visibility gate matrix.
- Any newest CC session handoff in this folder.

## The goal
Render stems **invisibly in the user's own login session** while they keep using
the Mac (drag-and-drop UX; the UI picks which project → which DAW). No cursor
movement, no focus theft, ideally no visible window. A second login session / second
machine is **rejected** (breaks drag-and-drop). "Headless = nobody logged in" is
impossible on macOS and not the goal.

## Strategy — three tiers (build 0 first)
- **Tier 0 (Foundation):** element/value automation, no cursor, no/masked frontmost,
  `headless` flag, App-Nap guard, DialogGuard. No private APIs, no setup.
- **Tier 1 (in-session invisibility):** off-screen **virtual display** (private
  `CGVirtualDisplay`) to hide the window + keyboard **event-tap** (buffer/replay).
  Built **once, shared** across all three DAWs — last.
- **Tier 2 (containment):** second machine. Documented fallback only.
- **Key principle:** the virtual display only hides the *window*; Tier 0 is what
  protects *keyboard focus*. Both are needed; one session = one keyboard/frontmost.

## Logic — current status
**Tier 0 essentially done and verified (headless path; legacy untouched behind
`if not self.headless:`):**
- Destination set by AX value (`text field 1 of sheet 1 of window "Open"`), per-job.
- `set frontmost` dropped for all element actions (menu/format/bypass/normalize/
  Export button work backgrounded).
- Two irreducible chords (⌘⇧G, Return) masked via `_run_masked_keys()`: idle-gate
  → snapshot frontmost → flick → restore. Cursor never moves. Measured flick
  (2026-06-28, 50ms sampler): baseline **~2.0s** observed / ~2.09s in-process (the
  old "~1.2s" came from coarse 0.2s sampling and was wrong). After compressing the
  two sheet-wait sleeps to bounded polls: **~1.4–1.5s** observed / ~1.58s in-process
  (~24% faster), audio byte-identical. See `P3_DISCOVERY_background.md`.
- Quit (headless): non-blocking Apple-event quit + instant "Don't Save" dismissal
  (element click, backgrounded, cursor never moves) + focus restore. Measured
  2026-06-29: **~13s → ~3s** (the old path blocked the full 10s on the quit
  osascript because the save prompt was only answered after it timed out). The quit
  modal transiently pulls Logic frontmost; restoring focus the instant the Don't-Save
  click lands cut that frontmost-during-quit leak from **~2.5s → ~0.12s**. Never
  saves (`Alternatives/000/ProjectData` mtime unchanged); focus ends on the user's
  app. Legacy (`not headless`) ⌘Q path unchanged.
- `headless` flag wired server.py → stem_exporter.py → LogicRenderBridge (default on).
- Minimal safe auto-dismiss (`_auto_dismiss_dialogs`): clears free AXDialogs + sheets,
  whitelisted safe buttons only, never destructive; readiness check fixed; verified
  3/3 hands-off on the audio-interface alert (clicks OK, focus/cursor untouched).

**Load-visibility gate (decisive result):** No in-session variant keeps Logic both
hidden AND frontmost-suppressed AND able to export. **Hiding the app breaks the
menu-driven export** (hidden app has no usable menu bar). So:
- Proven production path = **backgrounded-but-visible**: export works, cursor never
  moves, focus not stolen during element steps; cost = Logic's window sits in the
  background during the ~26s project load, and Logic is frontmost-process ~5–8s of
  load. (Verify whether that 5–8s steals keyboard.)
- **True "window never appears" requires Tier 1** (off-screen virtual display) —
  exactly as the handoff predicted.

## Remaining Logic work (in order)
1. **Pass-2 within-session optimization** — skip ⌘⇧G+Return on the raw pass (guard:
   read "Where:" value, fallback to masked path on mismatch). Cuts raw-pass chords to 0.
2. **Full DialogGuard (P6/P7)** — generalize the minimal auto-dismiss into the
   catalog-driven guard + learn-loop; finish the catalog.
3. **Full verification (P8)** — one clean hands-off end-to-end run; wire
   `tools/tester.py` smoke test + `STATUS.md` (match FL/Ableton).
4. **Branch + commit** — rename `headles-work` → `logic-renderer-vN` before any
   commit. **Never `git push`.** Commit only when the user asks.
5. **Logic completion handoff + porting notes** — the reference for Ableton/FL.

## After Logic
Ableton Tier 0 (run its export feasibility probe first — its Remote Script already
does bypass headless) → FL Tier 0 (hardest; non-accessible render dialog, one masked
Start blip, cliclick locked off) → **build Tier 1 once, shared** (Logic is now a
proven customer for it, so it may be built here first as the reference).

## Working style / constraints
- One change at a time; Claude Code stops and reports after each step; commit only
  when asked; never push; never save the project; native sample rate; never move the
  cursor (no cliclick/coordinate clicks).
- The human runs Claude Code and pastes its updates to the advisor chat, which
  interprets and returns the next prompt.
- Folders: only **Logic** needed now; connect Ableton + FL when porting begins.
