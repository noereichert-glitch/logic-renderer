# Logic Pro Renderer — Invisible / Background Render Handoff (v1)

**Date:** 2026-06-28
**Lives in:** `docs/2026-06-28/` (this folder). Supersedes the "PROMPT 5 —
Background / shared core" stub in `docs/Logic_Renderer_ClaudeCode_Prompts_v1.md`.

**Read order:** `../../CLAUDE.md` → `../CLAUDE_CODE_START_HERE.md` →
`../Logic_Renderer_Handoff_v1.md` → **this file**.

---

## 1. The goal (one sentence)

While the client keeps using the Mac — including dragging projects onto the
renderer and typing in other apps — the stem render runs **invisibly in their own
login session**: no window appears, **the cursor never moves**, and keyboard focus
is never stolen (or is stolen for a sub-second moment that is masked).

## 2. What "headless/invisible" means here (don't chase the wrong one)

- **Target (achievable):** invisible & automatic *inside the active session*.
- **Not possible on macOS:** running Logic with **nobody logged in** / as a pure
  daemon. Any GUI app needs a live window-server session. Ignore this definition.
- **Explicitly rejected:** a separate "render account" / Fast User Switching as the
  *primary* design. The app is **drag-and-drop and the user actively picks which
  project goes on which renderer** — you cannot drag a file into another user's
  session, so the worker must live in the user's own session. (A second machine is
  kept only as the optional Tier 2 "containment" fallback, see §9.)

## 3. Architecture decision — three tiers, build in order

| Tier | What | Setup | Result | Use when |
|------|------|-------|--------|----------|
| **0 — Foundation** | Element/value automation (no keystrokes, no frontmost, no cursor) + `headless` flag + App-Nap guard + DialogGuard | none | Logic renders with **zero** focus/cursor interference | **Always. Do this first.** |
| **1 — In-session invisibility** | + virtual (off-screen) display to host any window Logic does raise; + keyboard event-tap (only if any keystroke remains) | none (private APIs) | Window never seen even if Logic must come forward | Only if Tier 0 leaves a visible artifact |
| **2 — Containment (optional)** | Second Mac / login session as a render worker, UI forwards jobs over the network | one-time (~15 min) | Bulletproof: failures can't reach the user's screen | Only if "literally never any flicker, ever" is required |

**Logic verdict: Tier 0 alone is expected to fully reach the goal.** Logic is
already element-driven; once the few keystrokes are removed it needs no virtual
display and no event-tap. Tiers 1–2 are documented for completeness and for parity
with the FL/Ableton handoffs, but Logic should not need them.

## 4. Current focus-grab surface (the only things to fix)

All in `python/logic_render.py`:

| # | Location | Today | Fix |
|---|----------|-------|-----|
| 1 | `export_stems()` open-dialog block | `set frontmost to true` then click Export menu item | drop frontmost on headless path; menu-bar element click works backgrounded |
| 2 | `export_stems()` main block | `⌘⇧G` + `⌘A` + `keystroke "<path>"` + `keystroke return` | set the save-panel path **by element value**, no keystrokes |
| 3 | `quit_logic()` | `set frontmost to true` + `⌘Q` | `tell application "Logic Pro X" to quit` + existing `_click_dont_save()` |

Already element-based & safe (leave alone): Export menu item, File Format → WAVE,
Normalize → Off, Bypass checkbox, Export button, `_click_dont_save()`.

## 5. Tier 0 — Foundation (the real work)

1. **Destination by element, not keystrokes.** Probe the export ("Open") dialog's
   element tree and set the path field's accessibility *value* directly
   (`set value of text field 1 of w to "<path>"` — confirm the real element first).
   Keep the `⌘⇧G` keystroke path behind `if not self.headless:` as a fallback.
2. **Remove `set frontmost to true`** on the headless path. Verify menu-bar and
   dialog element clicks succeed against a **backgrounded** Logic.
3. **Quit by app command**, not `⌘Q` (see §4 #3). Project still never saved.
4. **`headless` flag** (default **on**) threaded `server.py → stem_exporter.py →
   LogicRenderBridge`. Old keystroke/frontmost path = the `not headless` fallback.
5. **Never move the cursor.** Logic has no coordinate-click path today — keep it
   that way (no `cliclick`, no pixel clicks ever).
6. **App-Nap / sleep guard:** set `NSAppSleepDisabled` for the server and wrap each
   render in `caffeinate -dimsu` so a backgrounded/occluded Logic isn't throttled.
7. **(Belt-and-suspenders, usually unnecessary for Logic) idle-gap masking:** if any
   single keystroke proves unavoidable, only fire it after detecting an input-idle
   gap (read seconds-since-last-event), snapshot the frontmost app, act, restore.

## 6. Shared DialogGuard module (build once, reuse in all three renderers)

Unexpected Logic pop-ups (missing plug-in, sample-rate mismatch, "save changes",
overwrite, crash recovery) are the main thing that can leak onto the screen or stall
a render. Generalize the existing `dismiss_macos_crash_reporter()` into a reusable
guard:

1. **Detect (event-driven):** an `AXObserver` on the Logic process for
   `kAXWindowCreatedNotification` / sheet-created, plus watch the `Problem Reporter`
   process. Sub-second reaction, no polling.
2. **Read:** pull the new window/sheet's title, static-text body, and the list of
   button names. Produce `{title, body, buttons[]}`.
3. **Decide:**
   - **Rule table (deterministic):** known patterns → action. e.g. save-changes →
     "Don't Save"; overwrite → "Replace"; sample-rate mismatch → safe default;
     missing plug-in → "OK"/Continue; crash recovery → decline (never "Reopen").
   - **Safety policy for unknowns:** never click a destructive-verb button
     (Delete/Discard/Overwrite/Move to Trash) unless explicitly whitelisted; prefer
     a non-destructive dismiss; if nothing matches confidently → **pause the job and
     notify**, don't guess.
   - *(Optional)* feed `{title, body, buttons}` to a small/local classifier for the
     fuzzy middle, with the safety policy still on top.
4. **Learn-loop:** log every unknown dialog (title/body/buttons + screenshot) so the
   rule table grows; a novel dialog pauses safely once, you add a rule, it's handled
   next time.

## 7. Popup research plan (build the rule table up front)

You can't enumerate *every* possible Logic dialog (closed source, state/plugin/
version dependent), but you can cover the **render path** (open → export → quit),
which is a small set. Logic is the **best case** here because it's native Cocoa:

