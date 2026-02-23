"""
transcriber.py
──────────────
VAD-basiertes Chunking statt fester Zeitfenster.

Funktionsprinzip:
  - Audio kommt in 30ms-Frames rein
  - Einfacher Energie-VAD erkennt Sprache/Stille pro Frame
  - Sobald Sprache endet (Pause > SILENCE_MS) → sofort an Whisper
  - Minimale Chunk-Länge: MIN_SPEECH_MS (verhindert "aha"-Verlust)
  - Maximale Chunk-Länge: MAX_CHUNK_SEC (Sicherheitsnetz)

Ergebnis: "aha" wird in ~400ms erkannt statt nach 3 Sekunden.
"""

import threading
import time
import queue
import numpy as np
import pyaudiowpatch as pyaudio
from faster_whisper import WhisperModel

from config import (
    WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE,
    CHUNK_SECONDS, SAMPLE_RATE,
    MAX_TRANSCRIPT_LINES, WHISPER_VAD_FILTER
)
from audio_devices import AudioDevice

# ── VAD-Parameter ────────────────────────────────────────────
FRAME_MS       = 30       # Frames die VAD analysiert (ms)
FRAME_SAMPLES  = int(SAMPLE_RATE * FRAME_MS / 1000)   # 480 Samples

SILENCE_MS     = 400      # Pause nach der ein Chunk gesendet wird
SILENCE_FRAMES = int(SILENCE_MS / FRAME_MS)           # 13 Frames

MIN_SPEECH_MS  = 200      # Mindest-Sprachanteil damit gesendet wird
MIN_SPEECH_FR  = int(MIN_SPEECH_MS / FRAME_MS)        # 6 Frames

MAX_CHUNK_SEC  = 6.0      # Sicherheitsnetz: max Chunk-Länge
MAX_CHUNK_FR   = int(MAX_CHUNK_SEC * 1000 / FRAME_MS)

VAD_RMS_THRESH = 0.008    # RMS-Schwelle: darüber = Sprache
                           # (0.008 ≈ flüstern; 0.002 = Silence-Gate)

PREROLL_MS     = 600      # Frames VOR Sprachbeginn die mit eingeschlossen werden
PREROLL_FR     = int(PREROLL_MS / FRAME_MS)           # 10 Frames → erstes Wort vollständig

CHUNK_FRAMES   = int(SAMPLE_RATE * CHUNK_SECONDS)


class VADAccumulator:
    """
    Sammelt Audio-Frames und sendet sobald eine Sprechpause erkannt wird.

    Pre-Roll: Die letzten PREROLL_FR Stille-Frames werden VOR dem ersten
    Sprach-Frame mit eingeschlossen → erstes Wort wird nicht abgeschnitten.
    """

    def __init__(self, on_chunk, rms_threshold=VAD_RMS_THRESH):
        self._on_chunk     = on_chunk
        self._rms_thresh   = rms_threshold
        self._frames       = []       # aktiver Sprach-Chunk
        self._preroll      = []       # Ringpuffer: letzte N Stille-Frames
        self._speech_count = 0
        self._silence_run  = 0
        self._total_frames = 0
        self._in_speech    = False    # sind wir gerade in einem Sprach-Segment?

    def push(self, audio: np.ndarray):
        for start in range(0, len(audio), FRAME_SAMPLES):
            frame = audio[start : start + FRAME_SAMPLES]
            if len(frame) < FRAME_SAMPLES // 2:
                continue
            self._process_frame(frame)

    def _process_frame(self, frame: np.ndarray):
        rms       = float(np.sqrt(np.mean(frame ** 2)))
        is_speech = rms >= self._rms_thresh

        if is_speech:
            if not self._in_speech:
                # Sprache beginnt: Pre-Roll-Buffer vorne anhängen
                self._frames.extend(self._preroll)
                self._preroll  = []
                self._in_speech = True
            self._frames.append(frame)
            self._speech_count += 1
            self._silence_run   = 0
            self._total_frames += 1
        else:
            if self._in_speech:
                # Stille während Sprach-Segment: zum Chunk hinzufügen
                self._frames.append(frame)
                self._silence_run  += 1
                self._total_frames += 1
                # Senden wenn Pause lang genug
                if self._silence_run >= SILENCE_FRAMES:
                    if self._speech_count >= MIN_SPEECH_FR:
                        self._flush()
                    else:
                        self._reset()
                # Sicherheitsnetz
                elif self._total_frames >= MAX_CHUNK_FR:
                    if self._speech_count >= MIN_SPEECH_FR:
                        self._flush()
                    else:
                        self._reset()
            else:
                # Stille vor Sprache: in Pre-Roll-Ringpuffer
                self._preroll.append(frame)
                if len(self._preroll) > PREROLL_FR:
                    self._preroll.pop(0)   # ältesten Frame entfernen

    def _flush(self):
        if self._frames:
            audio = np.concatenate(self._frames)
            try:
                self._on_chunk(audio)
            except Exception:
                pass
        self._reset()

    def _reset(self):
        self._frames       = []
        self._preroll      = []   # Pre-Roll auch zurücksetzen
        self._speech_count = 0
        self._silence_run  = 0
        self._total_frames = 0
        self._in_speech    = False

    def set_threshold(self, thresh: float):
        self._rms_thresh = thresh


