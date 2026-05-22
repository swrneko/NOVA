"""
Tool registry — manages all available tools for the LLM.
Provides function calling schema, execution, and result formatting.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from nova.security.command_executor import CommandExecutor, ExecutionResult
from nova.rag.rag_adapter import RAGAdapter

logger = logging.getLogger(__name__)


@dataclass
class ToolParam:
    """Describes a single tool parameter."""
    name: str
    type: str  # "string", "boolean", "integer", "number"
    description: str
    required: bool = True


@dataclass
class ToolDefinition:
    """Full definition of a tool for LLM function calling."""
    name: str
    description: str
    parameters: list[ToolParam] = field(default_factory=list)
    handler: Callable | None = None
    category: str = "general"  # "system", "smart_home", "info", "rag"


@dataclass
class ToolCall:
    """Represents a parsed tool call from the LLM."""
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Result of a tool execution."""
    tool_name: str
    success: bool
    output: str
    requires_confirmation: bool = False


class ToolRegistry:
    """
    Central registry of all available tools.

    Tools are registered with their JSON Schema for LLM function calling,
    and their handler function for execution.
    """

    def __init__(
        self,
        command_executor: CommandExecutor | None = None,
        rag_adapter: RAGAdapter | None = None,
    ):
        self._tools: dict[str, ToolDefinition] = {}
        self.command_executor = command_executor or CommandExecutor()
        self.rag_adapter = rag_adapter

        # Register built-in tools
        self._register_builtin_tools()

    def register(self, tool: ToolDefinition):
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_tool_schemas(self) -> list[dict]:
        """
        Generate JSON Schema definitions for all tools.
        Used for LLM function calling / tool_use format.
        """
        schemas = []
        for tool in self._tools.values():
            properties = {}
            required = []
            for param in tool.parameters:
                properties[param.name] = {
                    "type": param.type,
                    "description": param.description,
                }
                if param.required:
                    required.append(param.name)

            schema = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
            schemas.append(schema)
        return schemas

    def get_tool_prompt(self) -> str:
        """
        Generate a text description of all tools for the system prompt.
        Useful for models that don't support native function calling.
        """
        parts = ["Доступные инструменты:"]
        for tool in self._tools.values():
            params_str = ", ".join(
                f"{p.name}: {p.type}" for p in tool.parameters
            )
            parts.append(
                f"- {tool.name}({params_str}): {tool.description}"
            )
        return "\n".join(parts)

    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """
        Execute a tool call and return the result.

        Args:
            tool_call: Parsed tool call with name and arguments

        Returns:
            ToolResult with the output
        """
        tool = self._tools.get(tool_call.name)
        if not tool or not tool.handler:
            return ToolResult(
                tool_name=tool_call.name,
                success=False,
                output=f"Unknown tool: {tool_call.name}",
            )

        try:
            output = await tool.handler(**tool_call.arguments)
            return ToolResult(
                tool_name=tool_call.name,
                success=True,
                output=str(output),
            )
        except Exception as e:
            logger.error(f"Tool execution error [{tool_call.name}]: {e}")
            return ToolResult(
                tool_name=tool_call.name,
                success=False,
                output=f"Ошибка выполнения: {e}",
            )

    def _register_builtin_tools(self):
        """Register all built-in tools."""

        # --- execute_command ---
        async def _execute_command(command: list[str]) -> str:
            result: ExecutionResult = await self.command_executor.execute(command)
            if result.stderr:
                return f"stderr: {result.stderr}\nstdout: {result.stdout}"
            return result.stdout

        self.register(ToolDefinition(
            name="execute_command",
            description="Выполнить команду в системе. Команда передаётся как список аргументов.",
            parameters=[
                ToolParam(
                    name="command",
                    type="array",
                    description="Список аргументов команды, например: ['pacman', '-S', 'htop']",
                    required=True,
                ),
            ],
            handler=_execute_command,
            category="system",
        ))

        # --- search_docs ---
        async def _search_docs(query: str) -> str:
            if not self.rag_adapter:
                return "RAG не настроен. Индекс документов пуст."
            context = self.rag_adapter.format_context(query)
            if not context:
                return "Ничего не найдено в документации по запросу."
            return f"Найдено в документации:\n{context}"

        self.register(ToolDefinition(
            name="search_docs",
            description="Поиск по документации Arch Linux и личным заметкам.",
            parameters=[
                ToolParam(
                    name="query",
                    type="string",
                    description="Поисковый запрос",
                    required=True,
                ),
            ],
            handler=_search_docs,
            category="rag",
        ))

        # --- get_time ---
        async def _get_time() -> str:
            from datetime import datetime
            now = datetime.now()
            hours = now.hour
            minutes = now.minute

            # Russian time formatting
            if hours == 0:
                hour_str = "полночь"
            elif hours < 6:
                hour_str = "ночь"
            elif hours < 12:
                hour_str = f"{hours} утра"
            elif hours == 12:
                hour_str = "полдень"
            elif hours < 18:
                hour_str = f"{hours - 12} дня"
            else:
                hour_str = f"{hours - 12} вечера"

            return f"Сейчас {minutes} минут {hour_str}"

        self.register(ToolDefinition(
            name="get_time",
            description="Узнать текущее время.",
            parameters=[],
            handler=_get_time,
            category="info",
        ))

    def parse_tool_call_from_json(self, text: str) -> ToolCall | None:
        """
        Parse a tool call from LLM JSON output.

        Looks for JSON objects containing "name"/"tool" or "action" fields
        with arguments.
        """
        # Try to find JSON in the text
        text = text.strip()

        # Look for code block JSON
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()

        # Try to find JSON object
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx == -1 or end_idx == -1:
            return None

        json_str = text[start_idx:end_idx + 1]
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        # Extract tool name and arguments
        tool_name = data.get("name") or data.get("tool") or data.get("action")
        if not tool_name:
            return None

        arguments = data.get("arguments") or data.get("args") or data.get("parameters") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}

        return ToolCall(name=tool_name, arguments=arguments)
