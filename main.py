import asyncio
import json
import datetime

from components import llm, textCleaner, tts, stt, mqtt
from config import SYSTEM_PROMTP

# Инициализация компонентов
llm_engine = llm.LLM()
cleaner = textCleaner.TextCleaner()
tts_engine = tts.TTS()
stt_engine = stt.STT()
mqtt_client = mqtt.MQTT()

history = [{"role": "system", "content": SYSTEM_PROMTP}]

def turnOnTableLight(state: bool):
    topic = "nanasaki/desk-light"
    payload = json.dumps({"state": state})
    mqtt_client.mqtt_client.publish(topic, payload)
    return f"свет на столе сейчас в состоянии {state}."

def turnBigLight(state: bool):
    topic = "nanasaki/big-light"
    payload = json.dumps({"state": state})
    mqtt_client.mqtt_client.publish(topic, payload)
    return f"большой свет сейчас в состоянии {state}."

def get_time():
    now = datetime.datetime.now()
    h = now.hour
    m = now.minute

    # 1. Определяем время суток (по-русски так понятнее для LLM)
    if 5 <= h < 12:
        period = "утра"
    elif 12 <= h < 17:
        period = "дня"
    elif 17 <= h < 21:
        period = "вечера"
    else:
        period = "ночи"

    # 2. Математика: переводим 24 -> 12
    # Оператор % 12 превратит 14 в 2, а 20 в 8.
    h_12 = h % 12
    
    # Исправляем случай с 00:00 и 12:00 (так как 12 % 12 = 0)
    if h_12 == 0:
        h_12 = 12

    # Возвращаем строку. Например: "2:15 дня" или "10:30 вечера"
    return f"{h_12}:{m:02d} {period}"

ACTIONS = {
    "get_time": get_time,
    "turnOnTableLight": turnOnTableLight,
    "turnBigLight": turnBigLight
}

async def handleAnswerLLMandTTS(tool_res=None):
    # Проверяем на использование функции
    # Если используем функцию то передаём её результат
    # Если не используем то получаем ввод от stt и записываем в историю
    if tool_res is not None:
        message={"role": "system", "content": f"Function return: '{tool_res}'"}
    else:
        user_input = await asyncio.to_thread(stt_engine.listen, tts_engine)#type: ignore
        message={"role": "user", "content": user_input}
        tts_engine.abort()#type: ignore

        print("LLM answer: ")

    # Записываем сообщение пользователя в историю
    history.append(message)

    # Полный ответ и буфер tts
    full_responce = ''
    tts_buffer = ''

    # Получаем стрим от llm
    stream = llm_engine.llmGenerateStream(history) #type: ignore   

    # Флаг проверки размышлений модели
    is_thinking = False

    # Буфер json для сборки
    json_buffer = ""

    # Читаем токены по одному
    for chunk in stream:
        choices = chunk.get("choices", [])#type: ignore
        
        if not choices:
            continue
            
        delta = choices[0].get("delta", {})
        text_chunk = delta.get("content")

        if not text_chunk: continue

        # Убераем слова размышлений из ответа
        if "<think>" in text_chunk: is_thinking = True; continue
        elif "</think>" in text_chunk: is_thinking = False; continue
        elif is_thinking == True: continue

        # Проверка на json
        if "{" in text_chunk or json_buffer:
            json_buffer += text_chunk

            # Пытаемся загрузить json. Если он не загрузился значит он ещё не собран полностью
            try:
                data = json.loads(json_buffer)
            except json.JSONDecodeError:
                continue

            # Если дошли сюда, значит json корректный -> выполняем обработку функции вызванной моделью
            if data:
                action = data.get("action")

                if action in ACTIONS:
                    res = ACTIONS[action](**data.get("args", {}))
                    print("DEBUG")
                    print(data)
                    print("DEBUG")
                    print(res)
                    print("DEBUG")
                    return await handleAnswerLLMandTTS(tool_res=res)#type: ignore


        # Выводим чанк текста и добавляем в буфер
        print(text_chunk, end="", flush=True)
        tts_buffer += text_chunk

        # Проверка на конец предложения. Если конец то озвучиваем 
        if cleaner.is_sentence_end(tts_buffer):#type:ignore
            sentence = cleaner.clean_text(tts_buffer) #type:ignore

            if sentence:
                asyncio.create_task(asyncio.to_thread(tts_engine.speak, sentence))#type: ignore
                await asyncio.sleep(0.05)

            tts_buffer = ""

        # Собираем полный ответ модели
        full_responce += text_chunk



    # Если мы не вызывали функцию то добавляем ответ от модели
    # Если вызывали функцию, то не добавляем ответ от модели и удаляем сообщение вывода функции
    # Делается для того, чтобы не было скопления старой информации из-за чего модель выдаёт неверные данные
    if tool_res is None:
        history.append({"role": "assistant", "content": full_responce})
    else:
        history.pop()


async def main():
    """Main function"""
    while(True):
        await handleAnswerLLMandTTS()  

asyncio.run(main())
