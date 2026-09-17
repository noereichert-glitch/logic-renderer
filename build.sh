#!/bin/zsh
# Build the shareable stemma app: freeze BOTH backends, gather the Ableton
# Remote Script, then let electron-builder produce dist/stemma-<version>.dmg.
#   ./build.sh          full build
#   ./build.sh python   freeze the backends only
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ABLETON="${ABLETON_RENDERER:-$HERE/../ableton-renderer}"
# The Python that freezes the backends decides their CPU architecture: the app
# is arm64, so use the arm64 build venv (working/build-venv, python@3.13 +
# flask, pyyaml, pyobjc, numpy, soundfile, pyinstaller) rather than the
# x86_64 Anaconda python3 on PATH, which would make Rosetta a requirement.
PY="${BUILD_PYTHON:-$HERE/../build-venv/bin/python}"
[[ -x "$PY" ]] || { echo "build python not found: $PY (create working/build-venv, see docs)"; exit 1; }
echo "== Python: $PY ($("$PY" -c 'import platform; print(platform.machine())'))"

echo "== Logic backend"
(cd "$HERE" && "$PY" build_python.py)

echo "== Ableton backend ($ABLETON)"
(cd "$ABLETON" && "$PY" build_python.py)
mkdir -p "$HERE/dist_python" "$HERE/build-resources"
rm -rf "$HERE/dist_python/ableton-server"
cp -R "$ABLETON/dist_python/ableton-server" "$HERE/dist_python/ableton-server"
rm -rf "$HERE/build-resources/ableton_remote_script"
cp -R "$ABLETON/ableton_remote_script" "$HERE/build-resources/ableton_remote_script"
find "$HERE/build-resources/ableton_remote_script" -name "__pycache__" -type d -prune -exec rm -rf {} +

[[ "${1:-}" == "python" ]] && { echo "backends frozen: dist_python/"; exit 0; }

echo "== Electron app"
# Two steps, not one: electron-builder without a Developer ID leaves the bundle
# carrying Electron's own (now invalid) seal, and Apple Silicon refuses to run
# a bundle whose signature does not verify — it just exits. So build the .app,
# ad-hoc sign the whole bundle ourselves, then wrap the signed app in the dmg.
# (A Developer ID + notarization replaces the ad-hoc step later.)
(cd "$HERE" && env -u ELECTRON_RUN_AS_NODE ./node_modules/.bin/electron-builder --dir)
APP="$HERE/dist/mac-arm64/stemma.app"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP" && echo "ad-hoc signature verified"
(cd "$HERE" && env -u ELECTRON_RUN_AS_NODE ./node_modules/.bin/electron-builder --prepackaged "$APP")
ls -la "$HERE/dist"/*.dmg
