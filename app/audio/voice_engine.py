"""Real-time microphone processing: input stream → voice chain → output sinks.

One input stream (the microphone) feeds the effect chain; the processed signal is
copied into a small ring buffer per output.  Two outputs can run at once: the
primary target (a virtual cable when one is installed) and headphone monitoring.
Both are ordinary ``sounddevice`` output streams, so no audio driver work is
needed here.

Nothing in this module talks to Qt: the audio callback only touches numpy arrays
and counters, and the page polls :meth:`VoiceEngine.levels` from a timer.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np

from app.audio import devices as dev
from app.audio.presets import build_chain, chain_spec
from app.audio.processor import StreamingProcessor
from app.audio.recorder import WavRecorder, recording_path

log = logging.getLogger(__name__)

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_ERROR = "error"

#: Saved device value meaning "do not play anywhere" (record-only).
NO_OUTPUT = "__none__"

#: Playback buffer per output; small enough to stay responsive, large enough to
#: absorb a scheduling hiccup.
RING_SECONDS = 0.06

#: How long a freshly started input stream gets to deliver its first block.
#: A device that rejects the format reports itself running and dies about 150 ms
#: later; Bluetooth hands-free endpoints can take a second to switch over, so the
#: window is generous — the wait ends as soon as audio arrives.
START_SETTLE_SECONDS = 1.2


class _RingBuffer:
    """Single-producer / single-consumer float ring, dropping the oldest audio."""

    def __init__(self, capacity: int) -> None:
        self._buffer = np.zeros(max(1, int(capacity)), dtype=np.float32)
        self._lock = threading.Lock()
        self._read = 0
        self._write = 0
        self._count = 0
        self.underruns = 0
        self.overwritten = 0

    def reset(self) -> None:
        with self._lock:
            self._buffer[:] = 0.0
            self._read = self._write = self._count = 0

    def write(self, block: np.ndarray) -> None:
        data = np.asarray(block, dtype=np.float32).reshape(-1)
        capacity = self._buffer.shape[0]
        if data.shape[0] > capacity:
            data = data[-capacity:]
        count = data.shape[0]
        with self._lock:
            overflow = self._count + count - capacity
            if overflow > 0:
                self._read = (self._read + overflow) % capacity
                self._count -= overflow
                self.overwritten += overflow
            end = self._write + count
            if end <= capacity:
                self._buffer[self._write:end] = data
            else:
                first = capacity - self._write
                self._buffer[self._write:] = data[:first]
                self._buffer[: count - first] = data[first:]
            self._write = (self._write + count) % capacity
            self._count += count

    def read(self, frames: int) -> np.ndarray:
        out = np.zeros(frames, dtype=np.float32)
        with self._lock:
            take = min(frames, self._count)
            capacity = self._buffer.shape[0]
            end = self._read + take
            if end <= capacity:
                out[:take] = self._buffer[self._read:end]
            else:
                first = capacity - self._read
                out[:first] = self._buffer[self._read:]
                out[first:take] = self._buffer[: take - first]
            self._read = (self._read + take) % capacity
            self._count -= take
            if take < frames:
                self.underruns += 1
        return out


class _OutputSink:
    """One output endpoint fed from the engine's ring buffer."""

    def __init__(self, device: dev.AudioDevice, gain_db: float, capacity: int) -> None:
        self.device = device
        self.gain = float(10 ** (float(gain_db) / 20.0))
        self.ring = _RingBuffer(capacity)
        self.stream = None
        self.peak = 0.0

    def callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        block = self.ring.read(frames)
        if self.gain != 1.0:
            block *= self.gain
        np.clip(block, -1.0, 1.0, out=block)
        outdata[:, 0] = block
        if block.size:
            self.peak = float(np.max(np.abs(block)))


