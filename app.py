import piper
import re
import sounddevice as sd
import numpy as np

from config import *

# ------ #
# Config #
# ------ #

# LLM CONFIG

def is_sentence_end(text: str) -> bool:
    return bool(SENTENCE_END_RE.search(text))

def speak(text: str, piper_voice: piper.PiperVoice):
    audio_gen = piper_voice.synthesize(text)

    for audio_chunk in audio_gen:
        audio_bytes = getattr(audio_chunk, 'audio_int16_bytes', None)
        if audio_bytes:
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
            sd.play(audio_np, samplerate=22050)
            sd.wait()

def clean_text(text: str) -> str:
    """Clean text for tts"""

    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`[^`]*`', '', text)
    
    # Удаляем ссылки и специальные символы
    text = re.sub(r'\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'[*_~#`]', '', text)
    
    # Заменяем HTML-сущности
    text = text.replace('&quot;', '"').replace('&amp;', 'и')
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    
    # Очищаем пунктуацию
    text = re.sub(r'[\[\](){}]', '', text)
    
    # Убираем лишние пробелы
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def main():
    """Main function"""

    print("Load model...")

    # Load model
    try:
        llm = Llama(
            model_path=LLAMA_MODEL_PATH,
            n_ctx=LLM_CONTEXT_LENTH,
            n_gpu_layers=LLM_GPU_LAYERS,
            verbose=False
        )

    except Exception as e:
        print(f"Error when loading llm model:{e}")

    # Initializing tts
    try:
        piper_voice = piper.PiperVoice.load(
            model_path=PIPER_MODEL_PAHT,
            config_path=PIPER_CONFIG_PATH,
            use_cuda=True
        )

    except Exception as e:
        print(f"Error when loading tts model:{e}")

    print("All moldels sucsessfully loaded!")
    print("=====================")


    history=[]
    history.append({"role": "system", "content": SYSTEM_PROMTP})

    while(True):

        user_input = input("Input prompt: ")
        message={"role": "user", "content": user_input}
        history.append(message)

        # Используем chat_completion с stream=True
        stream = llm.create_chat_completion(
            messages=history,
            stream=True
        )

        print("LLM answer: ", end="", flush=True)

        full_responce = ''
        tts_buffer = ''

        # Читаем токены по одному
        for chunk in stream:
            # Теперь редактор знает, что это словарь, и метод .get() подсветится нормально
            choices = chunk.get("choices", [])#type: ignore
            
            if not choices:
                continue
                
            delta = choices[0].get("delta", {})
            text_chunk = delta.get("content")

            if not text_chunk:
                continue

            print(text_chunk, end="", flush=True)
            tts_buffer += text_chunk

            if is_sentence_end(tts_buffer):
                    sentence = clean_text(tts_buffer)

                    if sentence:
                        speak(sentence, piper_voice)

                    tts_buffer = ""

            full_responce += text_chunk


        history.append({"role": "assistant", "content": full_responce})

main()
