/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PackagePhotoDraft } from './PackagePhotoDraft';
export type PackagePhotoDraftResponse = {
    capture_id: string;
    status: PackagePhotoDraftResponse.status;
    drafts: Array<PackagePhotoDraft>;
    available_categories: Array<string>;
    available_locations: Array<string>;
    available_date_types: Array<'best_before' | 'use_by'>;
};
export namespace PackagePhotoDraftResponse {
    export enum status {
        PROCESSING = 'processing',
        PENDING_REVIEW = 'pending_review',
        CONFIRMED = 'confirmed',
        FAILED = 'failed',
    }
}

