from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ShortText = Annotated[str, Field(min_length=1, max_length=500)]


class SprintSummaryRequest(StrictModel):
    kind: Literal["sprint_summary"]
    org_id: UUID
    sprint_id: str = Field(min_length=1, max_length=120)


class StoryDraft(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4_000)
    acceptance: list[ShortText] = Field(default_factory=list, max_length=30)
    estimate_days: float | None = Field(default=None, ge=0.5, le=100)


class StoryAssistantRequest(StrictModel):
    kind: Literal["story_assistant"]
    org_id: UUID
    item_id: str | None = Field(default=None, max_length=120)
    draft: StoryDraft | None = None

    @model_validator(mode="after")
    def require_story_source(self):
        if self.item_id is None and self.draft is None:
            raise ValueError("item_id or draft is required")
        return self


class StandupDraftRequest(StrictModel):
    kind: Literal["standup_draft"]
    org_id: UUID
    sprint_id: str = Field(min_length=1, max_length=120)
    member_id: str | None = Field(default=None, max_length=120)


class ScrumCoachRequest(StrictModel):
    kind: Literal["scrum_coach"]
    org_id: UUID
    sprint_id: str = Field(min_length=1, max_length=120)


AiRequest = Annotated[
    SprintSummaryRequest
    | StoryAssistantRequest
    | StandupDraftRequest
    | ScrumCoachRequest,
    Field(discriminator="kind"),
]


class SprintSummarySuggestion(StrictModel):
    headline: ShortText
    narrative: str = Field(min_length=1, max_length=4_000)
    completed: list[ShortText] = Field(max_length=30)
    carry_over: list[ShortText] = Field(max_length=30)
    blockers: list[ShortText] = Field(max_length=30)
    next_focus: list[ShortText] = Field(max_length=20)


class StorySuggestion(StrictModel):
    description: str = Field(min_length=1, max_length=4_000)
    acceptance: list[ShortText] = Field(min_length=1, max_length=30)
    tasks: list[ShortText] = Field(max_length=30)
    estimate_days: float = Field(ge=0.5, le=100)
    estimate_rationale: ShortText


class StandupMemberDraft(StrictModel):
    member_id: str = Field(min_length=1, max_length=120)
    member_name: ShortText
    completed: list[ShortText] = Field(max_length=30)
    current: list[ShortText] = Field(max_length=30)
    blockers: list[ShortText] = Field(max_length=30)


class StandupSuggestion(StrictModel):
    members: list[StandupMemberDraft] = Field(max_length=50)


class EvidenceRef(StrictModel):
    kind: Literal["sprint", "story", "task", "metric"]
    id: str = Field(min_length=1, max_length=120)


class CoachObservation(StrictModel):
    severity: Literal["info", "warning", "critical"]
    claim: ShortText
    suggestion: ShortText
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=10)


class CoachSuggestion(StrictModel):
    observations: list[CoachObservation] = Field(max_length=5)


class ResponseBase(StrictModel):
    request_id: UUID
    model: str


class SprintSummaryResponse(ResponseBase):
    kind: Literal["sprint_summary"]
    suggestion: SprintSummarySuggestion


class StoryAssistantResponse(ResponseBase):
    kind: Literal["story_assistant"]
    suggestion: StorySuggestion


class StandupDraftResponse(ResponseBase):
    kind: Literal["standup_draft"]
    suggestion: StandupSuggestion


class ScrumCoachResponse(ResponseBase):
    kind: Literal["scrum_coach"]
    suggestion: CoachSuggestion


AiResponse = Annotated[
    SprintSummaryResponse
    | StoryAssistantResponse
    | StandupDraftResponse
    | ScrumCoachResponse,
    Field(discriminator="kind"),
]
