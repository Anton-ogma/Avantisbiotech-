import { useEffect, useState } from "react";
import { api, type Platform, type SessionOut } from "../lib/api";
import { Banner, Card, Empty, Tile } from "../components/ui";

const STATUS_RU: Record<string, string> = {
  prepared: "подготовка", plan_approved: "план утверждён", baseline_recorded: "нейтраль снята",
  probes_running: "идут пробы", imported: "импортировано", quality_reviewed: "качество разобрано",
  shortlist_confirmed: "шорт-лист подтверждён", analyzed: "проанализировано", reported: "отчёт выпущен",
};

export function Overview({ platform, onOpen }: { platform: Platform | null; onOpen: (id: string) => void }) {
  const [sessions, setSessions] = useState<SessionOut[]>([]);
  const [progress, setProgress] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.sessions().then(setSessions).catch((e) => setError(e.message));
    api.progress().then(setProgress).catch(() => {});
  }, []);

  const lowConf = sessions.filter((s) => s.low_confidence).length;

  return (
    <>
      <h1 className="title">Обзор</h1>
      <p className="subtitle">
        Научно-практическая платформа: выявляет закономерности, а не применяет готовые.
        Нормы, пороги и направление «лучше/хуже» — параметры исследования, каждый
        поддерживает состояние «не определено» и своим отсутствием работу не блокирует.
      </p>

      {platform?.banners.map((b) => <Banner key={b} text={b} />)}
      {error && <Banner text={`Ошибка загрузки: ${error}`} />}

      <div className="grid cols-4">
        <Tile label="Сессий" value={sessions.length} hint="всего в базе" />
        <Tile label="С меткой low_confidence" value={lowConf}
              tone={lowConf ? "warn" : undefined}
              hint="остаточный дрейф нейтрали выше порога" />
        <Tile label="Направление установлено"
              value={progress ? `${progress.params_direction_known} / ${progress.params_total}` : "…"}
              hint="параметров вышло из direction = unknown" />
        <Tile label="Режим" value={platform?.intended_use === "research" ? "Исследование" : "Клиника"}
              hint={platform?.intended_use === "research"
                ? "не медизделие, назначений не выдаёт"
                : `РУ ${platform?.registration_number ?? "—"}`} />
      </div>

      <div className="section-title">Сессии</div>
      <Card style={{ padding: 8 }}>
        {sessions.length === 0 && <Empty text="Сессий нет. Запустите seed: make seed" />}
        {sessions.map((s) => (
          <button key={s.id} className="list-row" onClick={() => onOpen(s.id)}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 560, fontSize: 14 }}>
                <span className="mono">{s.patient_ref.slice(0, 16)}</span>
              </div>
              <div className="tile-hint">
                {new Date(s.started_at).toLocaleString("ru-RU")} · оператор {s.operator_ref} ·
                проб {s.trial_count} · проходов {s.pass_count}
              </div>
            </div>
            {s.study_mode && <span className="badge accent">исследование</span>}
            {s.low_confidence && <span className="badge">низкая достоверность</span>}
            <span className="badge neutral">{STATUS_RU[s.status] ?? s.status}</span>
            <span aria-hidden style={{ color: "var(--text-3)" }}>›</span>
          </button>
        ))}
      </Card>
    </>
  );
}
