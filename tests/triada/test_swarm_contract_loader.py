from pathlib import Path

from app.contracts.loader import load_default_swarm_contract, load_swarm_contract
from app.contracts.swarm import AgentEndpoint


def test_pyproject_includes_default_contract_package_data():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.setuptools.package-data]" in pyproject
    assert '"app.contracts" = ["*.json"]' in pyproject


def test_load_default_swarm_contract():
    contract = load_default_swarm_contract()

    assert contract.contract_version == "1.0"
    assert len(contract.worker_auditor_pairs) == 3
    assert contract.swarm_scaling.default_pairs == 3
    assert any(
        route.source == AgentEndpoint.WORKER and route.target == AgentEndpoint.ASSIGNED_AUDITOR
        for route in contract.route_map
    )
    assert all(
        route.input_contract.version == "1.0" and route.output_contract.version == "1.0"
        for route in contract.route_map
    )


def test_load_swarm_contract_from_json_path(tmp_path: Path):
    source = Path("app/contracts/default_swarm_contract.json")
    target = tmp_path / "swarm.json"
    target.write_text(source.read_text())

    contract = load_swarm_contract(target)

    assert contract.contract_version == "1.0"
