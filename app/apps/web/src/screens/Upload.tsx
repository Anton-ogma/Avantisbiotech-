import { useRef, useState } from "react";
import { api, isSnapshot, type IngestReport, type SessionOut } from "../lib/api";
import { Banner, Card, Empty, Tile } from "../components/ui";

const STATUS_RU: Record<string, string> = {
  ingested: "загружено",
  needs_probe_assignment: "нужна проба",
  duplicate: "дубликат",
  unrecognized: "формат не распознан",
  failed: "ошибка разбора",
  rejected: "отклонено",
};
const STATUS_TONE: Record<string, string> = {
  ingested: "good", needs_probe_assignment: "neutral", duplicate: "neutral",
  unrecognized: "bad", failed: "bad", rejected: "bad",
};

export function Upload({ sessions, onDone }: { sessions: SessionOut[]; onDone: () => void }) {
  const [selected, setSelected] = useState(sessions[0]?.id ?? "");
  const [report, setReport] = useState<IngestReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const offline = isSnapshot();
  const input = useRef<HTMLInputElement>(null);

  async function send(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length || !selected) return;
    setBusy(true); setError(null);
    try {
      setReport(await api.autoIngest(selected, list));
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <>
      <h1 className="title">Загрузка данных</h1>
      <p className="subtitle">
        Положите файлы любых приборов — формометрия, кондилография, ЭМГ, изометрическая
        сила. Модальность, показатели и проба определяются из самих файлов; указывать
        ничего не нужно. Что распознать не удалось, не пропадает: остаётся с причиной.
      </p>
      {offline && (
        <Banner text={
          "Открыт автономный снимок: данные показываются, но загрузка файлов в него " +
          "невозможна — бэкенда рядом нет. Разверните экземпляр (docker compose up), " +
          "чтобы принимать выгрузки приборов."
        } />
      )}
      {error && <Banner text={error} />}

      <Card>
        <div className="row">
          <span className="tile-label">Сессия</span>
          <select className="pill" style={{ minWidth: 300 }} value={selected}
                  onChange={(e) => setSelected(e.target.value)}>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {new Date(s.started_at).toLocaleDateString("ru-RU")} · {s.patient_ref.slice(0, 22)} · {s.status}
              </option>
            ))}
          </select>
        </div>
      </Card>

      <div
        className="card fade-in"
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); send(e.dataTransfer.files); }}
        style={{
          marginTop: 14, textAlign: "center", padding: "44px 24px",
          borderStyle: "dashed", borderWidth: 2,
          borderColor: dragging ? "var(--accent)" : "var(--stroke-strong)",
          transition: "border-color .24s var(--spring), transform .24s var(--spring)",
          transform: dragging ? "scale(1.01)" : "none",
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>
          {busy ? "Разбираю…" : "Перетащите файлы сюда"}
        </div>
        <div className="tile-hint" style={{ marginBottom: 16 }}>
          CSV, TXT, XML, PDF-протоколы · можно сразу пачкой
        </div>
        <button className="pill" onClick={() => input.current?.click()} disabled={busy || !selected}>
          Выбрать файлы
        </button>
        <input ref={input} type="file" multiple hidden accept=".csv,.txt,.xml,.pdf,.c3d,.edf"
               onChange={(e) => e.target.files && send(e.target.files)} />
      </div>

      {report && (
        <>
          <div className="section-title">Результат распознавания</div>
          <div className="grid cols-4">
            <Tile label="Загружено" value={report.summary.ingested}
                  tone={report.summary.ingested ? "good" : undefined} />
            <Tile label="Нужна проба" value={report.summary.needs_assignment}
                  hint="метка условия не найдена в реестре — угадывать нельзя" />
            <Tile label="Не распознано" value={report.summary.unrecognized}
                  tone={report.summary.unrecognized ? "bad" : undefined}
                  hint="файл сохранён с причиной, не пропал" />
            <Tile label="Дубликаты" value={report.summary.duplicates}
                  hint="тот же файл уже импортирован" />
          </div>
          <Card style={{ marginTop: 14, padding: 8 }}>
            {report.files.length === 0 ? <Empty text="Файлов нет" /> : report.files.map((f, i) => (
              <div key={`${f.filename}-${i}`} className="list-row" style={{ cursor: "default" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 560, fontSize: 13.5 }}>{f.filename}</div>
                  <div className="tile-hint">
                    {f.modality ?? "—"}
                    {f.format_id && <span className="mono"> · {f.format_id}</span>}
                    {f.condition_label && <> · метка «{f.condition_label}»</>}
                    {f.params > 0 && <> · показателей {f.params}</>}
                  </div>
                  {f.reason && <div className="tile-hint" style={{ marginTop: 4 }}>{f.reason}</div>}
                </div>
                {f.probe_code && <span className="badge accent">{f.probe_code}</span>}
                <span className={`badge ${STATUS_TONE[f.status] ?? ""}`}>
                  {STATUS_RU[f.status] ?? f.status}
                </span>
              </div>
            ))}
          </Card>
        </>
      )}
    </>
  );
}
