#!/usr/bin/env python3
"""
run_job.py — SendStems contract-v1 renderer for Logic Pro sessions.

Reads a job folder prepared by the daemon (job.json + a .logicx session),
drives the REAL StemExporter (two passes: 01_With_FX + 02_Raw, T11 guard,
zip), then satisfies the contract: every exported WAV lands flat in stems/
and .done is written last. The verified zip is kept in the job folder as the
deliverable artifact.

Stdlib-only (like the whole exporter chain) — any python3 can run it.

Usage:  python3 run_job.py <job_folder>
"""
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'python'))
from stem_exporter import StemExporter  # noqa: E402

CONTRACT_VERSION = 1


def render_stems(job_dir: Path, job: dict) -> Path:
    """Run the real Logic export into the job folder; return the zip path."""
    session = job_dir / job["session"]
    if not session.exists():
        raise FileNotFoundError(f"session not found in job folder: {session}")

    state = {}  # progress dict (the Electron UI's export_state; unused here)
    exporter = StemExporter(
        file_path=str(session),
        output_folder=str(job_dir),
        state=state,
        headless=True,
    )
    result = exporter.run()
    zip_path = result.get("zip_path")
    if not zip_path or not Path(zip_path).exists():
        raise RuntimeError("export finished but no zip was produced")
    return Path(zip_path)


def unpack_stems(zip_path: Path, stems_dir: Path):
    """Extract every WAV from the zip flat into stems/ (contract layout).
    No name collisions: raw stems already carry the _raw suffix."""
    stems_dir.mkdir(exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            if not member.lower().endswith(".wav"):
                continue
            target = stems_dir / Path(member).name
            with z.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())
            count += 1
    print(f"[run_job] unpacked {count} stem(s) into {stems_dir.name}/")


def main():
    if len(sys.argv) != 2:
        print("usage: run_job.py <job_folder>", file=sys.stderr)
        return 2

    job_dir = Path(sys.argv[1]).resolve()
    job_path = job_dir / "job.json"
    if not job_path.exists():
        print(f"error: no job.json in {job_dir}", file=sys.stderr)
        return 1

    job = json.loads(job_path.read_text())
    if job.get("version") != CONTRACT_VERSION:
        print(f"error: unsupported contract version {job.get('version')!r}",
              file=sys.stderr)
        return 1

    print(f"[run_job] rendering job {job.get('job_id')} (session={job.get('session')})")
    zip_path = render_stems(job_dir, job)
    unpack_stems(zip_path, job_dir / "stems")

    # Signal completion last, after stems are fully written.
    (job_dir / ".done").touch()
    print("[run_job] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
