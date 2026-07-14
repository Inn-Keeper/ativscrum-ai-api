import json
from copy import deepcopy
from uuid import UUID

import pytest

from app.context import build_context
from app.errors import AppError
from app.schemas import (
    ScrumCoachRequest,
    SprintSummaryRequest,
    StandupDraftRequest,
    StoryAssistantRequest,
    StoryDraft,
)


ORG_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def board() -> dict:
    return {
        "project": {
            "name": "Launch board",
            "description": "SECRET_PROJECT_DESCRIPTION",
            "dod": ["Reviewed", "Tested"],
            "productGoal": "SECRET_PRODUCT_GOAL",
        },
        "sprints": [
            {
                "id": "s-old",
                "name": "Old sprint",
                "goal": "SECRET_OLD_SPRINT",
                "startDate": "2026-06-01",
                "endDate": "2026-06-14",
                "state": "done",
                "snapshot": "SECRET_SNAPSHOT",
                "demoUrl": "https://secret.example",
            },
            {
                "id": "s-current",
                "name": "Current sprint",
                "goal": "Ship safely",
                "startDate": "2026-07-01",
                "endDate": "2026-07-14",
                "state": "active",
                "snapshot": "SECRET_CURRENT_SNAPSHOT",
                "demoUrl": "https://secret.example/current",
            },
        ],
        "items": [
            {
                "id": "story-old",
                "title": "SECRET_OLD_STORY",
                "type": "feature",
                "priority": "low",
                "estimateDays": 1,
                "sprintId": "s-old",
                "order": 0,
                "description": "old",
                "links": ["https://secret.example/old"],
            },
            {
                "id": "story-b",
                "title": "Second story",
                "type": "bug",
                "priority": "high",
                "estimateDays": 2,
                "sprintId": "s-current",
                "order": 2,
                "description": "Fix the edge case",
                "acceptance": [{"id": "ac-b", "text": "It works", "done": False}],
                "links": ["https://secret.example/pr/2"],
            },
            {
                "id": "story-a",
                "title": "First story",
                "type": "feature",
                "priority": "critical",
                "estimateDays": 3,
                "sprintId": "s-current",
                "order": 1,
                "description": "Build it",
                "acceptance": [{"id": "ac-a", "text": "Done safely", "done": True}],
                "links": ["https://secret.example/pr/1"],
            },
        ],
        "tasks": [
            {
                "id": "task-b",
                "backlogItemId": "story-b",
                "title": "Investigate",
                "assigneeId": "person-b",
                "status": "inprogress",
                "completedAt": None,
                "blocked": "Waiting for access",
            },
            {
                "id": "task-a",
                "backlogItemId": "story-a",
                "title": "Implement",
                "assigneeId": "person-a",
                "status": "done",
                "completedAt": "2026-07-04",
            },
            {
                "id": "task-old",
                "backlogItemId": "story-old",
                "title": "SECRET_OLD_TASK",
                "assigneeId": "person-a",
                "status": "done",
                "completedAt": "2026-06-02",
            },
        ],
        "people": [
            {
                "id": "person-b",
                "name": "Bob",
                "email": "bob-secret@example.com",
                "auth_id": "SECRET_AUTH_B",
                "hue": 10,
                "role": "dev",
            },
            {
                "id": "person-a",
                "name": "Alice",
                "email": "alice-secret@example.com",
                "user_id": "SECRET_AUTH_A",
                "hue": 20,
                "role": "po",
            },
        ],
        "transitions": [
            {"taskId": "task-b", "from": "todo", "to": "inprogress", "at": "2026-07-06"},
            {"taskId": "task-a", "from": "todo", "to": "inprogress", "at": "2026-07-02"},
            {"taskId": "task-a", "from": "inprogress", "to": "done", "at": "2026-07-04"},
            {"taskId": "task-old", "from": "todo", "to": "done", "at": "2026-06-02"},
        ],
        "reviewCards": [
            {"id": "review-low", "sprintId": "s-current", "text": "Minor note", "votes": 0},
            {"id": "review-top", "sprintId": "s-current", "text": "Strong result", "votes": 5},
            {"id": "review-old", "sprintId": "s-old", "text": "SECRET_OLD_REVIEW", "votes": 9},
        ],
        "retroCards": [
            {"id": "retro-low", "sprintId": "s-current", "column": "start", "text": "Pair more", "votes": 0},
            {"id": "retro-top", "sprintId": "s-current", "column": "continue", "text": "Small PRs", "votes": 4},
            {"id": "retro-old", "sprintId": "s-old", "column": "stop", "text": "SECRET_OLD_RETRO", "votes": 9},
        ],
        "comments": [{"id": "comment-1", "text": "SECRET_COMMENT"}],
        "invites": [{"id": "invite-1", "email": "invite-secret@example.com"}],
        "members": [{"user_id": "SECRET_MEMBER_AUTH", "email": "member-secret@example.com"}],
        "wipLimits": {"inprogress": 3, "test": 2},
        "metrics": {"blocked": 1, "cycleTimeDays": 2.5},
    }


