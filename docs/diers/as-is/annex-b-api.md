# Приложение Б. Контракт API модуля DIERS

Источник: `server/routes.ts:5690-5915`, `server/doctor_routes.ts:54-88`.

Общее для всех эндпоинтов:

- Аутентификация — `await authenticate(req, res)`; при отказе обработчик выходит,
  ответ формирует сама `authenticate`.
- Клиент читает токен из cookie `fitmed_t` через `document.cookie` и передаёт
  заголовком `Authorization: Bearer <token>`.
- Пациентские эндпоинты **всегда** скоупятся по `user.id` из токена. Передать
  чужой `id` в query нельзя — выборка вернёт пусто/404.
- Ошибки обработчиков: `500 { error: <message> }` (текст исключения).

---

## Б.1 Сводная таблица

| Метод | Путь | Роль | Назначение | Строка |
|---|---|---|---|---|
| GET | `/api/diers/studies` | пациент | список исследований | 5694 |
| POST | `/api/diers/studies` | пациент | создать | 5701 |
| PATCH | `/api/diers/studies/:id` | пациент | обновить | 5712 |
| DELETE | `/api/diers/studies/:id` | пациент | удалить | 5723 |
| POST | `/api/diers/import-csv` | пациент | импорт CSV | 5730 |
| GET | `/api/diers/export` | пациент | выгрузка JSON | 5768 |
| GET | `/api/diers/compare` | пациент | сравнение двух | 5777 |
| POST | `/api/diers/api-sync` | пациент | заглушка DICAM | 5801 |
| GET | `/api/myoline/studies` | пациент | список ЭМГ | 5825 |
| POST | `/api/myoline/studies` | пациент | создать ЭМГ | 5831 |
| DELETE | `/api/myoline/studies/:id` | пациент | удалить ЭМГ | 5840 |
| POST | `/api/myoline/import-csv` | пациент | импорт ЭМГ CSV | 5846 |
| GET | `/api/myoline/export` | пациент | выгрузка ЭМГ | 5887 |
| GET | `/api/myoline/compare` | пациент | сравнение ЭМГ | 5895 |
| GET | `/api/doctor/patient-studies/:patientId` | врач | исследования пациента | dr:55 |
| GET | `/api/doctor/patient-studies/:patientId/diers-compare` | врач | сравнение у врача | dr:69 |

`PATCH` для Myoline отсутствует — редактировать ЭМГ-исследование нельзя.

---

## Б.2 `GET /api/diers/studies`

Список исследований текущего пользователя, `ORDER BY study_date DESC`.
Пагинации нет — отдаётся всё.

**200** — массив строк таблицы целиком (включая `raw_data`).

---

## Б.3 `POST /api/diers/studies`

```jsonc
// Request
{
  "study_date": "2026-03-14",           // строка, как есть; не валидируется
  "device_type": "formetric4d",         // опц., default "formetric4d"
  "title": "После курса",               // опц., default ""
  "spine_params":   { "Kyphosis": "42.3" },   // опц., default {}
  "posture_params": { "COG_X": "0.3" },       // опц., default {}
  "gait_params":    {},                       // опц., default {}
  "raw_data":       {},                       // опц., default {}
  "source": "manual",                   // опц., default "manual"
  "notes": "…"                          // опц., default ""
}
```

**200** — созданная строка (`RETURNING *`).
**500** — `{ error }` при исключении.

Валидации нет: ни обязательности `study_date`, ни проверки формата даты,
ни ограничения `device_type`/`source` доменом, ни фильтрации допустимых ключей
внутри `*_params` — сохраняется любой присланный объект.

---

## Б.4 `PATCH /api/diers/studies/:id`

Обновляемые поля: `title`, `notes`, `spine_params`, `posture_params`,
`gait_params`. Каждое через `COALESCE(?, <поле>)` — `null`/отсутствие означает
«не менять». `study_date`, `device_type`, `source`, `raw_data` неизменяемы.

Скоуп `WHERE id=? AND user_id=?`. Ответ — перечитанная строка **без** скоупа
по пользователю (`SELECT ... WHERE id=?`); при попытке обновить чужую запись
UPDATE ничего не изменит, но в ответ вернётся чужая строка. Учтено как Д-10.

---

## Б.5 `DELETE /api/diers/studies/:id`

Жёсткое удаление, скоуп `id + user_id`. Всегда **200** `{ ok: true }` —
даже если ничего не удалено.

---

## Б.6 `POST /api/diers/import-csv`

`Content-Type: multipart/form-data`, поле `file`, опционально `device_type`.
Правила разбора — [Приложение В](./annex-c-csv-mapping.md).

**200** `{ "imported": 3, "studies": [ … ] }`
**400** `{ "error": "No file" }` — файл не передан
**400** `{ "error": "Empty CSV" }` — меньше двух непустых строк
**500** `{ "error": … }`

Временный файл удаляется через `fs.unlinkSync` **только на успешном пути** —
при исключении остаётся на диске (Д-11).

---

## Б.7 `GET /api/diers/export`

`ORDER BY study_date ASC`, заголовки:

```
Content-Type: application/json
Content-Disposition: attachment; filename="diers_studies_{userId}_{YYYY-MM-DD}.json"
```

