import { useEffect, useState } from "react";
import { api, type CompareOut, type CrossModal as CM, type Measurements, type SessionOut } from "../lib/api";
import { BodyMap, RegionBars } from "../components/BodyMap";
import { CondylarProfile, EmgMirror, SignalTriad, type Channel, type CondylarMetric } from "../components/Modality";
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
    if (!selected || picked.length === 0) { setCompare(null); return; }
    api.compare(selected, picked)
      .then((c) => { setCompare(c); if (!c.regions.some((r) => r.key === region))
        setRegion(c.regions[0]?.key ?? ""); })
      .catch((e) => setError(e.message));
  }, [selected, picked]);

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
                {compare && !compare.has_baseline && (
                  <p className="tile-hint">
                    Нейтрали в сессии нет: показаны абсолютные значения без Δ.
                  </p>
                )}
              </Card>

              {compare && compare.regions.length > 0 && (
                <>
                  <div className="section-title">От сустава до стоп</div>
                  <div className="grid cols-2">
                    <Card>
                      <div className="chart-scroll">
                        <BodyMap regions={compare.regions} active={region} onPick={setRegion} />
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
                        {compare.regions.map((r) => (
                          <button key={r.key} className="pill" aria-pressed={r.key === region}
                                  onClick={() => setRegion(r.key)}>
                            {r.label_ru}
                          </button>
                        ))}
                      </div>
                      <div className="row" style={{ marginTop: 14 }}>
                        {compare.columns.map((c, i) => (
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

                  {compare.regions.filter((r) => r.key === region).map((r) => (
                    <div key={r.key}>
                      <div className="section-title">{r.label_ru}</div>
                      <Card>
                        {r.hint && <p className="tile-hint" style={{ marginTop: 0 }}>{r.hint}</p>}
                        <div className="chart-scroll">
                          <RegionBars region={r} columns={compare.columns} palette={PALETTE} />
                        </div>
                        <div className="table-wrap" style={{ marginTop: 16 }}>
                          <table>
                            <thead>
                              <tr>
                                <th>Параметр</th>
                                <th className="num">Нейтраль</th>
                                {compare.columns.map((c) => (
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
                                  {compare.columns.map((c) => {
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
              <div className="section-title">Три сигнала пробы</div>
              <Card>
                <div className="chart-scroll"><SignalTriad posture={current.posture.delta} joint={current.joint.delta}
                             muscle={current.muscle.delta} threshold={2.0} /></div>
                <div className="grid cols-3" style={{ marginTop: 12 }}>
                  {(["posture", "joint", "muscle"] as const).map((k) => (
                    <div key={k} className="tile-hint">
                      <strong>{k === "posture" ? "Поза" : k === "joint" ? "Сустав" : "Мышца"}:</strong>{" "}
                      {current[k].detail}
                    </div>
                  ))}
                </div>
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
