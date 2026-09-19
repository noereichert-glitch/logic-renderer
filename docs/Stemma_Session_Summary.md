---
title: "Stemma Session Summary"
subtitle: "Consolidated — through 19 September 2026"
date: "19 September 2026"
geometry: margin=2.5cm
fontsize: 11pt
---

# Recap — June & July 2026

Architecture: per-DAW renderers in separate repos, coordinated by a daemon through a shared
versioned contract; communication only via the job folder. Walking skeleton proven with a stubbed
Ableton export. **5 July:** the pipeline became real for Logic. **22 July:** DialogGuard rule C10;
the stemma library UI replaced the one-shot app; branch renamed logic-slice -> logic-and-UI.
**23 July:** the Stemma folder — a watched Finder folder that IS the library; aliases, never
copies; droplet; Finder-alias support.

# Recap — 24 August 2026

Root cause of a month of failures: **macOS Accessibility permission is inherited from the
launching app** — Terminal.app needed the grant. Driver hardening: 10-minute ready ceiling,
retryable export-dialog stage. Open case opened: the missing "Sum 8" summing stack.

# Recap — 7 September 2026

The staged-success ("checkpoint") model: outcomes ok / ok_warnings / failed with the border after
the raw-differs verify (owner's call: stems are the deliverable, packaging is bonus). Raw-differs
downgraded from a false-failure to an honest warning (no-FX projects ship). Robust cleanup
(.DS_Store scrub). The key insight that four roadmap items (pre-flight warning, completeness
check, silent-stem detection, effects check) are ONE feature: the missing `logicx_parser.py`,
Logic's twin of Ableton's `als_parser.py`. Busy-click patience (40 s). Date-audit: summaries are
now dated from the system clock, never from conversation memory.

# Recap — 10 September 2026

Sum 8 filed as an unreproduced ghost. Naming untangled: "Stemma" the repo (Noe's — old app + the
Ableton kitchen) vs "stemma" the product (the logic-renderer repo — current app + Logic kitchen).
Ableton integration plan of record: **a second backend on its own port, routed by file type; the
two backends' APIs are twins.** Live-warnings design agreed (raise warnings as they become
knowable; a mid-render warning is only actionable with a cancel button, so cancel came first).
The cancel button built and debugged live to a 1-second abort: Cmd-period posted straight into
Logic's process with Quartz, bounce-wait scans capped at 4 s (System Events serialises Apple
events and jams for 16-19 s against a pegged Logic), DialogGuard rule C11 `disk_too_slow`.

# Recap — 14 September 2026

Live warnings layers 1+2 built (pushed into the shared state as discovered; silent-stem scan,
pass symmetry, completeness). The "missing track" ghost root-caused: **a lit solo** silences
stack/DMD tracks and Trim Silence erases the file; fix = read mute/solo from the track headers,
clear solo with Option+S (only a System Events keystroke with Logic frontmost works), exclude
muted stems. Logic's export ignores mute, honours solo, skips region-less tracks. Cancel made
~1 s. Warning UI (green status + amber mark, hover card, click-to-pin cascade). Status column
widened and left-aligned. Light lavender retheme. DAW badges drawn in the palette: Logic platter,
"Live" wordmark, FL mango stencil traced from the real icon. Recon of the Ableton renderer and the
owner's sequencing: connect it as-is first, parity later. PR #2 opened (logic-and-UI into main).

# Recap — 15 September 2026

