/**
 * Spanish UI strings. Every user-visible string lives here so a second locale is a
 * new file with the same shape (enforced by the `Messages` type).
 */
import type { components } from "../lib/api-types";

type ErrorCode = components["schemas"]["ErrorCode"];
export type ErrorText = { title: string; hint: string };

export const es = {
  locale: "es",
  site: {
    name: "downloader.sh",
    title: "downloader.sh — Descarga vídeo y audio desde un enlace",
    description:
      "Pega el enlace de una publicación pública de YouTube, X, Instagram, TikTok y más, elige la calidad y descárgala. Sin registro y sin rastreadores.",
    skip: "Saltar al contenido",
  },
  theme: {
    label: "Tema",
    light: "Claro",
    dark: "Oscuro",
    system: "Sistema",
  },
  hero: {
    title: "Pega el enlace del vídeo que quieres descargar",
    lead: "Analizamos la publicación y te mostramos las calidades disponibles.",
  },
  form: {
    label: "Enlace del vídeo",
    placeholder: "https://…",
    submit: "Analizar",
    submitting: "Analizando…",
    paste: "Pegar",
    supported: "Compatible con",
    empty: "Escribe o pega un enlace.",
  },
  result: {
    by: "de",
    duration: "Duración",
    published: "Publicado",
    quality: "Calidad",
    recommended: "Recomendada",
    best: "Máxima",
    audioOnly: "Solo audio",
    video: "Vídeo",
    approx: "aprox.",
    unknownSize: "tamaño desconocido",
    overLimit: "Supera el límite del servicio",
    advanced: "Opciones avanzadas",
    advancedHint: "Elige un formato concreto. El audio se añade automáticamente si hace falta.",
    columns: {
      pick: "Elegir",
      id: "ID",
      container: "Contenedor",
      resolution: "Resolución",
      fps: "FPS",
      vcodec: "Códec vídeo",
      acodec: "Códec audio",
      bitrate: "Bitrate",
      size: "Tamaño",
    },
    download: "Descargar",
    another: "Analizar otro enlace",
  },
  progress: {
    queued: "En cola…",
    preparing: "Preparando…",
    downloading: "Descargando…",
    processing: "Procesando audio y vídeo…",
    ready: "Listo",
    readyHint: "La descarga debería empezar sola. Si no, usa el botón.",
    save: "Guardar archivo",
    cancel: "Cancelar",
    cancelled: "Descarga cancelada.",
    of: "de",
    left: "restantes",
    expires: "Disponible hasta las",
  },
  errors: {
    retry: "Intentar de nuevo",
    network: {
      title: "No hay conexión con el servicio",
      hint: "Comprueba tu conexión e inténtalo de nuevo.",
    },
    codes: {
      INVALID_URL: {
        title: "El enlace no es válido",
        hint: "Copia el enlace completo de la publicación, empezando por https://.",
      },
      URL_NOT_ALLOWED: {
        title: "Esta dirección no está permitida",
        hint: "Solo se aceptan enlaces públicos de las plataformas compatibles.",
      },
      UNSUPPORTED_SITE: {
        title: "Este sitio no es compatible",
        hint: "Consulta la lista de plataformas compatibles debajo del campo.",
      },
      UNSUPPORTED_CONTENT: {
        title: "Este tipo de enlace no es compatible",
        hint: "Usa el enlace de una publicación concreta, no de un perfil, lista o búsqueda.",
      },
      VALIDATION_ERROR: {
        title: "La petición no es válida",
        hint: "Revisa el enlace e inténtalo de nuevo.",
      },
      CONTENT_NOT_FOUND: {
        title: "No encontramos el contenido",
        hint: "Puede que se haya eliminado o que el enlace esté incompleto.",
      },
      CONTENT_PRIVATE: {
        title: "El contenido es privado",
        hint: "Solo podemos descargar publicaciones públicas.",
      },
      LOGIN_REQUIRED: {
        title: "La plataforma exige iniciar sesión",
        hint: "Este contenido tiene restricciones (por ejemplo, de edad o de suscripción) y no podemos acceder a él.",
      },
      GEO_RESTRICTED: {
        title: "No disponible en nuestra región",
        hint: "La plataforma restringe este contenido geográficamente.",
      },
      DRM_PROTECTED: {
        title: "Contenido protegido con DRM",
        hint: "No descargamos contenido protegido técnicamente.",
      },
      LIVE_NOT_SUPPORTED: {
        title: "Los directos no son compatibles",
        hint: "Vuelve a intentarlo cuando la emisión haya terminado y esté disponible como vídeo.",
      },
      NO_MEDIA_FOUND: {
        title: "No hay vídeo ni audio en esta publicación",
        hint: "Comprueba que el enlace apunta a una publicación con vídeo o audio.",
      },
      FORMAT_UNAVAILABLE: {
        title: "Esa calidad ya no está disponible",
        hint: "Vuelve a analizar el enlace y elige otra calidad.",
      },
      TOO_LARGE: {
        title: "El archivo es demasiado grande",
        hint: "Elige una calidad menor o solo el audio.",
      },
      TOO_LONG: {
        title: "El contenido es demasiado largo",
        hint: "Supera la duración máxima que admite el servicio.",
      },
      PLATFORM_BLOCKED: {
        title: "La plataforma ha rechazado la petición temporalmente",
        hint: "Suele resolverse solo. Inténtalo de nuevo en unos minutos.",
      },
      UPSTREAM_UNAVAILABLE: {
        title: "La plataforma no responde",
        hint: "Inténtalo de nuevo en unos minutos.",
      },
      EXTRACTOR_FAILED: {
        title: "No hemos podido leer esta publicación",
        hint: "La plataforma puede haber cambiado. Inténtalo más tarde.",
      },
      TIMEOUT: {
        title: "La operación ha tardado demasiado",
        hint: "Inténtalo de nuevo o elige una calidad menor.",
      },
      RATE_LIMITED: {
        title: "Demasiadas peticiones",
        hint: "Espera un momento antes de volver a intentarlo.",
      },
      SERVER_BUSY: {
        title: "El servicio está ocupado",
        hint: "Hay muchas descargas en curso. Inténtalo en unos minutos.",
      },
      JOB_NOT_FOUND: {
        title: "No encontramos esta descarga",
        hint: "Vuelve a analizar el enlace.",
      },
      JOB_NOT_READY: {
        title: "La descarga aún no está lista",
        hint: "Espera a que termine el proceso.",
      },
      JOB_EXPIRED: {
        title: "La descarga ha caducado",
        hint: "Los archivos se borran a los pocos minutos. Vuelve a descargarla.",
      },
      NOT_FOUND: { title: "No encontrado", hint: "Vuelve a la página principal." },
      INTERNAL_ERROR: {
        title: "Algo ha fallado por nuestra parte",
        hint: "Inténtalo de nuevo. Si persiste, vuelve más tarde.",
      },
    } satisfies Record<ErrorCode, ErrorText>,
  },
  footer: {
    responsibility:
      "Descarga solo contenido propio, con licencia o que tengas permiso para descargar. Eres responsable de respetar los derechos de autor, las condiciones de cada plataforma y la ley aplicable.",
    terms: "Términos",
    privacy: "Privacidad",
    copyright: "Copyright y retirada",
    acceptableUse: "Uso aceptable",
    nav: "Legal",
  },
} as const;

export type Messages = typeof es;
