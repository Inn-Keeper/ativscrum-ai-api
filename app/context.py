import json
from copy import deepcopy
from typing import Any

from app.errors import AppError
from app.schemas import (
    AiRequest,
    ScrumCoachRequest,
    SprintSummaryRequest,
    StandupDraftRequest,
    StoryAssistantRequest,
)


_MAX_DOD = 30


def _text(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _number(value: Any, default: int | float | None = None) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return default


def _serialized_size(context: dict) -> int:
    return len(json.dumps(context, separators=(",", ":"), ensure_ascii=False))


def _not_found() -> AppError:
    return AppError(404, "resource_not_found", "The requested resource was not found.")


def _too_large() -> AppError:
    return AppError(422, "context_too_large", "The selected context is too large.")


def _project(board: dict) -> dict:
    source = board.get("project") or {}
    return {
        "name": _text(source.get("name"), 240),
        "dod": [_text(item, 500) for item in source.get("dod", [])[:_MAX_DOD]],
    }


def _sprint(board: dict, sprint_id: str) -> dict:
    source = next(
        (item for item in board.get("sprints", []) if item.get("id") == sprint_id), None
    )
    if source is None:
        raise _not_found()
    return {
        "id": _string(source.get("id")),
        "name": _text(source.get("name"), 240),
        "goal": _text(source.get("goal"), 500),
        "startDate": _text(source.get("startDate"), 20),
        "endDate": _text(source.get("endDate"), 20),
        "state": _text(source.get("state"), 20),
    }


def _acceptance(source: dict) -> list[dict]:
    return [
        {
            "id": _string(item.get("id")),
            "text": _string(item.get("text")),
            "done": bool(item.get("done")),
        }
        for item in source.get("acceptance", [])
        if isinstance(item, dict)
    ]


def _story(source: dict, *, detail: bool) -> dict:
    result = {
        "id": _string(source.get("id")),
        "title": _string(source.get("title")),
        "type": _text(source.get("type"), 20),
        "priority": _text(source.get("priority"), 20),
        "estimateDays": _number(source.get("estimateDays")),
    }
    if detail:
        result["description"] = _string(source.get("description"))
        result["acceptance"] = _acceptance(source)
    return result


def _sprint_stories(board: dict, sprint_id: str, *, detail: bool) -> list[dict]:
    sources = sorted(
        (item for item in board.get("items", []) if item.get("sprintId") == sprint_id),
        key=lambda item: str(item.get("id", "")),
    )
    return [_story(item, detail=detail) for item in sources]


def _task(source: dict) -> dict:
    result = {
        "id": _string(source.get("id")),
        "storyId": _string(source.get("backlogItemId")),
        "title": _text(source.get("title"), 240),
        "assigneeId": (
            _text(source.get("assigneeId"), 120) if source.get("assigneeId") is not None else None
        ),
        "status": _text(source.get("status"), 20),
        "completedAt": (
            _text(source.get("completedAt"), 40) if source.get("completedAt") is not None else None
        ),
    }
    if source.get("blocked"):
        result["blocked"] = _string(source["blocked"])
    return result


def _tasks(board: dict, story_ids: set[str], member_id: str | None = None) -> list[dict]:
    sources = sorted(
        (
            task
            for task in board.get("tasks", [])
            if task.get("backlogItemId") in story_ids
            and (member_id is None or task.get("assigneeId") == member_id)
        ),
        key=lambda task: str(task.get("id", "")),
    )
    return [_task(task) for task in sources]


def _cards(board: dict, field: str, sprint_id: str, *, retro: bool) -> list[dict]:
    sources = sorted(
        (card for card in board.get(field, []) if card.get("sprintId") == sprint_id),
        key=lambda card: str(card.get("id", "")),
    )
    result = []
    for source in sources:
        card = {
            "id": _string(source.get("id")),
            "text": _text(source.get("text"), 500),
            "votes": _number(source.get("votes"), 0),
        }
        if retro:
            card["column"] = _text(source.get("column"), 20)
        result.append(card)
    return result


def _transitions(board: dict, task_ids: set[str]) -> list[dict]:
    sources = sorted(
        (item for item in board.get("transitions", []) if item.get("taskId") in task_ids),
        key=lambda item: (
            str(item.get("at", "")),
            str(item.get("taskId", "")),
            str(item.get("from", "")),
            str(item.get("to", "")),
        ),
    )
    return [
        {
            "taskId": _string(item.get("taskId")),
            "from": _text(item.get("from"), 20),
            "to": _text(item.get("to"), 20),
            "at": _text(item.get("at"), 40),
        }
        for item in sources
    ]


def _summary_context(board: dict, request: SprintSummaryRequest) -> dict:
    sprint = _sprint(board, request.sprint_id)
    stories = _sprint_stories(board, request.sprint_id, detail=False)
    story_ids = {story["id"] for story in stories}
    return {
        "kind": request.kind,
        "project": _project(board),
        "sprint": sprint,
        "stories": stories,
        "tasks": _tasks(board, story_ids),
        "reviewCards": _cards(board, "reviewCards", request.sprint_id, retro=False),
        "retroCards": _cards(board, "retroCards", request.sprint_id, retro=True),
    }


def _story_context(board: dict, request: StoryAssistantRequest) -> dict:
    source = None
    if request.item_id is not None:
        source = next(
            (item for item in board.get("items", []) if item.get("id") == request.item_id), None
        )
        if source is None:
            raise _not_found()

    if source is None:
        draft = request.draft
        assert draft is not None
        story = {
            "title": draft.title,
            "description": draft.description,
            "acceptance": list(draft.acceptance),
            "estimateDays": draft.estimate_days,
        }
        tasks = []
    else:
        story = _story(source, detail=True)
        tasks = _tasks(board, {story["id"]})
        if request.draft is not None:
            supplied = request.draft.model_dump(exclude_unset=True)
            if "title" in supplied:
                story["title"] = supplied["title"]
            if "description" in supplied:
                story["description"] = supplied["description"]
            if "acceptance" in supplied:
                story["acceptance"] = list(supplied["acceptance"])
            if "estimate_days" in supplied:
                story["estimateDays"] = supplied["estimate_days"]

    return {
        "kind": request.kind,
        "project": _project(board),
        "story": story,
        "tasks": tasks,
    }


def _standup_context(board: dict, request: StandupDraftRequest) -> dict:
    sprint = _sprint(board, request.sprint_id)
    stories = _sprint_stories(board, request.sprint_id, detail=False)
    tasks = _tasks(board, {story["id"] for story in stories}, request.member_id)
    person_ids = {task["assigneeId"] for task in tasks if task["assigneeId"]}
    people = [
        {"id": _string(person.get("id")), "name": _text(person.get("name"), 240)}
        for person in sorted(board.get("people", []), key=lambda item: str(item.get("id", "")))
        if person.get("id") in person_ids
    ]
    referenced_story_ids = {task["storyId"] for task in tasks}
    if request.member_id is not None:
        stories = [story for story in stories if story["id"] in referenced_story_ids]
    return {
        "kind": request.kind,
        "sprint": sprint,
        "stories": stories,
        "tasks": tasks,
        "people": people,
        "transitions": _transitions(board, {task["id"] for task in tasks}),
    }


def _metrics(board: dict) -> dict:
    source = board.get("metrics") or {}
    return {
        key: value
        for key, value in sorted(source.items(), key=lambda item: str(item[0]))
        if isinstance(key, str) and isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def _coach_context(board: dict, request: ScrumCoachRequest) -> dict:
    sprint = _sprint(board, request.sprint_id)
    stories = _sprint_stories(board, request.sprint_id, detail=False)
    tasks = _tasks(board, {story["id"] for story in stories})
    limits = board.get("wipLimits") or {}
    return {
        "kind": request.kind,
        "sprint": sprint,
        "stories": stories,
        "tasks": tasks,
        "transitions": _transitions(board, {task["id"] for task in tasks}),
        "wipLimits": {
            status: limits[status]
            for status in ("todo", "inprogress", "test", "done")
            if isinstance(limits.get(status), int) and not isinstance(limits.get(status), bool)
        },
        "metrics": _metrics(board),
    }


def _trim_to_size(context: dict, max_chars: int) -> dict:
    result = deepcopy(context)
    while _serialized_size(result) > max_chars:
        transitions = result.get("transitions", [])
        if transitions:
            transitions.pop(0)
            continue

        cards = [
            (card.get("votes", 0), field, card.get("id", ""), index)
            for field in ("reviewCards", "retroCards")
            for index, card in enumerate(result.get(field, []))
        ]
        if cards:
            _, field, _, index = min(cards)
            result[field].pop(index)
            continue

        completed = next(
            (
                task
                for task in result.get("tasks", [])
                if task.get("status") == "done"
                and (task.get("completedAt") is not None or task.get("assigneeId") is not None)
            ),
            None,
        )
        if completed is not None:
            if completed.get("completedAt") is not None:
                completed["completedAt"] = None
            else:
                completed["assigneeId"] = None
            continue

        raise _too_large()
    return result


def build_context(board: dict, request: AiRequest, max_chars: int) -> dict:
    if isinstance(request, SprintSummaryRequest):
        context = _summary_context(board, request)
    elif isinstance(request, StoryAssistantRequest):
        context = _story_context(board, request)
    elif isinstance(request, StandupDraftRequest):
        context = _standup_context(board, request)
    elif isinstance(request, ScrumCoachRequest):
        context = _coach_context(board, request)
    else:  # pragma: no cover - AiRequest is a closed discriminated union
        raise TypeError("Unsupported AI request")

    return _trim_to_size(context, max_chars)
