# Claude Code — START HERE (Logic Pro Renderer)

You're building the **Logic Pro** stem renderer. It was scaffolded from the
working FL Studio renderer; the UI, Flask server, and orchestrator are reused, and
the only real work is the Logic automation driver.

## Read in this order
1. `../CLAUDE.md` — project rules + **branch discipline** + hard constraints.
2. `Logic_Renderer_Handoff_v1.md` — the architecture + build spec + open questions.
3. `Logic_Renderer_ClaudeCode_Prompts_v1.md` — run these prompts in order.

## First actions
- Confirm the active branch is `logic-renderer-v*` (the user created it). Do **not**
  create/switch/push branches.
- Run **PROMPT 0** to verify the scaffold (`npm install`, `pip3 install -r
  requirements.txt`, backend `/health`, `npm start`).
- Then **PROMPT 1**.

## The one file you implement
`python/logic_render.py` — scaffolded with the full class contract that
`python/stem_exporter.py` already imports. The AppleScript bodies marked
`TODO(real-machine)` are yours to write **and verify against a real Logic install**
(element names can't be guessed — dump the accessibility tree).

## Non-negotiables
- Reuse the UI 100% (don't redesign `electron/renderer/*`).
- Drive Logic by **accessible UI elements** (System Events) — **no Screen
  Recording, no coordinate clicks, no Finder automation**.
- Render at the project's **native sample rate**.
- **Never save** the Logic project; always quit it in `try/finally`.
- Scope now = two sets: `01_With_FX` + `03_Raw`.
  `02_With_Returns_And_Master` is a later phase.

## Definition of "first green" (Phase 1)
A real `.logicx` fixture exports `01_With_FX` (one WAV per track, ≥2), the zip is
created, Logic quit cleanly, and the project file is unchanged.
