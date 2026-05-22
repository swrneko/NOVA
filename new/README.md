# NOVA — Neural Operational Voice Assistant (Refactored)

Голосовой AI-ассистент для Arch Linux с RAG, безопасным выполнением команд и умным домом.

## Архитектура

```
nova/
├── config.py                  # Центральный конфиг (пути, модели, безопасность)
├── app.py                     # Главный entry point (пайплайн STT→RAG→LLM→TTS)
├── components/
│   ├── stt.py                 # Speech-to-Text (faster-whisper + Silero VAD)
│   ├── tts.py                 # Text-to-Speech (Piper, streaming)
│   └── llm.py                 # LLM (llama-cpp-python, streaming)
├── rag/
│   └── rag_adapter.py         # RAG адаптор (ChromaDB, embeddings)
├── tools/
│   └── tool_registry.py       # Реестр инструментов + function calling
└── security/
    ├── command_validator.py   # Валидация команд (allowlist/blocklist)
    └── command_executor.py    # Безопасное выполнение (sandbox + confirmation)
```

## Ключевые особенности

### 1. Безопасность
- **Allowlist/Blocklist**: Только разрешённые команды выполняются
- **Sandbox**: Команды запускаются в bubblewrap/firejail
- **Confirmation**: Средне-рисковые команды требуют подтверждения пользователя
- **Audit log**: Все действия логируются
- **Pattern detection**: Защита от injection (`;`, `|`, backticks, `$()`)

### 2. RAG (Retrieval-Augmented Generation)
- **ChromaDB**: Локальная векторная база данных
- **Multilingual embeddings**: `intfloat/multilingual-e5-large`
- **Источники**: Arch Wiki, личные заметки, системные конфиги
- **Incremental indexing**: Только новые/изменённые файлы

### 3. Tool System
- **JSON Schema**: Автоматическая генерация для LLM function calling
- **Registry**: Централизованный реестр с метаданными
- **Categories**: system, rag, info, smart_home

## Установка

```bash
# 1. Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate

# 2. Установить llama-cpp-python с CUDA
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir

# 3. Установить остальные зависимости
pip install -r requirements.txt

# 4. Установить bubblewrap (для sandbox)
sudo pacman -S bubblewrap
```

## Настройка

Все настройки в `nova/config.py` или через переменные окружения:

```bash
export NOVA_LLM_MODEL="/path/to/model.gguf"
export NOVA_RAG_DB="~/.local/share/nova/rag_chroma"
export NOVA_SANDBOX="bwrap"
```

## Запуск

```bash
python -m nova.app
```

## Безопасные команды

По умолчанию разрешены:
- Информационные: `ls`, `cat`, `echo`, `date`, `uptime`, `ps`, `df`, `free`
- Arch Linux: `pacman -Q`, `pacman -Qs`, `pacman -Si`, `journalctl`, `systemctl status`
- Сеть: `ping`, `ip`, `ss`, `dig`
- Системные: `lscpu`, `lsblk`, `lspci`, `lsusb`, `neofetch`

Требуют подтверждения:
- Установка пакетов: `pacman -S`, `pacman -Syu`
- Управление сервисами: `systemctl start/stop/restart/enable/disable`
- Файловые операции: `mkdir`, `touch`, `cp`, `mv`

Заблокированы:
- `rm`, `rmdir`, `shred`, `dd`, `mkfs`
- `sudo`, `su`, `kill`, `killall`
- Любые команды с `;`, `|`, `&&`, backticks, `$()`
