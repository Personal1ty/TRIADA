import pytest

from app.schemas.enums import RiskPolicy
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


def test_safe_adapters_block_mutating_commands(tmp_path):
    assert GitTool(workspace=tmp_path).is_command_allowed(["git", "status"]) is True
    assert GitTool(workspace=tmp_path).is_command_allowed(["git", "commit"]) is False
    assert KubernetesReadOnlyTool(workspace=tmp_path).is_command_allowed(["kubectl", "get", "pods"]) is True
    assert KubernetesReadOnlyTool(workspace=tmp_path).is_command_allowed(["kubectl", "delete", "pod", "x"]) is False
    assert DockerTool(workspace=tmp_path).is_command_allowed(["docker", "ps"]) is True
    assert DockerTool(workspace=tmp_path).is_command_allowed(["docker", "run", "alpine"]) is False
