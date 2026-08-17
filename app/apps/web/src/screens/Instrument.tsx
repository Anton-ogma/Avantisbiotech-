import { useEffect, useMemo, useState } from "react";
import { api, type FiguresOut, type MeasuredParam, type Measurements,
         type SessionOut } from "../lib/api";
import { AnatomyCompare, type Orientation } from "../components/Anatomy";
import { ReportByStructure, ReportCompare } from "../components/ReportViews";
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
  // Несколько проб сразу и выбор раскладки: одна проба отвечает на «что в этой
  // пробе», несколько — на «чем пробы отличаются». Это разные вопросы.
  const [picked, setPicked] = useState<string[]>([]);
  const [orientation, setOrientation] = useState<Orientation>("rows");
  // Схемы платформы — вторичны: иллюстрация берётся из отчёта DIERS, а
  // перерисовка существует ради сравнения проб там, где листа отчёта нет.
  const [showSchemes, setShowSchemes] = useState(false);

  useEffect(() => {
    if (!selected && sessions.length) setSelected(sessions[0].id);
  }, [sessions, selected]);

  useEffect(() => {
    if (!selected) return;
    setData(null);
    api.measurements(selected).then((d) => {
      setData(d);
      setTrial(d.trials[0]?.trial_id ?? "");
      setPicked(d.trials.slice(0, 2).map((x) => x.trial_id));
    }).catch((e) => setError(e.message));
    // Иллюстраций может не быть вовсе — это не ошибка, а свойство формата.
    api.figures(selected).then(setFigures).catch(() => setFigures(null));
  }, [selected]);

  const current = data?.trials.find((t) => t.trial_id === trial);
  const { paired, single } = current ? pairs(current.params) : { paired: [], single: [] };
  /** Структурные величины измеряются один раз за сессию и по пробам не меняются
   *  (§14.2 п. 8). Дублировать их измерением в каждой пробе значило бы объявить
   *  сделанными измерения, которых не делали, — поэтому они подмешиваются к
   *  значениям пробы при показе, а не в данные. */
  const structural = useMemo(() => {
    const out: Record<string, number> = {};
    for (const tr of data?.trials ?? []) {
      for (const pp of tr.params) {
        if (pp.code.startsWith("LEG_AXIS_")) out[pp.code] = pp.value;
      }
    }
    return out;
  }, [data]);

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
            <ReportByStructure figures={figures?.figures ?? []} probe={current.probe_code} />
          )}

          {data.trials.length > 0 && (
            <>
              <div className="row" style={{ marginTop: 26, marginBottom: 12 }}>
                <div className="section-title" style={{ margin: 0 }}>Сравнение проб</div>
                <span className="spacer" />
                <Segmented value={orientation} onChange={setOrientation} options={[
                  { value: "rows", label: "Горизонтально" },
                  { value: "columns", label: "Вертикально" },
                ]} />
              </div>
              <Card>
                <div className="tile-label" style={{ marginBottom: 10 }}>
                  Пробы в просмотре · выбрано {picked.length}
                </div>
                <div className="row">
                  {data.trials.map((tr) => {
                    const on = picked.includes(tr.trial_id);
                    return (
                      <button key={tr.trial_id} className="pill" aria-pressed={on}
                              onClick={() => setPicked((prev) => on
                                ? prev.filter((x) => x !== tr.trial_id)
                                : [...prev, tr.trial_id])}>
                        {on ? "− " : "+ "}{tr.label_ru}
                      </button>
                    );
                  })}
                </div>
                <p className="tile-hint">
                  {orientation === "rows"
                    ? "Строка — структура, столбцы — пробы: так сравнивают одну структуру между пробами."
                    : "Колонка — проба, структуры сверху вниз: так читают пробу целиком."}
                  {" "}Число проб не ограничено, ряд прокручивается. Показаны
                  иллюстрации отчёта DIERS; где листа нет — так и сказано.
                </p>
                <div className="row">
                  <button className="pill" aria-pressed={showSchemes}
                          onClick={() => setShowSchemes((v) => !v)}>
                    {showSchemes ? "− схемы из чисел" : "+ схемы из чисел"}
                  </button>
                  <span className="tile-hint" style={{ flex: 1 }}>
                    Дополнительно к иллюстрациям отчёта: та же геометрия, построенная
                    из измеренных величин. Отчёт она не заменяет.
                  </span>
                </div>
                {picked.length === 0 && (
                  <Empty text="Добавьте пробы, чтобы построить схемы." />
                )}
              </Card>

              {picked.length > 0 && (
                <ReportCompare
                  figures={figures?.figures ?? []}
                  orientation={orientation}
                  probes={picked.map((id) => {
                    const tr = data.trials.find((x) => x.trial_id === id);
                    return { code: tr?.probe_code ?? id,
                             label: (tr?.label_ru ?? id) };
                  })}
                />
              )}

              {showSchemes && picked.length > 0 && (
                <AnatomyCompare orientation={orientation} probes={picked.map((id) => {
                  const tr = data.trials.find((x) => x.trial_id === id);
                  return {
                    code: id,
                    label: (tr?.label_ru ?? id).replace(/^(MAND|PODAL|CTRL|CDG)[_\s]/, ""),
                    values: { ...structural,
                      ...Object.fromEntries((tr?.params ?? []).map((pp) => [pp.code, pp.value])) },
                  };
                })} />
              )}
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
