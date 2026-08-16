import asyncio
import os
import stat
import sys
import textwrap

import pytest

from app.schemas.enums import RiskPolicy
from app.tools.apply_patch import ApplyPatchTool
from app.tools.base import ToolRequest, ensure_risk_allowed
from app.tools.docker import DockerTool
from app.tools.filesystem import FileSystemTool
from app.tools.git import GitTool
from app.tools.kubernetes import KubernetesReadOnlyTool
from app.tools.shell import ShellTool
from app.tools.terraform import TerraformPlanTool


@pytest.mark.asyncio
async def test_shell_tool_rejects_non_allowlisted_command(tmp_path):
    tool = ShellTool(allowlist={"echo"}, workspace=tmp_path)
    request = ToolRequest(command=["rm", "-rf", "/"], risk_policy=RiskPolicy.DESTRUCTIVE)
    with pytest.raises(PermissionError, match="not allowlisted"):
        await tool.execute(request)


@pytest.mark.asyncio
async def test_shell_tool_executes_allowlisted_command(tmp_path):
    tool = ShellTool(allowlist={"echo"}, workspace=tmp_path)
    result = await tool.execute(
        ToolRequest(command=["echo", "hello"], risk_policy=RiskPolicy.READ_ONLY)
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"


@pytest.mark.asyncio
async def test_shell_tool_uses_trusted_executable_not_workspace_path_hijack(tmp_path, monkeypatch):
    hijack_dir = tmp_path / "bin"
    hijack_dir.mkdir()
    fake_echo = hijack_dir / "echo"
    fake_echo.write_text("#!/bin/sh\necho hijacked\n")
    fake_echo.chmod(fake_echo.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{hijack_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    tool = ShellTool(allowlist={"echo"}, workspace=tmp_path)
    result = await tool.execute(
        ToolRequest(command=["echo", "hello"], risk_policy=RiskPolicy.READ_ONLY)
    )

    assert result.stdout.strip() == "hello"
    assert "hijacked" not in result.stdout


@pytest.mark.skipif(os.name != "posix", reason="process group cancellation is POSIX-specific")
@pytest.mark.asyncio
async def test_shell_tool_timeout_kills_process_group_children(tmp_path):
    python_name = os.path.basename(sys.executable)
    marker = tmp_path / "child-marker"
    child_code = (
        "import pathlib, time; "
        "time.sleep(0.5); "
        f"pathlib.Path({str(marker)!r}).write_text('child survived')"
    )
    parent_code = textwrap.dedent(
        f"""
        import subprocess
        import sys
        import time

        subprocess.Popen(
            [sys.executable, "-c", {child_code!r}],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(60)
        """
    )
    tool = ShellTool(
        allowlist={python_name},
        workspace=tmp_path,
        timeout_seconds=0.2,
        trusted_paths=[os.path.dirname(sys.executable)],
    )

    result = await tool.execute(
        ToolRequest(command=[python_name, "-c", parent_code], risk_policy=RiskPolicy.READ_ONLY)
    )
    assert result.timed_out is True
    await asyncio.sleep(0.8)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_high_risk_requires_approval_reference(tmp_path):
    tool = ShellTool(allowlist={"echo"}, workspace=tmp_path)
    request = ToolRequest(command=["echo", "write"], risk_policy=RiskPolicy.HIGH_RISK_WRITE)
    with pytest.raises(PermissionError, match="approval"):
        await tool.execute(request)


def test_terraform_plan_tool_blocks_apply(tmp_path):
    tool = TerraformPlanTool(workspace=tmp_path)
    assert tool.is_command_allowed(["terraform", "plan"]) is True
    assert tool.is_command_allowed(["terraform", "apply"]) is False


@pytest.mark.asyncio
async def test_shell_tool_rejects_working_dir_outside_workspace(tmp_path):
    tool = ShellTool(allowlist={"pwd"}, workspace=tmp_path)
    request = ToolRequest(
        command=["pwd"],
        working_dir=tmp_path.parent,
        risk_policy=RiskPolicy.READ_ONLY,
    )
    with pytest.raises(PermissionError, match="outside workspace"):
        await tool.execute(request)


@pytest.mark.asyncio
async def test_shell_tool_redacts_secret_stdout(tmp_path):
    tool = ShellTool(allowlist={"echo"}, workspace=tmp_path, secrets={"topsecret"})
    result = await tool.execute(
        ToolRequest(command=["echo", "topsecret"], risk_policy=RiskPolicy.READ_ONLY)
    )
    assert "topsecret" not in result.stdout
    assert "[REDACTED]" in result.stdout


def test_low_risk_write_requires_change_and_validation():
    with pytest.raises(PermissionError, match="expected_change"):
        ensure_risk_allowed(ToolRequest(command=["touch", "x"], risk_policy=RiskPolicy.LOW_RISK_WRITE))

    with pytest.raises(PermissionError, match="validation_command"):
        ensure_risk_allowed(
            ToolRequest(
                command=["touch", "x"],
                risk_policy=RiskPolicy.LOW_RISK_WRITE,
                expected_change="create x",
            )
        )


@pytest.mark.asyncio
async def test_filesystem_tool_rejects_path_traversal_outside_workspace(tmp_path):
    tool = FileSystemTool(workspace=tmp_path)
    request = ToolRequest(
        command=["read", "../secret.txt"],
        risk_policy=RiskPolicy.READ_ONLY,
    )
    with pytest.raises(PermissionError, match="outside workspace"):
        await tool.execute(request)


@pytest.mark.asyncio
async def test_filesystem_tool_rejects_write_with_read_only_policy(tmp_path):
    tool = FileSystemTool(workspace=tmp_path)
    request = ToolRequest(
        command=["write", "note.txt", "hello"],
        risk_policy=RiskPolicy.READ_ONLY,
    )
    with pytest.raises(PermissionError, match="write requires"):
        await tool.execute(request)


@pytest.mark.asyncio
async def test_filesystem_tool_redacts_and_caps_read_output(tmp_path):
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("Authorization: Bearer abc123\n" + ("x" * 128))
    tool = FileSystemTool(workspace=tmp_path, max_output_bytes=32)

    result = await tool.execute(
        ToolRequest(command=["read", "secret.txt"], risk_policy=RiskPolicy.READ_ONLY)
    )

    assert "abc123" not in result.stdout
    assert "[REDACTED]" in result.stdout
    assert "[TRUNCATED]" in result.stdout


def test_safe_adapters_block_mutating_commands(tmp_path):
    assert GitTool(workspace=tmp_path).is_command_allowed(["git", "status"]) is True
    assert GitTool(workspace=tmp_path).is_command_allowed(["git", "commit"]) is False
    assert (
        GitTool(workspace=tmp_path).is_command_allowed(
            ["git", "commit", "-m", "checkpoint"],
            risk_policy=RiskPolicy.HIGH_RISK_WRITE,
            approval_ref="operator",
        )
        is True
    )
    assert KubernetesReadOnlyTool(workspace=tmp_path).is_command_allowed(["kubectl", "get", "pods"]) is True
    assert KubernetesReadOnlyTool(workspace=tmp_path).is_command_allowed(["kubectl", "delete", "pod", "x"]) is False
    assert DockerTool(workspace=tmp_path).is_command_allowed(["docker", "ps"]) is True
    assert DockerTool(workspace=tmp_path).is_command_allowed(["docker", "run", "alpine"]) is False


def test_git_tool_blocks_execution_overrides(tmp_path):
    tool = GitTool(workspace=tmp_path)
    assert tool.is_command_allowed(["git", "diff", "--no-index", "/tmp/a", "/tmp/b"]) is False
    assert tool.is_command_allowed(["git", "diff", "--ext-diff"]) is False
    assert tool.is_command_allowed(["git", "diff", "--external-diff"]) is False
    assert tool.is_command_allowed(["git", "-c", "core.pager=cat", "status"]) is False
    assert tool.is_command_allowed(["git", "log", "--output=/tmp/outside-file"]) is False
    assert tool.is_command_allowed(["git", "log", "--pathspec-from-file=/tmp/outside-file"]) is False


def test_git_tool_requires_approval_for_write_commands(tmp_path):
    tool = GitTool(workspace=tmp_path)

    assert tool.is_command_allowed(["git", "add", "README.md"]) is False
    assert (
        tool.is_command_allowed(
            ["git", "add", "README.md"],
            risk_policy=RiskPolicy.HIGH_RISK_WRITE,
            approval_ref="operator",
        )
        is True
    )
    assert (
        tool.is_command_allowed(
            ["git", "push", "origin", "main"],
            risk_policy=RiskPolicy.HIGH_RISK_WRITE,
            approval_ref="operator",
        )
        is True
    )
    assert (
        tool.is_command_allowed(
            ["git", "add", "../outside.txt"],
            risk_policy=RiskPolicy.HIGH_RISK_WRITE,
            approval_ref="operator",
        )
        is False
    )


@pytest.mark.asyncio
async def test_apply_patch_tool_replaces_existing_file_text_after_approval(tmp_path):
    target = tmp_path / "README.md"
    target.write_text("old heading\nbody\n", encoding="utf-8")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = await tool.execute(
        ToolRequest(
            command=["apply_patch", "README.md", "old heading", "new heading"],
            risk_policy=RiskPolicy.HIGH_RISK_WRITE,
            approval_ref="operator",
        )
    )

    assert result.tool == "apply_patch"
    assert result.exit_code == 0
    assert target.read_text(encoding="utf-8") == "new heading\nbody\n"


@pytest.mark.asyncio
async def test_apply_patch_tool_rejects_patch_without_approval(tmp_path):
    (tmp_path / "README.md").write_text("old\n", encoding="utf-8")
    tool = ApplyPatchTool(workspace=tmp_path)

    with pytest.raises(PermissionError):
        await tool.execute(
            ToolRequest(
                command=["apply_patch", "README.md", "old", "new"],
                risk_policy=RiskPolicy.HIGH_RISK_WRITE,
            )
        )
