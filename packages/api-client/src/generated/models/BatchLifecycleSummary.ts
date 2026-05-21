/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { BatchLifecycleEventSummary } from './BatchLifecycleEventSummary';
import type { FreshnessSummary } from './FreshnessSummary';
export type BatchLifecycleSummary = {
    id: string;
    name: string;
    quantity: string;
    category: string;
    location: string;
    state: BatchLifecycleSummary.state;
    freshness?: (FreshnessSummary | null);
    events?: Array<BatchLifecycleEventSummary>;
};
export namespace BatchLifecycleSummary {
    export enum state {
        SEALED = 'sealed',
        OPENED = 'opened',
        DEPLETED = 'depleted',
        DISCARDED = 'discarded',
    }
}

