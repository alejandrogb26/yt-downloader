export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const FALLBACK_ERROR_MESSAGE = "Se ha producido un error al comunicarse con el servicio.";

const ERROR_TRANSLATIONS = new Map<string, string>([
  ["Invalid source URL.", "La URL de origen no es válida."],
  ["Download service is unavailable.", "El servicio de descargas no está disponible."],
  ["Profile not found.", "No se ha encontrado el perfil."],
  ["Profiles configuration is unavailable.", "La configuración de perfiles no está disponible."],
  ["Profile storage is unavailable.", "El almacenamiento del perfil no está disponible."],
  ["Invalid directory path.", "La ruta de carpeta no es válida."],
  ["Directory not found.", "No se ha encontrado la carpeta."],
  ["Requested path is not a directory.", "La ruta indicada no es una carpeta."],
  ["Invalid directory name.", "El nombre de carpeta no es válido."],
  ["Invalid entry path.", "La ruta de la entrada no es válida."],
  ["Invalid entry name.", "El nombre de la entrada no es válido."],
  ["Entry not found.", "No se ha encontrado la entrada."],
  ["Requested entry is not allowed.", "La entrada solicitada no está permitida."],
  ["Requested directory is not allowed.", "La carpeta solicitada no está permitida."],
  ["An entry with this name already exists.", "Ya existe una entrada con ese nombre."],
  ["Cannot move a directory into itself.", "No se puede mover una carpeta dentro de sí misma."],
  ["Download job not found.", "No se ha encontrado el trabajo de descarga."],
]);

export function getUserErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return ERROR_TRANSLATIONS.get(error.message) ?? FALLBACK_ERROR_MESSAGE;
  }
  return FALLBACK_ERROR_MESSAGE;
}
