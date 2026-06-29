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

---

# Candidate entries — from static string-dump (2026-06-29) — NOT yet observed live

**Method (RESEARCH ONLY, no dialogs triggered):** read Logic's bundled string
table and extracted the render-path alert strings verbatim. No automation was run
against Logic; none of these have been seen live in our flow yet. They are
**candidates** to seed the DialogGuard rule table; promote one to a numbered live
entry above only after it is actually observed.

## Environment this dump describes
- **Bundle:** `/Applications/Logic Pro X.app` (the modern *Logic Pro 11* ships in a
  bundle still literally named `Logic Pro X.app` on this machine).
- **Version:** Logic Pro **11.0.1** (build 6029). **Bundle id** `com.apple.logic10`.
- **Process / executable name:** **`Logic Pro X`** — matches `LOGIC_PROCESS_NAME`
  and what the AX code targets. (No "Logic Pro" process on this install.)
- **String table:** `Contents/Resources/en.lproj/Localizable.strings`
  (Apple binary plist, 9,714 keys), German sibling `de.lproj/Localizable.strings`.

## ⚠️ Locale finding (decisive for the guard's button whitelist)
- System: `AppleLocale = en_AT`, `AppleLanguages = ("en-AT", "de-AT")`. Logic has
  no per-app language override (`com.apple.logic10` AppleLanguages unset). **First
  preferred language is English → the live UI renders in ENGLISH.** Entry #1's
  English strings match the live capture, confirming this.
- **BUT German (`de-AT`) is the secondary system language and `de.lproj` is present.**
  If the user ever reorders system languages to German, Logic's dialogs (and their
  **button labels**) switch to German. Our current `_click_dont_save()` whitelist is
  English-only (`"Don't Save"`, `"Don’t Save"`, `"Delete"`) and `_auto_dismiss_dialogs()`
  whitelists `{"OK","Continue","Close"}` + `"Use "`. On a German UI these would MISS
  the buttons. **DialogGuard must match localized button labels** (table below gives
  the German equivalents). Not a live risk *today* (English UI) — but a latent one.

