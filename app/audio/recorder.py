"""WAV capture of the processed microphone signal.

The audio callback must never touch the disk, so blocks are handed to a small
writer thread through a bounded queue.  Standard library only.

The file is a normal 16-bit PCM WAV whose RIFF/data sizes are patched every
fraction of a second while recording, so the file is playable *during* a
recording instead of looking empty until it is closed.
"""

from __future__ import annotations

import logging
import queue
import struct
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_QUEUE_BLOCKS = 64  # ~0.35 s at 256 frames / 48 kHz
_PATCH_EVERY = 12  # blocks between header updates (~0.5 s at 256 frames)


def wav_header(sample_rate: int, data_bytes: int, channels: int = 1, width: int = 2) -> bytes:
    """Canonical 44-byte PCM WAV header for a known payload size."""
    byte_rate = sample_rate * channels * width
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_bytes,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channels,
        sample_rate,
        byte_rate,
        channels * width,
        width * 8,
        b"data",
        data_bytes,
    )


class WavRecorder:
    """Write mono float blocks to a 16-bit PCM WAV file from a worker thread."""

    def __init__(self, path: Path, sample_rate: int) -> None:
        self.path = Path(path)
        self.sample_rate = int(sample_rate)
        self.frames = 0
        self.dropped = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._queue: queue.Queue = queue.Queue(maxsize=_QUEUE_BLOCKS)
        self._closed = False
        self._error: str | None = None
        self._written = 0  # payload bytes
        self._handle = open(self.path, "wb")
        self._handle.write(wav_header(self.sample_rate, 0))
        self._handle.flush()
        self._thread = threading.Thread(target=self._write_loop, name="voice-recorder", daemon=True)
        self._thread.start()

    # -- audio thread ------------------------------------------------------
    def push(self, block: np.ndarray) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(np.array(block, dtype=np.float32, copy=True))
        except queue.Full:
            self.dropped += 1

    # -- writer thread -----------------------------------------------------
    def _patch_sizes(self) -> None:
        self._handle.seek(4)
        self._handle.write(struct.pack("<I", 36 + self._written))
        self._handle.seek(40)
        self._handle.write(struct.pack("<I", self._written))
        self._handle.seek(0, 2)  # back to the end for the next payload

    def _write_loop(self) -> None:
        pending = 0
        while True:
            item = self._queue.get()
            if item is None:
                break
            try:
                pcm = np.clip(item, -1.0, 1.0)
                pcm = (pcm * 32767.0).astype("<i2")
                payload = pcm.tobytes()
                self._handle.write(payload)
                self._written += len(payload)
                self.frames += int(pcm.shape[0])
                pending += 1
                if pending >= _PATCH_EVERY:
                    # Keep the header truthful so the file plays while recording.
                    self._patch_sizes()
                    self._handle.flush()
                    pending = 0
            except Exception as exc:  # pragma: no cover - disk failures
                self._error = str(exc)
                log.exception("Writing the recording failed")
                break
        try:
            self._patch_sizes()
            self._handle.flush()
            self._handle.close()
        except Exception:  # pragma: no cover
            log.exception("Closing the recording failed")

    # -- api ---------------------------------------------------------------
    @property
    def error(self) -> str | None:
        return self._error

    @property
    def seconds(self) -> float:
        return self.frames / float(self.sample_rate or 1)

    @property
    def bytes_written(self) -> int:
        return self._written + 44

    def close(self) -> Path:
        if self._closed:
            return self.path
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:  # make room for the stop marker
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(None)
            except queue.Full:  # pragma: no cover
                pass
        self._thread.join(timeout=2.0)
        return self.path


def recording_path(folder: Path, prefix: str = "voice") -> Path:
    """A new, timestamped file name inside ``folder``."""
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = folder / f"{prefix}-{stamp}.wav"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{prefix}-{stamp}-{counter}.wav"
        counter += 1
    return candidate
