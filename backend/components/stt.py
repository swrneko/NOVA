import torch
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from silero_vad import load_silero_vad
from collections import deque

MODEL_SIZE = "large-v3-turbo"
SAMPLE_RATE = 16000
VAD_TRESHOLD = 0.75
CHUNK_SIZE = 512
MAX_SILENCE_CHUNKS = 30
PRE_ROLL_SEC = 0.5

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

        self.pre_roll = deque(maxlen=int(SAMPLE_RATE/CHUNK_SIZE * 0.5))


    def listen(self, tts: None):
        audio_buffer = []
        is_speaking = False
        silence_chunks = 0

        self.pre_roll.clear()

        print("[Listen...]\n")

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32") as stream:
            while True:
                chunk, _ = stream.read(CHUNK_SIZE)
                chunk = chunk.flatten()

                speech_probe = self.vad(torch.from_numpy(chunk), SAMPLE_RATE).item()

                if speech_probe > VAD_TRESHOLD:
                    if not is_speaking:
                        is_speaking = True
                        print("[VOICE TARGETED!]")

                        audio_buffer.extend(list(self.pre_roll))

                    if tts:
                        tts.abort()

                    audio_buffer.append(chunk)
                    silence_chunks = 0

                elif is_speaking:
                    silence_chunks += 1

                    if silence_chunks > MAX_SILENCE_CHUNKS:
                        print("[VOID]")
                        break

                else:
                    self.pre_roll.append(chunk)

        if audio_buffer:
            full_audio = np.concatenate(audio_buffer)

            segments, _ = self.stt.transcribe(
                full_audio,
                language='ru',
                initial_prompt="Александр Егоров, Нанасаки, Аи, время, сколько, включи, выключи.",
                vad_filter=True,
                no_speech_threshold=VAD_TRESHOLD
            )

            text = "".join([s.text for s in segments]).strip()

            print(f"[TRANSCRIBED RESULT: {text}]")

        return text