1. **String-dump the app bundle.** Read Logic's `.lproj` `.strings` and nib/xib
   resources to extract alert titles, bodies, and button labels without triggering
   them. (Needs read access to `/Applications/Logic Pro X.app`.)
2. **Manuals/forums** for the named warnings/errors.
3. **Empirical capture + error injection:** run many fixtures and deliberately
   create conditions — remove a plug-in, unlink an audio file, set a sample-rate
   mismatch, point at a read-only/full output folder, open a newer-version project,
   force a crash — logging each dialog via the DialogGuard.

Deliverable: `docs/2026-06-28/logic_dialog_catalog.md` + a `dialog_rules` config the
DialogGuard loads.

## 8. Tier 1 — In-session invisibility (only if Tier 0 leaves an artifact)

Not expected for Logic. If ever needed: host any Logic window on a **virtual
off-screen display** (private `CGVirtualDisplay`, or shell out to a maintained app
like BetterDisplay) so it's drawn where the user can't see it; add a keyboard
**event-tap** that buffers physical keystrokes and replays them to the prior app for
any unavoidable focus moment (must run a watchdog for `kCGEventTapDisabledByTimeout`
and **fail open** so the keyboard can never be left dead). Residual: a sub-second
menu-bar flick if Logic must ever be frontmost.

## 9. Tier 2 — Containment (optional, bulletproof)

A second Mac (or a background login session) runs the render worker; the UI forwards
jobs over localhost/LAN and exchanges files via a shared folder. Failures (stray
dialogs, crashes) physically cannot touch the user's screen. Cost: one-time per-user
setup that **cannot be cloned/skipped** — Apple stores Accessibility/Automation
grants per-user in a SIP-protected DB; only enterprise MDM (PPPC) can pre-grant, and
that requires MDM enrollment. So budget ~15 min of permission clicks + DAW auth.
Logic licenses fine via the same Apple ID on the second account/Mac.

## 10. Ordered prompts for Claude Code

> **Branch discipline (CLAUDE.md):** the **user** creates the next
> `logic-renderer-v*` branch before launching Claude Code. Claude Code only
> *confirms* it — never create/switch/delete branches, never `git push`, commit only
> when asked. Element-level System Events only; never save the project; native
> sample rate.

**P0 — confirm & map.** Confirm the `logic-renderer-v*` branch. Read `CLAUDE.md`,
this handoff, `python/logic_render.py`, `stem_exporter.py`, `server.py`. List every
`set frontmost`, `keystroke`, `key code`. Confirm there are no coordinate clicks.

**P1 — probe the save panel.** With the export dialog open, dump its element tree
(text fields/pop-ups/checkboxes/buttons with name/role/value). Save under
`docs/2026-06-28/`. Identify the element holding the destination path.

**P2 — destination by value.** Replace the `⌘⇧G`+keystroke destination with setting
the path field's value. Keep the keystroke path behind `if not self.headless:`.

**P3 — drop frontmost.** Remove `set frontmost to true` from `export_stems()` and
`quit_logic()` on the headless path; verify element clicks work backgrounded.

**P4 — element quit.** Replace `⌘Q` with `tell application "Logic Pro X" to quit` +
`_click_dont_save()`. Confirm never-saved.

**P5 — headless flag + App-Nap guard.** Add `headless` (default on) through the
orchestrator; `NSAppSleepDisabled` + `caffeinate -dimsu`. Document in `CLAUDE.md`.

**P6 — DialogGuard.** Build the §6 module (AX-notification watcher + rule table +
safe policy + learn-loop), generalizing `dismiss_macos_crash_reporter`. Wire it
around the export.

**P7 — dialog catalog.** Do the §7 research (needs read access to
`/Applications/Logic Pro X.app`); produce `logic_dialog_catalog.md` + `dialog_rules`.

**P8 — verify (see §11).**

## 11. Verification (must pass)

1. **Invisibility:** type continuously in TextEdit + park the mouse in a corner;
   run a full render. Pass = no window appears, cursor never moves, typing never
   interrupted.
2. **Output:** `01_With_FX` + `03_Raw` at native sample rate, byte-stable vs.
   pre-change; T11 guard still passes.
3. **Never-saved:** `.logicx` mtime unchanged.
4. **DialogGuard:** inject a known dialog (e.g. trigger overwrite) → auto-handled;
   inject an unknown → job pauses + logs rather than mis-clicks.
5. **Fallback:** `headless=False` → old path still works.
6. **Audio-identical proof:** diff before/after WAV sets for one fixture (subagent).