class Transcriber:

    def __init__(self):
        self._running     = False
        self._model       = None
        self._callbacks   = []
        self._buffer      = []
        self._buffer_lock = threading.Lock()

        self._mic_q  = queue.Queue(maxsize=20)
        self._loop_q = queue.Queue(maxsize=20)

        self._mic_device    : AudioDevice | None = None
        self._loop_device   : AudioDevice | None = None
        self._pending_mic   : AudioDevice | None = None
        self._pending_loop  : AudioDevice | None = None
        self._mic_change    = threading.Event()
        self._loop_change   = threading.Event()

        self._mic_thread   = None
        self._loop_thread  = None
        self._mixer_thread = None

        self.speaker_monitor = None

    # ── Public API ──────────────────────────────────────────

    def start(self):
        print(f"[Transcriber] Lade faster-whisper … (device={WHISPER_DEVICE}, compute={WHISPER_COMPUTE})")
        self._model   = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE
        )
        self._running = True
        self._mic_thread   = threading.Thread(target=self._mic_loop,   daemon=True)
        self._loop_thread  = threading.Thread(target=self._loop_loop,  daemon=True)
        self._mixer_thread = threading.Thread(target=self._mixer_loop, daemon=True)
        self._mic_thread.start()
        self._loop_thread.start()
        self._mixer_thread.start()
        print(f"[Transcriber] Bereit – VAD-Modus, Pause={SILENCE_MS}ms, Min={MIN_SPEECH_MS}ms")

    def stop(self):
        self._running = False
        self._mic_change.set()
        self._loop_change.set()

    def set_mic_device(self, device: AudioDevice | None):
        self._pending_mic = device
        self._mic_change.set()

    def set_loopback_device(self, device: AudioDevice | None):
        self._pending_loop = device
        self._loop_change.set()

    def register_callback(self, fn):
        self._callbacks.append(fn)

    def get_last_n_lines(self, n: int = 20) -> str:
        with self._buffer_lock:
            return "\n".join(self._buffer[-n:])

    def clear_buffer(self):
        with self._buffer_lock:
            self._buffer.clear()

    # ── Mic-Stream-Loop ──────────────────────────────────────

    def _mic_loop(self):
        pa     = None
        stream = None

        def _close():
            nonlocal pa, stream
            if stream:
                try: stream.stop_stream()
                except Exception: pass
                try: stream.close()
                except Exception: pass
                stream = None
            if pa:
                try: pa.terminate()
                except Exception: pass
                pa = None

        while self._running:
            if self._mic_change.is_set():
                self._mic_change.clear()
                _close()
                self._mic_device = self._pending_mic

                if self._mic_device is not None:
                    try:
                        pa  = pyaudio.PyAudio()
                        ch  = min(self._mic_device.channels, 2)
                        sr  = SAMPLE_RATE

                        # VAD-Akkumulator für Mic
                        # Mic-RMS ist in float32/32768 normalisiert → gleicher Schwellenwert
                        vad = VADAccumulator(
                            on_chunk=lambda a: self._mic_q.put_nowait(a)
                            if not self._mic_q.full() else None,
                            rms_threshold=VAD_RMS_THRESH
                        )

                        def cb(in_data, frame_count, time_info, status,
                               _ch=ch, _vad=vad):
                            audio = (np.frombuffer(in_data, dtype=np.int16)
                                     .astype(np.float32) / 32768.0)
                            if _ch > 1:
                                audio = audio.reshape(-1, _ch).mean(axis=1)
                            _vad.push(audio)
                            return (None, pyaudio.paContinue)

                        stream = pa.open(
                            format=pyaudio.paInt16,
                            channels=ch,
                            rate=sr,
                            input=True,
                            input_device_index=self._mic_device.index,
                            frames_per_buffer=FRAME_SAMPLES,
                            stream_callback=cb
                        )
                        print(f"[Transcriber] 🎙 Mic: {self._mic_device.name}")
                    except Exception as e:
                        print(f"[Transcriber] Mic-Fehler: {e}")
                        _close()

            if not self._running:
                break
            time.sleep(0.05)

        _close()

    # ── Loopback-Stream-Loop ─────────────────────────────────

    def _loop_loop(self):
        pa     = None
        stream = None

        def _close():
            nonlocal pa, stream
            if stream:
                try: stream.stop_stream()
                except Exception: pass
                try: stream.close()
                except Exception: pass
                stream = None
            if pa:
                try: pa.terminate()
                except Exception: pass
                pa = None

        while self._running:
            if self._loop_change.is_set():
                self._loop_change.clear()
                _close()
                self._loop_device = self._pending_loop

                if self._loop_device is not None:
                    try:
                        pa  = pyaudio.PyAudio()
                        sr  = self._loop_device.sample_rate
                        ch  = max(1, self._loop_device.channels)

                        small_buf = int(sr * FRAME_MS / 1000)  # 30ms in Geräte-Samples

                        # Loopback-Audio ist leiser → niedrigerer Schwellenwert
                        vad = VADAccumulator(
                            on_chunk=lambda a: self._loop_q.put_nowait(a)
                            if not self._loop_q.full() else None,
                            rms_threshold=VAD_RMS_THRESH * 0.3   # Loopback typisch leiser
                        )

                        def cb(in_data, frame_count, time_info, status,
                               _ch=ch, _sr=sr, _vad=vad):
                            audio = (np.frombuffer(in_data, dtype=np.int16)
                                     .astype(np.float32) / 32768.0)
                            if _ch > 1:
                                audio = audio.reshape(-1, _ch).mean(axis=1)
                            if _sr != SAMPLE_RATE:
                                ratio = SAMPLE_RATE / _sr
                                n_out = int(len(audio) * ratio)
                                audio = np.interp(
                                    np.linspace(0, len(audio), n_out),
                                    np.arange(len(audio)), audio
                                )
                            # VU-Meter sofort füttern
                            if self.speaker_monitor is not None:
                                self.speaker_monitor.push_chunk(audio, SAMPLE_RATE)
                            # VAD-Akkumulator
                            _vad.push(audio)
                            return (None, pyaudio.paContinue)

                        stream = pa.open(
                            format=pyaudio.paInt16,
                            channels=ch,
                            rate=sr,
                            input=True,
                            input_device_index=self._loop_device.index,
                            frames_per_buffer=small_buf,
                            stream_callback=cb
                        )
                        print(f"[Transcriber] 🔊 Loopback: {self._loop_device.name}")
                    except Exception as e:
                        print(f"[Transcriber] Loopback-Fehler: {e}")
                        _close()

            if not self._running:
                break
            time.sleep(0.05)

        _close()

    # ── Mixer + Whisper ──────────────────────────────────────

    def _mixer_loop(self):
        while self._running:
            mic_chunk  = None
            loop_chunk = None

            try:
                mic_chunk = self._mic_q.get(timeout=0.05)
            except queue.Empty:
                pass

            try:
                loop_chunk = self._loop_q.get(timeout=0.05)
            except queue.Empty:
                pass

            if mic_chunk is None and loop_chunk is None:
                continue

            if mic_chunk is not None and loop_chunk is not None:
                min_len = min(len(mic_chunk), len(loop_chunk))
                mixed   = (mic_chunk[:min_len] + loop_chunk[:min_len]) * 0.5
                if self._has_speech(mixed):
                    self._transcribe(mixed, source="mixed")
            else:
                if mic_chunk is not None and self._has_speech(mic_chunk):
                    self._transcribe(mic_chunk, source="mic")
                if loop_chunk is not None and self._has_speech(loop_chunk):
                    self._transcribe(loop_chunk, source="loopback")

    # Schwellenwerte für finalen Stille-Check
    _SPEECH_RMS_MIN  = 0.002
    _SPEECH_PEAK_MIN = 0.005

    def _has_speech(self, audio: np.ndarray) -> bool:
        rms  = float(np.sqrt(np.mean(audio ** 2)))
        peak = float(np.max(np.abs(audio)))
        return rms >= self._SPEECH_RMS_MIN and peak >= self._SPEECH_PEAK_MIN

    def _transcribe(self, audio: np.ndarray, source: str = "mic"):
        try:
            segments, _ = self._model.transcribe(
                audio.astype(np.float32),
                language="de",
                beam_size=5,
                vad_filter=False,        # Wir machen VAD selbst via VADAccumulator
                condition_on_previous_text=False,
                without_timestamps=True
            )
            parts = [s.text.strip() for s in segments if s.text.strip()]
            text  = " ".join(parts)
            if text:
                with self._buffer_lock:
                    self._buffer.append(text)
                    if len(self._buffer) > MAX_TRANSCRIPT_LINES:
                        self._buffer = self._buffer[-MAX_TRANSCRIPT_LINES:]
                for fn in self._callbacks:
                    try:
                        fn(text, False, source)
                    except Exception as e:
                        print(f"[Transcriber] Callback-Fehler: {e}")
        except Exception as e:
            print(f"[Transcriber] Whisper-Fehler: {e}")