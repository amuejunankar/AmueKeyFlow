"""Voice FX unit tests: preset tables, cable matching and WAV output.

These never touch an audio device, so they run on any machine.
"""

from __future__ import annotations

import time
import wave

import numpy as np
import pytest

from app.audio import devices
from app.audio.presets import (
    DEFAULT_PRESET,
    MAX_CHAIN_GAIN_DB,
    MAX_GAIN_DB,
    MAX_PITCH,
    MIN_PITCH,
    PRESET_ORDER,
    PRESETS,
    build_chain,
    chain_spec,
    clamp_gain,
    clamp_pitch,
    clamp_wet,
    is_bypass,
    preset,
)
from app.audio.recorder import WavRecorder, recording_path


# -- presets ---------------------------------------------------------------
def test_every_preset_is_registered_and_ordered():
    assert set(PRESETS) == set(PRESET_ORDER)
    assert PRESET_ORDER[0] == DEFAULT_PRESET
    for key in PRESET_ORDER:
        assert PRESETS[key].key == key
        assert PRESETS[key].label
        assert PRESETS[key].hint


def test_unknown_preset_falls_back_to_off():
    assert preset("nonsense").key == DEFAULT_PRESET
    assert preset(None).key == DEFAULT_PRESET
    assert chain_spec("nonsense")["preset"] == DEFAULT_PRESET


def test_presets_have_the_expected_direction():
    assert PRESETS["child"].pitch > PRESETS["woman"].pitch > 0
    assert PRESETS["man"].pitch < 0
    assert PRESETS["elderly"].pitch < 0
    # Elderly is band-limited and slightly unsteady.
    assert PRESETS["elderly"].lowpass_hz < PRESETS["man"].lowpass_hz
    assert PRESETS["elderly"].tremolo_depth > 0


def test_off_is_bypass_until_pitch_is_shifted():
    spec = chain_spec("off")
    assert is_bypass(spec)
    assert spec["bands"] == []
    shifted = chain_spec("off", 4)
    assert not is_bypass(shifted)
    assert shifted["pitch_semitones"] == 4.0
    assert not is_bypass(chain_spec("child"))


def test_pitch_offset_is_added_and_clamped():
    assert chain_spec("woman", 2)["pitch_semitones"] == pytest.approx(5.5)
    spec = chain_spec("child", MAX_PITCH)
    assert spec["pitch_semitones"] == pytest.approx(PRESETS["child"].pitch + MAX_PITCH)
    assert chain_spec("man", MIN_PITCH * 4)["pitch_semitones"] == pytest.approx(PRESETS["man"].pitch + MIN_PITCH)


def test_wet_and_gain_conversion():
    assert chain_spec("man", 0, 100)["wet"] == 1.0
    assert chain_spec("man", 0, 50)["wet"] == 0.5
    assert chain_spec("man", 0, -20)["wet"] == 0.0
    assert chain_spec("man", 0, 180)["wet"] == 1.0
    assert chain_spec("man", 0, 100, 40)["gain_db"] == MAX_CHAIN_GAIN_DB
    assert chain_spec("man", 0, 100, -40)["gain_db"] == -24.0


def test_clamps():
    assert clamp_pitch(99) == MAX_PITCH
    assert clamp_pitch(-99) == MIN_PITCH
    assert clamp_pitch("3") == 3
    assert clamp_pitch("bad") == 0
    assert clamp_wet(140) == 100
    assert clamp_wet(-5) == 0
    assert clamp_gain(100) == MAX_GAIN_DB


def test_chain_spec_band_structure():
    spec = chain_spec("child")
    assert spec["highpass_hz"] > 100
    assert spec["lowpass_hz"] > spec["highpass_hz"]
    for band in spec["bands"]:
        assert band["kind"] in {"peak", "low_shelf", "high_shelf"}
        assert band["frequency_hz"] > 0
        assert band["q"] > 0
    assert spec["compressor"]["ratio"] > 1
    assert spec["tremolo"] is None


def test_tremolo_only_for_elderly():
    assert chain_spec("elderly")["tremolo"]["rate_hz"] > 0
    assert chain_spec("woman")["tremolo"] is None


# -- DSP -------------------------------------------------------------------
def test_build_chain_processes_a_block():
    pytest.importorskip("pedalboard")
    board = build_chain(chain_spec("child"))
    # A fresh board only emits samples when it is reset on the first block.
    block = np.zeros((1, 256), dtype=np.float32)
    first = board.process(block, 48000, buffer_size=256, reset=True)
    second = board.process(block, 48000, buffer_size=256, reset=False)
    assert first.shape == (1, 256)
    assert second.shape == (1, 256)

    signal = (np.random.default_rng(1).standard_normal((1, 1024)) * 0.2).astype(np.float32)
    out = board.process(signal, 48000, buffer_size=1024, reset=True)
    assert np.all(np.isfinite(out))
    # The chain itself does not limit (preset trims can push it above 0 dBFS);
    # the processor's soft limiter is what bounds the output.
    from app.audio.processor import soft_limit

    assert float(np.max(np.abs(soft_limit(out.reshape(-1))))) <= 1.0 + 1e-6


