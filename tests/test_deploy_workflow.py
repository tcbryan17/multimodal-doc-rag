"""Pins the shape of the deploy gate (control C37) without needing a YAML parser.

We can't run GitHub Actions here, so these text checks guard the three properties that
matter: it is manual-only, the release check runs before the deploy step, and the deploy
step stays disabled until the owner picks a host.
"""

from pathlib import Path

TEXT = (Path(__file__).resolve().parent.parent / ".github/workflows/deploy.yml").read_text()


def test_deploy_workflow_is_manual_only() -> None:
    assert "workflow_dispatch:" in TEXT
    for trigger in ("\n  push:", "\n  pull_request:", "\n  schedule:"):
        assert trigger not in TEXT


def test_release_check_runs_before_the_deploy_step() -> None:
    check = TEXT.index("uv run python scripts/release_check.py")
    deploy = TEXT.index("name: Deploy (PLACEHOLDER")
    assert check < deploy
    assert "uv run pytest" in TEXT[:check]  # the full check suite comes first too


def test_deploy_step_is_disabled_and_never_forced_to_run() -> None:
    placeholder = TEXT[TEXT.index("name: Deploy (PLACEHOLDER") :]
    assert "if: false" in placeholder
    assert "always()" not in placeholder
