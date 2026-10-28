import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { SiteFooter } from "../components/SiteFooter";
import { PRIVACY } from "../legal/privacy";
import { SUPPORT } from "../legal/support";
import { TERMS } from "../legal/terms";
import { DRAFT_NOTICE, type LegalDoc } from "../legal/types";
import { ROUTES } from "../routes";
import styles from "./Legal.module.css";

interface TocItem {
  id: string;
  title: string;
}

interface FrameProps {
  title: string;
  intro: string;
  effectiveDate: string;
  toc: TocItem[];
  showNotice: boolean;
  children: ReactNode;
}

/** Tarjeta de cierre: lleva a soporte (o al correo, en la propia página de soporte). */
function HelpCard({ onSupport }: { onSupport: boolean }) {
  return (
    <aside className={styles.help}>
      <h2>¿Dudas? Escríbenos</h2>
      <p>Si algo no te quedó claro, con gusto te ayudamos.</p>
      {onSupport ? (
        <p>[CORREO DE CONTACTO]</p>
      ) : (
        <Link to={ROUTES.support} className={styles.link}>
          Ir a soporte y ayuda <Icon name="arrow" size={16} />
        </Link>
      )}
    </aside>
  );
}

/** Plantilla común: encabezado, índice fijo, contenido y pie. */
function Frame({ title, intro, effectiveDate, toc, showNotice, children }: FrameProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className={styles.page}>
      <div className="aurora" />
      <header className={styles.top}>
        <Link to={ROUTES.home} aria-label="Ir al inicio">
          <Logo size={30} />
        </Link>
        <nav className={styles.crumbs} aria-label="Documentos">
          <Link to={ROUTES.terms}>Términos</Link>
          <Link to={ROUTES.privacy}>Privacidad</Link>
          <Link to={ROUTES.support}>Soporte</Link>
        </nav>
      </header>
      <div className={styles.layout}>
        <nav className={styles.toc} aria-label="Contenido del documento">
          <button type="button" className={styles.tocToggle} onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls="toc-list">
            Contenido <Icon name="chevron" size={16} />
          </button>
          <ul id="toc-list" className={open ? styles.tocOpen : ""}>
            {toc.map((item) => (
              <li key={item.id}>
                <a href={`#${item.id}`} onClick={() => setOpen(false)}>
                  {item.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <main className={styles.doc}>
          <h1>{title}</h1>
          <p className={styles.meta}>Vigente desde: {effectiveDate}</p>
          {/* PENDIENTE(fase 3): revisión legal y datos de la empresa */}
          {showNotice && (
            <p className={styles.notice} role="note">
              {DRAFT_NOTICE}
            </p>
          )}
          <p className={styles.intro}>{intro}</p>
          {children}
        </main>
      </div>
      <SiteFooter />
    </div>
  );
}

function DocPage({ doc }: { doc: LegalDoc }) {
  return (
    <Frame title={doc.title} intro={doc.intro} effectiveDate={doc.effectiveDate} toc={doc.sections} showNotice>
      {doc.sections.map((section) => (
        <section key={section.id} id={section.id} className={styles.section}>
          <h2>{section.title}</h2>
          {section.paragraphs.map((text) => (
            <p key={text}>{text}</p>
          ))}
          {section.list && (
            <ul>
              {section.list.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </section>
      ))}
      <HelpCard onSupport={false} />
    </Frame>
  );
}

export function Terms() {
  return <DocPage doc={TERMS} />;
}

export function Privacy() {
  return <DocPage doc={PRIVACY} />;
}

export function Support() {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  return (
    <Frame
      title={SUPPORT.title}
      intro={SUPPORT.intro}
      effectiveDate={SUPPORT.effectiveDate}
      toc={[
        { id: "faq", title: "Preguntas frecuentes" },
        { id: "contacto", title: SUPPORT.contact.title },
      ]}
      showNotice
    >
      <section id="faq" className={styles.section}>
        <h2>Preguntas frecuentes</h2>
        <div className={styles.faq}>
          {SUPPORT.faq.map((item, index) => {
            const open = openIndex === index;
            return (
              <div key={item.q} className={styles.faqItem}>
                <h3>
                  <button type="button" onClick={() => setOpenIndex(open ? null : index)} aria-expanded={open} aria-controls={`faq-${index}`}>
                    <span>{item.q}</span>
                    <Icon name="chevron" size={16} />
                  </button>
                </h3>
                <div id={`faq-${index}`} role="region" hidden={!open} className={styles.answer}>
                  <p>{item.a}</p>
                </div>
              </div>
            );
          })}
        </div>
      </section>
      <section id="contacto" className={styles.section}>
        <h2>{SUPPORT.contact.title}</h2>
        <div className={styles.contact}>
          {SUPPORT.contact.lines.map((line) => (
            <p key={line}>{line}</p>
          ))}
          <p className={styles.note}>{SUPPORT.contact.note}</p>
        </div>
      </section>
      <HelpCard onSupport />
    </Frame>
  );
}
