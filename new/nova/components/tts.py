"""
Text-to-Speech module using Piper TTS.
Blocking playback per sentence, abort-check between sentences.
"""

import asyncio
import logging
import threading
import time
import re

import numpy as np
import sounddevice as sd
from piper import PiperVoice
from piper.config import SynthesisConfig

from nova.config import (
    TTS_MODEL_PATH,
    TTS_CONFIG_PATH,
    TTS_VOLUME,
    TTS_SPEED,
    SENTENCE_END_RE,
)

logger = logging.getLogger(__name__)


class TTS:
    """
    Text-to-Speech with Piper TTS.

    Plays sentence by sentence. Checks abort flag between sentences.
    """

    def __init__(self):
        logger.info("Loading Piper TTS model: %s", TTS_MODEL_PATH)
        self._voice = PiperVoice.load(
            TTS_MODEL_PATH,
            config_path=TTS_CONFIG_PATH if TTS_CONFIG_PATH else None,
        )

        self._sample_rate = self._voice.config.sample_rate
        logger.info("TTS initialized (sample_rate=%d)", self._sample_rate)

        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"```[\s\S]*?```", "", text)
        text = re.sub(r"`[^`]*`", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = text.replace("&nbsp;", " ")
        text = re.sub(r"[\[\]{}()<>]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _synthesize(self, text: str) -> np.ndarray:
        cleaned = self._clean_text(text)
        if not cleaned:
            return np.array([], dtype=np.float32)

        syn_config = SynthesisConfig(
            length_scale=TTS_SPEED,
            volume=TTS_VOLUME,
        )

        audio_chunks = []
        for chunk in self._voice.synthesize(cleaned, syn_config=syn_config):
            audio_chunks.append(chunk.audio_int16_array)

        if not audio_chunks:
            return np.array([], dtype=np.float32)

        combined = np.concatenate(audio_chunks, dtype=np.int16)
        return combined.astype(np.float32) / 32768.0

    def abort(self):
        """Immediately stop playback."""
        self._stop_event.set()
        sd.stop()
        logger.debug("TTS aborted")

    def speak(self, text: str):
        """
        Speak text sentence by sentence.
        Checks abort between each sentence.
        """
        self._stop_event.clear()

        cleaned = self._clean_text(text)
        if not cleaned:
            return

        sentences = re.split(r"(?<=[.!?…])\s+", cleaned)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return

        for sentence in sentences:
            if self._stop_event.is_set():
                self._stop_event.clear()
                return

            audio = self._synthesize(sentence)
            if len(audio) > 0:
                sd.play(audio, self._sample_rate)

                # Wait with periodic abort checks (instead of blocking sd.wait)
                while sd.get_stream() is not None and sd.get_stream().active:
                    if self._stop_event.is_set():
                        sd.stop()
                        self._stop_event.clear()
                        return
                    time.sleep(0.05)

                sd.wait()

    async def speak_async(self, text: str):
        """Async version."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.speak, text)

    def close(self):
        self.abort()
        sd.stop()
        logger.info("TTS closed")
