"use client";

import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  type BatchSummary,
  createFreshbotClient,
  type FreshnessPolicySummary,
  type FreshnessSummary,
  type HouseholdSessionResponse,
  type PackagePhotoDraft,
  type PackagePhotoDraftResponse,
  type TextCaptureDraft,
  type TodayResponse
} from "@freshbot-butler/api-client";

import { getMessages } from "../lib/copy";
import { SESSION_STORAGE_KEY } from "../lib/session";

type HouseholdShellProps = {
  apiBaseUrl: string;
  storage?: Storage;
};

type Status = "idle" | "submitting" | "loading" | "drafting" | "transcribing" | "saving" | "ready" | "error";
type DraftSource = "text" | "voice" | "package_photo" | null;
type ReviewDraft = TextCaptureDraft &
  Partial<Pick<PackagePhotoDraft, "requires_date_review" | "date_reviewed">>;

const PACKAGE_PHOTO_POLLING_DELAY_MS = 100;
const PACKAGE_PHOTO_POLLING_MAX_ATTEMPTS = 20;

function formatFreshnessLabel(freshness: FreshnessSummary | null | undefined) {
  switch (freshness?.state) {
    case "urgent":
      return "Dringend";
    case "soon":
      return "Bald";
    default:
      return "Gut";
  }
}

function formatFreshnessDetail(freshness: FreshnessSummary | null | undefined, locale: string) {
  if (!freshness) {
    return null;
  }

  const formattedDate = new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric"
  }).format(new Date(`${freshness.due_on}T12:00:00Z`));

  if (freshness.date_type === "use_by") {
    return `Zu verbrauchen bis ${formattedDate}`;
  }

  if (freshness.date_type === "best_before") {
    return `Mindestens haltbar bis ${formattedDate}`;
  }

  return `Geschätzt bis ${formattedDate}`;
}

function formatDateTypeLabel(dateType: string | null | undefined, messages: ReturnType<typeof getMessages>) {
  if (dateType === "use_by") {
    return messages.useByLabel;
  }
  if (dateType === "best_before") {
    return messages.bestBeforeLabel;
  }
  return messages.noDateLabel;
}

