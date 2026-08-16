# Приложение А. Модель данных модуля DIERS

Источник: `shared/schema.ts:1658-1690`, `drizzle/migrations/0014_sync_missing_tables.sql:122-135, 361, 370`.

---

## А.1 Замечание о стеке

Таблицы объявлены как `pgTable` (PostgreSQL), но код обращается к ним через
обёртку `sqlite.prepare(...)` — след миграции SQLite → Postgres. Из комментария
авторов схемы (`shared/schema.ts:1650-1657`):

- **FK намеренно отсутствуют.** Добавление `references()` сгенерировало бы
  `ALTER TABLE ADD CONSTRAINT`, который упадёт на осиротевших строках в проде.
- **JSON-поля объявлены как `text`.** Код кладёт `JSON.stringify(...)`, читает
  `JSON.parse(...)`.
- **Календарные даты — `text`**, а не `date`, ради совместимости с уже
  применёнными миграциями.

Следствия: нет каскадного удаления при удалении пользователя; нет валидации
`user_id` на уровне БД; нет запросов по значению отдельного параметра.

---

## А.2 Таблица `diers_studies`

```sql
CREATE TABLE IF NOT EXISTS "diers_studies" (
  "id"             serial PRIMARY KEY NOT NULL,
  "user_id"        integer NOT NULL,
  "study_date"     text,
  "device_type"    text DEFAULT 'formetric4d',
  "title"          text,
  "spine_params"   text,
  "posture_params" text,
  "gait_params"    text,
  "raw_data"       text,
  "source"         text DEFAULT 'manual',
  "notes"          text,
  "created_at"     timestamp DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "diers_studies_user_date_idx"
  ON "diers_studies" USING btree ("user_id","study_date");
```

| Поле | Тип | Null | Default | Инвариант / примечание |
|---|---|---|---|---|
| `id` | serial | нет | — | PK |
| `user_id` | integer | нет | — | пациент-владелец; FK нет |
| `study_date` | text | да | — | `YYYY-MM-DD`; при импорте без даты — сегодня |
| `device_type` | text | да | `formetric4d` | домен: `formetric4d`, `formetric3d` |
| `title` | text | да | `''` из API | пустая строка, не NULL, при создании через API |
| `spine_params` | text/JSON | да | `'{}'` | плоский объект `ключ → строка` |
| `posture_params` | text/JSON | да | `'{}'` | то же |
| `gait_params` | text/JSON | да | `'{}'` | то же; вручную не заполняется |
| `raw_data` | text/JSON | да | `'{}'` | полный CSV-ряд при импорте |
| `source` | text | да | `manual` | домен: `manual`, `csv_import` |
| `notes` | text | да | `''` | свободный текст |
| `created_at` | timestamp | да | `now()` | |

**Домены не выражены в БД** — `device_type` и `source` контролируются только
кодом. Уникальности «один пациент — одна дата» нет: дубликаты возможны и
допускаются (повторный импорт того же файла создаст копии).

---

## А.3 Структура JSON-параметров DIERS

Все значения хранятся **строками** — так, как пришли из формы или CSV.
Числами становятся только при сравнении (`parseFloat`). Единицы измерения
в данных не хранятся; они зашиты в подписи полей UI.

### spine_params — позвоночник

| Ключ | Расшифровка | Ед. | Форма ввода |
|---|---|---|---|
| `Kyphosis` | грудной кифоз | ° | да |
| `Lordosis` | поясничный лордоз | ° | да |
| `Scoliosis` | сколиотическая деформация | ° | да |
| `Trunk_Imbalance` | дисбаланс туловища | мм | да |
| `Pelvis_Tilt` | наклон таза | ° | да |
| `Sacrum_Inclination` | инклинация крестца | ° | да |
| `VP`, `VP_SD` | Vertebra Prominens (C7) + SD | — / мм | только CSV |
| `TP`, `TP_SD` | Thoracic Point (вершина кифоза) + SD | — / мм | только CSV |
| `LP`, `LP_SD` | Lumbar Point (вершина лордоза) + SD | — / мм | только CSV |
| `KA`, `KA_SD` | Kyphotic Angle + SD | ° | только CSV |
| `LA`, `LA_SD` | Lordotic Angle + SD | ° | только CSV |