Тело — массив строк целиком, включая `raw_data`.

---

## Б.8 `GET /api/diers/compare?id1=&id2=`

Оба исследования выбираются с `AND user_id=?`.

**404** `{ "error": "Study not found" }` — если хотя бы одно не найдено
(в т.ч. когда оно принадлежит другому пользователю).

**200:**

```jsonc
{
  "study1": { "id": 12, "date": "2026-01-10", "title": "Исходное" },
  "study2": { "id": 17, "date": "2026-03-14", "title": "После курса" },
  "spine": {
    "Kyphosis":  { "v1": "45.1", "v2": "42.3", "delta": -2.8, "direction": "↓" },
    "Scoliosis": { "v1": "1.4",  "v2": "2.1",  "delta": 0.7,  "direction": "↑" },
    "VP":        { "v1": "C7",   "v2": "C7",   "delta": null, "direction": "—" }
  },
  "posture": { /* та же форма */ },
  "gait":    { /* та же форма */ }
}
```

Правила:

- Ключи — объединение ключей обоих исследований; отсутствующее значение → `"—"`.
- `delta = +(v2 - v1).toFixed(2)`, считается только если оба `parseFloat` дали число.
- Непарсибельное значение → `delta: null`, `direction: "—"`.
- `direction`: `↑` при `delta > 0`, `↓` при `delta < 0`, `=` при нуле.

---

## Б.9 `POST /api/diers/api-sync` — заглушка

```jsonc
// Request
{ "host": "192.168.1.100", "port": 8080, "patient_id": "demo" }
```

**400** без `host`:
`{ "error": "host required", "docs": "Provide DICAM server host/IP and patient_id …" }`

**200:**

```jsonc
{
  "status": "stub",
  "message": "DIERS DICAM не имеет публичного REST API. Интеграция возможна через: …",
  "integration_options": [
    { "method": "CSV Export",       "status": "available",         "description": "…" },
    { "method": "HL7 FHIR",         "status": "requires_setup",    "description": "…" },
    { "method": "DICAM Plugin API", "status": "requires_license",  "description": "…" }
  ],
  "sample_payload": {
    "study_date": "2026-08-16",
    "device": "DIERS formetric 4D",
    "spine_params": {
      "Kyphosis": 42.3, "Lordosis": 38.7, "Scoliosis": 2.1,
      "Trunk_Imbalance": 5.2, "Pelvis_Tilt": 1.8, "Sacrum_Inclination": 29.4,
      "VP": "C7", "TP": "T6", "LP": "L1"
    },
    "posture_params": { "COG_X": 0.3, "COG_Y": 12.4, "Trunk_Flex": -1.2, "Lat_Dev": 3.1 }
  }
}
```

Сетевого обращения к `host` не происходит: `host`/`port`/`patient_id` не
используются нигде, кроме проверки на пустоту. UI (`DiersModule.tsx`, вкладка
«API DICAM») ожидает `status === "ok"` для зелёного состояния — его заглушка
не возвращает никогда.

---

## Б.10 Myoline

Форма запросов аналогична DIERS. Отличия:

- `POST /api/myoline/studies` принимает `emg_channels` (массив объектов),
  `muscle_groups` (массив строк), `analysis_results` (объект).
- `GET /api/myoline/compare` возвращает **плоский массив** `channels`,
  а не три секции:

```jsonc
{
  "study1": { "id": 4, "date": "2026-01-10", "title": "ЭМГ покой" },
  "study2": { "id": 9, "date": "2026-03-14", "title": "ЭМГ покой" },
  "channels": [
    { "muscle": "Erector Spinae L", "v1": "38.2", "v2": "41.0",
      "delta": 2.8, "unit": "µV", "direction": "↑" }
  ]
}
```

Отсутствующий в одном исследовании канал: `v = "—"`, но в дельту он входит как
`parseFloat(undefined || '0') = 0`, то есть отсутствие канала трактуется как
нулевая активность. Учтено как Д-12.

---

## Б.11 Врачебные эндпоинты

### `GET /api/doctor/patient-studies/:patientId`

Проверки по порядку:
1. `authenticate`;
2. `user.role ∈ {doctor, admin}`, иначе **403** `{ error: "Только для врачей" }`;
3. пациент есть среди `storage.getProviderBookings(user.id)`, иначе
   **403** `{ error: "Пациент не в вашем списке" }`.

**200** `{ "diers": [...], "myoline": [...] }` — обе выборки `ORDER BY study_date DESC`,
столбцы перечислены явно, `raw_data` **не отдаётся**.

### `GET /api/doctor/patient-studies/:patientId/diers-compare?id1=&id2=`

Формат ответа идентичен `/api/diers/compare`, но скоуп — `patientId`, а не врач.
**404** `{ error: "Исследование не найдено" }`.

> **Проверка роли есть, проверки «пациент мой» — нет.** В отличие от
> `/patient-studies/:patientId`, здесь связь врач–пациент не проверяется:
> любой пользователь с ролью `doctor` может сравнить исследования произвольного
> пациента, зная `patientId` и пару `id`. Учтено как Д-13.

Клиент этот эндпоинт **не вызывает** — см. Д-02.
