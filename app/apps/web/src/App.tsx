import { useEffect, useState } from "react";
import { api, type Platform, type SessionOut } from "./lib/api";
import { Banner } from "./components/ui";
import { CrossModalScreen } from "./screens/CrossModal";
import { Instrument } from "./screens/Instrument";
import { Montage } from "./screens/Montage";
import { Overview } from "./screens/Overview";
import { Params } from "./screens/Params";
import { Protocol } from "./screens/Protocol";
import { Repeatability } from "./screens/Repeatability";
import { Upload } from "./screens/Upload";
import { SessionView } from "./screens/SessionView";

type Tab = "overview" | "upload" | "montage" | "compare" | "instrument"
         | "repeatability" | "protocol" | "params";
type Theme = "auto" | "light" | "dark";

/** short — подпись для нижней панели телефона: семь полных названий туда
 *  не помещаются, и вкладки уезжают за край вместо того, чтобы быть видимыми. */
const TABS: { id: Tab; label: string; short: string }[] = [
  { id: "overview", label: "Обзор", short: "Обзор" },
  { id: "upload", label: "Загрузка", short: "Файлы" },
  { id: "montage", label: "Монтаж ЭМГ", short: "ЭМГ" },
  { id: "compare", label: "Сравнение", short: "Пробы" },
  { id: "instrument", label: "Приборы", short: "Приборы" },
  { id: "repeatability", label: "Повторяемость", short: "Повтор" },
  { id: "protocol", label: "Протокол", short: "Метод" },
  { id: "params", label: "Параметры", short: "Реестр" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [session, setSession] = useState<string | null>(null);
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [sessions, setSessions] = useState<SessionOut[]>([]);
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("diers-theme") as Theme) ?? "auto",
  );

  // Отказ загрузки НЕ проглатывается. Пустая оболочка без единого слова —
  // худший из отказов: пользователь не отличит «данных нет» от «сервер не
  // отвечает» и будет считать, что обследования потерялись.
  const [loadError, setLoadError] = useState<string | null>(null);
  const reload = () => {
    api.sessions()
      .then((x) => { setSessions(x); setLoadError(null); })
      .catch((e) => setLoadError((e as Error).message));
  };
  useEffect(() => {
    api.platform().then(setPlatform).catch((e) => setLoadError((e as Error).message));
    reload();
  }, []);

  /** §14.6: три состояния темы. «Авто» не ставит атрибут вовсе — тогда работает
   *  системная настройка через prefers-color-scheme. */
  useEffect(() => {
    localStorage.setItem("diers-theme", theme);
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const themeSwitch = (compact = false) => (
    <div className={`segmented ${compact ? "theme-compact" : ""}`} role="group" aria-label="Тема">
      {(["auto", "light", "dark"] as Theme[]).map((t) => (
        <button key={t} aria-pressed={theme === t} onClick={() => setTheme(t)}>
          {t === "auto" ? "Авто" : t === "light" ? "Светлая" : "Тёмная"}
        </button>
      ))}
    </div>
  );

  return (
    <div className="app">
      {/* Шапка появляется на планшете и телефоне: там нет боковой панели,
          и без неё сменить тему было бы нечем. */}
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden>D</div>
          <div>
            <div className="brand-name">DIERS</div>
            <div className="brand-sub">постуральный модуль</div>
          </div>
        </div>
        {themeSwitch(true)}
      </header>

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
            <span className="nav-full">{t.label}</span>
            <span className="nav-short">{t.short}</span>
          </button>
        ))}

        <div className="theme-row">
          <div className="tile-label" style={{ marginBottom: 8 }}>Тема</div>
          {themeSwitch()}
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
        {loadError && (
          <Banner text={
            `Данные не загрузились: ${loadError}. Показанное ниже может быть `
            + "неполным. Проверьте, поднят ли модуль и доступен ли он с этой машины."
          } />
        )}
        {session ? (
          <SessionView sessionId={session} onBack={() => setSession(null)} />
        ) : tab === "overview" ? (
          <Overview platform={platform} onOpen={setSession} />
        ) : tab === "upload" ? (
          <Upload sessions={sessions} onDone={reload} />
        ) : tab === "montage" ? (
          <Montage sessions={sessions} />
        ) : tab === "compare" ? (
          <CrossModalScreen sessions={sessions} />
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
