import piper as p
import sounddevice as sd
import queue as q
import threading as th
import numpy as np
import re

from config import *


class TTS:
    def __init__(self):
        print(">>> Загрузка TTS (Piper)...")
        self.audio_queue = q.Queue()
        self.is_running = True
        self.stop_signal = False
        self.current_chunk = None
        self.lock = th.Lock()

        try:
            self.tts = p.PiperVoice.load(
                model_path=PIPER_MODEL_PAHT,
                config_path=PIPER_CONFIG_PATH,
                use_cuda=True # CPU для стабильности
            )
            self.syn_config = p.SynthesisConfig(
                volume=1.0,
                length_scale=0.85,
                noise_scale=0.667, 
                noise_w_scale=0.8,
                normalize_audio=True
            )
        except Exception as e:
            print(f"Ошибка загрузки Piper: {e}")

        # Инициализация и запуск потока воспроизведения (Callback)
        self.stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=self._audio_callback,
            blocksize=1024  # Маленький буфер для мгновенной реакции
        )
        self.stream.start()

    def _audio_callback(self, outdata, frames, time, status):
        """Звуковая карта сама вызывает эту функцию, когда ей нужны данные"""
        if self.stop_signal:
            outdata.fill(0)
            return

        read_frames = 0
        while read_frames < frames:
            # Если текущий чанк закончился, берем новый из очереди
            if self.current_chunk is None or len(self.current_chunk) == 0:
                try:
                    self.current_chunk = self.audio_queue.get_nowait()
                except q.Empty:
                    outdata[read_frames:] = 0 # Тишина
                    break

            # Откусываем столько, сколько просит звуковая карта
            remaining = frames - read_frames
            take = min(remaining, len(self.current_chunk))
            
            outdata[read_frames : read_frames + take, 0] = self.current_chunk[:take]
            self.current_chunk = self.current_chunk[take:]
            read_frames += take

    def speak(self, text: str):
        """Синтезирует текст и кладет его в очередь (блокирующая, вызывать в thread)"""
        with self.lock: # Очередность предложений
            self.stop_signal = False
            
            # Чистим текст от мусора
            clean_text = re.sub(r'[*_#`~\[\]]', '', text).strip()
            if len(clean_text) < 2: return

            try:
                audio_gen = self.tts.synthesize(clean_text, self.syn_config)
                for chunk in audio_gen:
                    if self.stop_signal: break
                    
                    audio_bytes = chunk.audio_int16_bytes
                    if audio_bytes:
                        audio_np = np.frombuffer(audio_bytes, dtype="int16")
                        self.audio_queue.put(audio_np)
            except Exception as e:
                print(f"Ошибка синтеза: {e}")

    def abort(self):
        """Мгновенная остановка"""
        self.stop_signal = True
        self.current_chunk = None
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except q.Empty: break
