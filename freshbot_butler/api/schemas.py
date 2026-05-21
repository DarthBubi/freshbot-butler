from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

NonBlankShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class HouseholdSessionRequest(BaseModel):
    household_name: str = Field(min_length=1, max_length=255)
    member_name: str = Field(min_length=1, max_length=255)


class HouseholdInfo(BaseModel):
    name: str
    slug: str


class MemberInfo(BaseModel):
    display_name: str


class HouseholdSessionResponse(BaseModel):
    token: str
    locale: str
    household: HouseholdInfo
    member: MemberInfo


DateType = Literal["best_before", "use_by"]
FreshnessState = Literal["urgent", "soon", "normal"]
FreshnessSource = Literal["exact_date", "category_default", "household_override"]


class FreshnessSummary(BaseModel):
    state: FreshnessState
    source: FreshnessSource
    due_on: date
    date_type: DateType | None = None


class BatchSummary(BaseModel):
    name: str
    quantity: str
    category: str
    location: str
    freshness: FreshnessSummary | None = None


class TodaySections(BaseModel):
    needs_attention: list[BatchSummary] = Field(default_factory=list)
    upcoming: list[BatchSummary] = Field(default_factory=list)
    shopping_suggestions: list[dict] = Field(default_factory=list)
    inventory: list[BatchSummary] = Field(default_factory=list)


class TodayResponse(BaseModel):
    household_name: str
    member_name: str
    locale: str
    sections: TodaySections


class FreshnessPolicySummary(BaseModel):
    category: str
    default_shelf_life_days: int
    default_soon_window_days: int
    shelf_life_days: int
    soon_window_days: int
    is_override: bool


class FreshnessPolicyListResponse(BaseModel):
    policies: list[FreshnessPolicySummary]


class FreshnessOverrideRequest(BaseModel):
    shelf_life_days: int = Field(ge=0, le=365)
    soon_window_days: int = Field(ge=0, le=365)


class TextCaptureDraft(BaseModel):
    name: NonBlankShortText
    quantity: NonBlankShortText
    category: NonBlankShortText
    location: NonBlankShortText
    date_type: DateType | None = None
    expires_on: date | None = None


class TextCaptureDraftRequest(BaseModel):
    input_text: str = Field(min_length=1, max_length=1000)


class TextCaptureDraftResponse(BaseModel):
    drafts: list[TextCaptureDraft]
    available_categories: list[str]
    available_locations: list[str]


class VoiceCaptureDraftResponse(TextCaptureDraftResponse):
    transcript: str

class TextCaptureConfirmRequest(BaseModel):
    drafts: list[TextCaptureDraft] = Field(min_length=1)


class TextCaptureConfirmResponse(BaseModel):
    batches: list[BatchSummary]


class PackagePhotoDraft(TextCaptureDraft):
    requires_date_review: bool = False
    date_reviewed: bool = False


class PackagePhotoDraftResponse(BaseModel):
    capture_id: str
    status: Literal["processing", "pending_review"]
    drafts: list[PackagePhotoDraft]
    available_categories: list[str]
    available_locations: list[str]
    available_date_types: list[DateType]


class PackagePhotoConfirmRequest(BaseModel):
    capture_id: str = Field(min_length=1, max_length=255)
    drafts: list[PackagePhotoDraft] = Field(min_length=1)
