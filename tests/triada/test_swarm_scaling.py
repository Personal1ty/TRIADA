from app.contracts.loader import load_default_swarm_contract
from app.services.swarm_scaling import choose_scaling


def test_scaling_selects_small_rule_for_single_read_only_step():
    decision = choose_scaling(load_default_swarm_contract(), step_count=1, risk_policy="read_only")

    assert decision.weight == "small"
    assert decision.requested_pairs == 3
    assert decision.selected_worker_ids == ["worker-1", "worker-2", "worker-3"]


def test_scaling_selects_large_rule_for_many_steps():
    decision = choose_scaling(load_default_swarm_contract(), step_count=6, risk_policy="read_only")

    assert decision.weight == "large"
    assert decision.requested_pairs == 5
    assert decision.selected_worker_ids == ["worker-1", "worker-2", "worker-3"]
