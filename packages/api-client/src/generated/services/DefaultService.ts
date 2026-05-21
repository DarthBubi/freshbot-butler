/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { Body_createPackagePhotoDrafts } from '../models/Body_createPackagePhotoDrafts';
import type { Body_createVoiceCaptureDrafts } from '../models/Body_createVoiceCaptureDrafts';
import type { FreshnessOverrideRequest } from '../models/FreshnessOverrideRequest';
import type { FreshnessPolicyListResponse } from '../models/FreshnessPolicyListResponse';
import type { FreshnessPolicySummary } from '../models/FreshnessPolicySummary';
import type { HouseholdSessionRequest } from '../models/HouseholdSessionRequest';
import type { HouseholdSessionResponse } from '../models/HouseholdSessionResponse';
import type { PackagePhotoConfirmRequest } from '../models/PackagePhotoConfirmRequest';
import type { PackagePhotoDraftResponse } from '../models/PackagePhotoDraftResponse';
import type { TextCaptureConfirmRequest } from '../models/TextCaptureConfirmRequest';
import type { TextCaptureConfirmResponse } from '../models/TextCaptureConfirmResponse';
import type { TextCaptureDraftRequest } from '../models/TextCaptureDraftRequest';
import type { TextCaptureDraftResponse } from '../models/TextCaptureDraftResponse';
import type { TodayResponse } from '../models/TodayResponse';
import type { VoiceCaptureDraftResponse } from '../models/VoiceCaptureDraftResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class DefaultService {
    /**
     * Healthcheck
     * @returns string Successful Response
     * @throws ApiError
     */
    public static getHealth(): CancelablePromise<Record<string, string>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/health',
        });
    }
    /**
     * Create Household Session
     * @param requestBody
     * @returns HouseholdSessionResponse Successful Response
     * @throws ApiError
     */
    public static createHouseholdSession(
        requestBody: HouseholdSessionRequest,
    ): CancelablePromise<HouseholdSessionResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/auth/household-session',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Today
     * @param authorization
     * @returns TodayResponse Successful Response
     * @throws ApiError
     */
    public static getTodayDashboard(
        authorization?: (string | null),
    ): CancelablePromise<TodayResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/today',
            headers: {
                'authorization': authorization,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Freshness Overrides
     * @param authorization
     * @returns FreshnessPolicyListResponse Successful Response
     * @throws ApiError
     */
    public static listFreshnessOverrides(
        authorization?: (string | null),
    ): CancelablePromise<FreshnessPolicyListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/freshness-overrides',
            headers: {
                'authorization': authorization,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Save Freshness Override
     * @param category
     * @param requestBody
     * @param authorization
     * @returns FreshnessPolicySummary Successful Response
     * @throws ApiError
     */
    public static saveFreshnessOverride(
        category: string,
        requestBody: FreshnessOverrideRequest,
        authorization?: (string | null),
    ): CancelablePromise<FreshnessPolicySummary> {
        return __request(OpenAPI, {
            method: 'PUT',
            url: '/api/freshness-overrides/{category}',
            path: {
                'category': category,
            },
            headers: {
                'authorization': authorization,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Text Capture Drafts
     * @param requestBody
     * @param authorization
     * @returns TextCaptureDraftResponse Successful Response
     * @throws ApiError
     */
    public static createTextCaptureDrafts(
        requestBody: TextCaptureDraftRequest,
        authorization?: (string | null),
    ): CancelablePromise<TextCaptureDraftResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/text-capture/drafts',
            headers: {
                'authorization': authorization,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Voice Capture Drafts
     * @param formData
     * @param authorization
     * @returns VoiceCaptureDraftResponse Successful Response
     * @throws ApiError
     */
    public static createVoiceCaptureDrafts(
        formData: Body_createVoiceCaptureDrafts,
        authorization?: (string | null),
    ): CancelablePromise<VoiceCaptureDraftResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/voice-capture/drafts',
            headers: {
                'authorization': authorization,
            },
            formData: formData,
            mediaType: 'multipart/form-data',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Package Photo Drafts
     * @param formData
     * @param authorization
     * @returns PackagePhotoDraftResponse Successful Response
     * @throws ApiError
     */
    public static createPackagePhotoDrafts(
        formData: Body_createPackagePhotoDrafts,
        authorization?: (string | null),
    ): CancelablePromise<PackagePhotoDraftResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/package-photo/drafts',
            headers: {
                'authorization': authorization,
            },
            formData: formData,
            mediaType: 'multipart/form-data',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Package Photo Drafts
     * @param captureId
     * @param authorization
     * @returns PackagePhotoDraftResponse Successful Response
     * @throws ApiError
     */
    public static getPackagePhotoDrafts(
        captureId: string,
        authorization?: (string | null),
    ): CancelablePromise<PackagePhotoDraftResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/package-photo/drafts/{capture_id}',
            path: {
                'capture_id': captureId,
            },
            headers: {
                'authorization': authorization,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Confirm Text Capture Drafts
     * @param requestBody
     * @param authorization
     * @returns TextCaptureConfirmResponse Successful Response
     * @throws ApiError
     */
    public static confirmTextCaptureDrafts(
        requestBody: TextCaptureConfirmRequest,
        authorization?: (string | null),
    ): CancelablePromise<TextCaptureConfirmResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/text-capture/confirm',
            headers: {
                'authorization': authorization,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Confirm Package Photo Drafts
     * @param requestBody
     * @param authorization
     * @returns TextCaptureConfirmResponse Successful Response
     * @throws ApiError
     */
    public static confirmPackagePhotoDrafts(
        requestBody: PackagePhotoConfirmRequest,
        authorization?: (string | null),
    ): CancelablePromise<TextCaptureConfirmResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/package-photo/confirm',
            headers: {
                'authorization': authorization,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
