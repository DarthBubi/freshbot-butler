/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type KitchenAssistantQueryResponse = {
    question: string;
    answer: string;
    topic: KitchenAssistantQueryResponse.topic;
    needs_clarification: boolean;
};
export namespace KitchenAssistantQueryResponse {
    export enum topic {
        INVENTORY_PRESENCE = 'inventory_presence',
        FRESHNESS_STATUS = 'freshness_status',
        SOON_ITEMS = 'soon_items',
        SHOPPING_AVAILABILITY = 'shopping_availability',
        FALLBACK = 'fallback',
    }
}

