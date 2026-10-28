import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { CreditPack, Plan as PlanInfo, PlansView } from "../api/types";
import background from "../assets/login/background-900.jpg";
import { Button } from "../components/Button";
import { Icon, type IconName } from "../components/Icon";
import { Shell } from "../components/Shell";
import { CREDITS, SHOW_PENDING, soonNotice } from "../mocks/pendientes";
import { ROUTES } from "../routes";
import styles from "./Plan.module.css";

/** Lo que se va a comprar: un plan (mensual) o un paquete de créditos sueltos. */
type Purchase = { kind: "plan"; plan: PlanInfo } | { kind: "pack"; pack: CreditPack };

const HERO_POINTS: { icon: IconName; text: string }[] = [
  { icon: "sparkles", text: "Efectos de IA de última generación" },
  { icon: "bolt", text: "Procesamiento rápido y seguro" },
  { icon: "shield", text: "Resultados en alta calidad" },
];

const TRUST: { icon: IconName; title: string; text: string }[] = [
  { icon: "card", title: "Pago seguro", text: "Tus datos siempre protegidos" },
  { icon: "refresh", title: "Cancelación flexible", text: "Sin permanencia" },
  { icon: "headset", title: "Soporte 24/7", text: "Estamos para ayudarte" },
  { icon: "devices", title: "Compatible en todos los dispositivos", text: "Web, Windows, Mac y móvil" },
];

const EMPTY_TEXT = "Tu saldo y tu consumo aparecerán aquí cuando se activen los créditos.";

const KIND_LABEL: Record<string, string> = { compra: "Compra", renovación: "Renovación", consumo: "Consumo", bono: "Bono", reembolso: "Reembolso" };

/** Da formato de moneda al precio ("$14.99"); la moneda viene del servidor. */
/** "$14.99", y sin decimales si es entero ("$0", "$99"), como en el diseño. */
const money = (value: number, currency: string): string =>
  new Intl.NumberFormat("en-US", { style: "currency", currency, minimumFractionDigits: Number.isInteger(value) ? 0 : 2 }).format(value);

const renewalDate = (iso: string): string =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("es", { day: "numeric", month: "short", year: "numeric" }).replace(/\./g, "");

