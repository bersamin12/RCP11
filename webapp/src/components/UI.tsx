import { useEffect, useRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Button({ variant = "default", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "danger" | "ghost" }) {
  return <button {...props} className={`btn ${variant === "default" ? "" : `btn-${variant}`} ${className}`.trim()} />;
}

export function Alert({ children, tone = "info", title }: { children: ReactNode; tone?: "info" | "warning" | "danger"; title?: string }) {
  return <div role={tone === "danger" ? "alert" : "status"} className={`alert alert-${tone}`}>{title && <div style={{ fontWeight: 750, marginBottom: 2 }}>{title}</div>}{children}</div>;
}

export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return <div className="card empty-state" aria-live="polite" aria-busy="true"><div className="skeleton" style={{ width: 180, height: 12, margin: "0 auto 10px" }} /><span>{label}</span></div>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="card empty-state">{children}</div>;
}

export function Dialog({ open, title, children, actions, onClose }: { open: boolean; title: string; children: ReactNode; actions?: ReactNode; onClose: () => void }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { onClose(); return; }
      if (event.key !== "Tab" || !panel.current) return;
      const focusable = Array.from(panel.current.querySelectorAll<HTMLElement>(
        'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      )).filter((item) => !item.hasAttribute("hidden"));
      if (!focusable.length) { event.preventDefault(); panel.current.focus(); return; }
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); previous?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><div ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="dialog-title" className="dialog"><h2 id="dialog-title">{title}</h2>{children}{actions && <div className="dialog-actions">{actions}</div>}</div></div>;
}
