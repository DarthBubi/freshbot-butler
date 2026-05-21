/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ShoppingListSummary } from './ShoppingListSummary';
import type { ShoppingReplenishmentSuggestionSummary } from './ShoppingReplenishmentSuggestionSummary';
export type ShoppingListsResponse = {
    lists: Array<ShoppingListSummary>;
    replenishment_suggestions?: Array<ShoppingReplenishmentSuggestionSummary>;
};