def serialized(value: dict) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def assert_private_fields_absent(context: dict) -> None:
    text = serialized(context)
    for secret in (
        "SECRET_OLD_SPRINT",
        "SECRET_OLD_STORY",
        "SECRET_OLD_TASK",
        "SECRET_OLD_REVIEW",
        "SECRET_OLD_RETRO",
        "SECRET_COMMENT",
        "SECRET_AUTH_A",
        "SECRET_AUTH_B",
        "SECRET_MEMBER_AUTH",
        "secret@example.com",
        "https://secret.example",
    ):
        assert secret not in text


def test_summary_selects_only_current_sprint_records(board):
    context = build_context(
        board,
        SprintSummaryRequest(kind="sprint_summary", org_id=ORG_ID, sprint_id="s-current"),
        max_chars=10_000,
    )

    assert context["project"] == {"name": "Launch board", "dod": ["Reviewed", "Tested"]}
    assert context["sprint"]["id"] == "s-current"
    assert [story["id"] for story in context["stories"]] == ["story-a", "story-b"]
    assert [task["id"] for task in context["tasks"]] == ["task-a", "task-b"]
    assert [card["id"] for card in context["reviewCards"]] == ["review-low", "review-top"]
    assert [card["id"] for card in context["retroCards"]] == ["retro-low", "retro-top"]
    assert_private_fields_absent(context)


def test_story_merges_only_explicit_draft_fields_and_keeps_tasks(board):
    context = build_context(
        board,
        StoryAssistantRequest(
            kind="story_assistant",
            org_id=ORG_ID,
            item_id="story-a",
            draft=StoryDraft(title="Refined title", acceptance=["One", "Two"]),
        ),
        max_chars=10_000,
    )

    assert context["story"]["id"] == "story-a"
    assert context["story"]["title"] == "Refined title"
    assert context["story"]["description"] == "Build it"
    assert context["story"]["acceptance"] == ["One", "Two"]
    assert context["story"]["estimateDays"] == 3
    assert [task["id"] for task in context["tasks"]] == ["task-a"]
    assert_private_fields_absent(context)


def test_unsaved_story_uses_only_the_draft(board):
    context = build_context(
        board,
        StoryAssistantRequest(
            kind="story_assistant",
            org_id=ORG_ID,
            draft=StoryDraft(title="New story", description="New description", estimate_days=5),
        ),
        max_chars=10_000,
    )

    assert context["story"] == {
        "title": "New story",
        "description": "New description",
        "acceptance": [],
        "estimateDays": 5.0,
    }
    assert context["tasks"] == []


def test_standup_keeps_names_but_removes_contact_and_unrelated_data(board):
    context = build_context(
        board,
        StandupDraftRequest(kind="standup_draft", org_id=ORG_ID, sprint_id="s-current"),
        max_chars=10_000,
    )

    assert context["people"] == [
        {"id": "person-a", "name": "Alice"},
        {"id": "person-b", "name": "Bob"},
    ]
    assert [transition["at"] for transition in context["transitions"]] == [
        "2026-07-02",
        "2026-07-04",
        "2026-07-06",
    ]
    assert_private_fields_absent(context)


