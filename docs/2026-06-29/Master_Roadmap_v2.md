# Renderer — Master Roadmap & Handoff (v2)

**Date:** 2026-06-29 (revised same day — see §2 sequence change: Ableton prioritized
as the main hard-testing DAW).
**Lives in:** `docs/2026-06-29/` (this folder).
**Status:** current master plan. Supersedes the *sequencing* in
`docs/2026-06-28/STATE_OF_PLAY.md` and extends the tiered plan in
`docs/2026-06-28/Invisible_Render_Handoff_v1.md` (which remains the source of truth
for Tier definitions, DialogGuard spec §6/§7, and verification §11).

**Read order for a fresh session:** `../../CLAUDE.md` -> this file ->
`../2026-06-28/Invisible_Render_Handoff_v1.md` -> `../2026-06-28/logic_dialog_catalog.md`.

---

## 1. Goal (unchanged)

Render stems **invisibly inside the user's own login session** while they keep using
the Mac: no cursor movement, no stolen focus (or a sub-second masked moment), and --
ultimately -- no visible window. Three DAWs share one design: **Logic, FL Studio,
Ableton**. The UI is drag-and-drop and DAW-agnostic.

---

## 2. Master build sequence (the order we work in)

1. **Logic Tier 0 -- finish** *(in progress; nearly done)*
2. **Ableton Tier 0** *(next -- it is the owner's MAIN DAW)* + wire the shared modules
   + Ableton's own dialog catalog + notifications/inbox.
3. **Hard-test on Ableton** with real/big projects -- this is the primary validation
   pass, because the owner has the most real projects here and the shared modules get
   their real workout. Fixes propagate to Logic + FL via the shared code.
4. **FL Studio Tier 0** *(last DAW -- hardest: non-accessible render dialog, masked
   Start blip, cliclick locked off)*.
5. **Tier 1 (off-screen virtual display + keyboard event-tap)** -- built **once,
   shared** across all three DAWs, **last**.

**Why Ableton second and as the hard-test target:** it is the main DAW (most real
projects to test with) and its **Remote Script already does bypass headless**, so its
Tier 0 is likely *easier* than Logic's (a real Python API into Live, not accessibility
hacks), and being scripted it may raise *fewer* macOS dialogs. Logic is still finished
first so the shared modules are proven on **two** DAWs, not just Ableton.

### What transfers between DAWs vs what does not (important)
- **Shared -- built once, improvements flow to all three:** the Electron UI, the Flask
  server/orchestrator, the **DialogGuard engine** (`dialog_guard.py`), and the
  notifications/inbox. Hard-testing Ableton validates these; Logic + FL inherit fixes.
- **Per-DAW -- does NOT transfer:** the render **driver**. Logic = macOS accessibility
  automation (`logic_render.py`); Ableton = its **Remote Script** (Live Python API);
  FL = different again (hardest). Each is its own build; hard-testing one driver does
  not validate another -- so Logic and FL drivers still need their own (lighter)
  validation passes.
- **Per-DAW data, shared engine:** each DAW needs its **own dialog catalog**
  (different app = different alert strings), but they all load it into the *same*
  DialogGuard engine.

---

## 3. Logic Tier 0 -- status

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
- **DialogGuard engine (6a):** `python/dialog_guard.py`, 45 unit tests green.
- **DialogGuard live wiring (6b):** detector + executor + `DialogGuardPause`, wired
  behind `self.headless`. Three scan-seam bugs fixed (splitlines / join-normalize /
  strip-eats-RS). **C9 verified live 3/3** (`clicked=['OK']`, dialog cleared, ready).

### Remaining to "hard-testable"
1. **Prove the PAUSE/fail path live** against a real non-C9 dialog (C5 missing-audio or
   C7 read-only output) -- detect -> decide -> abort clean (never saved) -> reason
   surfaced. (Only the CLICK case, C9, is proven live so far.)
2. **Notifications + inbox** (see §4) -- the instrument for hard-testing.
3. **P8-basics:** full export end-to-end with the guard active (4+4 WAVs, never-saved,
   focus/cursor) + **"stems are not silent" check** + **scan-timing check** +
   `tools/tester.py` smoke test + `STATUS.md`.

**Note on the dialog catalog:** only **C9 is live-confirmed**. C1-C8 are string-dump
candidates -- the **learn-loop** (logs unknown dialogs, pauses safely) grows the
catalog organically during hard-testing, so exhaustive pre-validation is NOT required;
unrecognized dialogs fail safe (pause + log). JSON wire-format hardening of the scan is
flagged for the hardening pass if any further parse-class bug appears.

---

## 4. Notifications & in-UI inbox (product decisions)

**When to notify -- critical failures only.** A notification fires **only when
something is critical and the project cannot be bounced** (a guard PAUSE, a
fail_job/terminal dialog, a render that can't complete). **Not** for routine progress.
The user must always learn *which project* failed and *why*.

**Two channels, one signal** -- both driven by the same server signal (job
**paused/failed with `{project, reason}`**):
1. **Native macOS notification** on that critical failure -- no UI redesign.
2. **In-UI message inbox** -- net-new UI, a **deliberate, owner-approved deviation**
   from "reuse the UI 100%". DAW-agnostic so all three share it.

**Scope = programming only now.** Build the feature + UI; **hard-testing the
notification system is a separate pass later**, alongside the big-project campaign.

---

## 5. Open items / decisions (updated 2026-06-29)

- **C2 / "Replace" -- RESOLVED (owner decision):** overwriting same-named stems IS the
  desired behavior. Keep current handling (defensive `_dismiss_replace_sheet`; the gated
  engine rule remains available). The "empty per-job root at job start" Option A is NOT
  pursued. No longer an open question.
- **Silent/empty WAV exports -- OUT OF SCOPE (owner decision):** the owner handles
  silent-stem detection separately, by other means. The planned P8 "stems are not
  silent" check is **dropped** from this project's scope.
- **Keystroke-leak during the masked flick -- deferred to Tier 1.** The sub-second
  leak window is accepted for Tier 0; eliminated by the Tier 1 keyboard event-tap
  ("keyboard numbing"). No Tier 0 action.
- **Field failure mode (still relevant):** Logic 11/Sequoia "open file operation
  failed... open and save panel service" -> guard should surface/pause (now covered by
  the post-Export dialog scan).
