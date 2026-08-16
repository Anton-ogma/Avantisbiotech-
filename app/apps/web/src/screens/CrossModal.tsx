import { useEffect, useMemo, useState } from "react";
import { api, type CompareOut, type CrossModal as CM, type FiguresOut, type Measurements,
         type SessionOut } from "../lib/api";
import { AnatomyCompare, AnatomySet, type Values } from "../components/Anatomy";
import { BodyMap, RegionBars } from "../components/BodyMap";
import { ProtocolFigures } from "../components/ProtocolFigures";
import { CondylarProfile, EmgMirror, SignalPanel, type Channel,
         type CondylarMetric } from "../components/Modality";
import { DeltaChart } from "../components/DeltaChart";
import { Banner, Card, DeltaBadge, Empty, Segmented, Tile } from "../components/ui";

const VERDICT_TONE: Record<string, string> = {
  best: "good", worse: "bad", conflicting: "bad",
  unsigned: "neutral", neutral: "neutral", no_posture: "neutral",
};
const BUCKET_TITLE: Record<string, string> = {
  best: "Лучшие по отклику",
  worse: "Ухудшают",
  conflicting: "Конфликт позы и мышцы",
  unsigned: "Отвечают, знак не установлен",
  neutral: "В пределах шума",
  no_posture: "Поза не измерена",
};
/** Палитра серий: цвет кодирует ПРОБУ, направление уходит в подпись — §14.2 п. 3
 *  для случая нескольких наложенных объектов. */
const PALETTE = ["var(--accent)", "var(--accent-2)", "#e08a3c", "#39a06b", "#c2569a"];

const SIGNAL_RU: Record<string, string> = {
  posture: "Поза", joint: "Сустав", muscle: "Мышца", strength: "Сила",
};

const MUSCLE_RU: Record<string, string> = {
  MASSETER: "жеват.", TEMPORALIS: "височ.", SCM: "ГКС", TRAPEZIUS: "трапец.",
  ERECTOR_SPINAE: "выпрям.", QUADRATUS_LUMBORUM: "кв.пояс.", GLUTEUS_MAXIMUS: "ягод.",
  RECTUS_FEMORIS: "пр.бедра", TIBIALIS_ANTERIOR: "перед.б/б", GASTROCNEMIUS: "икр.",
};

