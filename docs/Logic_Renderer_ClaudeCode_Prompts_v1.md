# Logic Pro Renderer — Claude Code Prompts (v1)

Copy each prompt into Claude Code **in order**. Run each on its own
`logic-renderer-vN` branch (you create the branch in Terminal first; Claude Code
only confirms it). Don't start a phase until the previous one is green.

Before Phase 1, open Logic Pro once and grant Accessibility + Automation when
macOS asks. Test against the owner's real project: `/Users/reichertnoe/Desktop/logic test.logicx`. Open it when you need to run a
real export. (A Folder-style copy, `~/Desktop/logic test folder/`, exists too if
you want to test the package-vs-folder path resolver.)

---

## PROMPT 0 — Verify the scaffold

```
Read CLAUDE.md and docs/Logic_Renderer_Handoff_v1.md first. Confirm the active
git branch is a logic-renderer-v* branch and tell me which — do NOT create,
switch, or push branches.

This project was scaffolded from the FL Studio renderer. Verify the scaffold runs
before any feature work:
1. `npm install` and `pip3 install -r requirements.txt`.
2. Start the backend alone: `python3 python/server.py`, then in another shell
   `curl localhost:5123/health` → expect {"status":"ok"}. Stop it.
3. `npm start`. Confirm the window opens, the sidebar/drop zone render, and
   dropping (or browsing to) a .logicx project shows the file row without errors.
   The "Stem Export" button should enable once a project and an output folder are
   chosen. Do NOT click Export yet (the Logic driver isn't implemented).
4. Report what worked. Don't change code unless something is broken; if you fix
   something, keep it minimal and explain it.
```

---

## PROMPT 1 — Implement the Logic driver: launch + WET export + zip (first green)

```
Confirm the active logic-renderer-v* branch. Read docs/Logic_Renderer_Handoff_v1.md
§4 and §5, and python/logic_render.py (the scaffold with the contract + TODOs).

Goal: a real `01_With_FX` export end to end on the fixture at /Users/reichertnoe/Desktop/logic test.logicx, then a zip.
Implement ONLY the wet pass this prompt (bypass_fx=False); leave the Raw pass for
the next prompt. Work element-by-element via AppleScript / System Events — NO
screenshots, NO coordinate/pixel clicks (hard constraint).

Steps:
1. First, DISCOVER the real UI, don't guess. Open /Users/reichertnoe/Desktop/logic test.logicx in Logic and
   run small osascript probes to dump:
   - the exact process name,
   - the File ▸ Export submenu item titles (find the "All Tracks as Audio
     Files…" item verbatim),
   - after triggering that menu item once by hand if needed, the export dialog's
     accessibility tree: the names/roles of the File Format pop-up, the "Bypass
     Effect Plug-ins" checkbox, Normalize control, and the Save button.
   Print these so we have ground truth. Save the useful probes under
   docs/<today>/ for reuse.
2. Add a project-path resolver (Handoff §11): accept a dropped/selected path
   that is either a `.logicx` package OR a Folder-style project folder, and
   resolve to the inner `.logicx` (detect `.musicapps-project-folder` or a
   single `*.logicx`). Test with BOTH save styles on the Desktop fixtures
   (`~/Desktop/logic test.logicx` = Package; `~/Desktop/logic test folder/` = Folder). Update the
   UI drop/picker so dropping the folder works too.
2. Implement in python/logic_render.py:
   - detect_logic_process_name (confirm/return the real name)
   - wait_for_logic_ready: poll for the project window to exist + a short settle;
     adaptive with a proven floor and a hard ceiling (mirror the FL approach).
   - export_stems(output_folder, file_stem, bypass_fx=False): bring Logic
     frontmost → File ▸ Export ▸ All Tracks as Audio Files… → ⌘⇧G to the
     output_folder → set Format=WAVE, Normalize=Off, Bypass=OFF → Save.
   - wait_for_export_complete: primary = bounce/progress window closing after it
     was seen; backstop = WAV file-size stability (N consecutive identical
     snapshots). Raise LogicCrashedError if Logic exits mid-wait.
   - quit_logic: ⌘Q without saving, poll for exit, handle a "Don't Save" sheet,
     escalate to terminate/kill.
3. Range/length handling (Handoff §4a) — fixes the "cursor not at start" bug:
   before each export, press Return to reset the playhead; read the Cycle button
   state; if cycle OFF do ⌘A + "Set Locators by Regions" so the range spans first
   clip → last clip; if cycle ON use the existing loop range. Verify the exported
   stems start at bar 1 and have the full song length, regardless of where the
   playhead/cycle was beforehand. Use identical range for the wet and raw passes.
3. The orchestrator (python/stem_exporter.py) already calls these and sorts WAVs
   into 01_With_FX, runs _validate_set, and zips. Run a full export via the app
   (or by POSTing /export) on /Users/reichertnoe/Desktop/logic test.logicx.
4. Test stack behavior: if my fixture has a Track Stack, report whether a
   Summing Stack exported as ONE combined file vs per-subtrack, and whether a
   Folder Stack exported per-subtrack (this varies by Logic version — see Handoff
   §6a). Note the actual stem count vs track count.
5. Success = 01_With_FX contains one WAV per exported track (≥2), the zip exists,
   Logic quit cleanly and the project was NOT modified. Report timings. Commit
   only if I ask.
```

