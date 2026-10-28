import type { LegalDoc } from "./types";

// PENDIENTE(fase 3): revisión legal y datos de la empresa
export const TERMS: LegalDoc = {
  title: "Términos de uso",
  intro: "Estas reglas explican cómo puedes usar Vexora y qué esperamos de ti y de nosotros. Léelas con calma: al crear tu cuenta o usar el servicio, las aceptas.",
  effectiveDate: "[FECHA DE VIGENCIA]",
  sections: [
    {
      id: "quienes-somos",
      title: "1. Quiénes somos y qué es Vexora",
      paragraphs: [
        "Vexora es un servicio web de [RAZÓN SOCIAL], NIT [NIT], con domicilio en [DIRECCIÓN], [CIUDAD], Colombia (en adelante, «Vexora», «nosotros»).",
        "Vexora te permite subir un video tuyo, o de personas que se mueven o bailan, y agregarle efectos visuales como fuego, agua o neón. Tú eliges el estilo y nosotros procesamos el video para entregarte el resultado.",
      ],
    },
    {
      id: "aceptacion",
      title: "2. Aceptación y cambios",
      paragraphs: [
        "Al registrarte, entrar con tu cuenta o usar Vexora, declaras que leíste estos términos y la Política de privacidad, y que los aceptas.",
        "Podemos actualizar estos términos. Si el cambio es importante, te avisaremos por la aplicación o por correo antes de que entre en vigor. Si sigues usando Vexora después de esa fecha, entendemos que aceptas la nueva versión. Si no estás de acuerdo, puedes dejar de usar el servicio y eliminar tu cuenta.",
      ],
    },
    {
      id: "cuenta",
      title: "3. Tu cuenta",
      paragraphs: [
        "Para usar Vexora necesitas una cuenta. El acceso se gestiona con Firebase Authentication, un servicio de Google.",
        "Debes ser mayor de 18 años para crear una cuenta. Una persona menor de edad solo puede usar Vexora con la autorización y la supervisión de su madre, padre o representante legal, quien es responsable de esa cuenta.",
        "Eres responsable de mantener segura tu contraseña y de lo que ocurra desde tu cuenta. Si crees que alguien entró sin permiso, avísanos de inmediato.",
      ],
    },
    {
      id: "contenido",
      title: "4. Tu contenido y tus derechos",
      paragraphs: [
        "Tus videos y los resultados que generes siguen siendo tuyos. No te quitamos la propiedad de nada.",
        "Nos das una licencia limitada, no exclusiva y solo para operar el servicio: guardar, procesar y mostrar tu contenido para ti (y para quien tú decidas con un enlace público) y generar el resultado que pediste. No usamos tu contenido para publicidad ni lo vendemos.",
        "Declaras y garantizas que:",
      ],
      list: [
        "Eres dueño del video o tienes los derechos y permisos para usarlo y modificarlo, incluida la música y las imágenes que aparezcan.",
        "Cada persona que se ve o se escucha en el video te dio su consentimiento para subirlo y procesarlo con Vexora.",
        "Si aparece una persona menor de edad, subes el video tú, o con la autorización expresa de su madre, padre o representante legal.",
      ],
    },
    {
      id: "uso-aceptable",
      title: "5. Uso aceptable",
      paragraphs: ["No puedes usar Vexora para subir, generar o compartir contenido que:"],
      list: [
        "Sea ilegal o promueva actividades ilegales.",
        "Tenga contenido sexual que involucre a menores de edad. Esto es absolutamente prohibido y lo reportaremos a las autoridades.",
        "Muestre a una persona sin su consentimiento, o la humille, acose o amenace.",
        "Suplante la identidad de otra persona o engañe sobre quién aparece en el video.",
        "Infrinja derechos de autor, marcas u otros derechos de terceros.",
        "Incluya violencia gráfica, odio o discriminación contra personas o grupos.",
        "Intente dañar el servicio: acceder sin permiso, saturar los sistemas, copiar de forma automática o saltarse los límites del plan.",
      ],
    },
    {
      id: "enlaces-publicos",
      title: "6. Enlaces públicos para compartir",
      paragraphs: [
        "Puedes crear un enlace público a un video terminado. Cualquier persona que tenga ese enlace podrá verlo hasta que tú lo revoques. Piensa bien con quién lo compartes: no podemos controlar lo que otros hagan con un video que ya vieron o descargaron.",
        "Puedes revocar el enlace cuando quieras desde la aplicación. Al revocarlo, deja de funcionar. Si eliminas el proyecto, el enlace también deja de funcionar.",
      ],
    },
    {
      id: "marca-de-agua",
      title: "7. Plan gratuito y marca de agua",
      paragraphs: [
        "Los videos generados con el plan gratuito llevan una marca de agua de Vexora. No puedes quitarla ni ocultarla por tus propios medios.",
      ],
    },
    {
      id: "planes-y-pagos",
      title: "8. Planes, créditos y pagos",
      paragraphs: [
        "Hoy los planes, los créditos y los pagos aún no están activos; los precios que ves en la aplicación son solo de referencia.",
        "Cuando se activen, los pagos los procesará un proveedor externo, [PROVEEDOR DE PAGOS]. Antes de cobrarte te mostraremos el precio final, qué incluye y cómo cancelar. No guardamos los datos completos de tu tarjeta.",
        "Si compras a distancia en Colombia, tendrás los derechos de retracto y reversión de pago que la ley de protección al consumidor (Ley 1480 de 2011) te reconoce, en los casos que aplique.",
      ],
    },
    {
      id: "servicios-de-terceros",
      title: "9. Servicios de terceros",
      paragraphs: [
        "Para funcionar usamos servicios de otras empresas: Google (autenticación, almacenamiento y alojamiento) y, en dos funciones opcionales, OpenAI y Google Gemini. En la Política de privacidad explicamos qué datos reciben cada uno y cuándo.",
        "Esas funciones opcionales solo se activan cuando tú las eliges.",
      ],
    },
    {
      id: "conservacion",
      title: "10. Cuánto tiempo guardamos tu contenido",
      paragraphs: [
        "Los videos que subes y no usas en un proyecto se borran automáticamente a las 24 horas.",
        "Los proyectos (videos, análisis y resultados) se guardan hasta que tú los elimines. Al eliminar un proyecto borramos sus archivos y su análisis. También puedes eliminar tu cuenta con todos tus datos desde Configuración.",
      ],
    },
    {
      id: "propiedad-intelectual",
      title: "11. Propiedad intelectual de Vexora",
      paragraphs: [
        "La marca Vexora, el logotipo, el diseño de la aplicación, los efectos y el software son de [RAZÓN SOCIAL] o de quienes nos los licencian. Estos términos no te transfieren ningún derecho sobre ellos, salvo el de usar el servicio como está previsto.",
      ],
    },
    {
      id: "retiro-de-contenido",
      title: "12. Retiro de contenido y suspensión",
      paragraphs: [
        "Podemos retirar contenido o suspender una cuenta si incumples estos términos, si lo exige una autoridad o si hay un riesgo para otras personas. Cuando sea posible te avisaremos y te explicaremos el motivo.",
        "Si crees que un contenido infringe tus derechos, escríbenos a [CORREO DE CONTACTO] con el enlace y una explicación, y lo revisaremos.",
      ],
    },
    {
      id: "responsabilidad",
      title: "13. Garantías y límites de responsabilidad",
      paragraphs: [
        "Hacemos lo posible para que Vexora funcione bien, pero no podemos garantizar que esté siempre disponible ni libre de errores. Los efectos se generan con inteligencia artificial y el resultado puede no ser exactamente el que esperabas.",
        "En la medida que la ley lo permita, Vexora no responde por daños indirectos ni por pérdidas derivadas del uso del servicio, ni por el contenido que los usuarios suban. Nada de lo anterior limita derechos que la ley colombiana no permite limitar, como los de los consumidores.",
      ],
    },
    {
      id: "ley-aplicable",
      title: "14. Ley aplicable y contacto",
      paragraphs: [
        "Estos términos se rigen por las leyes de Colombia. Cualquier diferencia se tratará primero de buena fe escribiéndonos; si no se resuelve, corresponderá a los jueces competentes de [CIUDAD], sin perjuicio de las competencias de la Superintendencia de Industria y Comercio.",
        "Para cualquier duda sobre estos términos, escríbenos a [CORREO DE CONTACTO].",
      ],
    },
  ],
};
