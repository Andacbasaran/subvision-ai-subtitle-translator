"""
SubVision AI — Optional Live Audio Subtitle Engine (WASAPI Loopback / Mic + faster-whisper).

Design goals:
1. Optional & zero-bloat: base SubVision AI works 100% without `faster-whisper` or
   audio capture libraries installed. If installed (`pip install faster-whisper sounddevice`
   or `pyaudiowpatch`), users can switch Input Source to Live Audio for unsubtitled
   Twitch streams, YouTube videos, podcasts, or in-game voice lines.
2. Reuses `ctranslate2` (already bundled with SubVision AI) via `faster-whisper` INT8 on CPU.
3. Pure-Python RMS Voice Activity Detection (`SpeechSegmenter`) splits continuous 16 kHz
   mono PCM streams into clean utterance chunks for low-latency EN -> TR translation.
"""

import importlib.util
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class AudioCapabilities:
    has_faster_whisper: bool
    has_sounddevice: bool
    has_pyaudiowpatch: bool

    @property
    def is_ready(self) -> bool:
        return self.has_faster_whisper and (self.has_sounddevice or self.has_pyaudiowpatch)

    @property
    def capture_backend(self) -> str:
        if self.has_pyaudiowpatch:
            return "pyaudiowpatch_wasapi"
        if self.has_sounddevice:
            return "sounddevice"
        return "none"


def detect_audio_capabilities() -> AudioCapabilities:
    """Checks whether optional live-audio dependencies are available in the environment."""
    return AudioCapabilities(
        has_faster_whisper=importlib.util.find_spec("faster_whisper") is not None,
        has_sounddevice=importlib.util.find_spec("sounddevice") is not None,
        has_pyaudiowpatch=importlib.util.find_spec("pyaudiowpatch") is not None,
    )


