import piper as p
import numpy as np
import re
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import *

class TTS:
    def __init__(self):
        print(">>> Загрузка TTS (Piper)...")
        try:
            self.tts = p.PiperVoice.load(
                model_path=PIPER_MODEL_PAHT,
                config_path=PIPER_CONFIG_PATH,
                use_cuda=True # CPU для стабильности, но если есть CUDA - оставляем True
            )
            self.syn_config = p.SynthesisConfig(
                volume=1.0,
                length_scale=0.85, # Скорость речи
                noise_scale=0.667, 
                noise_w_scale=0.8,
                normalize_audio=True
            )
        except Exception as e:
            print(f"Ошибка загрузки Piper: {e}")

    def synthesize_to_bytes(self, text: str):
        """Синтезирует текст и возвращает генератор байт (int16)"""
        # Чистим текст от мусора
        clean_text = re.sub(r'[*_#`~\[\]]', '', text).strip()
        if len(clean_text) < 2: 
            return

        try:
            audio_gen = self.tts.synthesize(clean_text, self.syn_config)
            for chunk in audio_gen:
                audio_bytes = getattr(chunk, 'audio_int16_bytes', None)
                if audio_bytes:
                     yield audio_bytes
        except Exception as e:
            print(f"Ошибка синтеза: {e}")
