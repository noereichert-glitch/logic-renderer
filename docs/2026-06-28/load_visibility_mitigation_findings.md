# Launch/Load Visibility Mitigation — gate findings (2026-06-28)

**Question:** the project load brings Logic frontmost **and** shows its window despite
`open -g`. Can that be suppressed so Logic stays both **not-frontmost** AND
**not-visible-on-screen** through launch → load → export-start — *while still being
able to export*?

**Scope:** investigation only. **No production code was changed** for this test; the
variants are pure launch strategies issued by a scratch harness. Tier 0.
Companion: `P3_DISCOVERY_background.md`, `logic_dialog_catalog.md`.

---

## Prerequisite finding (clean, 3×) — load self-activates Logic

With the current production launch (`open -g`), measured hands-off (TextEdit
frontmost) across 3 runs:
- **Logic VISIBLE during load: 30/30, 27/27, 28/28** — the window is on screen the
  whole load.
- **POST-LOAD idle: Logic FRONTMOST 10/10 in all 3 runs** — deterministic.
- LOAD-phase frontmost count varied (0.6s–8.7s) run to run (timing), but the end
  state is stable: **opening the project leaves Logic frontmost + visible.**

So `-g` only suppresses the *initial* activation; opening the document re-activates
and shows Logic by the time load completes.

## Method (the gate)

Hands-off (TextEdit frontmost, no mouse/keyboard input), each variant 2–3×, sampling
every 0.3s through launch → load → export-start. **Two independent signals:**
- **frontmost** — is `Logic Pro X` the frontmost process (System Events).
- **on-screen** — # of Logic *normal* windows actually composited on screen, via
  CoreGraphics `CGWindowListCopyWindowInfo` (`OnScreenOnly | ExcludeDesktopElements`,
  layer 0). This is the true "what the user sees" measure: a **hidden** app reports
  **0** here even while System Events still calls it "frontmost". (Demonstrated:
  TextEdit with no document is frontmost yet has 0 on-screen windows.)

## Variants tested

1. `open -g -j` (launch hidden) + project in one shot.
2. `open -g -j` (hidden, **no** project) then Apple-event `tell app "Logic Pro X" to open <path>`.
3. `open -g` + project, then `set visible of process to false`, **re-asserted each poll tick**.
4. Combo: `open -g -j` + `set visible=false` re-asserted each tick.

## Results

| Variant | On-screen windows (what the user SEES) | Frontmost process |
|---|---|---|
| **v1** `open -g -j` | **0 / 0 / 0** (load·idle·export) — invisible, 2/2 | load 16–17/18, idle 10/10 — **not** suppressed |
| **v2** hidden + Apple-event open | **0** throughout — invisible, 2/2 | idle 9–10/10 — not suppressed (load sampling degenerate*) |
| **v3** `open -g` + `visible=false` re-assert | **0** throughout — invisible, 2/2 | load flaky (0/19 **or** 15/17), idle **0/8**, export **0/5** — suppressed post-load |
| **v4** `open -g -j` + `visible=false` re-assert | **0** throughout — invisible, **3/3** | load 14–16/17, idle **0/8**, export **0/5** — suppressed post-load |

\* v2's no-project launch already has a window, so readiness fired at sample 1 — its
load phase isn't meaningfully sampled. Behaviour otherwise matches v1.

## Key findings

1. **The visible window CAN be fully suppressed.** Every hide variant (v1/v3/v4) kept
   Logic at **0 on-screen windows in 100% of runs, across load, idle, and export** —
   including the ~26s load. `-j` or `visible=false` reliably stops the user ever
   seeing a Logic window.
2. **Frontmost-process cannot be suppressed during the ~5–8s load window** by any
   variant. `visible=false` re-assertion (v3/v4) reliably suppresses frontmost
   **post-load and at export-start** (0/8, 0/5); `-j` alone (v1/v2) does not suppress
   frontmost at all.
3. **DECISIVE CAVEAT — hiding breaks the export.** When launched hidden (`-j`), the
   **Export menu-bar click is accepted (`"clicked"`) but no dialog opens**
   (`exists window "Open"` = false). A hidden app has no usable menu bar, so the very
   thing that buys invisibility (hiding) disables the menu-driven export.
   (Also observed: `visible` flips back to `true` by ready-time even with re-assert,
   yet CGWindowList still shows 0 on-screen — i.e. `visible` attribute ≠ composited
   on screen; the authoritative signal is CGWindowList.)

## Conclusion / recommendation

- **No tested variant keeps Logic both not-frontmost AND not-visible through load
  while remaining able to export.** Hiding gains invisibility but breaks the menu
  export; `-j` doesn't suppress frontmost; `visible=false` only suppresses frontmost
  after load.
- The **proven working state** for driving the export (P3) is
  **backgrounded-but-VISIBLE** (current `open -g`, Logic not frontmost): menu/element
  clicks work, cursor never moves, focus isn't stolen during the element steps. Its
  only cost: **Logic's window is on screen (backgrounded) during the ~26s load**, and
  Logic is the frontmost process for ~5–8s of it.
- **Recommendation: do NOT adopt the hide-based mitigations in production** — they
  break or endanger the export. Either accept the backgrounded-but-visible load
  window as the **Tier-0 residual**, or implement **Tier 1 (off-screen virtual
  display)** for true "window never appears" with a working export — exactly what
  `Invisible_Render_Handoff_v1.md` predicted would be required. A
  hide-during-load / un-hide-to-export hybrid is theoretically possible but fragile
  given the menu-needs-visible constraint; Tier 1 is the clean path.

## Notes

- **Cursor:** never moved by the renderer in any run — the harness and production
  contain **no cursor API** (no coordinate/cliclick/CGWarp). Cursor-position changes
  seen in a few runs were the human operator (large, arbitrary jumps) and are
  unrelated to the code.
- **Never-saved:** `.logicx` ProjectData byte-identical / mtime unchanged (Jun 6)
  across the entire investigation; every run quit clean.
- Measurement hygiene: the earlier full-run "% Logic frontmost" numbers were
  discarded as noise (interactive-session apps + crash-recovery dialogs from repeated
  kills). This gate used a clean baseline, hands-off, two precise signals, multi-run.
