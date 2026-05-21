import React from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { HouseholdShell } from "./household-shell";
import { SESSION_STORAGE_KEY } from "../lib/session";


class MemoryStorage implements Storage {
  #store = new Map<string, string>();

  get length(): number {
    return this.#store.size;
  }

  clear(): void {
    this.#store.clear();
  }

  getItem(key: string): string | null {
    return this.#store.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.#store.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.#store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.#store.set(key, value);
  }
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;

  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });

  return { promise, resolve, reject };
}

test("haushaltsmitglied kann beitreten und das leere Heute-Dashboard sehen", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/today") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          sections: {
            inventory: [],
            needs_attention: [],
            upcoming: [],
            shopping_suggestions: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    return new Response("not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);

  render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

  await user.type(screen.getByLabelText("Haushaltsname"), "WG Sonnenseite");
  await user.type(screen.getByLabelText("Dein Name"), "Johannes");
  await user.click(screen.getByRole("button", { name: "Haushalt betreten" }));

  expect(await screen.findByRole("heading", { name: "Heute" })).toBeInTheDocument();
  expect(screen.getByText("Willkommen, Johannes.")).toBeInTheDocument();
  expect(screen.getByText("Noch ist alles ruhig in eurer Küche.")).toBeInTheDocument();
  expect(storage.getItem("freshbot.householdSession")).toContain("session-token");
  const todayCall = fetchMock.mock.calls.find(([url]) => url === "http://api.example/api/today");
  expect(todayCall?.[0]).toBe("http://api.example/api/today");
  expect(new Headers(todayCall?.[1]?.headers).get("authorization")).toBe("Bearer session-token");
});

