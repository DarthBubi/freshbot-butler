/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type ShoppingReplenishmentSuggestionSummary = {
    id: string;
    product_key: string;
    name: string;
    quantity: string;
    source_action: ShoppingReplenishmentSuggestionSummary.source_action;
    source_batch_name: string;
    accepted_at?: (string | null);
    accepted_list_id?: (string | null);
};
export namespace ShoppingReplenishmentSuggestionSummary {
    export enum source_action {
        USED_UP = 'used_up',
        DISCARDED = 'discarded',
    }
}

