# P3 — Backgrounded actions + focus masking (discovery & implementation)

**Date:** 2026-06-28
**Scope:** Tier 0, prompts P2–P3 of `Invisible_Render_Handoff_v1.md`.
**Touches:** `python/logic_render.py` only (behind `if not self.headless:`).
**Companion:** `probe_save_panel.txt` (P1/P2), `logic_dialog_catalog.md` (DialogGuard).

---

## 1. Which export actions work against a BACKGROUNDED Logic?

Probed with Logic running but **Finder frontmost** (no `set frontmost` on Logic),
checking the frontmost app before/after each action (must stay Finder). Fixture:
`~/Desktop/logic test.logicx`.

| Action | Backgrounded? | Evidence |
|--------|---------------|----------|
| Export **menu-item** click (`menu bar 1 … All Tracks as Audio Files…`) | ✅ YES | dialog opened, front Finder→Finder |
| **Show Options** button click | ✅ YES | "Hide Options" appeared, front stayed Finder |
| Pop-up **set by AXValue** (`set value of pop up button …`) | ❌ NO | value stayed `WAVE` (no-op) — must click-open+select |
| Pop-up **click-open + select menu item** (Format/Normalize/Range) | ✅ YES | menuItems=3, value→WAVE, front stayed Finder |
| **Checkbox** click (Bypass Effect Plug-ins) | ✅ YES | value 0→1, front stayed Finder |
| **Export** button click | ✅ YES | full headless export bounced 4 WAVs, front stayed Finder |
| Destination text field **set by AXValue** | ✅ YES | (P1) set while Finder frontmost, read back OK |
| `keystroke` (⌘⇧G, Return) | ❌ NO (by nature) | macOS keystrokes always go to the frontmost app |

**Conclusion:** every ELEMENT action on the export path works backgrounded. The
ONLY actions needing Logic frontmost are the two fixed keystroke chords **⌘⇧G**
(summon the Go-to-Folder field) and **Return** (confirm it). `set frontmost` was
removed from the headless menu-open step and is not used for any element action.

## 2. Focus masking for the two chords (P3 part 2)

The destination's ⌘⇧G + AX set-value + Return are run as a single **masked**
moment (`LogicRenderBridge._run_masked_keys`):

1. **Idle-gate** — wait until `HIDIdleTime` (via `ioreg -c IOHIDSystem`) shows the
   user has been idle ≥ `self._idle_min` (0.7s), up to `self._idle_timeout` (60s),
   then proceed best-effort so a render can never hang. (`_input_idle_seconds`
   fails safe to 0.0 = "active" if it can't read.)
2. **Snapshot** the user's frontmost app (`_frontmost_app_name`).
3. **Flick Logic frontmost** (`set frontmost of process … to true`), send the
   chords + set the field value, then in a `finally`
4. **Restore** the prior app (`_set_app_frontmost(prior)`) — always, even on error.

**The cursor is never moved** — no coordinate/`cliclick`/`CGEvent` anywhere;
keystrokes and app-activation don't move the pointer.

### End-to-end verification (headless, Logic backgrounded)
Sampling the frontmost app every 0.2s across a full 16.6s export:
`Finder: 38, Logic Pro X: 6` → Logic was frontmost only **~1.2s** (the masked
moment); focus **restored to Finder** afterward; **4 WAVs** in the dest; Logic
quit clean; `.logicx` mtime unchanged (Jun 6 — **never saved**).

**Residual:** that ~1.2s is Logic visibly coming forward for the chords — the
documented Tier-0 residual (a brief menu-bar/window flick). Eliminating even that
is Tier 1 (virtual display), not needed unless "never any flicker" is required.

## 3. Staging-folder idea (FL/reg.xml-style) — DEAD END

- Logic persists the export panel's last dir in **`com.apple.logic10` →
  `NSNavLastRootDirectory`**, a **plain POSIX path** (Logic Pro X is not sandboxed,
  so no security-scoped bookmark blob). It's freely `defaults read/write`-able.
- **Flavor A (sticky after one export):** ❌ after exporting to a folder, quit +
  relaunch → the export panel reopened at `Where: 'Logic'` (= `~/Music/Logic`),
  ignoring the persisted path.
- **Flavor B (pre-write before launch):** ❌ `defaults write NSNavLastRootDirectory
  <staging>` (+ `killall cfprefsd`) before launch → panel still opened at `Logic`.
- **Verdict:** Logic resets the export panel to its default `~/Music/Logic` on every
  launch and ignores `NSNavLastRootDirectory`. The reg.xml-style "persist a path the
  panel honors on open" approach does **not** work for Logic. A shared staging folder
  would also *add* WAV move/collision complexity vs. today's per-project export +
  `sort_wavs_into_subfolder`. Do not pursue.

## 4. Within-session stickiness — USABLE (next small step, not P3)

In a **single** Logic session, after one ⌘⇧G export to folder X, reopening the
export dialog showed `Where: 'X'` — the panel remembers the last export dir **within
the session**. Our orchestrator runs BOTH passes (wet + raw) in one session into the
same folder, so **pass 2 can skip ⌘⇧G + Return and just click Export**.

Planned as a separate guarded step (after P3): on pass 2, read the `Where:` pop-up
value first; if it matches the target folder, click Export directly; otherwise fall
back to the masked ⌘⇧G path. Not implemented yet.

## 5. Code shape (logic_render.py, all behind `if not self.headless:`)

- `__init__(headless=True)` + idle tunables `_idle_min` / `_idle_timeout`.
- Module helpers: `_input_idle_seconds`, `_frontmost_app_name`, `_set_app_frontmost`.
- Methods: `_wait_input_idle`, `_run_masked_keys`.
- `export_stems`: headless → backgrounded menu click; Show Options (bg); masked
  destination; shared `controls_body` (Format/Bypass/Normalize/Range/Export) run
  backgrounded. Legacy → unchanged frontmost-held single script with path typing.
- `quit_logic` still uses frontmost + ⌘Q — that's **P4**, deliberately untouched here.
