import { useEffect, useState } from "react";
import { api, type Analysis } from "../lib/api";
import { DeltaChart, ResponseChart } from "../components/DeltaChart";
import { Banner, Card, DeltaBadge, Empty, Segmented, Tile } from "../components/ui";

export function SessionView({ sessionId, onBack }: { sessionId: string; onBack: () => void }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [probe, setProbe] = useState<string>("");
  const [interim, setInterim] = useState<string[] | null>(null);

  useEffect(() => {
    setAnalysis(null);
    api.analyze(sessionId).then((a) => {
      setAnalysis(a);
      const first = a.result.responses.find((r) => r.pass_no === 1);
      setProbe(first?.probe_code ?? "");
    }).catch((e) => setError(e.message));
  }, [sessionId]);

  if (error) return <><h1 className="title">Анализ</h1><Banner text={error} /></>;
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
        ) : <Empty text="Проба не выбрана" />}
      </Card>

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
