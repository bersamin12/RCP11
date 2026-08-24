import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, errorMessage } from "../api";
import { CredibilityBadge } from "../components/Credibility";
import { PdfReaderPane } from "../components/PdfReaderPane";
import { Alert, Button, EmptyState, LoadingBlock } from "../components/UI";
import type { MemoryDetail, MemoryTopic, PaperCard } from "../types";

type SortKey = "score" | "relevance" | "credibility" | "citations" | "recency";
const SORT_KEYS: SortKey[] = ["score", "relevance", "credibility", "citations", "recency"];
const credibilityOrder: Record<string, number> = { verified: 4, likely: 3, uncertain: 2, preprint: 1 };

export function KnowledgeBase() {
  const [params, setParams] = useSearchParams();
  const [topics, setTopics] = useState<MemoryTopic[]>([]);
  const [detail, setDetail] = useState<MemoryDetail | null>(null);
  const [topicsLoading, setTopicsLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [topicsError, setTopicsError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  const slug = params.get("topic") ?? "";
  const query = params.get("q") ?? "";
  const confidence = params.get("credibility") ?? "all";
  const publication = params.get("publication") ?? "all";
  const requestedSort = params.get("sort") as SortKey | null;
  const sort = requestedSort && SORT_KEYS.includes(requestedSort) ? requestedSort : "score";
  // Reader state lives in the URL like every other view state here, so a passage
  // stays deep-linkable down to the page.
  const openPaperId = params.get("pdf") ?? "";
  const readerPage = Math.max(1, Number(params.get("page") || 1));
  const readerView = params.get("pdfview") === "text" ? "text" : "page";
  const readerDim = params.get("pdfdim") === "1";

  const updateParams = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    setParams(next, { replace: true });
  };

  const loadTopics = async () => {
    setTopicsLoading(true); setTopicsError("");
    try {
      const rows = await api.memoryTopics();
      setTopics(rows);
      const selected = rows.some((topic) => topic.slug === slug) ? slug : rows[0]?.slug ?? "";
      if (selected !== slug) updateParams({ topic: selected || null });
    } catch (err) { setTopicsError(errorMessage(err)); }
    finally { setTopicsLoading(false); }
  };

  useEffect(() => { void loadTopics(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!slug || !topics.some((topic) => topic.slug === slug)) { setDetail(null); return; }
    let active = true;
    setDetailLoading(true); setDetailError(""); setDetail(null);
    api.memoryDetail(slug)
      .then((next) => { if (active) setDetail(next); })
      .catch((err) => { if (active) setDetailError(errorMessage(err)); })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [reloadKey, slug, topics]);

  const all = detail?.paper_cards ?? [];
  const publicationTypes = Array.from(new Set(all.map((paper) => paper.publication_type || "unknown"))).sort();
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rows = all.filter((paper) =>
      (!needle || [paper.title, paper.tags.join(" "), paper.method, paper.problem, paper.venue ?? ""].join(" ").toLowerCase().includes(needle))
      && (confidence === "all" || paper.peer_review_confidence === confidence)
      && (publication === "all" || (paper.publication_type || "unknown") === publication)
    );
    const value = (paper: PaperCard) => {
      if (sort === "relevance") return paper.ranking_factors?.relevance ?? 0;
      if (sort === "credibility") return credibilityOrder[paper.peer_review_confidence] ?? 0;
      if (sort === "citations") return paper.citations;
      if (sort === "recency") return paper.year ?? 0;
      return paper.selection_score ?? 0;
    };
    return [...rows].sort((a, b) => value(b) - value(a) || a.title.localeCompare(b.title));
  }, [all, confidence, publication, query, sort]);
  const themes = Object.entries(detail?.themes ?? {}).map(([tag, titles]) => ({ tag, count: titles.length })).sort((a, b) => b.count - a.count).slice(0, 12);
  const hasFilters = Boolean(query || confidence !== "all" || publication !== "all" || sort !== "score");
  const openPaper = all.find((paper) => paper.id === openPaperId) ?? null;
  const closeReader = () => updateParams({ pdf: null, page: null, pdfview: null, pdfdim: null });

  return <section>
    <div className="page-header"><div><h1>Knowledge base</h1><p>Search ranked literature snapshots with credibility and extraction provenance visible.</p></div></div>
    {topicsError && <Alert tone="danger" title="Knowledge topics unavailable"><p>{topicsError}</p><Button onClick={() => void loadTopics()}>Retry</Button></Alert>}
    {topicsLoading ? <LoadingBlock label="Loading literature snapshots…" /> : !topics.length ? <EmptyState>No knowledge snapshots yet. Start a research run or use <span className="mono">rcp memory-build</span>.</EmptyState> : <div className="knowledge-layout">
      <nav className="knowledge-topics" aria-label="Knowledge topics">{topics.map((topic) => { const active = topic.slug === slug; return <button key={topic.slug} onClick={() => updateParams({ topic: topic.slug })} aria-current={active ? "page" : undefined}><span>{topic.slug.replaceAll("-", " ")}</span><small className="mono">{topic.cards} cards · {topic.snapshot}</small></button>; })}</nav>
      <div className="knowledge-workspace" aria-busy={detailLoading}>
        <div className="knowledge-filters card">
          <label className="knowledge-search"><span className="sr-only">Search papers</span><input className="field" value={query} onChange={(event) => updateParams({ q: event.target.value || null })} placeholder="Search titles, tags, methods…" /></label>
          <label><span className="sr-only">Peer review filter</span><select className="field" aria-label="Peer review filter" value={confidence} onChange={(event) => updateParams({ credibility: event.target.value === "all" ? null : event.target.value })}><option value="all">All credibility</option><option value="verified">Verified</option><option value="likely">Likely reviewed</option><option value="uncertain">Uncertain</option><option value="preprint">Preprints</option></select></label>
          <label><span className="sr-only">Publication type filter</span><select className="field" aria-label="Publication type filter" value={publication} onChange={(event) => updateParams({ publication: event.target.value === "all" ? null : event.target.value })}><option value="all">All publication types</option>{publicationTypes.map((type) => <option key={type}>{type}</option>)}</select></label>
          <label><span className="sr-only">Sort papers</span><select className="field" aria-label="Sort papers" value={sort} onChange={(event) => updateParams({ sort: event.target.value === "score" ? null : event.target.value })}><option value="score">Selection score</option><option value="relevance">Relevance</option><option value="credibility">Credibility</option><option value="citations">Citations</option><option value="recency">Recency</option></select></label>
          {hasFilters && <Button variant="ghost" onClick={() => updateParams({ q: null, credibility: null, publication: null, sort: null })}>Clear filters</Button>}
        </div>
        {detailError && <Alert tone="danger" title="Snapshot unavailable"><p>{detailError}</p><Button onClick={() => setReloadKey((key) => key + 1)}>Retry snapshot</Button></Alert>}
        {detailLoading ? <LoadingBlock label={`Loading ${slug.replaceAll("-", " ")}…`} /> : detail && <>
          <div className="theme-toolbar" aria-label="Themes">{themes.map((theme) => <button key={theme.tag} className="theme-chip mono" aria-pressed={query === theme.tag} onClick={() => updateParams({ q: query === theme.tag ? null : theme.tag })}>{theme.tag} <span>{theme.count}</span></button>)}<span className="mono knowledge-count" aria-live="polite">{filtered.length} of {all.length}</span></div>
          {!filtered.length ? <EmptyState>No papers match these filters. Clear a filter or search term.</EmptyState> : <div className={openPaper ? "reader-layout" : undefined}><div className="knowledge-grid">{filtered.map((paper) => <article className={`card paper-memory-card${paper.id === openPaperId ? " reading" : ""}`} key={paper.id}>
            <div className="paper-memory-meta"><CredibilityBadge status={paper.peer_review_confidence} /><span className="mono publication-badge">{paper.publication_type || "unknown type"}</span><strong className="mono">{(paper.selection_score ?? 0).toFixed(1)}</strong></div>
            <div className="paper-memory-title"><h2>{paper.url ? <a href={paper.url} target="_blank" rel="noreferrer">{paper.title}<span className="sr-only"> (opens in a new tab)</span></a> : paper.title}</h2><span className="mono">{paper.year ?? "—"}</span></div>
            <div className="paper-source">{paper.venue ?? "Unknown venue"} · {paper.citations} citations · extraction from {paper.extraction_basis ?? "unknown source"} · {paper.findings?.length ?? 0} findings</div>
            <p><b>Problem</b>{paper.problem || "Not established from the available source."}</p>
            <p><b className="limitation-label">Limitations</b>{paper.limitations.join("; ") || "Not stated in the available source."}</p>
            {paper.findings?.length ? <details className="paper-rationale"><summary>Extracted findings and conditions</summary><ul>{paper.findings.map((finding) => <li key={finding.id}>{finding.statement} <span className="mono">({finding.direction.replaceAll("_", " ")})</span></li>)}</ul>{paper.study_conditions?.length ? <p>Conditions: {paper.study_conditions.join("; ")}</p> : null}</details> : null}
            <details className="paper-rationale"><summary>Why selected</summary><p>{paper.credibility_explanation}</p>{Object.entries(paper.ranking_factors ?? {}).map(([factor, score]) => <div className="ranking-factor" key={factor}><span>{factor.replaceAll("_", " ")}</span><span className="ranking-track"><i style={{ width: `${Math.min(100, score * 100)}%` }} /></span><span className="mono">{Math.round(score * 100)}</span></div>)}<div className="paper-provenance">Provenance: {(paper.provenance ?? []).join(", ") || "not recorded"}</div></details>
            <div className="tag-row">{paper.tags.map((tag) => <button key={tag} onClick={() => updateParams({ q: tag })}>{tag}</button>)}</div>
            <div className="toolbar paper-actions">{paper.pdf?.status === "available"
              ? <Button onClick={() => paper.id === openPaperId ? closeReader() : updateParams({ pdf: paper.id, page: "1" })}>{paper.id === openPaperId ? "Close full text" : "Read full text"}</Button>
              : <span className="mono paper-no-fulltext">no open-access full text</span>}</div>
          </article>)}</div>
          {openPaper && <PdfReaderPane paper={openPaper} page={readerPage} view={readerView} dim={readerDim} onParams={updateParams} onClose={closeReader} />}
          </div>}
        </>}
      </div>
    </div>}
  </section>;
}
