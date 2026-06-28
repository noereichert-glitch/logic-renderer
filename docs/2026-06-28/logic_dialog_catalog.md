# Logic — Dialog Catalog (seed for DialogGuard, P6/P7)

**Date started:** 2026-06-28
**Purpose:** Running catalog of pop-ups seen on the render path (open → export →
quit), and the safe action for each. This file is the source for the DialogGuard
`dialog_rules` config (handoff §6/§7). Append every new dialog encountered here.

---

## ⚠️ DialogGuard requirements discovered during P1 (must implement)

1. **Clear free-floating `AXDialog`s, not just sheets.** At least one blocking
   alert appears as an independent floating window (`AXDialog`), NOT as a sheet
   attached to a window. A guard that only sweeps `sheets of window …` will MISS
   it. The detector must handle `kAXWindowCreatedNotification` for free dialogs in
   addition to sheet-created.
2. **Readiness check must not pass while a blocking free `AXDialog` is present.**
   During P1, `wait_for_logic_ready` reported "ready" even though a free
   `AXDialog` was blocking the Export menu. Fix: treat a blocking free dialog the
   same as a blocking sheet when deciding readiness, and let the DialogGuard clear
   it before proceeding.

---

## Catalog entries

| # | Trigger / when | Title / body (verbatim) | Buttons | Window kind | Safe action | Notes |
|---|----------------|-------------------------|---------|-------------|-------------|-------|
| 1 | Logic launch (this machine) | "The last selected audio interface is not available. The previously selected interface 'MacBook Pro Speakers' will be used instead for this session." | `Open Settings`, `OK` | **free `AXDialog`** (not a sheet) | **click `OK`** | Blocks the Export menu until cleared; readiness check wrongly passed while it was up (see requirement #2). Found during P1, 2026-06-28. **AUTO-HANDLED ✅** by `_auto_dismiss_dialogs` (clicks `OK`, never `Open Settings`). |

## Implementation status (2026-06-28)

Requirements #1 and #2 are **implemented (minimal, headless path)** in
`python/logic_render.py` and gated behind `self.headless` (legacy unchanged):

- **`LogicRenderBridge._auto_dismiss_dialogs()`** — scans the Logic process for
  blocking pop-ups, **both free `AXDialog` windows AND sheets**, reads each one's
  buttons + static-text body, and clicks a SAFE whitelisted button only:
  `{"OK","Continue","Close"}` or a button starting with `"Use "`. It NEVER clicks a
  destructive verb (`Delete/Discard/Overwrite/Replace/Move to Trash`) or
  `"Open Settings"`; a dialog with no safe button is left untouched (fail safe).
  Element clicks only → works backgrounded, **cursor never moves**. Logs every
  dialog it clears (title / body / button).
- Called (a) inside `wait_for_logic_ready()` each poll tick, and (b) right before
  opening the Export menu in `export_stems()`.
- **Requirement #2 fix:** `wait_for_logic_ready()` (headless) now returns "no" while
  any free `AXDialog` exists, so readiness can't pass with a blocking alert up.

**Verification (2026-06-28, headless, Logic backgrounded, hands-off, 3/3 runs):**
the entry-1 audio-interface alert appeared on every launch and was auto-cleared by
clicking `OK`; the frontmost app stayed **TextEdit** before and after (focus never
stolen), the free dialog was gone afterward, and the **cursor did not move**
(`(1038.3, 538.6)` unchanged across each dismiss and each whole run).

<!-- Append new dialogs below as they are encountered (learn-loop, handoff §6).
Always record: trigger, verbatim title/body, button list, window kind
(sheet vs free AXDialog vs separate process e.g. Problem Reporter), the safe
non-destructive action, and whether AX could read/click it. Never auto-click a
destructive button (Delete/Discard/Overwrite/Move to Trash) unless whitelisted. -->
