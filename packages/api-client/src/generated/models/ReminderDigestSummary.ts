/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ReminderDigestItemSummary } from './ReminderDigestItemSummary';
export type ReminderDigestSummary = {
    generated_on: string;
    summary: string;
    urgent_items?: Array<ReminderDigestItemSummary>;
    soon_items?: Array<ReminderDigestItemSummary>;
};

