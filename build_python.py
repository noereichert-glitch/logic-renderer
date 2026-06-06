#!/usr/bin/env python3
"""
build_python.py — bundles the Python backend into a single executable
using PyInstaller. Run this before electron-builder.

Usage: python3 build_python.py
"""

import subprocess
import sys
import os
import shutil

def run(cmd, **kwargs):
    print(f'\n▶ {" ".join(cmd)}')
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f'❌ Command failed with code {result.returncode}')
        sys.exit(1)
    return result

def main():
    # Install PyInstaller if needed
    run([sys.executable, '-m', 'pip', 'install', 'pyinstaller', '--quiet'])

    # Clean previous build
    for folder in ['build', 'dist_python']:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f'🗑  Cleaned {folder}/')

    # Build the Python server into a single executable
    run([
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--name', 'stemexport-server',
        '--distpath', 'dist_python',
        '--workpath', 'build',
        '--specpath', 'build',
        '--hidden-import', 'flask',
        '--hidden-import', 'flask_cors',
        '--hidden-import', 'librosa',
        '--hidden-import', 'numpy',
        '--hidden-import', 'soundfile',
        '--hidden-import', 'anthropic',
        '--hidden-import', 'sklearn',
        '--hidden-import', 'scipy',
        '--collect-all', 'librosa',
        '--collect-all', 'soundfile',
        'python/server.py'
    ])

    # Verify output
    binary = 'dist_python/stemexport-server'
    if os.path.exists(binary):
        size = os.path.getsize(binary) / (1024 * 1024)
        print(f'\n✅ Python binary built: {binary} ({size:.1f} MB)')
        print('   Now run: ./node_modules/.bin/electron-builder')
    else:
        print('❌ Binary not found after build')
        sys.exit(1)

if __name__ == '__main__':
    main()
