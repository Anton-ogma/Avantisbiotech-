import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Banner, Card, Empty, Tile } from "../components/ui";

/** Слой 2 аналитики: платформа изучает СОБСТВЕННЫЙ протокол.
 *  settle_sec и carryover_min в реестре — назначенные числа и непроверенные
 *  допущения; здесь они калибруются по накопленным данным. */
export function Protocol() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.protocolAnalytics().then(setData).catch((e) => setError(e.message)); }, []);

  return (
    <>
      <h1 className="title">Аналитика протокола</h1>
      <p className="subtitle">
        Метод — единственное, что здесь полностью под вашим контролем. Выдержка и отмывка
        заданы числами, которые никто не проверял; урожайность показывает, какие пробы
        стоят времени пациента, а какие нет.
      </p>
      {error && <Banner text={error} />}

      <div className="grid cols-3">
        <Tile label="Доля сессий low_confidence"
              value={data?.low_confidence_share === null || data?.low_confidence_share === undefined
                ? "—" : `${(data.low_confidence_share * 100).toFixed(0)}%`} />
        <Tile label="Отклонений от плана"
              value={data?.deviation_summary?.reduce((a: number, d: any) => a + d.count, 0) ?? "…"}
              hint="ГОСТ Р ИСО 14155: прослеживаемость" />
        <Tile label="Проб в анализе урожайности" value={data?.yield_by_probe?.length ?? "…"} />
      </div>

      <div className="section-title">Урожайность протокола</div>
      <Card>
        {!data?.yield_by_probe?.length ? <Empty text="Недостаточно проанализированных сессий" /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Проба</th><th className="num">Всего</th><th className="num">Интерпретируемых</th><th className="num">Урожайность</th><th>Вывод</th></tr></thead>
              <tbody>
                {data.yield_by_probe.map((y: any) => (
                  <tr key={y.probe_code}>
                    <td className="mono">{y.probe_code}</td>
                    <td className="num">{y.total}</td>
                    <td className="num">{y.interpretable}</td>
                    <td className="num">{y.yield_pct}%</td>
                    <td>
                      <span className={`badge ${y.yield_pct >= 50 ? "good" : y.yield_pct >= 20 ? "neutral" : "bad"}`}>
                        {y.yield_pct >= 50 ? "оставить" : y.yield_pct >= 20 ? "наблюдать" : "кандидат на исключение"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="section-title">Калибровка выдержки и отмывки</div>
      <Card>
        <p className="tile-hint" style={{ marginTop: 0 }}>
          Если средний отклик при выдержке ниже назначенной сопоставим с откликом при
          выдержке от назначенной — назначенное значение избыточно, и сессию можно
          сократить. Это прямая экономия времени пациента и стоимости набора.
        </p>
        {!data?.settle_calibration?.length && !data?.carryover_calibration?.length ? (
          <Empty text="Нужно ≥3 наблюдений на пробу" />
        ) : (
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead><tr><th>Проба</th><th>Параметр</th><th className="num">Назначено</th><th className="num">Отклик ниже</th><th className="num">Отклик от нормы</th><th className="num">n</th></tr></thead>
              <tbody>
                {[...(data.settle_calibration ?? []).map((x: any) => ({ ...x, kind: "выдержка" })),
                  ...(data.carryover_calibration ?? []).map((x: any) => ({ ...x, kind: "отмывка" }))].map((x: any, i: number) => (
                  <tr key={i}>
                    <td className="mono">{x.probe_code}</td>
                    <td>{x.kind}</td>
                    <td className="num">{x.assigned} {x.unit}</td>
                    <td className="num">{x.mean_below?.toFixed(2) ?? "—"}</td>
                    <td className="num">{x.mean_at_or_above?.toFixed(2) ?? "—"}</td>
                    <td className="num">{x.n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
