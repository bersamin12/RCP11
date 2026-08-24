import type { ReactNode } from "react";

const BADGE: Record<string, { color: string; bg: string; label: string }> = {
  verified: { color: "var(--success)", bg: "var(--success-soft)", label: "peer review verified" },
  likely: { color: "var(--accent)", bg: "var(--accent-soft)", label: "likely reviewed" },
  uncertain: { color: "var(--warning)", bg: "var(--warning-soft)", label: "review uncertain" },
  preprint: { color: "var(--warning)", bg: "var(--warning-soft)", label: "preprint" },
  validated: { color: "var(--success)", bg: "var(--success-soft)", label: "validated" },
  conceptual: { color: "var(--warning)", bg: "var(--warning-soft)", label: "conceptual" },
  unvalidated: { color: "var(--danger)", bg: "var(--danger-soft)", label: "unvalidated" },
};

export function CredibilityBadge({ status }: { status: string }) {
  const style = BADGE[status] ?? { color: "var(--text-muted)", bg: "var(--surface-subtle)", label: status || "unknown" };
  return (
    <span
      className="mono"
      style={{ display: "inline-flex", padding: "2px 7px", borderRadius: 5, fontSize: 9.5, fontWeight: 700, color: style.color, background: style.bg, textTransform: "uppercase", letterSpacing: 0.25, whiteSpace: "nowrap" }}
    >
      {style.label}
    </span>
  );
}

export function WarningBanner({ children, title = "Exploratory evidence" }: { children: ReactNode; title?: string }) {
  return (
    <div role="alert" style={{ background: "var(--warning-soft)", border: "1px solid color-mix(in srgb, var(--warning) 40%, var(--border))", borderLeft: "4px solid var(--warning)", borderRadius: 8, padding: "10px 13px", color: "var(--warning)", fontSize: 11.5, lineHeight: 1.45 }}>
      <div style={{ fontWeight: 700, marginBottom: 2 }}>{title}</div>
      {children}
    </div>
  );
}
