"""Streaming wrapper around a pedalboard chain.

Pedalboard's ``PitchShift`` produces almost nothing when it is fed tiny blocks
(a 256-sample block comes back nearly silent), so the chain is run on 2048-sample
windows with 50 % overlap and a square-root Hann crossfade.  That costs one
window of latency (~43 ms at 48 kHz) and keeps the audio continuous while the
microphone callback can stay at 256 frames.
"""

from __future__ import annotations

import math

import numpy as np

#: Samples per processed window hop.  The window is twice the hop.
HOP = 1024

#: Below this level the audio is untouched; above it, peaks are bent smoothly.
SOFT_KNEE = 0.75


def soft_limit(samples: np.ndarray) -> np.ndarray:
    """Transparent peak safety net (unity below the knee, asymptotic to 1.0)."""
    magnitudes = np.abs(samples)
    if magnitudes.size == 0 or float(magnitudes.max()) <= SOFT_KNEE:
        return samples
    span = 1.0 - SOFT_KNEE
    over = magnitudes > SOFT_KNEE
    limited = magnitudes.copy()
    limited[over] = SOFT_KNEE + span * np.tanh((magnitudes[over] - SOFT_KNEE) / span)
    return np.sign(samples) * limited


class StreamingProcessor:
    """Accumulate microphone blocks and emit processed hops."""

    def __init__(self, chain, sample_rate: int, hop: int = HOP) -> None:
        self._chain = chain
        self._rate = int(sample_rate)
        self._hop = int(hop)
        self._window = self._hop * 2
        self._window_gain = np.sqrt(np.hanning(self._window)).astype(np.float32)
        self._input = np.zeros(self._hop, dtype=np.float32)
        self._history = np.zeros(self._hop, dtype=np.float32)
        self._tail = np.zeros(self._window, dtype=np.float32)
        self._fill = 0
        self._phase = 0.0

    # -- info --------------------------------------------------------------
    @property
    def hop(self) -> int:
        return self._hop

    @property
    def window(self) -> int:
        return self._window

    @property
    def latency_seconds(self) -> float:
        return self._window / float(self._rate or 1)

    def reset(self) -> None:
        self._input[:] = 0.0
        self._history[:] = 0.0
        self._tail[:] = 0.0
        self._fill = 0
        self._phase = 0.0

    # -- streaming ---------------------------------------------------------
    def process(self, block: np.ndarray, spec: dict) -> np.ndarray:
        """Consume microphone samples; return zero or more processed samples."""
        samples = np.asarray(block, dtype=np.float32).reshape(-1)
        chunks: list[np.ndarray] = []
        position = 0
        total = samples.shape[0]
        while position < total:
            take = min(self._hop - self._fill, total - position)
            self._input[self._fill:self._fill + take] = samples[position:position + take]
            self._fill += take
            position += take
            if self._fill == self._hop:
                chunks.append(self._process_hop(spec))
                self._fill = 0
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return chunks[0] if len(chunks) == 1 else np.concatenate(chunks)

    def _process_hop(self, spec: dict) -> np.ndarray:
        hop = self._hop
        window = self._window
        chunk = np.concatenate((self._history, self._input))
        self._history = chunk[hop:].copy()

        try:
            processed = self._chain.process(
                chunk.reshape(1, -1), float(self._rate), buffer_size=window, reset=True
            )
            wet = np.asarray(processed, dtype=np.float32).reshape(-1)
        except Exception:  # pragma: no cover - never break the audio callback
            wet = chunk.copy()
        if wet.shape[0] < window:
            wet = np.pad(wet, (0, window - wet.shape[0]))
        elif wet.shape[0] > window:
            wet = wet[:window]
        wet *= self._window_gain

        out = self._tail[:hop] + wet[:hop]
        self._tail[:-hop] = self._tail[hop:]
        self._tail[-hop:] = 0.0
        self._tail[: window - hop] += wet[hop:]

        wet_amount = float(spec.get("wet", 1.0))
        if wet_amount < 0.999:
            dry = chunk[hop:]
            out = dry + (out - dry) * wet_amount

        out = soft_limit(out)

        tremolo = spec.get("tremolo")
        if tremolo:
            rate = float(tremolo.get("rate_hz", 0.0))
            depth = float(tremolo.get("depth", 0.0))
            if rate > 0 and depth > 0:
                step = 2.0 * math.pi * rate / float(self._rate)
                lfo = 1.0 - depth * 0.5 + depth * 0.5 * np.sin(self._phase + step * np.arange(hop))
                out = out * lfo.astype(np.float32)
                self._phase = float((self._phase + step * hop) % (2.0 * math.pi))

        return np.clip(out, -1.0, 1.0).astype(np.float32, copy=False)


def render_blocks(chain, spec: dict, signal: np.ndarray, sample_rate: int, block: int = 256) -> np.ndarray:
    """Offline equivalent of the live path (used by tools/audio_check.py)."""
    processor = StreamingProcessor(chain, sample_rate)
    parts = [processor.process(signal[start:start + block], spec) for start in range(0, signal.shape[0], block)]
    parts = [part for part in parts if part.size]
    if not parts:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(parts)
