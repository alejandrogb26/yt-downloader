import type { ReactNode } from "react";

type StatusMessageProps = {
  tone: "error" | "success" | "info";
  children: ReactNode;
};

export function StatusMessage({ tone, children }: StatusMessageProps) {
  const role = tone === "error" ? "alert" : "status";
  return (
    <p className={`status-message status-message--${tone}`} role={role}>
      {children}
    </p>
  );
}