def test_standup_member_filter_limits_tasks_people_and_transitions(board):
    context = build_context(
        board,
        StandupDraftRequest(
            kind="standup_draft", org_id=ORG_ID, sprint_id="s-current", member_id="person-b"
        ),
        max_chars=10_000,
    )

    assert [task["id"] for task in context["tasks"]] == ["task-b"]
    assert context["people"] == [{"id": "person-b", "name": "Bob"}]
    assert [transition["taskId"] for transition in context["transitions"]] == ["task-b"]


def test_coach_includes_only_evidence_records_limits_and_supplied_metrics(board):
    context = build_context(
        board,
        ScrumCoachRequest(kind="scrum_coach", org_id=ORG_ID, sprint_id="s-current"),
        max_chars=10_000,
    )

    assert context["wipLimits"] == {"inprogress": 3, "test": 2}
    assert context["metrics"] == {"blocked": 1, "cycleTimeDays": 2.5}
    assert [story["id"] for story in context["stories"]] == ["story-a", "story-b"]
    assert [task["id"] for task in context["tasks"]] == ["task-a", "task-b"]
    assert_private_fields_absent(context)


@pytest.mark.parametrize(
    "ai_request",
    [
        SprintSummaryRequest(kind="sprint_summary", org_id=ORG_ID, sprint_id="missing"),
        StandupDraftRequest(kind="standup_draft", org_id=ORG_ID, sprint_id="missing"),
        ScrumCoachRequest(kind="scrum_coach", org_id=ORG_ID, sprint_id="missing"),
        StoryAssistantRequest(kind="story_assistant", org_id=ORG_ID, item_id="missing"),
    ],
)
def test_unknown_requested_resource_is_not_found(board, ai_request):
    with pytest.raises(AppError) as caught:
        build_context(board, ai_request, max_chars=10_000)

    assert (caught.value.status_code, caught.value.code, caught.value.message) == (
        404,
        "resource_not_found",
        "The requested resource was not found.",
    )


def test_context_is_deterministic_for_reordered_input(board):
    shuffled = deepcopy(board)
    for field in ("sprints", "items", "tasks", "people", "transitions", "reviewCards", "retroCards"):
        shuffled[field].reverse()
    request = ScrumCoachRequest(kind="scrum_coach", org_id=ORG_ID, sprint_id="s-current")

    assert serialized(build_context(board, request, 10_000)) == serialized(
        build_context(shuffled, request, 10_000)
    )


def test_size_limit_trims_oldest_transitions_before_current_blockers(board):
    for index in range(30):
        board["transitions"].append(
            {
                "taskId": "task-a",
                "from": "todo",
                "to": "inprogress",
                "at": f"2026-01-{index + 1:02d}",
            }
        )
    request = StandupDraftRequest(kind="standup_draft", org_id=ORG_ID, sprint_id="s-current")
    full = build_context(board, request, max_chars=20_000)
    limit = len(serialized(full)) - 250

    context = build_context(board, request, max_chars=limit)

    assert len(serialized(context)) <= limit
    assert len(context["transitions"]) < len(full["transitions"])
    assert context["transitions"][-1]["at"] == "2026-07-06"
    assert next(task for task in context["tasks"] if task["id"] == "task-b")["blocked"] == (
        "Waiting for access"
    )


def test_summary_trims_lowest_voted_cards_after_transitions(board):
    request = SprintSummaryRequest(kind="sprint_summary", org_id=ORG_ID, sprint_id="s-current")
    full = build_context(board, request, max_chars=10_000)
    limit = len(serialized(full)) - len(serialized(full["reviewCards"][0]))

    context = build_context(board, request, max_chars=limit)

    assert len(serialized(context)) <= limit
    retained_ids = {
        card["id"] for field in ("reviewCards", "retroCards") for card in context[field]
    }
    assert {"review-low", "retro-low"} - retained_ids
    assert "review-top" in {card["id"] for card in context["reviewCards"]}
    assert "retro-top" in {card["id"] for card in context["retroCards"]}


