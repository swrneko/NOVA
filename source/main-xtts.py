import torch
import numpy as np
import sounddevice as sd
import queue
import threading
import re
import sys
from llama_cpp import Llama
from TTS.api import TTS



# === НАСТРОЙКИ ===
LLAMA_MODEL = "/home/swrneko/HDD/lm_studio_models/lmstudio-community/gemma-3-4b-it-GGUF/gemma-3-4b-it-Q4_K_M.gguf"
SPEAKER_WAV = "/home/swrneko/Documents/Japanese Female Voice Sample 1.mp3"
SYSTEM_PROMPT = "Ты голосовой ассистент. Отвечай кратко."
SAMPLE_RATE = 24000  # Родная частота XTTS v2

# === ФИКС PYTORCH ===
_old_load = torch.load
def new_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _old_load(*args, **kwargs)
torch.load = new_load

# === АУДИО ДВИЖОК (Low Latency) ===
class AudioPlayer:
    def __init__(self):
        self.q = queue.Queue()
        self.stream = sd.OutputStream(
            samplerate=24000,       # Убедись, что тут 24000 для XTTS
            channels=1,
            dtype='float32',
            callback=self.callback,
            blocksize=2048
        )
        self.stream.start()         # Запускаем сразу
        self.buffer = None          # Буфер для хранения остатков аудио

    def callback(self, outdata, frames, time, status):
        if status:
            print(status, file=sys.stderr)
        
        filled = 0
        
        # Пока не заполним весь запрошенный буфер аудиокарты (frames)
        while filled < frames:
            # 1. Если у нас нет данных в буфере, пытаемся взять из очереди
            if self.buffer is None or len(self.buffer) == 0:
                try:
                    # Берем новый кусок из очереди
                    self.buffer = self.q.get_nowait()
                except queue.Empty:
                    # Если данных нет вообще - заполняем тишиной и выходим
                    outdata[filled:] = 0
                    return

            # 2. Рассчитываем, сколько можем взять
            # Сколько осталось заполнить в outdata
            needed = frames - filled
            # Сколько есть в нашем буфере
            available = len(self.buffer)
            
            # Берем минимум (либо всё что нужно, либо всё что есть)
            to_copy = min(needed, available)
            
            # 3. Копируем данные
            # reshape(-1, 1) нужен, так как sounddevice ждет [frames, channels]
            outdata[filled : filled + to_copy] = self.buffer[:to_copy].reshape(-1, 1)
            
            # 4. Обновляем счетчики
            filled += to_copy
            
            # 5. Отрезаем использованную часть от буфера
            if to_copy < available:
                self.buffer = self.buffer[to_copy:] # Оставляем остаток на следующий раз
            else:
                self.buffer = None # Буфер кончился

    def add_chunk(self, chunk):
        # Просто кладем данные в очередь, callback сам разберется с размерами
        self.q.put(chunk)

# === ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ===
player = AudioPlayer()
tts_queue = queue.Queue() # Очередь текста для TTS

def tts_worker(tts_model, gpt_cond_latent, speaker_embedding):
    """Поток, который берет текст и превращает его в аудио-чанки на лету"""
    while True:
        text = tts_queue.get()
        if text is None: break
        
        # ПРЯМОЙ ДОСТУП К STREAMING МЕТОДУ МОДЕЛИ
        # Это самое быстрое, что есть в Coqui TTS
        chunks = tts_model.inference_stream(
            text,
            "ru",
            gpt_cond_latent,
            speaker_embedding,
            decoder="ne_hifigan" # Быстрый декодер
        )

        for i, chunk in enumerate(chunks):
            # chunk - это torch tensor. Переводим в numpy
            audio_np = chunk.cpu().numpy().astype(np.float32)
            player.add_chunk(audio_np)
        
        tts_queue.task_done()

def main():
    print(">>> 1. Загрузка LLM...")
    llm = Llama(
        model_path=LLAMA_MODEL,
        n_ctx=4096,
        n_gpu_layers=-1,
        verbose=False
    )

    print(">>> 2. Загрузка TTS...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # Загружаем обертку
    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    
    # !!! ХАК: Достаем внутреннюю модель для стриминга !!!
    model = tts.synthesizer.tts_model

    print(">>> 3. Кэширование голоса (займет пару секунд)...")
    # Мы делаем это ОДИН РАЗ при запуске, а не каждый раз при генерации
    gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(audio_path=[SPEAKER_WAV])

    # Запускаем поток TTS
    threading.Thread(
        target=tts_worker, 
        args=(model, gpt_cond_latent, speaker_embedding), 
        daemon=True
    ).start()

    print(">>> Готово! Говорите.")
    
    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Регулярка для разбивки: рубит по точкам, запятым и переносам
    # Чем чаще рубим, тем быстрее начало речи, но может быть "рваная" интонация
    SPLIT_PATTERN = re.compile(r'([.,!?;:…\n]+)') 

    while True:
        try:
            user_input = input("\nВы: ")
        except KeyboardInterrupt: break

        history.append({"role": "user", "content": user_input})
        stream = llm.create_chat_completion(messages=history, stream=True)
        
        print("Ассистент: ", end="", flush=True)

        full_response = ""
        buffer = ""

        for chunk in stream:
            chunk: dict = chunk # type: ignore
            choices = chunk.get("choices", [])
            if not choices: continue
            
            delta = choices[0].get("delta", {})
            text = delta.get("content")

            if text:
                print(text, end="", flush=True)
                full_response += text
                buffer += text

                # Проверяем на разделители
                # Если нашли знак препинания И буфер достаточно длинный (>5 символов)
                if SPLIT_PATTERN.search(text) and len(buffer) > 5:
                    # Чистим текст от лишних символов
                    clean_sent = buffer.replace("*", "").strip()
                    if clean_sent:
                        tts_queue.put(clean_sent)
                    buffer = ""

        # Досылаем остатки
        if buffer.strip():
             tts_queue.put(buffer.replace("*", "").strip())

        history.append({"role": "assistant", "content": full_response})
        print()

if __name__ == "__main__":
    main()
