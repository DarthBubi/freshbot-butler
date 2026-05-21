from datetime import date, datetime
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
    shopping_suggestions: list["ShoppingReplenishmentSuggestionSummary"] = Field(default_factory=list)
    inventory: list[BatchSummary] = Field(default_factory=list)


class TodayResponse(BaseModel):
    household_name: str
    member_name: str
    locale: str
    sections: TodaySections


class KitchenAssistantQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class KitchenAssistantQueryResponse(BaseModel):
    question: str
    answer: str
    topic: Literal[
        "inventory_presence",
        "freshness_status",
        "soon_items",
        "shopping_availability",
        "fallback",
    ]
    needs_clarification: bool


class FreshnessPolicySummary(BaseModel):
    category: str
    default_shelf_life_days: int
    default_soon_window_days: int
    shelf_life_days: int
    soon_window_days: int
    is_override: bool


class FreshnessPolicyListResponse(BaseModel):
    policies: list[FreshnessPolicySummary]


class ReminderSettingsSummary(BaseModel):
    daily_digest_enabled: bool
    urgent_push_enabled: bool


class ReminderSettingsRequest(BaseModel):
    daily_digest_enabled: bool
    urgent_push_enabled: bool


class ReminderDigestItemSummary(BaseModel):
    name: str
    quantity: str
    category: str
    location: str
    freshness: FreshnessSummary


class ReminderDigestSummary(BaseModel):
    generated_on: date
    summary: str
    urgent_items: list[ReminderDigestItemSummary] = Field(default_factory=list)
    soon_items: list[ReminderDigestItemSummary] = Field(default_factory=list)


class ReminderDeliveryPlanSummary(BaseModel):
    daily_digest_delivery: Literal["in_app", "quiet"]
    urgent_push_delivery: Literal["web_push", "quiet"]
    urgent_push_candidates: list[ReminderDigestItemSummary] = Field(default_factory=list)


class ReminderDeliverySummary(BaseModel):
    kind: Literal["daily_digest", "urgent_push"]
    channel: Literal["in_app", "web_push"]
    payload: dict | list
    created_at: datetime
    delivered_at: datetime


class ReminderPreviewResponse(BaseModel):
    household_name: str
    member_name: str
    locale: str
    settings: ReminderSettingsSummary
    digest: ReminderDigestSummary
    delivery: ReminderDeliveryPlanSummary
    freshness_policies: list[FreshnessPolicySummary]
    deliveries: list[ReminderDeliverySummary] = Field(default_factory=list)


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


BatchLifecycleAction = Literal["open", "decrement", "use_up", "discard"]
BatchLifecycleState = Literal["sealed", "opened", "depleted", "discarded"]


class BatchLifecycleEventSummary(BaseModel):
    action: Literal["opened", "decremented", "used_up", "discarded"]
    quantity_before: str | None = None
    quantity_after: str | None = None
    created_at: datetime
    member_name: str


class BatchMergeSuggestion(BaseModel):
    batch_ids: list[str]
    name: str
    category: str
    location: str
    count: int


class BatchLifecycleSummary(BaseModel):
    id: str
    name: str
    quantity: str
    category: str
    location: str
    state: BatchLifecycleState
    freshness: FreshnessSummary | None = None
    events: list[BatchLifecycleEventSummary] = Field(default_factory=list)


class BatchLifecycleListResponse(BaseModel):
    batches: list[BatchLifecycleSummary]
    merge_suggestions: list[BatchMergeSuggestion] = Field(default_factory=list)


class BatchLifecycleActionRequest(BaseModel):
    action: BatchLifecycleAction


class BatchLifecycleEventListResponse(BaseModel):
    events: list[BatchLifecycleEventSummary]


class ShoppingListRequest(BaseModel):
    name: NonBlankShortText


class ShoppingListItemRequest(BaseModel):
    name: NonBlankShortText
    quantity: NonBlankShortText


class ShoppingSuggestionAcceptRequest(BaseModel):
    list_id: str = Field(min_length=1, max_length=36)


class ShoppingListItemSummary(BaseModel):
    id: str
    product_key: str
    name: str
    quantity: str


class ShoppingListSummary(BaseModel):
    id: str
    name: str
    items: list[ShoppingListItemSummary] = Field(default_factory=list)


class ShoppingReplenishmentSuggestionSummary(BaseModel):
    id: str
    product_key: str
    name: str
    quantity: str
    source_action: Literal["used_up", "discarded"]
    source_batch_name: str
    accepted_at: datetime | None = None
    accepted_list_id: str | None = None


class ShoppingListsResponse(BaseModel):
    lists: list[ShoppingListSummary]
    replenishment_suggestions: list[ShoppingReplenishmentSuggestionSummary] = Field(default_factory=list)


class PackagePhotoDraft(TextCaptureDraft):
    requires_date_review: bool = False
    date_reviewed: bool = False


class PackagePhotoDraftResponse(BaseModel):
    capture_id: str
    status: Literal["processing", "pending_review", "confirmed", "failed"]
    drafts: list[PackagePhotoDraft]
    available_categories: list[str]
    available_locations: list[str]
    available_date_types: list[DateType]


class PackagePhotoConfirmRequest(BaseModel):
    capture_id: str = Field(min_length=1, max_length=255)
    drafts: list[PackagePhotoDraft] = Field(min_length=1)
