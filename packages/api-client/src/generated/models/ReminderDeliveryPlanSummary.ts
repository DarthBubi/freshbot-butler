/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ReminderDigestItemSummary } from './ReminderDigestItemSummary';
export type ReminderDeliveryPlanSummary = {
    daily_digest_delivery: ReminderDeliveryPlanSummary.daily_digest_delivery;
    urgent_push_delivery: ReminderDeliveryPlanSummary.urgent_push_delivery;
    urgent_push_candidates?: Array<ReminderDigestItemSummary>;
};
export namespace ReminderDeliveryPlanSummary {
    export enum daily_digest_delivery {
        IN_APP = 'in_app',
        QUIET = 'quiet',
    }
    export enum urgent_push_delivery {
        WEB_PUSH = 'web_push',
        QUIET = 'quiet',
    }
}

