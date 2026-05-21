/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { BatchLifecycleActionRequest } from '../models/BatchLifecycleActionRequest';
import type { BatchLifecycleEventListResponse } from '../models/BatchLifecycleEventListResponse';
import type { BatchLifecycleListResponse } from '../models/BatchLifecycleListResponse';
import type { BatchLifecycleSummary } from '../models/BatchLifecycleSummary';
import type { Body_createPackagePhotoDrafts } from '../models/Body_createPackagePhotoDrafts';
import type { Body_createVoiceCaptureDrafts } from '../models/Body_createVoiceCaptureDrafts';
import type { FreshnessOverrideRequest } from '../models/FreshnessOverrideRequest';
import type { FreshnessPolicyListResponse } from '../models/FreshnessPolicyListResponse';
import type { FreshnessPolicySummary } from '../models/FreshnessPolicySummary';
import type { HouseholdSessionRequest } from '../models/HouseholdSessionRequest';
import type { HouseholdSessionResponse } from '../models/HouseholdSessionResponse';
import type { KitchenAssistantQueryRequest } from '../models/KitchenAssistantQueryRequest';
import type { KitchenAssistantQueryResponse } from '../models/KitchenAssistantQueryResponse';
import type { PackagePhotoConfirmRequest } from '../models/PackagePhotoConfirmRequest';
import type { PackagePhotoDraftResponse } from '../models/PackagePhotoDraftResponse';
import type { ReminderPreviewResponse } from '../models/ReminderPreviewResponse';
import type { ReminderSettingsRequest } from '../models/ReminderSettingsRequest';
import type { ReminderSettingsSummary } from '../models/ReminderSettingsSummary';
import type { ShoppingListItemRequest } from '../models/ShoppingListItemRequest';
import type { ShoppingListRequest } from '../models/ShoppingListRequest';
import type { ShoppingListsResponse } from '../models/ShoppingListsResponse';
import type { ShoppingSuggestionAcceptRequest } from '../models/ShoppingSuggestionAcceptRequest';
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
     * List Shopping Lists
     * @param authorization
     * @returns ShoppingListsResponse Successful Response
     * @throws ApiError
     */
    public static listShoppingLists(
        authorization?: (string | null),
    ): CancelablePromise<ShoppingListsResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/shopping-lists',
            headers: {
                'authorization': authorization,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Shopping List
     * @param requestBody
     * @param authorization
     * @returns ShoppingListsResponse Successful Response
     * @throws ApiError
     */
    public static createShoppingList(
        requestBody: ShoppingListRequest,
        authorization?: (string | null),
    ): CancelablePromise<ShoppingListsResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/shopping-lists',
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
     * Rename Shopping List
     * @param listId
     * @param requestBody
     * @param authorization
     * @returns ShoppingListsResponse Successful Response
     * @throws ApiError
     */
    public static renameShoppingList(
        listId: string,
        requestBody: ShoppingListRequest,
        authorization?: (string | null),
    ): CancelablePromise<ShoppingListsResponse> {
        return __request(OpenAPI, {
            method: 'PUT',
            url: '/api/shopping-lists/{list_id}',
            path: {
                'list_id': listId,
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
     * Upsert Shopping List Item
     * @param listId
     * @param requestBody
     * @param authorization
     * @returns ShoppingListsResponse Successful Response
     * @throws ApiError
     */
    public static upsertShoppingListItem(
        listId: string,
        requestBody: ShoppingListItemRequest,
        authorization?: (string | null),
    ): CancelablePromise<ShoppingListsResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/shopping-lists/{list_id}/items',
            path: {
                'list_id': listId,
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
     * Remove Shopping List Item
     * @param listId
     * @param itemId
     * @param authorization
     * @returns ShoppingListsResponse Successful Response
     * @throws ApiError
     */
    public static removeShoppingListItem(
        listId: string,
        itemId: string,
        authorization?: (string | null),
    ): CancelablePromise<ShoppingListsResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/shopping-lists/{list_id}/items/{item_id}',
            path: {
                'list_id': listId,
                'item_id': itemId,
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
     * Accept Shopping Suggestion
     * @param suggestionId
     * @param requestBody
     * @param authorization
     * @returns ShoppingListsResponse Successful Response
     * @throws ApiError
     */
    public static acceptShoppingSuggestion(
        suggestionId: string,
        requestBody: ShoppingSuggestionAcceptRequest,
        authorization?: (string | null),
    ): CancelablePromise<ShoppingListsResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/shopping-suggestions/{suggestion_id}/accept',
            path: {
                'suggestion_id': suggestionId,
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
     * Query Kitchen Assistant
     * @param requestBody
     * @param authorization
     * @returns KitchenAssistantQueryResponse Successful Response
     * @throws ApiError
     */
    public static queryKitchenAssistant(
        requestBody: KitchenAssistantQueryRequest,
        authorization?: (string | null),
    ): CancelablePromise<KitchenAssistantQueryResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/kitchen-assistant/query',
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
     * List Batches
     * @param authorization
     * @returns BatchLifecycleListResponse Successful Response
     * @throws ApiError
     */
    public static listBatches(
        authorization?: (string | null),
    ): CancelablePromise<BatchLifecycleListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/batches',
            headers: {
                'authorization': authorization,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Act On Batch
     * @param batchId
     * @param requestBody
     * @param authorization
     * @returns BatchLifecycleSummary Successful Response
     * @throws ApiError
     */
    public static actOnBatch(
        batchId: string,
        requestBody: BatchLifecycleActionRequest,
        authorization?: (string | null),
    ): CancelablePromise<BatchLifecycleSummary> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/batches/{batch_id}/actions',
            path: {
                'batch_id': batchId,
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
     * List Batch Events
     * @param batchId
     * @param authorization
     * @returns BatchLifecycleEventListResponse Successful Response
     * @throws ApiError
     */
    public static listBatchEvents(
        batchId: string,
        authorization?: (string | null),
    ): CancelablePromise<BatchLifecycleEventListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/batches/{batch_id}/events',
            path: {
                'batch_id': batchId,
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
     * Get Reminders
     * @param authorization
     * @returns ReminderPreviewResponse Successful Response
     * @throws ApiError
     */
    public static getReminders(
        authorization?: (string | null),
    ): CancelablePromise<ReminderPreviewResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/reminders',
            headers: {
                'authorization': authorization,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Reminder Settings
     * @param requestBody
     * @param authorization
     * @returns ReminderSettingsSummary Successful Response
     * @throws ApiError
     */
    public static updateReminderSettings(
        requestBody: ReminderSettingsRequest,
        authorization?: (string | null),
    ): CancelablePromise<ReminderSettingsSummary> {
        return __request(OpenAPI, {
            method: 'PUT',
            url: '/api/reminder-settings',
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
     * Dispatch Reminders
     * @param authorization
     * @returns ReminderPreviewResponse Successful Response
     * @throws ApiError
     */
    public static dispatchReminders(
        authorization?: (string | null),
    ): CancelablePromise<ReminderPreviewResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/reminders/dispatch',
            headers: {
                'authorization': authorization,
            },
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
