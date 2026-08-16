/** Клиент API. Типы соответствуют packages/contracts (§3 ТЗ: единственный
 *  источник — Pydantic-модели; `make types` регенерирует этот файл). */

const BASE = (import.meta as any).env?.VITE_API_BASE ?? "/api";

/** Актор передаётся заголовками: аутентификация — на стороне хоста, ПДн внутрь
 *  модуля не попадают (Р-9). */
export type Role = "operator" | "clinician" | "methodologist" | "coach" | "admin";
let actor = { ref: "clinician-1", role: "clinician" as Role };
export const setActor = (ref: string, role: Role) => { actor = { ref, role }; };
export const getActor = () => actor;

/** Статический снимок для автономного просмотра: страница, опубликованная без
 *  бэкенда, читает данные отсюда. Контур замкнут — внешних запросов нет (Р-23). */
const snapshot = (): Record<string, unknown> | null =>
  (globalThis as any).__DIERS_SNAPSHOT__ ?? null;

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const snap = snapshot();
  if (snap && path in snap) return snap[path] as T;
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Actor-Ref": actor.ref,
      "X-Actor-Role": actor.role,
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? res.statusText),
    );
  }
  return res.json() as Promise<T>;
}

export type Direction = "two_sided" | "higher_worse" | "lower_worse" | "unknown";
export type Confidence = "noise" | "probable" | "reliable" | "undefined";

export interface Platform {
  intended_use: "research" | "clinical";
  registration_number: string | null;
  versions: Record<string, string>;
  protocol_version: string;
  thresholds_are_demo: boolean;
  norms_defined: boolean;
  banners: string[];
}

export interface ParamInfo {
  code: string; label_ru: string; unit: string; domain: string;
  direction: Direction; in_pi: boolean; sdc: number | null;
  norm_defined: boolean; direction_evidence: string | null;
}

export interface SessionOut {
  id: string; patient_ref: string; status: string; study_mode: boolean;
  neutral_definition: string; low_confidence: boolean; started_at: string;
  operator_ref: string; versions: Record<string, string>; protocol_version: string;
  trial_count: number; pass_count: number;
}

export interface ParamEffect {
  code: string; label_ru: string; unit: string; domain: string;
  baseline: number; value: number; delta: number; sdc: number | null;
  effect_size: number | null; confidence: Confidence; direction: Direction;
  interpretation: "improving" | "worsening" | null;
}

export interface ProbeResponse {
  probe_code: string; pass_no: number; delta_index: number | null;
  index_kind: "RI" | "PI"; confidence: Confidence; confirmed: boolean;
  direction_known: boolean; params: ParamEffect[];
}

export interface AnalysisResult {
  session_id: string; index_kind: "RI" | "PI"; versions: Record<string, string>;
  input_hash: string; baseline: Record<string, number>;
  drift: {
    raw: number | null; residual: number | null; worst_param: string | null;
    computable: boolean; reason: string | null;
  };
  low_confidence: boolean; responses: ProbeResponse[];
  shortlist: string[]; notable_worsening: string[];
  responsive_unsigned: string[]; in_noise: string[]; warnings: string[];
}

export interface Analysis {
  id: string; session_id: string; input_hash: string;
  versions: Record<string, string>; index_kind: "RI" | "PI";
  created_at: string; result: AnalysisResult;
}

export interface Passport {
  code: string; label_ru: string; n_subjects: number; n_measurements: number;
  icc: number | null; icc_ci: number[] | null; sem: number | null; sdc: number | null;
  cv_pct: number | null; reliability: string; detectable_at_n30: number | null;
}