def test_streaming_processor_keeps_the_audio_alive():
    """Regression: pitch shift fed 256-frame blocks used to return near silence."""
    pytest.importorskip("pedalboard")
    from app.audio.processor import StreamingProcessor, render_blocks

    rate = 48000
    noise = (np.random.default_rng(3).standard_normal(rate) * 0.08).astype(np.float32)
    input_rms = float(np.sqrt(np.mean(noise.astype(np.float64) ** 2)))
    for key in ("off", "child", "woman", "man", "elderly"):
        spec = chain_spec(key)
        processor = StreamingProcessor(build_chain(spec), rate)
        out = render_blocks(build_chain(spec), spec, noise, rate)
        assert np.all(np.isfinite(out)), key
        # The output is one window shorter than the input (the overlap-add delay).
        assert out.shape[0] >= noise.shape[0] - processor.window, key
        rms = float(np.sqrt(np.mean(out.astype(np.float64) ** 2)))
        assert rms > input_rms * 0.25, f"{key} output is near silent ({rms:.4f})"


def test_bypass_preset_preserves_level():
    pytest.importorskip("pedalboard")
    from app.audio.processor import render_blocks

    rate = 48000
    noise = (np.random.default_rng(4).standard_normal(rate) * 0.08).astype(np.float32)
    spec = chain_spec("off")
    out = render_blocks(build_chain(spec), spec, noise, rate)
    ratio = float(np.sqrt(np.mean(out.astype(np.float64) ** 2)) / np.sqrt(np.mean(noise.astype(np.float64) ** 2)))
    assert 0.5 < ratio < 1.6


# -- devices ---------------------------------------------------------------
def _device(index, name, api, inputs, outputs):
    return devices.AudioDevice(
        index=index,
        name=name,
        host_api=api,
        max_inputs=inputs,
        max_outputs=outputs,
        default_rate=48000.0,
    )


def test_virtual_cable_matcher():
    assert devices.is_virtual_cable("CABLE Input (VB-Audio Virtual Cable)")
    assert devices.is_virtual_cable("cable output")
    assert devices.is_virtual_cable("VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)")
    assert not devices.is_virtual_cable("Speakers (Realtek High Definition Audio)")
    assert not devices.is_virtual_cable("")


def test_find_cable_output_prefers_wasapi():
    pool = [
        _device(1, "CABLE Input (VB-Audio Virtual Cable)", "MME", 0, 2),
        _device(2, "CABLE Input (VB-Audio Virtual Cable)", "Windows WASAPI", 0, 2),
        _device(3, "Speakers", "Windows WASAPI", 0, 2),
        _device(4, "Microphone", "Windows WASAPI", 1, 0),
    ]
    cable = devices.virtual_cable_output(pool)
    assert cable is not None and cable.index == 2
    installed, message = devices.cable_status(pool)
    assert installed and "CABLE Input" in message


def test_no_cable_reports_install_hint():
    pool = [_device(1, "Speakers", "Windows WASAPI", 0, 2), _device(2, "Mic", "Windows WASAPI", 1, 0)]
    assert devices.virtual_cable_output(pool) is None
    installed, message = devices.cable_status(pool)
    assert not installed
    assert "virtual" in message.lower()


def test_find_device_matches_by_name_and_falls_back():
    pool = [
        _device(1, "Headset (Bluetooth)", "MME", 1, 0),
        _device(2, "Headset (Bluetooth)", "Windows WASAPI", 1, 0),
    ]
    assert devices.find_device(pool, "Headset (Bluetooth)", prefer_input=True).index == 2
    # Unknown names resolve to something usable rather than None.
    assert devices.find_device(pool, "Gone mic", prefer_input=True) is not None
    assert devices.find_device(pool, "", prefer_input=False) is None


def test_picker_hides_duplicates_and_noise():
    """One row per device name, without stereo mix or unnamed placeholders."""
    pool = [
        _device(0, "Windows default microphone", "Windows DirectSound", 1, 0),
        _device(1, "Input ()", "Windows WDM-KS", 2, 0),
        _device(
            2,
            "Input (@System32\\drivers\\bthhfenum.sys,#4;%1 Hands-Free HF Audio%0 ;(Google Pixel 6a))",
            "Windows WDM-KS",
            1,
            0,
        ),
        _device(3, "Line In (Realtek HD Audio Line input)", "Windows WDM-KS", 2, 0),
        _device(4, "Microphone (Realtek HD Audio Mic input)", "Windows WDM-KS", 2, 0),
        _device(5, "Microphone (Realtek HD Audio Mic input)", "Windows WASAPI", 2, 0),
        _device(6, "Stereo Mix (Realtek HD Audio Stereo input)", "Windows WASAPI", 2, 0),
    ]
    picked = devices.pick_devices(pool, prefer_input=True)
    labels = [d.label for d in picked]
    # The duplicate microphone keeps its shared-API copy...
    assert labels.count("Microphone (Realtek HD Audio Mic input)") == 1
    assert picked[labels.index("Microphone (Realtek HD Audio Mic input)")].host_api == "Windows WASAPI"
    # ...while a headset that only exists on WDM-KS is still offered.
    assert "Google Pixel 6a — input" in labels
    assert not any(label.startswith("Input (") or label.startswith("Line In") for label in labels)
    assert not any("Stereo Mix" in label for label in labels)


