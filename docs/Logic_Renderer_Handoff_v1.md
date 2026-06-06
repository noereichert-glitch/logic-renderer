# Logic Pro Renderer — Handoff & Architecture (v1)

**Date:** 2026-06-06
**Author:** planning pass over the working Ableton + FL Studio renderers.
**Status:** scaffold created; DAW driver to be implemented by Claude Code.
**Audience:** Claude Code (build spec) + the product owner.

> This is the build spec. Read it, then run the prompts in
> `Logic_Renderer_ClaudeCode_Prompts_v1.md` in order. Branch discipline per
> `../CLAUDE.md`.

---

## 0. North-star UX

Client drops a `.logicx` project, picks an output folder, hits **Stem Export**,
and **keeps using their Mac** while it renders. They get a zip containing two
stem sets — `01_With_FX` (wet) and `03_Raw` (dry) — one WAV per track in each. No
Logic configuration by the client, no corrupt deliveries.

---

## 1. Why Logic is the easy one (the key insight)

The other two renderers fought their DAW:

| Need | Ableton | FL Studio | **Logic Pro** |
|---|---|---|---|
| Per-track stems | Export dialog, "All Individual Tracks" | Split-mixer render (canvas, un-clickable) | **`File ▸ Export ▸ All Tracks as Audio Files…`** — native, accessible |
| Dry / Raw pass | Custom **Remote Script inside Live** bypasses plugins | Pre-write `reg.xml` `InputFXBox=0`, relaunch | **"Bypass Effect Plug-ins" checkbox in the same dialog** |
| Passes per launch | many | 1 (flag read at launch) | **both passes in ONE launch** (checkbox read per-export) |
| Dialog drivable by element? | partly | **no** (canvas → Return/cliclick) | **yes** (standard Cocoa Save panel) |

Consequences for us:
- **No Remote Script, no config-file surgery.** The Raw pass is one checkbox.
- **One Logic launch for both passes** → simpler + faster than FL's two cycles.
- **Element-level UI scripting** → we satisfy "no Screen Recording" naturally; no
  coordinate/pixel clicking is needed.

The single thing Logic does *not* do in one shot is per-track stems **with bus /
master FX folded in** (`02_With_Returns_And_Master`). FL deferred the same set.
We defer it too (see §6).

---

## 2. Architecture (unchanged 4-layer shape)

```
Electron UI  ──HTTP :5123──>  Flask backend  ──fn calls──>  StemExporter
(renderer/*)                  (server.py)                   (stem_exporter.py)
     ▲ IPC (pickers, history)                                     │
     │                                                            ▼
electron/main.js + preload.js                          logic_render.py  ──AppleScript/System Events──>  Logic Pro
```

Same separation-by-reachability, async-work/polling-UI, fail-fast, never-persist
principles as the other two apps. The progress channel is the shared
`export_state` dict the UI polls every ~800 ms.

---

## 3. What is reused vs. net-new

**Reused 100% (copied from the FL renderer, only labels swapped):**
- `electron/renderer/index.html`, `app.js`, `styles.css` — the entire UI (sidebar,
  drop zone, 3-step export screen, progress bar, History). Only file-type text was
  changed (`.flp`→`.logicx`, "FL Studio"→"Logic Pro") and the picker filter.
- `electron/main.js`, `preload.js` — window/lifecycle, spawns Python, IPC. Only the
  open-file filter changed (`dialog:openFLP`→`dialog:openProject`, ext `logicx`).
