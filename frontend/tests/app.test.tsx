import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Navigate, RouterProvider, createMemoryRouter } from "react-router-dom";
import { describe, expect, test, vi } from "vitest";

import { SelectionProvider } from "../src/app/SelectionContext";
import { ThemeProvider } from "../src/app/ThemeContext";
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
    makeJob("1", "running", null, null),
    makeJob("2", "completed", 100, "Rock/Clasicos/Canción final [abc].m4a"),
    makeJob("3", "queued", 0, null),
    makeJob("4", "failed", 12, null),
    makeJob("5", "cancelled", null, null),
    makeLongJob(),
  ],
  total: 6,
  limit: 25,
  offset: 0,
};

type FetchSpy = ReturnType<typeof mockApi>;

describe("frontend rediseñado", () => {
  test("redirige desde raíz, renderiza navegación principal y cambia tema persistido", async () => {
    mockApi();
    const user = userEvent.setup();
    renderApp(["/"]);

    expect(await screen.findByRole("heading", { name: "Nueva descarga" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Descargas/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: /Biblioteca/ }).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Cambiar a tema oscuro" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("yt-downloader-theme")).toBe("dark");
    expect(screen.getByRole("button", { name: "Cambiar a tema claro" })).toBeInTheDocument();
  });

  test("permite seleccionar perfil desde descargas", async () => {
    mockApi();
    const user = userEvent.setup();
    renderApp(["/downloads"]);

    const select = await screen.findByLabelText("Perfil");
    await screen.findByRole("option", { name: "Pepe" });
    await user.selectOptions(select, "manolo");
    expect(select).toHaveValue("manolo");
  });

  test("muestra estados de descarga con progreso y resultado sin rutas privadas", async () => {
    mockApi();
    renderApp(["/downloads"]);

    expect(await screen.findByText("Descargando")).toBeInTheDocument();
    expect(screen.getAllByText("Indeterminado").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Completada").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Nombre solicitado: Sandunga verano")).toBeInTheDocument();
    expect(screen.getByText("En cola")).toBeInTheDocument();
    expect(screen.getByText("Fallida")).toBeInTheDocument();
    expect(screen.getByText("Cancelada")).toBeInTheDocument();
    expect(screen.getAllByText("100 %").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("/Rock/Clasicos/Canción final [abc].m4a")).toBeInTheDocument();
    expect(screen.queryByText(/root_path|worker_id|\/mnt\/music/)).not.toBeInTheDocument();
  });

  test("renderiza trabajos con título, nombre solicitado y resultado largos", async () => {
    mockApi();
    renderApp(["/downloads"]);

    expect(await screen.findByText(/Título extremadamente largo/)).toBeInTheDocument();
    expect(screen.getByText(/Nombre solicitado: Sandunga verano edición extendida/)).toBeInTheDocument();
    expect(screen.getByText(/archivo-final-con-un-nombre-muy-largo/)).toBeInTheDocument();
  });

  test("envía nueva descarga con profile_id, source_url y destination_path correctos", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe&select=1"]);

    await user.dblClick(await screen.findByRole("listitem", { name: "Seleccionar Rock" }));
    await screen.findByRole("heading", { name: "/Rock" });
    await user.click(screen.getByRole("button", { name: "Seleccionar esta carpeta" }));
    await user.type(await screen.findByLabelText(/URL/), "https://www.youtube.com/watch?v=abc");
    await user.click(screen.getByRole("button", { name: "Añadir a la cola" }));

    expect(await screen.findByText("Trabajo de descarga creado correctamente.")).toBeInTheDocument();
    const postCall = findFetchCall(fetchMock, "/api/v1/downloads", "POST");
    expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
      profile_id: "pepe",
      source_url: "https://www.youtube.com/watch?v=abc",
      destination_path: "Rock",
      requested_filename: null,
    });
  });

  test("envía nombre personalizado válido al crear una descarga", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/downloads"]);

    expect(await screen.findByText(/Opcional\. No indiques la extensión/)).toBeInTheDocument();
    await user.type(await screen.findByLabelText(/URL/), "https://www.youtube.com/watch?v=abc");
    await user.type(screen.getByLabelText(/Nombre del archivo/), "Sandunga verano");
    await user.click(screen.getByRole("button", { name: "Añadir a la cola" }));

    const postCall = findFetchCall(fetchMock, "/api/v1/downloads", "POST");
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      requested_filename: "Sandunga verano",
    });
  });

  test.each([
    ["Rock/tema", "El nombre del archivo no puede contener rutas ni caracteres de control."],
    ["tema.m4a", "No incluyas la extensión del archivo; el sistema la determina automáticamente."],
    [".", "El nombre del archivo no puede ser oculto ni reservado."],
    ["a".repeat(181), "El nombre del archivo no puede superar 180 caracteres."],
  ])("muestra validación local de nombre personalizado: %s", async (filename, message) => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/downloads"]);

    await user.type(await screen.findByLabelText(/URL/), "https://www.youtube.com/watch?v=abc");
    await user.type(screen.getByLabelText(/Nombre del archivo/), filename);
    await user.click(screen.getByRole("button", { name: "Añadir a la cola" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(findFetchCall(fetchMock, "/api/v1/downloads", "POST")).toBeUndefined();
  });

  test("muestra errores de descargas traducidos al español", async () => {
    mockApi({ createDownloadStatus: 422, createDownloadBody: { detail: "Invalid source URL." } });
    const user = userEvent.setup();
    renderApp(["/downloads"]);

    await user.type(await screen.findByLabelText(/URL/), "no-es-url");
    await user.click(screen.getByRole("button", { name: "Añadir a la cola" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("La URL de origen no es válida.");
    expect(alert).not.toHaveTextContent("Invalid source URL.");
  });

  test("abre panel móvil de carpetas y expande árbol bajo demanda", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    expect(await screen.findByRole("button", { name: "Carpetas" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Expandir Rock" }));
    expect(await screen.findByRole("button", { name: "Clasicos" })).toBeInTheDocument();
    expect(countFetchCalls(fetchMock, "/api/v1/profiles/pepe/entries?path=Rock")).toBeGreaterThan(0);
  });

  test("navega por carpeta con doble clic y selecciona destino", async () => {
    mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe&select=1"]);

    await user.dblClick(await screen.findByRole("listitem", { name: "Seleccionar Rock" }));
    expect(await screen.findByRole("heading", { name: "/Rock" })).toBeInTheDocument();
    expect(screen.queryByText("/mnt/music")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Seleccionar esta carpeta" }));
    expect(await screen.findByText("Destino seleccionado")).toBeInTheDocument();
    expect(screen.getAllByText("/Rock").length).toBeGreaterThan(0);
  });

  test("crea carpeta en la carpeta activa con payload correcto", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await user.dblClick(await screen.findByRole("listitem", { name: "Seleccionar Rock" }));
    await screen.findByRole("heading", { name: "/Rock" });
    await user.click(screen.getByRole("button", { name: "Crear carpeta" }));
    await user.type(screen.getByLabelText("Nombre de la carpeta"), "Directos");
    await user.click(screen.getByRole("button", { name: "Crear" }));

    expect(await screen.findByText("Carpeta creada correctamente.")).toBeInTheDocument();
    const postCall = findFetchCall(fetchMock, "/api/v1/profiles/pepe/directories", "POST");
    expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({ parent_path: "Rock", name: "Directos" });
  });

  test("usa menú contextual para renombrar una entrada", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await user.click(await screen.findByRole("listitem", { name: "Seleccionar Rock" }));
    await user.click(screen.getByRole("button", { name: "Acciones..." }));
    await user.click(screen.getByRole("menuitem", { name: "Renombrar" }));
    expect(screen.getByRole("dialog", { name: "Renombrar entrada" })).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Nuevo nombre"));
    await user.type(screen.getByLabelText("Nuevo nombre"), "Rock Clasico");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByText("Entrada renombrada correctamente.")).toBeInTheDocument();
    const patchCall = findFetchCall(fetchMock, "/api/v1/profiles/pepe/entries/rename", "PATCH");
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ path: "Rock", new_name: "Rock Clasico" });
  });

  test("pide confirmación antes de enviar a papelera desde menú contextual", async () => {
    const fetchMock = mockApi();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await user.click(await screen.findByRole("listitem", { name: "Seleccionar tema.mp3" }));
    await user.click(screen.getByRole("button", { name: "Acciones..." }));
    await user.click(screen.getByRole("menuitem", { name: "Enviar a papelera" }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("papelera interna"));
    expect(findFetchCall(fetchMock, "/api/v1/profiles/pepe/entries", "DELETE")).toBeUndefined();
  });

  test("mueve una entrada a subdirectorio con target_directory_path correcto", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await user.click(await screen.findByRole("listitem", { name: "Seleccionar tema.mp3" }));
    await user.click(screen.getByRole("button", { name: "Acciones..." }));
    await user.click(screen.getByRole("menuitem", { name: "Mover" }));
    const dialog = await screen.findByRole("dialog", { name: "Mover entrada" });
    await user.click(within(dialog).getByRole("button", { name: /Rock \/Rock/ }));
    await user.click(screen.getByRole("button", { name: "Mover aquí" }));

    expect(await screen.findByText("Entrada movida correctamente.")).toBeInTheDocument();
    const moveCall = findFetchCall(fetchMock, "/api/v1/profiles/pepe/entries/move", "POST");
    expect(JSON.parse(String(moveCall?.[1]?.body))).toEqual({
      source_path: "tema.mp3",
      target_directory_path: "Rock",
    });
  });

  test("impide mover carpeta dentro de sí misma", async () => {
    const user = userEvent.setup();
    mockApi();
    renderApp(["/library?profile=pepe"]);

    await user.click(await screen.findByRole("listitem", { name: "Seleccionar Rock" }));
    await user.click(screen.getByRole("button", { name: "Acciones..." }));
    await user.click(screen.getByRole("menuitem", { name: "Mover" }));

    expect(within(screen.getByRole("dialog", { name: "Mover entrada" })).getByRole("button", { name: /Rock \/Rock/ })).toBeDisabled();
  });

  test("maneja API no disponible con error claro", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network"));
    renderApp(["/downloads"]);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Se ha producido un error al comunicarse con el servicio.",
    );
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
      <ThemeProvider>
        <SelectionProvider>
          <RouterProvider router={router} />
        </SelectionProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

function mockApi(
  options: {
    createDownloadStatus?: number;
    createDownloadBody?: unknown;
    createDirectoryStatus?: number;
    createDirectoryBody?: unknown;
    renameStatus?: number;
    renameBody?: unknown;
    moveStatus?: number;
    moveBody?: unknown;
  } = {},
) {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/profiles/pepe/entries?path=Rock")) return jsonResponse(rockEntriesResponse);
    if (url.includes("/profiles/pepe/entries?path=")) return jsonResponse(rootEntriesResponse);
    if (url.endsWith("/profiles")) return jsonResponse(profilesResponse);
    if (url.endsWith("/profiles/pepe/directories") && init?.method === "POST") {
      return jsonResponse(
        options.createDirectoryBody ?? { name: "Jazz", path: "Jazz", type: "directory" },
        options.createDirectoryStatus ?? 201,
      );
    }
    if (url.endsWith("/profiles/pepe/entries/rename") && init?.method === "PATCH") {
      return jsonResponse(
        options.renameBody ?? { name: "Rock Clasico", path: "Rock Clasico", type: "directory", size_bytes: null },
        options.renameStatus ?? 200,
      );
    }
    if (url.endsWith("/profiles/pepe/entries") && init?.method === "DELETE") {
      return jsonResponse({ status: "trashed", original_path: "tema.mp3" });
    }
    if (url.endsWith("/profiles/pepe/entries/move") && init?.method === "POST") {
      return jsonResponse(
        options.moveBody ?? { name: "tema.mp3", path: "Rock/tema.mp3", type: "file", size_bytes: 1200 },
        options.moveStatus ?? 200,
      );
    }
    if (url.includes("/downloads") && init?.method === "POST") {
      return jsonResponse(
        options.createDownloadBody ?? { id: "new", profile: profilesResponse.profiles[0] },
        options.createDownloadStatus ?? 201,
      );
    }
    if (url.includes("/downloads")) return jsonResponse(downloadsResponse);
    return jsonResponse({ detail: "Not found" }, 404);
  });
  return fetchMock;
}

function makeJob(id: string, status: string, progress: number | null, outputPath: string | null) {
  return {
    id,
    profile_id: "pepe",
    source_url: `https://www.youtube.com/watch?v=VIDEO_${id}`,
    destination_path: id === "2" ? "Rock/Clasicos" : "Rock",
    requested_filename: id === "2" ? "Sandunga verano" : null,
    audio_policy: "prefer_m4a_then_best_source",
    status,
    progress_percent: progress,
    title: id === "2" ? "Canción final" : null,
    output_path: outputPath,
    created_at: "2026-07-01T12:00:00Z",
    started_at: status === "running" ? "2026-07-01T12:01:00Z" : null,
    finished_at: status === "completed" ? "2026-07-01T12:05:00Z" : null,
  };
}

function makeLongJob() {
  return {
    id: "6",
    profile_id: "pepe",
    source_url: "https://www.youtube.com/watch?v=VIDEO_6",
    destination_path:
      "Rock/Clasicos/Directos/Temporada 2026/Carpeta con un nombre descriptivo y largo",
    requested_filename:
      "Sandunga verano edición extendida para comprobar que no rompe el contenedor",
    audio_policy: "prefer_m4a_then_best_source",
    status: "completed",
    progress_percent: 100,
    title:
      "Título extremadamente largo de una canción descargada desde YouTube para validar wrapping visual",
    output_path:
      "Rock/Clasicos/Directos/Temporada 2026/archivo-final-con-un-nombre-muy-largo-y-suficiente-para-forzar-saltos-controlados.m4a",
    created_at: "2026-07-01T12:00:00Z",
    started_at: "2026-07-01T12:01:00Z",
    finished_at: "2026-07-01T12:05:00Z",
  };
}

function findFetchCall(fetchMock: FetchSpy, urlSuffix: string, method: string) {
  return fetchMock.mock.calls.find(([url, init]) => String(url).endsWith(urlSuffix) && init?.method === method);
}

function countFetchCalls(fetchMock: FetchSpy, urlPart: string) {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes(urlPart)).length;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
