import { useEffect, useState } from "react";
import { api, type ParamInfo } from "../lib/api";
import { Card, Empty, Tile } from "../components/ui";

const DIRECTION_RU: Record<string, string> = {
  two_sided: "двустороннее", higher_worse: "рост хуже",
  lower_worse: "снижение хуже", unknown: "не установлено",
};

export function Params() {
  const [params, setParams] = useState<ParamInfo[]>([]);
  useEffect(() => { api.params().then(setParams).catch(() => {}); }, []);
  const unknown = params.filter((p) => p.direction === "unknown").length;

  return (
    <>
      <h1 className="title">Реестр параметров</h1>
      <p className="subtitle">
        Направление «лучше/хуже» — параметр исследования, а не константа. Новый параметр
        заводится со значением «не установлено» и входит в индекс по модулю. Смена на
        определённое направление требует ссылки на подтверждающий анализ: так результат
        исследования попадает в продукт, а не правкой конфигурации.
      </p>

      <div className="grid cols-3">
        <Tile label="Всего параметров" value={params.length} />
        <Tile label="Направление не установлено" value={unknown}
              hint="входят в индекс по модулю, красятся нейтрально" />
        <Tile label="С откалиброванным SDC" value={params.filter((p) => p.sdc !== null).length} />
      </div>

      <Card style={{ marginTop: 14 }}>
        {!params.length ? <Empty text="Загрузка…" /> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Параметр</th><th>Домен</th><th>Направление</th>
                    <th className="num">SDC</th><th>Норма</th><th>В индексе</th></tr>
              </thead>
              <tbody>
                {params.map((p) => (
                  <tr key={p.code}>
                    <td>{p.label_ru}<div className="mono">{p.code} · {p.unit}</div></td>
                    <td><span className="badge neutral">{p.domain}</span></td>
                    <td>
                      <span className={`badge ${p.direction === "unknown" ? "" : "accent"}`}>
                        {DIRECTION_RU[p.direction]}
                      </span>
                      {p.direction_evidence && <div className="mono">{p.direction_evidence}</div>}
                    </td>
                    <td className="num">{p.sdc?.toFixed(2) ?? "—"}</td>
                    {/* §14.2.5: норма показывается только там, где определена */}
                    <td>{p.norm_defined ? <span className="badge good">задана</span> : <span className="muted">—</span>}</td>
                    <td>{p.in_pi ? "да" : <span className="muted">структурный</span>}</td>
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
