#!/usr/bin/env python3
"""
build_python.py — freeze the Logic backend into ONE executable with PyInstaller,
so the stemma app can ship it and the user's Mac needs no Python at all.

Output: dist_python/logic-server

Usage: python3 build_python.py
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd):
    print('\n▶ ' + ' '.join(cmd), flush=True)
    if subprocess.run(cmd, cwd=HERE).returncode != 0:
        sys.exit('build failed')


def main():
    for folder in ('build', 'dist_python'):
        shutil.rmtree(os.path.join(HERE, folder), ignore_errors=True)

    run([
        sys.executable, '-m', 'PyInstaller', # --onedir, not --onefile: a one-file bundle unpacks itself on every launch
        # (~20 s before the server answers); a folder starts in a second or two.
        '--onedir', '--noconfirm',
        '--name', 'logic-server',
        '--distpath', 'dist_python', '--workpath', 'build', '--specpath', 'build',
        # Imported lazily (inside functions / try-blocks) — PyInstaller's static
        # scan would miss them:
        '--hidden-import', 'yaml',
        '--hidden-import', 'ApplicationServices',   # pyobjc: Accessibility pre-flight (permissions.py)        # DialogGuard rules
        '--hidden-import', 'Quartz',      # pyobjc: the 1-second cancel (⌘. to Logic's pid)
        '--hidden-import', 'AppKit',      # pyobjc: NSWorkspace pid lookup
        '--hidden-import', 'Foundation',
        # Data read at runtime, resolved through sys._MEIPASS (dialog_guard.py):
        '--add-data', os.path.join(HERE, 'python', 'dialog_rules.yaml') + ':.',
        # Never needed by the export path (inherited from the old app's recipe):
        '--exclude-module', 'librosa', '--exclude-module', 'anthropic',
        '--exclude-module', 'sklearn', '--exclude-module', 'scipy',
        '--exclude-module', 'matplotlib', '--exclude-module', 'IPython',
        '--exclude-module', 'tkinter', '--exclude-module', 'numpy',
        os.path.join(HERE, 'python', 'server.py'),
    ])

    binary = os.path.join(HERE, 'dist_python', 'logic-server', 'logic-server')
    if not os.path.exists(binary):
        sys.exit('binary not found after build')
    total = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(os.path.dirname(binary)) for f in fs)
    print(f'\n✅ {os.path.dirname(binary)}/ ({total / 1e6:.0f} MB)')


if __name__ == '__main__':
    main()