**The Ableton chapter opened:** Stemma's Flask server takes `STEMEXPORT_PORT`; the app spawns it
on 5124 beside the Logic backend through one shared `spawnBackend()`, routes `.als` rows to it,
and the health pill names whichever backend is down. **First full render at 20:35** (17 tracks,
18/15/18 stems, 2.0 GB zip). Four driver bugs fixed on the way: return tracks matched by the
typed name instead of Live's exported "A-Reverb" (prefer `EffectiveName`); a dialog scan that
overran 8 s was fatal (now a skipped tick); a 5-minute export ceiling expired mid-pass while Live
was still writing (now 30 min like Logic, honest error if reached); the backend's output was
buffered and it emitted no failure marker (unbuffered, marker, reason shown on the row). Fresh
output folder per render on both DAWs (`<name> (2)`). Repos renamed: **Stemma → ableton-renderer**
(owner's FleapStems account; the app and Daemon try both names), **SendStems → Steminem** locally
(aliases, app paths, venv and Claude memory fixed up). The checkout moved to the headless-V1
driver on `ableton-exporter-v1`; `Slice` superseded. Architecture schematic and a collaborator
handoff page published; typeface pairings explored (no decision). Lesson: renames in Live reach
the export only once the set is saved.

# Recap — 16 September 2026

**The parity chapter, complete.** Owner's goal: "both renderers provide the same experience."
(1) Two sets, not three: `01_With_FX` + `02_Raw` (`_raw` suffix); the returns-and-master pass
kept as an opt-in flag, renders ~35% shorter. (2) Native sample rate, 24-bit, no dither: Live
stores no per-set rate in the `.als`, so the engine rate is read from Live's own `Log.txt` after
launch (the old max-clip-rate guess gave 96 kHz on a 48 kHz set); stems 119 → 45 MB, zip 2.0 →
0.5 GB. (3) Never-save was already law in the headless driver; new gentle teardown clicks Cancel
on Live's export progress window before the never-save quit. (4) Cancel: `/export/cancel`,
cooperative flag at every gate and inside the waits, immediate abort of Live's render from the
route's thread, status `cancelled`, folder removed, row back to Ready — "perfect" mid-pass-1 and
mid-pass-2. (5) Live warnings the Logic way (owner's call: a missing stem is a warning, not a
failure): Solo, Muted (stems left out, named), Empty (Live writes a silent stem for a clip-less
track; removed and named — both DAWs now say "Empty"), Silent, Missing media, Identical,
Mismatch, Zip/Cleanup; staged success; one inbox note per render; verified with a "messy" set
(2 solos, 4 mutes, 1 empty track). Found on the way: a dropped import crashed the server's
`finally` (leaked the sleep guard, never released the in-flight flag) — hardened. App: warnings
clickable mid-render (delegated listener — the status cell is rebuilt every poll), health pill
"initiating…" vs "offline". Claude Code hooks: reply-done and needs-attention sounds. Lessons:
import the module after an edit, not just compile it; Live writes silent stems where Logic writes
nothing; a process-exists "wait ready" is blind to dialogs. Summary rule set: one recap per past
session kept forever, full chapter for the newest day, Markdown source on disk.

# Recap — 17 September 2026

Packaging, layer 1. "What would it take to create a sharable prototype?" — answered in three
layers and the bundle built the same morning: `logic-renderer/build.sh` freezes both backends with
PyInstaller, gathers the Remote Script, packs the Electron app and produces
`dist/stemma-1.0.0-arm64.dmg` (~124 MB; product renamed **stemma**, `com.stemma.app`,
`docs/BUILD.md`). Three things bit and are now in the recipe: the Anaconda `python3` is x86_64 (a
dedicated arm64 `build-venv` freezes the backends); an unsigned bundle carries Electron's invalid
seal and Apple Silicon exits it silently (ad-hoc `codesign` between the `--dir` and `--prepackaged`
steps); VS Code's `ELECTRON_RUN_AS_NODE=1` makes any Electron binary act as Node. First tests:
"Failed to fetch" (one-file backends took 20 s to unpack → folder bundles + Render disabled until
the backend answers `/health`); Logic stuck at "Launching…" behind the audio-interface alert
because the packaged app had no Accessibility grant → `permissions.py` pre-flight in both backends
(`AXIsProcessTrustedWithOptions` with prompt, Automation probe, fail fast with the exact switch).
Owner rule set: **push after every commit, in any repo.** Explained: `main.js` vs `app.js`, why
Electron, why the packaged app needs its own grants.

# Session of 19 September 2026 — documents, the first packaged Ableton render, and a fresh account

Three chapters in one day: the project's documents got their own shape and look; the packaged app
rendered Ableton for the first time after a real diagnosis; and the first test in a fresh macOS
account showed where the next work is.

## Documents
- **Three documents now exist** beside this summary, all in `working/Documents/` with Markdown
  sources in `summary-source/`: the **Technical Overview** (`Stemma_Technical_Overview.pdf`, title
  "stemma": architecture, repos, the renderer contract, both renderers, packaging, practices,
  roadmap — written for a prospective engineering hire; renamed from "Engineering Onboarding Brief"
  after a naming discussion: *Engineering Handbook* or *Technical Overview* are the industry names,
  "Tech Sheet" is a hardware term) and the **Team Task List** (`Stemma_Team_Task_List_<date>.pdf`,
  plain language, seven phases with owners: Phase 1 Phil; 2–4 Phil and Noé; 5–7 the hire with Phil
  and Noé). Both built from the workflow and the owner's `stemma_project_brief.md`.
- **The PDFs look like the app** (owner request: "font and colours"): Inter body, Poppins headings,
  JetBrains Mono code, the lavender page, plum headings and links, a title tile, plum table headers.
  Toolchain: `summary-source/render_pdf.sh` (pandoc + xelatex, `stemma-style.tex`,
  `stemma-tables.lua`; fonts installed in `~/Library/Fonts/stemma/`, copies in `fonts/`; loading
  fonts by path failed on this TeX Live, by family name works; code blocks are kept on one page).
- **This summary now travels with the code:** a copy in every repository as
  `docs/Stemma_Session_Summary.pdf` (+ `.md`), refreshed each session; the Technical Overview points
  to it as the first thing to read.

## The packaged app: Logic fine, Ableton failed three times — then "rendered perfectly"
- Owner's retest of the dmg: Logic rendered; Ableton failed 3× with *"Save button element-click
  failed: STUCK: windows=[Save][Export Audio/Video][][set] sheets=0"* — on the With FX pass twice,
  on the Raw pass once, while the dev app from Terminal worked minutes later.
- **Nothing to diagnose with:** a packaged app launched from Finder has no stdout. `main.js` now
  writes each backend's output to `~/Library/Logs/stemma/<logic|ableton>-backend.log` (rotated per
  launch, polling routes filtered). Two facts on the way: the app in Applications was the *first*
  17 Sept build (before the pre-flight); and an ad-hoc signature's identity is the build's
  `cdhash`, so **every rebuild is a new app to macOS permissions** — the toggle shows ON for the
  old build while the new one is untrusted; remove stemma from the Accessibility list and let the
  prompt re-add it after each install (in `docs/BUILD.md`).
