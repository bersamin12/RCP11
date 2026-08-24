import { lazy, Suspense, useEffect, useState } from "react";
import { HashRouter, Navigate, NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";

import { api } from "./api";
import { Button, LoadingBlock } from "./components/UI";
import { ToastProvider } from "./components/Toast";
import { Dashboard } from "./screens/Dashboard";
import { KnowledgeBase } from "./screens/KnowledgeBase";
import { Models } from "./screens/Models";
import { NewRun } from "./screens/NewRun";

const RunDetail = lazy(() => import("./screens/RunDetail").then((module) => ({ default: module.RunDetail })));

type Theme = "light" | "dark";

function preferredTheme(): Theme {
  const saved = localStorage.getItem("rcp-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function RunRoute() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  return <Suspense fallback={<LoadingBlock label="Loading research cockpit…" />}><RunDetail runId={runId} goDashboard={() => navigate("/")} openRun={(id) => navigate(`/runs/${id}`)} /></Suspense>;
}

function NewRunRoute() {
  const navigate = useNavigate();
  return <NewRun goDashboard={() => navigate("/")} openRun={(id) => navigate(`/runs/${id}`)} />;
}

function Shell() {
  const navigate = useNavigate();
  const [apiUp, setApiUp] = useState<boolean | null>(null);
  const [theme, setTheme] = useState<Theme>(preferredTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("rcp-theme", theme);
  }, [theme]);
  useEffect(() => {
    let active = true;
    const check = () => api.health().then(() => active && setApiUp(true)).catch(() => active && setApiUp(false));
    check();
    const timer = window.setInterval(check, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="app-header">
      <NavLink to="/" className="brand" aria-label="RCP home">
        <span className="brand-mark mono">R</span>
        <span className="brand-copy"><strong className="mono">RCP·2026/11</strong><small>Research cockpit</small></span>
      </NavLink>
      <nav className="app-nav" aria-label="Primary navigation">
        <NavLink className="nav-link" to="/">Runs</NavLink>
        <NavLink className="nav-link" to="/knowledge">Knowledge</NavLink>
        <NavLink className="nav-link" to="/models">Models</NavLink>
      </nav>
      <div className="header-actions">
        <span className="api-health" title={apiUp === false ? "API unavailable" : "API connected"}><i className={`health-dot ${apiUp === false ? "down" : ""}`} /><span>{apiUp === false ? "API down" : apiUp === null ? "Checking API" : "API connected"}</span></span>
        <Button className="btn-icon" aria-label={`Use ${theme === "light" ? "dark" : "light"} theme`} title={`Use ${theme === "light" ? "dark" : "light"} theme`} onClick={() => setTheme(theme === "light" ? "dark" : "light")}>{theme === "light" ? "◐" : "◑"}</Button>
        <Button variant="primary" onClick={() => navigate("/runs/new")}><span aria-hidden="true">＋</span><span className="desktop-only">New run</span></Button>
      </div>
    </header>
    <main id="main-content" className="app-main" tabIndex={-1}>
      <Routes>
        <Route path="/" element={<Dashboard openRun={(id) => navigate(`/runs/${id}`)} />} />
        <Route path="/runs/new" element={<NewRunRoute />} />
        <Route path="/runs/:runId" element={<RunRoute />} />
        <Route path="/knowledge" element={<KnowledgeBase />} />
        <Route path="/models" element={<Models />} />
        <Route path="/new" element={<Navigate to="/runs/new" replace />} />
        <Route path="/run/:runId" element={<RunRoute />} />
        <Route path="/kb" element={<Navigate to="/knowledge" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </main>
  </div>;
}

export default function App() {
  return <HashRouter><ToastProvider><Shell /></ToastProvider></HashRouter>;
}
