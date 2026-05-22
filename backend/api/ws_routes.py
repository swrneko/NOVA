from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
import asyncio
import json
import datetime

from backend.database.db import get_db
from backend.database.models import User, Message
from backend.components.llm import LLM
from backend.components.stt import STT
from backend.components.tts import TTS
from backend.components.textCleaner import TextCleaner
from backend.components.mqtt import MQTT
from config import SYSTEM_PROMTP

router = APIRouter()

# Инициализируем AI компоненты при старте роутера
# (В реальном проде это делают через Dependency Injection или Lifespan events)
print("Инициализация AI модулей...")
llm_engine = LLM()
stt_engine = STT()
tts_engine = TTS()
cleaner = TextCleaner()
mqtt_client = MQTT()

# --- Инструменты (Функции) ---
def get_time():
    now = datetime.datetime.now()
    h = now.hour
    m = now.minute

    if 5 <= h < 12: period = "утра"
    elif 12 <= h < 17: period = "дня"
    elif 17 <= h < 21: period = "вечера"
    else: period = "ночи"

    h_12 = h % 12
    if h_12 == 0: h_12 = 12
    return f"{h_12}:{m:02d} {period}"

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

ACTIONS = {
    "get_time": get_time,
    "turnOnTableLight": turnOnTableLight,
    "turnBigLight": turnBigLight
}


# --- WebSocket Роут ---
@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket, db: Session = Depends(get_db)):
    """
    WebSocket endpoint. Клиент подключается, отправляет аудио-байты (голос),
    а сервер отвечает аудио-байтами (синтезированной речью).
    """
    await websocket.accept()
    print("[WS] Клиент подключился к голосовому чату.")

    # Временно: создаем "заглушку" пользователя, если его нет (для тестов)
    # В проде мы должны брать юзера из JWT токена
    user = db.query(User).first()
    if not user:
        user = User(username="test_user", password_hash="hash", totp_secret="secret")
        db.add(user)
        db.commit()

    # Загружаем историю из БД
    db_history = db.query(Message).filter(Message.user_id == user.id).order_by(Message.timestamp).all()
    history = [{"role": "system", "content": SYSTEM_PROMTP}]
    for msg in db_history:
        history.append({"role": msg.role, "content": msg.content})

    active_task = None

    try:
        while True:
            # Ждем любое сообщение от клиента (текст или бинарные данные)
            message = await websocket.receive()
            print(f"[WS DEBUG] Received message: {list(message.keys())}")
            
            # 1. Если пришел сигнал отмены (abort) в текстовом виде:
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    print(f"[WS DEBUG] Received text data: {data}")
                    if data.get("type") == "abort":
                        if active_task and not active_task.done():
                            active_task.cancel()
                            print("[WS] Генерация предыдущего ответа прервана пользователем!")
                except Exception as e:
                    print(f"Error parsing text WS message: {e}")
            
            # 2. Если пришли аудио-байты (новый вопрос):
            elif "bytes" in message:
                audio_bytes = message["bytes"]
                
                # Если сейчас идет генерация старого ответа, ПРЕРЫВАЕМ её!
                if active_task and not active_task.done():
                    active_task.cancel()
                    print("[WS] Предыдущая генерация прервана перед обработкой нового запроса!")
                
                # Запускаем обработку нового аудио в фоне в отдельной задаче asyncio!
                # Благодаря этому, основной цикл while True свободен и может мгновенно принять
                # сигнал 'abort' или новые байты, пока текущая задача обрабатывается!
                async def handle_request():
                    try:
                        print(f"[WS] Начало обработки аудио: {len(audio_bytes)} байт")
                        # Переводим звук в текст
                        user_text = await asyncio.to_thread(stt_engine.transcribe_audio_bytes, audio_bytes)
                        
                        if not user_text:
                            await websocket.send_json({"type": "info", "message": "Голос не распознан"})
                            return
                            
                        # НЕ сохраняем в БД сразу, чтобы избежать блокировок SQLite при отмене (CancelledError)
                        # Мы сохраним и вопрос, и ответ одной транзакцией при успешном завершении.
                        history.append({"role": "user", "content": user_text})
                        
                        # Оповещаем UI
                        await websocket.send_json({"type": "text_user", "text": user_text})

                        # Обрабатываем ответ через LLM + Tools
                        await process_llm_and_tts(websocket, history, user, db)
                    except asyncio.CancelledError:
                        print("[WS] Задача генерации была успешно прервана.")
                        # Очищаем историю контекста в памяти от неоконченного запроса
                        if history and history[-1]["role"] == "user":
                            history.pop()
                    except Exception as e:
                        print(f"Error in handle_request task: {e}")

                active_task = asyncio.create_task(handle_request())

    except WebSocketDisconnect:
        print("[WS] Клиент отключился")


