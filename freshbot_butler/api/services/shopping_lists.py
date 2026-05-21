from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.models import (
    Batch,
    BatchEvent,
    Household,
    Member,
    SessionToken,
    ShoppingList,
    ShoppingListItem,
    ShoppingReplenishmentSuggestion,
    utc_now,
)
from freshbot_butler.api.services.batch_quantities import is_countable_quantity, parse_quantity
from freshbot_butler.api.schemas import (
    ShoppingListItemRequest,
    ShoppingListItemSummary,
    ShoppingListRequest,
    ShoppingListSummary,
    ShoppingListsResponse,
    ShoppingReplenishmentSuggestionSummary,
    ShoppingSuggestionAcceptRequest,
)


@dataclass(frozen=True)
class HouseholdContext:
    household: Household
    member: Member


class ShoppingListService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_token(self, token: str) -> ShoppingListsResponse:
        context = await self._load_context(token)
        return await self._load_for_household(context.household.id)

    async def create_list(self, token: str, request: ShoppingListRequest) -> ShoppingListsResponse:
        context = await self._load_context(token)
        self._session.add(
            ShoppingList(
                household_id=context.household.id,
                name=request.name.strip(),
            )
        )
        await self._session.commit()
        return await self._load_for_household(context.household.id)

    async def rename_list(self, token: str, list_id: str, request: ShoppingListRequest) -> ShoppingListsResponse:
        context = await self._load_context(token)
        shopping_list = await self._load_list(context.household.id, list_id)
        shopping_list.name = request.name.strip()
        await self._session.commit()
        return await self._load_for_household(context.household.id)

    async def upsert_item(
        self,
        token: str,
        list_id: str,
        request: ShoppingListItemRequest,
    ) -> ShoppingListsResponse:
        context = await self._load_context(token)
        shopping_list = await self._load_list(context.household.id, list_id)
        product_key = normalize_product_key(request.name)
        item = await self._session.scalar(
            select(ShoppingListItem).where(
                ShoppingListItem.shopping_list_id == shopping_list.id,
                ShoppingListItem.product_key == product_key,
            )
        )
        if item is None:
            item = ShoppingListItem(
                shopping_list_id=shopping_list.id,
                product_key=product_key,
                name=request.name.strip(),
                quantity=request.quantity.strip(),
            )
            self._session.add(item)
        else:
            item.name = request.name.strip()
            item.quantity = request.quantity.strip()
        await self._session.commit()
        return await self._load_for_household(context.household.id)

    async def remove_item(self, token: str, list_id: str, item_id: str) -> ShoppingListsResponse:
        context = await self._load_context(token)
        shopping_list = await self._load_list(context.household.id, list_id)
        await self._session.execute(
            delete(ShoppingListItem).where(
                ShoppingListItem.id == item_id,
                ShoppingListItem.shopping_list_id == shopping_list.id,
            )
        )
        await self._session.commit()
        return await self._load_for_household(context.household.id)

    async def accept_suggestion(
        self,
        token: str,
        suggestion_id: str,
        request: ShoppingSuggestionAcceptRequest,
    ) -> ShoppingListsResponse:
        context = await self._load_context(token)
        shopping_list = await self._load_list(context.household.id, request.list_id)
        suggestion = await self._load_pending_suggestion(context.household.id, suggestion_id)
        item = await self._upsert_item(
            shopping_list.id,
            product_key=suggestion.product_key,
            name=suggestion.name,
            quantity=suggestion.quantity,
        )
        suggestion.accepted_list_id = shopping_list.id
        suggestion.accepted_item_id = item.id
        suggestion.accepted_at = utc_now()
        await self._session.commit()
        return await self._load_for_household(context.household.id)

    async def load_pending_suggestions_for_household(
        self,
        household_id: str,
    ) -> list[ShoppingReplenishmentSuggestionSummary]:
        rows = await self._session.scalars(
            select(ShoppingReplenishmentSuggestion)
            .where(
                ShoppingReplenishmentSuggestion.household_id == household_id,
                ShoppingReplenishmentSuggestion.accepted_at.is_(None),
            )
            .order_by(ShoppingReplenishmentSuggestion.created_at.asc(), ShoppingReplenishmentSuggestion.id.asc())
        )
        return [self._to_suggestion_summary(suggestion) for suggestion in rows.all()]

    async def record_replenishment_suggestion(self, household_id: str, batch: Batch, event: BatchEvent) -> None:
        if event.action not in {"used_up", "discarded"} and not self._is_countable_decrement_to_zero(event):
            return

        suggestion = await self._session.scalar(
            select(ShoppingReplenishmentSuggestion).where(
                ShoppingReplenishmentSuggestion.household_id == household_id,
                ShoppingReplenishmentSuggestion.source_batch_event_id == event.id,
            )
        )
        if suggestion is not None:
            return

        quantity = event.quantity_before or event.quantity_after or batch.quantity
        source_action = "used_up" if event.action == "decremented" else event.action
        self._session.add(
            ShoppingReplenishmentSuggestion(
                household_id=household_id,
                source_batch_id=batch.id,
                source_batch_event_id=event.id,
                source_action=source_action,
                product_key=normalize_product_key(batch.name),
                name=batch.name,
                quantity=quantity or batch.quantity,
            )
        )

    def _is_countable_decrement_to_zero(self, event: BatchEvent) -> bool:
        if event.action != "decremented" or event.quantity_after is None:
            return False

        amount, unit = parse_quantity(event.quantity_after)
        return amount == 0 and is_countable_quantity(amount, unit)

    async def _load_for_household(self, household_id: str) -> ShoppingListsResponse:
        shopping_lists = (
            await self._session.scalars(
                select(ShoppingList)
                .where(ShoppingList.household_id == household_id)
                .order_by(ShoppingList.created_at.asc(), ShoppingList.id.asc())
            )
        ).all()
        items = (
            await self._session.scalars(
                select(ShoppingListItem)
                .join(ShoppingList, ShoppingList.id == ShoppingListItem.shopping_list_id)
                .where(ShoppingList.household_id == household_id)
                .order_by(ShoppingListItem.created_at.asc(), ShoppingListItem.id.asc())
            )
        ).all()
        suggestions = await self.load_pending_suggestions_for_household(household_id)

        items_by_list: dict[str, list[ShoppingListItemSummary]] = {}
        for item in items:
            items_by_list.setdefault(item.shopping_list_id, []).append(self._to_item_summary(item))

        return ShoppingListsResponse(
            lists=[
                ShoppingListSummary(
                    id=shopping_list.id,
                    name=shopping_list.name,
                    items=items_by_list.get(shopping_list.id, []),
                )
                for shopping_list in shopping_lists
            ],
            replenishment_suggestions=suggestions,
        )

    async def _upsert_item(self, shopping_list_id: str, *, product_key: str, name: str, quantity: str) -> ShoppingListItem:
        item = await self._session.scalar(
            select(ShoppingListItem).where(
                ShoppingListItem.shopping_list_id == shopping_list_id,
                ShoppingListItem.product_key == product_key,
            )
        )
        if item is None:
            item = ShoppingListItem(
                shopping_list_id=shopping_list_id,
                product_key=product_key,
                name=name,
                quantity=quantity,
            )
            self._session.add(item)
            await self._session.flush()
            return item

        item.name = name
        item.quantity = quantity
        return item

    async def _load_context(self, token: str) -> HouseholdContext:
        session_token = await self._session.scalar(
            select(SessionToken).where(
                SessionToken.token == token,
                SessionToken.expires_at > utc_now(),
            )
        )
        if session_token is None:
            raise InvalidShoppingListSessionError()

        member = await self._session.get(Member, session_token.member_id)
        if member is None:
            raise InvalidShoppingListSessionError()

        household = await self._session.get(Household, member.household_id)
        if household is None:
            raise InvalidShoppingListSessionError()
        return HouseholdContext(household=household, member=member)

    async def _load_list(self, household_id: str, list_id: str) -> ShoppingList:
        shopping_list = await self._session.scalar(
            select(ShoppingList).where(
                ShoppingList.id == list_id,
                ShoppingList.household_id == household_id,
            )
        )
        if shopping_list is None:
            raise UnknownShoppingListError()
        return shopping_list

    async def _load_pending_suggestion(self, household_id: str, suggestion_id: str) -> ShoppingReplenishmentSuggestion:
        suggestion = await self._session.scalar(
            select(ShoppingReplenishmentSuggestion).where(
                ShoppingReplenishmentSuggestion.id == suggestion_id,
                ShoppingReplenishmentSuggestion.household_id == household_id,
                ShoppingReplenishmentSuggestion.accepted_at.is_(None),
            )
        )
        if suggestion is None:
            raise UnknownShoppingSuggestionError()
        return suggestion

    def _to_item_summary(self, item: ShoppingListItem) -> ShoppingListItemSummary:
        return ShoppingListItemSummary(
            id=item.id,
            product_key=item.product_key,
            name=item.name,
            quantity=item.quantity,
        )

    def _to_suggestion_summary(self, suggestion: ShoppingReplenishmentSuggestion) -> ShoppingReplenishmentSuggestionSummary:
        return ShoppingReplenishmentSuggestionSummary(
            id=suggestion.id,
            product_key=suggestion.product_key,
            name=suggestion.name,
            quantity=suggestion.quantity,
            source_action=suggestion.source_action,
            source_batch_name=suggestion.name,
            accepted_at=suggestion.accepted_at,
            accepted_list_id=suggestion.accepted_list_id,
        )


def normalize_product_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized.casefold())
    return normalized.strip("-") or "produkt"


class InvalidShoppingListSessionError(Exception):
    pass


class UnknownShoppingListError(Exception):
    pass


class UnknownShoppingSuggestionError(Exception):
    pass