def test_irreducible_unsaved_draft_is_rejected(board):
    request = StoryAssistantRequest(
        kind="story_assistant",
        org_id=ORG_ID,
        draft=StoryDraft(title="Required title", description="x" * 500),
    )

    with pytest.raises(AppError) as caught:
        build_context(board, request, max_chars=100)

    assert (caught.value.status_code, caught.value.code) == (422, "context_too_large")


def test_large_required_collections_are_not_silently_pre_capped(board):
    board["items"] = []
    board["tasks"] = []
    board["reviewCards"] = []
    board["retroCards"] = []
    for index in range(105):
        story_id = f"story-{index:03d}"
        board["items"].append(
            {
                "id": story_id,
                "title": f"Story {index}",
                "type": "feature",
                "priority": "medium",
                "estimateDays": 1,
                "sprintId": "s-current",
            }
        )
        board["tasks"].append(
            {
                "id": f"task-{index:03d}",
                "backlogItemId": story_id,
                "title": f"Task {index}",
                "assigneeId": None,
                "status": "todo",
                "completedAt": None,
                **({"blocked": "Current blocker"} if index == 104 else {}),
            }
        )
        board["reviewCards"].append(
            {
                "id": f"review-{index:03d}",
                "sprintId": "s-current",
                "text": f"Review {index}",
                "votes": index,
            }
        )
        board["retroCards"].append(
            {
                "id": f"retro-{index:03d}",
                "sprintId": "s-current",
                "column": "continue",
                "text": f"Retro {index}",
                "votes": index,
            }
        )

    context = build_context(
        board,
        SprintSummaryRequest(kind="sprint_summary", org_id=ORG_ID, sprint_id="s-current"),
        max_chars=1_000_000,
    )

    assert len(context["stories"]) == 105
    assert len(context["tasks"]) == 105
    assert len(context["reviewCards"]) == 105
    assert len(context["retroCards"]) == 105
    assert context["stories"][-1]["title"] == "Story 104"
    assert context["tasks"][-1]["blocked"] == "Current blocker"

    board_without_cards = deepcopy(board)
    board_without_cards["reviewCards"] = []
    board_without_cards["retroCards"] = []
    protected = build_context(
        board_without_cards,
        SprintSummaryRequest(kind="sprint_summary", org_id=ORG_ID, sprint_id="s-current"),
        max_chars=1_000_000,
    )
    trimmed = build_context(
        board,
        SprintSummaryRequest(kind="sprint_summary", org_id=ORG_ID, sprint_id="s-current"),
        max_chars=len(serialized(protected)),
    )
    assert len(trimmed["stories"]) == 105
    assert len(trimmed["tasks"]) == 105
    assert trimmed["reviewCards"] == []
    assert trimmed["retroCards"] == []
    assert trimmed["tasks"][-1]["blocked"] == "Current blocker"


def test_requested_story_text_is_lossless_and_fails_closed_when_too_large(board):
    long_title = "T" * 300
    long_description = "D" * 4_000
    long_acceptance = "A" * 500
    board["items"][2]["title"] = long_title
    board["items"][2]["description"] = long_description
    board["items"][2]["acceptance"] = [
        {"id": "ac-lossless", "text": long_acceptance, "done": False}
    ]
    request = StoryAssistantRequest(kind="story_assistant", org_id=ORG_ID, item_id="story-a")

    context = build_context(board, request, max_chars=20_000)

    assert context["story"]["title"] == long_title
    assert context["story"]["description"] == long_description
    assert context["story"]["acceptance"][0]["text"] == long_acceptance
    with pytest.raises(AppError) as caught:
        build_context(board, request, max_chars=500)
    assert caught.value.code == "context_too_large"


def test_member_standup_keeps_only_stories_referenced_by_filtered_tasks(board):
    context = build_context(
        board,
        StandupDraftRequest(
            kind="standup_draft", org_id=ORG_ID, sprint_id="s-current", member_id="person-b"
        ),
        max_chars=10_000,
    )

    assert [story["id"] for story in context["stories"]] == ["story-b"]


