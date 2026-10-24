"""Windows FFmpeg launcher; apply native limits before starting any decoder."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.platform_process import apply_windows_worker_limits,background_options


def main():
    if os.name!='nt' or len(sys.argv)<3:
        raise ValueError('WINDOWS_AUDIO_WORKER_ARGUMENTS')
    executable=Path(sys.argv[1]).resolve(strict=True)
    if executable.name.lower()!='ffmpeg.exe' or not executable.is_file():
        raise ValueError('WINDOWS_AUDIO_DECODER_INVALID')
    apply_windows_worker_limits(memory_bytes=1024*1024*1024,cpu_seconds=3600)
    # The child inherits the Job Object and the existing bounded pipe rings.
    # Closing this worker kills its decoder too, including during cancellation.
    return subprocess.call([str(executable),*sys.argv[2:]],stdin=sys.stdin.buffer,
                           stdout=sys.stdout.buffer,stderr=sys.stderr.buffer,
                           **background_options())


if __name__=='__main__':raise SystemExit(main())
