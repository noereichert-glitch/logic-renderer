# Renderer — Master Roadmap & Handoff (v2)

**Date:** 2026-06-29
**Lives in:** `docs/2026-06-29/` (this folder).
**Status:** current master plan. Supersedes the *sequencing* in
`docs/2026-06-28/STATE_OF_PLAY.md` and extends the tiered plan in
`docs/2026-06-28/Invisible_Render_Handoff_v1.md` (which remains the source of truth
for Tier definitions, DialogGuard spec §6/§7, and verification §11).

**Read order for a fresh session:** `../../CLAUDE.md` → this file →
`../2026-06-28/Invisible_Render_Handoff_v1.md` → `../2026-06-28/logic_dialog_catalog.md`.

---

## 1. Goal (unchanged)

Render stems **invisibly inside the user's own login session** while they keep using
the Mac: no cursor movement, no stolen focus (or a sub-second masked moment), and —
ultimately — no visible window. Three DAWs share one design: **Logic, FL Studio,
Ableton**. The UI is drag-and-drop and DAW-agnostic.

---

## 2. Master build sequence (the order we work in)

1. **Logic Tier 0 — finish** *(in progress)*
2. **Logic notifications + in-UI message inbox** *(after Tier 0, before Tier 1)*
3. **FL Studio — Tier 0 + notifications/inbox**
4. **Ableton — Tier 0 + notifications/inbox**
5. **Tier 1 (off-screen virtual display + keyboard event-tap)** — built **once,
   shared** across all three DAWs, **last**. Logic is the reference customer.

