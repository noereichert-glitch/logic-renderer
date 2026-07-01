"""
StemExport Flask backend — Logic Pro edition.
Port 5123. /export triggers the stem orchestration; all settings are locked
defaults so the payload only carries file_path and output_folder.

Reused verbatim from the FL Studio renderer EXCEPT:
  • No als_parser import — Logic projects (.logicx) aren't parsed up front; the
    export names the stems itself, so /parse returns a benign empty structure.
This file is otherwise the proven shared backend: concurrency-guarded /export on
a daemon thread, shared export_state dict, /export/progress polling.
"""
from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import os
import glob
import json
from dotenv import load_dotenv

load_dotenv()

from stem_exporter import StemExporter
from logic_render import resolve_project_path

app = Flask(__name__)
CORS(app)

# Friendly fallback reason for a terminal failure that is NOT a DialogGuard dialog
# (e.g. Logic didn't load, crashed past its retries, or produced too few stems).
GENERIC_FAILURE_REASON = (
    "The render couldn't be completed. Please check the project opens in Logic Pro "
    "and the output folder is writable, then try again."
)
# Single-line stdout marker the Electron main process watches to fire the native
# failure notification. Emitted ONCE, only on a terminal render failure.
EXPORT_FAILURE_MARKER = '[[EXPORT_FAILURE]]'

export_state = {
    'status_title': 'Waiting…',
    'status_sub': '',
    'progress': 0,
    'current_track': '',
    'done': False,
    'error': None,
    'zip_path': None,
    'project_folder': None,
    'sets': {},
}

# Concurrency guard: only one export may run at a time.
_export_lock = threading.Lock()
_export_in_flight = False


def _reset_state(output_folder):
    global export_state
    export_state = {
        'status_title': 'Starting…',
        'status_sub': 'Preparing export',
        'progress': 0,
        'current_track': '',
        'done': False,
        'error': None,
        'zip_path': None,
        'project_folder': None,
        'sets': {},
        'output_folder': output_folder,
        # Critical-failure signal (set only in run_export's terminal except).
        'project': None,
        'reason': None,
        'detail': None,
    }


@app.route('/parse', methods=['POST'])
def parse():
    data = request.json
    file_path = data.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 400
    # Accept a .logicx package OR a folder-style project; resolve to the inner
    # .logicx and reject anything that isn't a Logic project (§11). Logic projects
    # aren't parsed up front (the export names the WAVs itself), so on success the
    # drop UI just needs a benign response plus the resolved path.
    try:
        resolved = resolve_project_path(file_path)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'track_count': 0, 'tracks': [], 'resolved_path': resolved})


@app.route('/export', methods=['POST'])
def export():
    global export_state, _export_in_flight
    data = request.json or {}
    file_path = data.get('file_path')
    output_folder = data.get('output_folder')
    # headless (default True): run the export invisibly/backgrounded. The UI sends
    # only file_path + output_folder, so this stays the default; pass
    # "headless": false in the payload to force the legacy frontmost path.
    headless = bool(data.get('headless', True))

    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'file_path missing or not found'}), 400
    if not output_folder:
        return jsonify({'error': 'output_folder missing'}), 400

    with _export_lock:
        if _export_in_flight:
            return jsonify({'error': 'export already in progress'}), 409
        _export_in_flight = True

    print(f'[Server] One-Click export: {file_path} -> {output_folder}')
    _reset_state(output_folder)

    def run_export():
        global export_state, _export_in_flight
        try:
            exporter = StemExporter(
                file_path=file_path,
                output_folder=output_folder,
                state=export_state,
                headless=headless,
            )
            result = exporter.run()
            export_state['sets'] = result.get('sets', {})
            export_state['zip_path'] = result.get('zip_path')
            export_state['project_folder'] = result.get('project_folder')
            export_state['progress'] = 100
            export_state['status_title'] = 'Export complete'
            export_state['status_sub'] = 'Zip ready in your output folder'
            export_state['done'] = True
        except Exception as e:
            print(f'[Server] Export failed: {e}')
            export_state['done'] = True
            # In-screen "Export failed" display is unchanged (raw error string).
            export_state['error'] = str(e)
            export_state['status_title'] = 'Export failed'
            export_state['status_sub'] = str(e)
            # Critical-failure signal — set ONLY here (the terminal except, after the
            # orchestrator's own auto-handling/retries have given up). A DialogGuard
            # terminal/PAUSE carries a friendly user_message + the verbatim dialog;
            # any other terminal error gets the generic friendly reason.
            project = os.path.basename(file_path)
            reason = (getattr(e, 'user_message', '') or '').strip() or GENERIC_FAILURE_REASON
            export_state['project'] = project
            export_state['reason'] = reason
            export_state['detail'] = getattr(e, 'dialog', None) or {'message': str(e)}
            # One flushed marker line → Electron main fires the native notification
            # AND appends the in-UI inbox entry (detail = raw {title,body,buttons}).
            print(EXPORT_FAILURE_MARKER + json.dumps(
                {'project': project, 'reason': reason,
                 'detail': export_state['detail']}), flush=True)
        finally:
            with _export_lock:
                _export_in_flight = False

    threading.Thread(target=run_export, daemon=True).start()
    return jsonify({'started': True})


@app.route('/export/progress', methods=['GET'])
def export_progress():
    return jsonify({**export_state, 'busy': _export_in_flight})


@app.route('/folder/stems', methods=['POST'])
def folder_stems():
    """Read WAVs from a folder (used by History to re-open past exports)."""
    data = request.json
    folder = data.get('folder')
    if not folder or not os.path.exists(folder):
        return jsonify({'error': 'Folder not found'}), 400
    sets = {}
    for sub in ('01_With_FX', '02_Raw'):
        path = os.path.join(folder, sub)
        if os.path.isdir(path):
            sets[sub] = sorted(glob.glob(os.path.join(path, '*.wav')))
    if not sets:
        sets['_flat'] = sorted(glob.glob(os.path.join(folder, '*.wav')))
    return jsonify({'sets': sets, 'output_folder': folder})


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(port=5123, debug=False)
