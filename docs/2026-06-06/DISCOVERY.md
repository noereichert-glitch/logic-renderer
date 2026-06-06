# Logic Pro UI discovery — ground truth (2026-06-06)

Probed live against the installed Logic on this machine with the fixture
`~/Desktop/logic test.logicx` open. Everything below is element-level System
Events (no screenshots, no coordinate clicks). Reusable probes: `probes.sh`.

## Install / process

- App bundle: **`/Applications/Logic Pro X.app`** (Logic Pro **X**, not "Logic Pro 11").
- Process / executable name (System Events `name`, `pgrep -x`): **`Logic Pro X`**.
  - `pgrep -x "Logic Pro X"` → pid; `pgrep -x "Logic Pro"` → **nothing**.
  - ⚠️ Scaffold assumed `"Logic Pro"`. Worse, `detect_logic_process_name`
    substring-matched `"Logic Pro"` *inside* `"Logic Pro X"` first → returned the
    wrong name → `pgrep -x` would report Logic dead. **Fixed** (exact-match,
    longest/most-specific first).
- `en-AT` / `de-AT` locale — menu strings came back in English. (Watch this:
  localized Logic could rename menu items; we dump, never hard-code blindly.)

## Project window = readiness signal

- Main window name: **`logic test - Tracks`** → `<project stem> - Tracks`,
  role `AXWindow`, subrole `AXStandardWindow`, `sheets = 0`.
- Readiness = a standard window exists AND no sheet is open. Logic can be running
  with **zero** windows before a project finishes opening (`name of windows` empty
  / `missing value` during load), so poll for a real window name.

## Menu path (verbatim)

`File ▸ Export ▸ All Tracks as Audio Files…`  (real ellipsis `…`, U+2026)

File ▸ Export submenu items (full):
```
Region/Cell to Loop Library…, Regions as Audio Files…, Audio Files As…,
Selection as Audio File…, Selection as MIDI File…,
1 Track as Audio File…, All Tracks as Audio Files…, All MIDI Tracks as MIDI File…,
Project as AAF File…, Project to Final Cut Pro XML…, Project as ADM BWF…,
Selection as ADM BWF…, Score as MusicXML…
```
- `1 Track as Audio File…` becomes `n Tracks as Audio Files…` with a multi-track
  selection — the route for per-subtrack stems out of a Summing Stack (§6a, later).

## Export dialog

- Opens as a **separate window titled `Open`** (Cocoa save/nav panel), NOT a sheet.
- Interactive controls (role | name | current value):

| Purpose         | Role           | name                        | value (default)            |
|-----------------|----------------|-----------------------------|----------------------------|
| Folder nav      | AXPopUpButton  | `Where:`                    | `Logic`                    |
| Silence handling| AXPopUpButton  | —                           | `Trim Silence at File End` |
| **File Format** | AXPopUpButton  | —                           | `WAVE`                     |
| **Export mode** | AXPopUpButton  | —                           | `One File per Track`       |
| **Bit depth**   | AXPopUpButton  | —                           | `24-bit`                   |
| **Normalize**   | AXPopUpButton  | —                           | `Overload Protection Only` |
| **Bypass FX**   | AXCheckBox     | `Bypass Effect Plug-ins`    | `0` (off)                  |
| (other cbs)     | AXCheckBox     | `Include Audio Tail`, `Include Volume/Pan Automation`, `Add resulting files to Project Browser` (all `0`), `Include Tempo Information` (`1`) | |
| **Save**        | AXButton       | `Export`                    | —                          |
| Cancel          | AXButton       | `Cancel`                    | —                          |
| New Folder      | AXButton       | `New Folder`                | —                          |
| Show/Hide opts  | AXButton       | `Hide Options`              | —                          |

- ⚠️ The four config pop-ups have **no AXTitle/AXDescription** — only their value
  distinguishes them. Menus are **lazy** (empty until the pop-up is clicked open).
  Stable identification: **positional order** of `pop up button` within window
  `Open` (1 Where, 2 Silence, 3 Format, 4 Mode, 5 Bit depth, 6 Normalize) when
  Options are shown, cross-checked by the value being a member of that control's
  known option set. We click the pop-up, read `menu 1`, then click the item.
- Pop-up option sets (opened to confirm exact strings):
  - **File Format**: `AIFF`, `WAVE`, `CAF`  → we want `WAVE`.
  - **Normalize**: `Off`, `Overload Protection Only`, `On`  → we want `Off`.
  - Export mode default `One File per Track` is exactly per-track stems (leave).
  - Bit depth default `24-bit` (leave; native sample rate isn't in this dialog).

## Wet-pass settings to apply

1. ⌘⇧G → type `output_folder` → Return  (off-Finder path entry).
2. File Format → `WAVE` (only if not already WAVE).
3. Bypass Effect Plug-ins → `0` (read AXValue, click only if differs). Wet = off.
4. Normalize → `Off`.
5. Bit depth → leave `24-bit`; Export mode → leave `One File per Track`.
6. Click button `Export`.

## Notes / open items

- `~/Desktop/logic test folder` (Folder-style fixture) does **not** exist on this
  machine — resolver was unit-tested synthetically instead.
- Sandboxed shell can't read `~/Desktop` (TCC), but `osascript`/System Events and
  `python3` both can — the driver path is unaffected.
