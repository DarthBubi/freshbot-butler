from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.models import Batch, Household, Member, SessionToken, utc_now
from freshbot_butler.api.schemas import (
    BatchSummary,
    TextCaptureConfirmRequest,
    TextCaptureConfirmResponse,
    TextCaptureDraft,
    TextCaptureDraftRequest,
    TextCaptureDraftResponse,
)

AVAILABLE_CATEGORIES = [
    "Molkerei",
    "Obst & Gemüse",
    "Vorrat",
    "Getränke",
    "Sonstiges",
]
AVAILABLE_LOCATIONS = [
    "Kühlschrank",
    "Gefrierschrank",
    "Vorratsschrank",
]
COUNT_UNITS = {"packung", "packungen", "karton", "kartons", "flasche", "flaschen"}
LOCATION_PATTERNS = {
    "Kühlschrank": re.compile(r"\b(?:im|in den|in der|in)\s+kühlschrank$", re.IGNORECASE),
    "Gefrierschrank": re.compile(r"\b(?:im|in den|in der|in)\s+gefrierschrank$", re.IGNORECASE),
    "Vorratsschrank": re.compile(r"\b(?:im|in den|in der|in)\s+vorratsschrank$", re.IGNORECASE),
}
CATEGORY_KEYWORDS = {
    "Molkerei": {"milch", "joghurt", "käse", "butter", "quark"},
    "Obst & Gemüse": {"apfel", "äpfel", "banane", "bananen", "tomate", "tomaten", "gurke"},
    "Vorrat": {"pasta", "penne", "nudeln", "spaghetti", "reis", "mehl"},
    "Getränke": {"wasser", "saft", "haferdrink", "limonade"},
}


class TextCaptureService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def validate_session(self, token: str) -> None:
        await self._load_household_for_token(token)

    async def create_drafts(self, token: str, request: TextCaptureDraftRequest) -> TextCaptureDraftResponse:
        household = await self._load_household_for_token(token)
        return TextCaptureDraftResponse(
            drafts=[self._parse_segment(segment) for segment in split_segments(request.input_text)],
            available_categories=AVAILABLE_CATEGORIES,
            available_locations=AVAILABLE_LOCATIONS,
        )

    async def confirm_drafts(
        self,
        token: str,
        request: TextCaptureConfirmRequest,
    ) -> TextCaptureConfirmResponse:
        household = await self._load_household_for_token(token)
        batches = [
            Batch(
                household_id=household.id,
                name=draft.name.strip(),
                quantity=draft.quantity.strip(),
                category=validated_category(draft.category),
                location=validated_location(draft.location),
                date_type=draft.date_type,
                expires_on=draft.expires_on,
            )
            for draft in request.drafts
        ]
        self._session.add_all(batches)
        await self._session.commit()
        return TextCaptureConfirmResponse(
            batches=[
                BatchSummary(
                    name=batch.name,
                    quantity=batch.quantity,
                    category=batch.category,
                    location=batch.location,
                )
                for batch in batches
            ]
        )

    async def _load_household_for_token(self, token: str) -> Household:
        session_token = await self._session.scalar(
            select(SessionToken).where(
                SessionToken.token == token,
                SessionToken.expires_at > utc_now(),
            )
        )
        if session_token is None:
            raise InvalidSessionError()

        member = await self._session.get(Member, session_token.member_id)
        if member is None:
            raise InvalidSessionError()

        household = await self._session.get(Household, member.household_id)
        if household is None:
            raise InvalidSessionError()
        return household

    def _parse_segment(self, segment: str) -> TextCaptureDraft:
        cleaned_segment = normalize_whitespace(segment)
        location, cleaned_segment = extract_location(cleaned_segment)
        quantity, name = extract_quantity_and_name(cleaned_segment)
        return TextCaptureDraft(
            name=name,
            quantity=quantity,
            category=infer_category(name),
            location=location,
        )


def split_segments(input_text: str) -> list[str]:
    return [segment for segment in re.split(r"\s+und\s+", normalize_whitespace(input_text)) if segment]


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def extract_location(segment: str) -> tuple[str, str]:
    for location, pattern in LOCATION_PATTERNS.items():
        if pattern.search(segment):
            return location, normalize_whitespace(pattern.sub("", segment))
    return "Vorratsschrank", segment


def extract_quantity_and_name(segment: str) -> tuple[str, str]:
    parts = segment.split()
    if not parts:
        return "1", "Unbekannt"

    if len(parts) >= 3 and is_number(parts[0]) and parts[1].casefold() in COUNT_UNITS:
        return f"{parts[0]} {parts[1]}", " ".join(parts[2:])

    if len(parts) >= 2 and is_number(parts[0]):
        return parts[0], " ".join(parts[1:])

    return "1", segment


def infer_category(name: str) -> str:
    normalized = normalize_whitespace(name).casefold()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return category
    return "Sonstiges"


def is_number(value: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:[.,]\d+)?", value))


def validated_category(value: str) -> str:
    normalized = normalize_whitespace(value)
    if normalized not in AVAILABLE_CATEGORIES:
        return "Sonstiges"
    return normalized


def validated_location(value: str) -> str:
    normalized = normalize_whitespace(value)
    if normalized not in AVAILABLE_LOCATIONS:
        return "Vorratsschrank"
    return normalized


class InvalidSessionError(Exception):
    pass
