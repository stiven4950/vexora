import { useMemo, useState } from "react";

import { actionHue, actionLabel, choiceLabel, personLabel, timecode } from "../api/format";
import type { Moment } from "../api/types";
import { Icon } from "./Icon";
import styles from "./ChoreographyPanel.module.css";

/** Filtros visibles de entrada (los efectos más frecuentes); el resto, a un clic. */
const CHIPS = 8;

/** El efecto sin "en la pareja": la copia de la pareja cuenta en el mismo filtro. */
const effectOf = (moment: Moment) => choiceLabel(moment.choice.replace(" (espejo)", ""));

interface Props {
  moments: Moment[];
  /** Segundo que se está viendo: resalta el momento en curso. */
  time: number;
  /** Clic en un momento: el visor salta a ese instante. */
  onSelect: (moment: Moment) => void;
}

/**
 * Los efectos que eligió la coreografía. Plegada por defecto (la lista puede ser larga); al
 * abrirla, un filtro por efecto y la lista en orden de tiempo. Cada fila lleva al momento exacto.
 */
export function ChoreographyPanel({ moments, time, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [only, setOnly] = useState<string | null>(null);
  const [allChips, setAllChips] = useState(false);

  const ordered = useMemo(() => [...moments].sort((a, b) => a.second - b.second), [moments]);
  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const moment of moments) {
      const key = effectOf(moment);
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return [...map.entries()].sort((a, b) => b[1] - a[1]);
  }, [moments]);
  const shown = only ? ordered.filter((m) => effectOf(m) === only) : ordered;
  // El momento en curso: el último que empezó antes del instante actual (con una tolerancia de un cuadro).
  const current = useMemo(() => {
    let last = -1;
    shown.forEach((m, index) => {
      if (m.second <= time + 0.034) last = index;
    });
    return last;
  }, [shown, time]);

  return (
    <section className={styles.panel}>
      <button type="button" className={styles.toggle} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span>
          <span className="eyebrow">La coreografía</span>
          <span className={styles.total}>
            {moments.length} efectos · {counts.length} distintos
          </span>
        </span>
        <span className={`${styles.chevron} ${open ? styles.up : ""}`}>
          <Icon name="chevron" size={18} />
        </span>
      </button>

      {open && (
        <>
          <div className={styles.filters} role="group" aria-label="Filtrar por efecto">
            {(allChips ? counts : counts.slice(0, CHIPS)).map(([label, count]) => (
              <button
                type="button"
                key={label}
                className={`${styles.chip} ${only === label ? styles.chipOn : ""}`}
                onClick={() => setOnly((current) => (current === label ? null : label))}
                aria-pressed={only === label}
              >
                {label} <b>{count}</b>
              </button>
            ))}
            {counts.length > CHIPS && (
              <button type="button" className={styles.more} onClick={() => setAllChips((v) => !v)}>
                {allChips ? "ver menos" : `+${counts.length - CHIPS} más`}
              </button>
            )}
          </div>
          <ol className={styles.list}>
            {shown.map((moment, index) => {
              const person = personLabel(moment.target);
              return (
                <li key={`${moment.second}-${moment.choice}-${moment.target}`}>
                  <button
                    type="button"
                    className={`${styles.row} ${index === current ? styles.current : ""}`}
                    onClick={() => onSelect(moment)}
                    style={{ ["--hue" as string]: actionHue(moment.action) }}
                    title="Ir a este momento"
                  >
                    <span className={`${styles.time} mono`}>{timecode(moment.second)}</span>
                    <span className={styles.what}>
                      <strong>{choiceLabel(moment.choice)}</strong>
                      <span>
                        {actionLabel(moment.action)}
                        {person && ` · ${person}`}
                      </span>
                      {moment.note && <em className={styles.note}>{moment.note}</em>}
                    </span>
                    <Icon name="play" size={12} />
                  </button>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </section>
  );
}