class SpeechSegmenter:
    """
    Lightweight RMS energy-based Voice Activity Detector (VAD) & utterance chunker.
    Accepts float32 mono PCM frames (16 kHz) and emits complete speech segments
    once trailing silence or maximum chunk duration is reached.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        energy_threshold: float = 0.015,
        silence_duration_sec: float = 0.65,
        min_speech_sec: float = 0.45,
        max_speech_sec: float = 6.0,
    ):
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self.silence_samples = int(sample_rate * silence_duration_sec)
        self.min_speech_samples = int(sample_rate * min_speech_sec)
        self.max_speech_samples = int(sample_rate * max_speech_sec)

        self._buffer: List[np.ndarray] = []
        self._buffered_samples = 0
        self._silent_samples = 0
        self._in_speech = False

    def reset(self) -> None:
        self._buffer.clear()
        self._buffered_samples = 0
        self._silent_samples = 0
        self._in_speech = False

    def push_frame(self, pcm_float32: np.ndarray) -> Optional[np.ndarray]:
        """
        Pushes a 1D float32 audio chunk in [-1.0, 1.0].
        Returns a concatenated float32 utterance array when a segment finishes, else None.
        """
        if pcm_float32.size == 0:
            return None
        frame = np.asarray(pcm_float32, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(frame * frame)))

        if rms >= self.energy_threshold:
            self._in_speech = True
            self._silent_samples = 0
            self._buffer.append(frame)
            self._buffered_samples += frame.size
        elif self._in_speech:
            self._buffer.append(frame)
            self._buffered_samples += frame.size
            self._silent_samples += frame.size

        if not self._in_speech:
            return None

        reached_max = self._buffered_samples >= self.max_speech_samples
        reached_silence = self._silent_samples >= self.silence_samples

        if reached_max or reached_silence:
            segment = np.concatenate(self._buffer)
            total_samples = self._buffered_samples
            self.reset()
            if total_samples >= self.min_speech_samples:
                return segment
        return None


class LiveAudioTranscriber:
    """
    Wraps `faster-whisper` (CTranslate2 INT8 CPU) for English speech-to-text.
    Lazily imports `faster_whisper` so the base app never requires it.
    """

    def __init__(
        self,
        model_size: str = "tiny.en",
        cpu_threads: int = 4,
        compute_type: str = "int8",
    ):
        self.model_size = model_size
        self.cpu_threads = max(1, int(cpu_threads))
        self.compute_type = compute_type
        self._model = None

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Run: pip install faster-whisper sounddevice"
            ) from exc

        self._model = WhisperModel(
            self.model_size,
            device="cpu",
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
        )

    def transcribe(self, audio_float32: np.ndarray) -> Tuple[str, float]:
        if self._model is None:
            self.load()
        t0 = time.perf_counter()
        segments, _info = self._model.transcribe(
            audio_float32,
            language="en",
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return text, elapsed_ms


try:
    from PyQt6.QtCore import QThread, pyqtSignal

    class AudioCaptureTranslateWorker(QThread):
        """
        Captures live audio (WASAPI loopback via pyaudiowpatch or default input via sounddevice),
        transcribes English speech via faster-whisper, and translates to Turkish via the
        shared translator (CTranslate2 INT8 or ContextAwareTranslator).
        """

        subtitle_updated = pyqtSignal(str, str, float, float, bool, int)
        subtitle_cleared = pyqtSignal()
        status_message = pyqtSignal(str)
        error_occurred = pyqtSignal(str)

        def __init__(
            self,
            translator,
            model_size: str = "tiny.en",
            cpu_threads: int = 4,
            parent=None,
        ):
            super().__init__(parent)
            self.translator = translator
            self.transcriber = LiveAudioTranscriber(
                model_size=model_size,
                cpu_threads=cpu_threads,
            )
            self.segmenter = SpeechSegmenter()
            self._running = True

        def stop(self) -> None:
            self._running = False

        def _process_segment(self, audio_chunk: np.ndarray) -> None:
            en_text, stt_ms = self.transcriber.transcribe(audio_chunk)
            if not en_text:
                return
            tr_text, nmt_ms, from_cache = self.translator.translate_with_metrics(en_text)
            if tr_text and self._running:
                self.subtitle_updated.emit(en_text, tr_text, stt_ms, nmt_ms, from_cache, 0)

        def run(self) -> None:
            caps = detect_audio_capabilities()
            if not caps.is_ready:
                self.error_occurred.emit(
                    "Canlı ses modu için opsiyonel paketler gerekli: "
                    "pip install faster-whisper sounddevice"
                )
                return

            try:
                self.status_message.emit(f"Whisper ({self.transcriber.model_size}) yükleniyor...")
                self.transcriber.load()
                self.status_message.emit("Canlı ses dinleniyor...")
            except Exception as exc:
                self.error_occurred.emit(f"Whisper yükleme hatası: {exc}")
                return

            if caps.has_sounddevice:
                self._run_sounddevice()
            elif caps.has_pyaudiowpatch:
                self._run_pyaudiowpatch()

        def _run_sounddevice(self) -> None:
            import queue
            import sounddevice as sd

            audio_q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=64)

            def _cb(indata, frames, time_info, status):
                if self._running:
                    mono = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
                    try:
                        audio_q.put_nowait(mono)
                    except queue.Full:
                        pass

            try:
                with sd.InputStream(
                    samplerate=16000,
                    channels=1,
                    dtype="float32",
                    blocksize=1600,
                    callback=_cb,
                ):
                    while self._running:
                        try:
                            frame = audio_q.get(timeout=0.2)
                        except queue.Empty:
                            continue
                        seg = self.segmenter.push_frame(frame)
                        if seg is not None and self._running:
                            self._process_segment(seg)
            except Exception as exc:
                self.error_occurred.emit(f"Ses yakalama hatası: {exc}")

        def _run_pyaudiowpatch(self) -> None:
            import pyaudiowpatch as pyaudio

            pa = pyaudio.PyAudio()
            stream = None
            try:
                wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_speakers = pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
                if not default_speakers.get("isLoopbackDevice"):
                    for loopback in pa.get_loopback_device_info_generator():
                        if default_speakers["name"] in loopback["name"]:
                            default_speakers = loopback
                            break
                src_rate = int(default_speakers["defaultSampleRate"])
                channels = max(1, int(default_speakers["maxInputChannels"]))
                stream = pa.open(
                    format=pyaudio.paFloat32,
                    channels=channels,
                    rate=src_rate,
                    frames_per_buffer=int(src_rate * 0.1),
                    input=True,
                    input_device_index=default_speakers["index"],
                )
                while self._running:
                    raw = stream.read(int(src_rate * 0.1), exception_on_overflow=False)
                    arr = np.frombuffer(raw, dtype=np.float32)
                    if channels > 1:
                        arr = arr.reshape(-1, channels).mean(axis=1)
                    if src_rate != 16000 and arr.size > 0:
                        target_len = max(1, int(arr.size * 16000 / src_rate))
                        x_old = np.linspace(0.0, 1.0, arr.size, endpoint=False)
                        x_new = np.linspace(0.0, 1.0, target_len, endpoint=False)
                        arr = np.interp(x_new, x_old, arr).astype(np.float32)
                    seg = self.segmenter.push_frame(arr)
                    if seg is not None and self._running:
                        self._process_segment(seg)
            except Exception as exc:
                self.error_occurred.emit(f"WASAPI loopback hatası: {exc}")
            finally:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
                pa.terminate()

except Exception:
    AudioCaptureTranslateWorker = None  # type: ignore[assignment,misc]
