"""Tests for merge_hypothesis_results in app/nodes/investigate/merge.py."""

from __future__ import annotations

from typing import Any

from app.nodes.investigate import merge as merge_module
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


def _state() -> dict[str, Any]:
    return dict(make_initial_state("HighErrorRate", "checkout", "critical"))


def test_merge_hypothesis_results_merges_successful_evidence(monkeypatch: Any) -> None:
    """Successful action data is mapped into evidence and tracked in executed_hypotheses."""
    monkeypatch.setattr(merge_module, "get_tracker", _TrackerStub)

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
    """hypothesis_results is reset with a __clear sentinel after merging."""
    monkeypatch.setattr(merge_module, "get_tracker", _TrackerStub)

    state = _state()
    state["hypothesis_results"] = [
        {"action_name": "alertmanager_alerts", "success": True, "data": {"total": 0}}
    ]

    result = merge_module.merge_hypothesis_results(state)

    assert result["hypothesis_results"] == [{"__clear": True}]


def test_merge_hypothesis_results_preserves_existing_evidence_without_results(
    monkeypatch: Any,
) -> None:
    """Empty hypothesis_results must not clobber existing evidence."""
    monkeypatch.setattr(merge_module, "get_tracker", _TrackerStub)

    state = _state()
    state["evidence"] = {"existing_signal": {"status": "kept"}}
    state["hypothesis_results"] = []

    result = merge_module.merge_hypothesis_results(state)

    assert result["evidence"] == {"existing_signal": {"status": "kept"}}
    assert result["executed_hypotheses"] == []


def test_merge_hypothesis_results_ignores_entries_without_action_name(
    monkeypatch: Any,
) -> None:
    """Malformed entries missing action_name are silently skipped."""
    monkeypatch.setattr(merge_module, "get_tracker", _TrackerStub)

    state = _state()
    state["evidence"] = {"existing_signal": True}
    state["hypothesis_results"] = [
        {"success": True, "data": {"alerts": [{"labels": {"alertname": "ignored"}}]}}
    ]

    result = merge_module.merge_hypothesis_results(state)

    assert result["evidence"] == {"existing_signal": True}
    assert result["executed_hypotheses"] == []
