/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { BatchSummary } from './BatchSummary';
import type { ShoppingReplenishmentSuggestionSummary } from './ShoppingReplenishmentSuggestionSummary';
export type TodaySections = {
    needs_attention?: Array<BatchSummary>;
    upcoming?: Array<BatchSummary>;
    shopping_suggestions?: Array<ShoppingReplenishmentSuggestionSummary>;
    inventory?: Array<BatchSummary>;
};