export const api = {
  platform: () => call<Platform>("/platform"),
  params: () => call<ParamInfo[]>("/params"),
  sessions: () => call<SessionOut[]>("/sessions"),
  analyze: (id: string) => call<Analysis>(`/sessions/${id}/analyze`, { method: "POST", body: "{}" }),
  interim: (id: string) =>
    call<{ probe_codes: string[]; note: string }>(`/sessions/${id}/interim`, { method: "POST" }),
  repeatability: () =>
    call<{ passports: Passport[]; operator_variance_share: number | null; warning: string | null }>(
      "/research/repeatability",
    ),
  protocolAnalytics: () => call<any>("/research/protocol-analytics"),
  progress: () => call<any>("/research/progress"),
  measurements: (id: string) => call<Measurements>(`/sessions/${id}/measurements`),
  crossmodal: (id: string) => call<CrossModal>(`/sessions/${id}/crossmodal`),
  /** Запрашивается ОДИН раз на сессию и отдаёт все пробы; выбор столбцов —
   *  локальный. Прежняя схема «адрес на каждый набор» упиралась в число
   *  заранее сгенерированных сочетаний и молча ограничивала сравнение. */
  compare: (id: string) => call<CompareOut>(`/sessions/${id}/compare`),
  figures: (id: string) => call<FiguresOut>(`/sessions/${id}/figures`),
  autoIngest: async (id: string, files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const a = getActor();
    const res = await fetch(`${BASE}/sessions/${id}/auto-ingest`, {
      method: "POST", body: form,
      headers: { "X-Actor-Ref": a.ref, "X-Actor-Role": a.role },
    });
    const body = await res.json();
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "ошибка загрузки");
    return body as IngestReport;
  },
};

export interface Signal { available: boolean; delta: number | null; reliable: boolean; detail: string }
export interface ProbeSynthesis {
  probe_code: string; label_ru: string;
  posture: Signal; joint: Signal; muscle: Signal;
  coherence: string; verdict: string; verdict_ru: string; rationale: string;
  excursion: { status: string; delta_mm: number | null; message: string } | null;
  params: { code: string; label_ru: string; delta: number; effect_size: number | null;
            confidence: Confidence; direction: Direction;
            interpretation: "improving" | "worsening" | null }[];
}
export interface CrossModal {
  session_id: string;
  modalities: Record<string, string[]>;
  session_level?: { myoline: Record<string, number>; note: string };
  probes: ProbeSynthesis[];
  ranking: Record<string, string[]>;
  note?: string;
  warning?: string;
}
export interface CompareCell {
  value: number; delta: number | null; effect_size: number | null;
  confidence: Confidence; interpretation: "improving" | "worsening" | null;
}
export interface CompareRow {
  code: string; label_ru: string; unit: string; modality: string; direction: Direction;
  baseline: number | null; sdc: number | null; cells: Record<string, CompareCell>;
}
export interface RegionOut {
  key: string; label_ru: string; hint: string; order: number;
  structural: boolean; rows: CompareRow[];
}
export interface CompareOut {
  session_id: string;
  columns: { code: string; label_ru: string; modality: string }[];
  regions: RegionOut[];
  has_baseline: boolean;
  note: string;
}

export interface IngestFile {
  filename: string; status: string; modality: string | null; format_id: string | null;
  condition_label: string | null; probe_code: string | null; params: number; reason: string | null;
}
export interface IngestReport {
  session_id: string; files: IngestFile[];
  summary: { ingested: number; needs_assignment: number; unrecognized: number; duplicates: number };
}

export interface MeasuredParam {
  code: string; value: number; label_ru: string; unit: string;
  domain: string; modality: string; direction: Direction; in_index: boolean;
}
export interface MeasuredTrial {
  trial_id: string; probe_code: string; label_ru: string; modality: string;
  pass_no: number; quality_flags: string[]; params: MeasuredParam[];
}
export interface Measurements {
  session_id: string; started_at: string; device: string | null; trials: MeasuredTrial[];
}

/** Иллюстрация приборного протокола. `data_uri` приходит вместе с ответом:
 *  контур замкнут, внешних CDN нет, а отдельный запрос за каждой картинкой на
 *  экране сравнения — это десятки round-trip на одну сессию. */
export interface FigureOut {
  id: string; probe_code: string | null; probe_label_ru: string | null;
  format_id: string | null; name: string; kind: "render" | "caption";
  mime: string; width: number; height: number;
  data_uri: string | null; url: string;
}
export interface FiguresOut {
  session_id: string; figures: FigureOut[]; truncated: number; note: string;
}
