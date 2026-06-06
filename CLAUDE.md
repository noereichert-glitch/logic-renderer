# StemExport — notes for Claude Code

## Project

macOS **Logic Pro** stem renderer (built from the FL Studio renderer, which was
itself migrated from the original Ableton renderer).
Electron UI → Flask backend → stem export → zip. The deliverable is two stem
sets: `01_With_FX` (plugins on) and `03_Raw` (dry / plugins bypassed).
`02_With_Returns_And_Master` is a documented later phase.

Logic is driven entirely through macOS accessibility automation (AppleScript /
System Events) — there is no Logic scripting API. The one net-new file vs. the FL
renderer is `python/logic_render.py`. Everything else (Electron UI, Flask server,
the `StemExporter` orchestrator skeleton, the safety guards) is reused.

Start here: `docs/CLAUDE_CODE_START_HERE.md`
Full plan:  `docs/Logic_Renderer_Handoff_v1.md`
Build prompts (run in order): `docs/Logic_Renderer_ClaudeCode_Prompts_v1.md`

## Hard constraints (from the product owner)

- **Reuse the UI 100%.** The Electron renderer (`electron/renderer/*`) is
  DAW-agnostic; only file-type labels were swapped. Do not redesign it.
- **No Screen Recording.** Drive Logic by accessible UI *elements* (System
  Events), never by screenshots or coordinate clicks.
- **No Finder automation.** Use the in-dialog "Go to Folder" (⌘⇧G) to set paths;
  `shell.showItemInFinder` (NSWorkspace, no permission prompt) is fine.
- **Render at the project's native sample rate.** Don't force a sample rate.
- **Background-friendly.** Target: the client keeps using the Mac while it
  renders (Logic minimized; only the brief export-trigger grabs focus). Keep the
  driver clean so a fully-headless mode could be added later.
- **Never save the project.** Quit Logic without saving every time.

## Branching convention

Incrementing version branches: `logic-renderer-v1`, `logic-renderer-v2`, ...

**The user creates the next version branch manually in Terminal before launching
Claude Code.** Claude Code only *confirms* the active branch in its first step.

Claude Code must **not** create, switch, or delete branches, and must **never
`git push`** — the user pushes manually. It may `git add` / `git commit` on the
already-checked-out branch only when explicitly asked, and never commits directly
to a pre-existing version branch without being asked.
