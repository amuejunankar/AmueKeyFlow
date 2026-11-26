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

#: WDM-KS exposes paired-but-disconnected hardware as a bare role with empty
#: parentheses (``Headphones ()``); several devices share that useless name.
_PLACEHOLDER_ENDPOINT = re.compile(
    r"^(?:input|output|microphone|headphones?|speakers?|headset)\s*\(\s*\)$", re.I
)


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
    # PortAudio names contain stray CR/LF from the driver strings; collapse every
    # whitespace run so a device never renders with a replacement glyph.
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text or str(name or "").strip()


#: The driver that exposes a Bluetooth hands-free link to WDM-KS.
_BT_DRIVER = "bthhfenum"

#: ``role (hardware name)`` as MME, DirectSound and WASAPI spell it.
_ROLE_NAME = re.compile(r"^([^()]+?)\s*\((.*)\)\s*$")


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip(" -").casefold()


def is_bluetooth_descriptor(name: str) -> bool:
    """True for the WDM-KS name bthhfenum gives a Bluetooth hands-free link."""
    return _BT_DRIVER in str(name or "").lower()


def endpoint_identity(name: str) -> tuple[str, str]:
    """Split a device name into ``(role, hardware name)``.

    One Bluetooth endpoint reaches PortAudio under different names per host API:
    MME and WASAPI say ``Headset (realme Buds Air 5)`` while WDM-KS exposes the
    driver string ``Headset (@System32\\drivers\\bthhfenum.sys,#2;%1 Hands-Free%0
    ;(realme Buds Air 5))``.  Comparing raw names treats those as two devices, so
    the picker lists both and the saved WDM-KS stub can beat the working copy.
    """
    text = str(name or "").strip()
    if is_bluetooth_descriptor(text):
        role = text.split("(", 1)[0]
        match = _DRIVER_DEVICE.search(text)
        return _compact(role), _compact(match.group(1) if match else "")
    match = _ROLE_NAME.match(text)
    if match:
        return _compact(match.group(1)), _compact(match.group(2))
    return "", _compact(text)


def device_key(name: str) -> tuple[str, str]:
    """A dedupe key: one entry per endpoint, whichever host API named it."""
    role, inner = endpoint_identity(name)
    return ("bluetooth" if is_bluetooth_descriptor(name) else role, inner)


def same_device(first: str, second: str) -> bool:
    """True when two names describe the same endpoint on different host APIs."""
    role_a, inner_a = endpoint_identity(first)
    role_b, inner_b = endpoint_identity(second)
    if not inner_a or not inner_b:
        return _compact(first) == _compact(second)
    if inner_a != inner_b:
        return False
    # A bthhfenum role ("Hands-Free", "Input") never matches MME's "Headset",
    # so for Bluetooth endpoints only the hardware name can be compared.
    if is_bluetooth_descriptor(first) or is_bluetooth_descriptor(second):
        return True
    return role_a == role_b


def is_placeholder_endpoint(name: str) -> bool:
    """True for a driver placeholder rather than a real, named endpoint."""
    cleaned = friendly_name(name).strip()
    return not cleaned or bool(_PLACEHOLDER_ENDPOINT.match(cleaned))


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
    """The list of endpoints a person should choose from.

    Windows lists every endpoint once per host API, so one microphone can appear
    as WASAPI, DirectSound, MME and WDM-KS.  Keep the best-mapped copy of each
    name and drop non-microphone endpoints, but never hide a device that only
    exists on one host API: a Bluetooth headset or a Realtek speaker set is often
    WDM-KS only, and the Voice FX picker used to omit exactly those.
    """
    pool = [d for d in devices if (d.is_input if prefer_input else d.is_output)]
    filtered = [
        d for d in pool if not is_noise_name(d.name) and not is_placeholder_endpoint(d.name)
    ]
    if not filtered:
        filtered = [d for d in pool if not is_placeholder_endpoint(d.name)] or pool

    picked: list[AudioDevice] = []
    kept: list[tuple[str, bool]] = []
    kept_names: list[str] = []
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
        # The best-ranked copy of an endpoint was kept first, so the WDM-KS stub
        # of a Bluetooth headset never survives alongside its WASAPI/MME copy.
        if any(same_device(device.name, name) for name in kept_names):
            continue
        kept.append((text, truncated))
        kept_names.append(device.name)
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


def default_device_index(kind: str) -> int | None:
    """PortAudio's default endpoint index for ``kind`` (``input``/``output``).

    ``query_devices(kind=...)`` returns nothing (and raises) when Windows has no
    default for that direction, while the index still names a usable endpoint.
    """
    try:
        sd = sounddevice_module()
        pair = sd.default.device
        index = int(pair[0] if kind == "input" else pair[1])
    except Exception:
        return None
    return index if index >= 0 else None


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
        if not matches:
            # MME/WASAPI and WDM-KS name one Bluetooth endpoint differently.
            matches = [d for d in pool if same_device(d.name, name)]
        if matches:
            # Add every host-API copy of that endpoint. The pool is ordered best
            # API first, so the working WASAPI/MME stream is tried before the
            # WDM-KS stub that reports ERROR_DEVICE_NOT_CONNECTED.
            targets = [d.name for d in matches]
            matches = [
                d for d in pool if d.name in targets or any(same_device(d.name, name) for name in targets)
            ]
            return matches[:limit]
    index = default_device_index("input" if prefer_input else "output")
    if index is not None:
        matches = [d for d in pool if d.index == index]
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