`VP`/`TP`/`LP` в примере полезной нагрузки заглушки api-sync приходят как
буквенные обозначения позвонков (`"C7"`, `"T6"`, `"L1"`) — то есть нечисловые.
При сравнении такие значения дают `delta = null`, `direction = "—"`.

### posture_params — постура

| Ключ | Расшифровка | Ед. | Форма ввода |
|---|---|---|---|
| `COG_X` | центр тяжести, отклонение по X | мм | да |
| `COG_Y` | центр тяжести, отклонение по Y | мм | да |
| `Trunk_Flex` | наклон туловища | ° | да |
| `Lat_Dev` | боковое отклонение | мм | да |
| `Rot_Asym` | ротационная асимметрия | ° | только CSV |
| `Shoulder_Tilt` | перекос плеч | ° | только CSV |
| `Hip_Tilt` | перекос таза | ° | только CSV |

### gait_params — походка

`Step_Length`, `Stride_Width`, `Cadence`, `Speed`, `Stance_Phase`, `Swing_Phase`.
Заполняются **только** импортом CSV; в форме ручного ввода отсутствуют,
при ручном создании сохраняется `{}`.

---

## А.4 Таблица `myoline_studies`

```sql
CREATE TABLE IF NOT EXISTS "myoline_studies" (
  "id"               serial PRIMARY KEY NOT NULL,
  "user_id"          integer NOT NULL,
  "study_date"       text,
  "title"            text,
  "emg_channels"     text,   -- JSON array
  "muscle_groups"    text,   -- JSON array
  "analysis_results" text,   -- JSON
  "raw_data"         text,   -- JSON
  "source"           text DEFAULT 'manual',
  "notes"            text,
  "created_at"       timestamp DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "myoline_studies_user_date_idx"
  ON "myoline_studies" USING btree ("user_id","study_date");
```

Канал ЭМГ:

```json
{ "name": "Erector Spinae L", "raw_value": "42.7", "unit": "µV" }
```

`muscle_groups` — производный массив имён мышц (дублирует `name` из каналов).
`analysis_results` заполняется пустым объектом и **нигде не рассчитывается** —
поле зарезервировано под будущий анализ (асимметрия L/R, коэффициенты
ко-активации). В UI не отображается.

Штатный набор — 12 каналов, 6 пар:

| Пара | Мышца |
|---|---|
| `Erector Spinae L/R` | выпрямитель спины |
| `Quadratus Lumborum L/R` | квадратная мышца поясницы |
| `Gluteus Maximus L/R` | большая ягодичная |
| `Rectus Femoris L/R` | прямая мышца бедра |
| `Tibialis Ant L/R` | передняя большеберцовая |
| `Gastrocnemius L/R` | икроножная |

---

## А.5 Пример записи

```json
{
  "id": 17,
  "user_id": 42,
  "study_date": "2026-03-14",
  "device_type": "formetric4d",
  "title": "После курса реабилитации",
  "spine_params": "{\"Kyphosis\":\"42.3\",\"Lordosis\":\"38.7\",\"Scoliosis\":\"2.1\",\"Trunk_Imbalance\":\"5.2\",\"Pelvis_Tilt\":\"1.8\",\"Sacrum_Inclination\":\"29.4\"}",
  "posture_params": "{\"COG_X\":\"0.3\",\"COG_Y\":\"12.4\",\"Trunk_Flex\":\"-1.2\",\"Lat_Dev\":\"3.1\"}",
  "gait_params": "{}",
  "raw_data": "{}",
  "source": "manual",
  "notes": "Жалобы на боль в пояснице уменьшились",
  "created_at": "2026-03-14T09:12:44.000Z"
}
```

---

## А.6 Рекомендации по эволюции схемы

1. `text` → `jsonb` для четырёх JSON-полей + GIN-индекс — открывает когортные
   запросы («все пациенты со `Scoliosis` > 10°») и агрегаты без выгрузки в приложение.
2. Хранить единицы измерения рядом со значением либо ввести справочник параметров
   (`code`, `label_ru`, `unit`, `norm_min`, `norm_max`, `direction_is_good`) —
   это же снимает Д-03 (локализация) и Д-04 (окраска дельты).
3. Числовые значения хранить числами; строки оставить только для нечисловых
   маркеров вроде `VP = "C7"`.
4. Уникальный индекс `(user_id, study_date, device_type, source)` либо хеш
   `raw_data` — защита от повторного импорта одного файла.
