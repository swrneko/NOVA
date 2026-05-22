"""
Continuous speech listener using Silero VAD + sounddevice.
Keeps the mic stream open at all times and yields transcribed speech.
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


class ContinuousListener:
    """
    Keeps the microphone stream open continuously.
    Detects speech via VAD, transcribes, and yields text.

    Usage:
        listener = ContinuousListener()
        listener.start()

        # Later, from async code:
        text = await listener.get_speech()
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

        # Speech result queue
        self._speech_queue: queue.Queue[str | None] = queue.Queue()

        # Abort flag for current speech collection
        self._abort_event = threading.Event()

        self._stream = None
        self._listener_thread = None
        self._running = False

    def _get_vad_prob(self, audio_chunk: np.ndarray) -> float:
        """Run VAD on an audio chunk."""
        import torch
        audio_tensor = torch.from_numpy(audio_chunk).float()
        with torch.no_grad():
            score = self._vad_model(audio_tensor, AUDIO_SAMPLE_RATE).item()
        return score

    def _collect_speech(self, tts=None) -> str:
        """
        Collect speech from the always-open mic stream.
        Blocks until speech ends or abort is called.
        Returns transcribed text or empty string.
        """
        pre_roll_buffer = deque(maxlen=self._preroll_chunks * AUDIO_CHUNK_SAMPLES)
        speech_buffer = []
        consecutive_silence = 0
        in_speech = False
        speech_ended = threading.Event()

        def audio_callback(indata, frames, time_info, status):
            nonlocal consecutive_silence, in_speech
            if status:
                logger.debug(f"Audio status: {status}")

            chunk = indata[:, 0]  # mono
            prob = self._get_vad_prob(chunk)

            if prob >= self._vad_threshold:
                if not in_speech:
                    in_speech = True
                    logger.debug("Speech onset detected")
                consecutive_silence = 0
                speech_buffer.append(chunk.copy())
            else:
                if in_speech:
                    consecutive_silence += 1
                    speech_buffer.append(chunk.copy())
                    if consecutive_silence >= self._silence_chunks:
                        logger.debug("Speech ended (silence timeout)")
                        speech_ended.set()
                else:
                    pre_roll_buffer.extend(chunk.tolist())

        # Abort TTS if speaking
        if tts:
            tts.abort()

        self._abort_event.clear()

        with sd.InputStream(
            samplerate=AUDIO_SAMPLE_RATE,
            channels=AUDIO_CHANNELS,
            dtype=np.float32,
            blocksize=AUDIO_CHUNK_SAMPLES,
            callback=audio_callback,
        ):
            # Wait for speech to end or abort
            while not self._abort_event.is_set():
                if speech_ended.wait(timeout=0.05):
                    break
                # Also check abort
                if self._abort_event.is_set():
                    break

        if self._abort_event.is_set():
            return ""

        # Combine pre-roll + speech
        if pre_roll_buffer:
            preroll = np.array(list(pre_roll_buffer), dtype=np.float32)
            speech = np.concatenate([preroll] + speech_buffer) if speech_buffer else preroll
        else:
            speech = np.concatenate(speech_buffer) if speech_buffer else np.array([], dtype=np.float32)

        # Transcribe
        if len(speech) < AUDIO_SAMPLE_RATE * 0.2:
            return ""

        segments, _ = self._whisper.transcribe(
            speech,
            language=STT_LANGUAGE,
            initial_prompt=self._initial_prompt,
            beam_size=3,
        )

        text = " ".join(seg.text for seg in segments).strip()
        logger.debug(f"Transcribed: {text}")
        return text

    def abort(self):
        """Abort the current speech collection."""
        self._abort_event.set()

    async def get_speech(self, tts=None) -> str:
        """
        Wait for user speech and return transcribed text.
        This is the main entry point — call it in a loop.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._collect_speech, tts)

    def close(self):
        """Clean up resources."""
        self._abort_event.set()
