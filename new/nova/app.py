"""
NOVA Voice Assistant — Main entry point.

Full pipeline: STT → RAG → LLM → TTS (with tool execution)
with secure command execution and semantic document search.

TTS runs in background and can be interrupted by new STT.
"""

import os
import sys
import ctypes

# Fix CUDA 12/13 library mismatch for CTranslate2 (used by faster-whisper).
_cuda_lib_dir = os.path.expanduser(
    "~/.conda/envs/NOVA/lib/python3.10/site-packages/nvidia/cu13/lib"
)
for lib in ("libcublas.so.13", "libcublasLt.so.13"):
    try:
        ctypes.CDLL(os.path.join(_cuda_lib_dir, lib))
    except Exception:
        pass

_ld = os.environ.get("LD_LIBRARY_PATH", "")
os.environ["LD_LIBRARY_PATH"] = f"{_cuda_lib_dir}:{_ld}"

import asyncio
import logging
import re

from nova.config import SYSTEM_PROMPT, SENTENCE_END_RE
from nova.components.stt import STT
from nova.components.tts import TTS
from nova.components.llm import LLM
from nova.rag.rag_adapter import RAGAdapter
from nova.tools.tool_registry import ToolRegistry, ToolCall
from nova.security.command_executor import CommandExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("nova.app")


class NOVAAssistant:
    """Main assistant orchestrating the voice pipeline."""

    def __init__(self):
        logger.info("Initializing NOVA Assistant...")

        self.llm = LLM()
        self.tts = TTS()
        self.stt = STT()

        self.command_executor = CommandExecutor()
        self.rag = RAGAdapter()
        self.tool_registry = ToolRegistry(
            command_executor=self.command_executor,
            rag_adapter=self.rag,
        )

        self.history: list[dict[str, str]] = []

        # Single TTS task tracker — replaced, not accumulated
        self._current_tts: asyncio.Task | None = None

        logger.info("NOVA Assistant initialized")

    async def initialize_rag(self):
        await self.rag.build_index()
        logger.info(f"RAG index: {self.rag.get_stats()}")

    async def warmup(self):
        logger.info("Warming up models...")
        logger.info("  LLM...")
        for _ in self.llm.generate_stream(
            self.llm.build_messages("ok"), max_tokens=5
        ):
            pass
        logger.info("  LLM done")

        logger.info("  TTS...")
        self.tts.speak("Готово.")
        logger.info("  TTS done")

        logger.info("  RAG embedding...")
        self.rag.search("тест", top_k=1)
        logger.info("  RAG done")

        logger.info("All models warmed up")

    def _cancel_tts(self):
        """Cancel any pending TTS task and abort playback immediately."""
        if self._current_tts is not None:
            self._current_tts.cancel()
            self._current_tts = None
        self.tts.abort()

    async def _wait_tts_done(self):
        """Wait for the current TTS task to finish (cleanly)."""
        if self._current_tts is not None:
            try:
                await self._current_tts
            except asyncio.CancelledError:
                pass
            self._current_tts = None

    def _speak_async(self, text: str):
        """Start TTS playback as a tracked task."""
        self._current_tts = asyncio.create_task(self.tts.speak_async(text))

    def _clean_thinking(self, text: str) -> str:
        return re.sub(r"<thinking>[\s\S]*?</thinking>", "", text)

    def _is_sentence_end(self, text: str) -> bool:
        tail = text[-50:] if len(text) > 50 else text
        return bool(re.search(SENTENCE_END_RE, tail))

    async def _process_llm_stream(self, messages: list[dict]) -> tuple[str, str | None]:
        """
        Stream LLM output → send to TTS sentence-by-sentence.
        Detect tool calls in JSON and execute immediately (recursive).
        TTS runs in background — caller must cancel before next turn.
        """
        full_output = ""
        sentence_buffer = ""
        json_buffer = ""
        is_thinking = False

        for chunk in self.llm.generate_stream(messages):
            if not chunk:
                continue

            # Skip thinking blocks
            if "<think>" in chunk:
                is_thinking = True
                continue
            if "</think>" in chunk:
                is_thinking = False
                continue
            if is_thinking:
                continue

            chunk = self._clean_thinking(chunk)

            # Tool call detection via JSON buffer
            if "{" in chunk or json_buffer:
                json_buffer += chunk
                try:
                    data = __import__("json").loads(json_buffer)
                    tool_call = self.tool_registry.parse_tool_call_from_json(json_buffer)
                    if tool_call:
                        print(f"\n🔧 Executing tool: {tool_call.name}")
                        # Cancel TTS before tool execution
                        self._cancel_tts()

                        result = await self.tool_registry.execute_tool(tool_call)
                        if result.output:
                            print(f"🔧 Result: {result.output[:100]}")

                        # Wait for TTS to fully stop
                        await self._wait_tts_done()

                        # Pop the partial assistant message
                        if self.history and self.history[-1].get("role") == "assistant":
                            self.history.pop()

                        self.history.append({
                            "role": "tool",
                            "content": result.output,
                        })
                        return await self._process_llm_stream([
                            {"role": "system", "content": "Результат выполнения получен. Объясни кратко."},
                            *self.history[-6:],
                        ])

                except __import__("json").JSONDecodeError:
                    pass

            # Print token
            print(chunk, end="", flush=True)
            sentence_buffer += chunk

            # Sentence boundary → send to TTS
            if self._is_sentence_end(sentence_buffer):
                tts_text = sentence_buffer.strip()
                if tts_text:
                    self._speak_async(tts_text)
                sentence_buffer = ""

            full_output += chunk

        # Flush remaining
        if sentence_buffer.strip():
            self._speak_async(sentence_buffer.strip())

        return full_output, None

    async def handle_conversation_turn(self, user_input: str):
        """Process one turn: RAG → LLM → TTS."""
        logger.info(f"User: {user_input}")

        rag_context = self.rag.format_context(user_input)
        augmented = user_input
        if rag_context:
            augmented = f"Контекст из документации:\n{rag_context}\n\nЗапрос пользователя: {user_input}"

        messages = self.llm.build_messages(
            user_input=augmented,
            system_prompt=SYSTEM_PROMPT,
            history=self.history,
        )

        logger.info("Generating LLM response...")
        print("LLM: ", end="", flush=True)
        full_output, tool_result = await self._process_llm_stream(messages)
        print()  # newline after output

        if tool_result is None:
            self.history.append({"role": "assistant", "content": full_output})

        self.history = self.llm.trim_history(self.history)

    async def run(self):
        """Main loop."""
        await self.initialize_rag()
        await self.warmup()

        greeting = "Привет! Я Нанасаки Ай, твой голосовой ассистент. Чем могу помочь?"
        print(f"\n🤖 NOVA: {greeting}")
        self._speak_async(greeting)
        await self._wait_tts_done()

        try:
            while True:
                # Wait for TTS to finish so mic doesn't pick up TTS audio
                await self._wait_tts_done()

                # Listen for user speech
                logger.info("Listening for user input...")
                user_input = await self.stt.listen_async()

                if not user_input or len(user_input.strip()) < 2:
                    logger.debug("Empty input, skipping")
                    continue

                # Respond (TTS runs in background, next iteration will wait for it)
                await self.handle_conversation_turn(user_input)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self._cancel_tts()
            self.stt.close()
            self.tts.close()
            logger.info("NOVA stopped")


def main():
    assistant = NOVAAssistant()
    try:
        asyncio.run(assistant.run())
    except KeyboardInterrupt:
        print("\n👋 NOVA: До встречи!")


if __name__ == "__main__":
    main()
