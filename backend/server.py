from fastapi import FastAPI
from backend.api.routes import router as api_router
from backend.api.ws_routes import router as ws_router
from backend.database.db import init_db

# Инициализируем БД
init_db()

app = FastAPI(title="NOVA API")

# Подключаем роуты
app.include_router(api_router, prefix="/api")
app.include_router(ws_router) # Без префикса, чтобы путь был /ws/chat

@app.get("/")
def read_root():
    return {"message": "NOVA Backend is running. Use TUI Client to connect."}

# Точка входа для запуска (для удобства)
if __name__ == "__main__":
    import uvicorn
    # ОТКЛЮЧЕНО reload=True. 
    # С тяжелыми моделями (Qwen) reload вызывает двойную загрузку в VRAM, 
    # из-за чего возникает ошибка OOM (Out Of Memory) при старте воркера.
    uvicorn.run("backend.server:app", host="0.0.0.0", port=8000, reload=False)
