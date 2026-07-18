import { useEffect, useState } from "react";

import { api } from "./api";
import { useNarrow } from "./hooks";
import { Dashboard } from "./screens/Dashboard";
import { KnowledgeBase } from "./screens/KnowledgeBase";
import { Models } from "./screens/Models";
import { NewRun } from "./screens/NewRun";
import { RunDetail } from "./screens/RunDetail";
import { ACCENT } from "./theme";

type Route = { screen: "dashboard" | "newrun" | "kb" | "models" } | { screen: "run"; id: string };

function parseHash(): Route {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash.startsWith("run/")) return { screen: "run", id: hash.slice(4) };
  if (hash === "new") return { screen: "newrun" };
  if (hash === "kb") return { screen: "kb" };
  if (hash === "models") return { screen: "models" };
  return { screen: "dashboard" };
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash());
  const [apiUp, setApiUp] = useState<boolean | null>(null);
  const narrow = useNarrow(760);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const check = () => api.health().then(() => setApiUp(true)).catch(() => setApiUp(false));
    check();
    const t = window.setInterval(check, 10000);
    return () => window.clearInterval(t);
  }, []);

  const go = (hash: string) => {
    window.location.hash = hash;
  };
  const openRun = (id: string) => go(`/run/${id}`);

  const navItems = [
    { label: "Dashboard", key: "dashboard", hash: "/" },
    { label: "Knowledge Base", key: "kb", hash: "/kb" },
    { label: "Models", key: "models", hash: "/models" },
  ];
  const activeKey =
    route.screen === "run" || route.screen === "newrun" ? "dashboard" : route.screen === "kb" ? "kb" : route.screen === "models" ? "models" : "dashboard";

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", fontSize: 13 }}>
      <header
        style={{
          height: 46, flex: "0 0 46px", display: "flex", alignItems: "center",
          gap: narrow ? 8 : 20, padding: narrow ? "0 10px" : "0 18px",
          background: "#ffffff", borderBottom: "1px solid #e4e7ea",
          position: "sticky", top: 0, zIndex: 40,
        }}
      >
        <div onClick={() => go("/")} style={{ display: "flex", alignItems: "center", gap: 9, cursor: "pointer" }}>
          <div className="mono" style={{ width: 22, height: 22, borderRadius: 5, background: ACCENT, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: 12 }}>
            R
          </div>
          {!narrow && (
            <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.1 }}>
              <span className="mono" style={{ fontSize: 12, fontWeight: 600, letterSpacing: 0.2 }}>RCP·2026/11</span>
              <span style={{ fontSize: 9.5, color: "#8a9099", letterSpacing: 0.3, textTransform: "uppercase" }}>Digital Twin Research Loop</span>
            </div>
          )}
        </div>
        <nav style={{ display: "flex", gap: 2, marginLeft: narrow ? 0 : 8, overflowX: "auto", minWidth: 0 }}>
          {navItems.map((n) => {
            const active = activeKey === n.key;
            return (
              <button
                key={n.key}
                onClick={() => go(n.hash)}
                style={{
                  height: 28, padding: narrow ? "0 8px" : "0 12px", border: 0, borderRadius: 6,
                  background: active ? "#ecfeff" : "transparent",
                  color: active ? "#0e7490" : "#4b5563",
                  fontWeight: active ? 600 : 500, fontSize: 12.5, cursor: "pointer",
                  whiteSpace: "nowrap", flex: "0 0 auto",
                }}
              >
                {n.label}
              </button>
            );
          })}
        </nav>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: narrow ? 8 : 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "#6b7280" }}>
            <span
              style={{
                width: 7, height: 7, borderRadius: "50%",
                background: apiUp === false ? "#dc2626" : "#16a34a",
                boxShadow: `0 0 0 3px ${apiUp === false ? "#dc262622" : "#16a34a22"}`,
              }}
            />
            {!narrow && <span className="mono">{apiUp === false ? "api down" : "api :8000"}</span>}
          </div>
          <button
            onClick={() => go("/new")}
            style={{
              height: 28, padding: narrow ? "0 9px" : "0 13px", borderRadius: 6, border: 0, background: ACCENT,
              color: "#fff", fontWeight: 600, fontSize: 12, cursor: "pointer",
              display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap", flex: "0 0 auto",
            }}
          >
            <span style={{ fontSize: 14, lineHeight: 1 }}>+</span> {narrow ? "New" : "New Run"}
          </button>
        </div>
      </header>

      <main style={{ flex: 1, padding: narrow ? "14px 12px 40px" : "18px 22px 40px", maxWidth: 1320, width: "100%", margin: "0 auto" }}>
        {route.screen === "dashboard" && <Dashboard openRun={openRun} />}
        {route.screen === "newrun" && <NewRun goDashboard={() => go("/")} openRun={openRun} />}
        {route.screen === "run" && <RunDetail runId={route.id} goDashboard={() => go("/")} />}
        {route.screen === "kb" && <KnowledgeBase />}
        {route.screen === "models" && <Models />}
      </main>
    </div>
  );
}
