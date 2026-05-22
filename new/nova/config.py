"""
Central configuration for NOVA Voice Assistant.
All paths, model settings, and security parameters are defined here.
"""

import os

# ============================================================
# LLM Configuration
# ============================================================
LLM_MODEL_PATH = os.environ.get(
    "NOVA_LLM_MODEL",
    "/home/swrneko/HDD/Qwen3-8B-Q4_K_M.gguf"
)
LLM_CONTEXT_LENGTH = int(os.environ.get("NOVA_LLM_CTX", "12000"))
LLM_GPU_LAYERS = int(os.environ.get("NOVA_LLM_GPU", "-1"))  # -1 = all layers
LLM_TEMPERATURE = float(os.environ.get("NOVA_LLM_TEMP", "0.7"))
LLM_MAX_TOKENS = int(os.environ.get("NOVA_LLM_MAX_TOK", "2048"))

# ============================================================
# STT Configuration
# ============================================================
STT_MODEL_PATH = os.environ.get("NOVA_STT_MODEL", "large-v3-turbo")
STT_LANGUAGE = os.environ.get("NOVA_STT_LANG", "ru")
STT_VAD_THRESHOLD = float(os.environ.get("NOVA_VAD_THRESH", "0.75"))
STT_SILENCE_DURATION = float(os.environ.get("NOVA_SILENCE_DUR", "1.0"))  # seconds before EOD
STT_PREROLL = float(os.environ.get("NOVA_PREROLL", "0.5"))  # seconds of pre-roll buffer

# ============================================================
# TTS Configuration
# ============================================================
TTS_MODEL_PATH = os.environ.get(
    "NOVA_TTS_MODEL",
    "/home/swrneko/HDD/piper-tts-models/ru_RU-irina-medium.onnx"
)
TTS_CONFIG_PATH = os.environ.get(
    "NOVA_TTS_CONFIG",
    "/home/swrneko/HDD/piper-tts-models/ru_RU-irina-medium.onnx.json"
)
TTS_VOLUME = 1.0
TTS_SPEED = float(os.environ.get("NOVA_TTS_SPEED", "0.75"))  # length_scale
TTS_BLOCKSIZE = 1024  # sounddevice block size
TTS_SAMPLE_RATE = 22050

# ============================================================
# RAG Configuration
# ============================================================
RAG_CHROMA_PATH = os.environ.get(
    "NOVA_RAG_DB",
    os.path.expanduser("~/.local/share/nova/rag_chroma")
)
RAG_EMBEDDING_MODEL = os.environ.get(
    "NOVA_RAG_EMBED",
    "intfloat/multilingual-e5-large"
)
RAG_TOP_K = int(os.environ.get("NOVA_RAG_TOPK", "5"))
RAG_CHUNK_SIZE = 512  # characters per chunk
RAG_CHUNK_OVERLAP = 64  # overlap between chunks

# Document source directories to index
RAG_DOCUMENT_SOURCES = [
    # Arch Wiki local mirror (if available)
    os.path.expanduser("~/Documents/arch-wiki"),
    # Personal notes
    os.path.expanduser("~/Documents/notes"),
    # System configs backup
    os.path.expanduser("~/.config/nova-docs"),
]

# ============================================================
# Security Configuration
# ============================================================
# Commands that are ALWAYS allowed (no confirmation needed)
SAFE_COMMANDS = [
    "ls", "cat", "echo", "date", "uptime", "whoami", "uname",
    "hostname", "pwd", "df", "free", "top", "htop", "ps",
    "journalctl", "systemctl status", "pacman -Q", "pacman -Qs",
    "pacman -Si", "man", "whatis", "ip", "ping", "ss", "dig",
    "find", "grep", "head", "tail", "wc", "sort", "uniq", "diff",
    "stat", "file", "strings", "lscpu", "lsblk", "lspci", "lsusb",
    "neofetch", "fastfetch", "inxi",
]

# Commands that require user confirmation
REQUIRES_CONFIRMATION = [
    "pacman -S", "pacman -R", "pacman -Syu",
    "systemctl start", "systemctl stop", "systemctl restart",
    "systemctl enable", "systemctl disable",
    "mkdir", "touch", "cp", "mv", "chmod", "chown",
    "useradd", "usermod", "passwd",
    "mount", "umount", "fdisk", "mkfs",
    "shutdown", "reboot", "poweroff", "sleep", "hibernate",
    "wget", "curl", "git clone", "git pull",
]

# Commands that are NEVER allowed
BLOCKED_COMMANDS = [
    "rm", "rmdir", "shred",
    "mkfs", "dd", "fdisk", "parted",  # disk operations
    "iptables", "firewall-cmd",  # firewall
    "visudo", "sudo", "su",  # privilege escalation
    "kill", "killall", "pkill", "xkill",
    "rmmod", "modprobe", "insmod",
    "passwd root",  # root password change
]

# Regex patterns that indicate injection attempts
DANGEROUS_PATTERNS = [
    r"[;|&]",          # command chaining
    r"`[^`]*`",        # backtick substitution
    r"\$\([^)]*\)",    # command substitution
    r">\s*/",          # redirect to system paths
    r">\s*~",          # redirect to home
    r"/dev/",          # device files
    r"\.\./",           # path traversal
    r"\b(crond|cron)\b",  # cron manipulation
]

# Sandbox tool (firejail or bwrap)
SANDBOX_TOOL = os.environ.get("NOVA_SANDBOX", "bwrap")  # bubblewrap by default

# ============================================================
# MQTT Configuration (optional smart home)
# ============================================================
MQTT_ENABLED = os.environ.get("NOVA_MQTT", "false").lower() == "true"
MQTT_HOST = os.environ.get("NOVA_MQTT_HOST", "192.168.1.5")
MQTT_PORT = int(os.environ.get("NOVA_MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("NOVA_MQTT_USER", "")
MQTT_PASS = os.environ.get("NOVA_MQTT_PASS", "")

# ============================================================
# Audio Configuration
# ============================================================
AUDIO_SAMPLE_RATE = 16000  # for STT (mic input)
AUDIO_CHANNELS = 1
AUDIO_CHUNK_SAMPLES = 512

# ============================================================
# System Prompt
# ============================================================
SYSTEM_PROMPT = """/no_think
Ты — Нанасаки Ай (Nanasaki Ai), голосовой AI-ассистент для Arch Linux.
Твоя задача — помогать пользователю с системным администрированием,
настройкой Arch Linux, установкой пакетов, управлением сервисами и ответами на вопросы.

Ты имеешь доступ к следующим инструментам:
- execute_command: выполнить команду в системе (только безопасные или с подтверждением)
- search_docs: поиск по документации Arch Wiki и личным заметкам (RAG)
- get_time: узнать текущее время
- smart_home: управление умным домом через MQTT

Правила:
1. Всегда отвечай на русском языке.
2. Если不确定 — спрашивай подтверждение перед выполнением команд.
3. Не используй опасные команды (rm, dd, и т.д.).
4. Если запрос касается Arch Linux — обращайся к RAG для точной информации.
5. Отвечай кратко и по делу.

"""

# Sentence boundary regex for streaming TTS
SENTENCE_END_RE = r'[.!?…]+\s*'