/** Mi plan: el catálogo de planes y paquetes (del servidor) junto al saldo, el consumo y el historial (datos fijos por ahora). */
export function Plan() {
  const navigate = useNavigate();
  const [view, setView] = useState<PlansView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [purchase, setPurchase] = useState<Purchase | null>(null);
  const [movements, setMovements] = useState(false);

  useEffect(() => {
    api
      .plans()
      .then(setView)
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, []);

  const currency = view?.currency ?? "USD";
  const firstPack = view?.packs[0];
  const buyCredits = () => firstPack && setPurchase({ kind: "pack", pack: firstPack });

  return (
    <Shell footer={false}>
      <div className={styles.layout}>
        <div className={styles.main}>
          <section className={styles.hero}>
            <img src={background} alt="" className={styles.heroArt} />
            <div className={styles.heroText}>
              <span className="eyebrow">Planes y créditos</span>
              <h1>
                Elige el plan que se adapta <span>a tu creatividad</span>
              </h1>
              <p>Crea videos increíbles con efectos visuales de IA. Elige un plan o compra créditos adicionales cuando los necesites.</p>
            </div>
            <ul className={styles.heroPoints}>
              {HERO_POINTS.map((point) => (
                <li key={point.text}>
                  <Icon name={point.icon} size={18} /> {point.text}
                </li>
              ))}
            </ul>
          </section>

          {error && (
            <p className={styles.error} role="alert">
              <Icon name="alert" size={16} /> No se pudieron cargar los planes: {error}
            </p>
          )}
          {!view && !error && <p className={styles.note}>Cargando planes…</p>}

          {view && (
            <>
              {view.draft && <p className={styles.note}>Precios de referencia: aún no se cobra.</p>}
              <div className={styles.plans}>
                {view.plans.map((plan, index) => (
                  <PlanCard
                    key={plan.id}
                    plan={plan}
                    currency={currency}
                    cta={ctaFor(view, plan, index)}
                    onSelect={() => setPurchase({ kind: "plan", plan })}
                    onContact={() => navigate(ROUTES.support)}
                  />
                ))}
              </div>

              <section className={styles.banner}>
                <span className={styles.bannerIcon}>
                  <Icon name="bolt" size={26} />
                </span>
                <div>
                  <h2>¿Necesitas más créditos?</h2>
                  <p>Puedes comprar créditos extra en cualquier momento, sin cambiar de plan.</p>
                </div>
                <button type="button" className={styles.outline} onClick={buyCredits} disabled={!firstPack}>
                  Comprar créditos <Icon name="arrow" size={16} />
                </button>
              </section>
            </>
          )}

          <ul className={styles.trust}>
            {TRUST.map((item) => (
              <li key={item.title}>
                <span>
                  <Icon name={item.icon} size={20} />
                </span>
                <div>
                  <strong>{item.title}</strong>
                  <small>{item.text}</small>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <aside className={styles.side} aria-label="Créditos">
          <section className={styles.card}>
            <header className={styles.cardHead}>
              <h2>Tus créditos</h2>
              <button type="button" className={styles.link} onClick={() => setMovements(true)}>
                Historial <Icon name="arrow" size={14} />
              </button>
            </header>
            {SHOW_PENDING ? (
              <div className={styles.balance}>
                <span className={styles.hex}>
                  <Icon name="hexagon" size={28} />
                </span>
                <div>
                  <strong>{CREDITS.balance}</strong>
                  <span>créditos disponibles</span>
                  <small>
                    Se renuevan {CREDITS.renewal.credits} el {renewalDate(CREDITS.renewal.date)}
                  </small>
                </div>
              </div>
            ) : (
              <p className={styles.empty}>{EMPTY_TEXT}</p>
            )}
            <Button onClick={buyCredits} disabled={!firstPack} className={styles.full}>
              Comprar créditos
            </Button>
          </section>

          <section className={styles.card}>
            <header className={styles.cardHead}>
              <h2>Paquetes de créditos</h2>
            </header>
            <ul className={styles.packs}>
              {view?.packs.map((pack) => (
                <li key={pack.id}>
                  <button type="button" onClick={() => setPurchase({ kind: "pack", pack })}>
                    <span className={styles.packIcon}>
                      <Icon name="hexagon" size={20} />
                    </span>
                    <span className={styles.packText}>
                      <strong>{pack.credits} créditos</strong>
                      <small>{pack.note}</small>
                    </span>
                    <b>{money(pack.price, currency)}</b>
                    <Icon name="chevron" size={16} />
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className={styles.card}>
            <header className={styles.cardHead}>
              <h2>
                Uso de créditos <small>(últimos 30 días)</small>
              </h2>
            </header>
            {SHOW_PENDING ? <Usage /> : <p className={styles.empty}>{EMPTY_TEXT}</p>}
          </section>

          <section className={styles.card}>
            <header className={styles.cardHead}>
              <h2>Historial de compras</h2>
              <button type="button" className={styles.link} onClick={() => setMovements(true)}>
                Ver todas <Icon name="arrow" size={14} />
              </button>
            </header>
            {SHOW_PENDING ? (
              <ul className={styles.history}>
                {CREDITS.purchases.map((item) => (
                  <li key={item.id}>
                    <span className={styles.packIcon}>
                      <Icon name={item.icon} size={18} />
                    </span>
                    <span className={styles.packText}>
                      <strong>{item.title}</strong>
                      <small>{item.when}</small>
                    </span>
                    <b>{money(item.amount, currency)}</b>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.empty}>{EMPTY_TEXT}</p>
            )}
          </section>
        </aside>
      </div>

      {purchase && <Summary purchase={purchase} currency={currency} onClose={() => setPurchase(null)} />}
      {movements && <Movements currency={currency} onClose={() => setMovements(false)} />}
    </Shell>
  );
}

type Cta = { label: string; mode: "current" | "contact" | "select" };

/** El botón de cada plan: el actual, "Contactar" o comprar; el rango es el orden de la lista. */
function ctaFor(view: PlansView, plan: PlanInfo, index: number): Cta {
  if (plan.id === view.current) return { label: "Plan actual", mode: "current" };
  if (plan.contact) return { label: "Contactar", mode: "contact" };
  const currentIndex = view.plans.findIndex((item) => item.id === view.current);
  return { label: currentIndex > 0 && index > currentIndex ? "Mejorar plan" : "Seleccionar plan", mode: "select" };
}

function PlanCard({ plan, currency, cta, onSelect, onContact }: { plan: PlanInfo; currency: string; cta: Cta; onSelect: () => void; onContact: () => void }) {
  return (
    <article className={`${styles.plan} ${plan.highlighted ? styles.hot : ""}`}>
      {plan.highlighted && <span className={styles.ribbon}>Más popular</span>}
      <span className={styles.planIcon}>
        <Icon name={plan.icon} size={26} />
      </span>
      <h3>
        {plan.title}
        {/* El destacado ya lleva su cinta ("Más popular"): sin etiqueta repetida. */}
        {plan.badge && !plan.highlighted && <em>{plan.badge}</em>}
      </h3>
      <p className={styles.tagline}>{plan.tagline}</p>
      <p className={styles.price}>
        {plan.price_from && <span>Desde </span>}
        {money(plan.price_month, currency)}
        <small> /mes</small>
      </p>
      {cta.mode === "select" ? (
        <button type="button" className={styles.solid} onClick={onSelect}>
          {cta.label}
        </button>
      ) : (
        <button type="button" className={styles.outline} disabled={cta.mode === "current"} onClick={cta.mode === "contact" ? onContact : undefined}>
          {cta.label}
        </button>
      )}
      <ul className={styles.features}>
        {plan.features.map((feature) => (
          <li key={feature}>
            <Icon name="check" size={16} /> {feature}
          </li>
        ))}
      </ul>
      {plan.footnote && (
        <p className={styles.footnote}>
          {plan.footnote_icon && <Icon name={plan.footnote_icon} size={16} />} {plan.footnote}
        </p>
      )}
    </article>
  );
}

/** Dona del consumo: cian los efectos, violeta los renderizados, azul lo demás. */
function Usage() {
  const { usage } = CREDITS;
  const radius = 40;
  const length = 2 * Math.PI * radius;
  const used = usage.effects + usage.renders + usage.other;
  let offset = 0;
  const parts = [
    { label: "Efectos aplicados", value: usage.effects, color: "var(--cyan)" },
    { label: "Renderizados", value: usage.renders, color: "var(--violet)" },
    { label: "Otros", value: usage.other, color: "var(--blue)" },
  ];
  return (
    <div className={styles.usage}>
      <div className={styles.donut}>
        <svg viewBox="0 0 100 100" aria-hidden="true">
          <circle cx="50" cy="50" r={radius} fill="none" stroke="rgba(226,232,240,0.08)" strokeWidth="9" />
          {parts.map((part) => {
            const share = (part.value / usage.total) * length;
            const arc = (
              <circle
                key={part.label}
                cx="50"
                cy="50"
                r={radius}
                fill="none"
                stroke={part.color}
                strokeWidth="9"
                strokeDasharray={`${share} ${length - share}`}
                strokeDashoffset={-offset}
                transform="rotate(-90 50 50)"
              />
            );
            offset += share;
            return arc;
          })}
        </svg>
        <strong>{Math.round((used / usage.total) * 100)}%</strong>
      </div>
      <ul>
        {parts.map((part) => (
          <li key={part.label}>
            <i style={{ background: part.color }} /> {part.label} <b>{part.value}</b>
          </li>
        ))}
        <li className={styles.of}>de {usage.total} créditos</li>
      </ul>
    </div>
  );
}

/** Cierra con Esc y lleva el foco al diálogo al abrirlo. */
function useDialog(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const handler = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);
  return ref;
}

/** Resumen de compra: lo que se paga, sin simular ningún cobro. */
function Summary({ purchase, currency, onClose }: { purchase: Purchase; currency: string; onClose: () => void }) {
  const ref = useDialog(onClose);
  const isPlan = purchase.kind === "plan";
  const total = isPlan ? purchase.plan.price_month : purchase.pack.price;
  const rows: [string, string][] = isPlan
    ? [
        ["Plan", purchase.plan.title],
        ["Precio mensual", money(total, currency)],
        ["Créditos al mes", purchase.plan.monthly_credits !== null ? String(purchase.plan.monthly_credits) : "A medida"],
      ]
    : [
        ["Créditos", String(purchase.pack.credits)],
        ["Precio", money(total, currency)],
      ];
  return (
    <div className={styles.overlay} onMouseDown={onClose}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="resumen-titulo" tabIndex={-1} ref={ref} onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <h2 id="resumen-titulo">Resumen de compra</h2>
          <button type="button" className={styles.close} onClick={onClose} aria-label="Cerrar">
            <Icon name="close" size={18} />
          </button>
        </header>
        <dl>
          {rows.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
          <div className={styles.total}>
            <dt>Total</dt>
            <dd>{money(total, currency)}</dd>
          </div>
        </dl>
        <p className={styles.note}>{isPlan ? "Se cobra cada mes; puedes cancelar cuando quieras." : "Método de pago: se elige al conectar el proveedor de pagos."}</p>
        <footer>
          {/* PENDIENTE(fase 3): proveedor de pagos. Aquí iría el cobro real; hoy solo avisa y no simula un éxito. */}
          <Button onClick={() => soonNotice("El pago")}>Pagar {money(total, currency)}</Button>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
        </footer>
      </div>
    </div>
  );
}

/** Panel lateral con todos los movimientos de créditos. */
function Movements({ currency, onClose }: { currency: string; onClose: () => void }) {
  const ref = useDialog(onClose);
  return (
    <div className={styles.overlay} onMouseDown={onClose}>
      <div className={`${styles.dialog} ${styles.drawer}`} role="dialog" aria-modal="true" aria-labelledby="movimientos-titulo" tabIndex={-1} ref={ref} onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <h2 id="movimientos-titulo">Movimientos de créditos</h2>
          <button type="button" className={styles.close} onClick={onClose} aria-label="Cerrar">
            <Icon name="close" size={18} />
          </button>
        </header>
        {SHOW_PENDING ? (
          <div className={styles.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Tipo</th>
                  <th>Proyecto</th>
                  <th>Créditos</th>
                  <th>Estado</th>
                  <th>Valor</th>
                </tr>
              </thead>
              <tbody>
                {CREDITS.movements.map((item) => (
                  <tr key={item.id}>
                    <td>{item.date}</td>
                    <td>{KIND_LABEL[item.kind]}</td>
                    <td>{item.project ?? "—"}</td>
                    <td className={item.credits > 0 ? styles.plus : styles.minus}>
                      {item.credits > 0 ? "+" : "−"}
                      {Math.abs(item.credits)}
                    </td>
                    <td>{item.status}</td>
                    <td>{item.value !== null ? money(item.value, currency) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className={styles.empty}>{EMPTY_TEXT}</p>
        )}
      </div>
    </div>
  );
}
