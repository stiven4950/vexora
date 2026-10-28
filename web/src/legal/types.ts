/** Una sección de un documento legal: el texto va como datos para poder revisarlo y exportarlo. */
export interface LegalSection {
  id: string;
  title: string;
  paragraphs: string[];
  list?: string[];
}

export interface LegalDoc {
  title: string;
  intro: string;
  /** PENDIENTE(fase 3): fecha real de entrada en vigor. */
  effectiveDate: string;
  sections: LegalSection[];
}

export interface FaqItem {
  q: string;
  a: string;
}

/** Aviso que se muestra arriba de cada documento mientras queden datos por completar. */
// PENDIENTE(fase 3): revisión legal y datos de la empresa
export const DRAFT_NOTICE = "Borrador: este texto debe ser revisado por un abogado y completado con los datos de la empresa antes de publicarse.";
