"""Иллюстрации приборных протоколов: сохранение и выдача (Р-40).

Почему это отдельная служба, а не две строки в роутере: путей импорта три —
ручная загрузка, автоподхват каталога и загрузка клинических данных скриптом, —
и все три обязаны класть иллюстрации одинаково. Разойдись они, часть сессий
осталась бы без картинок, и расхождение таблицы со схемой (мм против градусов)
стало бы невидимым ровно там, где его надо видеть.
"""
from __future__ import annotations

from importers import ParseResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ImportFigure, RawImport, Trial

#: Верхняя граница на картинку. Протокольные иллюстрации — десятки килобайт;
#: всё, что сильно больше, — не схема, а вложенное фото, и в БД ему не место.
MAX_FIGURE_BYTES = 512 * 1024


def store_figures(
    db: AsyncSession, record: RawImport, trial: Trial | None, results: list[ParseResult],
) -> int:
    """Сохраняет иллюстрации разбора. Возвращает число сохранённых.

    Идемпотентность обеспечена уровнем выше: повторная загрузка того же файла
    не доходит сюда — `RawImport.file_hash` уникален (§4 инвариант 1).
    """
    n = 0
    for res in results:
        for figure in res.figures:
            if len(figure.data) > MAX_FIGURE_BYTES:
                continue
            db.add(ImportFigure(
                raw_import_id=record.id,
                trial_id=trial.id if trial is not None else None,
                ordinal=n, name=figure.name, kind=figure.kind, mime=figure.mime,
                width=figure.width, height=figure.height, data=figure.data,
                structures=list(figure.structures), page=figure.page,
            ))
            n += 1
    return n
