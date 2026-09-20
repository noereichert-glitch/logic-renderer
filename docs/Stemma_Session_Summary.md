---
title: "Stemma Session Summary"
subtitle: "Consolidated — through 20 September 2026"
date: "20 September 2026"
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

# Recap — 19 September 2026

Three chapters in one day. **Documents:** the Technical Overview (`Stemma_Technical_Overview.pdf`,
for a prospective hire) and the Team Task List (seven phases with owners) were written from the
workflow and the owner's brief; all PDFs restyled to the app's look (Inter / Poppins / JetBrains
Mono, lavender page, plum headings; `summary-source/render_pdf.sh`, xelatex); this summary now
travels in every repo as `docs/Stemma_Session_Summary.pdf`. **The packaged app:** Logic rendered,
Ableton failed 3× at the Save click ("STUCK"); with no stdout to read, `main.js` gained per-backend
log files (`~/Library/Logs/stemma/`), and the log showed the first AXPress on Save being dropped
about half the time — fixed on `ableton-exporter-v5` by escalating inside the panel (click →
AXConfirm on the name field → click), sampler paused during modals; owner: "It rendered
perfectly!" — the first end-to-end packaged Ableton render. Learned: an ad-hoc build's permission
identity is its cdhash, so Accessibility must be re-added after every install. **Rows:** a refused
permission pre-flight is an amber "Permission needed" (message = the fix), and both it and red
Failed rows expand through the warnings' mark; launch errors keep `open`'s stderr. **Fresh
account** ("Stemma Build Tester", kit in `/Users/Shared/stemma-test`): both DAWs failed at launch
because licences are per account — authorise them manually first; Remote Script installer options
laid out (option 1, the backend, recommended).

# Session of 20 September 2026 — the Remote Script installs itself; row polish

A shorter day: one structural piece (the Ableton helper no longer needs a manual copy) and a
round of row behaviour fixes from the owner's hands-on testing, ending with "could I simply send
someone the dmg?" — answered honestly.

## Remote Script installer (option 1, owner decision)
- The owner asked for an automatic install and, after a Q&A on what "every render" means (a
  **check**, not a copy: files are written only when the folder is missing, its version stamp
  differs, or a file's bytes differ from the shipped copy — so a stemma update is picked up on the
  next render), chose **option 1: the Ableton backend does it in its pre-flight**, right before the
  Control-Surface slot auto-tick and moments before Live launches. Reasons over the app-launch
  option: it runs where a problem can be reported on the row, at the one moment Live is guaranteed
  to load it, for the dev app and the tester too, and keeps DAW knowledge out of the UI layer.
- `ableton-renderer/python/remote_script_installer.py` (branch `ableton-exporter-v6`): User
  Library resolved from Live's `Library.cfg` (`UserLibrary/LibraryProject/ProjectPath`, descending
  into a nested project, default `~/Music/Ableton/User Library`); a second copy in the prefs
  folder's `User Remote Scripts` (Live scans it too; survives an unmounted User Library volume);
  source from `STEMEXPORT_REMOTE_SCRIPT_SRC` (set by `main.js`: `Resources/ableton_remote_script`
  packaged, the sibling repo in dev). A write failure is terminal only when no loadable copy
  remains; the row then names the folder and the OS error. Verified: current on the owner's
  account, installed in a sandboxed home, updated after a tampered file and after an old stamp.
- Storage question answered: the script is 20 KB; a user who never renders Ableton carries the
  39 MB Ableton backend unused, out of a 291 MB app that is mostly Electron.
- Kit README no longer asks for the manual copy; `docs/BUILD.md` notes `BRIDGE_VERSION`.

## Row behaviour, from the owner's testing
- Clicking the ⚠ mark on a rendered row also opened the zip's folder: the folder listener sits on
  the status cell itself and fired before the mark's handler could stop it; the cell now ignores
  clicks from the mark. **Mark = toggle, "Rendered …" = open folder.**
- "then relaunch stemma" is in real bold in the permission message (hover card and cascade).
- The green "Rendered …" no longer underlines on hover: check + text are a pill that tints green
  like the mark's amber; hovering the mark leaves the text alone.
- **Permission needed** and **Failed** rows: text and ⚠ are one pill that hovers and toggles
  together (`warnMark(id, list, tone, label)`).

## Explained
- Dev vs packaged: same source, different container; both use the same DAW-side state (User
  Library, Live prefs, staging, library folder) and separate app state (settings/inbox under
  `stemma` vs `StemExport`; permissions under stemma.app vs Terminal). Never run both at once
  (ports 5123/5124); both write to `~/Library/Logs/stemma`.
- The process for every change: edit the source (what `npm start` runs) → checks (syntax, imports,
  tests) → commit + push → `build.sh` regenerates the dmg from the repos → copy to the kit.
- "Could I send the dmg today?" Yes to a trusted tester, with three manual steps: right-click →
  Open (the owner never sees this because a locally built dmg carries no quarantine flag; a
  downloaded one does), grant Accessibility then relaunch, allow System Events. DAW installed and
  authorised in that account; Apple Silicon only. Likely rough edges on a stranger's Mac: DAW
  first-launch dialogs, an output folder on an external drive, a User Library in an unusual place —
  the red pill's text plus `~/Library/Logs/stemma` is what diagnoses them.

## Git
logic-renderer `logic-and-UI`: `8614928` (script source env), `43dfd24` (mark vs folder click,
bold relaunch), `9c2e441` (green hover pill), `16a9a01` (permission pill), `3a2a05c` (failed
pill). ableton-renderer new `ableton-exporter-v6`: `acf4f69` (installer). dmg rebuilt after each
change; the kit holds the 15:21 build. All pushed.

# Next steps

1. **Fresh-account test, round two:** authorise Live and run Logic once in the tester account,
   install the kit's dmg, re-add Accessibility, render both — the installer's first real outing.
2. **First outside tester** with the three-step note; collect the red-pill text and
   `~/Library/Logs/stemma` on any failure.
3. **Packaging layer 2, remaining:** "DAW not installed" / "DAW not authorised" states (DialogGuard
   rules for Live's authorisation and Logic's first-run dialogs); a self-signed signing certificate
   so permission grants survive rebuilds; default output folder on the internal disk; a real
   second Mac.
4. **Layer 3:** Developer ID + notarization (removes the right-click → Open step).
5. **Render-complete sound** (and a failure sound; owner supplies files).
6. **Export-format option** per render: sample rate, bit depth, later the returns-and-master set.
7. Keep the Technical Overview's packaging section current (still says "state on 17 September").
8. Shared roadmap as before: staging-folder redesign for Logic, pre-flight "Render anyway /
   Cancel", carry-overs (per-project output default, "- " stem prefix, Range decision, daemon
   inbox return, zip-only job folders, absorb daemon, collaborator notice).
