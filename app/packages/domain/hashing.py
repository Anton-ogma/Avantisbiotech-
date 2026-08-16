"""Канонический хэш входа (§4, инвариант 2; Р-3).

input_hash = sha256(канонические данные + пять версий конфигурации).
Побайтовая воспроизводимость требует канонической сериализации: сортированные
ключи, фиксированный формат чисел, без пробелов и локали.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _norm(value: Any) -> Any:
    if isinstance(value, float):
        # Фиксированный формат: иначе 0.1+0.2 и 0.30000000000000004 дадут разные хэши
        # на разных платформах. 12 знаков заведомо больше точности любого прибора.
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("нечисловое значение не хэшируется")
        return format(round(value, 12), ".12f")
    if isinstance(value, dict):
        return {str(k): _norm(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    return value


def canonical_json(payload: Any) -> str:
    return json.dumps(_norm(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def input_hash(payload: Any, versions: dict[str, str]) -> str:
    doc = {"data": payload, "versions": dict(sorted(versions.items()))}
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()


def file_hash(blob: bytes) -> str:
    """Идемпотентность импорта (§4, инвариант 1)."""
    return hashlib.sha256(blob).hexdigest()