def test_coach_rejects_boolean_wip_limits(board):
    board["wipLimits"] = {"todo": True, "inprogress": 3, "test": False}

    context = build_context(
        board,
        ScrumCoachRequest(kind="scrum_coach", org_id=ORG_ID, sprint_id="s-current"),
        max_chars=10_000,
    )

    assert context["wipLimits"] == {"inprogress": 3}


def test_blockers_and_metric_evidence_ids_are_lossless(board):
    long_blocker = "blocked-" + "x" * 600
    long_metric_id = "metric-" + "y" * 150
    board["tasks"][0]["blocked"] = long_blocker
    board["metrics"] = {long_metric_id: 7}

    context = build_context(
        board,
        ScrumCoachRequest(kind="scrum_coach", org_id=ORG_ID, sprint_id="s-current"),
        max_chars=20_000,
    )

    assert next(task for task in context["tasks"] if task["id"] == "task-b")[
        "blocked"
    ] == long_blocker
    assert context["metrics"] == {long_metric_id: 7}


def test_all_allowlisted_summary_values_are_lossless(board):
    project_name = "project-" + "p" * 300
    dod_entry = "dod-" + "d" * 600
    sprint_name = "sprint-" + "s" * 300
    sprint_goal = "goal-" + "g" * 600
    story_title = "story-" + "y" * 300
    task_title = "task-" + "t" * 300
    card_text = "card-" + "c" * 600
    board["project"]["name"] = project_name
    board["project"]["dod"] = [f"criterion-{index}" for index in range(35)] + [dod_entry]
    board["sprints"][1]["name"] = sprint_name
    board["sprints"][1]["goal"] = sprint_goal
    board["items"][2]["title"] = story_title
    board["tasks"][1]["title"] = task_title
    board["reviewCards"][0]["text"] = card_text

    context = build_context(
        board,
        SprintSummaryRequest(kind="sprint_summary", org_id=ORG_ID, sprint_id="s-current"),
        max_chars=50_000,
    )

    assert context["project"]["name"] == project_name
    assert len(context["project"]["dod"]) == 36
    assert context["project"]["dod"][-1] == dod_entry
    assert context["sprint"]["name"] == sprint_name
    assert context["sprint"]["goal"] == sprint_goal
    assert next(story for story in context["stories"] if story["id"] == "story-a")[
        "title"
    ] == story_title
    assert next(task for task in context["tasks"] if task["id"] == "task-a")[
        "title"
    ] == task_title
    assert next(card for card in context["reviewCards"] if card["id"] == "review-low")[
        "text"
    ] == card_text


def test_all_allowlisted_standup_values_are_lossless(board):
    person_name = "person-" + "n" * 300
    assignee_id = "person-" + "i" * 150
    transition_state = "state-" + "z" * 30
    transition_at = "date-" + "a" * 50
    board["people"][0]["id"] = assignee_id
    board["people"][0]["name"] = person_name
    board["tasks"][1]["assigneeId"] = assignee_id
    board["transitions"][1]["from"] = transition_state
    board["transitions"][1]["at"] = transition_at

    context = build_context(
        board,
        StandupDraftRequest(kind="standup_draft", org_id=ORG_ID, sprint_id="s-current"),
        max_chars=50_000,
    )

    task = next(task for task in context["tasks"] if task["id"] == "task-a")
    transition = next(
        item for item in context["transitions"] if item["from"] == transition_state
    )
    assert task["assigneeId"] == assignee_id
    assert {"id": assignee_id, "name": person_name} in context["people"]
    assert transition["from"] == transition_state
    assert transition["at"] == transition_at


def test_oversized_allowlisted_project_name_fails_instead_of_truncating():
    board = {
        "project": {"name": "p" * 1_000, "dod": []},
        "sprints": [
            {
                "id": "s",
                "name": "S",
                "goal": "G",
                "startDate": "2026-01-01",
                "endDate": "2026-01-02",
                "state": "active",
            }
        ],
        "items": [],
        "tasks": [],
        "reviewCards": [],
        "retroCards": [],
    }

    with pytest.raises(AppError) as caught:
        build_context(
            board,
            SprintSummaryRequest(kind="sprint_summary", org_id=ORG_ID, sprint_id="s"),
            max_chars=600,
        )

    assert caught.value.code == "context_too_large"
