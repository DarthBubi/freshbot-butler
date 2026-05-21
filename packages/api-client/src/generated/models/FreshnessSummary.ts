/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type FreshnessSummary = {
    state: FreshnessSummary.state;
    source: FreshnessSummary.source;
    due_on: string;
    date_type?: ('best_before' | 'use_by' | null);
};
export namespace FreshnessSummary {
    export enum state {
        URGENT = 'urgent',
        SOON = 'soon',
        NORMAL = 'normal',
    }
    export enum source {
        EXACT_DATE = 'exact_date',
        CATEGORY_DEFAULT = 'category_default',
        HOUSEHOLD_OVERRIDE = 'household_override',
    }
}

