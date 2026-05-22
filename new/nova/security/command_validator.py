"""
Command validation and security layer.
Ensures that only safe, approved commands can be executed.
"""

import re
import logging
from dataclasses import dataclass
from enum import Enum

from nova.config import (
    SAFE_COMMANDS,
    REQUIRES_CONFIRMATION,
    BLOCKED_COMMANDS,
    DANGEROUS_PATTERNS,
)

logger = logging.getLogger(__name__)


class CommandRiskLevel(Enum):
    SAFE = "safe"
    NEEDS_CONFIRMATION = "needs_confirmation"
    BLOCKED = "blocked"


@dataclass
class CommandValidationResult:
    allowed: bool
    risk_level: CommandRiskLevel
    reason: str
    sanitized_command: list[str] | None = None


def _compile_dangerous_patterns() -> list[re.Pattern]:
    return [re.compile(p) for p in DANGEROUS_PATTERNS]


_DANGEROUS_RE = _compile_dangerous_patterns()


def check_dangerous_patterns(command_str: str) -> list[str]:
    """Check if a command string contains dangerous patterns."""
    found = []
    for pattern in _DANGEROUS_RE:
        if pattern.search(command_str):
            found.append(pattern.pattern)
    return found


def classify_command(command: list[str] | str) -> CommandRiskLevel:
    """
    Classify a command as SAFE, NEEDS_CONFIRMATION, or BLOCKED.

    Accepts either a list of args (e.g. ["pacman", "-S", "htop"])
    or a string command.
    """
    if isinstance(command, list):
        cmd_str = " ".join(command)
    else:
        cmd_str = command.strip()

    if not cmd_str:
        return CommandRiskLevel.BLOCKED

    # Check blocked commands first
    for blocked in BLOCKED_COMMANDS:
        if cmd_str.startswith(blocked) or cmd_str == blocked:
            return CommandRiskLevel.BLOCKED

    # Check dangerous patterns
    patterns_found = check_dangerous_patterns(cmd_str)
    if patterns_found:
        logger.warning(f"Command contains dangerous patterns: {patterns_found}")
        return CommandRiskLevel.BLOCKED

    # Check safe commands
    for safe in SAFE_COMMANDS:
        if cmd_str.startswith(safe) or cmd_str == safe:
            return CommandRiskLevel.SAFE

    # Check confirmation-required commands
    for req in REQUIRES_CONFIRMATION:
        if cmd_str.startswith(req) or cmd_str == req:
            return CommandRiskLevel.NEEDS_CONFIRMATION

    # Unknown commands are blocked by default
    logger.info(f"Unknown command not in any list: {cmd_str}")
    return CommandRiskLevel.BLOCKED


def sanitize_command(command: list[str]) -> list[str]:
    """
    Sanitize command arguments by removing dangerous characters
    from individual arguments.
    """
    sanitized = []
    for arg in command:
        # Remove null bytes
        arg = arg.replace("\x00", "")
        # Reject args with embedded newlines
        if "\n" in arg or "\r" in arg:
            raise ValueError(f"Command argument contains newline: {arg!r}")
        sanitized.append(arg)
    return sanitized


def validate_command(command: list[str]) -> CommandValidationResult:
    """
    Full validation pipeline for a command.

    Returns a CommandValidationResult with the decision and reason.
    """
    cmd_str = " ".join(command)

    # Step 1: Check empty
    if not command:
        return CommandValidationResult(
            allowed=False,
            risk_level=CommandRiskLevel.BLOCKED,
            reason="Empty command",
        )

    # Step 2: Sanitize
    try:
        sanitized = sanitize_command(command)
    except ValueError as e:
        return CommandValidationResult(
            allowed=False,
            risk_level=CommandRiskLevel.BLOCKED,
            reason=str(e),
        )

    # Step 3: Classify
    risk = classify_command(command)

    if risk == CommandRiskLevel.BLOCKED:
        return CommandValidationResult(
            allowed=False,
            risk_level=risk,
            reason=f"Command '{cmd_str}' is blocked for security reasons",
        )

    if risk == CommandRiskLevel.NEEDS_CONFIRMATION:
        return CommandValidationResult(
            allowed=True,
            risk_level=risk,
            reason=f"Command '{cmd_str}' requires user confirmation",
            sanitized_command=sanitized,
        )

    return CommandValidationResult(
        allowed=True,
        risk_level=risk,
        reason=f"Command '{cmd_str}' is safe to execute",
        sanitized_command=sanitized,
    )
