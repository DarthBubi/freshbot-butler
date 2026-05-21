import { OpenAPI } from "./generated/core/OpenAPI";
import { DefaultService } from "./generated/services/DefaultService";
import type {
  FreshnessOverrideRequest,
  FreshnessPolicyListResponse,
  FreshnessPolicySummary,
  HouseholdSessionRequest,
  TextCaptureConfirmRequest,
  TextCaptureConfirmResponse,
  TextCaptureDraftRequest,
  TextCaptureDraftResponse,
  PackagePhotoConfirmRequest,
  PackagePhotoDraftResponse,
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
    listFreshnessOverrides: async (token: string): Promise<FreshnessPolicyListResponse> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.listFreshnessOverrides(`Bearer ${token}`);
    },
    saveFreshnessOverride: async (
      token: string,
      category: string,
      payload: FreshnessOverrideRequest
    ): Promise<FreshnessPolicySummary> => {
      OpenAPI.BASE = baseUrl;
      return DefaultService.saveFreshnessOverride(category, payload, `Bearer ${token}`);
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