**Principle:** every DAW gets the full **Tier 0 + notification/inbox** template
*before* anyone builds Tier 1. Doing Tier 0 across all three first tells Tier 1
exactly which residuals it must cover (FL's non-accessible render dialog, etc.).

---

## 3. Logic Tier 0 — status

### Done & verified
- **Foundation:** element/value automation, cursor never moves, `set frontmost`
  dropped for element actions, masked flick for the Cmd-Shift-G/Return chords,
  Apple-event quit, `headless` flag (default on, legacy path intact), minimal safe
  auto-dismiss.
- **Flick compression:** sheet-wait sleeps -> bounded ~50 ms polls + fixed-delay
  fallback. ~2.0 s -> ~1.4 s, audio byte-identical (PCM).
- **Quit rework:** non-blocking quit + instant "Don't Save" + focus restore the
  moment the click lands. ~13 s -> ~3 s; Logic-frontmost-during-quit ~2.5 s -> ~0.12 s.
- **Instrumentation stripped;** committed and pushed as branch **`headless-V1`**
  (`origin/headless-V1`). Ongoing work continues on **`headles-work`**.
- **DialogGuard discovery:** catalog C1-C9 + 7-locale, **key-anchored**
  `dialog_rules.yaml` generated from the real bundle strings (Logic 11.0.1 / 6029).
- **DialogGuard engine (step 6a):** `python/dialog_guard.py` — pure decision logic,
  `{title, body, buttons}` -> CLICK / PAUSE / IGNORE. 28 unit tests green incl.
  adversarial (never click destructive on unknown, never_click overrides a rule,
  token-filled bodies match, fail-safe pause).

### Remaining
- **6b — wire engine to the live flow:** detector reads real `{title, body, buttons}`;
  executor does *only* what `decide()` returns; **`DialogGuardPause`** = safe job
  abort (stop render, quit clean, surface reason). Behind `headless`, legacy intact.
- **P7 — error-injection:** deliberately trigger missing-audio / missing-plugin /
  sample-rate / overwrite etc. to validate cataloged **C2-C8 against real dialogs**.
  Only **C9 (audio-interface alert) is live-confirmed** so far — it fires on every
  launch on this machine and the guard clicks **OK** (never Open Settings), 3/3
  hands-off. C1-C8 are string-dump candidates until injection confirms them.
- **P8 — verification:** one clean hands-off end-to-end run; `tools/tester.py` smoke
  test; `STATUS.md`; **plus a new "stems are not silent" check** (see Sec. 5).
- **Notifications** (see Sec. 4) — programmed as part of finishing this phase.
- **Logic completion handoff + porting notes** (reference for FL/Ableton).

---

## 4. Notifications & in-UI inbox (product decisions)

**When to notify — critical failures only.** A notification fires **only when
something is critical and the project cannot be bounced** — i.e. a guard PAUSE,
a `fail_job`/terminal dialog, or a render that can't complete. **Not** for routine
progress or non-blocking events. The user must always learn *which project* failed
and *why*.

**Two channels, one signal.** Both are driven by the same server signal — a job
reported **paused/failed with `{project, reason}`**:
1. **Native macOS notification** on that critical failure — standard OS notification,
   no UI redesign. Built with this phase.
2. **In-UI message inbox** — a place in the app where these failure notifications
   collect. **This is net-new UI** and a **deliberate, owner-approved deviation** from
   the "reuse the UI 100%" constraint. Built **after** Logic Tier 0, **before** Tier 1,
   then included in each DAW. Keep it DAW-agnostic so all three share it.

**Scope for now = programming only.** This phase **builds the feature and the UI**.
**Hard-testing / rigorous verification of the notification system is done separately,
later** — not part of the current implementation pass.

---

## 5. Open items / TODOs carried forward

- **C2 / "Replace" — product decision pending.** The export-overwrite "Replace" is the
  *only* destructive click in the guard. **Option A:** empty the per-job export root at
  job start (only our own artifacts; foreign files -> pause, never delete) -> lets
  `Replace` be **dropped entirely** (pause-notify). **Option B (current):** keep the
  gated `Replace` (G1 dest = our per-job root AND G2 collider = our own `.wav` AND G3
  pass 1). **Using B for now; owner to revisit.**
- **Field failure modes (not dialog rules — from user reports):**
  - Logic 11 / Sequoia: *"The open file operation failed... failed to connect to the
    open and save panel service"* — the export Save panel sometimes fails to open ->
    the guard should surface/pause rather than hang.
  - **Silent / empty WAV exports with NO dialog** (aux tracks, automation-related) ->
    DialogGuard **cannot** catch these (no popup). Defense = **P8 "stems are not
    silent" check**: verify exported stems actually contain audio.

---

## 6. DialogGuard reference notes (for 6b / P7 / ports)

- Catalog is **version-bound** — re-dump the bundle strings per Logic version (current
  dump = 11.0.1 / build 6029); reworded alerts shift the English-as-key anchors.
- Body-match treats tokens `^P` / `^C` / `%@` / `%ld` as **wildcards**; normalize
  curly/straight quotes and whitespace.
- **Separate-process surface:** macOS Problem Reporter (crash), **TCC/permission**
  prompts, and **disk-full** alerts are raised by a *different* process, so an
  AXObserver scoped to the Logic process alone won't see them. Problem Reporter is
  already handled (`dismiss_macos_crash_reporter`); TCC/disk-full are a **distinct
  detection surface not yet built**.
- Safety invariants (must always hold): never click a `never_click` button even if a
  rule lists it; gated `Replace` only when all gates hold; **any unrecognized dialog ->
  pause-notify, never guess**.
- Locale: system is `en_*` (English UI) with German secondary; Logic renders dialogs
  in English today. Rules are key-anchored across all 7 shipped locales so a future
  language switch is covered; unsupported locales fail safe (pause).

---

## 7. Per-DAW template (what each DAW must get before Tier 1)

For each of Logic / FL / Ableton:
1. **Tier 0** — element/value automation, no cursor, dropped/masked frontmost,
   `headless` flag with legacy fallback, App-Nap guard.
2. **DialogGuard** — shared engine + the DAW's own dialog catalog (string-dump +
   error-injection), key-anchored, fail-safe.
3. **Notifications + inbox** — critical-failure notification (native + inbox) on the
   same `{project, reason}` signal.
4. **Verification (P8-equiv)** — hands-off end-to-end, audio-identical, never-saved,
   stems-not-silent, dialog-injection.

DAW-specific notes (from `Invisible_Render_Handoff_v1.md`): **FL** is hardest
(non-accessible render dialog, one masked Start blip, cliclick locked off);
**Ableton** has a Remote Script that already does bypass headless — run its export
feasibility probe first.

---

## 8. Constraints (unchanged)

Never `git push`; commit only when the user asks; **the user creates/renames
branches** (CC only confirms the active branch). Never move the cursor (no
cliclick/coordinate clicks). Never save the project. Render at the project's native
sample rate. Every behavioural change stays **behind the `headless` flag with the
legacy path intact**. Reuse the UI — **now with the one deliberate exception: the
message inbox.** One change at a time; CC stops and reports after each step.

---

## 9. Next handoff — Ableton (to be written later)

**After** Logic Tier 0 + notification/inbox are programmed, the advisor will write a
fresh **Ableton handoff saved into the Ableton renderer's docs folder** (access to be
granted). That handoff will be a concrete, folder-grounded map — built from this Logic
work, toward the same goal — once the advisor can read the Ableton repo. Open
questions will be raised there before work begins.