- **The log said:** the trace of a failing and a succeeding attempt is identical up to the Save
  click; the panel then either closes in 0.75 s or ignores the AXPress outright for the 5 s poll —
  about half the attempts, same filename, same destination, same window stack. Redoing the whole
  pass rerolled the same coin. Fix (`ableton-exporter-v5`): the commit **escalates inside the open
  panel** — click Save; still open after 1.5 s → `AXConfirm` on the name field; still open → click
  again; each step only while the panel exists, result `OK:<stage>` in the log. The focus sampler
  (an osascript every 0.65 s alongside the click) is paused during modals by default. Owner: **"It
  rendered perfectly!"** — the first end-to-end Ableton render from the packaged app.
- "Pass 3" explained: the code numbers passes 1 With FX / 2 Returns+Master (skipped) / 3 Raw;
  messages now say *"Raw pass failed …"* and only claim Live crashed when it did.

## Permissions and failures on the row
- A refused pre-flight (no Accessibility / Automation grant) is no longer a red "Failed": the
  backends tag it `reason_code = permissions`, the row shows an **amber "Permission needed"**, the
  notification is "stemma needs a permission", the inbox says "Permission needed — <project>", and
  the message is the fix itself: *"Enable Accessibility access for stemma in System Settings ›
  Privacy & Security › Accessibility, then relaunch stemma."*
