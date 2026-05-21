from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Household(Base):
    __tablename__ = "households"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(16), default="de-DE")
    daily_digest_enabled: Mapped[bool] = mapped_column(default=True)
    urgent_push_enabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("household_id", "normalized_name", name="uq_member_household_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SessionToken(Base):
    __tablename__ = "session_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    queue_name: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(255))
    location: Mapped[str] = mapped_column(String(255))
    quantity_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(String(32), default="sealed")
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BatchEvent(Base):
    __tablename__ = "batch_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    quantity_before: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity_after: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PackagePhotoCapture(Base):
    __tablename__ = "package_photo_captures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True)
    extraction_payload: Mapped[dict] = mapped_column(JSON)
    raw_upload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    raw_upload_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_upload_content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_upload_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FreshnessOverride(Base):
    __tablename__ = "freshness_overrides"
    __table_args__ = (
        UniqueConstraint("household_id", "category", name="uq_freshness_override_household_category"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(255))
    shelf_life_days: Mapped[int] = mapped_column(Integer)
    soon_window_days: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ShoppingList(Base):
    __tablename__ = "shopping_lists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ShoppingListItem(Base):
    __tablename__ = "shopping_list_items"
    __table_args__ = (
        UniqueConstraint("shopping_list_id", "product_key", name="uq_shopping_list_item_product"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shopping_list_id: Mapped[str] = mapped_column(ForeignKey("shopping_lists.id", ondelete="CASCADE"), index=True)
    product_key: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ShoppingReplenishmentSuggestion(Base):
    __tablename__ = "shopping_replenishment_suggestions"
    __table_args__ = (
        UniqueConstraint("household_id", "source_batch_event_id", name="uq_shopping_suggestion_event"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    source_batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), index=True)
    source_batch_event_id: Mapped[str] = mapped_column(ForeignKey("batch_events.id", ondelete="CASCADE"), index=True)
    source_action: Mapped[str] = mapped_column(String(32), index=True)
    product_key: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[str] = mapped_column(String(255))
    accepted_list_id: Mapped[str | None] = mapped_column(
        ForeignKey("shopping_lists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    accepted_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("shopping_list_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReminderDelivery(Base):
    __tablename__ = "reminder_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    channel: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
