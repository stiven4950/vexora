import styles from "./Segmented.module.css";

interface Props<T extends string> {
  value: T;
  options: { id: T; label: string; disabled?: boolean; title?: string }[];
  onChange: (value: T) => void;
  label: string;
}

/** Dos o tres opciones en una píldora, una elegida (Original / Con efectos). */
export function Segmented<T extends string>({ value, options, onChange, label }: Props<T>) {
  return (
    <div className={styles.bar} role="group" aria-label={label}>
      {options.map((option) => (
        <button key={option.id} type="button" className={value === option.id ? styles.on : ""} onClick={() => onChange(option.id)} aria-pressed={value === option.id} disabled={option.disabled} title={option.title}>
          {option.label}
        </button>
      ))}
    </div>
  );
}
