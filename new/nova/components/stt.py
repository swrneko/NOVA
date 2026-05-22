"""
Speech-to-Text module.
Keeps the microphone stream open at all times.
VAD + transcription run in a background worker thread.
"""

import asyncio
import logging
import threading
import queue
from collections import deque

import numpy as np
import sounddevice as sd
from silero_vad import load_silero_vad
from faster_whisper import WhisperModel

from nova.config import (
    STT_MODEL_PATH,
    STT_LANGUAGE,
    STT_VAD_THRESHOLD,
    STT_SILENCE_DURATION,
    STT_PREROLL,
    AUDIO_SAMPLE_RATE,
    AUDIO_CHANNELS,
    AUDIO_CHUNK_SAMPLES,
)

logger = logging.getLogger(__name__)


class STT:
    """
    Always-open microphone with VAD-based speech detection.
    """

    def __init__(self):
        logger.info("Loading Whisper model: %s", STT_MODEL_PATH)
        self._whisper = WhisperModel(
            STT_MODEL_PATH,
            device="cuda",
            compute_type="float16",
        )

        logger.info("Loading Silero VAD")
        self._vad_model = load_silero_vad()
        self._vad_threshold = STT_VAD_THRESHOLD

        samples_per_chunk = AUDIO_CHUNK_SAMPLES / AUDIO_SAMPLE_RATE
        self._silence_chunks = int(STT_SILENCE_DURATION / samples_per_chunk)
        self._preroll_chunks = int(STT_PREROLL / samples_per_chunk)

        self._initial_prompt = "привет нанасаки ай нова помощник arch linux"

        # Audio buffer (only accessed from audio callback thread — safe)
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()

        # Result signaling
        self._result_text: str = ""
        self._result_ready = threading.Event()
        self._abort_event = threading.Event()
        self._generation = 0  # incremented each listen_async call

        # Speech detection state (accessed only from worker thread)
        self._speech_buffer: list[np.ndarray] = []
        self._preroll_buffer: deque = deque(maxlen=self._preroll_chunks * AUDIO_CHUNK_SAMPLES)
        self._in_speech = False
        self._consecutive_silence = 0

        # Start VAD + transcription worker
        self._vad_thread = threading.Thread(target=self._vad_worker, daemon=True)
        self._vad_thread.start()

        # Always-open audio input stream
        self._stream = sd.InputStream(
            samplerate=AUDIO_SAMPLE_RATE,
            channels=AUDIO_CHANNELS,
            dtype=np.float32,
            blocksize=AUDIO_CHUNK_SAMPLES,
            callback=self._audio_callback,
        )
        self._stream.start()
        logger.info("STT mic stream opened")

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            pass  # Status logged at debug level if needed

        # Put chunk into queue for VAD processing in worker thread
        self._audio_queue.put(indata[:, 0].copy())

    def _vad_worker(self):
        """Worker thread: runs VAD, detects speech boundaries, transcribes."""
        import torch

        while True:
            chunk = self._audio_queue.get()
            if chunk is None:
                break  # Shutdown signal

            # VAD
            audio_tensor = torch.from_numpy(chunk).float()
            with torch.no_grad():
                prob = self._vad_model(audio_tensor, AUDIO_SAMPLE_RATE).item()

            if prob >= self._vad_threshold:
                # Speech detected
                if not self._in_speech:
                    self._in_speech = True
                    # Flush preroll into speech buffer
                    if self._preroll_buffer:
                        self._speech_buffer.extend(list(self._preroll_buffer))
                        self._preroll_buffer.clear()
                    logger.debug("Speech onset")
                self._consecutive_silence = 0
                self._speech_buffer.append(chunk)
            else:
                # Silence
                if self._in_speech:
                    self._consecutive_silence += 1
                    self._speech_buffer.append(chunk)
                    if self._consecutive_silence >= self._silence_chunks:
                        self._in_speech = False
                        self._consecutive_silence = 0
                        logger.debug("Speech ended, transcribing...")
                        self._transcribe()
                else:
                    # Buffer for preroll
                    self._preroll_buffer.extend(chunk.tolist())

    def _transcribe(self):
        """Transcribe the current speech buffer and signal completion."""
        if self._abort_event.is_set():
            self._abort_event.clear()
            self._speech_buffer.clear()
            return

        if not self._speech_buffer:
            return  # Don't signal — no speech detected

        try:
            audio = np.concatenate(self._speech_buffer)
        except (ValueError, TypeError):
            audio = np.array([], dtype=np.float32)

        self._speech_buffer.clear()

        if len(audio) < AUDIO_SAMPLE_RATE * 0.2:
            return  # Too short, not real speech

        try:
            segments, _ = self._whisper.transcribe(
                audio,
                language=STT_LANGUAGE,
                initial_prompt=self._initial_prompt,
                beam_size=3,
            )
            self._result_text = " ".join(seg.text for seg in segments).strip()
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            self._result_text = ""

        # Only signal if we got meaningful text
        if self._result_text:
            logger.debug(f"Transcribed: '{self._result_text}'")
            self._result_ready.set()
        else:
            logger.debug("Empty transcription result, ignoring")

    def abort(self):
        """Abort the current speech collection."""
        self._abort_event.set()
        self._result_ready.clear()
        # Drain audio queue
        try:
            while True:
                self._audio_queue.get_nowait()
        except queue.Empty:
            pass
        self._speech_buffer.clear()
        self._preroll_buffer.clear()
        self._in_speech = False
        self._consecutive_silence = 0
        self._result_text = ""

    async def listen_async(self, tts=None) -> str:
        """
        Wait for the next user speech event.
        """
        # Clear result state
        self._abort_event.clear()
        self._result_ready.clear()
        self._result_text = ""
        # Reset speech detection state
        self._speech_buffer.clear()
        self._preroll_buffer.clear()
        self._in_speech = False
        self._consecutive_silence = 0
        # Drain audio queue (remove stale TTS audio picked up by mic)
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

        # Wait for result or abort
        while not self._abort_event.is_set():
            if self._result_ready.wait(timeout=0.1):
                return self._result_text

        self._abort_event.clear()
        return ""

    def close(self):
        """Stop the microphone stream."""
        self._audio_queue.put(None)  # Shutdown worker
        self._abort_event.set()
        self._stream.stop()
        self._stream.close()
        logger.info("STT mic stream closed")
