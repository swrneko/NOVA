import re

from config import *

class TextCleaner():
    def __init__(self):
        pass

    def clean_text(self, text: str) -> str:
        '''Clean text for tts'''

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

    def is_sentence_end(self, text: str) -> bool:
        return bool(SENTENCE_END_RE.search(text))

