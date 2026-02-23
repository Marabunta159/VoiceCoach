"""
audio_devices.py
────────────────
Erkennt und verwaltet alle Audio-Eingabe- und Ausgabegeräte.
Nutzt PyAudioWPatch für WASAPI-Loopback (Lautsprecher aufnehmen).

Gibt strukturierte Gerätelisten zurück, die direkt in Dropdowns
der UI verwendet werden können.
"""

import pyaudiowpatch as pyaudio


# ── Gerät-Typen ──────────────────────────────────────────────
TYPE_MIC      = "mic"       # echtes Eingabegerät (Mikrofon)
TYPE_LOOPBACK = "loopback"  # WASAPI-Loopback eines Ausgabegeräts


class AudioDevice:
    """Repräsentiert ein Audio-Gerät (Mikrofon oder Loopback)."""

    def __init__(self, index: int, name: str, device_type: str,
                 channels: int, sample_rate: float, raw: dict):
        self.index       = index
        self.name        = name
        self.device_type = device_type   # TYPE_MIC oder TYPE_LOOPBACK
        self.channels    = channels
        self.sample_rate = int(sample_rate)
        self.raw         = raw           # Original PyAudio dict

    def __repr__(self):
        icon = "🎙" if self.device_type == TYPE_MIC else "🔊"
        return f"{icon} {self.name}"

    @property
    def display_name(self) -> str:
        icon = "🎙 " if self.device_type == TYPE_MIC else "🔊 "
        return icon + self.name


def get_all_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    """
    Gibt (mic_devices, loopback_devices) zurück.
    Loopback-Geräte sind WASAPI-Loopback-Streams der Ausgabegeräte.
    """
    mic_devices      = []
    loopback_devices = []

    pa = pyaudio.PyAudio()
    try:
        # ── Mikrofone: alle Geräte mit maxInputChannels > 0
        #    die KEINE Loopback-Geräte sind
        for i in range(pa.get_device_count()):
            try:
                info = pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    if info.get("isLoopbackDevice", False):
                        # Loopback-Gerät → in loopback_devices
                        loopback_devices.append(AudioDevice(
                            index       = i,
                            name        = info["name"],
                            device_type = TYPE_LOOPBACK,
                            channels    = info["maxInputChannels"],
                            sample_rate = info["defaultSampleRate"],
                            raw         = info
                        ))
                    else:
                        mic_devices.append(AudioDevice(
                            index       = i,
                            name        = info["name"],
                            device_type = TYPE_MIC,
                            channels    = info["maxInputChannels"],
                            sample_rate = info["defaultSampleRate"],
                            raw         = info
                        ))
            except Exception:
                continue

        # ── Falls keine Loopback-Geräte gefunden: WASAPI-Standard-Lautsprecher
        #    und dessen Loopback-Gerät suchen
        if not loopback_devices:
            try:
                wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_out = pa.get_device_info_by_index(
                    wasapi_info["defaultOutputDevice"]
                )
                # Loopback-Gerät mit gleichem Namen finden
                for lb in pa.get_loopback_device_info_generator():
                    loopback_devices.append(AudioDevice(
                        index       = lb["index"],
                        name        = lb["name"],
                        device_type = TYPE_LOOPBACK,
                        channels    = lb["maxInputChannels"],
                        sample_rate = lb["defaultSampleRate"],
                        raw         = lb
                    ))
            except Exception as e:
                print(f"[AudioDevices] WASAPI Loopback nicht verfügbar: {e}")

    finally:
        pa.terminate()

    return mic_devices, loopback_devices


def get_default_mic() -> AudioDevice | None:
    """Gibt das Standard-Mikrofon zurück."""
    mics, _ = get_all_devices()
    if not mics:
        return None
    pa = pyaudio.PyAudio()
    try:
        default_idx = pa.get_default_input_device_info()["index"]
        for m in mics:
            if m.index == default_idx:
                return m
    except Exception:
        pass
    finally:
        pa.terminate()
    return mics[0] if mics else None


def get_default_loopback() -> AudioDevice | None:
    """Gibt das Standard-Loopback-Gerät zurück."""
    _, loopbacks = get_all_devices()
    return loopbacks[0] if loopbacks else None