- Because the column can never show a whole sentence, **both the amber permission row and every
  red Failed row now use the warnings' mark**: hover card, click to cascade the full text under
  the row, pinned until clicked again (red variant for failures).
- Both DAW launches keep `open`'s stderr, so a refused launch says *why* instead of printing the
  command line.

## First test in a fresh macOS account ("Stemma Build Tester")
- Kit staged in `/Users/Shared/stemma-test` (readable by every account): the dmg, the two test
  projects, the Remote Script folder, a README with the steps.
- Result: both DAWs failed at launch — Live opened and closed (DialogGuard paused on an unknown
  first-launch dialog), Logic's `open` was refused. Diagnosis agreed with the owner: **DAW licences
  are per account** (Live's authorisation lives in the account's Library; Logic's App Store licence
  follows the Apple ID). A second account is a poor proxy for a tester's machine on that point and a
  good one for everything else (install, Gatekeeper, prompts, Remote Script, library folder). Plan:
  authorise Live and run Logic once manually in that account, then test stemma; a "DAW not
  authorised" rule joins the layer 2 list. The account had no log folder, which points at an old
  dmg from its Desktop having been installed — the kit's 20:12 dmg is the one to use.
- Remote Script location confirmed correct (`User Library/Remote Scripts/StemExportBridge`).
  **Installer options** laid out: (1) the Ableton backend copies it in its pre-flight next to the
  existing slot auto-tick, version-stamped (`.stem_export_version`, now 9) — recommended; (2) port
  the old shell's JavaScript installer into `main.js`; (3) manual. Caveats: Live must be relaunched
  to load it (the backend launches Live anyway); a never-run Live has no preferences to tick.
- Explained: where the build lives (inside the repos: `logic-renderer/build.sh`, `build_python.py`
  in each backend repo, electron-builder config in `package.json`, `build-resources/`) and how a
  packaged app differs from `npm start` (same code, different container: frozen Python and a
  self-contained Electron in `stemma.app` vs the source trees under Terminal's permissions).

## Git
logic-renderer `logic-and-UI`: `726f8a2` (summary in docs), `716e438` (backend log files),
`622aa3b` (amber permission state), `6e8f207` (clickable permission warning), `5977cf4` (failed
rows expand, Logic launch cause). ableton-renderer: `bc52a10` on `v4` (summary in docs); new
`ableton-exporter-v5`: `49a2f5f` (Save commit escalation), `a284755` (permission message + code),
`8629dea` (Live launch cause). Daemon `a85e156`, Contract `e93339c` (summary in docs). All pushed.

# Next steps

1. **Fresh-account test, round two:** authorise Live and run Logic once in the tester account,
   install the kit's dmg, re-add Accessibility, render both; send the red-mark text, the inbox
   entries and `~/Library/Logs/stemma` (copy into `/Users/Shared/stemma-test/logs-tester`).
2. **Packaging layer 2:** Remote Script installer in the Ableton backend's pre-flight (option 1);
   honest "DAW not installed" / "DAW not authorised" states (DialogGuard rules for Live's
   authorisation and Logic's first-run dialogs); a self-signed signing certificate so permission
   grants survive rebuilds; default output folder on the internal disk; then a real second Mac.
3. **Layer 3:** Developer ID + notarization (electron-builder does both once the certificate is
   in the Keychain).
4. **Render-complete sound** (and a failure sound; owner supplies files).
5. **Export-format option** per render: sample rate, bit depth, later the returns-and-master set
   (the Technical Overview already describes it as the Settings override of the native-rate rule).
6. Keep the Technical Overview's packaging section current (it still says "state on 17 September").
7. Shared roadmap as before: staging-folder redesign for Logic, pre-flight "Render anyway /
   Cancel", carry-overs (per-project output default, "- " stem prefix, Range decision, daemon
   inbox return, zip-only job folders, absorb daemon, collaborator notice).
