"""
LLM module using llama-cpp-python.
Handles model loading, streaming generation, and chat history management.
"""

import logging
from llama_cpp import Llama

from nova.config import (
    LLM_MODEL_PATH,
    LLM_CONTEXT_LENGTH,
    LLM_GPU_LAYERS,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


class LLM:
    """
    LLM wrapper for llama-cpp-python.

    Provides streaming chat completion with chat history management.
    """

    def __init__(self, model_path: str = LLM_MODEL_PATH):
        logger.info(
            "Loading LLM model: %s (context=%d, gpu_layers=%d)",
            model_path,
            LLM_CONTEXT_LENGTH,
            LLM_GPU_LAYERS,
        )
        self._llm = Llama(
            model_path=model_path,
            n_ctx=LLM_CONTEXT_LENGTH,
            n_gpu_layers=LLM_GPU_LAYERS,
            verbose=False,
            # Chat template settings for Qwen3
            chat_format="chatml",
        )
        logger.info("LLM model loaded successfully")

    def generate_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = LLM_TEMPERATURE,
        max_tokens: int = LLM_MAX_TOKENS,
    ):
        """
        Generate a streaming chat completion.

        Yields content chunks as they are generated.

        Args:
            messages: Chat history in OpenAI format:
                     [{"role": "user", "content": "..."}, ...]
            temperature: Sampling temperature
            max_tokens: Max tokens to generate

        Yields:
            str: Content chunks from the model
        """
        stream = self._llm.create_chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        for chunk in stream:
            # Extract content from chat completion chunk
            choices = chunk.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})
            content = delta.get("content", "")
            if content:
                yield content

    def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float = LLM_TEMPERATURE,
        max_tokens: int = LLM_MAX_TOKENS,
    ) -> str:
        """
        Generate a full (non-streaming) chat completion.

        Args:
            messages: Chat history in OpenAI format
            temperature: Sampling temperature
            max_tokens: Max tokens to generate

        Returns:
            str: Full response text
        """
        response = self._llm.create_chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        choices = response.get("choices", [])
        if not choices:
            return ""

        return choices[0].get("message", {}).get("content", "")

    @staticmethod
    def build_messages(
        user_input: str,
        system_prompt: str = SYSTEM_PROMPT,
        history: list[dict] | None = None,
    ) -> list[dict[str, str]]:
        """
        Build the messages list for a chat completion.

        Args:
            user_input: Current user input
            system_prompt: System prompt (optional, defaults to config)
            history: Previous conversation history

        Returns:
            List of message dicts in OpenAI format
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": user_input})
        return messages

    @staticmethod
    def trim_history(
        history: list[dict],
        max_messages: int = 20,
        max_tokens: int = LLM_CONTEXT_LENGTH * 0.8,
    ) -> list[dict]:
        """
        Trim conversation history to prevent context overflow.

        Args:
            history: Full conversation history
            max_messages: Maximum number of messages to keep
            max_tokens: Approximate max tokens (80% of context)

        Returns:
            Trimmed history
        """
        if len(history) <= max_messages:
            return history

        # Keep the most recent messages
        return history[-max_messages:]