## Button-label map (EN → DE), verbatim from the table
| English | German | Role for us |
|---|---|---|
| `OK` | `OK` | safe dismiss |
| `Cancel` | `Abbrechen` | safe (abort), non-destructive |
| `Continue` | `Weiter` | safe dismiss |
| `Don’t Save` | `Nicht sichern` | **safe in our never-save flow** |
| `Save` | `Sichern` | **NEVER click** (would persist the project) |
| `Delete` | `Löschen` | safe **only** as the save-discard button; destructive elsewhere |
| `Ignore` | `Ignorieren` | safe (proceed without the missing asset) |
| `Locate` | `Suchen` | avoid (opens a file browser → stalls headless) |
| `Skip` / `Skip All` | `Überspringen` / `Alle überspringen` | safe (proceed) |
| `Change` | `Ändern` | context-dependent (e.g. change project SR) → pause |
| `Don’t Change` | `Nicht ändern` | safe (keep native SR) |
| `Replace` | `Ersetzen` | **destructive — whitelist only for our own export root** |
| `Overwrite` | `Überschreiben` | **destructive — never auto-click** |
| `Use …` | `Verwenden …` | safe (accept default device, entry #1) |
| `Open Settings` | `Einstellungen öffnen` | **never** (leaves the render path) |
| `Proceed` | `Fortfahren` | context-dependent → pause unless known-safe |
| `Recover` | `Wiederherstellen` | **never auto-click** (crash/backup recovery) |

## Candidate dialogs (render path: open → export → quit)

### C1 — Save changes on quit  *(already handled live by `quit_logic`/`_click_dont_save`)*
- **Title/body (verbatim, one of):** `Do you want to save the changes you made to “%@”?`
  · `Do you want to save the changes made to the Alternative “%@”?`
  · `Do you want to save the document “%@”?`
  Body: `Your changes will be lost if you don’t save them.` /
  `Changes in the current Alternative will be lost if you don’t save them.`
- **Buttons:** `Save` / `Don’t Save` / `Cancel` (some variants use `Delete` as the
  discard verb). DE: `Sichern` / `Nicht sichern` / `Abbrechen` / `Löschen`.
- **Class:** safe non-destructive dismiss (in OUR flow). **Action:** click
  `Don’t Save` (`Nicht sichern`) — never `Save`. This is exactly what the headless
  quit already does; listed here so the generalized guard inherits it (incl. DE).

### C2 — Export overwrite  *(already defensively handled by `_dismiss_replace_sheet`)*
- **Body:** `An item named “%@” already exists in this location. Do you want to
  replace it with the one you are exporting?` · `A file or folder with the same name
  already exists in %@. Replacing it will overwrite its current contents.` ·
  `File “%@” exists.\nReplace the file or save with a unique file name?`
- **Buttons:** `Replace` / `Cancel` (`Ersetzen` / `Abbrechen`).
- **Class:** **whitelisted-destructive (explicit, our root only).** `Replace` is a
  destructive verb; we permit it ONLY because we sort WAVs between passes so the
  export root is our own and empty. **Preferred:** avoid the dialog by guaranteeing
  an empty destination; if it appears, `Replace` is acceptable per the §6 explicit
  whitelist. The generic guard must NOT click `Replace` for any other dialog.

### C3 — Sample-rate mismatch / change
- **Body:** `Change Project Sample Rate to %@?\nOne or more added audio files have a
  sample rate different than the project sample rate. Do you want to change the
  project sample rate…` · `Could not switch to new sample rate!` · `Sample rate in
  the movie doesn’t match that of the project.…`
- **Buttons:** `Change` / `Don’t Change` / `Cancel` (`Ändern` / `Nicht ändern` /
  `Abbrechen`); error variants `OK`.
- **Class:** **pause-and-notify** (the "Change…" prompt). Changing the project SR
  would violate "render at native sample rate." If forced to act, the native-SR-safe
  choice is `Don’t Change`. Primarily fires on *adding* files, not plain open, so it
  is unlikely on our path — but if seen, pause rather than guess. Pure error variants
  (`Could not switch…`) → safe `OK`.

### C4 — Missing / incompatible plug-in
- **Body:** `Plug-in “%@” for device “%@” could not be loaded.` · `Plug-in for
  device “%@” is missing.` · `The “%1$s” plug-in is not available on your system…` ·
  `Audio Units plug-in missing on frozen track\nTrack %@ is frozen and uses an Audio
  Units plug-in which is not installed… Do you want to unfreeze…?`
- **Buttons:** informational variants `OK`; the frozen-track variant `Unfreeze` /
  `Cancel`; the replacement-offer variant `Yes`/`No`-style.
- **Class:** **pause-and-notify.** A missing plug-in can silently change or null a
  stem's audio — auto-dismissing risks shipping a wrong `01_With_FX`/`03_Raw` set.
  Pure-informational `… could not be loaded.` may be `OK`'d, but treat the
  interactive variants (`Unfreeze`?) as pause-worthy. Never auto-`Unfreeze`.

### C5 — Missing audio files
- **Body:** `Missing file in Sampler Instrument\nThe Sampler Instrument “%@” is
  missing the audio file “%@”.\n\nClick ”Ignore” to continue without the audio file,
  click ”Loc[ate]”…` · `Missing Audio Files in Plug-ins` · `This Logic Pro for Mac
  project is missing audio files. Consolidate…`
- **Buttons:** `Ignore` / `Locate` / `Skip` (`Ignorieren` / `Suchen` /
  `Überspringen`).
- **Class:** **pause-and-notify** (audio correctness). If a hands-off default is
  needed, `Ignore`/`Skip` *proceeds* (non-destructive, no file browser) whereas
  `Locate` opens a browser that would stall a headless run — so **never** `Locate`.
  Default lean: pause; fallback non-stalling dismiss = `Ignore`.

### C6 — Newer-version project
- **Body (blocking):** `This project can’t be loaded because it was created by a
  newer Logic Pro version.\nPlease update Logic Pro!` — **Buttons:** `OK`. Job cannot
  proceed; **class: safe `OK`, then fail the job cleanly** (no stems possible).
- **Body (warning, still loads):** `Warning! This project was created by a newer
  Logic Pro version.\nThis may cause problems.\nPlease update Logic Pro.` — **Buttons:**
  `OK`/`Cancel`. **Class: pause-and-notify** — it loads but output may be wrong;
  don't silently proceed on an unattended render.

### C7 — Bounce / export failed
- **Body:** `The export operation failed.` — **Buttons:** `OK`.
- **Class:** safe `OK`, then surface the failure to the orchestrator (retry/relaunch).

### C8 — Crash recovery / reopen / revert-to-backup
- **macOS Problem Reporter** ("…quit unexpectedly", `Reopen`/`OK`/`Ignore`) is a
  *separate process*, already handled by `dismiss_macos_crash_reporter()` — **never
  click `Reopen`**.
- **Logic's own:** `Revert to Backup?` · `The data for the chosen alternative is
  corrupt. The backup from %@ has been used instead.` — **Buttons:** `Recover` /
  `Revert to Backup` / `Cancel` (`Wiederherstellen` / `Abbrechen`).
- **Class:** **never auto-click `Recover`/`Reopen`/`Revert`** → **pause-and-notify**.

### C9 — Audio-interface unavailable (sibling of live entry #1)
- A second wording exists alongside entry #1: `The previously selected audio
  interface is not available.\nThe built-in audio inputs and outputs of the ^C will
  be used instead for this session.` — **Buttons:** `Use …` / `OK` / `Open Settings`.
- **Class:** safe dismiss — click `OK` or the `Use …` button, **never** `Open
  Settings`. Same handling as entry #1; included so the rule matches both wordings.

---

# Seed `dialog_rules` (draft schema for the future DialogGuard to load)

> **⚠️ SUPERSEDED by "Step 1b — finalized, language-agnostic rule table" below
> (2026-06-29).** This first seed matched on English/German surface text; the Step 1b
> table re-anchors every rule on the stable `.strings` **key** and resolves the match
> set across all 7 shipped locales. Kept here for history; the guard loads the 1b table.

Match on **body substring(s)** (localized, EN+DE) — NOT on button name alone, so a
generic verb like `Delete`/`Replace` is only ever clicked in the dialog where it is
safe. Evaluate `pause` rules before `dismiss` rules. `click` lists are tried in
order; if none present → fall through to `pause`.

```yaml
# action ∈ { dismiss_safe, dismiss_whitelisted_destructive, pause_notify, fail_job }
# never_click is a hard global stop-list applied to EVERY rule.
never_click: ["Save", "Sichern", "Overwrite", "Überschreiben", "Move to Trash",
              "Open Settings", "Einstellungen öffnen", "Reopen", "Recover",
              "Wiederherstellen", "Locate", "Suchen", "Discard"]

rules:
  - id: save_changes_on_quit            # C1 (already live in quit_logic)
    match_body_any: ["save the changes", "Änderungen", "changes will be lost",
                     "Änderungen", "save the document", "Dokument"]
    action: dismiss_safe
    click: ["Don’t Save", "Nicht sichern"]   # Delete only if body is a save-prompt

  - id: audio_interface_unavailable     # entry #1 + C9 (entry #1 live-confirmed)
    match_body_any: ["audio interface is not available", "Audio-Schnittstelle",
                     "will be used instead for this session", "für diese Sitzung"]
    action: dismiss_safe
    click: ["OK", "Use ", "Verwenden"]

  - id: export_overwrite                # C2 (whitelisted destructive, our root only)
    match_body_any: ["replace it with the one you are exporting",
                     "already exists in this location", "zu exportierende",
                     "exists.\nReplace the file"]
    action: dismiss_whitelisted_destructive
    click: ["Replace", "Ersetzen"]

  - id: export_failed                   # C7
    match_body_any: ["export operation failed", "Exportvorgang ist fehlgeschlagen"]
    action: fail_job
    click: ["OK"]

  - id: newer_version_blocking          # C6 (blocking)
    match_body_any: ["can’t be loaded because it was created by a newer",
                     "kann nicht geladen werden, da es mit einer neueren"]
    action: fail_job
    click: ["OK"]

  - id: sample_rate_change              # C3 (native-SR safety)
    match_body_any: ["Change Project Sample Rate", "Projekt-Sample-Rate",
                     "different than the project sample rate"]
    action: pause_notify                # if forced: prefer "Don’t Change"/"Nicht ändern"

  - id: missing_plugin                  # C4 (audio correctness)
    match_body_any: ["plug-in", "Plug-in"]
    match_body_also_any: ["missing", "could not be loaded", "not available",
                          "fehlt", "nicht verfügbar", "nicht geladen", "frozen"]
    action: pause_notify

  - id: missing_audio_files             # C5 (audio correctness; never Locate)
    match_body_any: ["missing the audio file", "missing audio files",
                     "fehlt die Audiodatei", "Audiodateien fehlen"]
    action: pause_notify                # fallback non-stalling dismiss: Ignore/Ignorieren

  - id: newer_version_warning           # C6 (loads but risky)
    match_body_any: ["created by a newer Logic Pro version", "This may cause problems",
                     "von einer neueren Version von Logic Pro erstellt"]
    action: pause_notify

  - id: crash_recovery_revert           # C8 (never Recover/Reopen/Revert)
    match_body_any: ["Revert to Backup", "Zurück zu Sicherungskopie",
                     "the chosen alternative is corrupt", "beschädigt"]
    action: pause_notify
```

**Open follow-ups for the live-capture phase (P7):** confirm the exact *button set*
attached to each candidate (the flat string table can't prove which buttons a given
alert shows); decide whether `missing_plugin` should ever auto-`OK` its purely
informational variants; and localize the existing `_click_dont_save()` /
`_auto_dismiss_dialogs()` whitelists to cover DE before any German UI is in scope.

---

# Step 1b — finalized, language-agnostic rule table (2026-06-29)

Doc/research only — no code changed, no dialogs triggered. Resolves C2 against the
orchestrator, hardens C3/C5, and re-anchors every rule on the stable `.strings` key
so the guard is language-agnostic across all 7 shipped locales.

## `.strings` key nature → anchoring quality
Logic's tables are **English-as-key**, *not* symbolic: 8,098 / 9,714 entries have
`key == value`; the remainder differ only because the **key** is the canonical
English template carrying tokens (`^P` = product name, `^C` = device, `%@`/`%ld`/
`%1$s` = runtime fills) while the value is the resolved English. Every other locale
(`de, es, fr, ja, ko, zh_CN` — all 9,714 keys) is keyed by those **same English
strings** → German/Japanese/… values. Verified: all render-path body anchors and all
18 render-path buttons resolve in **all 7 locales** by looking up the English key.

**Implication — anchoring is GOOD but version-bound.** We anchor each rule on the
English key; the guard resolves the localized match set by reading that key from
Logic's active `.lproj` (or all of them) at load. Because the key *is* English text,
a future Logic that reworks the English wording shifts the key → **re-dump per Logic
version** (record the version; this dump = **11.0.1 / build 6029**). Truly symbolic
keys would be more robust, but Apple didn't ship those here.

**Matcher note (required):** the live dialog has tokens already substituted, so the
matcher must treat `%@ ^P ^C ^p %ld %d %1$s %2$s` as wildcards — split each anchor on
its tokens and require the literal segments present in order (don't string-equals).

## C2 (overwrite / Replace)

> **OPEN — product decision pending:** how to guarantee a clean export destination /
> handle the overwrite-on-pass-1 case.
> **Option A:** empty the per-job root at job start (only our artifacts, else pause)
> → lets `Replace` be dropped entirely.
> **Option B (current):** keep the gated `Replace` (G1 dest = our per-job root ∧
> G2 collider = our own `.wav` ∧ G3 pass 1).
> **Using B for now; revisit.** The gated `Replace` rule stays in `dialog_rules.yaml`
> and `dialog_guard.py` until this is decided.

### Analysis. Case = **NO** (not guaranteed fresh).
Read `python/stem_exporter.py`. The destination is `output_folder/<project_name>`
created with `os.makedirs(..., exist_ok=True)`; per-track WAVs bounce **loose into
that root**, then `sort_wavs_into_subfolder()` moves them into `01_With_FX` /
`03_Raw`. So the root is emptied **between passes**, and `_cleanup_stale_wavs()`
clears loose root WAVs **on a crash-retry within a job** — but **nothing empties the
root at job START** (only `exist_ok=True`). A prior job that was killed before its
sort, or a re-export of the same project, can therefore leave same-named WAVs in the
root and trigger an overwrite prompt on pass 1. **⇒ a clean per-job destination is
NOT strictly guaranteed.**

Therefore C2 is **not** blanket pause-notify; `Replace` stays permitted **only behind
a gate the guard can verify**, else pause-notify:

- **G1 — destination is our own per-job folder:** the export dialog's `Where:` value
  resolves to the expected `output_folder/<project_name>` root (our scratch area),
  not a user/library/system path.
- **G2 — collider is our own transient output:** the colliding filename ends in
  `.wav` and sits in that root (the root only ever holds Logic's per-track stem
  exports we are about to regenerate and immediately sort away).
- **G3 — pass context:** only on pass 1 (pass 2's root is already emptied by the pass-1
  sort, so an overwrite there is unexpected → pause-notify).

If **G1∧G2∧G3** hold, the collider is a leftover of *our own* prior export inside
*our own* folder → `Replace` is safe (matches today's `_dismiss_replace_sheet`). If
any gate fails → **pause-notify** (do not click `Replace`).

> **Recommended hardening (orchestrator, separate code step — out of scope here):**
> empty the `<project_name>` root at job start (or export each pass into its own fresh
> subfolder). That would make a clean destination a true invariant and let C2 drop to
> **pause-notify with no `Replace` whitelist at all** — the stronger §6-aligned state.

## C5 (missing audio files) — HARDENED → **pause-notify only**
Remove the "Ignore fallback." The guard must **never auto-`Ignore`** (proceeding
without media silently corrupts a stem) and **never `Locate`** (opens a file browser
→ stalls a headless run). Any missing-audio dialog → **pause and notify**, full stop.

## C3 (sample-rate) — unchanged: **pause-notify**
Keep pause-notify. Note for any future auto-handling: the **only** permissible click
is the **native-rate-preserving** button — `Don’t Change` (`Nicht ändern` / `No
cambiar` / `Ne pas changer` / `変更しない` / `변경 안 함` / `不更改`). Never `Change`.

## Global never-click stop-list — key-anchored, resolved per language
Defined by **key**, not English surface text. The guard expands each key via the
active `.lproj` (table below = the 7 shipped locales). `Delete` is deliberately **not**
global-never — it is the discard button inside the save-changes rule only; it stays
destructive (and forbidden) everywhere else by matching on body.

| key | en | de | es | fr | ja | ko | zh_CN |
|---|---|---|---|---|---|---|---|
| `Save` | Save | Sichern | Guardar | Enregistrer | 保存 | 저장 | 存储 |
| `Overwrite` | Overwrite | Überschreiben | Sobrescribir | Remplacer | 上書き | 덮어쓰기 | 覆盖 |
| `Open Settings` | Open Settings | Einstellungen öffnen | Abrir Ajustes | Ouvrir Réglages | “設定”を開く | 설정 열기 | 打开设置 |
| `Recover` | Recover | Wiederherstellen | Recuperar | Restaurer | 復元 | 복구 | 恢复 |
| `Locate` | Locate | Suchen | Localizar | Rechercher | 場所を指定 | 지정 | 查找 |

Plus hard literals never in this table but never clicked: `Reopen` / `Don’t Reopen`
(macOS Problem Reporter, separate process — handled there), `Move to Trash`,
`Discard`.

## Safe click-buttons referenced by rules (key → 7 locales)
| key | en | de | es | fr | ja | ko | zh_CN |
|---|---|---|---|---|---|---|---|
| `OK` | OK | OK | Aceptar | OK | OK | 확인 | 好 |
| `Don’t Save` | Don’t Save | Nicht sichern | No guardar | Ne pas enregistrer | 保存しない | 저장 안 함 | 不存储 |
| `Use` | Use | Verwenden | Usar | Utiliser | 使用 | 사용 | 使用 |
| `Replace` *(gated, C2)* | Replace | Ersetzen | Reemplazar | Remplacer | 置き換える | 대치 | 替换 |
| `Don’t Change` *(C3, if ever)* | Don’t Change | Nicht ändern | No cambiar | Ne pas changer | 変更しない | 변경 안 함 | 不更改 |

## Finalized key-anchored `dialog_rules` (the table the guard loads)
```yaml
# Each rule anchors on .strings KEY(s). At load the guard resolves body_keys and
# click/never_click to the localized strings via Logic's active .lproj (fallback:
# union of all shipped .lproj). Tokens (%@ ^P ^C %ld %1$s …) are wildcards.
# action ∈ { dismiss_safe, dismiss_gated, pause_notify, fail_job }
# Evaluate order: gated/fail/pause rules before dismiss_safe. NO match in the
# active language  →  pause_notify (FAIL-SAFE: never click an unrecognized dialog).

meta: { logic_version: "11.0.1", build: 6029, locales: [en,de,es,fr,ja,ko,zh_CN] }

never_click_keys: ["Save", "Overwrite", "Open Settings", "Recover", "Locate"]
never_click_literals: ["Reopen", "Don’t Reopen", "Move to Trash", "Discard"]

rules:
  - id: audio_interface_unavailable        # entry #1 (LIVE) + C9 sibling
    body_keys:
      - 'The last selected audio interface is not available.\nThe previously selected interface “%@” will be used instead for this session.'
      - 'The previously selected audio interface is not available.\nThe built-in audio inputs and outputs of the ^C will be used instead for this session.'
    action: dismiss_safe
    click_keys: ["OK", "Use"]

  - id: save_changes_on_quit               # C1 (already live in quit_logic)
    body_keys:
      - 'Do you want to save the changes you made to “%@”?'
      - 'Do you want to save the changes made to the Alternative “%@”?'
      - 'Do you want to save the document “%@”?'
      - 'Your changes will be lost if you don’t save them.'
    action: dismiss_safe
    click_keys: ["Don’t Save"]             # Delete allowed ONLY here (save-discard)

  - id: export_overwrite                   # C2 — GATED (see G1∧G2∧G3 above)
    body_keys:
      - 'An item named “%@” already exists in this location. Do you want to replace it with the one you are exporting?'
      - 'A file or folder with the same name already exists in %@. Replacing it will overwrite its current contents.'
    action: dismiss_gated
    gate: dest_is_per_job_root AND collider_is_our_wav AND pass==1
    click_keys: ["Replace"]                # only if gate passes; else pause_notify

  - id: export_failed                      # C7
    body_keys: ['The export operation failed.']
    action: fail_job
    click_keys: ["OK"]

  - id: newer_version_blocking             # C6 blocking
    body_keys: ['This project can’t be loaded because it was created by a newer ^P version.\nPlease update ^P!']
    action: fail_job
    click_keys: ["OK"]

  - id: newer_version_warning              # C6 warning (loads but risky)
    body_keys: ['Warning! This project was created by a newer ^P version.\nThis may cause problems.\nPlease update ^P.']
    action: pause_notify

  - id: sample_rate_change                 # C3 (native-SR safety)
    body_keys: ['Change Project Sample Rate to %@?\nOne or more added audio files have a sample rate different than the project sample rate. Do you want to change the project sample rate to match the highest file sample rate?']
    action: pause_notify                   # if ever auto: click_keys:["Don’t Change"] ONLY

  - id: missing_audio_files                # C5 (HARDENED: never Ignore/Locate)
    body_keys:
      - 'Missing file in Sampler Instrument\nThe Sampler Instrument “%@” is missing the audio file “%@”.\n'
      - 'Missing Audio Files in Plug-ins'
    action: pause_notify

  - id: missing_plugin                     # C4 (audio correctness)
    body_keys:
      - 'Plug-in “%@” for device “%@” could not be loaded.'
      - 'Plug-in for device “%@” is missing.'
      - 'Audio Units plug-in missing on frozen track\nTrack %@ is frozen and uses an Audio Units plug-in which is not installed on this system. Do you want to unfreeze the track?'
    action: pause_notify                   # never auto-Unfreeze

  - id: crash_recovery_revert              # C8 (never Recover/Revert)
    body_keys:
      - 'The data for the chosen alternative is corrupt. The backup from %@ has been used instead.'
    action: pause_notify
```

## Fail-safe policy (restated, unchanged)
Any dialog whose body matches **no** rule in the active language → **pause-notify,
never click**. The guard never guesses on an unrecognized alert; it logs
`{title, body, buttons}` (learn-loop, §6) and waits. The `never_click_*` lists are a
hard stop applied on top of every rule.

## Note (P6 detection surface, NOT a rule yet)
macOS **TCC/permission** prompts (Microphone/Files-and-Folders/Automation access) and
**disk-full / read-only volume** alerts can be raised by a **separate process**
(`tccd` / the system, or Finder-side), not by `Logic Pro X` — so an AX scan scoped to
Logic's process will MISS them, exactly like the `Problem Reporter` crash dialog. P6
must treat these as a **distinct detection surface**: watch the relevant system
process(es) in addition to Logic, and default to pause-notify. Catalog them live when
encountered (none observed yet).
