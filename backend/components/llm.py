from openai import OpenAI
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import *

class LLM():
    def __init__(self):
        '''init class'''
        print(f"Подключение к io.net Intelligence API: {OPENAI_BASE_URL}")
        try:
            self.client = OpenAI(
                api_key=OPENAI_API_KEY,
                base_url=OPENAI_BASE_URL,
            )
            self.model = OPENAI_MODEL_NAME
            print(f"LLM API успешно инициализирован (модель: {self.model})")
        except Exception as e:
            print("ОШИБКА: Не удалось инициализировать OpenAI клиент!")
            print(f"Error: {e}")
            self.client = None
            self.model = None

    def llmGenerateStream(self, history: list):
        if not self.client:
            yield {"choices": [{"delta": {"content": "Ошибка: LLM клиент не инициализирован."}}]}
            return

        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=history,
                stream=True,
                temperature=TEMPERATUE,
                max_completion_tokens=LLM_CONTEXT_LENTH,
            )

            for chunk in stream:
                # chunk: ChatCompletionChunk
                # конвертируем в dict для обратной совместимости с ws_routes.py
                yield chunk.model_dump()

        except Exception as e:
            print(f"Ошибка при запросе к LLM API: {e}")
            yield {"choices": [{"delta": {"content": f"[Ошибка API: {e}]"}}]}