---

## PROMPT 2 — Add the Raw pass + the T11 guard

```
Confirm the branch. The wet pass works. Now add the dry/Raw pass IN THE SAME
Logic session (Logic reads the Bypass checkbox per-export, so do NOT relaunch
between passes).

1. In export_stems, make bypass_fx actually drive the "Bypass Effect Plug-ins"
   checkbox: read its current AXValue and click only if it differs from the
   requested state (don't blind-toggle).
2. Confirm stem_exporter runs pass 1 (bypass off → sorted to 01_With_FX) then
   pass 2 (bypass on → sorted to 03_Raw) without quitting Logic in between, then
   quits once at the end.
3. The T11 guard (_assert_raw_differs) must pass on real audio: at least one
   shared-name stem differs in PCM content between 01_With_FX and 03_Raw. If it
   fails, the Bypass click didn't take — fix the checkbox handling, don't weaken
   the guard.
4. Verify on a project that has audible insert FX (e.g. heavy reverb/distortion)
   so wet vs dry clearly differ. Report which stems differed. Commit only if I ask.
```

---

## PROMPT 3 — Harden

```
Confirm the branch. Make it robust for unattended-ish runs (I keep using my Mac
while it renders).

1. Crash-retry: verify _run_pass_with_retry relaunches + retries ONLY when Logic's
   process actually dies, and propagates any other error. Simulate a crash (e.g.
   pkill Logic mid-export) and confirm one clean retry.
2. Replace-sheet + stray-dialog handling in export_stems (defensive even though we
   sort between passes). Reuse dismiss_macos_crash_reporter before each pass.
3. Replace any remaining fixed sleeps with event-driven waits; set sane timeouts
   so a hung export fails loudly instead of hanging forever.
4. Confirm concurrency: a 2nd POST /export while one runs returns 409 (already in
   server.py) and the UI handles it.
5. Wire tools/tester.py to do a full smoke export on a fixture and write STATUS.md
   (mirror the FL/Ableton tester). Run it; paste STATUS.md.
6. Confirm the project file is byte-identical before/after a full run (never
   saved). Commit only if I ask.
```

---

## PROMPT 4 — (LATER) 02_With_Returns_And_Master

```
Confirm the branch. Read docs/Logic_Renderer_Handoff_v1.md §6. Research and
propose (do not build yet) how to produce per-track stems WITH bus/master FX in
Logic — compare stem-group/summing-stack routing vs. solo+bounce vs. a separate
master print. Recommend one, list the automation steps, and estimate effort. Then
wait for my go-ahead before implementing. Keep a T11-style content guard in the
plan.
```

---

## PROMPT 5 — (LATER) Background / shared core

```
Confirm the branch. Two directions to scope (plan, don't build): (a) a fully
headless render mode with no focus grab (likely a separate macOS login session or
VM per DAW) and (b) extracting one shared engine with pluggable ableton/fl/logic
drivers used by all three apps. Give me a migration plan and risks for each; flag
anything that would touch the working FL/Ableton apps.
```

---

### Conventions reminder for every prompt
- Confirm the `logic-renderer-v*` branch first; never create/switch/push branches.
- Element-level System Events only — no Screen Recording, no coordinate clicks.
- Never save the Logic project; always quit it (try/finally).
- Render at the project's native sample rate.
- Commit only when explicitly asked.
