"""The ingest workflow is checked as data: what can trigger it, what it may do, what it uses."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / ".github" / "workflows" / "ingest.yml").read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(TEXT)
# PyYAML reads the bare key `on` as the boolean True.
TRIGGERS = WORKFLOW.get("on", WORKFLOW.get(True))
STEPS = WORKFLOW["jobs"]["ingest"]["steps"]


def step_index(fragment: str) -> int:
    return next(i for i, s in enumerate(STEPS) if fragment in (s.get("name", "") + s.get("run", "")))


def test_it_runs_only_when_someone_dispatches_it_by_hand():
    assert set(TRIGGERS) == {"workflow_dispatch"}  # no schedule, push or pull_request
    assert "schedule" not in TRIGGERS


def test_the_job_input_is_a_closed_choice_so_it_cannot_inject_commands():
    job = TRIGGERS["workflow_dispatch"]["inputs"]["job"]
    assert job["type"] == "choice" and job["options"] == ["daily", "weekly", "monthly"]


def test_permissions_are_exactly_issues_and_contents_write():
    assert WORKFLOW["permissions"] == {"issues": "write", "contents": "write"}


def test_secrets_come_from_actions_secrets_and_nothing_is_hardcoded():
    env = WORKFLOW["jobs"]["ingest"]["env"]
    assert env["DATABASE_URL"] == "${{ secrets.DATABASE_URL }}"
    assert env["TIMEGLOBE_CONTACT"] == "${{ secrets.TIMEGLOBE_CONTACT }}"
    assert "postgres://" not in TEXT and "postgresql://" not in TEXT


def test_the_database_opt_in_is_set_only_inside_this_workflow():
    assert WORKFLOW["jobs"]["ingest"]["env"]["TIMEGLOBE_ALLOW_DB"] == "1"


def test_steps_run_in_a_safe_order():
    order = [step_index(x) for x in ("migrations", "timeglobe_pipeline.run ${{ inputs.job }}",
                                     "Build the snapshot", "data branch")]
    assert order == sorted(order) and len(set(order)) == 4


def test_a_failed_run_opens_an_issue_with_the_default_token():
    last = STEPS[-1]
    assert last["if"] == "failure()"
    assert last["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "gh issue create" in last["run"]


def test_it_never_deploys_and_there_is_no_vercel_hook_yet():
    assert "VERCEL" not in TEXT.upper()


def test_runs_do_not_overlap():
    assert WORKFLOW["concurrency"] == {"group": "ingest", "cancel-in-progress": False}


USES_LINES = [line.strip() for line in TEXT.splitlines() if line.strip().lstrip("- ").startswith("uses:")]


def test_there_are_pinned_actions_to_check():
    assert len(USES_LINES) == 2 == len([s for s in STEPS if "uses" in s])


@pytest.mark.parametrize("line", USES_LINES)
def test_every_action_is_pinned_to_a_full_commit_sha_with_its_version_as_a_comment(line):
    assert re.fullmatch(r"-? ?uses: [\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+", line), line


def test_dependabot_keeps_the_pinned_actions_current_weekly():
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert config["version"] == 2
    (update,) = config["updates"]
    assert update["package-ecosystem"] == "github-actions" and update["directory"] == "/"
    assert update["schedule"] == {"interval": "weekly"}


def test_the_package_is_installed_editable_because_its_data_paths_are_relative_to_the_checkout():
    install = STEPS[step_index("Install the pipeline")]["run"]
    assert install == "pip install -e ./pipeline"  # a plain install loses migrations/ and labs.csv
