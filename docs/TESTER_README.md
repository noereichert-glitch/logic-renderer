---
title: "stemma"
subtitle: "Read me first — test build for early testers"
date: "22 September 2026"
geometry: margin=2.3cm
fontsize: 11pt
---

# What stemma does

stemma turns a Logic Pro or Ableton Live project into a zip of stems with one click: every track
as its own audio file, once with effects and once without, checked and packed for you. You keep
using your Mac while it works. Your project file is never saved or changed.

This is an early test build. It works on our machines; you are the first person outside the team
to run it. Anything that looks wrong is worth telling us about, even if it seems small.

# What you need

- A Mac with an **Apple Silicon** chip (M1 or later).
- **Logic Pro** or **Ableton Live 12** installed and working in your account. stemma drives the
  DAW you already have; it does not include one.
- The file `stemma-1.0.0-arm64.dmg` we sent you.

# Installing (once)

1. Open the dmg and drag **stemma** into your Applications folder.
2. In Applications, **right-click stemma and choose Open**. macOS will warn that it cannot verify
   the developer; click Open anyway. This happens only the first time, because the test build is
   not yet registered with Apple. Double-clicking works from then on.

# Your first render

1. Click **Add projects** and pick a Logic project (`.logicx`) or an Ableton set (`.als`). The
   project stays where it is; stemma only remembers where to find it.
2. Press **Render** on the row.
3. The row will say **Permission needed** and macOS will open a prompt. stemma needs
   *Accessibility* access to operate the DAW for you. In System Settings, under Privacy &
   Security, Accessibility, switch **stemma** on. Then **quit stemma and open it again**.
4. Press **Render** again. macOS may ask once whether stemma may control *System Events*: click
   **Allow**.
5. Now the DAW opens in the background and the row shows what stemma is doing. **Keep your hands
   off the keyboard and mouse until the row turns green.** A typical project takes a few minutes.
6. Green means done. Click the green text to open the folder with the zip. An amber ⚠ next to it
   means the stems are fine but there is something you should know, for example a muted track that
   was left out. Click the ⚠ to read it.

# Where things go

- Your renders land in the folder shown at the top of the window. Keep it on your internal disk
  for now; external drives are not tested yet.
- Ableton users: stemma places a small helper called *StemExportBridge* into Live's User Library
  the first time you render. That is expected. It lets stemma switch effects off for the dry stems
  and switch them back on afterwards.

# If something goes wrong

A red **Failed** on the row means the render did not complete. Click it to read why. Then send us:

1. The text behind the red Failed pill.
2. The folder `~/Library/Logs/stemma`. In Finder: menu **Go**, **Go to Folder…**, paste the path,
   press Return, and send us the folder or the files inside it.
3. Which DAW, which project, and what you saw on screen.

Two things we already know about:

- If the DAW shows a dialog we have not seen before, for example a first-launch welcome screen
  or a sound-library download, stemma stops rather than guessing. Dismiss it in the DAW, then
  render again. Tell us what the dialog said.
- If we send you a newer build, macOS treats it as a new app. In Accessibility, remove stemma with
  the minus button and switch it on again when stemma asks.

# What we would love to hear

- Did the first render work without asking us anything?
- Did anything in the window confuse you?
- Open the zip: are the stems the ones you expected, named the way you expect?
- Anything else, however small.

Thank you for testing.
