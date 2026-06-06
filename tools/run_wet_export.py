"""
run_wet_export.py — Phase 1 verification harness (WET pass only).

Exercises the REAL Logic driver (logic_render.LogicRenderBridge) plus the
orchestrator's own helpers (_validate_set, sort_wavs_into_subfolder,
zip_project_folder) end to end for the `01_With_FX` set, then zips. The Raw pass
(bypass_fx=True) + the T11 raw-differs guard are intentionally NOT run here — they
belong to the next prompt — so we do not call StemExporter.run() (which does both).

Usage:
    python3 tools/run_wet_export.py "<project path>" "<output folder>"
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))

from logic_render import (LogicRenderBridge, resolve_project_path,
                          dismiss_macos_crash_reporter)
from one_click_helpers import sort_wavs_into_subfolder, zip_project_folder
from stem_exporter import StemExporter


def main():
    project = sys.argv[1] if len(sys.argv) > 1 else \
        '/Users/reichertnoe/Desktop/logic test.logicx'
    out = sys.argv[2] if len(sys.argv) > 2 else '/tmp/stemexport_out'

    file_path = resolve_project_path(project)
    project_name = os.path.splitext(os.path.basename(file_path))[0]
    project_folder = os.path.join(out, project_name)
    os.makedirs(project_folder, exist_ok=True)
    print(f'[wet] project  = {file_path}')
    print(f'[wet] dest     = {project_folder}')

    t0 = time.time()
    bridge = LogicRenderBridge()
    print(f'[wet] app      = {bridge.app_path}')

    t_launch = time.time()
    bridge.launch(file_path)
    print(f'[wet] process  = {bridge.process_name}')

    if not bridge.wait_for_logic_ready():
        raise SystemExit('Logic did not become ready.')
    t_ready = time.time()
    print(f'[wet] ready in {t_ready - t_launch:.1f}s')

    dismiss_macos_crash_reporter()

    try:
        t_exp = time.time()
        bridge.export_stems(output_folder=project_folder,
                            file_stem=project_name, bypass_fx=False)
        t_done = time.time()
        print(f'[wet] export+bounce in {t_done - t_exp:.1f}s')

        kept = sort_wavs_into_subfolder(
            src_folder=project_folder, subfolder_name='01_With_FX',
            exclude_group_wavs=False, group_track_names=[])
        print(f'[wet] sorted {len(kept)} WAV(s) into 01_With_FX/')

        # Reuse the orchestrator's real validator (≥2 stems).
        exporter = StemExporter(file_path, out, state={})
        wavs = exporter._validate_set(project_folder, '01_With_FX')
        print(f'[wet] _validate_set OK: {len(wavs)} stems')
        for w in wavs:
            print(f'        - {os.path.basename(w)}  ({os.path.getsize(w)} bytes)')
    finally:
        t_quit = time.time()
        bridge.quit_logic()
        print(f'[wet] Logic quit in {time.time() - t_quit:.1f}s '
              f'(alive now? {bridge.is_alive()})')

    zip_path = zip_project_folder(project_folder)
    print(f'[wet] ZIP = {zip_path}  ({os.path.getsize(zip_path)} bytes)')
    print(f'[wet] TOTAL {time.time() - t0:.1f}s')


if __name__ == '__main__':
    main()
