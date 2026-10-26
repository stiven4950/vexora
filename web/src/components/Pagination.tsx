import { Icon } from "./Icon";
import styles from "./Pagination.module.css";

interface Props {
  page: number;
  pages: number;
  size: number;
  sizes?: number[];
  onPage: (page: number) => void;
  onSize: (size: number) => void;
}

/** Paginación del diseño: anterior, números, siguiente y "12 / página". */
export function Pagination({ page, pages, size, sizes = [12, 24, 48], onPage, onSize }: Props) {
  return (
    <div className={styles.bar}>
      <button type="button" onClick={() => onPage(page - 1)} disabled={page <= 1} aria-label="Página anterior">
        <Icon name="back" size={16} />
      </button>
      {Array.from({ length: pages }, (_, index) => index + 1).map((number) => (
        <button key={number} type="button" className={number === page ? styles.on : ""} onClick={() => onPage(number)} aria-current={number === page ? "page" : undefined}>
          {number}
        </button>
      ))}
      <button type="button" onClick={() => onPage(page + 1)} disabled={page >= pages} aria-label="Página siguiente">
        <Icon name="arrow" size={16} />
      </button>
      <select value={size} onChange={(event) => onSize(Number(event.target.value))} aria-label="Proyectos por página">
        {sizes.map((value) => (
          <option key={value} value={value}>
            {value} / página
          </option>
        ))}
      </select>
    </div>
  );
}
