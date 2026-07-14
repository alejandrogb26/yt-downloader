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
  ["Invalid requested filename.", "El nombre del archivo no es válido."],
  [
    "No incluyas la extensión del archivo; el sistema la determina automáticamente.",
    "No incluyas la extensión del archivo; el sistema la determina automáticamente.",
  ],
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
  [
    "La solicitud enviada a la API no es válida. Revisa los datos del formulario.",
    "La solicitud enviada a la API no es válida. Revisa los datos del formulario.",
  ],
  ["Los tiempos de recorte no son válidos.", "Los tiempos de recorte no son válidos."],
  [
    "El nombre del nuevo archivo no es válido.",
    "El nombre del nuevo archivo no es válido.",
  ],
  [
    "El archivo de audio no es válido o no está soportado.",
    "El archivo de audio no es válido o no está soportado.",
  ],
  [
    "No se pudo editar el audio porque ffmpeg no está disponible en el servidor.",
    "No se pudo editar el audio porque ffmpeg no está disponible en el servidor.",
  ],
  ["No se pudo completar la operación de audio.", "No se pudo completar la operación de audio."],
]);

export function getUserErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === null) return FALLBACK_ERROR_MESSAGE;
    return ERROR_TRANSLATIONS.get(error.message) ?? error.message;
  }
  return FALLBACK_ERROR_MESSAGE;
}
