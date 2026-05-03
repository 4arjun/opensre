"""Tests for parallel investigate hypothesis routing and merging."""

from __future__ import annotations

from typing import Any

from langgraph.constants import Send

from app.nodes.investigate.execution.execute_actions import ActionExecutionResult
from app.nodes.investigate import parallel as parallel_module
from app.nodes.investigate.parallel import node_investigate_hypothesis
from app.pipeline.routing import distribute_hypotheses
from app.state.factory import make_initial_state


class _TrackerStub:
    def start(self, _name: str, _message: str) -> None:
        return

    def complete(
        self,
        _name: str,
        *,
        fields_updated: list[str],
        message: str,
    ) -> None:
        assert fields_updated is not None
        assert message is not None


class _ActionStub:
    def __init__(self, name: str) -> None:
        self.name = name


def test_distribute_hypotheses_with_actions():
    """Test that distribute_hypotheses routes to parallel branches."""
    state = make_initial_state("test", "test", "low")
    state["planned_actions"] = ["query_grafana_logs", "query_datadog_all"]
    state["available_sources"] = {"grafana": {"service_name": "test"}}

    routes = distribute_hypotheses(state)

    assert len(routes) == 2
    for route in routes:
        assert isinstance(route, Send)
        assert route.node == "investigate_hypothesis"
        assert "action_to_run" in route.arg
        assert "available_sources" in route.arg


def test_distribute_hypotheses_empty():
    """Test routing when no actions are planned."""
    state = make_initial_state("test", "test", "low")
    state["planned_actions"] = []

    routes = distribute_hypotheses(state)

    assert len(routes) == 1
    assert routes[0] == "merge_hypothesis_results"


def test_node_investigate_hypothesis_empty():
    """Test parallel node with empty action."""
    state = make_initial_state("test", "test", "low")
    state["action_to_run"] = ""

    result = node_investigate_hypothesis(state)
    assert result == {"hypothesis_results": []}


def test_node_investigate_hypothesis_unknown_action():
    """Test parallel node handles missing registry actions safely."""
    state = make_initial_state("test", "test", "low")
    state["action_to_run"] = "non_existent_action_123"

    result = node_investigate_hypothesis(state)
    assert result == {"hypothesis_results": []}


def test_node_investigate_hypothesis_success_serializes_result(monkeypatch: Any) -> None:
    """Successful execution serializes action name, data, and success flag."""
    action = _ActionStub("query_alertmanager")
    execution_result = ActionExecutionResult(
        action_name=action.name,
        success=True,
        data={"alerts": [{"labels": {"alertname": "HighErrorRate"}}]},
        error=None,
    )

    monkeypatch.setattr(parallel_module, "get_tracker", _TrackerStub)
    monkeypatch.setattr(parallel_module, "get_available_actions", lambda: [action])
    monkeypatch.setattr(
        parallel_module,
        "execute_actions",
        lambda _names, _actions, _sources: {action.name: execution_result},
    )

    state = dict(make_initial_state("HighErrorRate", "checkout", "critical"))
    state["action_to_run"] = action.name
    state["available_sources"] = {"alertmanager": {"url": "http://localhost:9093"}}

    assert parallel_module.node_investigate_hypothesis(state) == {
        "hypothesis_results": [
            {
                "action_name": action.name,
                "success": True,
                "data": {"alerts": [{"labels": {"alertname": "HighErrorRate"}}]},
                "error": None,
            }
        ]
    }


def test_node_investigate_hypothesis_failure_serializes_result(monkeypatch: Any) -> None:
    """Failed execution propagates error string into the serialized result."""
    action = _ActionStub("query_alertmanager")
    execution_result = ActionExecutionResult(
        action_name=action.name,
        success=False,
        data={"available": False},
        error="connection refused",
    )

    monkeypatch.setattr(parallel_module, "get_tracker", _TrackerStub)
    monkeypatch.setattr(parallel_module, "get_available_actions", lambda: [action])
    monkeypatch.setattr(
        parallel_module,
        "execute_actions",
        lambda _names, _actions, _sources: {action.name: execution_result},
    )

    state = dict(make_initial_state("HighErrorRate", "checkout", "critical"))
    state["action_to_run"] = action.name

    assert parallel_module.node_investigate_hypothesis(state) == {
        "hypothesis_results": [
            {
                "action_name": action.name,
                "success": False,
                "data": {"available": False},
                "error": "connection refused",
            }
        ]
    }