async def process_llm_and_tts(websocket: WebSocket, history: list, user: User, db: Session, tool_res=None):
    """Оркестратор: LLM стриминг -> TTS синтез -> Отправка клиенту"""
    
    if tool_res is not None:
        history.append({"role": "system", "content": f"Function return: '{tool_res}'"})

    full_response = ''
    tts_buffer = ''
    json_buffer = ""
    is_thinking = False

    # Запускаем генерацию в потоке
    stream = await asyncio.to_thread(llm_engine.llmGenerateStream, history)

    for chunk in stream:
        choices = chunk.get("choices", [])
        if not choices: continue
        
        delta = choices[0].get("delta", {})
        text_chunk = delta.get("content")
        if not text_chunk: continue

        # Убираем размышления <think>
        if "<think>" in text_chunk: is_thinking = True; continue
        elif "</think>" in text_chunk: is_thinking = False; continue
        elif is_thinking: continue

        # Проверка на вызов инструмента (JSON)
        if "{" in text_chunk or json_buffer:
            json_buffer += text_chunk
            try:
                data = json.loads(json_buffer)
            except json.JSONDecodeError:
                continue

            if data and "action" in data:
                action = data.get("action")
                if action in ACTIONS:
                    res = ACTIONS[action](**data.get("args", {}))
                    print(f"[TOOL] Executed {action}, result: {res}")
                    return await process_llm_and_tts(websocket, history, user, db, tool_res=res)

        full_response += text_chunk
        tts_buffer += text_chunk
        
        # Отправляем кусок текста клиенту для UI (чтобы печаталось в реальном времени)
        await websocket.send_json({"type": "text_chunk", "text": text_chunk})
        # Принудительно уступаем управление Event Loop'у на 1мс, чтобы 
        # сервер успел принять новые сообщения (например, сигнал 'abort') по WebSocket!
        await asyncio.sleep(0.001)

        # Если конец предложения -> синтезируем речь и отправляем байты!
        if cleaner.is_sentence_end(tts_buffer):
            sentence = cleaner.clean_text(tts_buffer)
            if sentence:
                # Синтезируем байты синхронно (генератор) и отправляем по websocket
                audio_gen = tts_engine.synthesize_to_bytes(sentence)
                for audio_chunk_bytes in audio_gen:
                    # Отправляем сырые байты по вебсокету
                    await websocket.send_bytes(audio_chunk_bytes)
                    await asyncio.sleep(0.001) # Уступаем управление
                
            tts_buffer = ""

    # Сохраняем финальный ответ в БД
    if tool_res is None:
        try:
            # Находим последний текст вопроса пользователя в памяти
            user_text = next(msg["content"] for msg in reversed(history) if msg["role"] == "user")
            
            # Сохраняем и вопрос, и ответ одной чистой транзакцией
            user_msg = Message(user_id=user.id, role="user", content=user_text)
            assistant_msg = Message(user_id=user.id, role="assistant", content=full_response.strip())
            
            db.add(user_msg)
            db.add(assistant_msg)
            db.commit()
        except Exception as e:
            print(f"Error saving chat history to DB: {e}")
            db.rollback()
            
        history.append({"role": "assistant", "content": full_response.strip()})
    else:
        history.pop() # Удаляем системное сообщение от функции
        
    # Сигнал клиенту, что ответ завершен
    await websocket.send_json({"type": "done"})