def test_picker_keeps_devices_that_only_exist_on_one_host_api():
    """Regression: WDM-KS-only speakers and microphones disappeared from Voice FX."""
    pool = [
        _device(0, "Speakers (Realtek HDA Primary output)", "Windows WDM-KS", 0, 6),
        _device(1, "Digital Output (AMD High Definition Audio Device)", "Windows WASAPI", 0, 2),
        _device(2, "Headphones ()", "Windows WDM-KS", 0, 2),
        _device(3, "Microphone (Realtek HD Audio Mic input)", "Windows WDM-KS", 2, 0),
    ]
    outputs = devices.pick_devices(pool, prefer_input=False)
    output_labels = [d.label for d in outputs]
    assert "Speakers (Realtek HDA Primary output)" in output_labels
    assert "Digital Output (AMD High Definition Audio Device)" in output_labels
    assert "Headphones ()" not in output_labels

    inputs = devices.pick_devices(pool, prefer_input=True)
    assert [d.label for d in inputs] == ["Microphone (Realtek HD Audio Mic input)"]
    assert not devices.is_placeholder_endpoint("Microphone (Realtek HD Audio Mic input)")
    assert devices.is_placeholder_endpoint("Headphones ()")
    assert devices.is_placeholder_endpoint("Speakers ( )")


def test_friendly_bluetooth_name():
    raw = "Headset (@System32\\drivers\\bthhfenum.sys,#2;%1 Hands-Free%0 ;(boAt Rugbyy))"
    assert devices.friendly_name(raw) == "boAt Rugbyy — headset"
    assert devices.friendly_name("Speakers (Realtek(R) Audio)") == "Speakers (Realtek(R) Audio)"
    # Driver names carry stray CR/LF; they must not reach the dropdown.
    assert devices.friendly_name("Speakers (Realtek\r\nAudio)") == "Speakers (Realtek Audio)"
    assert devices.is_noise_name("Input ()")
    assert devices.is_noise_name("Microsoft Sound Mapper - Output")
    assert not devices.is_noise_name("Microphone (USB Audio)")


def test_privacy_error_is_explained():
    message = devices.friendly_error(RuntimeError("Error opening InputStream: Access is denied [0x80070005]"))
    assert "Privacy" in message or "microphone access" in message.lower()
    assert devices.friendly_error(RuntimeError("weird")) == "weird"


# -- recording -------------------------------------------------------------
def test_recorder_writes_16bit_mono(tmp_path):
    path = tmp_path / "voice.wav"
    recorder = WavRecorder(path, 48000)
    recorder.push(np.full(480, 0.5, dtype=np.float32))
    recorder.push(np.zeros(480, dtype=np.float32))
    saved = recorder.close()
    assert saved == path
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 48000
        assert handle.getnframes() == 960
    assert recorder.seconds == pytest.approx(0.02, abs=1e-6)


def test_recording_header_is_valid_while_recording(tmp_path):
    """The WAV sizes are patched during capture so the file plays before close."""
    from app.audio.recorder import _PATCH_EVERY

    path = tmp_path / "live.wav"
    recorder = WavRecorder(path, 48000)
    for _ in range(_PATCH_EVERY + 2):
        recorder.push(np.full(256, 0.1, dtype=np.float32))
    deadline = 50
    while recorder.frames < (_PATCH_EVERY - 1) * 256 and deadline:
        time.sleep(0.02)  # let the writer thread catch up
        deadline -= 1
    recorder.close()
    with wave.open(str(path), "rb") as handle:
        assert handle.getnframes() == (_PATCH_EVERY + 2) * 256
        assert handle.getframerate() == 48000
    assert recorder.bytes_written == (_PATCH_EVERY + 2) * 256 * 2 + 44


def test_engine_never_re_enumerates_devices_while_running(monkeypatch):
    """Re-enumerating PortAudio aborts the live stream (and killed recordings)."""
    from app.audio.voice_engine import VoiceEngine

    engine = VoiceEngine(None)
    calls: list[bool] = []

    def fake_list(use_cache: bool = True):
        calls.append(use_cache)
        return []

    monkeypatch.setattr(devices, "list_devices", fake_list)
    engine._state = "running"
    engine._resolve()
    engine._state = "idle"
    engine._resolve()
    assert calls == [True, False]


def test_engine_levels_are_silent_when_idle():
    from app.audio.voice_engine import VoiceEngine

    engine = VoiceEngine(None)
    engine._input_peak = 0.9  # stale value from a dead stream
    engine._output_peak = 0.8
    levels = engine.levels()
    assert levels["input_peak"] == 0.0
    assert levels["output_peak"] == 0.0


def test_recording_paths_are_unique(tmp_path):
    first = recording_path(tmp_path)
    first.touch()
    second = recording_path(tmp_path)
    assert first != second
    assert second.suffix == ".wav"
