import httpx
import websockets
import json
import asyncio
from typing import Callable, Optional

SERVER_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws/chat"

class NetworkClient:
    def __init__(self):
        self.token = None
        self.ws = None
        self.username = None

    async def register(self, username, password):
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{SERVER_URL}/api/register", json={"username": username, "password": password})
            if response.status_code == 200:
                return True, response.json()
            return False, response.json().get("detail", "Unknown error")

    async def login(self, username, password):
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{SERVER_URL}/api/login", json={"username": username, "password": password})
            if response.status_code == 200:
                self.username = username
                return True, response.json()
            return False, response.json().get("detail", "Unknown error")

    async def verify_2fa(self, code):
        if not self.username:
            return False, "Not logged in"
            
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{SERVER_URL}/api/verify-2fa", json={"username": self.username, "code": code})
            if response.status_code == 200:
                self.token = response.json().get("access_token")
                return True, "Success"
            return False, response.json().get("detail", "Unknown error")

    async def connect_ws(self, on_message: Callable, on_audio: Callable):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        
        try:
            self.ws = await websockets.connect(WS_URL, additional_headers=headers)
            
            # Фоновый цикл чтения сообщений от сервера
            while True:
                message = await self.ws.recv()
                if isinstance(message, bytes):
                    on_audio(message)
                elif isinstance(message, str):
                    try:
                        data = json.loads(message)
                        on_message(data)
                    except json.JSONDecodeError:
                        pass
                        
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"WebSocket error: {e}")

    async def send_audio(self, audio_bytes: bytes):
        if self.ws:
            try:
                await self.ws.send(audio_bytes)
            except Exception as e:
                print(f"Error sending audio: {e}")

    async def send_abort(self):
        if self.ws:
            try:
                await self.ws.send(json.dumps({"type": "abort"}))
            except Exception as e:
                print(f"Error sending abort: {e}")
