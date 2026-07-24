from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from app.contracts.swarm import SwarmContract


DEFAULT_SWARM_CONTRACT_PATH = Path(__file__).with_name("default_swarm_contract.json")


def load_swarm_contract(path: str | Path) -> SwarmContract:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return SwarmContract.model_validate(payload)


def load_default_swarm_contract() -> SwarmContract:
    resource = resources.files("app.contracts").joinpath("default_swarm_contract.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    return SwarmContract.model_validate(payload)
