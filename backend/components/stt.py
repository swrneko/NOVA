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
        try:
            self.stt = WhisperModel(MODEL_SIZE, device="cuda", compute_type="float16")
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
        
        # Проверяем VAD (есть ли голос вообще)
        # silero ожидает torch tensor
        audio_tensor = torch.from_numpy(audio_np)
        speech_prob = self.vad(audio_tensor, self.sample_rate).item()

        if speech_prob < VAD_TRESHOLD:
             return ""

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

