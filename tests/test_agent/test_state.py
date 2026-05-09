"""Tests for agent state structure."""
from gelochip.agent.graph import create_initial_state


def test_initial_state_structure():
    state = create_initial_state("Design a 5GHz LNA")
    assert state["user_request"] == "Design a 5GHz LNA"
    assert state["messages"] == []
    assert state["circuit_spec"] is None
    assert state["correction_count"] == 0
    assert state["max_corrections"] == 3
    assert state["errors"] == []


def test_initial_state_custom_corrections():
    state = create_initial_state("test", max_corrections=5)
    assert state["max_corrections"] == 5
