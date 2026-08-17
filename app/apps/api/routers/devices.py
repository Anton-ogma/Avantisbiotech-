"""Канал беспроводных датчиков ЭМГ и ручной ввод значений со снимка (Р-44).

Почему захват приходит от клиента, а не с сервера. Bluetooth Low Energy — это
локальная связь между датчиком и машиной, у которой есть радио: у планшета
оператора, а не у сервера в стойке. Тянуть BLE на сервер значило бы требовать
радио на нём и держать оператора у стойки. Поэтому соединение и подписку на
уведомления ведёт браузер, а сюда приходит уже собранный поток отсчётов.

Что это меняет для достоверности: расчёт остаётся на сервере, в чистом
`domain/emg_stream`. Клиент передаёт отсчёты и метки времени — то есть то, что
пришло от датчика, — а не готовые RMS. Иначе результат зависел бы от версии
браузера, и §7 (воспроизводимость) выполнить было бы нечем.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.config import load_ble_profiles
from domain.emg_stream import StreamError, process_capture
from domain.hashing import file_hash

from ..db import get_db
from ..models import Measurement, RawImport, SessionMontageRow, Trial
from ..security import Principal, audit, current_principal, require
from ..services.session_service import load_session, materialize_param_values

router = APIRouter(tags=["devices"])

#: Верхняя граница на один захват. 8 каналов × 2 кГц × 60 с ≈ 1 млн отсчётов;
#: больше — это уже не проба, а непрерывная запись, и она идёт файлом.
MAX_SAMPLES = 1_200_000


class CaptureIn(BaseModel):
    trial_id: UUID
    profile: str
    #: Метка канала на приборе → отсчёты как пришли от датчика (сырой АЦП).
    channels: dict[str, list[float]] = Field(min_length=1)
    #: Эпоха покоя по тем же каналам. Без неё SNR §9.8 не вычисляется.
    rest: dict[str, list[float]] | None = None
    #: Метки прихода пакетов, мс. По ним считается фактическая частота и потери.
    timestamps_ms: list[float] | None = None
    #: Заявленная частота, если оператор изменил её на приборе.
    fs_hz: float | None = None
    device_serial: str | None = Field(default=None, max_length=64)


@router.get("/devices/ble-profiles")
async def ble_profiles(principal: Principal = Depends(current_principal)) -> dict:
    lib = load_ble_profiles()
    return {
        "version": lib.version,
        "profiles": [
            {"code": p.code, "label_ru": p.label_ru, "vendor": p.vendor,
             "verified": p.verified, "note": p.note,
             "service_uuid": p.service_uuid,
             "data_characteristic": p.data_characteristic,
             "control_characteristic": p.control_characteristic,
             "sample_format": p.sample_format,
             "channels_per_packet": p.channels_per_packet,
             "channel_order": list(p.channel_order),
             "fs_hz": p.fs_hz, "unit_scale_uv": p.unit_scale_uv}
            for p in lib.profiles
        ],
        "note": (
            "verified=false — профиль описан по документации, но на железе не "
            "проверен: ошибка в коэффициенте к микровольтам даёт правдоподобные, "
            "но неверные амплитуды. Записи по такому профилю помечаются."
        ),
    }


@router.post("/sessions/{session_id}/ble-capture")
async def ble_capture(
    session_id: UUID, payload: CaptureIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("operator", "clinician", "admin")),
) -> dict:
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    trial = await db.get(Trial, payload.trial_id)
    if trial is None or trial.session_id != session.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "проба не найдена в этой сессии")

    profile = load_ble_profiles().get(payload.profile)
    if profile is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"профиля {payload.profile!r} нет в библиотеке")
    total = sum(len(v) for v in payload.channels.values())
    if total > MAX_SAMPLES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"{total} отсчётов: длинная запись загружается файлом")

    try:
        capture = process_capture(
            payload.channels, payload.fs_hz or profile.fs_hz,
            timestamps_ms=payload.timestamps_ms,
            unit_scale_uv=profile.unit_scale_uv,
            rest=payload.rest,
        )
    except StreamError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    montage = await _montage_map(db, session.id)
    params = capture.params(montage)
    unmapped = capture.unmapped_labels(montage)

    flags = list(capture.flags)
    for ch in capture.channels:
        flags.extend(f"{f}:{ch.label}" for f in ch.flags)
    if not profile.verified:
        flags.append("ble_profile_unverified")
    if unmapped:
        # Канал без прописи в параметры не идёт (Р-42). Молча его потерять
        # нельзя: оператор либо допишет монтаж, либо решит, что канал лишний.
        flags.append("channels_without_montage:" + ",".join(unmapped))

    # Идемпотентность §4: хеш по составу захвата, а не по времени приёма.
    digest = file_hash(repr([
        payload.profile, sorted(payload.channels), capture.fs_declared,
        [(c.label, c.rms_uv) for c in capture.channels],
    ]).encode())
    exists = (await db.execute(
        select(RawImport).where(RawImport.file_hash == digest)
    )).scalar_one_or_none()
    if exists is not None:
        return {"status": "duplicate", "import_id": str(exists.id),
                "reason": "такой захват уже загружен (идемпотентность §4)"}

    record = RawImport(
        session_id=session.id, file_hash=digest, modality="emg",
        format_id=f"ble-capture:{profile.code}", source="device",
        device_sw_version=payload.device_serial, status="parsed",
    )
    db.add(record)
    await db.flush()
    db.add(Measurement(
        trial_id=trial.id, raw_import_id=record.id, modality="emg",
        params=params, unmapped={label: "нет прописи в монтаже" for label in unmapped},
        quality_flags=flags,
    ))
    await db.flush()

    full = await load_session(db, session_id)
    if full is not None:
        await materialize_param_values(db, full)
        if full.status == "probes_running":
            full.status = "imported"
    await db.flush()
    await audit(db, principal, "session.ble_capture", "trial", str(trial.id),
                payload={"profile": profile.code, "channels": len(capture.channels),
                         "params": len(params)})

    return {
        "status": "captured",
        "import_id": str(record.id),
        "probe_code": trial.probe_code,
        "fs_declared": capture.fs_declared,
        "fs_actual": capture.fs_actual,
        "duration_sec": capture.duration_sec,
        "params": params,
        "channels": [
            {"label": c.label, "rms_uv": c.rms_uv, "peak_uv": c.peak_uv,
             "snr_db": c.snr_db, "mains_share_db": c.mains_share_db,
             "samples": c.samples, "flags": list(c.flags)}
            for c in capture.channels
        ],
        "unmapped": unmapped,
        "quality_flags": flags,
        "note": (
            "Амплитуды в мкВ сравнимы только внутри одной сессии: между записями "
            "меняется и положение датчика на мышце, и прижим (§9.8)."
        ),
    }


async def _montage_map(db: AsyncSession, session_id) -> dict[str, tuple[str, str]]:
    from domain.montage import MontageError, build_montage

    row = (await db.execute(
        select(SessionMontageRow)
        .where(SessionMontageRow.session_id == session_id)
        .order_by(SessionMontageRow.created_at.desc(), SessionMontageRow.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return {}
    try:
        return build_montage(list(row.channels or []), template=row.template).channel_map()
    except MontageError:
        return {}
