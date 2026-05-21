import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { HouseholdShell } from "./household-shell";


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
                    location: "Kühlschrank",
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
          status: packagePhotoDraftRequests === 1 ? "processing" : "pending_review",
          drafts:
            packagePhotoDraftRequests === 1
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
            location: "Kühlschrank",
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

  const file = new File(["fake-image-bytes"], "hackfleisch-label.jpg", { type: "image/jpeg" });
  await user.upload(await screen.findByLabelText("Packungsfoto"), file);
  await user.click(screen.getByRole("button", { name: "Packungsfoto prüfen" }));

  const draft = await screen.findByRole("group", { name: "Entwurf 1" });
  expect(packagePhotoDraftRequests).toBeGreaterThan(0);
  expect(within(draft).getByLabelText("Datumstyp")).toHaveValue("use_by");
  expect(within(draft).getByLabelText("Ablaufdatum")).toHaveValue("2099-03-14");

  const saveButton = screen.getByRole("button", { name: "Batches speichern" });
  expect(saveButton).toBeDisabled();

  await user.click(within(draft).getByLabelText("Ich habe das Datum geprüft"));
  expect(saveButton).toBeEnabled();

  await user.click(saveButton);

  expect(await screen.findByText("Hackfleisch")).toBeInTheDocument();
  expect(screen.getByText("500 g")).toBeInTheDocument();
  expect(screen.getByText("Molkerei")).toBeInTheDocument();
  expect(screen.getByText("Kühlschrank")).toBeInTheDocument();
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
