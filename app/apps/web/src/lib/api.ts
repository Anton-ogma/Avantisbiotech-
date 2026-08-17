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

/** Страница открыта как автономный снимок: бэкенда нет вовсе.
 *  Экраны, которые ПИШУТ (загрузка файлов, утверждение плана), обязаны это
 *  проверять и говорить прямо, а не выдавать сетевую ошибку за отказ прибора. */
export const isSnapshot = (): boolean => snapshot() !== null;

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
  /** ΔMI и ΔSI — мышечный и силовой сигналы §9.5. В delta_index не входят. */
  delta_muscle: number | null; delta_strength: number | null;
}

export interface AnalysisResult {
  session_id: string; index_kind: "RI" | "PI"; versions: Record<string, string>;
  input_hash: string; baseline: Record<string, number>;
  drift: {
    raw: number | null; residual: number | null; worst_param: string | null;
    computable: boolean; reason: string | null;
  };
  low_confidence: boolean; responses: ProbeResponse[];
  /** Порог значимости в единицах SDC: «значимо» без него — слово без содержания. */
  threshold: number;
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
  muscles: () => call<{ version: string; muscles: MuscleInfo[]; note: string }>("/emg/muscles"),
  montageTemplates: () =>
    call<{ version: string; montages: MontageTemplate[]; note: string }>("/emg/montages"),
  sessionMontage: (id: string) =>
    call<{ session_id: string; montage: MontageOut | null; note?: string }>(
      `/sessions/${id}/montage`),
  bleProfiles: () =>
    call<{ version: string; profiles: BleProfile[]; note: string }>("/devices/ble-profiles"),
  bleCapture: (id: string, body: {
    trial_id: string; profile: string; channels: Record<string, number[]>;
    timestamps_ms?: number[]; device_serial?: string;
  }) => call<BleCaptureOut>(`/sessions/${id}/ble-capture`, {
    method: "POST", body: JSON.stringify(body),
  }),
  saveTemplate: (body: {
    code: string; label_ru: string; purpose: string;
    channels: { muscle: string; side: string }[];
  }) => call<{ template: MontageTemplate; warnings: string[] }>("/emg/montages", {
    method: "POST", body: JSON.stringify(body),
  }),
  archiveTemplate: (code: string) =>
    call<{ code: string; archived: boolean; note: string }>(`/emg/montages/${code}`, {
      method: "DELETE",
    }),
  setMontage: (id: string, body: {
    template: string | null;
    channels: { label: string; muscle: string; side: string }[];
    note: string;
  }) => call<{ montage: MontageOut; warnings: string[] }>(`/sessions/${id}/montage`, {
    method: "PUT", body: JSON.stringify(body),
  }),
  autoIngest: async (id: string, files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const a = getActor();
    if (isSnapshot()) {
      throw new Error(
        "Это автономный снимок приложения: он показывает уже загруженные данные, " +
        "но принимать файлы ему некуда — бэкенда рядом нет. Загрузка работает в " +
        "развёрнутом экземпляре (docker compose up).",
      );
    }
    const res = await fetch(`${BASE}/sessions/${id}/auto-ingest`, {
      method: "POST", body: form,
      headers: { "X-Actor-Ref": a.ref, "X-Actor-Role": a.role },
    });
    // Ответ может оказаться и не JSON: перед API стоит прокси, и 404/502 от
    // него приходят страницей. res.json() на ней падает SyntaxError, и
    // пользователь видит «Unexpected token <» вместо причины.
    const raw = await res.text();
    let body: any = null;
    try { body = raw ? JSON.parse(raw) : null; } catch { body = null; }
    if (!res.ok || body === null) {
      throw new Error(
        typeof body?.detail === "string" ? body.detail
        : `сервер ответил ${res.status} ${res.statusText || ""}`.trim()
          + (body === null && raw ? " и не JSON — похоже, запрос не дошёл до API" : ""),
      );
    }
    return body as IngestReport;
  },
};

export interface Signal { available: boolean; delta: number | null; reliable: boolean; detail: string }
export interface ProbeSynthesis {
  probe_code: string; label_ru: string; group?: string; role?: string;
  posture: Signal; joint: Signal; muscle: Signal; strength: Signal;
  /** Тот же отклик по режимам: стоя и при ходьбе — разные измерения позы. */
  posture_static?: Signal; posture_dynamic?: Signal;
  coherence: string; verdict: string; verdict_ru: string; rationale: string;
  excursion: { status: string; delta_mm: number | null; message: string } | null;
  strength_params: { code: string; label_ru: string; delta: number; effect_size: number | null;
                     confidence: Confidence; direction: Direction;
                     interpretation: "improving" | "worsening" | null }[];
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
  threshold?: number; thresholds_are_demo?: boolean;
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
  /** Структуры со страницы отчёта: spine, pelvis, feet, knee. */
  structures: string[]; page: number;
  data_uri: string | null; url: string;
}
export interface FiguresOut {
  session_id: string; figures: FigureOut[]; truncated: number;
  structures?: string[]; note: string;
}

/** Каталог мышц ЭМГ. `surface: false` — мышца существует, но поверхностными
 *  электродами не снимается: подписать ею канал нельзя, и причина сказана. */
export interface MuscleInfo {
  code: string; label_ru: string; latin: string; region: string;
  surface: boolean; note: string; aliases: string[];
}
export interface MontageChannelOut {
  label: string; muscle: string; muscle_label_ru?: string; side: string;
  param_code?: string;
}
export interface MontageGroup {
  muscle: string; side: string; muscle_label_ru: string; region: string;
}
export interface MontageTemplate {
  code: string; label_ru: string; purpose: string;
  channels: MontageChannelOut[]; channel_count: number;
  /** false — свой шаблон клиники, а не поставляемый с платформой. */
  builtin?: boolean; created_by?: string; groups?: MontageGroup[];
}
export interface MontageOut {
  id: string; template: string | null; note: string; set_by: string;
  created_at: string; channels: MontageChannelOut[];
}

/** GATT-профиль датчика ЭМГ. verified=false — на железе не проверен: ошибка в
 *  unit_scale_uv даёт правдоподобные, но неверные микровольты. */
export interface BleProfile {
  code: string; label_ru: string; vendor: string; verified: boolean; note: string;
  service_uuid: string; data_characteristic: string; control_characteristic: string | null;
  sample_format: string; channels_per_packet: number; channel_order: string[];
  fs_hz: number; unit_scale_uv: number;
}
export interface BleCaptureOut {
  status: string; import_id?: string; probe_code?: string;
  fs_declared?: number; fs_actual?: number | null; duration_sec?: number;
  params?: Record<string, number>;
  channels?: { label: string; rms_uv: number; peak_uv: number; snr_db: number | null;
               mains_share_db: number | null; samples: number; flags: string[] }[];
  unmapped?: string[]; quality_flags?: string[]; note?: string; reason?: string;
}
