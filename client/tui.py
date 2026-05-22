from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal, VerticalScroll
from textual.widgets import Header, Footer, Input, Button, Label, Static, Select, TabbedContent, TabPane
from textual.screen import Screen
from textual.events import Key
from textual import work

from client.network import NetworkClient
from client.audio_io import AudioIO

import asyncio
import time

# --- ВИДЖЕТ: СООБЩЕНИЕ В ЧАТЕ ---
class MessageBubble(Static):
    def __init__(self, sender: str, text: str, **kwargs):
        classes = "user-bubble" if sender == "You" else "nova-bubble"
        super().__init__(classes=classes, **kwargs)
        self.sender = sender
        self.text = text

    def compose(self) -> ComposeResult:
        if self.sender == "You":
            yield Label("[bold green]You:[/bold green]", classes="msg-header")
        else:
            yield Label("[bold magenta]NOVA:[/bold magenta]", classes="msg-header")
        yield Label(self.text, classes="msg-text")

    def update_text(self, text: str):
        self.text = text
        self.query_one(".msg-text", Label).update(text)


# --- ГЛАВНЫЙ ЭКРАН С ВКЛАДКАМИ ---
class MainScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        
        # Получаем аудио-устройства
        inputs, outputs = AudioIO.get_devices()
        in_options = [(item["name"], item["id"]) for item in inputs]
        out_options = [(item["name"], item["id"]) for item in outputs]

        with TabbedContent(id="tabs"):
            # Вкладка 1: Чат (без динамических невидимых контейнеров, всегда отображается)
            with TabPane("Chat 🌌", id="tab-chat"):
                yield VerticalScroll(id="message-list")
                yield Static("READY. Press [SPACE] to start/stop recording.", id="status-bar")

            # Вкладка 2: Аккаунты
            with TabPane("Accounts 👤", id="tab-accounts"):
                with Vertical(id="accounts-container"):
                    # Блок 1: Вход / Регистрация
                    with Vertical(id="acc-unauthenticated-pane"):
                        yield Label("Accounts & Authentication", classes="section-title")
                        yield Input(placeholder="Username", id="acc-username")
                        yield Input(placeholder="Password", password=True, id="acc-password")
                        with Horizontal(classes="buttons-row"):
                            yield Button("Login", id="acc-btn-login", variant="primary")
                            yield Button("Register", id="acc-btn-register")
                        yield Label("", id="acc-status")

                    # Блок 2: Ввод 2FA
                    with Vertical(id="acc-2fa-pane"):
                        yield Label("Two-Factor Authentication", classes="section-title")
                        yield Label("Add this key to Aegis/Google Authenticator manually:")
                        yield Static("", id="acc-2fa-secret")
                        yield Input(placeholder="000000", id="acc-2fa-code")
                        yield Button("Verify 2FA", id="acc-btn-verify", variant="primary")
                        yield Label("", id="acc-2fa-status")

                    # Блок 3: Уже авторизован
                    with Vertical(id="acc-authenticated-pane"):
                        yield Label("Account Profile", classes="section-title")
                        yield Label("", id="acc-profile-info")
                        yield Button("Logout / Switch Account", id="acc-btn-logout", variant="error")

            # Вкладка 3: Настройки звука
            with TabPane("Audio Settings 🎙️", id="tab-audio"):
                with Vertical(id="settings-container"):
                    yield Label("Audio Settings", classes="section-title")
                    yield Label("Microphone (Input):")
                    yield Select(options=in_options, id="select-input")
                    yield Label("Speaker (Output):")
                    yield Select(options=out_options, id="select-output")
                    yield Button("Apply Audio Settings", id="btn-apply-audio", variant="primary")
                    yield Label("", id="audio-settings-status")

        yield Footer()

    def on_mount(self) -> None:
        # Ссылки на элементы
        self.tabs = self.query_one("#tabs", TabbedContent)
        self.message_list = self.query_one("#message-list", VerticalScroll)
        self.status_bar = self.query_one("#status-bar", Static)
        
        # Настройка видимости блоков авторизации
        self.query_one("#acc-2fa-pane").display = False
        self.query_one("#acc-authenticated-pane").display = False
        
        # Выводим приветственное сообщение в чат
        self.message_list.mount(MessageBubble("System", "[bold yellow]Welcome to NOVA![/bold yellow]\nPlease register or log in under the [bold cyan]Accounts[/bold cyan] tab first to start chatting."))
        
        # Переменные состояния
        self.is_recording = False
        self.last_toggle_time = 0.0
        self.current_response_text = ""
        self.current_bubble = None

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        net: NetworkClient = self.app.net  # type: ignore
        
        # --- ОБРАБОТКА ВХОДА / РЕГИСТРАЦИИ ---
        if event.button.id == "acc-btn-login":
            username = self.query_one("#acc-username").value
            password = self.query_one("#acc-password").value
            status = self.query_one("#acc-status")
            
            if not username or not password:
                status.update("[red]Enter username and password[/red]")
                return
                
            status.update("Logging in...")
            ok, res = await net.login(username, password)
            if ok:
                self.app.current_login_user = username
                # Прячем вход, показываем только ввод 2FA кода
                self.query_one("#acc-unauthenticated-pane").display = False
                self.query_one("#acc-2fa-pane").display = True
                self.query_one("#acc-2fa-secret").display = False # Секрет при входе не нужен
            else:
                status.update(f"[red]Error: {res}[/red]")

        elif event.button.id == "acc-btn-register":
            username = self.query_one("#acc-username").value
            password = self.query_one("#acc-password").value
            status = self.query_one("#acc-status")
            
            if not username or not password:
                status.update("[red]Enter username and password[/red]")
                return
                
            status.update("Registering...")
            ok, res = await net.register(username, password)
            if ok:
                self.app.current_login_user = username
                secret = res.get("totp_secret")
                
                # Показываем 2FA секрет
                self.query_one("#acc-unauthenticated-pane").display = False
                self.query_one("#acc-2fa-pane").display = True
                self.query_one("#acc-2fa-secret").display = True
                self.query_one("#acc-2fa-secret").update(f"[bold yellow]{secret}[/bold yellow]")
            else:
                status.update(f"[red]Error: {res}[/red]")

        # --- ПОДТВЕРЖДЕНИЕ 2FA ---
        elif event.button.id == "acc-btn-verify":
            code = self.query_one("#acc-2fa-code").value
            status = self.query_one("#acc-2fa-status")
            
            net.username = self.app.current_login_user
            status.update("Verifying...")
            ok, res = await net.verify_2fa(code)
            if ok:
                # Успешная авторизация!
                self.query_one("#acc-2fa-pane").display = False
                self.query_one("#acc-authenticated-pane").display = True
                self.query_one("#acc-profile-info").update(f"Logged in as: [bold cyan]{net.username}[/bold cyan]")
                
                # Выводим сообщение об успешном входе в чат
                self.message_list.mount(MessageBubble("System", f"[bold green]Connected as {net.username}! Press [SPACE] to start/stop voice recording.[/bold green]"))
                self.message_list.scroll_end()
                
                # Подключаемся к WebSocket
                self.connect_ws()
                
                # Автоматически переходим во вкладку чата!
                self.tabs.active = "tab-chat"
            else:
                status.update(f"[red]Invalid code: {res}[/red]")

        # --- ВЫХОД / СМЕНА АККАУНТА ---
        elif event.button.id == "acc-btn-logout":
            # Закрываем сокет
            if net.ws:
                await net.ws.close()
                net.ws = None
                
            net.token = None
            net.username = None
            self.app.current_login_user = None
            
            # Возвращаем UI в исходное состояние
            self.query_one("#acc-authenticated-pane").display = False
            self.query_one("#acc-unauthenticated-pane").display = True
            self.query_one("#acc-username").value = ""
            self.query_one("#acc-password").value = ""
            self.query_one("#acc-status").update("")
            
            # Очищаем историю чата на экране и выводим приветствие
            self.message_list.query(MessageBubble).remove()
            self.message_list.mount(MessageBubble("System", "[bold yellow]Welcome to NOVA![/bold yellow]\nPlease register or log in under the [bold cyan]Accounts[/bold cyan] tab first to start chatting."))

        # --- ПРИМЕНЕНИЕ НАСТРОЕК АУДИО ---
        elif event.button.id == "btn-apply-audio":
            input_id = self.query_one("#select-input").value
            output_id = self.query_one("#select-output").value
            status = self.query_one("#audio-settings-status")
            
            if not isinstance(input_id, int): input_id = None
            if not isinstance(output_id, int): output_id = None
            
            # Пересоздаем AudioIO с новыми девайсами
            if hasattr(self.app, "audio"):
                self.app.audio.stop()
                
            self.app.audio = AudioIO(input_device_index=input_id, output_device_index=output_id)
            status.update("[green]Audio settings applied successfully![/green]")

    def on_key(self, event: Key) -> None:
        if self.tabs.active == "tab-chat":
            net: NetworkClient = self.app.net # type: ignore
            if event.key == "space":
                if not net.token:
                    self.status_bar.update("[bold red]Please log in under the Accounts tab first![/bold red]")
                    return
                
                current_time = time.time()
                if current_time - self.last_toggle_time < 0.8:
                    return
                
                self.last_toggle_time = current_time
                if not self.is_recording:
                    self.start_recording()
                else:
                    self.run_worker(self.stop_recording())

    @work(exclusive=True)
    async def connect_ws(self):
        """Подключение к WebSocket на основном асинхронном цикле"""
        net: NetworkClient = self.app.net # type: ignore
        await net.connect_ws(self.handle_ws_message, self.handle_ws_audio)

    def handle_ws_message(self, data: dict):
        self._update_chat_ui(data)

    def _update_chat_ui(self, data: dict):
        t = data.get("type")
        if t == "info":
            bubble = MessageBubble("System", f"[yellow]Info: {data.get('message')}[/yellow]")
            self.message_list.mount(bubble)
            self.message_list.scroll_end()
        elif t == "text_user":
            # Добавляем сообщение пользователя
            bubble = MessageBubble("You", data.get("text"))
            self.message_list.mount(bubble)
            self.message_list.scroll_end()
        elif t == "text_chunk":
            # Накапливаем стриминг-чанки от LLM прямо в бабл чата!
            chunk = data.get("text", "")
            self.current_response_text += chunk
            
            if self.current_bubble is None:
                # Если бабл еще не создан - создаем его!
                self.current_bubble = MessageBubble("NOVA", self.current_response_text)
                self.message_list.mount(self.current_bubble)
            else:
                self.current_bubble.update_text(self.current_response_text)
                
            self.message_list.scroll_end()
        elif t == "done":
            # Завершили стриминг, сбрасываем указатели
            self.current_response_text = ""
            self.current_bubble = None

    def handle_ws_audio(self, audio_bytes: bytes):
        audio: AudioIO = self.app.audio # type: ignore
        audio.play_audio_bytes(audio_bytes)

    def start_recording(self) -> None:
        audio: AudioIO = self.app.audio # type: ignore
        net: NetworkClient = self.app.net # type: ignore
        self.is_recording = True
        self.status_bar.update("[bold red]RECORDING... (Press SPACE again to stop and send)[/bold red]")
        
        # Прерываем текущую озвучку на клиенте
        audio.abort_playback()
        
        # Посылаем сигнал прерывания (abort) на сервер
        self.run_worker(net.send_abort())
        
        audio.start_recording()

    async def stop_recording(self) -> None:
        audio: AudioIO = self.app.audio # type: ignore
        net: NetworkClient = self.app.net # type: ignore
        
        self.is_recording = False
        self.status_bar.update("[bold yellow]Processing (stopping recording)...[/bold yellow]")
        
        try:
            audio_bytes = audio.stop_recording()
            
            if audio_bytes:
                self.status_bar.update(f"[bold yellow]Sending {len(audio_bytes)} bytes to server...[/bold yellow]")
                await net.send_audio(audio_bytes)
            else:
                self.status_bar.update("[bold yellow]No audio recorded.[/bold yellow]")
        except Exception as e:
            bubble = MessageBubble("System", f"[red]Error while stopping/sending audio: {e}[/red]")
            self.message_list.mount(bubble)
            self.message_list.scroll_end()
        
        def reset_status():
            self.status_bar.update("READY. Press [SPACE] to start/stop recording.")
        self.set_timer(2.0, reset_status)


