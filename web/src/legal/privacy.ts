import type { LegalDoc } from "./types";

// PENDIENTE(fase 3): revisión legal y datos de la empresa
export const PRIVACY: LegalDoc = {
  title: "Política de privacidad y tratamiento de datos personales",
  intro: "Aquí te contamos qué datos tuyos usamos, para qué, con quién los compartimos y cómo puedes ejercer tus derechos. Esta política se emite en cumplimiento de la Ley 1581 de 2012 y el Decreto 1377 de 2013 (régimen de habeas data de Colombia).",
  effectiveDate: "[FECHA DE VIGENCIA]",
  sections: [
    {
      id: "responsable",
      title: "1. Responsable del tratamiento",
      paragraphs: [
        "El responsable de tus datos personales es [RAZÓN SOCIAL], NIT [NIT], con domicilio en [DIRECCIÓN], [CIUDAD], Colombia.",
        "Para temas de privacidad, escríbenos a [CORREO DE PRIVACIDAD] o llama al [TELÉFONO].",
      ],
    },
    {
      id: "datos",
      title: "2. Qué datos recogemos",
      paragraphs: ["Recogemos solo lo necesario para prestar el servicio:"],
      list: [
        "Datos de la cuenta: correo electrónico, nombre y foto si inicias con Google, y un identificador de usuario. Los gestiona Firebase Authentication, de Google.",
        "Tus videos: contienen imágenes de rostros y cuerpos y, a veces, voz. Pueden revelar rasgos físicos de las personas que aparecen.",
        "Datos derivados del video: puntos de referencia de pose y rostro, segmentación de la silueta y análisis de movimiento, que calculamos para aplicar los efectos.",
        "Tus proyectos y resultados: videos generados, análisis y configuraciones de estilo.",
        "Datos técnicos: registros del servidor y telemetría con un identificador de usuario cifrado (hash), nunca con tu correo, para detectar errores y proteger el servicio.",
        "Datos de pago, cuando los pagos estén activos: los recibe directamente nuestro proveedor, [PROVEEDOR DE PAGOS]; nosotros no guardamos los datos completos de tu tarjeta.",
      ],
    },
    {
      id: "datos-sensibles",
      title: "3. Datos sensibles: rostros y cuerpos",
      paragraphs: [
        "Las imágenes de rostros y cuerpos pueden considerarse datos sensibles (datos biométricos) según el artículo 5 de la Ley 1581. Por eso:",
      ],
      list: [
        "No estás obligado a darnos datos sensibles, pero sin tu video no podemos prestar el servicio.",
        "Los usamos únicamente para generar los efectos que pides, nunca para identificar a una persona, vender perfiles ni publicidad.",
        "Te pedimos tu autorización previa, expresa e informada antes de procesar tu video. Si en el video aparecen otras personas, tú debes contar con su autorización.",
      ],
    },
    {
      id: "finalidades",
      title: "4. Para qué usamos tus datos",
      paragraphs: ["Usamos tus datos para:"],
      list: [
        "Crear y administrar tu cuenta y autenticarte.",
        "Procesar tus videos y generar los efectos visuales que solicitas.",
        "Guardar tus proyectos y permitirte compartirlos mediante enlaces públicos que tú controlas.",
        "Gestionar tu plan, créditos y pagos cuando estén disponibles.",
        "Darte soporte y responder tus solicitudes.",
        "Mantener la seguridad del servicio, detectar abusos y corregir errores.",
        "Cumplir obligaciones legales y atender requerimientos de autoridades.",
      ],
    },
    {
      id: "menores",
      title: "5. Datos de niños, niñas y adolescentes",
      paragraphs: [
        "Según el artículo 7 de la Ley 1581, el tratamiento de datos de menores de edad solo puede hacerse respetando su interés superior y sus derechos, y con la autorización de su madre, padre o representante legal.",
        "En Vexora no está permitido subir videos de menores de edad sin esa autorización. Si aparecen menores en un video de baile, quien lo sube declara que cuenta con el consentimiento de su representante legal. Si sabemos que se subió sin autorización, retiraremos el contenido. Si eres madre, padre o representante y quieres eliminar datos de un menor, escríbenos a [CORREO DE PRIVACIDAD].",
      ],
    },
    {
      id: "terceros",
      title: "6. Con quién compartimos tus datos",
      paragraphs: [
        "No vendemos tus datos. Los compartimos solo con proveedores que nos ayudan a prestar el servicio:",
      ],
      list: [
        "Google (Firebase Authentication, Firestore, Firebase Storage y Google Cloud Run): acceso a la cuenta, almacenamiento y alojamiento del servicio.",
        "OpenAI, solo si usas el «lector de escena»: enviamos unos pocos fotogramas del video (no el video completo) para describir la escena.",
        "Google Gemini, solo si usas el «análisis profundo» (opcional y de pago): enviamos el video completo para analizarlo.",
        "[PROVEEDOR DE PAGOS], cuando los pagos estén activos.",
        "Autoridades, cuando una norma o una orden judicial nos lo exija.",
        "Cualquier persona con tu enlace público, si decides crear uno: podrá ver ese video hasta que lo revoques.",
      ],
    },
    {
      id: "transferencia",
      title: "7. Transferencia y transmisión internacional",
      paragraphs: [
        "Los servidores de Google y OpenAI pueden estar fuera de Colombia, por ejemplo en Estados Unidos. Al aceptar esta política autorizas la transferencia o transmisión de tus datos a esos países, solo para las finalidades descritas. Exigimos a nuestros proveedores medidas de seguridad adecuadas, y mantenemos tus derechos aunque los datos viajen.",
        "Las funciones que usan OpenAI o Gemini son opcionales: si no las activas, esas empresas no reciben tu video ni tus fotogramas.",
      ],
    },
    {
      id: "conservacion",
      title: "8. Cuánto tiempo conservamos tus datos",
      paragraphs: [],
      list: [
        "Videos subidos que no uses en un proyecto: se borran automáticamente a las 24 horas.",
        "Proyectos (videos, análisis y resultados): se conservan hasta que tú los elimines. Al borrar un proyecto eliminamos sus archivos y su análisis.",
        "Cuenta: puedes eliminarla desde Configuración, con todos tus datos.",
        "Registros y telemetría (con identificador cifrado, sin correos): [PLAZO] días.",
        "Algunos datos podrán conservarse más tiempo solo si una ley lo exige, por ejemplo para efectos contables o fiscales.",
      ],
    },
    {
      id: "derechos",
      title: "9. Tus derechos como titular",
      paragraphs: ["Según el artículo 8 de la Ley 1581, tienes derecho a:"],
      list: [
        "Conocer los datos que tenemos sobre ti y cómo los usamos.",
        "Actualizarlos y rectificarlos si están incompletos o son inexactos.",
        "Pedir prueba de la autorización que nos diste.",
        "Ser informado sobre el uso que hemos dado a tus datos.",
        "Revocar tu autorización y solicitar la supresión de tus datos, cuando no haya un deber legal o contractual de conservarlos.",
        "Presentar quejas ante la Superintendencia de Industria y Comercio (SIC) por infracciones a la ley, una vez agotado el trámite ante nosotros.",
        "Acceder gratuitamente a tus datos.",
      ],
    },
    {
      id: "procedimiento",
      title: "10. Cómo ejercer tus derechos",
      paragraphs: [
        "Escribe a [CORREO DE PRIVACIDAD] o a [DIRECCIÓN], indicando tu nombre, el correo de tu cuenta, lo que solicitas y, si es necesario, los documentos que lo soporten. Si actúas en nombre de otra persona o de un menor, indica tu calidad de representante.",
        "Consultas: las responderemos en máximo 10 días hábiles. Si no podemos hacerlo en ese plazo, te avisaremos el motivo y la nueva fecha, que no superará 5 días hábiles adicionales.",
        "Reclamos (actualizar, rectificar, suprimir o revocar): los responderemos en máximo 15 días hábiles. Si la solicitud está incompleta, te pediremos que la complementes en 5 días; si pasan dos meses sin respuesta se entiende que desististe. Si no podemos resolver en 15 días, te avisaremos el motivo y la nueva fecha, que no superará 8 días hábiles adicionales.",
        "Para eliminar tu cuenta y todos tus datos también puedes usar la opción en Configuración.",
      ],
    },
    {
      id: "seguridad",
      title: "11. Seguridad de la información",
      paragraphs: [
        "Aplicamos medidas técnicas y organizativas razonables para proteger tus datos: conexiones cifradas, control de acceso por usuario, autenticación gestionada por Google, identificadores cifrados en los registros, y borrado automático de archivos temporales.",
        "Ningún sistema es totalmente infalible. Si ocurre un incidente que afecte tus datos, lo gestionaremos conforme a la ley y la SIC, y te informaremos cuando corresponda.",
      ],
    },
    {
      id: "cookies",
      title: "12. Almacenamiento en tu navegador",
      paragraphs: [
        "Usamos almacenamiento local de tu navegador para mantener tu sesión y recordar preferencias de la aplicación. No usamos cookies de publicidad.",
      ],
    },
    {
      id: "cambios",
      title: "13. Cambios a esta política",
      paragraphs: [
        "Si cambiamos esta política de forma sustancial, te avisaremos por la aplicación o por correo antes de que entre en vigor, y cuando la ley lo requiera te pediremos de nuevo tu autorización. La versión vigente siempre estará en esta página, con su fecha.",
      ],
    },
    {
      id: "contacto",
      title: "14. Contacto",
      paragraphs: [
        "[RAZÓN SOCIAL] · NIT [NIT] · [DIRECCIÓN], [CIUDAD] · [CORREO DE PRIVACIDAD] · [TELÉFONO].",
      ],
    },
  ],
};
