"""Regression tests for investigation hypothesis execution and merging."""

from __future__ import annotations

from typing import Any

from app.nodes.investigate import merge as merge_module
from app.nodes.investigate import parallel as parallel_module
from app.nodes.investigate.execution.execute_actions import ActionExecutionResult
from app.pipeline.routing import should_continue_investigation
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


class _ExplodingState:
    def get(self, _key: str, _default: object | None = None) -> object:
        raise RuntimeError("state unavailable")


def _state() -> dict[str, Any]:
    return dict(make_initial_state("HighErrorRate", "checkout", "critical"))


def test_node_investigate_hypothesis_empty_action() -> None:
    state = _state()
    state["action_to_run"] = ""

    assert parallel_module.node_investigate_hypothesis(state) == {"hypothesis_results": []}


def test_node_investigate_hypothesis_unknown_action(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        parallel_module, "get_available_actions", lambda: [_ActionStub("known_action")]
    )

    state = _state()
    state["action_to_run"] = "missing_action"

    assert parallel_module.node_investigate_hypothesis(state) == {"hypothesis_results": []}


def test_node_investigate_hypothesis_success_serializes_result(monkeypatch: Any) -> None:
    action = _ActionStub("query_alertmanager")
    execution_result = ActionExecutionResult(
        action_name=action.name,
        success=True,
        data={"alerts": [{"labels": {"alertname": "HighErrorRate"}}]},
        error=None,
    )

    monkeypatch.setattr(parallel_module, "get_tracker", lambda: _TrackerStub())
    monkeypatch.setattr(parallel_module, "get_available_actions", lambda: [action])
    monkeypatch.setattr(
        parallel_module,
        "execute_actions",
        lambda _names, _actions, _sources: {action.name: execution_result},
    )

    state = _state()
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
    action = _ActionStub("query_alertmanager")
    execution_result = ActionExecutionResult(
        action_name=action.name,
        success=False,
        data={"available": False},
        error="connection refused",
    )

    monkeypatch.setattr(parallel_module, "get_tracker", lambda: _TrackerStub())
    monkeypatch.setattr(parallel_module, "get_available_actions", lambda: [action])
    monkeypatch.setattr(
        parallel_module,
        "execute_actions",
        lambda _names, _actions, _sources: {action.name: execution_result},
    )

    state = _state()
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


def test_merge_hypothesis_results_merges_successful_evidence(monkeypatch: Any) -> None:
    monkeypatch.setattr(merge_module, "get_tracker", lambda: _TrackerStub())

    state = _state()
    state["plan_rationale"] = "Check active alerts."
    state["investigation_loop_count"] = 2
    state["hypothesis_results"] = [
        {
            "action_name": "alertmanager_alerts",
            "success": True,
            "data": {
                "alerts": [{"labels": {"alertname": "HighErrorRate"}}],
                "firing_alerts": [{"labels": {"severity": "critical"}}],
                "total": 1,
            },
        }
    ]

    result = merge_module.merge_hypothesis_results(state)

    assert result["evidence"]["alertmanager_alerts_total"] == 1
    assert result["evidence"]["alertmanager_firing_alerts"] == [
        {"labels": {"severity": "critical"}}
    ]
    assert result["executed_hypotheses"][-1]["actions"] == ["alertmanager_alerts"]
    assert result["executed_hypotheses"][-1]["loop_count"] == 2


def test_merge_hypothesis_results_clears_parallel_results(monkeypatch: Any) -> None:
    monkeypatch.setattr(merge_module, "get_tracker", lambda: _TrackerStub())

    state = _state()
    state["hypothesis_results"] = [
        {"action_name": "alertmanager_alerts", "success": True, "data": {"total": 0}}
    ]

    result = merge_module.merge_hypothesis_results(state)

    assert result["hypothesis_results"] == [{"__clear": True}]


def test_merge_hypothesis_results_preserves_existing_evidence_without_results(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(merge_module, "get_tracker", lambda: _TrackerStub())

    state = _state()
    state["evidence"] = {"existing_signal": {"status": "kept"}}
    state["hypothesis_results"] = []

    result = merge_module.merge_hypothesis_results(state)

    assert result["evidence"] == {"existing_signal": {"status": "kept"}}
    assert result["executed_hypotheses"] == []


def test_merge_hypothesis_results_ignores_entries_without_action_name(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(merge_module, "get_tracker", lambda: _TrackerStub())

    state = _state()
    state["evidence"] = {"existing_signal": True}
    state["hypothesis_results"] = [
        {"success": True, "data": {"alerts": [{"labels": {"alertname": "ignored"}}]}}
    ]

    result = merge_module.merge_hypothesis_results(state)

    assert result["evidence"] == {"existing_signal": True}
    assert result["executed_hypotheses"] == []


def test_merge_hypothesis_results_does_not_mutate_input_available_sources(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(merge_module, "get_tracker", lambda: _TrackerStub())

    state = _state()
    state["evidence"] = {"grafana_service_names": ["checkout-api"]}
    state["available_sources"] = {
        "grafana": {
            "service_name": "checkout",
            "pipeline_name": "checkout",
        }
    }

    result = merge_module.merge_hypothesis_results(state)

    assert state["available_sources"]["grafana"]["service_name"] == "checkout"
    assert result["available_sources"]["grafana"]["service_name"] == "checkout-api"


def test_should_continue_investigation_defaults_to_publish_on_error() -> None:
    assert should_continue_investigation(_ExplodingState()) == "publish"  # type: ignore[arg-type]


def test_should_continue_investigation_publishes_without_available_actions() -> None:
    state = {
        "investigation_recommendations": ["inspect logs"],
        "investigation_loop_count": 0,
        "available_action_names": [],
    }

    assert should_continue_investigation(state) == "publish"
