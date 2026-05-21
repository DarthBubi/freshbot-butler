/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { FreshnessPolicySummary } from './FreshnessPolicySummary';
import type { ReminderDeliveryPlanSummary } from './ReminderDeliveryPlanSummary';
import type { ReminderDeliverySummary } from './ReminderDeliverySummary';
import type { ReminderDigestSummary } from './ReminderDigestSummary';
import type { ReminderSettingsSummary } from './ReminderSettingsSummary';
export type ReminderPreviewResponse = {
    household_name: string;
    member_name: string;
    locale: string;
    settings: ReminderSettingsSummary;
    digest: ReminderDigestSummary;
    delivery: ReminderDeliveryPlanSummary;
    freshness_policies: Array<FreshnessPolicySummary>;
    deliveries?: Array<ReminderDeliverySummary>;
};

