"""
Helpers for the One-Click three-pass export flow.
See docs/StemExport_OneClick_Concept_v1.pdf for the spec.
"""
import json
import os
import shutil
import socket
import time
import zipfile
from typing import Iterable

BRIDGE_HOST = '127.0.0.1'
BRIDGE_PORT = 9877


def send_remote_script_command(action: str, payload: dict = None, timeout: float = 30.0) -> dict:
    """
    Send a JSON command to the Ableton Remote Script and return the response.
    Raises on connection failure or non-OK response.
    """
    cmd = {'action': action}
    if payload:
        cmd.update(payload)
    data = json.dumps(cmd).encode('utf-8') + b'\n'

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    try:
        sock.connect((BRIDGE_HOST, BRIDGE_PORT))
        sock.sendall(data)
        sock.settimeout(timeout)
        buf = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b'\n' in buf:
                break
        response = json.loads(buf.decode('utf-8').strip())
    finally:
        try: sock.close()
        except Exception: pass

    if not response.get('ok'):
        raise RuntimeError(f"Remote Script '{action}' failed: {response.get('error')}")
    return response


_DIAG_LOG = '/tmp/stemexport_bypass_diag.log'


def _diag(line: str) -> None:
    try:
        with open(_DIAG_LOG, 'a') as f:
            f.write(line.rstrip() + '\n')
    except Exception:
        pass


def _diag_dump_scopes(label: str) -> None:
    try:
        scopes = list_devices_via_bridge()
    except Exception as e:
        _diag(f'[{label}] list_devices FAILED: {e}')
        return
    total = sum(len(s['devices']) for s in scopes)
    wb = sum(1 for s in scopes for d in s['devices'] if d.get('would_bypass'))
    on_zero = sum(1 for s in scopes for d in s['devices']
                  if d.get('would_bypass') and (d.get('on') == 0.0))
    _diag(f'[{label}] scopes={len(scopes)} devices={total} '
          f'would_bypass={wb} actually_off_among_those={on_zero}')
    # Dump EVERY scope + EVERY device, regardless of would_bypass. This
    # tells us why something is being skipped (wrong type, MIDI rule, or
    # the Device-On safety gate).
    for s in scopes:
        _diag(f'  [{label}] scope: kind={s["kind"]} name={s["name"]!r} '
              f'is_midi={s["is_midi"]} is_group={s["is_group"]} '
              f'devices={len(s["devices"])}')
        for d in s['devices']:
            _diag(f'    dev[{d["index"]}] name={d["name"]!r} type={d["type"]} '
                  f'on={d["on"]} would_bypass={d["would_bypass"]}')


def bypass_audio_devices_via_bridge() -> dict:
    """Bypass all audio-domain devices in the loaded project. Returns response."""
    print('[OneClick] Bypassing audio devices via Remote Script...')
    _diag(f'=== bypass_audio_devices @ {time.strftime("%Y-%m-%d %H:%M:%S")} ===')
    _diag_dump_scopes('BEFORE')
    resp = send_remote_script_command('bypass_audio_devices')
    print(f"[OneClick] Bypassed {resp.get('bypassed', '?')} devices")
    _diag(f'bypass_audio_devices response: {resp}')
    # Small grace period for audio engine to pick up changes
    time.sleep(1.5)
    _diag_dump_scopes('AFTER')
    return resp


def restore_devices_via_bridge() -> dict:
    """Restore device on/off states from the bypass snapshot. Returns response."""
    print('[OneClick] Restoring devices via Remote Script...')
    resp = send_remote_script_command('restore_devices')
    print(f"[OneClick] Restored {resp.get('restored', '?')} devices")
    _diag(f'restore_devices response: {resp}')
    time.sleep(0.5)
    return resp


def list_tracks_via_bridge() -> list:
    """Get the live track list (name, is_group, is_midi) from Ableton."""
    resp = send_remote_script_command('list_tracks')
    return resp.get('tracks', [])


def list_devices_via_bridge() -> list:
    """
    Diagnostic dump of every track + return + master, each with its devices
    and their current on-state. Used by the isolated bypass/restore test
    harness; see ableton_remote_script/StemExportBridge.py::_list_devices.
    """
    resp = send_remote_script_command('list_devices')
    return resp.get('scopes', [])


def sort_wavs_into_subfolder(
    src_folder: str,
    subfolder_name: str,
    exclude_group_wavs: bool,
    group_track_names: Iterable[str],
) -> list:
    """
    Move all .wav files currently in src_folder into src_folder/subfolder_name/.
    If exclude_group_wavs is True, delete (don't move) WAVs whose filename matches
    a known group track name — those are the group submixes and aren't wanted in
    this set. Returns the list of WAV paths that ended up in the subfolder.
    """
    dest_folder = os.path.join(src_folder, subfolder_name)
    os.makedirs(dest_folder, exist_ok=True)

    group_names_lower = {g.lower() for g in group_track_names}
    kept = []

    for entry in os.listdir(src_folder):
        full = os.path.join(src_folder, entry)
        if not os.path.isfile(full) or not entry.lower().endswith('.wav'):
            continue
        stem_name = os.path.splitext(entry)[0]
        if exclude_group_wavs and stem_name.lower() in group_names_lower:
            try:
                os.remove(full)
                print(f'[OneClick] Removed group WAV from set: {entry}')
            except Exception as e:
                print(f'[OneClick] Could not remove {entry}: {e}')
            continue
        dest_path = os.path.join(dest_folder, entry)
        try:
            shutil.move(full, dest_path)
            kept.append(dest_path)
        except Exception as e:
            print(f'[OneClick] Could not move {entry}: {e}')
    print(f'[OneClick] Sorted {len(kept)} WAV(s) into {subfolder_name}/')
    return kept


def zip_project_folder(project_folder: str) -> str:
    """
    Zip the project folder into <parent>/<project_name>.zip.
    Returns the absolute path of the resulting zip.
    """
    project_folder = os.path.abspath(project_folder)
    parent = os.path.dirname(project_folder)
    name = os.path.basename(project_folder)
    zip_path = os.path.join(parent, name + '.zip')

    print(f'[OneClick] Zipping {project_folder} -> {zip_path}')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for root, _, files in os.walk(project_folder):
            for f in files:
                full = os.path.join(root, f)
                arcname = os.path.relpath(full, parent)
                zf.write(full, arcname)
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f'[OneClick] Zip complete: {size_mb:.1f} MB')
    return zip_path
