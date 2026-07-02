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

type FetchSpy = ReturnType<typeof mockApi>;

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

  test("renderiza botón Crear carpeta", async () => {
    mockApi();
    renderApp(["/library?profile=pepe"]);

    expect(await screen.findByRole("button", { name: "Crear carpeta" })).toBeInTheDocument();
  });

  test("crea carpeta en raíz con payload correcto y recarga listado", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await user.click(await screen.findByRole("button", { name: "Crear carpeta" }));
    await user.type(screen.getByLabelText("Nombre de la carpeta"), "Jazz");
    await user.click(screen.getByRole("button", { name: "Crear" }));

    expect(await screen.findByText("Carpeta creada correctamente.")).toBeInTheDocument();
    const postCall = findFetchCall(fetchMock, "/api/v1/profiles/pepe/directories", "POST");
    expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({ parent_path: "", name: "Jazz" });
    expect(countFetchCalls(fetchMock, "/api/v1/profiles/pepe/entries?path=")).toBeGreaterThan(1);
  });

  test("crea carpeta dentro de subdirectorio con parent_path correcto", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await user.click(await screen.findByRole("button", { name: /Rock/ }));
    await screen.findByText("/Rock/Clasicos");
    await user.click(screen.getByRole("button", { name: "Crear carpeta" }));
    await user.type(screen.getByLabelText("Nombre de la carpeta"), "Directos");
    await user.click(screen.getByRole("button", { name: "Crear" }));

    const postCall = findFetchCall(fetchMock, "/api/v1/profiles/pepe/directories", "POST");
    expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({ parent_path: "Rock", name: "Directos" });
  });

  test("muestra error seguro al fallar creación", async () => {
    mockApi({ createDirectoryStatus: 409, createDirectoryBody: { detail: "An entry with this name already exists." } });
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await user.click(await screen.findByRole("button", { name: "Crear carpeta" }));
    await user.type(screen.getByLabelText("Nombre de la carpeta"), "Rock");
    await user.click(screen.getByRole("button", { name: "Crear" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Ya existe una entrada con ese nombre.");
  });

  test("renombra una entrada con path y new_name correctos", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await screen.findByText("/Rock");
    await user.click(screen.getAllByRole("button", { name: "Renombrar" })[0]);
    expect(screen.getByRole("form", { name: "Renombrar Rock" })).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Nuevo nombre"));
    await user.type(screen.getByLabelText("Nuevo nombre"), "Rock Clasico");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByText("Entrada renombrada correctamente.")).toBeInTheDocument();
    const patchCall = findFetchCall(fetchMock, "/api/v1/profiles/pepe/entries/rename", "PATCH");
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ path: "Rock", new_name: "Rock Clasico" });
  });

  test("muestra error seguro al fallar renombrado", async () => {
    mockApi({ renameStatus: 422, renameBody: { detail: "Invalid entry name." } });
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await screen.findByText("/Rock");
    await user.click(screen.getAllByRole("button", { name: "Renombrar" })[0]);
    await user.clear(screen.getByLabelText("Nuevo nombre"));
    await user.type(screen.getByLabelText("Nuevo nombre"), "Nombre");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("El nombre de la entrada no es válido.");
  });

  test("pide confirmación antes de enviar a papelera y cancela sin llamar API", async () => {
    const fetchMock = mockApi();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await screen.findByText("/Rock");
    await user.click(screen.getAllByRole("button", { name: "Enviar a papelera" })[0]);

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("papelera interna"));
    expect(findFetchCall(fetchMock, "/api/v1/profiles/pepe/entries", "DELETE")).toBeUndefined();
  });

  test("envía path correcto a papelera al confirmar y recarga listado", async () => {
    const fetchMock = mockApi();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await screen.findByText("/Rock");
    await user.click(screen.getAllByRole("button", { name: "Enviar a papelera" })[1]);

    expect(await screen.findByText("Entrada enviada a la papelera correctamente.")).toBeInTheDocument();
    const deleteCall = findFetchCall(fetchMock, "/api/v1/profiles/pepe/entries", "DELETE");
    expect(JSON.parse(String(deleteCall?.[1]?.body))).toEqual({ path: "tema.mp3" });
    expect(countFetchCalls(fetchMock, "/api/v1/profiles/pepe/entries?path=")).toBeGreaterThan(1);
  });

  test("renderiza acción Mover y abre el diálogo en la raíz", async () => {
    mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await screen.findByText("/Rock");
    expect(screen.getAllByRole("button", { name: "Mover" }).length).toBeGreaterThan(0);
    await user.click(screen.getAllByRole("button", { name: "Mover" })[1]);

    const dialog = await screen.findByRole("dialog", { name: "Mover entrada" });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText("Destino actual:")).toBeInTheDocument();
    expect(within(dialog).getByText("/Rock")).toBeInTheDocument();
    expect(within(dialog).queryByText("tema.mp3")).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/root_path|\/mnt\/music/)).not.toBeInTheDocument();
  });

  test("selecciona raíz como destino y envía cadena vacía", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await user.click(await screen.findByRole("button", { name: /Rock/ }));
    await screen.findByText("/Rock/Clasicos");
    await user.click(screen.getAllByRole("button", { name: "Mover" })[0]);
    await user.click(screen.getByRole("button", { name: "Mover aquí" }));

    expect(await screen.findByText("Entrada movida correctamente.")).toBeInTheDocument();
    const moveCall = findFetchCall(fetchMock, "/api/v1/profiles/pepe/entries/move", "POST");
    expect(JSON.parse(String(moveCall?.[1]?.body))).toEqual({
      source_path: "Rock/Clasicos",
      target_directory_path: "",
    });
    expect(countFetchCalls(fetchMock, "/api/v1/profiles/pepe/entries?path=Rock")).toBeGreaterThan(1);
  });

  test("selecciona un subdirectorio y envía target_directory_path correcto", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await screen.findByText("/Rock");
    await user.click(screen.getAllByRole("button", { name: "Mover" })[1]);
    await user.click(within(screen.getByRole("dialog", { name: "Mover entrada" })).getByRole("button", { name: /Rock/ }));
    await user.click(screen.getByRole("button", { name: "Mover aquí" }));

    const moveCall = findFetchCall(fetchMock, "/api/v1/profiles/pepe/entries/move", "POST");
    expect(JSON.parse(String(moveCall?.[1]?.body))).toEqual({
      source_path: "tema.mp3",
      target_directory_path: "Rock",
    });
  });

  test("cierra el diálogo con Cancelar sin llamar al endpoint de movimiento", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await screen.findByText("/Rock");
    await user.click(screen.getAllByRole("button", { name: "Mover" })[1]);
    await user.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(screen.queryByRole("dialog", { name: "Mover entrada" })).not.toBeInTheDocument();
    expect(findFetchCall(fetchMock, "/api/v1/profiles/pepe/entries/move", "POST")).toBeUndefined();
  });

  test("deshabilita confirmación cuando el destino es la carpeta padre actual", async () => {
    const user = userEvent.setup();
    mockApi();
    renderApp(["/library?profile=pepe"]);

    await screen.findByText("/Rock");
    await user.click(screen.getAllByRole("button", { name: "Mover" })[1]);

    expect(screen.getByText("La entrada ya se encuentra en esta carpeta.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mover aquí" })).toBeDisabled();
  });

  test("impide seleccionar una carpeta dentro de sí misma", async () => {
    const user = userEvent.setup();
    mockApi();
    renderApp(["/library?profile=pepe"]);

    await screen.findByText("/Rock");
    await user.click(screen.getAllByRole("button", { name: "Mover" })[0]);

    expect(within(screen.getByRole("dialog", { name: "Mover entrada" })).getByRole("button", { name: /Rock/ })).toBeDisabled();
  });

  test("muestra error seguro de API al fallar movimiento", async () => {
    mockApi({ moveStatus: 409, moveBody: { detail: "An entry with this name already exists." } });
    const user = userEvent.setup();
    renderApp(["/library?profile=pepe"]);

    await screen.findByText("/Rock");
    await user.click(screen.getAllByRole("button", { name: "Mover" })[1]);
    await user.click(within(screen.getByRole("dialog", { name: "Mover entrada" })).getByRole("button", { name: /Rock/ }));
    await user.click(screen.getByRole("button", { name: "Mover aquí" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Ya existe una entrada con ese nombre.");
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

  test("muestra error de URL en español", async () => {
    mockApi({ createDownloadStatus: 422, createDownloadBody: { detail: "Invalid source URL." } });
    const user = userEvent.setup();
    renderApp(["/downloads"]);

    await user.type(await screen.findByLabelText("URL"), "no-es-url");
    await user.click(screen.getByRole("button", { name: "Crear trabajo" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("La URL de origen no es válida.");
    expect(alert).not.toHaveTextContent("Invalid source URL.");
  });

  test("muestra error de servicio de descargas no disponible en español", async () => {
    mockApi({ createDownloadStatus: 503, createDownloadBody: { detail: "Download service is unavailable." } });
    const user = userEvent.setup();
    renderApp(["/downloads"]);

    await user.type(await screen.findByLabelText("URL"), "https://www.youtube.com/watch?v=abc");
    await user.click(screen.getByRole("button", { name: "Crear trabajo" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "El servicio de descargas no está disponible.",
    );
  });

  test("muestra fallback seguro para errores desconocidos", async () => {
    mockApi({ createDownloadStatus: 500, createDownloadBody: { detail: "Internal SQL detail" } });
    const user = userEvent.setup();
    renderApp(["/downloads"]);

    await user.type(await screen.findByLabelText("URL"), "https://www.youtube.com/watch?v=abc");
    await user.click(screen.getByRole("button", { name: "Crear trabajo" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Se ha producido un error al comunicarse con el servicio.");
    expect(alert).not.toHaveTextContent("Internal SQL detail");
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
      <SelectionProvider>
        <RouterProvider router={router} />
      </SelectionProvider>
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
    if (url.includes("/profiles/pepe/entries?path=Rock")) {
      return jsonResponse(rockEntriesResponse);
    }
    if (url.includes("/profiles/pepe/entries?path=")) {
      return jsonResponse(rootEntriesResponse);
    }
    if (url.endsWith("/profiles")) {
      return jsonResponse(profilesResponse);
    }
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
    if (url.includes("/downloads")) {
      return jsonResponse(downloadsResponse);
    }
    return jsonResponse({ detail: "Not found" }, 404);
  });
  return fetchMock;
}

function findFetchCall(
  fetchMock: FetchSpy,
  urlSuffix: string,
  method: string,
) {
  return fetchMock.mock.calls.find(
    ([url, init]) => String(url).endsWith(urlSuffix) && init?.method === method,
  );
}

function countFetchCalls(
  fetchMock: FetchSpy,
  urlPart: string,
) {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes(urlPart)).length;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
