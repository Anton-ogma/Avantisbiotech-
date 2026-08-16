import { useEffect, useState } from "react";
import { api, type Platform, type SessionOut } from "./lib/api";
import { Instrument } from "./screens/Instrument";
import { Overview } from "./screens/Overview";
import { Params } from "./screens/Params";
import { Protocol } from "./screens/Protocol";
import { Repeatability } from "./screens/Repeatability";
import { SessionView } from "./screens/SessionView";

type Tab = "overview" | "instrument" | "repeatability" | "protocol" | "params";
type Theme = "auto" | "light" | "dark";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Обзор" },
  { id: "instrument", label: "Приборы" },
  { id: "repeatability", label: "Повторяемость" },
  { id: "protocol", label: "Протокол" },
  { id: "params", label: "Параметры" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [session, setSession] = useState<string | null>(null);
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [sessions, setSessions] = useState<SessionOut[]>([]);
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("diers-theme") as Theme) ?? "auto",
  );

  useEffect(() => {
    api.platform().then(setPlatform).catch(() => {});
    api.sessions().then(setSessions).catch(() => {});
  }, []);

  /** §14.6: три состояния темы. «Авто» не ставит атрибут вовсе — тогда работает
   *  системная настройка через prefers-color-scheme. */
  useEffect(() => {
    localStorage.setItem("diers-theme", theme);
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  return (
    <div className="app">
      <nav className="sidebar" aria-label="Основная навигация">
        <div className="brand">
          <div className="brand-mark" aria-hidden>D</div>
          <div>
            <div className="brand-name">DIERS</div>
            <div className="brand-sub">
              постуральный модуль · {platform?.intended_use === "clinical" ? "клиника" : "исследование"}
            </div>
          </div>
        </div>

        {TABS.map((t) => (
          <button key={t.id} className="nav-item"
                  aria-current={tab === t.id && !session ? "page" : undefined}
                  onClick={() => { setTab(t.id); setSession(null); }}>
            <span className="dot" aria-hidden />
            {t.label}
          </button>
        ))}

        <div className="theme-row">
          <div className="tile-label" style={{ marginBottom: 8 }}>Тема</div>
          <div className="segmented">
            {(["auto", "light", "dark"] as Theme[]).map((t) => (
              <button key={t} aria-pressed={theme === t} onClick={() => setTheme(t)}>
                {t === "auto" ? "Авто" : t === "light" ? "Светлая" : "Тёмная"}
              </button>
            ))}
          </div>
          {platform && (
            <div className="mono" style={{ marginTop: 12, lineHeight: 1.6 }}>
              реестр {platform.versions.registry_version}<br />
              пороги {platform.versions.thresholds_version}<br />
              нормы {platform.versions.norms_version}
            </div>
          )}
        </div>
      </nav>

      <main className="main">
        {session ? (
          <SessionView sessionId={session} onBack={() => setSession(null)} />
        ) : tab === "overview" ? (
          <Overview platform={platform} onOpen={setSession} />
        ) : tab === "instrument" ? (
          <Instrument sessions={sessions} />
        ) : tab === "repeatability" ? (
          <Repeatability />
        ) : tab === "protocol" ? (
          <Protocol />
        ) : (
          <Params />
        )}
      </main>
    </div>
  );
}