- **Multi-project testing:** verification to date used ONE simple fixture
  (`~/Desktop/logic test.logicx`). Hard-testing must use real/big projects of varied
  size, plugins, sample rate, routing -- primarily on **Ableton** (main DAW), per §2.

---

## 6. DialogGuard reference notes

- Catalog is **version-bound** -- re-dump bundle strings per app version.
- Body-match treats tokens `^P`/`^C`/`%@`/`%ld` as **wildcards**; normalize quotes +
  whitespace. **Scan wire-format lesson:** ASCII separators (`\x1c\x1d\x1e\x1f`) collide
  with Python `str.splitlines()` AND `str.strip()` (both treat them as whitespace/line
  boundaries) -- three bugs came from this. Current scan avoids both (`split('\n')`,
  `strip=False`, `flat1` field-collapse). **JSON output is the recommended hardening**
  to end this class.
- **Separate-process surface:** Problem Reporter (handled), **TCC/permission**, and
  **disk-full** alerts come from a different process -- a Logic-scoped AX scan won't see
  them. TCC/disk-full = a distinct detection surface not yet built.
- **Post-Export scan gap (CC-found, fixed):** the guard scanned only at
  `wait_for_logic_ready` + once before the Export menu; a dialog appearing *after* the
  Export click ("export failed" / disk-full) went unhandled and the bounce-wait hung to
  its ~1800s timeout. Fix (headless only): `wait_for_export_complete` now runs
  `_handle_dialogs` each poll tick, so such a dialog is detected → decided → surfaced
  immediately; a healthy offline bounce shows no AXDialog/sheet so it is untouched.
- Safety invariants: never click a `never_click` button even if a rule lists it; gated
  `Replace` only when all gates hold; **any unrecognized dialog -> pause-notify**.

---

## 7. Per-DAW template (what each DAW must get before Tier 1)

For each of Logic / Ableton / FL:
1. **Tier 0** -- driver automation (DAW-specific), no cursor, dropped/masked frontmost
   where applicable, `headless` flag with legacy fallback, App-Nap guard.
2. **DialogGuard** -- the **shared engine** + the DAW's **own** dialog catalog
   (string-dump + learn-loop), key-anchored, fail-safe.
3. **Notifications + inbox** -- critical-failure notification (native + inbox) on the
   shared `{project, reason}` signal.
4. **Verification** -- hands-off end-to-end, audio-identical, never-saved,
   stems-not-silent, dialog handling; **the deep big-project campaign runs on Ableton**
   and its fixes propagate to the shared modules.

See §2 "What transfers": the shared modules are built once; only the per-DAW driver +
dialog catalog are rebuilt per DAW.

---

## 8. Constraints (unchanged)

Never `git push`; commit only when the user asks; **the user creates/renames branches**
(CC only confirms the active branch). Never move the cursor. Never save the project.
Native sample rate. Every behavioural change **behind the `headless` flag with the
legacy path intact**. Reuse the UI -- **one deliberate exception: the message inbox.**
One change at a time; CC stops and reports after each step. **Proof of a DialogGuard fix
is the LIVE verify, never unit tests** (they have missed live bugs three times).

---

## 9. Next handoff -- Ableton (to be written when we pivot)

Ableton is the **main DAW and the next build + primary hard-test target** (§2). When
Logic Tier 0 is finished, the advisor will write a fresh **Ableton handoff into the
Ableton renderer's docs folder** (access to be granted) -- a concrete, folder-grounded
map built from this Logic work toward the same goal, reusing the shared modules and
specifying Ableton's own driver (Remote Script) + dialog catalog. Open questions raised
there before work begins.

---

## 10. Planned shared post-processing agent -- "Stem Cleanup / Rename agent" (later)

A **DAW-agnostic** post-processing stage that runs **between render and delivery**, on
the produced WAVs (independent of which DAW made them -- built **once, shared** like the
other modules). Owner builds this later; **NOT on the Tier 0 or Tier 1 critical path**
(orthogonal -- can be built in parallel).

**Responsibilities:**
- **Rename** exported stems from the DAW's default track names to the desired
  convention.
- **De-duplicate / disambiguate:** handle **within-render name collisions** -- two
  *different* tracks sharing a track name can export to the same filename and silently
  overwrite (losing a stem). The agent disambiguates these. *Distinct from* the accepted
  re-run overwrite of same-named stems (§5). **Verify when built:** whether each DAW
  auto-appends a suffix on same-named tracks, or actually overwrites (would lose a stem
  before the agent ever sees it).
- **Silent-stem flag:** detect silent/empty WAVs and flag them. This is where the owner
  handles silent stems (per §5) -- out of the renderer / DialogGuard scope.

**Relationship to DialogGuard:** complementary, not overlapping. DialogGuard handles
*render-time* failures (dialog -> pause/surface); this agent handles *output-quality*
issues (silent / duplicate) after the render. Issues it flags can surface through the
same notifications/inbox `{project, reason}` signal.
