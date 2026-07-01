import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Navigate, RouterProvider, createMemoryRouter } from "react-router-dom";
import { describe, expect, test, vi } from "vitest";

import { SelectionProvider } from "../src/app/SelectionContext";
import { createQueryClient } from "../src/app/query-client";
import { Layout } from "../src/components/Layout";
import { DownloadsPage } from "../src/pages/DownloadsPage";
import { LibraryPage } from "../src/pages/LibraryPage";

const profilesResponse = {
  profiles: [
    { id: "pepe", display_name: "Pepe" },
    { id: "manolo", display_name: "Manolo" },
  ],
};

const rootEntriesResponse = {
  profile: { id: "pepe", display_name: "Pepe" },
  path: "",
  entries: [
    { name: "Rock", path: "Rock", type: "directory", size_bytes: null },
    { name: "tema.mp3", path: "tema.mp3", type: "file", size_bytes: 1200 },
  ],
};

const rockEntriesResponse = {
  profile: { id: "pepe", display_name: "Pepe" },
  path: "Rock",
  entries: [{ name: "Clasicos", path: "Rock/Clasicos", type: "directory", size_bytes: null }],
};

const downloadsResponse = {
  items: [
    {
      id: "00000000-0000-4000-8000-000000000001",
      profile_id: "pepe",
      source_url: "https://www.youtube.com/watch?v=VIDEO_ID",
      destination_path: "Rock",
      audio_policy: "prefer_m4a_then_best_source",
      status: "running",
      progress_percent: null,
      title: null,
      output_path: null,
      created_at: "2026-07-01T12:00:00Z",
      started_at: null,
      finished_at: null,
    },
    {
      id: "00000000-0000-4000-8000-000000000002",
      profile_id: "pepe",
      source_url: "https://example.invalid/audio",
      destination_path: "Rock/Clasicos",
      audio_policy: "prefer_m4a_then_best_source",
      status: "completed",
      progress_percent: 100,
      title: "Canción final",
      output_path: "Rock/Clasicos/Canción final [abc].m4a",
      created_at: "2026-07-01T13:00:00Z",
      started_at: null,
      finished_at: "2026-07-01T13:05:00Z",
    },
  ],
  total: 2,
  limit: 25,
  offset: 0,
};

describe("frontend", () => {
  test("redirige desde la raíz a descargas", async () => {
    mockApi();
    renderApp(["/"]);

    expect(await screen.findByRole("heading", { name: "Nueva descarga" })).toBeInTheDocument();
  });

  test("renderiza perfiles cargados y permite seleccionar perfil", async () => {
    mockApi();
    const user = userEvent.setup();
    renderApp(["/downloads"]);

    const select = await screen.findByLabelText("Perfil");
    await screen.findByRole("option", { name: "Pepe" });
    expect(within(select).getByRole("option", { name: "Pepe" })).toBeInTheDocument();
    await user.selectOptions(select, "manolo");
    expect(select).toHaveValue("manolo");
  });

  test("carga raíz, navega a subdirectorio y selecciona carpeta destino", async () => {
    mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe&select=1"]);

    expect(await screen.findByText("/Rock")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Rock/ }));
    expect(await screen.findByText("/Rock/Clasicos")).toBeInTheDocument();
    expect(screen.queryByText("/mnt/music")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Seleccionar esta carpeta" }));
    expect(await screen.findByText("Destino:")).toBeInTheDocument();
    expect(screen.getAllByText("/Rock").length).toBeGreaterThan(0);
  });

  test("envía formulario con profile_id, source_url y destination_path correctos", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe&select=1"]);

    await screen.findByText("/Rock");
    await user.click(screen.getByRole("button", { name: /Rock/ }));
    await screen.findByText("/Rock/Clasicos");
    await user.click(screen.getByRole("button", { name: "Seleccionar esta carpeta" }));
    await user.type(await screen.findByLabelText("URL"), "https://www.youtube.com/watch?v=abc");
    await user.click(screen.getByRole("button", { name: "Crear trabajo" }));

    await screen.findByText("Trabajo de descarga creado correctamente.");
    const postCall = fetchMock.mock.calls.find(([url, init]) =>
      String(url).endsWith("/api/v1/downloads") && init?.method === "POST",
    );
    expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
      profile_id: "pepe",
      source_url: "https://www.youtube.com/watch?v=abc",
      destination_path: "Rock",
    });
  });

  test("muestra error seguro devuelto por API", async () => {
    mockApi({ createDownloadStatus: 422, createDownloadBody: { detail: "Invalid source URL." } });
    const user = userEvent.setup();
    renderApp(["/downloads"]);

    await user.type(await screen.findByLabelText("URL"), "no-es-url");
    await user.click(screen.getByRole("button", { name: "Crear trabajo" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid source URL.");
  });

  test("muestra lista de trabajos con estados y progreso", async () => {
    mockApi();
    renderApp(["/downloads"]);

    expect(await screen.findByText("Descargando")).toBeInTheDocument();
    expect(screen.getByText("Indeterminado")).toBeInTheDocument();
    expect(screen.getByText("Completada")).toBeInTheDocument();
    expect(screen.getByText("100 %")).toBeInTheDocument();
    expect(screen.getByText("/Rock/Clasicos/Canción final [abc].m4a")).toBeInTheDocument();
    expect(screen.queryByText(/root_path|worker_id|\/mnt\/music/)).not.toBeInTheDocument();
  });

  test("maneja API no disponible", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network"));
    renderApp(["/downloads"]);

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo contactar con la API.");
  });
});

function renderApp(initialEntries: string[]) {
  const queryClient = createQueryClient();
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <Layout />,
        children: [
          { index: true, element: <Navigate to="/downloads" replace /> },
          { path: "downloads", element: <DownloadsPage /> },
          { path: "library", element: <LibraryPage /> },
        ],
      },
    ],
    { initialEntries },
  );

  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <RouterProvider router={router} />
      </SelectionProvider>
    </QueryClientProvider>,
  );
}

function mockApi(options: { createDownloadStatus?: number; createDownloadBody?: unknown } = {}) {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/profiles/pepe/entries?path=Rock")) {
      return jsonResponse(rockEntriesResponse);
    }
    if (url.includes("/profiles/pepe/entries?path=")) {
      return jsonResponse(rootEntriesResponse);
    }
    if (url.endsWith("/profiles")) {
      return jsonResponse(profilesResponse);
    }
    if (url.includes("/downloads") && init?.method === "POST") {
      return jsonResponse(
        options.createDownloadBody ?? { id: "new", profile: profilesResponse.profiles[0] },
        options.createDownloadStatus ?? 201,
      );
    }
    if (url.includes("/downloads")) {
      return jsonResponse(downloadsResponse);
    }
    return jsonResponse({ detail: "Not found" }, 404);
  });
  return fetchMock;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