function FreshnessList({
  title,
  items,
  locale
}: {
  title: string;
  items: BatchSummary[];
  locale: string;
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <section className="stack gap-sm" aria-label={title}>
      <h3>{title}</h3>
      <ul className="stack gap-xs">
        {items.map((batch) => (
          <li key={`${title}-${batch.name}-${batch.location}-${batch.quantity}`} className="stack gap-xs">
            <strong>{batch.name}</strong>
            <span>{formatFreshnessLabel(batch.freshness)}</span>
            <span>{formatFreshnessDetail(batch.freshness, locale)}</span>
            <span>{batch.quantity}</span>
            <span>{batch.location}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function HouseholdShell({ apiBaseUrl, storage }: HouseholdShellProps) {
  const client = useMemo(() => createFreshbotClient(apiBaseUrl), [apiBaseUrl]);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const [householdName, setHouseholdName] = useState("");
  const [memberName, setMemberName] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [isRecording, setIsRecording] = useState(false);
  const [today, setToday] = useState<TodayResponse | null>(null);
  const [session, setSession] = useState<HouseholdSessionResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [captureInput, setCaptureInput] = useState("");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [packagePhotoFile, setPackagePhotoFile] = useState<File | null>(null);
  const [packagePhotoCaptureId, setPackagePhotoCaptureId] = useState<string | null>(null);
  const [draftSource, setDraftSource] = useState<DraftSource>(null);
  const [drafts, setDrafts] = useState<ReviewDraft[]>([]);
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [availableLocations, setAvailableLocations] = useState<string[]>([]);
  const [availableDateTypes, setAvailableDateTypes] = useState<string[]>([]);
  const [freshnessPolicies, setFreshnessPolicies] = useState<FreshnessPolicySummary[]>([]);
  const [savingFreshnessCategory, setSavingFreshnessCategory] = useState<string | null>(null);
  const browserStorage =
    storage ?? (typeof window === "undefined" ? undefined : window.localStorage);
  const locale = (today?.locale ?? session?.locale ?? "de-DE") as "de-DE";
  const messages = getMessages(locale);
  const inventory = today?.sections.inventory ?? [];
  const canRecordAudio =
    typeof MediaRecorder !== "undefined" &&
    typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices?.getUserMedia === "function";
  const needsAttention = today?.sections.needs_attention ?? [];
  const upcoming = today?.sections.upcoming ?? [];
  const hasPendingDateReview =
    draftSource === "package_photo" &&
    drafts.some((draft) => draft.requires_date_review && !draft.date_reviewed);

  useEffect(() => {
    if (browserStorage === undefined) {
      return;
    }
    const storedSession = browserStorage.getItem(SESSION_STORAGE_KEY);
    if (storedSession === null) {
      return;
    }

    const parsedSession = JSON.parse(storedSession) as HouseholdSessionResponse;
    setSession(parsedSession);
    void loadToday(parsedSession);
  }, [browserStorage]);

  async function loadToday(activeSession: HouseholdSessionResponse) {
    setStatus("loading");
    setErrorMessage(null);
    try {
      const nextToday = await client.getTodayDashboard(activeSession.token);
      try {
        const nextPolicies = await client.listFreshnessOverrides(activeSession.token);
        setFreshnessPolicies(nextPolicies.policies);
      } catch {
        setFreshnessPolicies([]);
      }
      setToday(nextToday);
      setStatus("ready");
    } catch {
      browserStorage?.removeItem(SESSION_STORAGE_KEY);
      setSession(null);
      setToday(null);
      setFreshnessPolicies([]);
      setStatus("error");
      setErrorMessage(messages.error);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("submitting");
    setErrorMessage(null);
    const nextSession = await client.createHouseholdSession({
      household_name: householdName,
      member_name: memberName
    });
    browserStorage?.setItem(SESSION_STORAGE_KEY, JSON.stringify(nextSession));
    setSession(nextSession);
    await loadToday(nextSession);
  }

  async function handleDraftSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (session === null) {
      return;
    }

    setStatus("drafting");
    setErrorMessage(null);

    try {
      const response = await client.createTextCaptureDrafts(session.token, {
        input_text: captureInput
      });
      setDraftSource("text");
      setPackagePhotoCaptureId(null);
      setDrafts(response.drafts);
      setAvailableCategories(response.available_categories);
      setAvailableLocations(response.available_locations);
      setAvailableDateTypes([]);
      setStatus("ready");
    } catch {
      setStatus("error");
      setErrorMessage(messages.captureError);
    }
  }

  async function handlePackagePhotoDraftSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (session === null || packagePhotoFile === null) {
      return;
    }

    setStatus("drafting");
    setErrorMessage(null);

    try {
      let response = await client.createPackagePhotoDrafts(session.token, packagePhotoFile);
      setDraftSource("package_photo");
      setPackagePhotoCaptureId(response.capture_id);
      applyPackagePhotoDraftResponse(response);
      if (response.status === "processing") {
        response = await waitForPackagePhotoDrafts(session.token, response.capture_id);
        applyPackagePhotoDraftResponse(response);
      }
      setStatus("ready");
    } catch {
      setStatus("error");
      setErrorMessage(messages.captureError);
    }
  }

  function applyPackagePhotoDraftResponse(response: PackagePhotoDraftResponse) {
    setDrafts(response.drafts);
    setAvailableCategories(response.available_categories);
    setAvailableLocations(response.available_locations);
    setAvailableDateTypes(response.available_date_types);
  }

  async function waitForPackagePhotoDrafts(
    token: string,
    captureId: string
  ): Promise<PackagePhotoDraftResponse> {
    let response = await client.getPackagePhotoDrafts(token, captureId);
    let attempts = 1;
    while (response.status === "processing") {
      if (attempts >= PACKAGE_PHOTO_POLLING_MAX_ATTEMPTS) {
        throw new Error("package photo extraction timed out");
      }
      await new Promise((resolve) => setTimeout(resolve, PACKAGE_PHOTO_POLLING_DELAY_MS));
      response = await client.getPackagePhotoDrafts(token, captureId);
      attempts += 1;
    }
    return response;
  }

  async function handleVoiceDraftSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (audioFile === null) {
      return;
    }

    await createVoiceDrafts(audioFile);
  }

  async function createVoiceDrafts(nextAudioFile: Blob) {
    if (session === null) {
      return;
    }

    setStatus("transcribing");
    setErrorMessage(null);

    try {
      const response = await client.createVoiceCaptureDrafts(session.token, nextAudioFile);
      setCaptureInput(response.transcript);
      setDraftSource("voice");
      setPackagePhotoCaptureId(null);
      setDrafts(response.drafts);
      setAvailableCategories(response.available_categories);
      setAvailableLocations(response.available_locations);
      setAvailableDateTypes([]);
      setStatus("ready");
    } catch {
      setStatus("error");
      setErrorMessage(messages.captureError);
    }
  }

  async function startRecording() {
    if (!canRecordAudio) {
      return;
    }

    setErrorMessage(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      mediaStreamRef.current = stream;
      mediaRecorderRef.current = recorder;
      recordedChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          recordedChunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const recordedAudio = new File(recordedChunksRef.current, "voice-capture.webm", {
          type: recordedChunksRef.current[0]?.type || "audio/webm"
        });
        mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
        mediaStreamRef.current = null;
        mediaRecorderRef.current = null;
        recordedChunksRef.current = [];
        setIsRecording(false);
        void createVoiceDrafts(recordedAudio);
      };
      recorder.start();
      setIsRecording(true);
    } catch {
      setStatus("error");
      setErrorMessage(messages.captureError);
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
  }

  async function handleConfirmDrafts() {
    if (session === null || drafts.length === 0) {
      return;
    }

    setStatus("saving");
    setErrorMessage(null);

    try {
      if (draftSource === "package_photo" && packagePhotoCaptureId !== null) {
        await client.confirmPackagePhotoDrafts(session.token, {
          capture_id: packagePhotoCaptureId,
          drafts
        });
      } else {
        await client.confirmTextCaptureDrafts(session.token, { drafts });
      }
      setDrafts([]);
      setCaptureInput("");
      setAudioFile(null);
      setPackagePhotoFile(null);
      setPackagePhotoCaptureId(null);
      setDraftSource(null);
      setAvailableDateTypes([]);
      setIsRecording(false);
      await loadToday(session);
    } catch {
      setStatus("error");
      setErrorMessage(messages.captureError);
    }
  }

  function updateDraft(index: number, field: keyof ReviewDraft, value: string) {
    setDrafts((currentDrafts) =>
      currentDrafts.map((draft, draftIndex) =>
        draftIndex === index
          ? {
              ...draft,
              [field]: value,
              date_reviewed:
                (field === "date_type" || field === "expires_on") && draft.requires_date_review
                  ? true
                  : draft.date_reviewed
            }
          : draft
      )
    );
  }

  function updateDraftReview(index: number, dateReviewed: boolean) {
    setDrafts((currentDrafts) =>
      currentDrafts.map((draft, draftIndex) =>
        draftIndex === index ? { ...draft, date_reviewed: dateReviewed } : draft
      )
    );
  }

  function updateFreshnessPolicy(
    category: string,
    field: "shelf_life_days" | "soon_window_days",
    value: number
  ) {
    setFreshnessPolicies((currentPolicies) =>
      currentPolicies.map((policy) =>
        policy.category === category ? { ...policy, [field]: Math.max(0, value) } : policy
      )
    );
  }

  async function handleSaveFreshnessPolicy(category: string) {
    if (session === null) {
      return;
    }

    const policy = freshnessPolicies.find((entry) => entry.category === category);
    if (!policy) {
      return;
    }

    setSavingFreshnessCategory(category);
    setErrorMessage(null);

    try {
      const savedPolicy = await client.saveFreshnessOverride(session.token, category, {
        shelf_life_days: policy.shelf_life_days,
        soon_window_days: policy.soon_window_days
      });
      setFreshnessPolicies((currentPolicies) =>
        currentPolicies.map((currentPolicy) =>
          currentPolicy.category === category ? savedPolicy : currentPolicy
        )
      );
      await loadToday(session);
    } catch {
      setStatus("error");
      setErrorMessage(messages.freshnessRuleError);
    } finally {
      setSavingFreshnessCategory(null);
    }
  }

  function resetSession() {
    browserStorage?.removeItem(SESSION_STORAGE_KEY);
    setSession(null);
    setToday(null);
    setCaptureInput("");
    setAudioFile(null);
    setPackagePhotoFile(null);
    setPackagePhotoCaptureId(null);
    setDraftSource(null);
    setIsRecording(false);
    setDrafts([]);
    setAvailableCategories([]);
    setAvailableLocations([]);
    setAvailableDateTypes([]);
    setFreshnessPolicies([]);
    setSavingFreshnessCategory(null);
    setStatus("idle");
    setErrorMessage(null);
  }

  return (
    <main className="shell">
      <section className="card">
        <header className="stack gap-sm">
          <p className="eyebrow">{messages.appName}</p>
          <h1>{messages.title}</h1>
          <p className="muted">{messages.subtitle}</p>
        </header>

        {today ? (
          <div className="stack gap-md">
            <div className="stack gap-xs">
              <p className="welcome">{messages.welcome(today.member_name)}</p>
              <p className="muted">{today.household_name}</p>
            </div>
            <section className="dashboard-panel stack gap-md">
              <h2>{today.household_name}</h2>
              {needsAttention.length === 0 && upcoming.length === 0 ? (
                <p>{messages.emptyToday}</p>
              ) : (
                <>
                  <FreshnessList title={messages.urgentTitle} items={needsAttention} locale={locale} />
                  <FreshnessList title={messages.soonTitle} items={upcoming} locale={locale} />
                </>
              )}
            </section>
            <section className="dashboard-panel stack gap-sm">
              <h2>{messages.inventoryTitle}</h2>
              {inventory.length === 0 ? (
                <p>{messages.emptyInventory}</p>
              ) : (
                <ul className="stack gap-xs">
                  {inventory.map((batch) => (
                    <li key={`${batch.name}-${batch.location}-${batch.quantity}`} className="stack gap-xs">
                      <strong>{batch.name}</strong>
                      <span>{formatFreshnessLabel(batch.freshness)}</span>
                      <span>{formatFreshnessDetail(batch.freshness, locale)}</span>
                      <span>{batch.quantity}</span>
                      <span>{batch.category}</span>
                      <span>{batch.location}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section className="dashboard-panel stack gap-md">
              <h2>{messages.reviewTitle}</h2>
              <form className="stack gap-sm" onSubmit={(event) => void handleDraftSubmit(event)}>
                <label className="stack gap-xs">
                  <span>{messages.textCaptureLabel}</span>
                  <textarea
                    name="textCapture"
                    value={captureInput}
                    onChange={(event) => setCaptureInput(event.target.value)}
                    required
                  />
                </label>
                <button
                  type="submit"
                  disabled={
                    status === "drafting" || status === "transcribing" || status === "saving" || status === "loading"
                  }
                >
                  {status === "drafting" ? messages.drafting : messages.createDraftsLabel}
                </button>
              </form>
              <form className="stack gap-sm" onSubmit={(event) => void handleVoiceDraftSubmit(event)}>
                <label className="stack gap-xs" htmlFor="voiceCapture">
                  <span>{messages.voiceUploadLabel}</span>
                  <input
                    id="voiceCapture"
                    type="file"
                    accept="audio/*"
                    onChange={(event) => setAudioFile(event.target.files?.[0] ?? null)}
                  />
                </label>
                <button
                  type="submit"
                  disabled={
                    audioFile === null || status === "transcribing" || status === "saving" || status === "loading"
                  }
                >
                  {status === "transcribing" ? messages.transcribing : messages.transcribeAudioLabel}
                </button>
              </form>
              <form className="stack gap-sm" onSubmit={(event) => void handlePackagePhotoDraftSubmit(event)}>
                <label className="stack gap-xs" htmlFor="packagePhoto">
                  <span>{messages.packagePhotoLabel}</span>
                  <input
                    id="packagePhoto"
                    type="file"
                    accept="image/*"
                    onChange={(event) => setPackagePhotoFile(event.target.files?.[0] ?? null)}
                  />
                </label>
                <button
                  type="submit"
                  disabled={
                    packagePhotoFile === null ||
                    status === "drafting" ||
                    status === "transcribing" ||
                    status === "saving" ||
                    status === "loading"
                  }
                >
                  {status === "drafting" && packagePhotoFile !== null
                    ? messages.drafting
                    : messages.createPackagePhotoDraftsLabel}
                </button>
              </form>
              {canRecordAudio ? (
                <button
                  type="button"
                  onClick={() => {
                    if (isRecording) {
                      stopRecording();
                      return;
                    }
                    void startRecording();
                  }}
                  disabled={status === "transcribing" || status === "saving" || status === "loading"}
                >
                  {isRecording ? messages.stopRecordingLabel : messages.startRecordingLabel}
                </button>
              ) : null}

              {drafts.length > 0 ? (
                <div className="stack gap-md">
                  {drafts.map((draft, index) => (
                    <fieldset key={index} className="stack gap-sm" aria-label={messages.draftLabel(index + 1)}>
                      <label className="stack gap-xs" htmlFor={`draft-${index}-name`}>
                        <span>{messages.batchNameLabel}</span>
                        <input
                          id={`draft-${index}-name`}
                          aria-label={messages.batchNameLabel}
                          value={draft.name}
                          onChange={(event) => updateDraft(index, "name", event.target.value)}
                        />
                      </label>
                      <label className="stack gap-xs" htmlFor={`draft-${index}-quantity`}>
                        <span>{messages.batchQuantityLabel}</span>
                        <input
                          id={`draft-${index}-quantity`}
                          aria-label={messages.batchQuantityLabel}
                          value={draft.quantity}
                          onChange={(event) => updateDraft(index, "quantity", event.target.value)}
                        />
                      </label>
                      <label className="stack gap-xs" htmlFor={`draft-${index}-category`}>
                        <span>{messages.batchCategoryLabel}</span>
                        <select
                          id={`draft-${index}-category`}
                          aria-label={messages.batchCategoryLabel}
                          value={draft.category}
                          onChange={(event) => updateDraft(index, "category", event.target.value)}
                        >
                          {availableCategories.map((category) => (
                            <option key={category} value={category}>
                              {category}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="stack gap-xs" htmlFor={`draft-${index}-location`}>
                        <span>{messages.batchLocationLabel}</span>
                        <select
                          id={`draft-${index}-location`}
                          aria-label={messages.batchLocationLabel}
                          value={draft.location}
                          onChange={(event) => updateDraft(index, "location", event.target.value)}
                        >
                          {availableLocations.map((location) => (
                            <option key={location} value={location}>
                              {location}
                            </option>
                          ))}
                        </select>
                      </label>
                      {draftSource === "package_photo" ? (
                        <>
                          <label className="stack gap-xs" htmlFor={`draft-${index}-date-type`}>
                            <span>{messages.dateTypeLabel}</span>
                            <select
                              id={`draft-${index}-date-type`}
                              aria-label={messages.dateTypeLabel}
                              value={draft.date_type ?? ""}
                              onChange={(event) => updateDraft(index, "date_type", event.target.value)}
                            >
                              <option value="">{messages.noDateLabel}</option>
                              {availableDateTypes.map((dateType) => (
                                <option key={dateType} value={dateType}>
                                  {formatDateTypeLabel(dateType, messages)}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="stack gap-xs" htmlFor={`draft-${index}-expires-on`}>
                            <span>{messages.expiresOnLabel}</span>
                            <input
                              id={`draft-${index}-expires-on`}
                              aria-label={messages.expiresOnLabel}
                              type="date"
                              value={draft.expires_on ?? ""}
                              onChange={(event) => updateDraft(index, "expires_on", event.target.value)}
                            />
                          </label>
                          {draft.requires_date_review ? (
                            <label className="stack gap-xs" htmlFor={`draft-${index}-date-reviewed`}>
                              <span>{messages.reviewDateHelp}</span>
                              <input
                                id={`draft-${index}-date-reviewed`}
                                aria-label={messages.reviewDateLabel}
                                type="checkbox"
                                checked={Boolean(draft.date_reviewed)}
                                onChange={(event) => updateDraftReview(index, event.target.checked)}
                              />
                            </label>
                          ) : null}
                        </>
                      ) : null}
                    </fieldset>
                  ))}
                  <button
                    type="button"
                    onClick={() => void handleConfirmDrafts()}
                    disabled={status === "saving" || status === "loading" || hasPendingDateReview}
                  >
                    {status === "saving" ? messages.saving : messages.saveDraftsLabel}
                  </button>
                </div>
              ) : null}
            </section>
            {freshnessPolicies.length > 0 ? (
              <section className="dashboard-panel stack gap-md">
                <h2>{messages.freshnessSettingsTitle}</h2>
                {freshnessPolicies.map((policy) => (
                  <fieldset
                    key={policy.category}
                    className="stack gap-sm"
                    aria-label={`Frische-Regel ${policy.category}`}
                  >
                    <legend>{policy.category}</legend>
                    <p>{policy.is_override ? messages.activeOverrideLabel : messages.defaultRuleLabel}</p>
                    <label className="stack gap-xs" htmlFor={`freshness-${policy.category}-shelf-life`}>
                      <span>{messages.freshnessShelfLifeLabel}</span>
                      <input
                        id={`freshness-${policy.category}-shelf-life`}
                        aria-label={messages.freshnessShelfLifeLabel}
                        type="number"
                        min={0}
                        value={policy.shelf_life_days}
                        onChange={(event) =>
                          updateFreshnessPolicy(
                            policy.category,
                            "shelf_life_days",
                            Number.parseInt(event.target.value || "0", 10)
                          )
                        }
                      />
                    </label>
                    <label className="stack gap-xs" htmlFor={`freshness-${policy.category}-soon-window`}>
                      <span>{messages.freshnessSoonWindowLabel}</span>
                      <input
                        id={`freshness-${policy.category}-soon-window`}
                        aria-label={messages.freshnessSoonWindowLabel}
                        type="number"
                        min={0}
                        value={policy.soon_window_days}
                        onChange={(event) =>
                          updateFreshnessPolicy(
                            policy.category,
                            "soon_window_days",
                            Number.parseInt(event.target.value || "0", 10)
                          )
                        }
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => void handleSaveFreshnessPolicy(policy.category)}
                      disabled={status === "loading" || savingFreshnessCategory === policy.category}
                    >
                      {savingFreshnessCategory === policy.category
                        ? messages.savingFreshnessRuleLabel
                        : messages.saveFreshnessRuleLabel}
                    </button>
                  </fieldset>
                ))}
              </section>
            ) : null}
            <button type="button" className="ghost-button" onClick={resetSession}>
              {messages.switchHousehold}
            </button>
          </div>
        ) : (
          <form className="stack gap-md" onSubmit={(event) => void handleSubmit(event)}>
            <label className="stack gap-xs">
              <span>{messages.householdNameLabel}</span>
              <input
                name="householdName"
                value={householdName}
                onChange={(event) => setHouseholdName(event.target.value)}
                required
              />
            </label>
            <label className="stack gap-xs">
              <span>{messages.memberNameLabel}</span>
              <input
                name="memberName"
                value={memberName}
                onChange={(event) => setMemberName(event.target.value)}
                required
              />
            </label>
            <button type="submit" disabled={status === "submitting" || status === "loading"}>
              {status === "submitting" || status === "loading" ? messages.loading : messages.submitLabel}
            </button>
          </form>
        )}

        {errorMessage ? <p role="alert">{errorMessage}</p> : null}
      </section>
    </main>
  );
}