- `python/server.py` — concurrency-guarded `/export` on a daemon thread, shared
  `export_state`, `/export/progress`, `/folder/stems`, `/health`. Only change: it
  no longer imports `als_parser` (Logic isn't parsed up front).
- `python/one_click_helpers.py` — `sort_wavs_into_subfolder`, `zip_project_folder`.
  (The Ableton Remote-Script socket helpers in this file are dormant/unused.)
- `python/stem_exporter.py` — the orchestrator: validation (`_validate_set`), the
  T11 raw-differs guard (`_assert_raw_differs` + `_pcm_fingerprint`), crash-retry
  (`_run_pass_with_retry`), zip. **Re-shaped for Logic**: ONE launch, TWO exports
  (checkbox toggled), no `reg.xml` prestage.

**Net-new (the only real work):**
- `python/logic_render.py` — the Logic driver. Scaffolded with the full class
  contract `StemExporter` already imports; the AppleScript bodies marked
  `TODO(real-machine)` are what Claude Code implements and verifies against a real
  Logic install.

**Dropped (not needed for Logic):**
- `ableton_bridge.py`, `als_parser.py`, `ai_renamer.py`, `audio_analyzer.py`,
  `fl_render.py`, the FL `reg.xml` prestage, the Ableton remote script, and the
  `pyflp`/`librosa`/`anthropic` dependencies. `requirements.txt` is now just
  flask + flask-cors + python-dotenv.

---

## 4. The export flow (what `logic_render.export_stems` must do)

One call = one `All Tracks as Audio Files` export into the project root folder.
The orchestrator calls it twice (wet, then raw), sorting WAVs into `01_With_FX` /
`03_Raw` between calls so the root is empty before each pass.

1. Bring Logic frontmost.
2. Menu: **File ▸ Export ▸ "All Tracks as Audio Files…"**.
   ⚠️ Confirm the exact item title/submenu on the installed version (it has been
   both "All Tracks as Audio Files" and "…Audio File"). Dump the menu via System
   Events rather than hard-coding.
3. In the export dialog (a Cocoa Save panel + accessory controls):
   - Set the destination via **⌘⇧G "Go to Folder"** → type the output path →
     Return. (Keeps us off Finder automation.)
   - **File Format → WAVE.**
   - **"Bypass Effect Plug-ins" → `bypass_fx`.** Read the checkbox's current
     AXValue and only click if it differs (don't blind-toggle).
   - **Normalize → Off.** Bit depth → leave default / 24-bit. (Sample rate is not
     in this dialog — it follows the project, which is what we want.)
   - Click **Save / Export**.
4. Defensive: handle a stray "Replace existing files?" sheet (shouldn't occur
   because we sort between passes, but be safe).
5. **Wait for completion**: primary signal = Logic's bounce/progress window
   closing after it was seen open; backstop = WAV file-size stability
   (N consecutive identical snapshots). Return the instant it's done.
6. If Logic's process dies at any point → raise `LogicCrashedError`.

All of this is element-level System Events scripting. **No screenshots, no
coordinate clicks.**

---

## 5. Safety (reused, keep all of it)

- **`_validate_set`** — each set must have **≥2 WAVs** (else Logic produced a
  single mixdown, not per-track) → fail loudly before zipping.
- **`_assert_raw_differs` (T11 guard)** — at least one stem present in both sets
  must differ in PCM content (hashes only the WAV `data` chunk, so 32-bit-float
  files work and metadata can't cause false positives). Proves the Bypass checkbox
  took effect. If everything is identical → don't ship.
- **`try/finally`** — Logic is always quit, even on failure.
- **Quit without saving** — the export must never write the `.logicx`.
- **Crash-retry** — retry a pass only if Logic's *process* actually died; any
  other error propagates immediately.

---

## 6. Open question — `02_With_Returns_And_Master` (later phase)

Logic's per-track export does not fold bus/master FX into each stem. Options to
evaluate when we get there (don't build now):
1. A second export variant that routes each track through its bus chain (e.g.
   stem groups / summing stacks) — needs research on Logic's stem options.
2. Per-track solo + full bounce — correct but slow.
3. Post-process: print the master/bus separately and document it.
Keep the T11-style content guard whatever the choice. Until then, the orchestrator
returns `02_With_Returns_And_Master: []` and the UI simply shows two sets.

---

## 6a. Track Stacks / folders — affects stem count (IMPORTANT)

Logic does **not** export every visible track 1:1; stack type decides the output:

- **Summing Stack** (subtracks routed to a bus — the "group" type): `All Tracks
  as Audio Files` exports the **stack as ONE combined file**, not per subtrack.
  The stacked content arrives pre-summed (FX of the stack bus included). This is
  the Logic equivalent of Ableton group submixes.
- **Folder Stack** (organizational only; subtracks keep their own outputs):
  generally **one file per subtrack**.

Implications:
- The exported stem count can be **lower** than the raw track count → our
  `_validate_set` ≥2 check still holds, but don't assume "stems == tracks".
- A summing stack's stem is effectively a partial submix; for a true dry `03_Raw`
  the Bypass checkbox still applies, but the stack's *bus* FX behavior on export
  must be verified.
- This behavior **varies by Logic version** and is a known confusion point —
  confirm it on the real install before relying on it.
- If we later want per-subtrack stems from summing stacks, that needs selecting
  subtracks + `Export ▸ n Tracks as Audio Files` (the "n" changes with selection),
  or treating summing-stack output as the `02_With_Returns_And_Master`-style
  submix. Decide alongside §6.

## 7. Format decision (locked)

- **Sample rate:** the project's **native** rate (don't force one; not in the
  dialog anyway).
- **Bit depth:** dialog default / 24-bit (revisit if the client wants 32-bit float).
- **Format:** WAVE.

---

## 8. Background operation (current target)

The client keeps using the Mac while it renders. Logic's export runs offline
(faster than real time); Logic can be minimized. Only the brief menu/dialog
trigger (~seconds) grabs focus. This needs **no** VM or separate user session.

Keep the driver clean so a *fully*-headless mode (no focus grab at all) could be
added later — that would realistically require a separate macOS login session or
VM per DAW, which is out of scope now. This is the "all three renderers as
background actions later" direction the owner flagged: a shared, headless-capable
core is a future refactor (Option B), not this build.

---

## 9. Permissions / setup

- **Accessibility + Automation** granted once on first run (System Events driving
  Logic). Same class of permission the FL/Ableton apps need.
- **No Screen Recording**, **no Finder automation** — by design (see §4).
- Dev run: `npm install`, `pip3 install -r requirements.txt`, `npm start`.
- Packaged build: `build_python.py` (PyInstaller) + electron-builder, same as the
  other two apps.

---

## 10. Build order (phases → see the prompts doc)

- **Phase 0** — scaffold sanity: app launches, backend reachable, UI drops a
  `.logicx`. *(Scaffold already created; this phase just verifies it.)*
- **Phase 1** — implement `logic_render.py` launch / ready / **wet export** /
  completion / quit. First green: `01_With_FX` + zip on a real project.
- **Phase 2** — add the **Raw pass** (Bypass checkbox) → `03_Raw` + the T11 guard
  passes on real audio.
- **Phase 3** — harden: crash-retry on real crashes, replace-sheet handling,
  adaptive readiness/completion waits, timeouts, the `tools/tester.py` smoke test
  writing `STATUS.md`.
- **Phase 4 (later)** — `02_With_Returns_And_Master`.
- **Phase 5 (later)** — background/headless polish; optional shared-core unify.

---

## 11. Risks / things to watch

- **Menu item naming varies by Logic version** — dump it, don't hard-code.
- **Export dialog element names** — confirm by dumping the AX tree on the real
  machine (the prompts show how). This is the single biggest unknown.
- **`.logicx` is a package (folder bundle)** — the file picker treats it as a file
  on macOS; drag-drop passes `file.path`. Verify selection works.
- **Completion detection** — don't rely on a fixed sleep; watch the bounce window
  + file-size stability.
- **`.logicx` is saved two ways — Package vs Folder — handle BOTH.**
  - *Package*: a single self-contained `name.logicx` bundle (audio inside
    `Media/Audio Files/`).
  - *Folder*: a parent folder containing a hidden `.musicapps-project-folder`
    marker, an external `Audio Files/` folder, and the real `name.logicx`
    inside it. The project data (`Alternatives/000/ProjectData`) is identical
    to the package version; Logic opens either the same.
  - **Resolver required**: given a dropped path, the app must open the inner
    `.logicx`. If the path ends in `.logicx` → use it. If it is a folder
    containing `.musicapps-project-folder` (or exactly one `*.logicx`) →
    resolve to that inner `.logicx`. Do this in the drop/parse path AND the
    file picker (allow selecting either). `open -a "Logic Pro" <inner.logicx>`
    works for both.
- **First export of a session may be slower** (plugin loading) — readiness wait
  must be adaptive with a hard ceiling.
