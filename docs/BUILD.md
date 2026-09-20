# Building the shareable stemma app

`./build.sh` produces `dist/stemma-<version>-arm64.dmg`: the Electron app with BOTH
backends frozen inside it (no Python on the target Mac) and the Ableton Remote
Script it installs into Live.

## One-time setup

1. Node deps: `npm install` in this repo.
2. An **arm64** Python to freeze the backends with (the app is arm64; a backend
   frozen with the x86_64 Anaconda `python3` would make Rosetta a requirement):

       /opt/homebrew/opt/python@3.13/bin/python3.13 -m venv ../build-venv
       ../build-venv/bin/pip install flask==3.0.0 flask-cors==4.0.0 python-dotenv==1.0.0 \
           pyyaml pyobjc-framework-Quartz pyobjc-framework-Cocoa pyobjc-framework-ApplicationServices \
           numpy soundfile pyinstaller

   `build.sh` uses `../build-venv/bin/python` (override with `BUILD_PYTHON=`).
3. The Ableton renderer checked out next to this repo (`../ableton-renderer`, or
   `ABLETON_RENDERER=` path).

## What the build does

- `build_python.py` here → `dist_python/logic-server/` (PyInstaller one-dir; bundles
  `dialog_rules.yaml`, pyobjc for the cancel, PyYAML for DialogGuard).
- `../ableton-renderer/build_python.py` → `ableton-server` (adds numpy + soundfile for
  the silence check), copied into `dist_python/`; the Remote Script folder is copied
  to `build-resources/ableton_remote_script/`.
- electron-builder packs `electron/` + those resources into `stemma.app`, the bundle
  is **ad-hoc signed** (Apple Silicon will not run an unsigned/broken-seal bundle —
  it silently exits), then wrapped into the dmg. A Developer ID + notarization
  replaces the ad-hoc step for wider distribution (`electron-builder` picks the
  identity up from the Keychain automatically).

## Gotchas

- **`ELECTRON_RUN_AS_NODE`**: VS Code's integrated terminal sets it, and it makes any
  Electron binary behave like plain Node (the packaged app exits with code 0 and no
  output). `build.sh` unsets it for electron-builder; launch test builds from
  Terminal.app, or `env -u ELECTRON_RUN_AS_NODE dist/mac-arm64/stemma.app/Contents/MacOS/stemma`.
- The frozen backends start in a few seconds (one-dir bundles; a one-file build took
  ~20 s to unpack itself on every launch). The health pill shows "Renderers initiating…"
  meanwhile, and Render buttons stay disabled until a row's backend answers.
- Unsigned test builds: the recipient must right-click → Open the first time
  (Gatekeeper), or `xattr -d com.apple.quarantine stemma.app`.
- **Every ad-hoc build is a new identity to macOS permissions.** An ad-hoc signature's
  designated requirement is the bundle's `cdhash` (`codesign -d -r- stemma.app`), so
  Accessibility / Automation grants made for one build do not carry over to the next:
  the toggle in System Settings can show ON while the new build is not actually trusted
  (a DAW driven with no AX access looks like a hang or a dialog that never dismisses).
  After installing a new build, remove stemma from Privacy & Security → Accessibility
  (the "–" button) and let the pre-flight prompt re-add it; expect the Automation
  prompt for System Events again. A Developer ID signature is identity-based and
  removes this problem.
- **Remote Script**: shipped as `Resources/ableton_remote_script/`; the Ableton backend
  installs it into Live's User Library on each render if missing or stale
  (`ableton-renderer/python/remote_script_installer.py`, `STEMEXPORT_REMOTE_SCRIPT_SRC`
  from main.js). Bump `BRIDGE_VERSION` there when `StemExportBridge.py` changes.
- **Backend logs** of a packaged app: `~/Library/Logs/stemma/logic-backend.log` and
  `ableton-backend.log` (previous launch in `.log.1`). Everything the backends print,
  minus the two polling routes. Ask a tester for these files before anything else.
- Build artefacts (`build/`, `dist/`, `dist_python/`, `build-resources/ableton_remote_script/`)
  are git-ignored; `build-resources/icon.icns` (generated from `icon.svg`) is tracked.
