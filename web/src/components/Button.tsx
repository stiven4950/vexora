import type { ButtonHTMLAttributes, ReactNode } from "react";

import { Icon, type IconName } from "./Icon";
import styles from "./Button.module.css";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "ghost" | "danger";
  icon?: IconName;
  children: ReactNode;
}

export function Button({ variant = "primary", icon, children, className, ...rest }: Props) {
  return (
    <button className={`${styles.button} ${styles[variant]} ${className ?? ""}`} {...rest}>
      {icon && <Icon name={icon} />}
      <span>{children}</span>
    </button>
  );
}
