import type { CSSProperties } from "react";

import { statusOf } from "../theme";

export function StatusBadge({ status }: { status: string }) {
  const s = statusOf(status);
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 600,
        color: s.c, background: s.bg, padding: "2px 8px", borderRadius: 11,
      }}
    >
      <span
        style={{
          width: 6, height: 6, borderRadius: "50%", background: s.dot,
          animation: s.anim ? "pulse 1.2s infinite" : "none",
        }}
      />
      {s.label}
    </span>
  );
}

const CONF: Record<string, { c: string; bg: string }> = {
  high: { c: "#15803d", bg: "#dcfce7" },
  medium: { c: "#b45309", bg: "#fef3c7" },
  low: { c: "#6b7280", bg: "#f1f3f4" },
};

export function ConfidenceBadge({ level }: { level: string }) {
  const m = CONF[level] ?? CONF.low;
  const style: CSSProperties = {
    fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4,
    color: m.c, background: m.bg, padding: "3px 8px", borderRadius: 6,
    whiteSpace: "nowrap", marginTop: 1,
  };
  return <span style={style}>{level}</span>;
}

export function PendingMessage({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        background: "#fff", border: "1px dashed #dfe3e6", borderRadius: 9,
        padding: 26, textAlign: "center", color: "#9aa1a9", fontSize: 12.5,
      }}
    >
      {children}
    </div>
  );
}
