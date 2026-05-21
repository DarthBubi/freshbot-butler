/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type ReminderDeliverySummary = {
    kind: ReminderDeliverySummary.kind;
    channel: ReminderDeliverySummary.channel;
    payload: Record<string, any>;
    created_at: string;
    delivered_at: string;
};
export namespace ReminderDeliverySummary {
    export enum kind {
        DAILY_DIGEST = 'daily_digest',
        URGENT_PUSH = 'urgent_push',
    }
    export enum channel {
        IN_APP = 'in_app',
        WEB_PUSH = 'web_push',
    }
}

