import torch
import numpy as np
from faster_whisper import WhisperModel
from silero_vad import load_silero_vad

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import *

MODEL_SIZE = "large-v3-turbo"
SAMPLE_RATE = 16000
VAD_TRESHOLD = 0.75

class STT():
    def __init__(self):
        print("Loading Whisper model...")
        # Указываем явно директорию кэша в домашней папке пользователя, чтобы он не перекачивал модель
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
        try:
            self.stt = WhisperModel(MODEL_SIZE, device="cuda", compute_type="float16", download_root=cache_dir)
        except Exception as e:
            print("Whisper not loaded!")
            print(f"Error: {e}")

        print("Loading VAD...")
        try:
            self.vad = load_silero_vad(onnx=True)
        except Exception as e:
            print("VAD not loaded!")
            print(f"Error: {e}")

        self.sample_rate = SAMPLE_RATE

    def transcribe_audio_bytes(self, audio_bytes: bytes) -> str:
        """Принимает сырые аудио-байты от клиента, проверяет VAD и транскрибирует"""
        if not audio_bytes:
            return ""

        # Конвертируем байты (предполагается float32 16kHz) в numpy массив
        audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
        
        # Мы не делаем ручной VAD-чек на всей длине аудио, так как Silero VAD ожидает
        # короткие чанки и на длинном аудио может вернуть неверный результат (или упасть).
        # Вместо этого мы полагаемся на встроенный в faster-whisper параметр vad_filter=True.

        # Транскрибируем
        segments, _ = self.stt.transcribe(
            audio_np,
            language='ru',
            initial_prompt="Александр Егоров, Нанасаки, Аи, время, сколько, включи, выключи.",
            vad_filter=True,
            no_speech_threshold=VAD_TRESHOLD
        )

        text = "".join([s.text for s in segments]).strip()
        print(f"[TRANSCRIBED RESULT: {text}]")
        return text

