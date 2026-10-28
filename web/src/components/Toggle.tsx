import styles from "./Toggle.module.css";

interface Props {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** Lo que lee un lector de pantalla (el texto visible va aparte). */
  label: string;
  disabled?: boolean;
}

/** Interruptor de encendido y apagado (Configuración: avisos). */
export function Toggle({ checked, onChange, label, disabled }: Props) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} className={`${styles.toggle} ${checked ? styles.on : ""}`} onClick={() => onChange(!checked)}>
      <i />
    </button>
  );
}