# --- ГЛАВНОЕ ПРИЛОЖЕНИЕ ---
class NovaApp(App):
    CSS = """
    TabbedContent {
        height: 1fr;
    }
    #chat-unauthenticated-pane {
        padding: 4;
        text-align: center;
    }
    #chat-welcome-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 2;
        color: cyan;
    }
    #chat-welcome-subtitle {
        text-align: center;
        color: $text-muted;
    }
    #chat-authenticated-pane {
        height: 100%;
    }
    #message-list {
        height: 1fr;
        border: solid green;
        background: $background;
        padding: 1;
    }
    #status-bar {
        height: 3;
        content-align: center middle;
        background: $boost;
        text-style: bold;
    }
    .section-title {
        text-align: center;
        text-style: bold;
        margin: 1 0;
        color: cyan;
    }
    #settings-container, #accounts-container {
        padding: 2;
        align: center middle;
    }
    #acc-unauthenticated-pane, #acc-2fa-pane, #acc-authenticated-pane {
        width: 60;
        align: center middle;
    }
    .buttons-row {
        align: center middle;
        height: auto;
        margin-top: 1;
    }
    #acc-2fa-secret {
        width: auto;
        height: 3;
        content-align: center middle;
        border: dashed yellow;
        margin: 1 0;
        padding: 0 2;
    }
    Input {
        margin: 1 0;
        width: 40;
    }
    Button {
        margin: 0 1;
    }
    Select {
        width: 40;
        margin-bottom: 2;
    }
    MessageBubble {
        background: $surface;
        border-left: tall magenta;
        margin: 1 2;
        padding: 1 2;
        height: auto;
        width: 1fr;
    }
    MessageBubble.user-bubble {
        border-left: tall green;
        background: $surface;
    }
    .msg-header {
        margin-bottom: 1;
        text-style: bold;
    }
    .msg-text {
        color: $text;
        width: 100%;
    }
    """

    def on_mount(self) -> None:
        self.net = NetworkClient()
        self.current_login_user = None
        # Инициализируем аудио по умолчанию
        self.audio = AudioIO(input_device_index=None, output_device_index=None)
        self.push_screen(MainScreen())

    def on_unmount(self) -> None:
        if hasattr(self, 'audio'):
            self.audio.stop()

if __name__ == "__main__":
    app = NovaApp()
    app.run()
