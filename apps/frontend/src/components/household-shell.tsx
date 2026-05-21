"use client";

import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  type BatchLifecycleListResponse,
  type BatchLifecycleSummary,
  type BatchMergeSuggestion,
  type BatchLifecycleActionRequest,
  type BatchSummary,
  createFreshbotClient,
  type FreshnessPolicySummary,
  type FreshnessSummary,
  type KitchenAssistantQueryResponse,
  type HouseholdSessionResponse,
  type PackagePhotoDraft,
  type PackagePhotoDraftResponse,
  type ReminderPreviewResponse,
  type ShoppingListItemSummary,
  type ShoppingListSummary,
  type ShoppingListsResponse,
  type ShoppingReplenishmentSuggestionSummary,
  type TextCaptureDraft,
  type TodayResponse
} from "@freshbot-butler/api-client";

import { getMessages } from "../lib/copy";
import { SESSION_STORAGE_KEY } from "../lib/session";

type HouseholdShellProps = {
  apiBaseUrl: string;
  storage?: Storage;
};

type Status =
  | "idle"
  | "submitting"
  | "loading"
  | "drafting"
  | "processing"
  | "transcribing"
  | "saving"
  | "ready"
  | "error";
type DraftSource = "text" | "voice" | "package_photo" | null;
type ReviewDraft = TextCaptureDraft &
  Partial<Pick<PackagePhotoDraft, "requires_date_review" | "date_reviewed">>;
type BatchLifecycleEvent = NonNullable<BatchLifecycleSummary["events"]>[number];
type CachedHouseholdState = {
  today: TodayResponse | null;
  batchView: BatchLifecycleListResponse | null;
  shoppingView: ShoppingListsResponse | null;
  freshnessPolicies: FreshnessPolicySummary[];
  reminders: ReminderPreviewResponse | null;
};
type QueuedMutation =
  | { kind: "batch-action"; batchId: string; action: BatchLifecycleActionRequest["action"] }
  | { kind: "create-shopping-list"; name: string }
  | { kind: "rename-shopping-list"; listId: string; name: string }
  | { kind: "upsert-shopping-list-item"; listId: string; name: string; quantity: string }
  | { kind: "remove-shopping-list-item"; listId: string; itemId: string }
  | { kind: "accept-shopping-suggestion"; suggestionId: string; listId: string }
  | {
      kind: "save-freshness-override";
      category: string;
      shelf_life_days: number;
      soon_window_days: number;
    };

const PACKAGE_PHOTO_POLLING_DELAY_MS = 100;
const HOUSEHOLD_REFRESH_INTERVAL_MS = 5000;
const HOUSEHOLD_CACHE_PREFIX = "freshbot.householdCache:";
const HOUSEHOLD_QUEUE_PREFIX = "freshbot.householdQueue:";

function cacheKey(token: string) {
  return `${HOUSEHOLD_CACHE_PREFIX}${token}`;
}

function queueKey(token: string) {
  return `${HOUSEHOLD_QUEUE_PREFIX}${token}`;
}

