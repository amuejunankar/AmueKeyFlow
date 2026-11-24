"""Voice presets: the parameter table and the pedalboard chain built from it.

The tuning lives in plain numbers (:func:`chain_spec`) so it can be inspected and
tested without an audio device.  :func:`build_chain` is the only place that
imports ``pedalboard``, and it does so lazily so the UI can start even when the
audio libraries are unavailable.

A preset is a pitch shift plus a formant-ish EQ tilt, exactly what consumer
voice changers do.  It makes a voice sound younger/older/larger, but it is not
ML voice conversion and does not turn you into a different speaker.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Display order of the built-in presets.
PRESET_ORDER = ("off", "child", "woman", "man", "elderly")

DEFAULT_PRESET = "off"
DEFAULT_PITCH = 0
MIN_PITCH = -12
MAX_PITCH = 12
MIN_GAIN_DB = -12.0
MAX_GAIN_DB = 12.0

#: Hard ceiling for the summed trim + user volume inside the chain.  Child needs a
#: large trim because pitch shifting and the low-shelf cut remove a lot of energy.
MAX_CHAIN_GAIN_DB = 20.0

#: ``(kind, cutoff_hz, gain_db, q)`` — kind is one of the filter factories below.
Band = tuple[str, float, float, float]


@dataclass(frozen=True)
class VoicePreset:
    key: str
    label: str
    hint: str
    pitch: float
    highpass_hz: float
    lowpass_hz: float
    bands: tuple[Band, ...] = ()
    compressor: tuple[float, float] | None = None  # (threshold_db, ratio)
    drive_db: float = 0.0
    tremolo_hz: float = 0.0
    tremolo_depth: float = 0.0
    output_db: float = 0.0


PRESETS: dict[str, VoicePreset] = {
    "off": VoicePreset(
        key="off",
        label="Off",
        hint="Your normal voice, latency only.",
        pitch=0.0,
        highpass_hz=55.0,
        lowpass_hz=18000.0,
    ),
    "child": VoicePreset(
        key="child",
        label="Child",
        hint="Higher and lighter, like a young child.",
        pitch=7.0,
        highpass_hz=180.0,
        lowpass_hz=15000.0,
        bands=(
            ("low_shelf", 260.0, -7.0, 0.7),
            ("peak", 900.0, -3.0, 0.9),
            ("peak", 3300.0, 5.0, 0.9),
        ),
        compressor=(-22.0, 3.0),
        output_db=14.0,
    ),
    "woman": VoicePreset(
        key="woman",
        label="Woman",
        hint="Brighter, slightly higher than your voice.",
        pitch=3.5,
        highpass_hz=130.0,
        lowpass_hz=17000.0,
        bands=(
            ("low_shelf", 220.0, -5.0, 0.7),
            ("peak", 700.0, -2.0, 0.9),
            ("peak", 2800.0, 3.5, 0.9),
        ),
        output_db=8.5,
    ),
    "man": VoicePreset(
        key="man",
        label="Man",
        hint="Deeper chest voice.",
        pitch=-3.5,
        highpass_hz=70.0,
        lowpass_hz=16000.0,
        bands=(
            ("low_shelf", 190.0, 4.0, 0.7),
            ("peak", 420.0, 2.0, 0.8),
            ("peak", 2900.0, -3.0, 0.9),
        ),
        compressor=(-20.0, 2.5),
        output_db=7.5,
    ),
    "elderly": VoicePreset(
        key="elderly",
        label="Elderly",
        hint="Thinner, a little unsteady.",
        pitch=-1.0,
        highpass_hz=110.0,
        lowpass_hz=5800.0,
        bands=(
            ("peak", 800.0, -2.0, 0.9),
            ("peak", 1500.0, 4.0, 1.0),
            ("peak", 4200.0, -4.0, 0.8),
        ),
        drive_db=1.5,
        tremolo_hz=5.2,
        tremolo_depth=0.14,
        output_db=2.5,
    ),
}


def preset(key: str) -> VoicePreset:
    return PRESETS.get(str(key or DEFAULT_PRESET), PRESETS[DEFAULT_PRESET])


def clamp(value: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        # A missing or corrupt setting means "no change", not the minimum.
        number = 0.0
    if number != number:  # NaN
        number = 0.0
    return max(low, min(high, number))


def clamp_pitch(value: float) -> int:
    """Pitch fine-tune in whole semitones."""
    return int(round(clamp(value, MIN_PITCH, MAX_PITCH)))


def clamp_wet(value: float) -> int:
    """Dry/wet mix in percent."""
    return int(round(clamp(value, 0.0, 100.0)))


def clamp_gain(value: float) -> float:
    return round(clamp(value, MIN_GAIN_DB, MAX_GAIN_DB), 1)


def chain_spec(
    key: str,
    pitch_offset: float = DEFAULT_PITCH,
    wet_percent: float = 100.0,
    gain_db: float = 0.0,
) -> dict:
    """Resolve a preset and the user's fine-tuning into plain numbers."""
    p = preset(key)
    bands = [
        {"kind": kind, "frequency_hz": float(freq), "gain_db": float(gain), "q": float(q)}
        for kind, freq, gain, q in p.bands
    ]
    return {
        "preset": p.key,
        "label": p.label,
        "pitch_semitones": round(clamp(p.pitch + clamp_pitch(pitch_offset), -24.0, 24.0), 2),
        "highpass_hz": p.highpass_hz,
        "lowpass_hz": p.lowpass_hz,
        "bands": bands,
        "compressor": None
        if p.compressor is None
        else {"threshold_db": p.compressor[0], "ratio": p.compressor[1]},
        "drive_db": p.drive_db,
        "tremolo": None
        if p.tremolo_depth <= 0 or p.tremolo_hz <= 0
        else {"rate_hz": p.tremolo_hz, "depth": p.tremolo_depth},
        # The preset's own trim keeps every voice at a similar loudness.
        "gain_db": round(clamp(gain_db + p.output_db, -24.0, MAX_CHAIN_GAIN_DB), 2),
        "wet": round(clamp(wet_percent, 0.0, 100.0) / 100.0, 3),
    }


