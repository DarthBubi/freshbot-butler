from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.freshness import assess_batch_freshness
from freshbot_butler.api.models import Batch, Household, Member, SessionToken, utc_now
from freshbot_butler.api.schemas import (
    KitchenAssistantQueryRequest,
    KitchenAssistantQueryResponse,
    ShoppingListItemSummary,
    ShoppingListsResponse,
    TodayResponse,
)
from freshbot_butler.api.services.freshness_overrides import FreshnessOverrideService
from freshbot_butler.api.services.shopping_lists import ShoppingListService
from freshbot_butler.api.services.today import TodayDashboardService


@dataclass(frozen=True)
class QueryCandidate:
    name: str
    source: str
    quantity: str | None = None
    location: str | None = None
    due_on: date | None = None
    freshness_state: str | None = None
    freshness_detail: str | None = None
    shopping_list_name: str | None = None


@dataclass(frozen=True)
class HouseholdContext:
    household: Household
    member: Member


class KitchenAssistantService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def query_for_token(
        self,
        token: str,
        request: KitchenAssistantQueryRequest,
    ) -> KitchenAssistantQueryResponse:
        today = await TodayDashboardService(self._session).load_for_token(token)
        shopping = await ShoppingListService(self._session).list_for_token(token)
        question = request.question.strip()
        normalized_question = normalize_text(question)
        soon_candidates = await self._soon_candidates_for_token(token)
        return self._answer(today, shopping, soon_candidates, question, normalized_question)

    def _answer(
        self,
        today: TodayResponse,
        shopping: ShoppingListsResponse,
        soon_candidates: list[QueryCandidate],
        question: str,
        normalized_question: str,
    ) -> KitchenAssistantQueryResponse:
        inventory_candidates = self._inventory_candidates(today)
        shopping_candidates = self._shopping_candidates(shopping)

        if self._looks_like_soon_question(normalized_question):
            match = self._best_match(normalized_question, soon_candidates)
            if match is not None:
                if len(match) > 1:
                    return KitchenAssistantQueryResponse(
                        question=question,
                        answer=self._ambiguous_answer(match),
                        topic="soon_items",
                        needs_clarification=True,
                    )
                return KitchenAssistantQueryResponse(
                    question=question,
                    answer=self._soon_answer(match[0]),
                    topic="soon_items",
                    needs_clarification=False,
                )
            soon_focus = self._soon_focus(question)
            if soon_focus != question.strip():
                inventory_match = self._best_match(normalized_question, inventory_candidates)
                if inventory_match is not None:
                    if len(inventory_match) > 1:
                        return KitchenAssistantQueryResponse(
                            question=question,
                            answer=self._ambiguous_answer(inventory_match),
                            topic="soon_items",
                            needs_clarification=True,
                        )
                    return KitchenAssistantQueryResponse(
                        question=question,
                        answer=self._not_soon_answer(inventory_match[0]),
                        topic="soon_items",
                        needs_clarification=False,
                    )
                return KitchenAssistantQueryResponse(
                    question=question,
                    answer=self._missing_freshness_answer(soon_focus),
                    topic="soon_items",
                    needs_clarification=True,
                )
            return KitchenAssistantQueryResponse(
                question=question,
                answer=self._answer_soon_items(self._sorted_soon_candidates(soon_candidates)),
                topic="soon_items",
                needs_clarification=False,
            )

        if self._looks_like_freshness_question(normalized_question):
            match = self._best_match(normalized_question, inventory_candidates)
            if match is None:
                return KitchenAssistantQueryResponse(
                    question=question,
                    answer=self._missing_freshness_answer(self._freshness_focus(question)),
                    topic="freshness_status",
                    needs_clarification=True,
                )
            if len(match) > 1:
                return KitchenAssistantQueryResponse(
                    question=question,
                    answer=self._ambiguous_answer(match),
                    topic="freshness_status",
                    needs_clarification=True,
                )
            return KitchenAssistantQueryResponse(
                question=question,
                answer=self._freshness_answer(match[0]),
                topic="freshness_status",
                needs_clarification=False,
            )

        if self._looks_like_shopping_question(normalized_question):
            match = self._best_match(normalized_question, inventory_candidates + shopping_candidates)
            if match is None:
                return KitchenAssistantQueryResponse(
                    question=question,
                    answer=self._shopping_overview(shopping),
                    topic="shopping_availability",
                    needs_clarification=False,
                )
            if len(match) > 1:
                return KitchenAssistantQueryResponse(
                    question=question,
                    answer=self._ambiguous_answer(match),
                    topic="shopping_availability",
                    needs_clarification=True,
                )
            return KitchenAssistantQueryResponse(
                question=question,
                answer=self._shopping_answer(match[0], shopping),
                topic="shopping_availability",
                needs_clarification=False,
            )

        if self._looks_like_presence_question(normalized_question) or inventory_candidates:
            match = self._best_match(normalized_question, inventory_candidates)
            if match is not None:
                if len(match) > 1:
                    return KitchenAssistantQueryResponse(
                        question=question,
                        answer=self._ambiguous_answer(match),
                        topic="inventory_presence",
                        needs_clarification=True,
                    )
                return KitchenAssistantQueryResponse(
                    question=question,
                    answer=self._inventory_answer(match[0]),
                    topic="inventory_presence",
                    needs_clarification=False,
                )
            if self._looks_like_presence_question(normalized_question):
                focus = self._presence_focus(question)
                return KitchenAssistantQueryResponse(
                    question=question,
                    answer=self._missing_inventory_answer(focus, shopping_candidates),
                    topic="inventory_presence",
                    needs_clarification=False,
                )

        match = self._best_match(normalized_question, inventory_candidates)
        if match is not None:
            return KitchenAssistantQueryResponse(
                question=question,
                answer=self._inventory_answer(match[0]),
                topic="inventory_presence",
                needs_clarification=False,
            )

        return KitchenAssistantQueryResponse(
            question=question,
            answer="Ich kann nur Fragen zu Vorräten, Frische und Einkauf aus euren Haushaltsdaten beantworten.",
            topic="fallback",
            needs_clarification=True,
        )

    def _inventory_candidates(self, today: TodayResponse) -> list[QueryCandidate]:
        return [
            QueryCandidate(
                name=batch.name,
                source="inventory",
                quantity=batch.quantity,
                location=batch.location,
                freshness_state=batch.freshness.state if batch.freshness else None,
                freshness_detail=self._freshness_label(batch.freshness.state) if batch.freshness else None,
            )
            for batch in today.sections.inventory
        ]

    async def _soon_candidates_for_token(self, token: str) -> list[QueryCandidate]:
        context = await self._load_household_context(token)
        batches = (
            await self._session.scalars(
                select(Batch)
                .where(Batch.household_id == context.household.id)
                .order_by(Batch.created_at.asc(), Batch.id.asc())
            )
        ).all()
        batches = [batch for batch in batches if batch.lifecycle_state not in {"depleted", "discarded"}]
        override_map = await FreshnessOverrideService(self._session).load_override_map_for_household(context.household.id)
        today = utc_now().date()
        candidates: list[QueryCandidate] = []
        for batch in batches:
            freshness = assess_batch_freshness(batch, today=today, overrides=override_map)
            if freshness.state not in {"urgent", "soon"}:
                continue
            candidates.append(
                QueryCandidate(
                    name=batch.name,
                    source="soon",
                    quantity=batch.quantity,
                    location=batch.location,
                    due_on=freshness.due_on,
                    freshness_state=freshness.state,
                    freshness_detail=self._freshness_label(freshness.state),
                )
            )
        return candidates

    def _shopping_candidates(self, shopping: ShoppingListsResponse) -> list[QueryCandidate]:
        candidates: list[QueryCandidate] = []
        for shopping_list in shopping.lists:
            for item in shopping_list.items:
                candidates.append(
                    QueryCandidate(
                        name=item.name,
                        source="shopping_list",
                        quantity=item.quantity,
                        shopping_list_name=shopping_list.name,
                    )
                )
        for suggestion in shopping.replenishment_suggestions:
            candidates.append(
                QueryCandidate(
                    name=suggestion.name,
                    source="shopping_suggestion",
                    quantity=suggestion.quantity,
                )
            )
        return candidates

    def _looks_like_soon_question(self, question: str) -> bool:
        return any(
            keyword in question
            for keyword in (
                "bald",
                "aufbrauchen",
                "nutzen",
                "verbrauchen",
                "soon",
                "use soon",
                "use up",
                "what should we use",
            )
        )

    def _looks_like_freshness_question(self, question: str) -> bool:
        return any(
            keyword in question
            for keyword in (
                "frisch",
                "haltbar",
                "haltbarkeit",
                "ablauf",
                "ablaufen",
                "expire",
                "fresh",
                "freshness",
                "wie lange",
            )
        )

    def _looks_like_shopping_question(self, question: str) -> bool:
        return any(
            keyword in question
            for keyword in (
                "einkauf",
                "einkaufen",
                "kaufen",
                "besorgen",
                "shopping",
                "buy",
                "on the list",
                "shopping list",
            )
        )

    def _looks_like_presence_question(self, question: str) -> bool:
        return any(
            keyword in question
            for keyword in (
                "haben wir",
                "gibt es",
                "ist noch",
                "noch da",
                "do we have",
                "is there",
                "have we",
            )
        )

    def _best_match(self, question: str, candidates: list[QueryCandidate]) -> list[QueryCandidate] | None:
        if not candidates:
            return None

        scored: list[tuple[int, QueryCandidate]] = []
        for candidate in candidates:
            score = self._match_score(question, candidate.name)
            if score > 0:
                scored.append((score, candidate))

        if not scored:
            return None

        scored.sort(key=lambda entry: (-entry[0], entry[1].name.casefold(), entry[1].source))
        best_score = scored[0][0]
        best = [candidate for score, candidate in scored if score == best_score]
        if len(best) > 1:
            return best
        return [best[0]]

    def _match_score(self, question: str, candidate_name: str) -> int:
        normalized_candidate = normalize_text(candidate_name)
        question_tokens = set(question.split())
        candidate_tokens = set(normalized_candidate.split())
        overlap = len(question_tokens & candidate_tokens)
        score = overlap
        if normalized_candidate and normalized_candidate in question:
            score += 3
        for token in candidate_tokens:
            if len(token) >= 3 and token in question:
                score += 1
        return score

    def _answer_soon_items(self, candidates: list[QueryCandidate]) -> str:
        if not candidates:
            return "Aktuell muss nichts bald genutzt werden."

        primary = candidates[0]
        answer = f"Ihr solltet zuerst {primary.name} nutzen."
        if len(candidates) > 1:
            answer += " Bald dran: " + ", ".join(candidate.name for candidate in candidates[1:]) + "."
        return answer

    def _soon_answer(self, candidate: QueryCandidate) -> str:
        if candidate.freshness_detail is None:
            return f"{candidate.name} sollte bald genutzt werden."
        return f"{candidate.name} ist {candidate.freshness_detail.lower()} dran."

    def _inventory_answer(self, candidate: QueryCandidate) -> str:
        return f"Ja, {candidate.name} ist da: {candidate.quantity} in {candidate.location}."

    def _freshness_answer(self, candidate: QueryCandidate) -> str:
        if candidate.freshness_detail is None:
            return f"Ich finde {candidate.name}, aber ohne Frischeangabe."
        return f"{candidate.name} ist {candidate.freshness_detail.lower()}: {candidate.quantity} in {candidate.location}."

    def _not_soon_answer(self, candidate: QueryCandidate) -> str:
        return f"{candidate.name} ist aktuell kein bald zu nutzender Artikel."

    def _missing_inventory_answer(self, target: str, shopping_candidates: list[QueryCandidate]) -> str:
        shopping_names = {candidate.name.casefold() for candidate in shopping_candidates}
        if target.casefold() in shopping_names:
            return f"Ich finde {target} nicht im aktuellen Inventar. Auf der Einkaufsliste steht {target} bereits."
        return f"Ich finde {target} nicht im aktuellen Inventar. Auf keiner Einkaufsliste steht {target}."

    def _missing_freshness_answer(self, target: str) -> str:
        if target:
            return f"Ich finde {target} nicht im aktuellen Inventar. Meint ihr einen anderen Artikel?"
        return "Ich finde keinen eindeutig genannten Artikel im aktuellen Inventar. Könnt ihr ihn genauer benennen?"

    def _shopping_answer(self, candidate: QueryCandidate, shopping: ShoppingListsResponse) -> str:
        if candidate.source == "shopping_list" and candidate.shopping_list_name is not None:
            return f"Ja, {candidate.name} steht bereits auf der Liste {candidate.shopping_list_name}."

        if candidate.source == "shopping_suggestion":
            return f"Ja, {candidate.name} liegt bereits als Nachkaufvorschlag vor."

        if any(item.name.casefold() == candidate.name.casefold() for item in self._shopping_items(shopping)):
            return f"Ja, {candidate.name} steht bereits auf einer Einkaufsliste."

        return self._inventory_answer(candidate)

    def _shopping_overview(self, shopping: ShoppingListsResponse) -> str:
        list_names = [shopping_list.name for shopping_list in shopping.lists if shopping_list.items]
        suggestion_names = [suggestion.name for suggestion in shopping.replenishment_suggestions]
        if not list_names and not suggestion_names:
            return "Es gibt noch keine Einkaufslisten oder Nachkaufvorschläge."

        parts: list[str] = []
        if list_names:
            parts.append("Auf euren Einkaufslisten stehen " + ", ".join(list_names) + ".")
        if suggestion_names:
            parts.append("Nachkaufvorschläge: " + ", ".join(suggestion_names) + ".")
        return " ".join(parts)

    def _shopping_items(self, shopping: ShoppingListsResponse) -> list[ShoppingListItemSummary]:
        return [item for shopping_list in shopping.lists for item in shopping_list.items]

    def _ambiguous_answer(self, candidates: list[QueryCandidate]) -> str:
        names = ", ".join(candidate.name for candidate in candidates)
        return f"Ich finde mehrere mögliche Treffer: {names}. Könnt ihr einen davon genauer benennen?"

    def _sorted_soon_candidates(self, candidates: list[QueryCandidate]) -> list[QueryCandidate]:
        return sorted(
            candidates,
            key=lambda candidate: (
                self._freshness_rank(candidate.freshness_state),
                candidate.due_on or date.max,
                candidate.name.casefold(),
                candidate.source,
            ),
        )

    def _freshness_label(self, state: str | None) -> str | None:
        if state == "urgent":
            return "dringend"
        if state == "soon":
            return "bald"
        if state == "normal":
            return "unauffällig"
        return None

    def _freshness_rank(self, state: str | None) -> int:
        if state == "urgent":
            return 0
        if state == "soon":
            return 1
        return 2

    async def _load_household_context(self, token: str) -> HouseholdContext:
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
        return HouseholdContext(household=household, member=member)

    def _presence_focus(self, question: str) -> str:
        return self._question_focus(question)

    def _freshness_focus(self, question: str) -> str:
        return self._question_focus(
            question,
            extra_stopwords={
                "frisch",
                "haltbar",
                "haltbarkeit",
                "ablauf",
                "ablaufen",
                "expire",
                "fresh",
                "freshness",
                "wie",
                "lange",
            },
        )

    def _soon_focus(self, question: str) -> str:
        return self._question_focus(
            question,
            extra_stopwords={
                "bald",
                "nutzen",
                "aufbrauchen",
                "verbrauchen",
                "soon",
                "use",
                "up",
                "what",
                "should",
                "we",
                "was",
                "fur",
                "sollten",
                "sollen",
                "wir",
            },
        )

    def _question_focus(self, question: str, *, extra_stopwords: set[str] | None = None) -> str:
        stopwords = {
            "haben",
            "wir",
            "gibt",
            "es",
            "ist",
            "noch",
            "da",
            "do",
            "we",
            "have",
            "there",
            "is",
            "the",
            "a",
            "an",
            "what",
        }
        if extra_stopwords is not None:
            stopwords.update(extra_stopwords)
        tokens = [
            token
            for token in re.findall(r"[\wÄÖÜäöüß-]+", question)
            if normalize_text(token) not in stopwords
        ]
        return " ".join(tokens) if tokens else question.strip()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized.casefold())
    return re.sub(r"\s+", " ", normalized).strip()