test("haushaltsmitglied kann den küchenassistenten nach strukturierten haushaltsdaten fragen", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/today") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          sections: {
            inventory: [],
            needs_attention: [],
            upcoming: [],
            shopping_suggestions: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/kitchen-assistant/query" && init?.method === "POST") {
      expect(new Headers(init.headers).get("authorization")).toBe("Bearer session-token");
      expect(JSON.parse(String(init.body))).toEqual({ question: "Was sollten wir bald nutzen?" });
      return new Response(
        JSON.stringify({
          question: "Was sollten wir bald nutzen?",
          answer: "Ihr solltet zuerst Hackfleisch nutzen. Bald dran: Joghurt.",
          topic: "soon_items",
          needs_clarification: false
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    return new Response("not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);

  render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

  await user.type(screen.getByLabelText("Haushaltsname"), "WG Sonnenseite");
  await user.type(screen.getByLabelText("Dein Name"), "Johannes");
  await user.click(screen.getByRole("button", { name: "Haushalt betreten" }));

  expect(await screen.findByRole("heading", { name: "Küchenassistent" }, { timeout: 10000 })).toBeInTheDocument();
  await user.type(screen.getByLabelText("Frage an den Küchenassistenten"), "Was sollten wir bald nutzen?");
  await user.click(screen.getByRole("button", { name: "Frage stellen" }));

  expect(
    await screen.findByText(
      "Ihr solltet zuerst Hackfleisch nutzen. Bald dran: Joghurt.",
      {},
      { timeout: 10000 }
    )
  ).toBeInTheDocument();
});

test("haushaltsmitglied sieht nach einer frühen aktualisierung nicht wieder alte batch-daten", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();
  const session = {
    token: "session-token",
    locale: "de-DE",
    household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
    member: { display_name: "Johannes" }
  };
  const initialBatches = deferred<Response>();
  let batchState: "sealed" | "opened" = "sealed";
  let batchRequests = 0;

  storage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  storage.setItem(
    "freshbot.householdCache:session-token",
    JSON.stringify({
      today: {
        household_name: "WG Sonnenseite",
        member_name: "Johannes",
        locale: "de-DE",
        sections: {
          inventory: [],
          needs_attention: [],
          upcoming: [],
          shopping_suggestions: []
        }
      },
      batchView: {
        batches: [
          {
            id: "batch-1",
            name: "Haferdrink",
            quantity: "2 Packungen",
            category: "Getränke",
            location: "Vorratsschrank",
            state: "sealed",
            freshness: null,
            events: []
          }
        ],
        merge_suggestions: []
      },
      shoppingView: {
        lists: [],
        replenishment_suggestions: []
      },
      freshnessPolicies: []
    })
  );

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(JSON.stringify(session), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/today") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          sections: {
            inventory: [],
            needs_attention: [],
            upcoming: [],
            shopping_suggestions: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/shopping-lists") {
      return new Response(JSON.stringify({ lists: [], replenishment_suggestions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/batches" && (init?.method === undefined || init.method === "GET")) {
      batchRequests += 1;
      if (batchRequests === 1) {
        return initialBatches.promise;
      }

      return new Response(
        JSON.stringify({
          batches: [
            {
              id: "batch-1",
              name: "Haferdrink",
              quantity: "2 Packungen",
              category: "Getränke",
              location: "Vorratsschrank",
              state: batchState,
              freshness: null,
              events: []
            }
          ],
          merge_suggestions: []
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/batches/batch-1/actions" && init?.method === "POST") {
      batchState = "opened";
      return new Response(
        JSON.stringify({
          id: "batch-1",
          name: "Haferdrink",
          quantity: "2 Packungen",
          category: "Getränke",
          location: "Vorratsschrank",
          state: batchState,
          freshness: null,
          events: [{ action: "opened", member_name: "Johannes", created_at: "2026-05-20T10:00:00Z" }]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    return new Response("not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);

  render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

  const batchCard = await screen.findByRole("group", { name: "Haferdrink" });
  expect(within(batchCard).getByText("Versiegelt")).toBeInTheDocument();

  await user.click(within(batchCard).getByRole("button", { name: "Öffnen" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "http://api.example/api/batches/batch-1/actions",
    expect.objectContaining({ method: "POST" })
  );

  initialBatches.resolve(
    new Response(
      JSON.stringify({
        batches: [
          {
            id: "batch-1",
            name: "Haferdrink",
            quantity: "2 Packungen",
            category: "Getränke",
            location: "Vorratsschrank",
            state: "sealed",
            freshness: null,
            events: []
          }
        ],
        merge_suggestions: []
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    )
  );

  expect(await screen.findByText("Geöffnet")).toBeInTheDocument();
  expect(screen.queryByText("Versiegelt")).not.toBeInTheDocument();
});

test("haushaltsmitglied sieht frischezustände und kann kategorieregeln anpassen", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();
  let todayResponse = {
    household_name: "WG Sonnenseite",
    member_name: "Johannes",
    locale: "de-DE",
    sections: {
      inventory: [
        {
          name: "Hackfleisch",
          quantity: "500 g",
          category: "Molkerei",
          location: "Kühlschrank",
          freshness: {
            state: "urgent",
            source: "exact_date",
            due_on: "2026-05-20",
            date_type: "use_by"
          }
        },
        {
          name: "Joghurt",
          quantity: "2 Becher",
          category: "Molkerei",
          location: "Kühlschrank",
          freshness: {
            state: "soon",
            source: "exact_date",
            due_on: "2026-05-20",
            date_type: "best_before"
          }
        },
        {
          name: "Bananen",
          quantity: "6 Stück",
          category: "Obst & Gemüse",
          location: "Vorratsschrank",
          freshness: {
            state: "soon",
            source: "category_default",
            due_on: "2026-05-22",
            date_type: null
          }
        }
      ],
      needs_attention: [
        {
          name: "Hackfleisch",
          quantity: "500 g",
          category: "Molkerei",
          location: "Kühlschrank",
          freshness: {
            state: "urgent",
            source: "exact_date",
            due_on: "2026-05-20",
            date_type: "use_by"
          }
        }
      ],
      upcoming: [
        {
          name: "Joghurt",
          quantity: "2 Becher",
          category: "Molkerei",
          location: "Kühlschrank",
          freshness: {
            state: "soon",
            source: "exact_date",
            due_on: "2026-05-20",
            date_type: "best_before"
          }
        },
        {
          name: "Bananen",
          quantity: "6 Stück",
          category: "Obst & Gemüse",
          location: "Vorratsschrank",
          freshness: {
            state: "soon",
            source: "category_default",
            due_on: "2026-05-22",
            date_type: null
          }
        }
      ],
      shopping_suggestions: []
    }
  };
  let policiesResponse = {
    policies: [
      {
        category: "Getränke",
        default_shelf_life_days: 14,
        default_soon_window_days: 4,
        shelf_life_days: 14,
        soon_window_days: 4,
        is_override: false
      },
      {
        category: "Molkerei",
        default_shelf_life_days: 7,
        default_soon_window_days: 3,
        shelf_life_days: 7,
        soon_window_days: 3,
        is_override: false
      },
      {
        category: "Obst & Gemüse",
        default_shelf_life_days: 2,
        default_soon_window_days: 2,
        shelf_life_days: 2,
        soon_window_days: 2,
        is_override: false
      }
    ]
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/today") {
      return new Response(JSON.stringify(todayResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/freshness-overrides" && (init?.method === undefined || init.method === "GET")) {
      return new Response(JSON.stringify(policiesResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url.startsWith("http://api.example/api/freshness-overrides/") && init?.method === "PUT") {
      expect(decodeURIComponent(url.split("/api/freshness-overrides/")[1] ?? "")).toBe("Obst & Gemüse");
      const payload = JSON.parse(String(init.body));
      expect(payload).toEqual({ shelf_life_days: 0, soon_window_days: 0 });
      policiesResponse = {
        policies: policiesResponse.policies.map((policy) =>
          policy.category === "Obst & Gemüse"
            ? { ...policy, shelf_life_days: 0, soon_window_days: 0, is_override: true }
            : policy
        )
      };
      todayResponse = {
        ...todayResponse,
        sections: {
          ...todayResponse.sections,
          inventory: todayResponse.sections.inventory.map((batch) =>
            batch.name === "Bananen"
              ? {
                  ...batch,
                  freshness: {
                    state: "urgent",
                    source: "household_override",
                    due_on: "2026-05-20",
                    date_type: null
                  }
                }
              : batch
          ),
          needs_attention: [
            ...todayResponse.sections.needs_attention,
            {
              name: "Bananen",
              quantity: "6 Stück",
              category: "Obst & Gemüse",
              location: "Vorratsschrank",
              freshness: {
                state: "urgent",
                source: "household_override",
                due_on: "2026-05-20",
                date_type: null
              }
            }
          ],
          upcoming: [
            {
              name: "Joghurt",
              quantity: "2 Becher",
              category: "Molkerei",
              location: "Kühlschrank",
              freshness: {
                state: "soon",
                source: "exact_date",
                due_on: "2026-05-20",
                date_type: "best_before"
              }
            }
          ]
        }
      };
      return new Response(
        JSON.stringify({
          category: "Obst & Gemüse",
          default_shelf_life_days: 2,
          default_soon_window_days: 2,
          shelf_life_days: 0,
          soon_window_days: 0,
          is_override: true
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    return new Response("not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);

  render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

  await user.type(screen.getByLabelText("Haushaltsname"), "WG Sonnenseite");
  await user.type(screen.getByLabelText("Dein Name"), "Johannes");
  await user.click(screen.getByRole("button", { name: "Haushalt betreten" }));

  expect(await screen.findByRole("heading", { name: "Dringend heute" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Bald im Blick" })).toBeInTheDocument();
  const initialUrgentSection = screen.getByRole("region", { name: "Dringend heute" });
  const soonSection = screen.getByRole("region", { name: "Bald im Blick" });
  expect(within(initialUrgentSection).getByText("Zu verbrauchen bis 20.05.2026")).toBeInTheDocument();
  expect(within(soonSection).getByText("Mindestens haltbar bis 20.05.2026")).toBeInTheDocument();
  expect(within(soonSection).getByText("Geschätzt bis 22.05.2026")).toBeInTheDocument();

  const produceRule = screen.getByRole("group", { name: "Frische-Regel Obst & Gemüse" });
  await user.clear(within(produceRule).getByLabelText("Tage frisch ab Einräumen"));
  await user.type(within(produceRule).getByLabelText("Tage frisch ab Einräumen"), "0");
  await user.clear(within(produceRule).getByLabelText("Tage für bald"));
  await user.type(within(produceRule).getByLabelText("Tage für bald"), "0");
  await user.click(within(produceRule).getByRole("button", { name: "Regel speichern" }));

  const updatedProduceRule = await screen.findByRole("group", { name: "Frische-Regel Obst & Gemüse" });
  expect(within(updatedProduceRule).getByText("Haushaltsregel aktiv")).toBeInTheDocument();
  const urgentSection = screen.getByRole("region", { name: "Dringend heute" });
  expect(within(urgentSection).getByText("Bananen")).toBeInTheDocument();
});

test("haushaltsmitglied sieht den täglichen frische-digest und die reminder-zustellung", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/today") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          sections: {
            inventory: [],
            needs_attention: [],
            upcoming: [],
            shopping_suggestions: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/reminders") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          settings: {
            daily_digest_enabled: true,
            urgent_push_enabled: true
          },
          digest: {
            generated_on: "2026-05-21",
            summary: "1 dringende und 1 baldige Frischehinweise",
            urgent_items: [
              {
                name: "Hackfleisch",
                quantity: "500 g",
                category: "Molkerei",
                location: "Kühlschrank",
                freshness: {
                  state: "urgent",
                  source: "exact_date",
                  due_on: "2026-05-21",
                  date_type: "use_by"
                }
              }
            ],
            soon_items: [
              {
                name: "Joghurt",
                quantity: "2 Becher",
                category: "Molkerei",
                location: "Kühlschrank",
                freshness: {
                  state: "soon",
                  source: "exact_date",
                  due_on: "2026-05-22",
                  date_type: "best_before"
                }
              }
            ]
          },
          delivery: {
            daily_digest_delivery: "in_app",
            urgent_push_delivery: "web_push",
            urgent_push_candidates: [
              {
                name: "Hackfleisch",
                quantity: "500 g",
                category: "Molkerei",
                location: "Kühlschrank",
                freshness: {
                  state: "urgent",
                  source: "exact_date",
                  due_on: "2026-05-21",
                  date_type: "use_by"
                }
              }
            ]
          },
          freshness_policies: [],
          deliveries: []
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    return new Response("not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);

  render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

  await user.type(screen.getByLabelText("Haushaltsname"), "WG Sonnenseite");
  await user.type(screen.getByLabelText("Dein Name"), "Johannes");
  await user.click(screen.getByRole("button", { name: "Haushalt betreten" }));

  const remindersRegion = await screen.findByRole("region", { name: "Frische-Reminder" });
  expect(within(remindersRegion).getByText("1 dringende und 1 baldige Frischehinweise")).toBeInTheDocument();
  expect(within(remindersRegion).getByText("Hackfleisch")).toBeInTheDocument();
  expect(within(remindersRegion).getByText("Joghurt")).toBeInTheDocument();
  expect(within(remindersRegion).getByText("In der App")).toBeInTheDocument();
  expect(within(remindersRegion).getByText("Web Push")).toBeInTheDocument();
});

test("haushaltsmitglied kann text erfassen entwürfe prüfen und batches speichern", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();
  let confirmed = false;

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/today") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          sections: {
            inventory: confirmed
              ? [
                  {
                    name: "Haferdrink",
                    quantity: "2 Kartons",
                    category: "Getränke",
                    location: "Kühlschrank"
                  },
                  {
                    name: "Penne",
                    quantity: "1 Packung",
                    category: "Vorrat",
                    location: "Vorratsschrank"
                  }
                ]
              : [],
            needs_attention: [],
            upcoming: [],
            shopping_suggestions: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/text-capture/drafts") {
      return new Response(
        JSON.stringify({
          drafts: [
            {
              name: "Milch",
              quantity: "2",
              category: "Molkerei",
              location: "Kühlschrank"
            },
            {
              name: "Pasta",
              quantity: "1 Packung",
              category: "Vorrat",
              location: "Vorratsschrank"
            }
          ],
          available_categories: [
            "Molkerei",
            "Obst & Gemüse",
            "Vorrat",
            "Getränke",
            "Sonstiges"
          ],
          available_locations: ["Kühlschrank", "Gefrierschrank", "Vorratsschrank"]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/text-capture/confirm") {
      confirmed = true;
      return new Response(
        JSON.stringify({
          batches: [
            {
              name: "Haferdrink",
              quantity: "2 Kartons",
              category: "Getränke",
              location: "Kühlschrank"
            },
            {
              name: "Penne",
              quantity: "1 Packung",
              category: "Vorrat",
              location: "Vorratsschrank"
            }
          ]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    return new Response("not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);

  render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

  await user.type(screen.getByLabelText("Haushaltsname"), "WG Sonnenseite");
  await user.type(screen.getByLabelText("Dein Name"), "Johannes");
  await user.click(screen.getByRole("button", { name: "Haushalt betreten" }));

  await user.type(
    await screen.findByLabelText("Was habt ihr eingeräumt?"),
    "2 Milch im Kühlschrank und 1 Packung Pasta im Vorratsschrank"
  );
  await user.click(screen.getByRole("button", { name: "Entwürfe erstellen" }));

  const drafts = await screen.findAllByRole("group", { name: /Entwurf/ });
  const firstDraft = drafts[0];
  await user.clear(within(firstDraft).getByLabelText("Name"));
  await user.type(within(firstDraft).getByLabelText("Name"), "Haferdrink");
  await user.clear(within(firstDraft).getByLabelText("Menge"));
  await user.type(within(firstDraft).getByLabelText("Menge"), "2 Kartons");
  await user.selectOptions(within(firstDraft).getByLabelText("Kategorie"), "Getränke");

  await user.click(screen.getByRole("button", { name: "Batches speichern" }));

  expect(await screen.findByText("Haferdrink")).toBeInTheDocument();
  expect(screen.getByText("2 Kartons")).toBeInTheDocument();
  expect(screen.getByText("Getränke")).toBeInTheDocument();
  expect(screen.getByText("Vorratsschrank")).toBeInTheDocument();
});

test("haushaltsmitglied kann ein packungsfoto prüfen und ein unsicheres datum erst nach bestätigung speichern", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();
  let confirmed = false;
  let packagePhotoDraftRequests = 0;

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/today") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          sections: {
            inventory: confirmed
              ? [
                  {
                    name: "Hackfleisch",
                    quantity: "500 g",
                    category: "Molkerei",
                    location: "Keller",
                    freshness: {
                      state: "normal",
                      source: "exact_date",
                      date_type: "use_by",
                      due_on: "2099-03-14"
                    }
                  }
                ]
              : [],
            needs_attention: [],
            upcoming: [],
            shopping_suggestions: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/package-photo/drafts") {
      expect(init?.body).toBeInstanceOf(FormData);
      return new Response(
        JSON.stringify({
          capture_id: "package-photo-capture-1",
          status: "processing",
          drafts: [],
          available_categories: [
            "Molkerei",
            "Obst & Gemüse",
            "Vorrat",
            "Getränke",
            "Sonstiges"
          ],
          available_locations: ["Kühlschrank", "Gefrierschrank", "Vorratsschrank"],
          available_date_types: ["best_before", "use_by"]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/package-photo/drafts/package-photo-capture-1") {
      packagePhotoDraftRequests += 1;
      return new Response(
        JSON.stringify({
          capture_id: "package-photo-capture-1",
          status: packagePhotoDraftRequests <= 25 ? "processing" : "pending_review",
          drafts:
            packagePhotoDraftRequests <= 25
              ? []
              : [
                  {
                    name: "Hackfleisch",
                    quantity: "500 g",
                    category: "Molkerei",
                    location: "Kühlschrank",
                    date_type: "use_by",
                    expires_on: "2099-03-14",
                    requires_date_review: true,
                    date_reviewed: false
                  }
                ],
          available_categories: [
            "Molkerei",
            "Obst & Gemüse",
            "Vorrat",
            "Getränke",
            "Sonstiges"
          ],
          available_locations: ["Kühlschrank", "Gefrierschrank", "Vorratsschrank"],
          available_date_types: ["best_before", "use_by"]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/package-photo/confirm") {
      const payload = JSON.parse(String(init?.body));
      expect(payload).toEqual({
        capture_id: "package-photo-capture-1",
        drafts: [
          {
            name: "Hackfleisch",
            quantity: "500 g",
            category: "Molkerei",
            location: "Keller",
            date_type: "use_by",
            expires_on: "2099-03-14",
            requires_date_review: true,
            date_reviewed: true
          }
        ]
      });
      confirmed = true;
      return new Response(
        JSON.stringify({
          batches: [
            {
              name: "Hackfleisch",
              quantity: "500 g",
              category: "Molkerei",
              location: "Keller"
            }
          ]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    return new Response("not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);

  render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

  await user.type(screen.getByLabelText("Haushaltsname"), "WG Sonnenseite");
  await user.type(screen.getByLabelText("Dein Name"), "Johannes");
  await user.click(screen.getByRole("button", { name: "Haushalt betreten" }));

  const file = new File(["fake-image-bytes"], "hackfleisch-label.jpg", { type: "image/jpeg" });
  await user.upload(await screen.findByLabelText("Packungsfoto"), file);
  await user.click(screen.getByRole("button", { name: "Packungsfoto prüfen" }));

  const draft = await screen.findByRole("group", { name: "Entwurf 1" }, { timeout: 10000 });
  expect(packagePhotoDraftRequests).toBeGreaterThan(0);
  expect(within(draft).getByLabelText("Datumstyp")).toHaveValue("use_by");
  expect(within(draft).getByLabelText("Ablaufdatum")).toHaveValue("2099-03-14");
  await user.clear(within(draft).getByLabelText("Lagerort"));
  await user.type(within(draft).getByLabelText("Lagerort"), "Keller");

  const saveButton = screen.getByRole("button", { name: "Batches speichern" });
  expect(saveButton).toBeDisabled();

  await user.click(within(draft).getByLabelText("Ich habe das Datum geprüft"));
  expect(saveButton).toBeEnabled();

  await user.click(saveButton);

  expect(await screen.findByText("Hackfleisch")).toBeInTheDocument();
  expect(screen.getByText("500 g")).toBeInTheDocument();
  expect(screen.getByText("Molkerei")).toBeInTheDocument();
  expect(screen.getByText("Keller")).toBeInTheDocument();
});

test("haushaltsmitglied kann eine sprachaufnahme hochladen und im gleichen prüffluss speichern", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();
  let confirmed = false;

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/today") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          sections: {
            inventory: confirmed
              ? [
                  {
                    name: "Haferdrink",
                    quantity: "2 Kartons",
                    category: "Getränke",
                    location: "Kühlschrank"
                  }
                ]
              : [],
            needs_attention: [],
            upcoming: [],
            shopping_suggestions: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/voice-capture/drafts") {
      return new Response(
        JSON.stringify({
          transcript: "2 Milch im Kühlschrank",
          drafts: [
            {
              name: "Milch",
              quantity: "2",
              category: "Molkerei",
              location: "Kühlschrank"
            }
          ],
          available_categories: [
            "Molkerei",
            "Obst & Gemüse",
            "Vorrat",
            "Getränke",
            "Sonstiges"
          ],
          available_locations: ["Kühlschrank", "Gefrierschrank", "Vorratsschrank"]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/text-capture/confirm") {
      confirmed = true;
      return new Response(
        JSON.stringify({
          batches: [
            {
              name: "Haferdrink",
              quantity: "2 Kartons",
              category: "Getränke",
              location: "Kühlschrank"
            }
          ]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    return new Response("not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);

  render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

  await user.type(screen.getByLabelText("Haushaltsname"), "WG Sonnenseite");
  await user.type(screen.getByLabelText("Dein Name"), "Johannes");
  await user.click(screen.getByRole("button", { name: "Haushalt betreten" }));

  const audioFile = new File(["pretend-audio"], "capture.webm", { type: "audio/webm" });
  await user.upload(await screen.findByLabelText("Audiodatei hochladen"), audioFile);
  await user.click(screen.getByRole("button", { name: "Audio transkribieren" }));

  const transcriptField = await screen.findByLabelText("Was habt ihr eingeräumt?");
  expect(transcriptField).toHaveValue("2 Milch im Kühlschrank");

  const draft = await screen.findByRole("group", { name: "Entwurf 1" });
  await user.clear(within(draft).getByLabelText("Name"));
  await user.type(within(draft).getByLabelText("Name"), "Haferdrink");
  await user.clear(within(draft).getByLabelText("Menge"));
  await user.type(within(draft).getByLabelText("Menge"), "2 Kartons");
  await user.selectOptions(within(draft).getByLabelText("Kategorie"), "Getränke");
  await user.click(screen.getByRole("button", { name: "Batches speichern" }));

  expect(await screen.findByText("Haferdrink")).toBeInTheDocument();
  expect(screen.getByText("2 Kartons")).toBeInTheDocument();

  const voiceCaptureCall = fetchMock.mock.calls.find(
    ([url]) => url === "http://api.example/api/voice-capture/drafts"
  );
  expect(voiceCaptureCall?.[1]?.body).toBeInstanceOf(FormData);
  expect((voiceCaptureCall?.[1]?.body as FormData).has("audio_file")).toBe(true);
});

test("haushaltsmitglied kann eine sprachaufnahme aufnehmen und als entwürfe prüfen", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();
  const stopTrack = vi.fn();
  const stream = {
    getTracks: () => [{ stop: stopTrack }]
  } as unknown as MediaStream;

  class FakeMediaRecorder {
    static readonly isTypeSupported = vi.fn(() => true);

    ondataavailable: ((event: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    mimeType = "audio/webm";

    constructor(readonly _stream: MediaStream) {}

    start() {}

    stop() {
      this.ondataavailable?.({ data: new Blob(["recorded-audio"], { type: "audio/webm" }) });
      this.onstop?.();
    }
  }

  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  Object.defineProperty(window.navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => stream)
    }
  });

  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/today") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          sections: {
            inventory: [],
            needs_attention: [],
            upcoming: [],
            shopping_suggestions: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/voice-capture/drafts") {
      return new Response(
        JSON.stringify({
          transcript: "2 Milch im Kühlschrank",
          drafts: [
            {
              name: "Milch",
              quantity: "2",
              category: "Molkerei",
              location: "Kühlschrank"
            }
          ],
          available_categories: [
            "Molkerei",
            "Obst & Gemüse",
            "Vorrat",
            "Getränke",
            "Sonstiges"
          ],
          available_locations: ["Kühlschrank", "Gefrierschrank", "Vorratsschrank"]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    return new Response("not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);

  render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

  await user.type(screen.getByLabelText("Haushaltsname"), "WG Sonnenseite");
  await user.type(screen.getByLabelText("Dein Name"), "Johannes");
  await user.click(screen.getByRole("button", { name: "Haushalt betreten" }));

  await user.click(await screen.findByRole("button", { name: "Aufnahme starten" }));
  await user.click(screen.getByRole("button", { name: "Aufnahme stoppen" }));

  expect(await screen.findByDisplayValue("2 Milch im Kühlschrank")).toBeInTheDocument();
  expect(await screen.findByRole("group", { name: "Entwurf 1" })).toBeInTheDocument();
  expect(stopTrack).toHaveBeenCalled();
});

test("haushaltsmitglied kann batchs öffnen verringern aufbrauchen entsorgen und den verlauf sehen", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();

  const batches = [
    {
      id: "batch-1",
      name: "Haferdrink",
      quantity: "2 Packungen",
      category: "Getränke",
      location: "Vorratsschrank",
      state: "sealed",
      freshness: null,
      events: []
    },
    {
      id: "batch-2",
      name: "Haferdrink",
      quantity: "2 Packungen",
      category: "Getränke",
      location: "Vorratsschrank",
      state: "sealed",
      freshness: null,
      events: []
    }
  ];

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/today") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          sections: {
            inventory: batches.map(({ id: _id, state: _state, events: _events, ...batch }) => batch),
            needs_attention: [],
            upcoming: [],
            shopping_suggestions: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/batches" && (init?.method === undefined || init.method === "GET")) {
      return new Response(
        JSON.stringify({
          batches: batches.map((batch) => ({ ...batch })),
          merge_suggestions: [
            {
              batch_ids: ["batch-1", "batch-2"],
              name: "Haferdrink",
              category: "Getränke",
              location: "Vorratsschrank",
              count: 2
            }
          ]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url.startsWith("http://api.example/api/batches/") && url.endsWith("/actions") && init?.method === "POST") {
      const batchId = url.split("/api/batches/")[1]?.split("/")[0];
      const payload = JSON.parse(String(init.body));
      const batch = batches.find((entry) => entry.id === batchId);
      if (!batch) {
        return new Response("not found", { status: 404 });
      }

      if (payload.action === "open") {
        batch.state = "opened";
        batch.events = [...batch.events, { action: "opened", member_name: "Johannes", created_at: "2026-05-20T10:00:00Z" }];
      }

      if (payload.action === "decrement") {
        batch.quantity = "1 Packung";
        batch.events = [...batch.events, { action: "decremented", member_name: "Johannes", created_at: "2026-05-20T10:05:00Z" }];
      }

      if (payload.action === "use_up") {
        batch.state = "depleted";
        batch.quantity = "0 Packungen";
        batch.events = [...batch.events, { action: "used_up", member_name: "Johannes", created_at: "2026-05-20T10:10:00Z" }];
      }

      if (payload.action === "discard") {
        batch.state = "discarded";
        batch.events = [...batch.events, { action: "discarded", member_name: "Johannes", created_at: "2026-05-20T10:15:00Z" }];
      }

      return new Response(JSON.stringify({ ...batch }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url.startsWith("http://api.example/api/batches/") && url.endsWith("/events")) {
      const batchId = url.split("/api/batches/")[1]?.split("/")[0];
      const batch = batches.find((entry) => entry.id === batchId);
      return new Response(
        JSON.stringify({
          events: batch?.events ?? []
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    return new Response("not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);

  render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

  await user.type(screen.getByLabelText("Haushaltsname"), "WG Sonnenseite");
  await user.type(screen.getByLabelText("Dein Name"), "Johannes");
  await user.click(screen.getByRole("button", { name: "Haushalt betreten" }));

  const batchCards = await screen.findAllByRole("group", { name: "Haferdrink" });
  const batchCard = batchCards[0];
  expect(screen.getByText("Mögliche doppelte Batches")).toBeInTheDocument();

  await user.click(within(batchCard).getByRole("button", { name: "Öffnen" }));
  expect(within(batchCard).getAllByText("Geöffnet").length).toBeGreaterThan(0);

  await user.click(within(batchCard).getByRole("button", { name: "Verringern" }));
  expect(within(batchCard).getByText("1 Packung")).toBeInTheDocument();

  await user.click(within(batchCard).getByRole("button", { name: "Aufbrauchen" }));
  expect(within(batchCard).getAllByText("Verbraucht").length).toBeGreaterThan(0);

  const secondBatchCard = screen.getAllByRole("group", { name: "Haferdrink" })[1];
  await user.click(within(secondBatchCard).getByRole("button", { name: "Entsorgen" }));
  expect(within(secondBatchCard).getAllByText("Entsorgt").length).toBeGreaterThan(0);
});

test("haushaltsmitglied kann einkaufslisten verwalten und nachkaufvorschläge übernehmen", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();
  let shoppingListsResponse = { lists: [], replenishment_suggestions: [] };
  let batchesResponse = { batches: [], merge_suggestions: [] };
  let todayResponse = {
    household_name: "WG Sonnenseite",
    member_name: "Johannes",
    locale: "de-DE",
    sections: {
      inventory: [],
      needs_attention: [],
      upcoming: [],
      shopping_suggestions: []
    }
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/today") {
      return new Response(JSON.stringify(todayResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/shopping-lists" && (init?.method === undefined || init.method === "GET")) {
      return new Response(JSON.stringify(shoppingListsResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/shopping-lists" && init?.method === "POST") {
      const payload = JSON.parse(String(init.body));
      shoppingListsResponse = {
        lists: [
          {
            id: "shopping-list-1",
            name: payload.name,
            items: []
          }
        ],
        replenishment_suggestions: []
      };
      return new Response(JSON.stringify(shoppingListsResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/text-capture/drafts") {
      return new Response(
        JSON.stringify({
          drafts: [
            {
              name: "Bio Milch",
              quantity: "2",
              category: "Molkerei",
              location: "Kühlschrank",
              date_type: null,
              expires_on: null
            }
          ],
          available_categories: ["Molkerei", "Obst & Gemüse", "Vorrat", "Getränke", "Sonstiges"],
          available_locations: ["Kühlschrank", "Gefrierschrank", "Vorratsschrank"]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/text-capture/confirm") {
      batchesResponse = {
        batches: [
          {
            id: "batch-1",
            name: "Bio Milch",
            quantity: "1",
            category: "Molkerei",
            location: "Kühlschrank",
            state: "sealed",
            freshness: null,
            events: []
          }
        ],
        merge_suggestions: []
      };
      return new Response(
        JSON.stringify({
          batches: [
            {
              name: "Bio Milch",
              quantity: "1",
              category: "Molkerei",
              location: "Kühlschrank"
            }
          ]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/batches") {
      return new Response(JSON.stringify(batchesResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/batches/batch-1/actions" && init?.method === "POST") {
      batchesResponse = {
        batches: [
          {
            id: "batch-1",
            name: "Bio Milch",
            quantity: "0",
            category: "Molkerei",
            location: "Kühlschrank",
            state: "depleted",
            freshness: null,
            events: []
          }
        ],
        merge_suggestions: []
      };
      todayResponse = {
        ...todayResponse,
        sections: {
          ...todayResponse.sections,
          shopping_suggestions: [
            {
              id: "suggestion-1",
              product_key: "bio-milch",
              name: "Bio Milch",
              quantity: "1",
              source_action: "used_up",
              source_batch_name: "Bio Milch",
              accepted_at: null,
              accepted_list_id: null
            }
          ]
        }
      };
      return new Response(
        JSON.stringify({
          id: "batch-1",
          name: "Bio Milch",
          quantity: "0",
          category: "Molkerei",
          location: "Kühlschrank",
          state: "depleted",
          freshness: null,
          events: []
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/shopping-suggestions/suggestion-1/accept" && init?.method === "POST") {
      shoppingListsResponse = {
        lists: [
          {
            id: "shopping-list-1",
            name: "Samstag",
            items: [
              {
                id: "shopping-item-1",
                product_key: "bio-milch",
                name: "Bio Milch",
                quantity: "2"
              }
            ]
          }
        ],
        replenishment_suggestions: []
      };
      todayResponse = {
        ...todayResponse,
        sections: {
          ...todayResponse.sections,
          shopping_suggestions: []
        }
      };
      return new Response(JSON.stringify(shoppingListsResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    return new Response("not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);

  render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

  await user.type(screen.getByLabelText("Haushaltsname"), "WG Sonnenseite");
  await user.type(screen.getByLabelText("Dein Name"), "Johannes");
  await user.click(screen.getByRole("button", { name: "Haushalt betreten" }));

  await user.type(screen.getByLabelText("Listenname"), "Samstag");
  await user.click(screen.getByRole("button", { name: "Liste anlegen" }));
  expect(await screen.findByText("Samstag")).toBeInTheDocument();

  await user.type(screen.getByLabelText("Was habt ihr eingeräumt?"), "2 Bio Milch im Kühlschrank");
  await user.click(screen.getByRole("button", { name: "Entwürfe erstellen" }));
  await user.click(screen.getByRole("button", { name: "Batches speichern" }));

  const batchGroup = await screen.findByRole("group", { name: "Bio Milch" });
  await user.click(within(batchGroup).getByRole("button", { name: "Verringern" }));

  expect(await screen.findByText("bio-milch")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Vorschlag übernehmen" }));

  expect(screen.queryByRole("button", { name: "Vorschlag übernehmen" })).not.toBeInTheDocument();
  expect(screen.getByText("Samstag")).toBeInTheDocument();
});

test("haushaltsmitglied sieht änderungen anderer geräte ohne neu laden", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();
  let shoppingListsResponse = {
    lists: [
      {
        id: "shopping-list-1",
        name: "Samstag",
        items: []
      }
    ],
    replenishment_suggestions: []
  };
  let syncTick: (() => Promise<void>) | undefined;
  const freshnessPoliciesResponse = {
    policies: [
      {
        category: "Getränke",
        default_shelf_life_days: 14,
        default_soon_window_days: 4,
        shelf_life_days: 14,
        soon_window_days: 4,
        is_override: false
      }
    ]
  };
  const todayResponse = {
    household_name: "WG Sonnenseite",
    member_name: "Johannes",
    locale: "de-DE",
    sections: {
      inventory: [],
      needs_attention: [],
      upcoming: [],
      shopping_suggestions: []
    }
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/today") {
      return new Response(JSON.stringify(todayResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/freshness-overrides") {
      return new Response(JSON.stringify(freshnessPoliciesResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/batches") {
      return new Response(
        JSON.stringify({
          batches: [],
          merge_suggestions: []
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/shopping-lists") {
      return new Response(JSON.stringify(shoppingListsResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/shopping-lists" && init?.method === "POST") {
      shoppingListsResponse = {
        lists: [
          {
            id: "shopping-list-1",
            name: "Samstag",
            items: [
              {
                id: "shopping-item-1",
                product_key: "bio-milch",
                name: "Bio Milch",
                quantity: "2"
              }
            ]
          }
        ],
        replenishment_suggestions: []
      };
      return new Response(JSON.stringify(shoppingListsResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    return new Response("not found", { status: 404 });
  });

  const setIntervalSpy = vi.spyOn(window, "setInterval").mockImplementation(((handler: TimerHandler, timeout?: number) => {
    if (timeout === 5000) {
      syncTick = async () => {
        if (typeof handler === "function") {
          await handler();
        }
      };
    }
    return 1 as unknown as number;
  }) as typeof window.setInterval);
  const clearIntervalSpy = vi.spyOn(window, "clearInterval").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", fetchMock);

  try {
    render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

    await user.type(screen.getByLabelText("Haushaltsname"), "WG Sonnenseite");
    await user.type(screen.getByLabelText("Dein Name"), "Johannes");
    await user.click(screen.getByRole("button", { name: "Haushalt betreten" }));

    expect(await screen.findByText("Samstag")).toBeInTheDocument();
    expect(screen.getByText("Noch keine Einkaufslisten angelegt.")).toBeInTheDocument();
    expect(syncTick).toBeDefined();

    shoppingListsResponse = {
      lists: [
        {
          id: "shopping-list-1",
          name: "Samstag",
          items: [
            {
              id: "shopping-item-1",
              product_key: "bio-milch",
              name: "Bio Milch",
              quantity: "2"
            }
          ]
        }
      ],
      replenishment_suggestions: []
    };

    await act(async () => {
      await syncTick?.();
    });

    await waitFor(() => expect(screen.getByText("Bio Milch")).toBeInTheDocument(), { timeout: 10000 });
    expect(screen.getByText("2")).toBeInTheDocument();
  } finally {
    setIntervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
  }
}, 10000);

test("haushaltsmitglied sieht zwischengespeicherte daten und eine offline-aktion wird später erneut versucht", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();
  storage.setItem(
    "freshbot.householdSession",
    JSON.stringify({
      token: "session-token",
      locale: "de-DE",
      household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
      member: { display_name: "Johannes" }
    })
  );
  storage.setItem(
    "freshbot.householdCache:session-token",
    JSON.stringify({
      today: {
        household_name: "WG Sonnenseite",
        member_name: "Johannes",
        locale: "de-DE",
        sections: {
          inventory: [
            {
              name: "Haferdrink",
              quantity: "2 Packungen",
              category: "Getränke",
              location: "Vorratsschrank"
            }
          ],
          needs_attention: [],
          upcoming: [],
          shopping_suggestions: []
        }
      },
      batchView: {
        batches: [
          {
            id: "batch-1",
            name: "Haferdrink",
            quantity: "2 Packungen",
            category: "Getränke",
            location: "Vorratsschrank",
            state: "sealed",
            freshness: null,
            events: []
          }
        ],
        merge_suggestions: []
      },
      shoppingView: {
        lists: [],
        replenishment_suggestions: []
      },
      freshnessPolicies: []
    })
  );

  let online = false;
  let syncTick: (() => void) | undefined;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (!online) {
      throw new TypeError("offline");
    }

    if (url === "http://api.example/api/today") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          sections: {
            inventory: [
              {
                name: "Haferdrink",
                quantity: "0 Packungen",
                category: "Getränke",
                location: "Vorratsschrank"
              }
            ],
            needs_attention: [],
            upcoming: [],
            shopping_suggestions: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/freshness-overrides") {
      return new Response(JSON.stringify({ policies: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/batches" && (init?.method === undefined || init.method === "GET")) {
      return new Response(
        JSON.stringify({
          batches: [
            {
              id: "batch-1",
              name: "Haferdrink",
              quantity: "0 Packungen",
              category: "Getränke",
              location: "Vorratsschrank",
              state: "depleted",
              freshness: null,
              events: []
            }
          ],
          merge_suggestions: []
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/batches/batch-1/actions" && init?.method === "POST") {
      return new Response(
        JSON.stringify({
          id: "batch-1",
          name: "Haferdrink",
          quantity: "0 Packungen",
          category: "Getränke",
          location: "Vorratsschrank",
          state: "depleted",
          freshness: null,
          events: []
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/shopping-lists") {
      return new Response(JSON.stringify({ lists: [], replenishment_suggestions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    return new Response("not found", { status: 404 });
  });

  const setIntervalSpy = vi.spyOn(window, "setInterval").mockImplementation(((handler: TimerHandler, timeout?: number) => {
    if (timeout === 5000) {
      syncTick = () => {
        if (typeof handler === "function") {
          handler();
        }
      };
    }
    return 1 as unknown as number;
  }) as typeof window.setInterval);
  const clearIntervalSpy = vi.spyOn(window, "clearInterval").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", fetchMock);

  try {
    render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

    expect(screen.getByText("Zwischengespeicherte Daten werden angezeigt.")).toBeInTheDocument();
    expect(syncTick).toBeDefined();

    const batchButton = screen.getByRole("button", { name: "Aufbrauchen" });
    await user.click(batchButton);

    expect(screen.getByRole("status")).toHaveTextContent("Eine Änderung ist vorgemerkt");

    online = true;
    await act(async () => {
      await syncTick?.();
    });

    expect(await screen.findByText("Verbraucht")).toBeInTheDocument();
    expect(screen.queryByText("Zwischengespeicherte Daten werden angezeigt.")).not.toBeInTheDocument();
  } finally {
    setIntervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
  }
});

test("haushaltsmitglied lässt eine ungültige offline-änderung fallen und spielt spätere änderungen trotzdem ein", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();
  storage.setItem(
    "freshbot.householdSession",
    JSON.stringify({
      token: "session-token",
      locale: "de-DE",
      household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
      member: { display_name: "Johannes" }
    })
  );
  storage.setItem(
    "freshbot.householdCache:session-token",
    JSON.stringify({
      today: {
        household_name: "WG Sonnenseite",
        member_name: "Johannes",
        locale: "de-DE",
        sections: {
          inventory: [],
          needs_attention: [],
          upcoming: [],
          shopping_suggestions: []
        }
      },
      batchView: {
        batches: [],
        merge_suggestions: []
      },
      shoppingView: {
        lists: [],
        replenishment_suggestions: []
      },
      freshnessPolicies: []
    })
  );

  let online = false;
  let syncTick: (() => Promise<void>) | undefined;
  const createdShoppingLists: Array<{ id: string; name: string; items: Array<Record<string, never>> }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (!online) {
      throw new TypeError("offline");
    }

    if (url === "http://api.example/api/today") {
      return new Response(
        JSON.stringify({
          household_name: "WG Sonnenseite",
          member_name: "Johannes",
          locale: "de-DE",
          sections: {
            inventory: [],
            needs_attention: [],
            upcoming: [],
            shopping_suggestions: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "http://api.example/api/batches") {
      return new Response(JSON.stringify({ batches: [], merge_suggestions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/shopping-lists" && (init?.method === undefined || init.method === "GET")) {
      return new Response(JSON.stringify({ lists: createdShoppingLists, replenishment_suggestions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/shopping-lists" && init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as { name: string };
      if (body.name === "Ungültige Liste") {
        return new Response(JSON.stringify({ detail: "invalid shopping list" }), {
          status: 422,
          headers: { "Content-Type": "application/json" }
        });
      }

      const list = { id: "shopping-list-1", name: body.name, items: [] };
      createdShoppingLists.push(list);
      return new Response(JSON.stringify(list), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    return new Response("not found", { status: 404 });
  });

  const setIntervalSpy = vi.spyOn(window, "setInterval").mockImplementation(((handler: TimerHandler, timeout?: number) => {
    if (timeout === 5000) {
      syncTick = () => {
        if (typeof handler === "function") {
          handler();
        }
        return Promise.resolve();
      };
    }
    return 1 as unknown as number;
  }) as typeof window.setInterval);
  const clearIntervalSpy = vi.spyOn(window, "clearInterval").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", fetchMock);

  try {
    render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

    expect(screen.getByText("Zwischengespeicherte Daten werden angezeigt.")).toBeInTheDocument();
    expect(syncTick).toBeDefined();

    await user.type(screen.getByLabelText("Listenname"), "Ungültige Liste");
    await user.click(screen.getByRole("button", { name: "Liste anlegen" }));
    await user.type(screen.getByLabelText("Listenname"), "Vorratsliste");
    await user.click(screen.getByRole("button", { name: "Liste anlegen" }));

    expect(screen.getByRole("status")).toHaveTextContent("Eine Änderung ist vorgemerkt");

    online = true;
    await act(async () => {
      await syncTick?.();
    });

    expect(await screen.findByText("Vorratsliste")).toBeInTheDocument();
    expect(screen.queryByText("Zwischengespeicherte Daten werden angezeigt.")).not.toBeInTheDocument();
  } finally {
    setIntervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
  }
});

test("haushaltsmitglied sieht nach dem wiederverbinden keine veralteten refresh-daten mehr", async () => {
  const user = userEvent.setup();
  const storage = new MemoryStorage();
  storage.setItem(
    "freshbot.householdSession",
    JSON.stringify({
      token: "session-token",
      locale: "de-DE",
      household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
      member: { display_name: "Johannes" }
    })
  );
  storage.setItem(
    "freshbot.householdCache:session-token",
    JSON.stringify({
      today: {
        household_name: "WG Sonnenseite",
        member_name: "Johannes",
        locale: "de-DE",
        sections: {
          inventory: [
            {
              name: "Bio Milch",
              quantity: "1 Packung",
              category: "Molkerei",
              location: "Kühlschrank"
            }
          ],
          needs_attention: [],
          upcoming: [],
          shopping_suggestions: []
        }
      },
      batchView: {
        batches: [
          {
            id: "batch-1",
            name: "Bio Milch",
            quantity: "1 Packung",
            category: "Molkerei",
            location: "Kühlschrank",
            state: "sealed",
            freshness: null,
            events: []
          }
        ],
        merge_suggestions: []
      },
      shoppingView: {
        lists: [
          {
            id: "shopping-list-1",
            name: "Samstag",
            items: []
          }
        ],
        replenishment_suggestions: []
      },
      freshnessPolicies: []
    })
  );

  let online = false;
  let replayCompleted = false;
  let syncTick: (() => Promise<void>) | undefined;
  let resolveReplayAction: (() => void) | undefined;
  const staleRefreshResolvers: Array<() => void> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url === "http://api.example/api/auth/household-session") {
      return new Response(
        JSON.stringify({
          token: "session-token",
          locale: "de-DE",
          household: { name: "WG Sonnenseite", slug: "wg-sonnenseite" },
          member: { display_name: "Johannes" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (!online) {
      throw new TypeError("offline");
    }

    if (url === "http://api.example/api/batches/batch-1/actions" && init?.method === "POST") {
      return new Promise<Response>((resolve) => {
        resolveReplayAction = () => {
          replayCompleted = true;
          resolve(
            new Response(
              JSON.stringify({
                id: "batch-1",
                name: "Bio Milch",
                quantity: "0 Packungen",
                category: "Molkerei",
                location: "Kühlschrank",
                state: "depleted",
                freshness: null,
                events: []
              }),
              { status: 200, headers: { "Content-Type": "application/json" } }
            )
          );
        };
      });
    }

    if (url === "http://api.example/api/today") {
      const response = replayCompleted
        ? {
            household_name: "WG Sonnenseite",
            member_name: "Johannes",
            locale: "de-DE",
            sections: {
              inventory: [
                {
                  name: "Bio Milch",
                  quantity: "0 Packungen",
                  category: "Molkerei",
                  location: "Kühlschrank"
                }
              ],
              needs_attention: [],
              upcoming: [],
              shopping_suggestions: [
                {
                  id: "suggestion-1",
                  product_key: "bio-milch",
                  name: "Bio Milch",
                  quantity: "1",
                  source_action: "used_up",
                  source_batch_name: "Bio Milch",
                  accepted_at: null,
                  accepted_list_id: null
                }
              ]
            }
          }
        : null;
      if (response !== null) {
        return new Response(JSON.stringify(response), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      return new Promise<Response>((resolve) => {
        staleRefreshResolvers.push(() => {
          resolve(
            new Response(
              JSON.stringify({
                household_name: "WG Sonnenseite",
                member_name: "Johannes",
                locale: "de-DE",
                sections: {
                  inventory: [
                    {
                      name: "Bio Milch",
                      quantity: "1 Packung",
                      category: "Molkerei",
                      location: "Kühlschrank"
                    }
                  ],
                  needs_attention: [],
                  upcoming: [],
                  shopping_suggestions: []
                }
              }),
              { status: 200, headers: { "Content-Type": "application/json" } }
            )
          );
        });
      });
    }

    if (url === "http://api.example/api/freshness-overrides") {
      return new Response(JSON.stringify({ policies: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    if (url === "http://api.example/api/batches") {
      if (replayCompleted) {
        return new Response(
          JSON.stringify({
            batches: [
              {
                id: "batch-1",
                name: "Bio Milch",
                quantity: "0 Packungen",
                category: "Molkerei",
                location: "Kühlschrank",
                state: "depleted",
                freshness: null,
                events: []
              }
            ],
            merge_suggestions: []
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Promise<Response>((resolve) => {
        staleRefreshResolvers.push(() => {
          resolve(
            new Response(
              JSON.stringify({
                batches: [
                  {
                    id: "batch-1",
                    name: "Bio Milch",
                    quantity: "1 Packung",
                    category: "Molkerei",
                    location: "Kühlschrank",
                    state: "sealed",
                    freshness: null,
                    events: []
                  }
                ],
                merge_suggestions: []
              }),
              { status: 200, headers: { "Content-Type": "application/json" } }
            )
          );
        });
      });
    }

    if (url === "http://api.example/api/shopping-lists") {
      if (replayCompleted) {
        return new Response(
          JSON.stringify({
            lists: [
              {
                id: "shopping-list-1",
                name: "Samstag",
                items: []
              }
            ],
            replenishment_suggestions: []
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Promise<Response>((resolve) => {
        staleRefreshResolvers.push(() => {
          resolve(
            new Response(
              JSON.stringify({
                lists: [
                  {
                    id: "shopping-list-1",
                    name: "Samstag",
                    items: []
                  }
                ],
                replenishment_suggestions: []
              }),
              { status: 200, headers: { "Content-Type": "application/json" } }
            )
          );
        });
      });
    }

    return new Response("not found", { status: 404 });
  });

  const setIntervalSpy = vi.spyOn(window, "setInterval").mockImplementation(((handler: TimerHandler, timeout?: number) => {
    if (timeout === 5000) {
      syncTick = async () => {
        if (typeof handler === "function") {
          await handler();
        }
      };
    }
    return 1 as unknown as number;
  }) as typeof window.setInterval);
  const clearIntervalSpy = vi.spyOn(window, "clearInterval").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", fetchMock);

  try {
    render(<HouseholdShell apiBaseUrl="http://api.example" storage={storage} />);

    expect(screen.getByText("Zwischengespeicherte Daten werden angezeigt.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Verringern" }));
    expect(screen.getByRole("status")).toHaveTextContent("Eine Änderung ist vorgemerkt");

    online = true;
    await act(async () => {
      void syncTick?.();
    });
    expect(staleRefreshResolvers).toHaveLength(0);
    await waitFor(() => expect(resolveReplayAction).toBeDefined());

    await act(async () => {
      resolveReplayAction?.();
    });

    expect(await screen.findByText("Verbraucht")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Vorschlag übernehmen" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Verbraucht")).toBeInTheDocument());
    expect(screen.queryByText("1 Packung")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Vorschlag übernehmen" })).toBeInTheDocument();
  } finally {
    setIntervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
  }
});