def is_bypass(spec: dict) -> bool:
    """True when the chain would only add latency (preset Off, no pitch shift)."""
    return (
        spec.get("preset", DEFAULT_PRESET) == "off"
        and abs(float(spec.get("pitch_semitones", 0.0))) < 0.01
    )


def build_chain(spec: dict):
    """Build the pedalboard plugin chain for a resolved spec (lazy import)."""
    import pedalboard as pb

    chain: list = []
    if float(spec.get("highpass_hz", 0)) > 20:
        chain.append(pb.HighpassFilter(cutoff_frequency_hz=float(spec["highpass_hz"])))

    pitch = float(spec.get("pitch_semitones", 0.0))
    if abs(pitch) >= 0.01:
        chain.append(pb.PitchShift(semitones=pitch))

    for band in spec.get("bands", []):
        kind = band.get("kind")
        kwargs = {
            "cutoff_frequency_hz": float(band["frequency_hz"]),
            "gain_db": float(band["gain_db"]),
            "q": float(band["q"]),
        }
        if kind == "low_shelf":
            chain.append(pb.LowShelfFilter(**kwargs))
        elif kind == "high_shelf":
            chain.append(pb.HighShelfFilter(**kwargs))
        else:
            chain.append(pb.PeakFilter(**kwargs))

    compressor = spec.get("compressor")
    if compressor:
        chain.append(
            pb.Compressor(
                threshold_db=float(compressor["threshold_db"]),
                ratio=float(compressor["ratio"]),
                attack_ms=8.0,
                release_ms=120.0,
            )
        )

    drive = float(spec.get("drive_db", 0.0))
    if drive > 0:
        # Soft saturation: a distortion pedal at a low drive level.
        chain.append(pb.Distortion(drive_db=drive))

    if float(spec.get("lowpass_hz", 0)) > 0:
        chain.append(pb.LowpassFilter(cutoff_frequency_hz=float(spec["lowpass_hz"])))

    gain = float(spec.get("gain_db", 0.0))
    if abs(gain) >= 0.01:
        chain.append(pb.Gain(gain_db=gain))

    # No pb.Limiter here: it applies up to +9 dB of makeup gain, which would make
    # every preset a different loudness.  The processor applies a soft limiter
    # after the overlap-add instead.
    return pb.Pedalboard(chain)


def describe(spec: dict) -> str:
    """Short human summary of a resolved spec, used by the page and the WAV tool."""
    parts = [f"{spec.get('label', 'Off')}"]
    pitch = float(spec.get("pitch_semitones", 0.0))
    if abs(pitch) >= 0.01:
        parts.append(f"{pitch:+.1f} st")
    parts.append(f"mix {int(round(float(spec.get('wet', 1.0)) * 100))}%")
    if spec.get("tremolo"):
        parts.append(f"tremolo {spec['tremolo']['rate_hz']:.1f} Hz")
    return " · ".join(parts)
