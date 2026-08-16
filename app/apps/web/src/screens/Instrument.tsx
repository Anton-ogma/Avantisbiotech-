import { useEffect, useState } from "react";
import { api, type FiguresOut, type MeasuredParam, type Measurements,
         type SessionOut } from "../lib/api";
import { AnatomySet, type Values } from "../components/Anatomy";
import { ProtocolFigures } from "../components/ProtocolFigures";
import { Banner, Card, Empty, Segmented, Tile } from "../components/ui";

const FLAG_RU: Record<string, string> = {
  "reproducibility_side_mismatch:3mm":
    "Воспроизводимость сторон различается более чем в 5 раз на 3 мм — признак неравного качества записи, а не биологии",
  no_canonical_columns: "Ни один канонический столбец не распознан",
};

/** Пары «право/лево» для кондилографии: прибор печатает метрики по сторонам,
 *  и асимметрия здесь — содержательная величина, а не оформление. */
function pairs(params: MeasuredParam[]) {
  const map = new Map<string, { label: string; unit: string; r?: number; l?: number }>();
  const single: MeasuredParam[] = [];
  for (const p of params) {
    const m = p.code.match(/^(.*)_(R|L)$/);
    if (!m) { single.push(p); continue; }
    const base = m[1];
    const row = map.get(base) ?? { label: p.label_ru.replace(/,\s*(справа|слева)$/, ""), unit: p.unit };
    if (m[2] === "R") row.r = p.value; else row.l = p.value;
    map.set(base, row);
  }
  return { paired: [...map.entries()].sort(), single };
}

const asym = (r?: number, l?: number) =>
  r === undefined || l === undefined || Math.abs(r) + Math.abs(l) === 0
    ? null : (200 * (r - l)) / (Math.abs(r) + Math.abs(l));

export function Instrument({ sessions }: { sessions: SessionOut[] }) {
  const [selected, setSelected] = useState<string>("");
  const [data, setData] = useState<Measurements | null>(null);
  const [trial, setTrial] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [figures, setFigures] = useState<FiguresOut | null>(null);

  useEffect(() => {
    if (!selected && sessions.length) setSelected(sessions[0].id);
  }, [sessions, selected]);

  useEffect(() => {
    if (!selected) return;
    setData(null);
    api.measurements(selected).then((d) => {
      setData(d);
      setTrial(d.trials[0]?.trial_id ?? "");
    }).catch((e) => setError(e.message));
    // Иллюстраций может не быть вовсе — это не ошибка, а свойство формата.
    api.figures(selected).then(setFigures).catch(() => setFigures(null));
  }, [selected]);

  const current = data?.trials.find((t) => t.trial_id === trial);
  const { paired, single } = current ? pairs(current.params) : { paired: [], single: [] };
  const values: Values = Object.fromEntries((current?.params ?? []).map((p) => [p.code, p.value]));
  const shownFigures = (figures?.figures ?? []).filter((f) => f.probe_code === current?.probe_code);

  return (
    <>
      <h1 className="title">Приборные данные</h1>
      <p className="subtitle">
        Канонические значения по пробам для модальностей, которые не сводятся к отклику
        от нейтрали: кондилография CADIAX и динамическая формометрия. Сустав — отдельный
        сигнал, в постуральный индекс он не суммируется.
      </p>
      {error && <Banner text={error} />}

      <Card>
        <div className="row">
          <span className="tile-label">Сессия</span>
          <select className="pill" value={selected} onChange={(e) => setSelected(e.target.value)}
                  style={{ minWidth: 280 }}>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {new Date(s.started_at).toLocaleDateString("ru-RU")} · {s.patient_ref.slice(0, 22)}
              </option>
            ))}
          </select>
          {data?.device && <span className="badge accent">{data.device}</span>}
        </div>
      </Card>

      {!data ? <Empty text="Загрузка…" /> : (
        <>
          <div className="section-title">Пробы сессии</div>
          <Card>
            <Segmented value={trial}
                       options={data.trials.map((t) => ({ value: t.trial_id, label: t.label_ru }))}
                       onChange={setTrial} />
            {current?.quality_flags.map((f) => (
              <div key={f} style={{ marginTop: 12 }}>
                <Banner text={FLAG_RU[f] ?? f} />
              </div>
            ))}
          </Card>

          {current && (
            <>
              <div className="section-title">Схемы по измерениям</div>
              <Card>
                <AnatomySet values={values} />
              </Card>
            </>
          )}

          {shownFigures.length > 0 && (
            <>
              <div className="section-title">Иллюстрации протокола прибора</div>
              <Card>
                <ProtocolFigures figures={shownFigures} />
                {figures && <p className="tile-hint">{figures.note}</p>}
              </Card>
            </>
          )}

          {paired.length > 0 && (
            <>
              <div className="section-title">Право / лево и асимметрия</div>
              <Card>
                <div className="grid cols-3" style={{ marginBottom: 16 }}>
                  {paired.filter(([b]) => b.includes("MAX_EXCURSION")).map(([b, row]) => (
                    <Tile key={b} label="Максимальная экскурсия"
                          value={`${row.r ?? "—"} / ${row.l ?? "—"} ${row.unit}`}
                          hint="источник величины для сверки с формометрией (§6.2)" />
                  ))}
                  {paired.filter(([b]) => b.endsWith("SCI_10MM")).map(([b, row]) => {
                    const a = asym(row.r, row.l);
                    return <Tile key={b} label="Асимметрия SCI на 10 мм"
                                 value={a === null ? "—" : `${a.toFixed(1)} %`}
                                 hint="суставной знак когерентности (§9.5)" />;
                  })}
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>Показатель</th><th className="num">Справа</th><th className="num">Слева</th>
                          <th className="num">Асимметрия</th><th>Ед.</th></tr>
                    </thead>
                    <tbody>
                      {paired.map(([base, row]) => {
                        const a = asym(row.r, row.l);
                        return (
                          <tr key={base}>
                            <td>{row.label}<div className="mono">{base}</div></td>
                            <td className="num">{row.r ?? "—"}</td>
                            <td className="num">{row.l ?? "—"}</td>
                            {/* Цвет не назначается: направление не установлено (Р-18) */}
                            <td className="num">
                              {a === null ? "—" : (
                                <span className={`badge ${Math.abs(a) > 20 ? "neutral" : ""}`}>
                                  {a > 0 ? "+" : ""}{a.toFixed(1)} %
                                </span>
                              )}
                            </td>
                            <td className="muted">{row.unit}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            </>
          )}

          {single.length > 0 && (
            <>
              <div className="section-title">Параметры без сторонности</div>
              <Card>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Параметр</th><th className="num">Значение</th><th>Ед.</th><th>Домен</th><th>В индексе</th></tr></thead>
                    <tbody>
                      {single.map((p) => (
                        <tr key={p.code}>
                          <td>{p.label_ru}<div className="mono">{p.code}</div></td>
                          <td className="num">{p.value}</td>
                          <td className="muted">{p.unit}</td>
                          <td><span className="badge neutral">{p.domain}</span></td>
                          <td>{p.in_index ? "да" : <span className="muted">отдельный сигнал</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </>
          )}
        </>
      )}
    </>
  );
}
