"""
Secure command executor with sandboxing and confirmation.
Supports bubblewrap (bwrap) and firejail sandboxes.
"""

import asyncio
import logging
import shutil
from dataclasses import dataclass

from nova.config import SANDBOX_TOOL
from nova.security.command_validator import (
    CommandValidationResult,
    CommandRiskLevel,
    validate_command,
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int
    confirmation_given: bool = False


class ConfirmationRequired(Exception):
    """Raised when a command needs user confirmation."""

    def __init__(self, command: list[str], validation: CommandValidationResult):
        self.command = command
        self.validation = validation
        super().__init__(f"Confirmation needed for: {' '.join(command)}")


class CommandExecutor:
    """
    Executes shell commands securely with:
    - Validation against allowlist/blocklist
    - Sandboxing via bubblewrap or firejail
    - User confirmation for medium-risk commands
    - Audit logging
    """

    def __init__(self, auto_confirm: bool = False):
        """
        Args:
            auto_confirm: If True, automatically approves commands
                          that need confirmation (use with caution).
        """
        self.auto_confirm = auto_confirm
        self._audit_log: list[dict] = []
        self._sandbox_available: bool | None = None

    def _check_sandbox(self) -> bool:
        """Check if the sandbox tool is available."""
        if self._sandbox_available is not None:
            return self._sandbox_available
        self._sandbox_available = shutil.which(SANDBOX_TOOL) is not None
        if not self._sandbox_available:
            logger.warning(
                f"Sandbox tool '{SANDBOX_TOOL}' not found. "
                "Commands will run without sandboxing."
            )
        return self._sandbox_available

    def _build_sandbox_command(self, command: list[str]) -> list[str]:
        """Wrap a command in the sandbox."""
        if SANDBOX_TOOL == "bwrap":
            # Minimal bubblewrap sandbox with read-only filesystem
            return [
                "bwrap",
                "--ro-bind", "/", "/",
                "--dev", "/dev",
                "--proc", "/proc",
                "--dir", "/tmp",
                "--unshare-all",
                "--share-net",  # keep network access
                "--die-with-parent",
                "--",
            ] + command
        elif SANDBOX_TOOL == "firejail":
            return ["firejail", "--quiet", "--"] + command
        else:
            logger.warning(f"Unknown sandbox tool: {SANDBOX_TOOL}, running raw command")
            return command

    async def confirm_command(self, command: list[str], validation: CommandValidationResult) -> bool:
        """
        Ask user for confirmation in the terminal.
        Returns True if confirmed, False otherwise.
        """
        if self.auto_confirm:
            logger.info(f"Auto-confirming: {' '.join(command)}")
            return True

        print(f"\n⚠️  COMMAND NEEDS CONFIRMATION")
        print(f"   Risk: {validation.risk_level.value}")
        print(f"   Reason: {validation.reason}")
        print(f"   Command: {' '.join(command)}")
        print()

        # Use asyncio.to_thread for blocking input()
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None, lambda: input("Execute? (yes/no): ").strip().lower()
        )
        return answer in ("yes", "y")

    async def execute(
        self,
        command: list[str],
        timeout: int = 30,
        use_sandbox: bool = True,
    ) -> ExecutionResult:
        """
        Validate and execute a command.

        Args:
            command: List of command arguments (e.g. ["ls", "-la"])
            timeout: Max execution time in seconds
            use_sandbox: Whether to use sandboxing

        Returns:
            ExecutionResult with stdout, stderr, and return code
        """
        # Validate
        validation = validate_command(command)

        if not validation.allowed:
            logger.error(f"Command blocked: {validation.reason}")
            self._audit({
                "command": command,
                "action": "BLOCKED",
                "reason": validation.reason,
            })
            return ExecutionResult(
                success=False, stdout="", stderr=validation.reason, returncode=-1
            )

        # Confirmation
        if validation.risk_level == CommandRiskLevel.NEEDS_CONFIRMATION:
            confirmed = await self.confirm_command(command, validation)
            if not confirmed:
                logger.info(f"User declined: {' '.join(command)}")
                self._audit({
                    "command": command,
                    "action": "DECLINED",
                })
                return ExecutionResult(
                    success=False,
                    stdout="",
                    stderr="Command declined by user",
                    returncode=-1,
                    confirmation_given=False,
                )

        # Sandbox
        if use_sandbox and self._check_sandbox():
            exec_command = self._build_sandbox_command(validation.sanitized_command)
        else:
            exec_command = validation.sanitized_command

        logger.info(f"Executing: {' '.join(exec_command)}")
        self._audit({
            "command": command,
            "sandbox": use_sandbox and self._sandbox_available,
            "action": "EXECUTED",
        })

        # Execute
        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            result = ExecutionResult(
                success=(proc.returncode == 0 or validation.risk_level == CommandRiskLevel.NEEDS_CONFIRMATION),
                stdout=stdout.decode("utf-8", errors="replace").strip(),
                stderr=stderr.decode("utf-8", errors="replace").strip(),
                returncode=proc.returncode,
                confirmation_given=(validation.risk_level == CommandRiskLevel.NEEDS_CONFIRMATION),
            )
            logger.debug(
                f"Return code: {result.returncode}, "
                f"stdout: {result.stdout[:100]!r}"
            )
            return result
        except asyncio.TimeoutError:
            proc.kill()
            msg = f"Command timed out after {timeout}s"
            logger.error(msg)
            return ExecutionResult(
                success=False, stdout="", stderr=msg, returncode=-1
            )
        except Exception as e:
            msg = f"Execution error: {e}"
            logger.error(msg)
            return ExecutionResult(
                success=False, stdout="", stderr=msg, returncode=-1
            )

    def _audit(self, entry: dict):
        """Log an audit entry."""
        import time
        entry["timestamp"] = time.time()
        self._audit_log.append(entry)
        logger.info(f"AUDIT: {entry}")

    def get_audit_log(self) -> list[dict]:
        """Return the audit log."""
        return list(self._audit_log)
