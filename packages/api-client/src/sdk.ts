import { OpenAPI } from "./generated/core/OpenAPI";
import { DefaultService } from "./generated/services/DefaultService";
import type {
  BatchLifecycleActionRequest,
  BatchLifecycleEventListResponse,
  BatchLifecycleListResponse,
  BatchLifecycleSummary,
  FreshnessOverrideRequest,
  FreshnessPolicyListResponse,
  FreshnessPolicySummary,
  ReminderPreviewResponse,
  ReminderSettingsRequest,
  ReminderSettingsSummary,
  HouseholdSessionRequest,
  KitchenAssistantQueryRequest,
  KitchenAssistantQueryResponse,
  TextCaptureConfirmRequest,
  TextCaptureConfirmResponse,
  TextCaptureDraftRequest,
  TextCaptureDraftResponse,
  PackagePhotoConfirmRequest,
  PackagePhotoDraftResponse,
  ShoppingListItemRequest,
  ShoppingListRequest,
  ShoppingListsResponse,
  ShoppingSuggestionAcceptRequest,
  TodayResponse,
  VoiceCaptureDraftResponse
} from "./generated";

export function createFreshbotClient(baseUrl: string) {
  return {
    createHouseholdSession: async (payload: HouseholdSessionRequest) => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.createHouseholdSession(payload);
    },
    getTodayDashboard: async (token: string): Promise<TodayResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.getTodayDashboard(`Bearer ${token}`);
    },
    listShoppingLists: async (token: string): Promise<ShoppingListsResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.listShoppingLists(`Bearer ${token}`);
    },
    createShoppingList: async (token: string, payload: ShoppingListRequest): Promise<ShoppingListsResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.createShoppingList(payload, `Bearer ${token}`);
    },
    renameShoppingList: async (
      token: string,
      listId: string,
      payload: ShoppingListRequest
    ): Promise<ShoppingListsResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.renameShoppingList(listId, payload, `Bearer ${token}`);
    },
    upsertShoppingListItem: async (
      token: string,
      listId: string,
      payload: ShoppingListItemRequest
    ): Promise<ShoppingListsResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.upsertShoppingListItem(listId, payload, `Bearer ${token}`);
    },
    removeShoppingListItem: async (
      token: string,
      listId: string,
      itemId: string
    ): Promise<ShoppingListsResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.removeShoppingListItem(listId, itemId, `Bearer ${token}`);
    },
    acceptShoppingSuggestion: async (
      token: string,
      suggestionId: string,
      payload: ShoppingSuggestionAcceptRequest
    ): Promise<ShoppingListsResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.acceptShoppingSuggestion(suggestionId, payload, `Bearer ${token}`);
    },
    listBatches: async (token: string): Promise<BatchLifecycleListResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.listBatches(`Bearer ${token}`);
    },
    actOnBatch: async (
      token: string,
      batchId: string,
      payload: BatchLifecycleActionRequest
    ): Promise<BatchLifecycleSummary> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.actOnBatch(batchId, payload, `Bearer ${token}`);
    },
    listBatchEvents: async (token: string, batchId: string): Promise<BatchLifecycleEventListResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.listBatchEvents(batchId, `Bearer ${token}`);
    },
    listFreshnessOverrides: async (token: string): Promise<FreshnessPolicyListResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.listFreshnessOverrides(`Bearer ${token}`);
    },
    queryKitchenAssistant: async (
      token: string,
      payload: KitchenAssistantQueryRequest
    ): Promise<KitchenAssistantQueryResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.queryKitchenAssistant(payload, `Bearer ${token}`);
    },
    saveFreshnessOverride: async (
      token: string,
      category: string,
      payload: FreshnessOverrideRequest
    ): Promise<FreshnessPolicySummary> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.saveFreshnessOverride(category, payload, `Bearer ${token}`);
    },
    getReminders: async (token: string): Promise<ReminderPreviewResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.getReminders(`Bearer ${token}`);
    },
    updateReminderSettings: async (
      token: string,
      payload: ReminderSettingsRequest
    ): Promise<ReminderSettingsSummary> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.updateReminderSettings(payload, `Bearer ${token}`);
    },
    dispatchReminders: async (token: string): Promise<ReminderPreviewResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.dispatchReminders(`Bearer ${token}`);
    },
    createTextCaptureDrafts: async (
      token: string,
      payload: TextCaptureDraftRequest
    ): Promise<TextCaptureDraftResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.createTextCaptureDrafts(payload, `Bearer ${token}`);
    },
    createVoiceCaptureDrafts: async (
      token: string,
      audioFile: Blob
    ): Promise<VoiceCaptureDraftResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.createVoiceCaptureDrafts({ audio_file: audioFile }, `Bearer ${token}`);
    },
    createPackagePhotoDrafts: async (
      token: string,
      photo: Blob
    ): Promise<PackagePhotoDraftResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.createPackagePhotoDrafts({ photo }, `Bearer ${token}`);
    },
    getPackagePhotoDrafts: async (
      token: string,
      captureId: string
    ): Promise<PackagePhotoDraftResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.getPackagePhotoDrafts(captureId, `Bearer ${token}`);
    },
    confirmTextCaptureDrafts: async (
      token: string,
      payload: TextCaptureConfirmRequest
    ): Promise<TextCaptureConfirmResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.confirmTextCaptureDrafts(payload, `Bearer ${token}`);
    },
    confirmPackagePhotoDrafts: async (
      token: string,
      payload: PackagePhotoConfirmRequest
    ): Promise<TextCaptureConfirmResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.confirmPackagePhotoDrafts(payload, `Bearer ${token}`);
    }
  };
}
