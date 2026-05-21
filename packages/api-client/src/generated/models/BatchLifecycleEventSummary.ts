/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type BatchLifecycleEventSummary = {
    action: BatchLifecycleEventSummary.action;
    quantity_before?: (string | null);
    quantity_after?: (string | null);
    created_at: string;
    member_name: string;
};
export namespace BatchLifecycleEventSummary {
    export enum action {
        OPENED = 'opened',
        DECREMENTED = 'decremented',
        USED_UP = 'used_up',
        DISCARDED = 'discarded',
    }
}

