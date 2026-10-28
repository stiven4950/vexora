import type { FaqItem } from "./types";

// PENDIENTE(fase 3): revisión legal y datos de la empresa
export const SUPPORT = {
  title: "Soporte y ayuda",
  intro: "Respuestas rápidas a lo que más nos preguntan. Si no encuentras lo que buscas, escríbenos.",
  effectiveDate: "[FECHA DE VIGENCIA]",
  faq: [
    {
      q: "¿Qué hace Vexora?",
      a: "Subes un video tuyo (o de personas que se mueven o bailan) y Vexora le agrega efectos visuales como fuego, agua o neón que siguen tus movimientos. Tú eliges el estilo.",
    },
    {
      q: "¿Qué tipo de video funciona mejor?",
      a: "Uno donde se vea el cuerpo completo, con buena luz, la cámara quieta y la persona bien separada del fondo. Los videos muy oscuros, borrosos o con mucha gente tapándose entre sí dan peores resultados.",
    },
    {
      q: "¿Cuánto tarda en procesarse mi video?",
      a: "Depende de la duración y de cuánta gente haya en el servicio. Puedes ver el avance en la pantalla de procesamiento y salir; tu proyecto quedará en «Mis proyectos» cuando termine.",
    },
    {
      q: "¿Por qué mi video tiene una marca de agua?",
      a: "Los videos del plan gratuito llevan la marca de Vexora. Los planes de pago, cuando se activen, permitirán quitarla.",
    },
    {
      q: "¿Los planes y créditos ya funcionan?",
      a: "Todavía no. Los precios que ves son solo de referencia; te avisaremos antes de cobrar cualquier cosa.",
    },
    {
      q: "¿Cuánto tiempo se guardan mis videos?",
      a: "Los videos que subes y no usas en un proyecto se borran a las 24 horas. Los proyectos se guardan hasta que tú los elimines.",
    },
    {
      q: "¿Cómo borro un proyecto?",
      a: "Desde «Mis proyectos», elige el proyecto y selecciona eliminar. Se borran sus videos, resultados y análisis.",
    },
    {
      q: "¿Cómo elimino mi cuenta y todos mis datos?",
      a: "Entra a Configuración y usa la opción de eliminar cuenta. Se borran tu cuenta, tus proyectos y sus archivos. Si no puedes entrar, escríbenos desde el correo de tu cuenta.",
    },
    {
      q: "¿Quién ve mis videos?",
      a: "Solo tú, mientras no crees un enlace público. Si lo creas, cualquiera con el enlace puede ver ese video hasta que lo revoques.",
    },
    {
      q: "¿Cómo dejo de compartir un video?",
      a: "Abre el proyecto y revoca el enlace público. Desde ese momento el enlace deja de funcionar.",
    },
    {
      q: "¿Mis videos se envían a otras empresas?",
      a: "Solo si usas funciones opcionales: el «lector de escena» envía unos pocos fotogramas a OpenAI, y el «análisis profundo» (de pago) envía el video completo a Google Gemini. Sin esas funciones, tu video se procesa en nuestros servidores. Más detalles en la Política de privacidad.",
    },
    {
      q: "¿Puedo subir videos de niños o adolescentes?",
      a: "Solo si tienes la autorización de su madre, padre o representante legal. Es una regla de nuestros Términos de uso y de la ley colombiana.",
    },
    {
      q: "Mi video falló o el resultado se ve mal, ¿qué hago?",
      a: "Prueba con otro video más nítido y con el cuerpo completo en cuadro. Si sigue fallando, escríbenos con el nombre del proyecto y cuéntanos qué pasó.",
    },
    {
      q: "No me llega el correo para restablecer mi contraseña.",
      a: "Revisa la carpeta de spam y confirma que escribiste bien tu correo. Si usas «Continuar con Google», no tienes contraseña en Vexora: entra con ese botón.",
    },
    {
      q: "¿Cómo ejerzo mis derechos sobre mis datos personales?",
      a: "Escribe a [CORREO DE PRIVACIDAD]. El procedimiento y los plazos están en la Política de privacidad.",
    },
  ] satisfies FaqItem[],
  contact: {
    title: "Contáctanos",
    lines: [
      "Soporte: [CORREO DE CONTACTO]",
      "Privacidad y datos personales: [CORREO DE PRIVACIDAD]",
      "Teléfono: [TELÉFONO]",
      "Dirección: [RAZÓN SOCIAL], [DIRECCIÓN], [CIUDAD]",
    ],
    note: "Cuéntanos tu caso con el mayor detalle posible. Normalmente respondemos en pocos días hábiles.",
  },
};
