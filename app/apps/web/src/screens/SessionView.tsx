import { useEffect, useState } from "react";
import { api, type Analysis, type FiguresOut, type Measurements } from "../lib/api";
import { DeltaChart, ResponseChart } from "../components/DeltaChart";
import { ReportByStructure } from "../components/ReportViews";
import { Banner, Card, DeltaBadge, Empty, Segmented, Tile } from "../components/ui";

/** Что показывать, когда анализ невозможен.
 *
 *  Анализ — величина СРАВНИТЕЛЬНАЯ: без пригодной нейтрали сравнивать не с чем,
 *  и отказ здесь законен. Но измеренное-то есть: значения приборов и
 *  иллюстрации отчёта DIERS от анализа не зависят вовсе. Отдавать вместо них
 *  пустой экран с красной полосой — значит прятать загруженные данные за
 *  отказом в вычислении, которого никто и не просил.
 */
function WithoutAnalysis({ sessionId, reason }: { sessionId: string; reason: string }) {
  const [data, setData] = useState<Measurements | null>(null);
  const [figures, setFigures] = useState<FiguresOut | null>(null);
  const [trial, setTrial] = useState("");

  useEffect(() => {
    api.measurements(sessionId).then((d) => {
      setData(d);
      setTrial(d.trials[0]?.trial_id ?? "");
    }).catch(() => setData(null));
    api.figures(sessionId).then(setFigures).catch(() => setFigures(null));
  }, [sessionId]);

  const current = data?.trials.find((t) => t.trial_id === trial);

  return (
    <>
      <Banner text={`Анализ не построен: ${reason}`} />
      <Card>
        <p className="tile-hint" style={{ margin: 0 }}>
          Отклик считается ОТ НЕЙТРАЛИ этого же пациента, поэтому без пригодной
          нейтральной пробы сравнивать не с чем — это отказ по существу, а не
          сбой. Загруженное при этом никуда не делось: ниже приборные значения и
          иллюстрации отчёта DIERS, они от анализа не зависят.
        </p>
      </Card>

      {data && data.trials.length > 0 && (
        <>
          <div className="section-title">Пробы сессии</div>
          <Card>
            <Segmented value={trial}
                       options={data.trials.map((t) => ({ value: t.trial_id, label: t.label_ru }))}
                       onChange={setTrial} />
          </Card>
          {current && <ReportByStructure figures={figures?.figures ?? []} probe={current.probe_code} />}
          {current && (
            <>
              <div className="section-title">Измеренные значения · {current.label_ru}</div>
              <Card>
                {current.params.length === 0 ? <Empty text="Значений нет" /> : (
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>Параметр</th><th className="num">Значение</th></tr></thead>
                      <tbody>
                        {current.params.map((p) => (
                          <tr key={p.code}>
                            <td>{p.label_ru}<div className="mono">{p.code} · {p.unit}</div></td>
                            <td className="num">{p.value.toFixed(2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            </>
          )}
        </>
      )}
    </>
  );
}

export function SessionView({ sessionId, onBack }: { sessionId: string; onBack: () => void }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [probe, setProbe] = useState<string>("");
  const [interim, setInterim] = useState<string[] | null>(null);
  const [figures, setFigures] = useState<FiguresOut | null>(null);

  useEffect(() => {
    setAnalysis(null);
    setError(null);
    api.analyze(sessionId).then((a) => {
      setAnalysis(a);
      const first = a.result.responses.find((r) => r.pass_no === 1);
      setProbe(first?.probe_code ?? "");
    }).catch((e) => setError(e.message));
    // Иллюстрации отчёта DIERS относятся к пробе, а не к анализу, и грузятся
    // отдельно: их отсутствие — свойство формата выгрузки, а не ошибка.
    api.figures(sessionId).then(setFigures).catch(() => setFigures(null));
  }, [sessionId]);

  if (error) {
    return (
      <>
        <div className="row" style={{ marginBottom: 12 }}>
          <button className="pill" onClick={onBack}>‹ Обзор</button>
        </div>
        <h1 className="title">Сессия без анализа</h1>
        <WithoutAnalysis sessionId={sessionId} reason={error} />
      </>
    );
  }
  if (!analysis) return <><h1 className="title">Анализ</h1><Empty text="Считаю…" /></>;

  const r = analysis.result;
  const selected = r.responses.find((x) => x.probe_code === probe && x.pass_no === 1);

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className="pill" onClick={onBack}>‹ Обзор</button>
        <span className="spacer" />
        <span className="badge accent">{r.index_kind}</span>
        <span className="mono">hash {analysis.input_hash.slice(0, 12)}</span>
      </div>

      <h1 className="title">Анализ сессии</h1>
      <p className="subtitle">
        {r.index_kind === "RI"
          ? "Индекс отзывчивости RI: опирается на собственную нейтраль пациента, норм не требует. Популяционная норма не должна быть входом для оценки отклика."
          : "Постуральный индекс PI: нормы заданы, отклонение считается от популяции."}
      </p>

      {r.warnings.map((w) => <Banner key={w} text={w} />)}

      <div className="grid cols-4">
        <Tile label="Дрейф нейтрали, остаток"
              value={r.drift.residual === null ? "—" : r.drift.residual.toFixed(2)}
              tone={r.low_confidence ? "warn" : undefined}
              hint={r.drift.computable
                ? "в единицах SDC, после линейной поправки"
                : r.drift.reason ?? "не вычислен"} />
        <Tile label="Шорт-лист" value={r.shortlist.length}
              tone={r.shortlist.length ? "good" : undefined}
              hint="улучшающие, подтверждённые вторым проходом" />
        <Tile label="Ухудшение" value={r.notable_worsening.length}
              tone={r.notable_worsening.length ? "bad" : undefined}
              hint="в рекомендации не идут никогда" />
        <Tile label="Отклик без знака" value={r.responsive_unsigned.length}
              hint="величина есть, направление не установлено" />
      </div>

      <div className="section-title">Отклики проб · единая шкала Δ{r.index_kind}</div>
      <Card>
        <ResponseChart items={r.responses.map((x) => ({
          probe_code: x.probe_code, delta: x.delta_index,
          confidence: x.confidence, direction_known: x.direction_known, pass_no: x.pass_no,
        }))} />
        <div className="row" style={{ marginTop: 14, gap: 8 }}>
          {r.shortlist.map((c) => <span key={c} className="badge good">шорт-лист · {c}</span>)}
          {r.notable_worsening.map((c) => <span key={c} className="badge bad">ухудшение · {c}</span>)}
          {r.responsive_unsigned.map((c) => <span key={c} className="badge neutral">без знака · {c}</span>)}
          {r.in_noise.map((c) => <span key={c} className="badge">в шуме · {c}</span>)}
        </div>
      </Card>

      <div className="section-title">Положение челюсти, меняющее позу</div>
      <Card>
        {(() => {
          const mand = r.responses.filter(
            (x) => x.pass_no === 1 && x.probe_code.startsWith("MAND_"));
          if (mand.length === 0) {
            return <Empty text="В сессии нет проб положения нижней челюсти." />;
          }
          const moving = mand.filter(
            (x) => x.delta_index !== null && Math.abs(x.delta_index) >= r.threshold);
          const sorted = [...mand].sort(
            (a, b) => Math.abs(b.delta_index ?? 0) - Math.abs(a.delta_index ?? 0));
          return (
            <>
              <p className="tile-hint" style={{ marginTop: 0 }}>
                {moving.length === 0
                  ? `Ни одно из ${mand.length} положений не сдвинуло позу выше порога.`
                  : `Позу меняют ${moving.length} положения из ${mand.length}.`}
                {" "}Значимо — |Δ{r.index_kind}| ≥ {r.threshold} SDC: сдвиг больше
                собственного разброса повторного измерения.
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Положение челюсти</th><th className="num">Δ{r.index_kind}</th>
                      <th>Оценка</th><th>Достоверность</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((x) => {
                      const d = x.delta_index;
                      const big = d !== null && Math.abs(d) >= r.threshold;
                      const verdict = !big ? "в пределах шума"
                        : !x.direction_known ? "меняет позу, знак не установлен"
                        : d! < 0 ? "поза улучшается" : "поза ухудшается";
                      return (
                        <tr key={x.probe_code + x.pass_no}
                            className={big ? "row-accent" : undefined}>
                          <td>
                            {x.probe_code.replace(/^MAND_/, "")}
                            <div className="mono">{x.probe_code}</div>
                          </td>
                          <td className="num">{d === null ? "—" : d.toFixed(2)}</td>
                          <td>{verdict}</td>
                          <td className="tile-hint">
                            {x.confidence}
                            {x.confirmed ? " · подтверждено вторым проходом" : ""}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="tile-hint">
                Оценка описывает измеренный отклик, а не назначение. Проба без
                установленного направления не попадает ни в улучшения, ни в
                ухудшения: назначить ей знак нечем (Р-18).
              </p>
            </>
          );
        })()}
      </Card>

      <div className="section-title">Параметры выбранной пробы</div>
      <Card>
        <div className="row" style={{ marginBottom: 14 }}>
          <Segmented value={probe}
                     options={r.responses.filter((x) => x.pass_no === 1)
                       .map((x) => ({ value: x.probe_code, label: x.probe_code.replace(/^(MAND|PODAL|CTRL)_/, "") }))}
                     onChange={setProbe} />
        </div>
        {selected ? (
          <>
            <div className="grid cols-3" style={{ marginBottom: 16 }}>
              <Tile label={`Δ${selected.index_kind} · поза`}
                    value={selected.delta_index === null ? "—" : selected.delta_index.toFixed(2)}
                    hint="постуральный отклик от нейтрали, в единицах SDC" />
              <Tile label="ΔMI · мышца"
                    value={selected.delta_muscle === null ? "не измерено"
                           : selected.delta_muscle.toFixed(2)}
                    hint="отдельный сигнал §9.5, в индекс не суммируется" />
              <Tile label="ΔSI · сила"
                    value={selected.delta_strength === null ? "не измерено"
                           : selected.delta_strength.toFixed(2)}
                    hint="myoline под пробой (Р-41); направление не установлено" />
            </div>
            <div className="chart-scroll"><DeltaChart params={selected.params} /></div>
            <div className="table-wrap" style={{ marginTop: 18 }}>
              <table>
                <thead>
                  <tr>
                    <th>Параметр</th><th className="num">Нейтраль</th><th className="num">Проба</th>
                    <th className="num">SDC</th><th className="num">Эффект</th><th>Δ</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.params.map((p) => (
                    <tr key={p.code}>
                      <td>
                        {p.label_ru}
                        <div className="mono">{p.code} · {p.unit}</div>
                      </td>
                      <td className="num">{p.baseline.toFixed(2)}</td>
                      <td className="num">{p.value.toFixed(2)}</td>
                      {/* MUST §14.2.5: норма показывается только там, где определена.
                          Для SDC — прочерк, если порог не откалиброван. */}
                      <td className="num">{p.sdc === null ? "—" : p.sdc.toFixed(2)}</td>
                      <td className="num">{p.effect_size === null ? "—" : p.effect_size.toFixed(2)}</td>
                      <td>
                        <DeltaBadge delta={p.delta} confidence={p.confidence}
                                    interpretation={p.interpretation} direction={p.direction} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <Empty text={r.responses.length === 0
            ? "Откликов в сессии нет: сравнивать пробы не с чем — записана "
              + "только нейтраль. Это не пустой результат, а отсутствие второго "
              + "члена сравнения; измеренное показано ниже."
            : "Проба не выбрана"} />
        )}
      </Card>

      {/* Иллюстрации прибора — под той же пробой, что и её числа. Отчёт DIERS
          читают картинкой: держать её на отдельном экране значит заставлять
          сверять позвоночник и таблицу по памяти.
          Когда откликов нет (в сессии одна нейтраль), пробы для фильтра тоже
          нет — тогда показываются все листы сессии: иллюстрации существуют
          независимо от того, удалось ли построить сравнение. */}
      {(figures?.figures.length ?? 0) > 0 && (
        <ReportByStructure figures={figures!.figures} probe={selected?.probe_code} />
      )}

      <div className="section-title">Подтверждающий повтор</div>
      <Card>
        <p className="tile-hint" style={{ marginTop: 0 }}>
          Промежуточный расчёт отдаёт только коды проб к повтору — без величин, размеров
          эффекта и направления. Иначе слепота разбора качества снимается до его закрытия:
          тот, кто видит величины откликов, уже знает, какая проба «сработала».
        </p>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="pill" onClick={() => api.interim(sessionId).then((x) => setInterim(x.probe_codes))}>
            Рассчитать пробы к повтору
          </button>
          {interim?.map((c) => <span key={c} className="badge accent">{c}</span>)}
          {interim?.length === 0 && <span className="muted">нет проб выше порога</span>}
        </div>
      </Card>
    </>
  );
}
