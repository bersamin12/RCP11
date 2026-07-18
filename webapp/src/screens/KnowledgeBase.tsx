import { useEffect, useState } from "react";

import { api } from "../api";
import { PendingMessage } from "../components/Badges";
import { useNarrow } from "../hooks";
import type { MemoryDetail, MemoryTopic } from "../types";

export function KnowledgeBase() {
  const narrow = useNarrow();
  const [topics, setTopics] = useState<MemoryTopic[]>([]);
  const [slug, setSlug] = useState<string | null>(null);
  const [detail, setDetail] = useState<MemoryDetail | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.memoryTopics().then((t) => {
      setTopics(t);
      if (t.length && !slug) setSlug(t[0].slug);
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (slug) api.memoryDetail(slug).then(setDetail).catch(() => setDetail(null));
  }, [slug]);

  const q = query.toLowerCase();
  const all = detail?.paper_cards ?? [];
  const filtered = all.filter(
    (p) =>
      !q ||
      p.title.toLowerCase().includes(q) ||
      p.tags.join(" ").toLowerCase().includes(q) ||
      p.method.toLowerCase().includes(q) ||
      p.problem.toLowerCase().includes(q)
  );
  const themes = Object.entries(detail?.themes ?? {})
    .map(([tag, titles]) => ({ tag, count: titles.length }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 12);

  return (
    <section>
      <h1 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 14px" }}>Knowledge base</h1>
      {topics.length === 0 ? (
        <PendingMessage>No knowledge snapshots yet — run <span className="mono">research_memory_build</span> via a run or <span className="mono">rcp memory-build</span>.</PendingMessage>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: narrow ? "1fr" : "230px 1fr", gap: 16 }}>
          <div style={{ display: "flex", flexDirection: narrow ? "row" : "column", flexWrap: "wrap", gap: 8 }}>
            {topics.map((t) => {
              const active = t.slug === slug;
              return (
                <div
                  key={t.slug}
                  onClick={() => setSlug(t.slug)}
                  style={{
                    background: active ? "#ecfeff" : "#fff",
                    border: `1px solid ${active ? "#a5eef7" : "#e4e7ea"}`,
                    borderRadius: 9, padding: "11px 13px", cursor: "pointer",
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: 12.5, lineHeight: 1.3, marginBottom: 4 }}>
                    {t.slug.replace(/-/g, " ")}
                  </div>
                  <div className="mono" style={{ fontSize: 10.5, color: "#8a9099" }}>
                    {t.cards} cards · {t.snapshot}
                  </div>
                </div>
              );
            })}
          </div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search titles, tags, methods…"
                style={{ flex: 1, height: 34, border: "1px solid #d7dbdf", borderRadius: 7, padding: "0 12px", fontSize: 12.5, outline: "none" }}
              />
              <span className="mono" style={{ fontSize: 11, color: "#8a9099" }}>{filtered.length} of {all.length}</span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
              {themes.map((th) => (
                <span
                  key={th.tag}
                  className="mono"
                  onClick={() => setQuery(th.tag)}
                  style={{ fontSize: 11, background: "#f1f3f4", color: "#4b5563", padding: "4px 9px", borderRadius: 14, border: "1px solid #eceff1", cursor: "pointer" }}
                >
                  {th.tag}
                  <span style={{ opacity: 0.6 }}> {th.count}</span>
                </span>
              ))}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))", gap: 11 }}>
              {filtered.map((p) => (
                <div key={p.id} style={{ background: "#fff", border: "1px solid #e4e7ea", borderRadius: 9, padding: "13px 15px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginBottom: 5 }}>
                    <div style={{ fontWeight: 600, fontSize: 12.5, lineHeight: 1.35 }}>
                      {p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.title}</a> : p.title}
                    </div>
                    <span className="mono" style={{ fontSize: 11, color: "#8a9099", whiteSpace: "nowrap" }}>{p.year ?? "—"}</span>
                  </div>
                  <div style={{ fontSize: 11, color: "#8a9099", marginBottom: 8 }}>{p.venue ?? "—"} · {p.citations} cites</div>
                  <div style={{ fontSize: 11.5, color: "#4b5563", lineHeight: 1.45 }}>
                    <span style={{ color: "#0e7490", fontWeight: 600 }}>problem </span>{p.problem}
                  </div>
                  <div style={{ fontSize: 11.5, color: "#4b5563", lineHeight: 1.45, marginTop: 3 }}>
                    <span style={{ color: "#b45309", fontWeight: 600 }}>limits </span>{p.limitations.join("; ") || "—"}
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 9 }}>
                    {p.tags.map((t) => (
                      <span key={t} className="mono" style={{ fontSize: 10, background: "#ecfeff", color: "#0e7490", padding: "2px 6px", borderRadius: 4 }}>{t}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
