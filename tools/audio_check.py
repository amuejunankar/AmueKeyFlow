"""Audio pipeline check: devices, every preset and a live microphone capture.

Run with::

    python tools/audio_check.py            # offline render + live capture
    python tools/audio_check.py --offline  # offline render only

WAV files are written to the directory printed at the end (``AMUE_AUDIO_OUT``
overrides it).  This proves the pipeline runs and is neither silent nor
crashing; whether a preset *sounds* like a child can only be judged by ear.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from app.audio import devices as dev  # noqa: E402
from app.audio.presets import PRESET_ORDER, build_chain, chain_spec, describe  # noqa: E402
from app.audio.processor import StreamingProcessor, render_blocks  # noqa: E402
from app.audio.voice_engine import NO_OUTPUT, VoiceEngine  # noqa: E402

BLOCK = 256
SECONDS = 2.0


class _Settings:
    """Minimal stand-in for SettingsManager."""

    def __init__(self, values: dict) -> None:
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)

    def get_bool(self, key, default=False):
        return bool(self.values.get(key, default))


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(pcm.tobytes())


def stats(samples: np.ndarray) -> tuple[float, float, bool]:
    if samples.size == 0:
        return 0.0, 0.0, True
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    return peak, rms, bool(np.all(np.isfinite(samples)))


def synth_voice(rate: int, seconds: float, seed: int = 7) -> np.ndarray:
    """A rough voiced signal: f0 sweep + harmonics + breath noise."""
    rng = np.random.default_rng(seed)
    count = int(rate * seconds)
    t = np.arange(count, dtype=np.float32) / rate
    f0 = 112.0 + 14.0 * np.sin(2 * np.pi * 0.7 * t) - 10.0 * t / seconds
    phase = 2 * np.pi * np.cumsum(f0) / rate
    signal = np.zeros(count, dtype=np.float32)
    for harmonic, level in ((1, 1.0), (2, 0.55), (3, 0.32), (4, 0.2), (5, 0.12), (6, 0.08)):
        signal += level * np.sin(phase * harmonic)
    # Amplitude envelope so the output has both loud and quiet moments.
    signal *= 0.35 * (0.6 + 0.4 * np.sin(2 * np.pi * 1.3 * t))
    signal += rng.standard_normal(count).astype(np.float32) * 0.01
    return np.clip(signal, -1.0, 1.0)


def offline_render(out_dir: Path, rate: int = 48000) -> None:
    signal = synth_voice(rate, SECONDS)
    print("\nOffline render (synthetic voice):")
    for key in PRESET_ORDER:
        spec = chain_spec(key)
        # Exactly the live path: 256-frame blocks into the overlap-add processor.
        rendered = render_blocks(build_chain(spec), spec, signal, rate, BLOCK)
        peak, rms, finite = stats(rendered)
        path = out_dir / f"offline-{key}.wav"
        write_wav(path, rendered, rate)
        print(
            f"  {key:<8} {describe(spec):<38} "
            f"peak {peak:5.2f} rms {rms:5.3f} finite={finite} "
            f"latency {StreamingProcessor(build_chain(spec), rate).latency_seconds * 1000:.0f} ms "
            f"-> {path.name}"
        )


def list_audio() -> bool:
    try:
        dev.sounddevice_module()
    except dev.AudioUnavailable as exc:
        print(f"Audio backend unavailable: {exc}")
        return False
    print("Host APIs:", ", ".join(api["name"] for api in __import__("sounddevice").query_hostapis()))
    print("\nDevices:")
    for device in dev.list_devices(use_cache=False):
        marks = []
        if device.is_input:
            marks.append("in")
        if device.is_output:
            marks.append("out")
        if dev.is_virtual_cable(device.name):
            marks.append("virtual cable")
        print(f"  [{device.index:2}] {device.name} — {device.host_api} ({', '.join(marks)})")
    installed, message = dev.cable_status()
    print(f"\nVirtual microphone installed: {installed}\n  {message}\n")
    return True


def live_capture(out_dir: Path) -> int:
    settings = _Settings(
        {
            "voice_preset": "off",
            "voice_pitch": 0,
            "voice_wet": 100,
            "voice_gain": 0,
            "voice_input": "",
            "voice_output": NO_OUTPUT,  # never play into the room
            "voice_monitor": False,
            "voice_monitor_device": "",
            "voice_monitor_gain": -6,
        }
    )
    engine = VoiceEngine(settings)
    ok, message = engine.start()
    if not ok:
        print(f"Live capture failed: {message}")
        return 1
    device = engine.input_device()
    print(f"Live capture from: {device.name if device else '?'}")

    failures = 0
    captured: list[int] = []
    for key in PRESET_ORDER:
        settings.values["voice_preset"] = key
        engine.reload()
        started, note = engine.start_recording()
        if not started:
            print(f"  {key:<8} could not record: {note}")
            failures += 1
            continue
        time.sleep(SECONDS)
        path = engine.stop_recording()
        levels = engine.levels()
        peak = levels["output_peak"]
        if path is None:
            print(f"  {key:<8} no file produced")
            failures += 1
            continue
        target = out_dir / f"live-{key}.wav"
        path.replace(target)
        with wave.open(str(target), "rb") as handle:
            frames = handle.getnframes()
        print(
            f"  {key:<8} {describe(engine.spec()):<38} frames {frames:6} "
            f"peak {peak:5.3f} xruns {levels['underruns']} "
            f"latency {levels['latency_ms']:.1f} ms -> {target.name}"
        )
        captured.append(frames)
        if frames < 24000:
            failures += 1
    engine.stop()
    if captured and max(captured) < 24000:
        print(
            "  note: the microphone delivered little or no audio — Windows may have it "
            "muted, disabled, or blocked under Settings → Privacy & security → Microphone."
        )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Voice FX audio pipeline")
    parser.add_argument("--offline", action="store_true", help="skip the live microphone")
    parser.add_argument("--out", default=os.environ.get("AMUE_AUDIO_OUT", ""))
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="keyflow-audio-"))
    out_dir.mkdir(parents=True, exist_ok=True)

    if not list_audio():
        return 1
    offline_render(out_dir)
    code = 0
    if not args.offline:
        print("\nLive microphone capture (2 s per preset, no playback):")
        code = live_capture(out_dir)
    print(f"\nWAV files: {out_dir}")
    return code


if __name__ == "__main__":
    sys.exit(main())
