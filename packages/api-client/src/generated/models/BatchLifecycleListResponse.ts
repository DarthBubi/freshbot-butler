/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { BatchLifecycleSummary } from './BatchLifecycleSummary';
import type { BatchMergeSuggestion } from './BatchMergeSuggestion';
export type BatchLifecycleListResponse = {
    batches: Array<BatchLifecycleSummary>;
    merge_suggestions?: Array<BatchMergeSuggestion>;
};