class VoiceEngine:
    def __init__(self, settings=None) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._state = STATE_IDLE
        self._error = ""
        self._stream = None
        self._sinks: list[_OutputSink] = []
        self._processor: StreamingProcessor | None = None
        self._spec = chain_spec("off")
        self._sample_rate = dev.SAMPLE_RATE
        self._blocksize = dev.BLOCK_FRAMES
        self._input_device: dev.AudioDevice | None = None
        self._output_device: dev.AudioDevice | None = None
        self._monitor_device: dev.AudioDevice | None = None
        self._input_peak = 0.0
        self._output_peak = 0.0
        self._latency_ms = 0.0
        self._xruns = 0
        self._recorder: WavRecorder | None = None
        self._recording_path: Path | None = None
        self._frames_seen = 0

    # -- settings ----------------------------------------------------------
    def _value(self, key: str, default=None):
        if self.settings is None:
            return default
        return self.settings.get(key, default)

    def _flag(self, key: str, default: bool = False) -> bool:
        if self.settings is None:
            return default
        return self.settings.get_bool(key, default)

    def current_spec(self) -> dict:
        return chain_spec(
            str(self._value("voice_preset", "off")),
            self._value("voice_pitch", 0),
            self._value("voice_wet", 100),
            self._value("voice_gain", 0),
        )

    def spec(self) -> dict:
        return dict(self._spec)

    def preset_label(self) -> str:
        return str(self._spec.get("label", "Off"))

    # -- state -------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    def is_running(self) -> bool:
        return self._state == STATE_RUNNING

    def error_message(self) -> str:
        return self._error

    def input_device(self) -> dev.AudioDevice | None:
        return self._input_device

    def output_device(self) -> dev.AudioDevice | None:
        return self._output_device

    def monitor_device(self) -> dev.AudioDevice | None:
        return self._monitor_device

    def is_recording(self) -> bool:
        return self._recorder is not None

    def recording_seconds(self) -> float:
        recorder = self._recorder
        return recorder.seconds if recorder else 0.0

    def recording_name(self) -> str:
        recorder = self._recorder
        return recorder.path.name if recorder else ""

    def recording_bytes(self) -> int:
        recorder = self._recorder
        return recorder.bytes_written if recorder else 0

    def levels(self) -> dict:
        running = self._state == STATE_RUNNING
        return {
            # A dead stream must not leave the meter frozen at its last peak.
            "input_peak": self._input_peak if running else 0.0,
            "output_peak": self._output_peak if running else 0.0,
            "underruns": sum(sink.ring.underruns for sink in self._sinks) + self._xruns,
            "latency_ms": self._latency_ms,
            "sample_rate": self._sample_rate,
        }

    def devices(self) -> list[dev.AudioDevice]:
        return dev.list_devices()

    def refresh_devices(self) -> list[dev.AudioDevice]:
        dev.refresh()
        return dev.list_devices()

    def cable(self) -> dev.AudioDevice | None:
        try:
            return dev.virtual_cable_output()
        except dev.AudioUnavailable:
            return None

    # -- chain -------------------------------------------------------------
    def reload(self) -> None:
        """Rebuild the effect chain from the saved settings.

        Safe to call while running: the callback picks up the new chain on its
        next block.  A changed device selection restarts the streams.
        """
        was_running = self._state == STATE_RUNNING
        try:
            spec = self.current_spec()
            chain = build_chain(spec)
        except Exception as exc:
            log.exception("Building the voice chain failed")
            self._error = f"The voice effects could not be prepared: {exc}"
            if not was_running:
                self._state = STATE_ERROR
            return
        with self._lock:
            self._spec = spec
            self._processor = StreamingProcessor(chain, self._sample_rate)
        if was_running and self._selection_changed():
            log.info("Audio device selection changed; restarting the voice stream")
            self.stop()
            self.start()

    def _selection_changed(self) -> bool:
        try:
            inputs, outputs, monitors = self._resolve()
        except Exception:
            return False
        if not inputs:
            return False
        return (
            self._input_device is None
            or inputs[0].index != self._input_device.index
            or (outputs[0].index if outputs else None)
            != (self._output_device.index if self._output_device else None)
            or (monitors[0].index if monitors else None)
            != (self._monitor_device.index if self._monitor_device else None)
        )

    # -- devices -----------------------------------------------------------
    def _resolve(self):
        """Ranked device candidates; index 0 is the preferred endpoint."""
        # Never re-enumerate PortAudio while a stream is open: several host APIs
        # abort the running stream when the device list is rebuilt.
        all_devices = dev.list_devices(use_cache=self._state == STATE_RUNNING)
        inputs = dev.device_candidates(all_devices, str(self._value("voice_input", "")), True)
        saved_output = str(self._value("voice_output", ""))
        if saved_output == NO_OUTPUT:
            outputs: list[dev.AudioDevice] = []
        elif saved_output:
            outputs = dev.device_candidates(all_devices, saved_output, False)
        else:
            # Automatic never means "my speakers": without a virtual cable the
            # processed voice is only recorded, unless monitoring is enabled.
            cable = dev.virtual_cable_output(all_devices)
            outputs = [cable] if cable is not None else []
        monitors: list[dev.AudioDevice] = []
        if self._flag("voice_monitor", False):
            primary = outputs[0].index if outputs else None
            monitors = [
                device
                for device in dev.device_candidates(
                    all_devices, str(self._value("voice_monitor_device", "")), False
                )
                if device.index != primary
            ]
        return inputs, outputs, monitors

    def _candidate_rates(self, input_device: dev.AudioDevice) -> list[int]:
        rates: list[int] = []
        for value in (dev.SAMPLE_RATE, int(input_device.default_rate or 0), 44100):
            if value and 8000 <= value <= 192000 and value not in rates:
                rates.append(int(value))
        return rates

    def _candidate_channels(self, input_device: dev.AudioDevice) -> list[int]:
        """Channel counts to try for the microphone, best first.

        Several Windows WDM-KS microphones (the Realtek array on many laptops) do
        not accept a mono stream.  PortAudio raises nothing: the stream reports
        itself running, delivers no frames and collapses about 150 ms later, after
        which the device answers “Invalid device”.  Only the hardware's own
        channel count works there; the extra channel is simply discarded.
        """
        maximum = max(1, min(2, int(input_device.max_inputs or 1)))
        if maximum >= 2 and "wdm-ks" in str(input_device.host_api or "").lower():
            return [maximum, 1]
        counts = [1]
        if maximum >= 2:
            counts.append(2)
        return counts

    def _primary_gain_db(self) -> float:
        try:
            return float(self._value("voice_gain", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _monitor_gain_db(self) -> float:
        try:
            return float(self._value("voice_monitor_gain", -6) or -6)
        except (TypeError, ValueError):
            return -6.0

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self._state == STATE_RUNNING:
                return True, "Listening"
        try:
            sd = dev.sounddevice_module()
        except dev.AudioUnavailable as exc:
            return self._fail(str(exc))
        try:
            inputs, outputs, monitors = self._resolve()
        except Exception as exc:  # pragma: no cover - backend specific
            return self._fail(dev.friendly_error(exc))
        if not inputs:
            return self._fail("No microphone was found. Connect one, then press Refresh.")

        spec = self.current_spec()
        try:
            chain = build_chain(spec)
        except Exception as exc:
            log.exception("Building the voice chain failed")
            return self._fail(f"The voice effects could not be prepared: {exc}")

        last_error: BaseException | None = None
        # The same endpoint appears once per host API; try them until one opens.
        for input_device in inputs[:4]:
            for output_device in outputs[:2] or [None]:
                for monitor_device in monitors[:2] or [None]:
                    for rate in self._candidate_rates(input_device):
                        for channels in self._candidate_channels(input_device):
                            try:
                                self._open(
                                    sd,
                                    input_device,
                                    output_device,
                                    monitor_device,
                                    rate,
                                    chain,
                                    channels,
                                )
                            except Exception as exc:
                                last_error = exc
                                log.warning(
                                    "Opening %s (%s) at %s Hz, %s channel(s) failed: %s",
                                    input_device.name,
                                    input_device.host_api,
                                    rate,
                                    channels,
                                    exc,
                                )
                                self._teardown()
                                continue
                            with self._lock:
                                self._spec = spec
                                self._state = STATE_RUNNING
                                self._error = ""
                            log.info(
                                "Voice FX on: %s [%s] → %s%s @ %s Hz, %s channel(s), %s",
                                input_device.name,
                                input_device.host_api,
                                output_device.name if output_device else "no output",
                                f" (+ monitor {monitor_device.name})" if monitor_device else "",
                                rate,
                                channels,
                                spec,
                            )
                            return True, "Listening"
        return self._fail(
            dev.friendly_error(last_error) if last_error else "The microphone could not be opened."
        )

    def _open(
        self,
        sd,
        input_device,
        output_device,
        monitor_device,
        rate: int,
        chain,
        input_channels: int = 1,
    ) -> None:
        blocksize = self._blocksize
        ring_capacity = max(blocksize * 8, int(rate * RING_SECONDS))
        sinks: list[_OutputSink] = []
        if output_device is not None:
            sinks.append(_OutputSink(output_device, self._primary_gain_db(), ring_capacity))
        if monitor_device is not None:
            sinks.append(_OutputSink(monitor_device, self._monitor_gain_db(), ring_capacity))

        self._sample_rate = int(rate)
        self._processor = StreamingProcessor(chain, self._sample_rate)
        self._input_peak = 0.0
        self._output_peak = 0.0
        self._xruns = 0

        opened: list[_OutputSink] = []
        try:
            for sink in sinks:
                sink.stream = sd.OutputStream(
                    device=sink.device.index,
                    channels=1,
                    samplerate=rate,
                    blocksize=blocksize,
                    dtype="float32",
                    latency="low",
                    callback=sink.callback,
                )
                opened.append(sink)
            self._sinks = opened
            self._stream = sd.InputStream(
                device=input_device.index,
                channels=int(input_channels),
                samplerate=rate,
                blocksize=blocksize,
                dtype="float32",
                latency="low",
                callback=self._on_audio,
                finished_callback=self._on_stream_finished,
            )
            for sink in opened:
                sink.stream.start()
            self._frames_seen = 0
            self._stream.start()
            self._wait_for_audio(input_device, int(input_channels))
        except Exception:
            for sink in opened:
                try:
                    if sink.stream is not None:
                        sink.stream.close()
                except Exception:  # pragma: no cover
                    pass
            self._sinks = []
            raise

        latency = float(getattr(self._stream, "latency", 0.0) or 0.0)
        if opened:
            latency += max(float(getattr(sink.stream, "latency", 0.0) or 0.0) for sink in opened)
        # The overlap-add window is part of the audible delay.
        if self._processor is not None:
            latency += self._processor.latency_seconds
        self._latency_ms = round(latency * 1000.0, 1)
        self._input_device = input_device
        self._output_device = output_device
        self._monitor_device = monitor_device

    def _wait_for_audio(self, input_device: dev.AudioDevice, channels: int) -> None:
        """Wait for the first real audio block, treating a collapse as a failure.

        A rejected channel count does not raise; the stream looks active for a
        moment and then stops.  Checking both liveness and delivered frames is
        what separates a working microphone from that case.
        """
        deadline = time.monotonic() + START_SETTLE_SECONDS
        while time.monotonic() < deadline:
            if not bool(getattr(self._stream, "active", True)):
                raise RuntimeError(
                    f"{input_device.name} stopped immediately with {channels} channel(s)"
                )
            if self._frames_seen > 0:
                return
            time.sleep(0.02)
        raise RuntimeError(
            f"{input_device.name} delivered no audio with {channels} channel(s)"
        )

    def stop(self) -> None:
        self.stop_recording()
        with self._lock:
            # Mark idle before closing so the finished callback does not report a
            # normal stop as a device failure.
            self._state = STATE_IDLE
        self._teardown()
        self._input_peak = 0.0
        self._output_peak = 0.0
        self._latency_ms = 0.0

    def _on_stream_finished(self) -> None:
        """PortAudio calls this when the stream stops on its own (unplugged, taken)."""
        if self._state != STATE_RUNNING:
            return
        with self._lock:
            self._state = STATE_ERROR
            self._error = (
                "The microphone stream stopped — it may have been unplugged, muted by "
                "Windows, or taken by another application. Press Start listening to reconnect."
            )
        self._input_peak = 0.0
        self._output_peak = 0.0
        log.warning("Voice input stream finished unexpectedly")

    def _teardown(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:  # pragma: no cover
                pass
            try:
                stream.close()
            except Exception:  # pragma: no cover
                pass
        sinks = self._sinks
        self._sinks = []
        for sink in sinks:
            if sink.stream is None:
                continue
            try:
                sink.stream.stop()
            except Exception:  # pragma: no cover
                pass
            try:
                sink.stream.close()
            except Exception:  # pragma: no cover
                pass

    def _fail(self, message: str) -> tuple[bool, str]:
        self._teardown()
        with self._lock:
            self._state = STATE_ERROR
            self._error = message
        log.warning("Voice FX unavailable: %s", message)
        return False, message

    # -- audio thread ------------------------------------------------------
    def _on_audio(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            self._xruns += 1
        try:
            mono = np.asarray(indata[:, 0], dtype=np.float32)
        except Exception:  # pragma: no cover - callback safety
            return
        count = int(mono.shape[0])
        if count == 0:
            return
        self._frames_seen += count
        self._input_peak = float(np.max(np.abs(mono)))

        processor = self._processor
        if processor is None:
            return
        mixed = processor.process(mono, self._spec)
        if mixed.size == 0:
            return
        self._output_peak = float(np.max(np.abs(mixed)))

        sinks = self._sinks
        for sink in sinks:
            sink.ring.write(mixed)
        recorder = self._recorder
        if recorder is not None:
            recorder.push(mixed)

    # -- recording ---------------------------------------------------------
    def start_recording(self) -> tuple[bool, str]:
        if self._state != STATE_RUNNING:
            return False, "Start listening before recording."
        if self._recorder is not None:
            return False, "Already recording."
        stream = self._stream
        if stream is None or not bool(getattr(stream, "active", False)):
            return False, (
                "The microphone stream is not running. Press Start listening, then Record."
            )
        from app.constants import RECORDINGS_DIR

        path = recording_path(RECORDINGS_DIR)
        try:
            self._recorder = WavRecorder(path, self._sample_rate)
        except OSError as exc:
            log.exception("Could not start recording")
            return False, f"The recording could not be started: {exc}"
        self._recording_path = path
        return True, path.name

    def stop_recording(self) -> Path | None:
        recorder = self._recorder
        self._recorder = None
        if recorder is None:
            return None
        path = recorder.close()
        self._recording_path = None
        log.info("Voice recording written to %s (%.1f s)", path, recorder.seconds)
        return path

    def shutdown(self) -> None:
        self.stop()