export function CrossModalScreen({ sessions }: { sessions: SessionOut[] }) {
  const [selected, setSelected] = useState("");
  const [data, setData] = useState<CM | null>(null);
  const [raw, setRaw] = useState<Measurements | null>(null);
  const [probe, setProbe] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [compare, setCompare] = useState<CompareOut | null>(null);
  const [figures, setFigures] = useState<FiguresOut | null>(null);
  const [region, setRegion] = useState("");
  const [view, setView] = useState<"single" | "table">("single");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (!selected && sessions.length) setSelected(sessions[0].id); }, [sessions, selected]);
  useEffect(() => {
    if (!selected) return;
    setData(null); setError(null);
    Promise.all([api.crossmodal(selected), api.measurements(selected)])
      .then(([c, m]) => {
        setData(c); setRaw(m);
        setProbe(c.probes[0]?.probe_code ?? "");
        // По умолчанию сравниваем лучшую и худшую: именно этот контраст
        // читают в первую очередь.
        const best = c.ranking.best?.[0];
        const worse = c.ranking.worse?.[0];
        const initial = [best, worse].filter(Boolean) as string[];
        setPicked(initial.length ? initial : c.probes.slice(0, 2).map((p) => p.probe_code));
      })
      .catch((e) => setError(e.message));
  }, [selected]);

  useEffect(() => {
    if (!selected) { setCompare(null); return; }
    api.compare(selected)
      .then((c) => { setCompare(c); if (!c.regions.some((r) => r.key === region))
        setRegion(c.regions[0]?.key ?? ""); })
      .catch((e) => setError(e.message));
    // Иллюстрации протокола: их может не быть вовсе (CSV-путь), и это не ошибка.
    api.figures(selected).then(setFigures).catch(() => setFigures(null));
  }, [selected]);

  /** Значения по пробам для анатомических схем: одно место сборки на все
   *  схемы, иначе каждая лезла бы в `measurements` со своим разбором. */
  const valuesByProbe = useMemo(() => {
    const out = new Map<string, Values>();
    for (const trial of raw?.trials ?? []) {
      const acc = out.get(trial.probe_code) ?? {};
      for (const p of trial.params) acc[p.code] = p.value;
      out.set(trial.probe_code, acc);
    }
    return out;
  }, [raw]);

  /** Столбцы и строки фильтруются локально: ограничения на число проб нет. */
  const shown = useMemo(() => {
    if (!compare) return null;
    const columns = compare.columns.filter((c) => picked.includes(c.code));
    const regions = compare.regions
      .map((r) => ({
        ...r,
        rows: r.rows
          .map((row) => ({
            ...row,
            cells: Object.fromEntries(
              Object.entries(row.cells).filter(([code]) => picked.includes(code)),
            ),
          }))
          .filter((row) => Object.keys(row.cells).length > 0),
      }))
      .filter((r) => r.rows.length > 0);
    return { ...compare, columns, regions };
  }, [compare, picked]);

  const toggle = (code: string) =>
    setPicked((prev) => prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]);

  const current = data?.probes.find((p) => p.probe_code === probe);
  const trial = raw?.trials.find((t) => t.probe_code === probe);

  const emg: Channel[] = [];
  const condylar: CondylarMetric[] = [];
  if (trial) {
    const byMuscle = new Map<string, Channel>();
    const byBase = new Map<string, CondylarMetric>();
    for (const p of trial.params) {
      const emgM = p.code.match(/^EMG_RMS_(.+)_(L|R)$/);
      if (emgM) {
        const row = byMuscle.get(emgM[1]) ?? {
          muscle: emgM[1], label: MUSCLE_RU[emgM[1]] ?? emgM[1].slice(0, 8),
        };
        if (emgM[2] === "L") row.left = p.value; else row.right = p.value;
        byMuscle.set(emgM[1], row);
      }
      const cdgM = p.code.match(/^(CDG_.+)_(L|R)$/);
      if (cdgM) {
        const row = byBase.get(cdgM[1]) ?? {
          base: cdgM[1], label: p.label_ru.replace(/,\s*(справа|слева)$/, ""), unit: p.unit,
        };
        if (cdgM[2] === "L") row.l = p.value; else row.r = p.value;
        byBase.set(cdgM[1], row);
      }
    }
    emg.push(...byMuscle.values());
    condylar.push(...byBase.values());
  }

  return (
    <>
      <h1 className="title">Сравнение проб</h1>
      <p className="subtitle">
        Поза, сустав и мышца сводятся не в один индекс, а в согласованность между собой.
        Классификация описывает измеренный отклик, а не назначение: переход от «даёт
        наибольшее улучшение позы» к «назначить» делает врач.
      </p>
      {error && <Banner text={error} />}

      <Card>
        <div className="row">
          <span className="tile-label">Сессия</span>
          <select className="pill" style={{ minWidth: 300 }} value={selected}
                  onChange={(e) => setSelected(e.target.value)}>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {new Date(s.started_at).toLocaleDateString("ru-RU")} · {s.patient_ref.slice(0, 22)}
              </option>
            ))}
          </select>
        </div>
      </Card>

      {data?.warning && <Banner text={data.warning} />}
      {!data ? <Empty text="Считаю стыковку…" /> : data.probes.length === 0 ? (
        <Card>
          <Empty text={
            data.warning
              ? "Отклики не считаются: в сессии нет нейтрали. Опора нужна, чтобы было от чего отсчитывать Δ."
              : "В сессии нет проб, кроме нейтрали."
          } />
          {Object.keys(data.modalities).length > 0 && (
            <div className="row" style={{ justifyContent: "center", marginTop: 4 }}>
              {Object.entries(data.modalities).map(([code, mods]) => (
                <span key={code} className="badge">{code} · {mods.join(", ")}</span>
              ))}
            </div>
          )}
        </Card>
      ) : (
        <>
          <div className="section-title">Раскладка проб</div>
          <div className="grid cols-3">
            {["best", "worse", "conflicting", "unsigned", "neutral", "no_posture"]
              .filter((b) => (data.ranking[b] ?? []).length)
              .map((b) => (
                <Tile key={b} label={BUCKET_TITLE[b]} value={data.ranking[b].length}
                      tone={VERDICT_TONE[b] as any}
                      hint={data.ranking[b].map((c) => c.replace(/^(MAND|PODAL|CTRL|CDG)_/, "")).join(", ")} />
              ))}
          </div>

          <div className="row" style={{ marginTop: 26, marginBottom: 12 }}>
            <div className="section-title" style={{ margin: 0 }}>Проба</div>
            <span className="spacer" />
            <Segmented value={view} onChange={setView} options={[
              { value: "single", label: "Одна проба" },
              { value: "table", label: "Сравнить несколько" },
            ]} />
          </div>

          {view === "table" ? (
            <>
              <Card>
                <div className="tile-label" style={{ marginBottom: 10 }}>
                  Пробы в сравнении · выбрано {picked.length}
                </div>
                <div className="row">
                  {data.probes.map((p) => {
                    const on = picked.includes(p.probe_code);
                    return (
                      <button key={p.probe_code} className="pill" aria-pressed={on}
                              onClick={() => toggle(p.probe_code)}>
                        {on ? "− " : "+ "}{p.probe_code.replace(/^(MAND|PODAL|CTRL|CDG)_/, "")}
                      </button>
                    );
                  })}
                </div>
                {picked.length === 0 && (
                  <p className="tile-hint">Добавьте пробы, чтобы построить таблицу.</p>
                )}
                {shown && !shown.has_baseline && (
                  <p className="tile-hint">
                    Нейтрали в сессии нет: показаны абсолютные значения без Δ.
                  </p>
                )}
              </Card>

              {shown && shown.columns.length > 0 && (
                <>
                  <div className="section-title">Схемы по пробам</div>
                  <Card>
                    <p className="tile-hint" style={{ marginTop: 0 }}>
                      Один вид — один ряд, столбцы — пробы. Схемы строятся из
                      измеренных величин: угол проводится под измеренным углом,
                      размах движения — веером от границы до границы.
                    </p>
                    <AnatomyCompare probes={shown.columns.map((c) => ({
                      code: c.code,
                      label: c.code.replace(/^(MAND|PODAL|CTRL|CDG)_/, ""),
                      values: valuesByProbe.get(c.code) ?? {},
                    }))} />
                  </Card>
                </>
              )}

              {shown && shown.regions.length > 0 && (
                <>
                  <div className="section-title">От сустава до стоп</div>
                  <div className="grid cols-2">
                    <Card>
                      <div className="chart-scroll">
                        <BodyMap regions={shown.regions} active={region} onPick={setRegion} />
                      </div>
                      <p className="tile-hint">
                        Насыщенность кодирует величину отклика, а не направление: для
                        большинства параметров оно не установлено, и красить область
                        в «хорошо/плохо» было бы враньём.
                      </p>
                    </Card>
                    <Card>
                      <div className="tile-label" style={{ marginBottom: 8 }}>Область</div>
                      <div className="row">
                        {shown.regions.map((r) => (
                          <button key={r.key} className="pill" aria-pressed={r.key === region}
                                  onClick={() => setRegion(r.key)}>
                            {r.label_ru}
                          </button>
                        ))}
                      </div>
                      <div className="row" style={{ marginTop: 14 }}>
                        {shown.columns.map((c, i) => (
                          <span key={c.code} className="badge" style={{
                            borderColor: PALETTE[i % PALETTE.length],
                            color: PALETTE[i % PALETTE.length],
                          }}>
                            {c.label_ru}
                          </span>
                        ))}
                      </div>
                    </Card>
                  </div>

                  {shown.regions.filter((r) => r.key === region).map((r) => (
                    <div key={r.key}>
                      <div className="section-title">{r.label_ru}</div>
                      <Card>
                        {r.hint && <p className="tile-hint" style={{ marginTop: 0 }}>{r.hint}</p>}
                        <div className="chart-scroll">
                          <RegionBars region={r} columns={shown.columns} palette={PALETTE} />
                        </div>
                        <div className="table-wrap" style={{ marginTop: 16 }}>
                          <table>
                            <thead>
                              <tr>
                                <th>Параметр</th>
                                <th className="num">Нейтраль</th>
                                {shown.columns.map((c) => (
                                  <th key={c.code} className="num">
                                    {c.code.replace(/^(MAND|PODAL|CTRL|CDG)_/, "")}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {r.rows.map((row) => (
                                <tr key={row.code}>
                                  <td>
                                    {row.label_ru}
                                    <div className="mono">{row.code} · {row.unit}</div>
                                  </td>
                                  <td className="num">{row.baseline ?? "—"}</td>
                                  {shown.columns.map((c) => {
                                    const cell = row.cells[c.code];
                                    if (!cell) return <td key={c.code} className="num muted">—</td>;
                                    if (cell.delta === null) {
                                      return <td key={c.code} className="num">{cell.value}</td>;
                                    }
                                    return (
                                      <td key={c.code} className="num">
                                        <DeltaBadge delta={cell.delta} confidence={cell.confidence}
                                                    interpretation={cell.interpretation}
                                                    direction={row.direction} />
                                      </td>
                                    );
                                  })}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </Card>
                    </div>
                  ))}
                </>
              )}
            </>
          ) : (
          <>
          <Card>
            <Segmented value={probe}
                       options={data.probes.map((p) => ({
                         value: p.probe_code,
                         label: p.probe_code.replace(/^(MAND|PODAL|CTRL|CDG)_/, ""),
                       }))}
                       onChange={setProbe} />
            {current && (
              <>
                <div className="row" style={{ marginTop: 14 }}>
                  <span className={`badge ${VERDICT_TONE[current.verdict]}`}>{current.verdict_ru}</span>
                  <span className="badge">когерентность: {current.coherence}</span>
                  {(data.modalities[current.probe_code] ?? []).map((m) => (
                    <span key={m} className="badge accent">{m}</span>
                  ))}
                </div>
                <p className="tile-hint" style={{ marginTop: 10 }}>{current.rationale}</p>
                {current.excursion && current.excursion.status !== "absent" && (
                  <div style={{ marginTop: 10 }}>
                    <span className={`badge ${current.excursion.status === "matched" ? "good" : "bad"}`}>
                      сверка экскурсии: {current.excursion.status}
                    </span>
                    <div className="tile-hint">{current.excursion.message}</div>
                  </div>
                )}
              </>
            )}
          </Card>

          {current && (
            <>
              <div className="section-title">Схемы пробы</div>
              <Card>
                <AnatomySet values={valuesByProbe.get(current.probe_code) ?? {}} />
              </Card>

              {figures && figures.figures.some((f) => f.probe_code === current.probe_code) && (
                <>
                  <div className="section-title">Иллюстрации протокола прибора</div>
                  <Card>
                    <ProtocolFigures figures={figures.figures} probe={current.probe_code} />
                    <p className="tile-hint">{figures.note}</p>
                  </Card>
                </>
              )}

              <div className="section-title">Четыре сигнала пробы</div>
              <Card>
                <div className="chart-scroll">
                  <SignalPanel posture={current.posture.delta} joint={current.joint.delta}
                               muscle={current.muscle.delta} strength={current.strength?.delta ?? null}
                               threshold={2.0} />
                </div>
                <div className="grid cols-4" style={{ marginTop: 12 }}>
                  {(["posture", "joint", "muscle", "strength"] as const).map((k) => (
                    <div key={k} className="tile-hint">
                      <strong>{SIGNAL_RU[k]}:</strong> {current[k]?.detail ?? "не измерено"}
                    </div>
                  ))}
                </div>
                <p className="tile-hint">
                  Сила показана наравне с остальными, но знака «лучше/хуже» не несёт:
                  направление под пробой не установлено, и в вердикт она не входит.
                </p>
              </Card>

              {current.posture.available && current.params.length > 0 && (
                <>
                  <div className="section-title">Формометрия · параметры</div>
                  <Card><div className="chart-scroll"><DeltaChart params={current.params as any} /></div></Card>
                </>
              )}

              {emg.length > 0 && (
                <>
                  <div className="section-title">ЭМГ · каналы по сторонам</div>
                  <Card>
                    <div className="chart-scroll"><EmgMirror channels={emg} /></div>
                    <p className="tile-hint">
                      Амплитуды в мкВ сравнимы только внутри одной сессии: между сессиями
                      электроды переклеиваются, и межсессионная динамика без нормализации
                      не строится.
                    </p>
                  </Card>
                </>
              )}

              {condylar.length > 0 && (
                <>
                  <div className="section-title">Кондилография · профиль суставного угла</div>
                  <Card>
                    <div className="chart-scroll"><CondylarProfile metrics={condylar} /></div>
                    <p className="tile-hint">
                      Расхождение кривых сторон и есть суставной сигнал. В постуральный
                      индекс он не суммируется — это отдельная из трёх составляющих.
                    </p>
                  </Card>
                </>
              )}
            </>
          )}

          </>
          )}

          {data.session_level?.myoline && Object.keys(data.session_level.myoline).length > 0 && (
            <>
              <div className="section-title">Изометрическая сила · сессионное измерение</div>
              <Card>
                <div className="grid cols-4">
                  {Object.entries(data.session_level.myoline).map(([k, v]) => (
                    <Tile key={k} label={k.replace("MYO_FORCE_", "")} value={`${v} Н`} />
                  ))}
                </div>
                <p className="tile-hint">{data.session_level.note}</p>
              </Card>
            </>
          )}
        </>
      )}
    </>
  );
}
