from __future__ import annotations

from unittest.mock import patch

from app.pipeline.routing import route_investigation_loop, should_continue_investigation


class _ExplodingState:
    """State-like object that raises on every .get() call."""

    def get(self, _key: str, _default: object | None = None) -> object:
        raise RuntimeError("state unavailable")


def test_route_investigation_loop_goes_to_eval_when_flag_and_rubric() -> None:
    with patch("app.pipeline.routing.should_continue_investigation", return_value="publish"):
        out = route_investigation_loop(
            {
                "opensre_evaluate": True,
                "opensre_eval_rubric": "rule one",
                "available_action_names": ["x"],
            }
        )
    assert out == "opensre_eval"


def test_route_investigation_loop_skips_eval_without_rubric() -> None:
    with patch("app.pipeline.routing.should_continue_investigation", return_value="publish"):
        out = route_investigation_loop(
            {
                "opensre_evaluate": True,
                "opensre_eval_rubric": "",
                "available_action_names": ["x"],
            }
        )
    assert out == "publish"


def test_route_investigation_loop_investigate_takes_precedence() -> None:
    with patch("app.pipeline.routing.should_continue_investigation", return_value="investigate"):
        out = route_investigation_loop(
            {
                "opensre_evaluate": True,
                "opensre_eval_rubric": "rules",
                "available_action_names": ["x"],
            }
        )
    assert out == "investigate"


def test_should_continue_investigation_defaults_to_publish_on_error() -> None:
    """Exception during state access falls back safely to 'publish'."""
    assert should_continue_investigation(_ExplodingState()) == "publish"  # type: ignore[arg-type]


def test_should_continue_investigation_publishes_without_available_actions() -> None:
    """No available actions triggers immediate publish."""
    state = {
        "investigation_recommendations": ["inspect logs"],
        "investigation_loop_count": 0,
        "available_action_names": [],
    }

    assert should_continue_investigation(state) == "publish"

