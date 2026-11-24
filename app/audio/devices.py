"""Audio device discovery and the virtual-cable check.

Nothing here imports ``sounddevice`` at module level: PortAudio can fail to load
on an unusual installation, and that must never stop the rest of the app from
starting.  Call :func:`sounddevice_module` first and handle the exception.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Everything internal runs at 48 kHz; nearly every Windows endpoint supports it.
SAMPLE_RATE = 48000

BLOCK_FRAMES = 256

#: Any endpoint belonging to a virtual cable stack (both directions).
VIRTUAL_CABLE_HINTS = (
    "cable input",
    "cable output",
    "voicemeeter",
    "virtual audio cable",
)

#: Playback endpoints that are *virtual microphones*: audio played into them is
#: what other applications see as a microphone.
VIRTUAL_CABLE_PLAYBACK_HINTS = (
    "cable input",
    "cable-a input",
    "cable-b input",
    "voicemeeter input",
    "voicemeeter aux input",
    "voicemeeter vaio",
    "virtual audio cable",
    "line 1 (virtual audio cable)",
)

MIC_PRIVACY_MESSAGE = (
    "Windows is blocking microphone access. Open Settings → Privacy & security → "
    "Microphone, turn on “Microphone access” and “Let desktop apps access your "
    "microphone”, then press Start again."
)


class AudioUnavailable(RuntimeError):
    """Raised when the audio backend cannot be loaded at all."""


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    host_api: str
    max_inputs: int
    max_outputs: int
    default_rate: float

    @property
    def is_input(self) -> bool:
        return self.max_inputs > 0

    @property
    def is_output(self) -> bool:
        return self.max_outputs > 0

    @property
    def label(self) -> str:
        return friendly_name(self.name)


def sounddevice_module():
    try:
        import sounddevice as sd
    except Exception as exc:  # pragma: no cover - depends on the machine
        raise AudioUnavailable(f"Audio backend unavailable: {exc}") from exc
    return sd


#: Endpoints that are not microphones a person would pick by hand.
NOISE_NAMES = (
    "stereo mix",
    "what u hear",
    "wave out",
    "loopback",
    "line in",
    "cd audio",
    "aux",
    "input",
    "output",
)

#: Windows UI aliases for "the default device", not separate endpoints.
GENERIC_NAMES = (
    "microsoft sound mapper",
    "primary sound driver",
    "primary sound capture driver",
)

_DRIVER_SUFFIX = re.compile(r"\s*\(@System32.*$", re.I)
_DRIVER_DEVICE = re.compile(r";\s*\(([^()]+)\)\s*\)\s*$")
_PLACEHOLDER = re.compile(r"%\d")


def friendly_name(name: str) -> str:
    """A device name worth showing in a dropdown.

    WDM-KS exposes driver-internal strings such as
    ``Headset (@System32\\drivers\\bthhfenum.sys,#2;%1 Hands-Free%0 ;(boAt Rugbyy))``.
    Those are unreadable in a list, so reduce them to ``boAt Rugbyy — headset``.
    """
    text = str(name or "").strip()
    if "@system32" in text.lower():
        role = text.split("(", 1)[0].strip()
        match = _DRIVER_DEVICE.search(text)
        inner = match.group(1).strip() if match else ""
        if inner:
            text = f"{inner} — {role.lower()}" if role else inner
    text = _PLACEHOLDER.sub("", _DRIVER_SUFFIX.sub("", text))
    text = re.sub(r"\s{2,}", " ", text).strip(" -")
    return text or str(name or "").strip()


def is_noise_name(name: str) -> bool:
    """True for endpoints that only clutter the microphone picker."""
    cleaned = friendly_name(name).strip().casefold()
    if not cleaned:
        return True
    # "Stereo Mix (Realtek HD Audio)" and "Line In (…)" keep a parenthetical tail.
    if cleaned in NOISE_NAMES or cleaned.startswith(tuple(f"{word} (" for word in NOISE_NAMES)):
        return True
    return cleaned.startswith(GENERIC_NAMES)


def pick_devices(devices: list[AudioDevice], prefer_input: bool) -> list[AudioDevice]:
    """The short list a user should choose from.

    Windows lists every endpoint once per host API, so one microphone can appear
    as WASAPI, DirectSound, MME and WDM-KS.  Keep the best-mapped copy of each
    name, drop non-microphone endpoints, and skip WDM-KS entirely while a shared
    API is available (WDM-KS also exposes paired-but-offline hardware).
    """
    pool = [d for d in devices if (d.is_input if prefer_input else d.is_output)]
    filtered = [d for d in pool if not is_noise_name(d.name)]
    if not filtered:
        filtered = pool
    # WDM-KS also lists paired-but-offline hardware by driver-internal name; a
    # connected device always has a normal endpoint too, so those are duplicates.
    plain = [d for d in filtered if "@system32" not in d.name.lower()]
    if plain:
        filtered = plain
    if any(api_rank(d.host_api) <= 1 for d in filtered):
        filtered = [d for d in filtered if api_rank(d.host_api) <= 1]

    picked: list[AudioDevice] = []
    kept: list[tuple[str, bool]] = []
    for device in sorted(filtered, key=lambda d: (api_rank(d.host_api), name_score(d.name), d.index)):
        text = friendly_name(device.name).casefold()
        # MME truncates names at 31 characters, so compare those as prefixes.
        truncated = text.count("(") > text.count(")")
        if any(
            text == other
            or (truncated and other.startswith(text))
            or (other_truncated and text.startswith(other))
            for other, other_truncated in kept
        ):
            continue
        kept.append((text, truncated))
        picked.append(device)
    return picked


def is_virtual_cable(name: str) -> bool:
    text = str(name or "").strip().lower()
    return any(hint in text for hint in VIRTUAL_CABLE_HINTS)


def is_virtual_cable_playback(name: str) -> bool:
    text = str(name or "").strip().lower()
    return any(hint in text for hint in VIRTUAL_CABLE_PLAYBACK_HINTS)


def default_device_name(kind: str) -> str:
    """Name of the Windows default input/output, or an empty string."""
    try:
        sd = sounddevice_module()
        info = sd.query_devices(kind=kind)
        return str(info.get("name", ""))
    except Exception:
        return ""


_CACHE: list[AudioDevice] | None = None


def refresh() -> None:
    global _CACHE
    _CACHE = None


def list_devices(use_cache: bool = True) -> list[AudioDevice]:
    global _CACHE
    if use_cache and _CACHE is not None:
        return _CACHE
    sd = sounddevice_module()
    host_apis = sd.query_hostapis()
    found: list[AudioDevice] = []
    for index, info in enumerate(sd.query_devices()):
        channels_in = int(info.get("max_input_channels", 0))
        channels_out = int(info.get("max_output_channels", 0))
        if channels_in <= 0 and channels_out <= 0:
            continue
        api_index = int(info.get("hostapi", -1))
        api_name = str(host_apis[api_index]["name"]) if 0 <= api_index < len(host_apis) else ""
        found.append(
            AudioDevice(
                index=index,
                name=str(info.get("name", f"Device {index}")),
                host_api=api_name,
                max_inputs=channels_in,
                max_outputs=channels_out,
                default_rate=float(info.get("default_samplerate", SAMPLE_RATE) or SAMPLE_RATE),
            )
        )
    _CACHE = found
    return found


def input_devices(use_cache: bool = True) -> list[AudioDevice]:
    return [d for d in list_devices(use_cache) if d.is_input]


def output_devices(use_cache: bool = True) -> list[AudioDevice]:
    return [d for d in list_devices(use_cache) if d.is_output]


def api_rank(host_api: str) -> int:
    """Prefer shared, reliable host APIs over WDM-KS (often exclusive/broken)."""
    text = str(host_api or "").lower()
    if "wasapi" in text:
        return 0
    if "directsound" in text or "mme" in text:
        return 1
    if "wdm-ks" in text:
        return 3
    return 2


def name_score(name: str) -> int:
    """How likely an unnamed endpoint is the microphone a user means."""
    text = str(name or "").strip().lower()
    if not text or text in {"input", "input ()", "output", "output ()"}:
        return 4
    if any(bad in text for bad in ("stereo mix", "wave out", "what u hear", "line in", "loopback")):
        return 3
    if "microphone" in text or "mic" in text:
        return 0
    if "headset" in text or "headphone" in text:
        return 1
    return 2


def device_candidates(
    devices: list[AudioDevice], name: str, prefer_input: bool, limit: int = 6
) -> list[AudioDevice]:
    """Endpoints matching ``name``, best host API first.

    Every Windows device name exists once per host API, so the same microphone may
    appear as WASAPI, DirectSound, MME and WDM-KS.  Returning all of them lets the
    engine fall back when one API cannot open the device.
    """
    wanted = str(name or "").strip().lower()
    pool = sorted(
        (d for d in devices if (d.is_input if prefer_input else d.is_output)),
        key=lambda d: (api_rank(d.host_api), name_score(d.name), d.index),
    )
    if not pool:
        return []
    if wanted:
        matches = [d for d in pool if d.name.strip().lower() == wanted]
        if not matches:
            matches = [d for d in pool if wanted in d.name.strip().lower()]
        if matches:
            return matches[:limit]
    default_name = default_device_name("input" if prefer_input else "output").strip().lower()
    if default_name:
        matches = [d for d in pool if d.name.strip().lower() == default_name]
        if matches:
            return matches[:limit]
    return pool[:limit]


def find_device(devices: list[AudioDevice], name: str, prefer_input: bool) -> AudioDevice | None:
    """Resolve a saved device name to the best live endpoint."""
    candidates = device_candidates(devices, name, prefer_input, limit=1)
    return candidates[0] if candidates else None


def default_input(devices: list[AudioDevice] | None = None) -> AudioDevice | None:
    return find_device(devices if devices is not None else list_devices(), "", prefer_input=True)


def default_output(devices: list[AudioDevice] | None = None) -> AudioDevice | None:
    return find_device(devices if devices is not None else list_devices(), "", prefer_input=False)


def virtual_cable_output(devices: list[AudioDevice] | None = None) -> AudioDevice | None:
    """The playback endpoint of an installed virtual cable, if any."""
    pool = [
        d
        for d in sorted(
            (devices if devices is not None else list_devices()),
            key=lambda d: (api_rank(d.host_api), d.index),
        )
        if d.is_output
    ]
    for device in pool:
        if is_virtual_cable_playback(device.name):
            return device
    return None


def cable_status(devices: list[AudioDevice] | None = None) -> tuple[bool, str]:
    cable = virtual_cable_output(devices)
    if cable is None:
        return False, (
            "No virtual microphone installed. Amue KeyFlow can still process your "
            "microphone and record it, but Discord, Zoom and games only see a "
            "microphone through a virtual cable such as VB-Cable."
        )
    return True, (
        f"Virtual microphone found: {cable.name}. In Discord, Zoom or your game, "
        "choose the matching “CABLE Output” device as the microphone."
    )


def friendly_error(exc: BaseException) -> str:
    """Translate PortAudio/OS errors into something a user can act on."""
    text = f"{exc}".strip()
    lowered = text.lower()
    if (
        "access is denied" in lowered
        or "0x80070005" in lowered
        or "permission" in lowered
        or "e_accessdenied" in lowered
    ):
        return MIC_PRIVACY_MESSAGE
    if "device unavailable" in lowered or "unanticipated host error" in lowered:
        return (
            "The audio device could not be opened. Another application may be using "
            "it exclusively, or it may have been unplugged: " + text
        )
    if "invalid number of channels" in lowered or "invalid sample rate" in lowered:
        return "That device does not accept the requested format. Pick another device: " + text
    if "no default" in lowered or "device index" in lowered:
        return "No microphone was found. Connect one and press Refresh."
    return text or "The audio stream could not be started."