function readJson<T>(storage: Storage | undefined, key: string): T | null {
  if (storage === undefined) {
    return null;
  }

  const raw = storage.getItem(key);
  if (raw === null) {
    return null;
  }

  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function writeJson(storage: Storage | undefined, key: string, value: unknown) {
  if (storage === undefined) {
    return;
  }

  storage.setItem(key, JSON.stringify(value));
}

function readCachedHouseholdState(storage: Storage | undefined, token: string): CachedHouseholdState | null {
  const cached = readJson<Partial<CachedHouseholdState>>(storage, cacheKey(token));
  if (!cached) {
    return null;
  }

  return {
    today: cached.today ?? null,
    batchView: cached.batchView ?? null,
    shoppingView: cached.shoppingView ?? null,
    freshnessPolicies: cached.freshnessPolicies ?? [],
    reminders: cached.reminders ?? null
  };
}

function writeCachedHouseholdState(
  storage: Storage | undefined,
  token: string,
  state: CachedHouseholdState
) {
  writeJson(storage, cacheKey(token), state);
}

function readQueuedMutations(storage: Storage | undefined, token: string): QueuedMutation[] {
  return readJson<QueuedMutation[]>(storage, queueKey(token)) ?? [];
}

function writeQueuedMutations(storage: Storage | undefined, token: string, mutations: QueuedMutation[]) {
  writeJson(storage, queueKey(token), mutations);
}

function isNetworkError(error: unknown) {
  return (
    error instanceof TypeError ||
    (error instanceof Error && /fetch|network|offline/i.test(error.message))
  );
}

function formatBatchState(state: BatchLifecycleSummary["state"]) {
  switch (state) {
    case "opened":
      return "Geöffnet";
    case "depleted":
      return "Verbraucht";
    case "discarded":
      return "Entsorgt";
    default:
      return "Versiegelt";
  }
}

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
        {items.map((batch, index) => (
          <li key={`${title}-${index}-${batch.name}-${batch.location}-${batch.quantity}`} className="stack gap-xs">
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

function BatchEventList({
  events,
  locale
}: {
  events: BatchLifecycleEvent[];
  locale: string;
}) {
  if (events.length === 0) {
    return <p>Kein Verlauf erfasst.</p>;
  }

  return (
    <ol className="stack gap-xs">
      {events.map((event) => (
        <li key={`${event.action}-${event.created_at}-${event.member_name}`}>
          <strong>{formatBatchEvent(event.action)}</strong>
          <span>{event.member_name}</span>
          <span>{new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(new Date(event.created_at))}</span>
        </li>
      ))}
    </ol>
  );
}

function formatBatchEvent(action: BatchLifecycleEvent["action"]) {
  switch (action) {
    case "opened":
      return "Geöffnet";
    case "decremented":
      return "Verringert";
    case "used_up":
      return "Verbraucht";
    case "discarded":
      return "Entsorgt";
  }
}

function BatchManagementList({
  batches,
  mergeSuggestions,
  locale,
  onAction,
  labels
}: {
  batches: BatchLifecycleSummary[];
  mergeSuggestions: BatchMergeSuggestion[];
  locale: string;
  onAction: (batchId: string, action: "open" | "decrement" | "use_up" | "discard") => Promise<void>;
  labels: {
    title: string;
    empty: string;
    duplicateSuggestionsTitle: string;
    historyTitle: string;
    open: string;
    decrement: string;
    useUp: string;
    discard: string;
  };
}) {
  return (
    <section className="dashboard-panel stack gap-sm">
      <h2>{labels.title}</h2>
      {mergeSuggestions.length > 0 ? (
        <div className="stack gap-xs" aria-label={labels.duplicateSuggestionsTitle}>
          <strong>{labels.duplicateSuggestionsTitle}</strong>
          <ul className="stack gap-xs">
            {mergeSuggestions.map((suggestion) => (
              <li key={`${suggestion.name}-${suggestion.location}-${suggestion.category}`}>
                {suggestion.name} · {suggestion.count} · {suggestion.location}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {batches.length === 0 ? (
        <p>{labels.empty}</p>
      ) : (
        <div className="stack gap-sm">
          {batches.map((batch) => (
            <article key={batch.id} className="stack gap-xs" role="group" aria-label={batch.name}>
              <strong>{batch.name}</strong>
              <span>{formatBatchState(batch.state)}</span>
              <span>{batch.quantity}</span>
              <span>{batch.category}</span>
              <span>{batch.location}</span>
              <span>{formatFreshnessLabel(batch.freshness)}</span>
              <span>{formatFreshnessDetail(batch.freshness, locale)}</span>
              <div className="stack gap-xs">
                <button type="button" onClick={() => void onAction(batch.id, "open")}>
                  {labels.open}
                </button>
                <button type="button" onClick={() => void onAction(batch.id, "decrement")}>
                  {labels.decrement}
                </button>
                <button type="button" onClick={() => void onAction(batch.id, "use_up")}>
                  {labels.useUp}
                </button>
                <button type="button" onClick={() => void onAction(batch.id, "discard")}>
                  {labels.discard}
                </button>
              </div>
              <section className="stack gap-xs" aria-label={labels.historyTitle}>
                <h3>{labels.historyTitle}</h3>
                <BatchEventList events={batch.events ?? []} locale={locale} />
              </section>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ShoppingListCard({
  list,
  labels,
  onRename,
  onAddItem,
  onRemoveItem
}: {
  list: ShoppingListSummary;
  labels: {
    renameShoppingListLabel: string;
    shoppingItemNameLabel: string;
    shoppingItemQuantityLabel: string;
    addShoppingItemLabel: string;
    removeShoppingItemLabel: string;
    shoppingListEmpty: string;
  };
  onRename: (listId: string, name: string) => Promise<void>;
  onAddItem: (listId: string, name: string, quantity: string) => Promise<void>;
  onRemoveItem: (listId: string, itemId: string) => Promise<void>;
}) {
  const [nextListName, setNextListName] = useState(list.name);
  const [nextItemName, setNextItemName] = useState("");
  const [nextItemQuantity, setNextItemQuantity] = useState("1");
  const items = list.items ?? [];

  useEffect(() => {
    setNextListName(list.name);
  }, [list.name]);

  return (
    <article className="stack gap-sm" aria-label={list.name}>
      <strong>{list.name}</strong>
      <form
        className="stack gap-xs"
        onSubmit={(event) => {
          event.preventDefault();
          void onRename(list.id, nextListName);
        }}
      >
        <label className="stack gap-xs">
          <span>{labels.renameShoppingListLabel}</span>
          <input value={nextListName} onChange={(event) => setNextListName(event.target.value)} />
        </label>
        <button type="submit">{labels.renameShoppingListLabel}</button>
      </form>
      <form
        className="stack gap-xs"
        onSubmit={(event) => {
          event.preventDefault();
          void onAddItem(list.id, nextItemName, nextItemQuantity);
          setNextItemName("");
          setNextItemQuantity("1");
        }}
      >
        <label className="stack gap-xs">
          <span>{labels.shoppingItemNameLabel}</span>
          <input value={nextItemName} onChange={(event) => setNextItemName(event.target.value)} required />
        </label>
        <label className="stack gap-xs">
          <span>{labels.shoppingItemQuantityLabel}</span>
          <input value={nextItemQuantity} onChange={(event) => setNextItemQuantity(event.target.value)} required />
        </label>
        <button type="submit">{labels.addShoppingItemLabel}</button>
      </form>
      {items.length === 0 ? (
        <p>{labels.shoppingListEmpty}</p>
      ) : (
        <ul className="stack gap-xs">
          {items.map((item) => (
            <li key={item.id} className="stack gap-xs">
              <strong>{item.name}</strong>
              <span>{item.quantity}</span>
              <span>{item.product_key}</span>
              <button type="button" onClick={() => void onRemoveItem(list.id, item.id)}>
                {labels.removeShoppingItemLabel}
              </button>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

function ShoppingSuggestionsList({
  suggestions,
  lists,
  labels,
  onAccept
}: {
  suggestions: ShoppingReplenishmentSuggestionSummary[];
  lists: ShoppingListSummary[];
  labels: {
    acceptSuggestionLabel: string;
    chooseShoppingListLabel: string;
    shoppingSuggestionsEmpty: string;
  };
  onAccept: (suggestionId: string, listId: string) => Promise<void>;
}) {
  const [targets, setTargets] = useState<Record<string, string>>({});
  const defaultListId = lists[0]?.id ?? "";

  useEffect(() => {
    setTargets((current) => {
      const next: Record<string, string> = {};
      for (const suggestion of suggestions) {
        next[suggestion.id] = current[suggestion.id] ?? defaultListId;
      }
      return next;
    });
  }, [defaultListId, suggestions]);

  if (suggestions.length === 0) {
    return <p>{labels.shoppingSuggestionsEmpty}</p>;
  }

  return (
    <ul className="stack gap-xs">
      {suggestions.map((suggestion) => (
        <li key={suggestion.id} className="stack gap-xs">
          <strong>{suggestion.name}</strong>
          <span>{suggestion.quantity}</span>
          <span>{suggestion.product_key}</span>
          <span>{suggestion.source_action}</span>
          <label className="stack gap-xs">
            <span>{labels.chooseShoppingListLabel}</span>
            <select
              value={targets[suggestion.id] ?? defaultListId}
              onChange={(event) =>
                setTargets((current) => ({ ...current, [suggestion.id]: event.target.value }))
              }
            >
              {lists.map((list) => (
                <option key={list.id} value={list.id}>
                  {list.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={lists.length === 0}
            onClick={() => void onAccept(suggestion.id, targets[suggestion.id] ?? defaultListId)}
          >
            {labels.acceptSuggestionLabel}
          </button>
        </li>
      ))}
    </ul>
  );
}

export function HouseholdShell({ apiBaseUrl, storage }: HouseholdShellProps) {
  const client = useMemo(() => createFreshbotClient(apiBaseUrl), [apiBaseUrl]);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const packagePhotoPollingRunRef = useRef(0);
  const browserStorage =
    storage ?? (typeof window === "undefined" ? undefined : window.localStorage);
  const initialSession = readJson<HouseholdSessionResponse>(browserStorage, SESSION_STORAGE_KEY);
  const initialCachedState =
    initialSession === null ? null : readCachedHouseholdState(browserStorage, initialSession.token);
  const [session, setSession] = useState<HouseholdSessionResponse | null>(initialSession);
  const [today, setToday] = useState<TodayResponse | null>(initialCachedState?.today ?? null);
  const [batchView, setBatchView] = useState<BatchLifecycleListResponse | null>(
    initialCachedState?.batchView ?? null
  );
  const [shoppingView, setShoppingView] = useState<ShoppingListsResponse | null>(
    initialCachedState?.shoppingView ?? null
  );
  const [freshnessPolicies, setFreshnessPolicies] = useState<FreshnessPolicySummary[]>(
    initialCachedState?.freshnessPolicies ?? []
  );
  const [reminders, setReminders] = useState<ReminderPreviewResponse | null>(
    initialCachedState?.reminders ?? null
  );
  const [pendingMutations, setPendingMutations] = useState<QueuedMutation[]>(
    initialSession === null ? [] : readQueuedMutations(browserStorage, initialSession.token)
  );
  const [syncNotice, setSyncNotice] = useState<string | null>(
    initialCachedState === null ? null : "Zwischengespeicherte Daten werden angezeigt."
  );
  const [householdName, setHouseholdName] = useState("");
  const [memberName, setMemberName] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [isRecording, setIsRecording] = useState(false);
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
  const [savingFreshnessCategory, setSavingFreshnessCategory] = useState<string | null>(null);
  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [assistantResponse, setAssistantResponse] = useState<KitchenAssistantQueryResponse | null>(null);
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [newShoppingListName, setNewShoppingListName] = useState("");
  const syncInProgressRef = useRef(false);
  const syncQueueRef = useRef(Promise.resolve());
  const locale = (today?.locale ?? session?.locale ?? "de-DE") as "de-DE";
  const messages = getMessages(locale);
  const inventory = today?.sections.inventory ?? [];
  const managedBatches = batchView?.batches ?? [];
  const mergeSuggestions = batchView?.merge_suggestions ?? [];
  const shoppingLists = shoppingView?.lists ?? [];
  const shoppingSuggestions = today?.sections.shopping_suggestions ?? [];
  const canRecordAudio =
    typeof MediaRecorder !== "undefined" &&
    typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices?.getUserMedia === "function";
  const needsAttention = today?.sections.needs_attention ?? [];
  const upcoming = today?.sections.upcoming ?? [];
  const reminderUrgentItems = reminders?.digest.urgent_items ?? [];
  const reminderSoonItems = reminders?.digest.soon_items ?? [];
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
    const cachedState = readCachedHouseholdState(browserStorage, parsedSession.token);
    if (cachedState !== null) {
      setToday(cachedState.today);
      setBatchView(cachedState.batchView);
      setShoppingView(cachedState.shoppingView);
      setFreshnessPolicies(cachedState.freshnessPolicies);
      setReminders(cachedState.reminders);
      setSyncNotice(messages.cachedHouseholdData);
    }
    setPendingMutations(readQueuedMutations(browserStorage, parsedSession.token));
    void synchronizeHouseholdState(parsedSession, { replayQueuedMutations: true });
  }, [browserStorage]);

  useEffect(() => {
    if (session === null || browserStorage === undefined) {
      return;
    }

    const onOnline = () => {
      void synchronizeHouseholdState(session, { replayQueuedMutations: true, silent: true });
    };

    const intervalId = window.setInterval(onOnline, HOUSEHOLD_REFRESH_INTERVAL_MS);
    window.addEventListener("online", onOnline);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("online", onOnline);
    };
  }, [browserStorage, session]);

  useEffect(() => {
    if (session === null || browserStorage === undefined) {
      return;
    }

    writeCachedHouseholdState(browserStorage, session.token, {
      today,
      batchView,
      shoppingView,
      freshnessPolicies,
      reminders
    });
  }, [batchView, browserStorage, freshnessPolicies, reminders, session, shoppingView, today]);

  async function loadToday(activeSession: HouseholdSessionResponse, options: { silent?: boolean } = {}) {
    if (!options.silent) {
      setStatus("loading");
      setErrorMessage(null);
    }
    try {
      const nextToday = await client.getTodayDashboard(activeSession.token);
      try {
        const nextPolicies = await client.listFreshnessOverrides(activeSession.token);
        setFreshnessPolicies(nextPolicies.policies);
      } catch {
        setFreshnessPolicies(freshnessPolicies);
      }
      setToday(nextToday);
      if (!options.silent) {
        setStatus("ready");
        if (readQueuedMutations(browserStorage, activeSession.token).length === 0) {
          setSyncNotice(null);
        }
      }
    } catch {
      if (
        !options.silent &&
        readCachedHouseholdState(browserStorage, activeSession.token) === null &&
        today === null &&
        batchView === null &&
        shoppingView === null
      ) {
        setStatus("error");
        setErrorMessage(messages.error);
      }
    }
  }

  async function loadReminders(activeSession: HouseholdSessionResponse, options: { silent?: boolean } = {}) {
    if (!options.silent) {
      setErrorMessage(null);
    }
    try {
      const nextReminders = await client.getReminders(activeSession.token);
      setReminders(nextReminders);
    } catch {
      if (!options.silent && reminders !== null) {
        return;
      }
    }
  }

  async function loadBatches(activeSession: HouseholdSessionResponse, options: { silent?: boolean } = {}) {
    if (!options.silent) {
      setErrorMessage(null);
    }
    try {
      const nextBatches = await client.listBatches(activeSession.token);
      setBatchView(nextBatches);
    } catch {
      if (!options.silent && readCachedHouseholdState(browserStorage, activeSession.token) === null && batchView === null) {
        setErrorMessage(messages.error);
      }
    }
  }

  async function loadShoppingLists(
    activeSession: HouseholdSessionResponse,
    options: { silent?: boolean } = {}
  ) {
    if (!options.silent) {
      setErrorMessage(null);
    }
    try {
      const nextShoppingView = await client.listShoppingLists(activeSession.token);
      setShoppingView(nextShoppingView);
    } catch {
      if (
        !options.silent &&
        readCachedHouseholdState(browserStorage, activeSession.token) === null &&
        shoppingView === null
      ) {
        setErrorMessage(messages.error);
      }
    }
  }

  function synchronizeHouseholdState(
    activeSession: HouseholdSessionResponse,
    options: { replayQueuedMutations?: boolean; silent?: boolean } = {}
  ) {
    const run = async () => {
      if (options.replayQueuedMutations) {
        await replayQueuedMutations(activeSession);
      }

      await loadToday(activeSession, { silent: options.silent });
      await loadReminders(activeSession, { silent: options.silent });
      await loadBatches(activeSession, { silent: options.silent });
      await loadShoppingLists(activeSession, { silent: options.silent });
    };

    const nextSync = syncQueueRef.current.then(run, run);
    syncQueueRef.current = nextSync.catch(() => undefined);
    return nextSync;
  }

  async function handleKitchenAssistantSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (session === null) {
      return;
    }

    setAssistantLoading(true);
    setErrorMessage(null);

    try {
      const response = await client.queryKitchenAssistant(session.token, { question: assistantQuestion });
      setAssistantResponse(response);
    } catch {
      setStatus("error");
      setErrorMessage(messages.captureError);
    } finally {
      setAssistantLoading(false);
    }
  }

  function queueMutation(activeSession: HouseholdSessionResponse, mutation: QueuedMutation) {
    if (browserStorage === undefined) {
      return;
    }

    const nextQueue = [...readQueuedMutations(browserStorage, activeSession.token), mutation];
    writeQueuedMutations(browserStorage, activeSession.token, nextQueue);
    setPendingMutations(nextQueue);
    setSyncNotice(messages.offlineChangesQueued);
  }

  async function replayQueuedMutations(activeSession: HouseholdSessionResponse) {
    if (browserStorage === undefined || syncInProgressRef.current) {
      return;
    }

    const queued = readQueuedMutations(browserStorage, activeSession.token);
    if (queued.length === 0) {
      setPendingMutations([]);
      return;
    }

    syncInProgressRef.current = true;
    try {
      const nextQueued = [...queued];
      let index = 0;
      let reportedPermanentError = false;

      while (index < nextQueued.length) {
        const mutation = nextQueued[index];
        try {
          if (mutation.kind === "batch-action") {
            await client.actOnBatch(activeSession.token, mutation.batchId, { action: mutation.action });
          }
          if (mutation.kind === "create-shopping-list") {
            await client.createShoppingList(activeSession.token, { name: mutation.name });
          }
          if (mutation.kind === "rename-shopping-list") {
            await client.renameShoppingList(activeSession.token, mutation.listId, { name: mutation.name });
          }
          if (mutation.kind === "upsert-shopping-list-item") {
            await client.upsertShoppingListItem(activeSession.token, mutation.listId, {
              name: mutation.name,
              quantity: mutation.quantity
            });
          }
          if (mutation.kind === "remove-shopping-list-item") {
            await client.removeShoppingListItem(activeSession.token, mutation.listId, mutation.itemId);
          }
          if (mutation.kind === "accept-shopping-suggestion") {
            await client.acceptShoppingSuggestion(activeSession.token, mutation.suggestionId, {
              list_id: mutation.listId
            });
          }
          if (mutation.kind === "save-freshness-override") {
            await client.saveFreshnessOverride(activeSession.token, mutation.category, {
              shelf_life_days: mutation.shelf_life_days,
              soon_window_days: mutation.soon_window_days
            });
          }
          index += 1;
        } catch (error) {
          if (isNetworkError(error)) {
            const remaining = nextQueued.slice(index);
            writeQueuedMutations(browserStorage, activeSession.token, remaining);
            setPendingMutations(remaining);
            return;
          }

          nextQueued.splice(index, 1);
          writeQueuedMutations(browserStorage, activeSession.token, nextQueued);
          setPendingMutations(nextQueued);
          if (!reportedPermanentError) {
            setErrorMessage(messages.captureError);
            reportedPermanentError = true;
          }
        }
      }

      writeQueuedMutations(browserStorage, activeSession.token, []);
      setPendingMutations([]);
      setSyncNotice(null);
    } finally {
      syncInProgressRef.current = false;
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
    await synchronizeHouseholdState(nextSession);
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
      packagePhotoPollingRunRef.current += 1;
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
        const pollingRun = ++packagePhotoPollingRunRef.current;
        setStatus("processing");
        void pollForPackagePhotoDrafts(session.token, response.capture_id, pollingRun);
        return;
      }
      if (response.status === "failed") {
        throw new Error("package photo extraction failed");
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

  async function pollForPackagePhotoDrafts(token: string, captureId: string, pollingRun: number) {
    while (packagePhotoPollingRunRef.current === pollingRun) {
      await new Promise((resolve) => setTimeout(resolve, PACKAGE_PHOTO_POLLING_DELAY_MS));
      if (packagePhotoPollingRunRef.current !== pollingRun) {
        return;
      }

      let response: PackagePhotoDraftResponse;
      try {
        response = await client.getPackagePhotoDrafts(token, captureId);
      } catch {
        continue;
      }

      if (packagePhotoPollingRunRef.current !== pollingRun) {
        return;
      }

      applyPackagePhotoDraftResponse(response);
      if (response.status === "pending_review") {
        setStatus("ready");
        return;
      }
      if (response.status === "failed") {
        setStatus("error");
        setErrorMessage(messages.captureError);
        return;
      }
    }
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
      packagePhotoPollingRunRef.current += 1;
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
      await synchronizeHouseholdState(session);
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
      await synchronizeHouseholdState(session);
    } catch (error) {
      if (isNetworkError(error)) {
        queueMutation(session, {
          kind: "save-freshness-override",
          category,
          shelf_life_days: policy.shelf_life_days,
          soon_window_days: policy.soon_window_days
        });
        setStatus("ready");
        setErrorMessage(null);
        return;
      }
      setStatus("error");
      setErrorMessage(messages.freshnessRuleError);
    } finally {
      setSavingFreshnessCategory(null);
    }
  }

  async function handleBatchAction(batchId: string, action: "open" | "decrement" | "use_up" | "discard") {
    if (session === null) {
      return;
    }

    setStatus("saving");
    setErrorMessage(null);

    try {
      await client.actOnBatch(session.token, batchId, {
        action: action as BatchLifecycleActionRequest["action"]
      });
      await synchronizeHouseholdState(session);
      setStatus("ready");
    } catch (error) {
      if (isNetworkError(error)) {
        queueMutation(session, {
          kind: "batch-action",
          batchId,
          action: action as BatchLifecycleActionRequest["action"]
        });
        setStatus("ready");
        setErrorMessage(null);
        return;
      }
      setStatus("error");
      setErrorMessage(messages.captureError);
    }
  }

  async function handleCreateShoppingList(name: string) {
    if (session === null) {
      return;
    }

    setStatus("saving");
    setErrorMessage(null);
    try {
      await client.createShoppingList(session.token, { name });
      await synchronizeHouseholdState(session);
      setStatus("ready");
    } catch (error) {
      if (isNetworkError(error)) {
        queueMutation(session, { kind: "create-shopping-list", name });
        setStatus("ready");
        setErrorMessage(null);
        return;
      }
      setStatus("error");
      setErrorMessage(messages.captureError);
    }
  }

  async function handleRenameShoppingList(listId: string, name: string) {
    if (session === null) {
      return;
    }

    setStatus("saving");
    setErrorMessage(null);
    try {
      await client.renameShoppingList(session.token, listId, { name });
      await synchronizeHouseholdState(session);
      setStatus("ready");
    } catch (error) {
      if (isNetworkError(error)) {
        queueMutation(session, { kind: "rename-shopping-list", listId, name });
        setStatus("ready");
        setErrorMessage(null);
        return;
      }
      setStatus("error");
      setErrorMessage(messages.captureError);
    }
  }

  async function handleAddShoppingListItem(listId: string, name: string, quantity: string) {
    if (session === null) {
      return;
    }

    setStatus("saving");
    setErrorMessage(null);
    try {
      await client.upsertShoppingListItem(session.token, listId, { name, quantity });
      await synchronizeHouseholdState(session);
      setStatus("ready");
    } catch (error) {
      if (isNetworkError(error)) {
        queueMutation(session, {
          kind: "upsert-shopping-list-item",
          listId,
          name,
          quantity
        });
        setStatus("ready");
        setErrorMessage(null);
        return;
      }
      setStatus("error");
      setErrorMessage(messages.captureError);
    }
  }

  async function handleRemoveShoppingListItem(listId: string, itemId: string) {
    if (session === null) {
      return;
    }

    setStatus("saving");
    setErrorMessage(null);
    try {
      await client.removeShoppingListItem(session.token, listId, itemId);
      await synchronizeHouseholdState(session);
      setStatus("ready");
    } catch (error) {
      if (isNetworkError(error)) {
        queueMutation(session, { kind: "remove-shopping-list-item", listId, itemId });
        setStatus("ready");
        setErrorMessage(null);
        return;
      }
      setStatus("error");
      setErrorMessage(messages.captureError);
    }
  }

  async function handleAcceptShoppingSuggestion(suggestionId: string, listId: string) {
    if (session === null) {
      return;
    }

    setStatus("saving");
    setErrorMessage(null);
    try {
      await client.acceptShoppingSuggestion(session.token, suggestionId, { list_id: listId });
      await synchronizeHouseholdState(session);
      setStatus("ready");
    } catch (error) {
      if (isNetworkError(error)) {
        queueMutation(session, {
          kind: "accept-shopping-suggestion",
          suggestionId,
          listId
        });
        setStatus("ready");
        setErrorMessage(null);
        return;
      }
      setStatus("error");
      setErrorMessage(messages.captureError);
    }
  }

  function resetSession() {
    if (browserStorage !== undefined && session !== null) {
      browserStorage.removeItem(cacheKey(session.token));
      browserStorage.removeItem(queueKey(session.token));
    }
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
    setAssistantQuestion("");
    setAssistantResponse(null);
    setAssistantLoading(false);
    setBatchView(null);
    setShoppingView(null);
    setPendingMutations([]);
    setSyncNotice(null);
    setNewShoppingListName("");
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

        {syncNotice ? (
          <p role="status" className="muted">
            {syncNotice}
          </p>
        ) : null}

        {today ? (
          <div className="stack gap-md">
            <div className="stack gap-xs">
              <p className="welcome">{messages.welcome(today.member_name)}</p>
              <p className="muted">{today.household_name}</p>
            </div>
            {reminders ? (
              <section className="dashboard-panel stack gap-sm" aria-label={messages.remindersTitle}>
                <h2>{messages.remindersTitle}</h2>
                <p className="muted">{messages.remindersNote}</p>
                <p>
                  <strong>{messages.reminderDigestLabel}:</strong> {reminders.digest.summary}
                </p>
                <p>
                  <strong>{messages.reminderDigestDeliveryLabel}:</strong>{" "}
                  {reminders.settings.daily_digest_enabled ? "In der App" : "Aus"}
                </p>
                <p>
                  <strong>{messages.urgentPushDeliveryLabel}:</strong>{" "}
                  {reminders.delivery.urgent_push_delivery === "web_push" ? "Web Push" : "Aus"}
                </p>
                {reminderUrgentItems.length > 0 ? (
                  <div className="stack gap-xs">
                    <h3>{messages.urgentTitle}</h3>
                    <ul className="stack gap-xs">
                      {reminderUrgentItems.map((item) => (
                        <li key={`urgent-${item.name}-${item.location}`}>
                          <strong>{item.name}</strong>
                          <span>{item.quantity}</span>
                          <span>{item.location}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {reminderSoonItems.length > 0 ? (
                  <div className="stack gap-xs">
                    <h3>{messages.soonTitle}</h3>
                    <ul className="stack gap-xs">
                      {reminderSoonItems.map((item) => (
                        <li key={`soon-${item.name}-${item.location}`}>
                          <strong>{item.name}</strong>
                          <span>{item.quantity}</span>
                          <span>{item.location}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </section>
            ) : null}
            <section className="dashboard-panel stack gap-sm">
              <h2>{messages.kitchenAssistantTitle}</h2>
              <p className="muted">{messages.kitchenAssistantNote}</p>
              <form className="stack gap-sm" onSubmit={(event) => void handleKitchenAssistantSubmit(event)}>
                <label className="stack gap-xs">
                  <span>{messages.kitchenAssistantQuestionLabel}</span>
                  <textarea
                    value={assistantQuestion}
                    onChange={(event) => setAssistantQuestion(event.target.value)}
                    required
                  />
                </label>
                <button type="submit" disabled={assistantLoading || assistantQuestion.trim().length === 0}>
                  {assistantLoading ? messages.askingKitchenAssistantLabel : messages.askKitchenAssistantLabel}
                </button>
              </form>
              {assistantResponse ? (
                <div className="stack gap-xs" role="status" aria-label={messages.kitchenAssistantTitle}>
                  <p>{assistantResponse.answer}</p>
                  {assistantResponse.needs_clarification ? <p>{messages.kitchenAssistantClarifyLabel}</p> : null}
                </div>
              ) : null}
            </section>
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
                  {inventory.map((batch, index) => (
                    <li key={`${index}-${batch.name}-${batch.location}-${batch.quantity}`} className="stack gap-xs">
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
              <h2>{messages.shoppingListsTitle}</h2>
              <form
                className="stack gap-xs"
                onSubmit={(event) => {
                  event.preventDefault();
                  void handleCreateShoppingList(newShoppingListName);
                  setNewShoppingListName("");
                }}
              >
                <label className="stack gap-xs">
                  <span>{messages.shoppingListNameLabel}</span>
                  <input
                    value={newShoppingListName}
                    onChange={(event) => setNewShoppingListName(event.target.value)}
                    required
                  />
                </label>
                <button type="submit">{messages.createShoppingListLabel}</button>
              </form>
              <div className="stack gap-sm">
                {shoppingLists.length === 0 ? (
                  <p>{messages.shoppingListEmpty}</p>
                ) : (
                  shoppingLists.map((list) => (
                    <ShoppingListCard
                      key={list.id}
                      list={list}
        labels={{
          renameShoppingListLabel: messages.renameShoppingListLabel,
          shoppingItemNameLabel: messages.shoppingItemNameLabel,
          shoppingItemQuantityLabel: messages.shoppingItemQuantityLabel,
          addShoppingItemLabel: messages.addShoppingItemLabel,
          removeShoppingItemLabel: messages.removeShoppingItemLabel,
          shoppingListEmpty: messages.shoppingListEmpty
        }}
                      onRename={handleRenameShoppingList}
                      onAddItem={handleAddShoppingListItem}
                      onRemoveItem={handleRemoveShoppingListItem}
                    />
                  ))
                )}
              </div>
              <section className="stack gap-sm" aria-label={messages.shoppingSuggestionsTitle}>
                <h3>{messages.shoppingSuggestionsTitle}</h3>
                <ShoppingSuggestionsList
                  suggestions={shoppingSuggestions}
                  lists={shoppingLists}
                  labels={{
                    acceptSuggestionLabel: messages.acceptSuggestionLabel,
                    chooseShoppingListLabel: messages.chooseShoppingListLabel,
                    shoppingSuggestionsEmpty: messages.shoppingSuggestionsEmpty
                  }}
                  onAccept={handleAcceptShoppingSuggestion}
                />
              </section>
            </section>
            <BatchManagementList
              batches={managedBatches}
              mergeSuggestions={mergeSuggestions}
              locale={locale}
              onAction={handleBatchAction}
              labels={{
                title: messages.batchManagementTitle,
                empty: messages.emptyBatchManagement,
                duplicateSuggestionsTitle: messages.duplicateBatchSuggestionsTitle,
                historyTitle: messages.batchHistoryTitle,
                open: messages.openBatchLabel,
                decrement: messages.decrementBatchLabel,
                useUp: messages.useUpBatchLabel,
                discard: messages.discardBatchLabel
              }}
            />
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
                    status === "processing" ||
                    status === "transcribing" ||
                    status === "saving" ||
                    status === "loading"
                  }
                >
                  {(status === "drafting" || status === "processing") && packagePhotoFile !== null
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
                        <input
                          id={`draft-${index}-location`}
                          aria-label={messages.batchLocationLabel}
                          value={draft.location}
                          onChange={(event) => updateDraft(index, "location", event.target.value)}
                          list={`draft-${index}-locations`}
                        />
                        <datalist id={`draft-${index}-locations`}>
                          {availableLocations.map((location) => (
                            <option key={location} value={location} />
                          ))}
                        </datalist>
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
