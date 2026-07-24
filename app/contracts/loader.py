from __future__ import annotations

import json
from pathlib import Path

from app.contracts.swarm import SwarmContract


DEFAULT_SWARM_CONTRACT_PATH = Path(__file__).with_name("default_swarm_contract.json")


def load_swarm_contract(path: str | Path) -> SwarmContract:
    payload = json.loads(Path(path).read_text())
    return SwarmContract.model_validate(payload)


def load_default_swarm_contract() -> SwarmContract:
    return load_swarm_contract(DEFAULT_SWARM_CONTRACT_PATH)
