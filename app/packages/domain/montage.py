"""Монтаж ЭМГ сессии: какие каналы записаны и что к чему приклеено (Р-42).

Каталог мышц говорит, что БЫВАЕТ. Монтаж — что БЫЛО в этой записи. Разница
принципиальна: без монтажа столбец «CH3» не опознаётся никак, и у платформы
есть ровно два честных выхода — оставить канал неопознанным или взять готовую
пропись оператора. Догадка («третий канал обычно ГКС») не выход: она даёт
измерение, которого никто не делал.

Монтаж собирается двумя способами и обычно обоими сразу:
  • из шаблона (montages.yaml) — типовая раскладка группы мышц;
  • ручной прописью — оператор вписывает метку, которой миограф подписывает
    провод, и назначает ей мышцу и сторону.

`ChannelMap` — то, что уходит в парсер: нормализованная метка → (мышца, сторона).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import Montage, load_montages, load_muscles

ChannelMap = dict[str, tuple[str, str]]

SIDES = ("L", "R")


class MontageError(ValueError):
    """Монтаж описывает запись, которой не могло быть."""


def normalize_label(label: str) -> str:
    """Метка провода приводится к сравнимому виду, но не «угадывается».

    Свернуть регистр и пробелы можно: «CH 1» и «ch1» — одна и та же надпись на
    приборе. Всё остальное — уже интерпретация, и здесь её нет.
    """
    return " ".join(label.strip().lower().replace("-", " ").replace("_", " ").split())


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    """Один записанный канал: провод, мышца, сторона."""

    label: str        # как подписан на миографе: «CH3», «MASS_L», «жев слева»
    muscle: str
    side: str         # "L" | "R"

    @property
    def param_code(self) -> str:
        return f"EMG_RMS_{self.muscle}_{self.side}"


@dataclass(frozen=True, slots=True)
class SessionMontage:
    """Монтаж сессии. `template` — от какого шаблона отталкивались, если от какого-то."""

    channels: tuple[ChannelSpec, ...]
    template: str | None = None
    note: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def channel_map(self) -> ChannelMap:
        return {normalize_label(c.label): (c.muscle, c.side) for c in self.channels}

    def param_codes(self) -> list[str]:
        codes = [c.param_code for c in self.channels]
        # Асимметрия появляется только у мышцы, записанной с ОБЕИХ сторон:
        # односторонний отвод не даёт правой и левой величины, и вычислять
        # «асимметрию» по одной из них было бы выдумкой.
        paired = {c.muscle for c in self.channels
                  if {x.side for x in self.channels if x.muscle == c.muscle} == set(SIDES)}
        codes += [f"EMG_ASYM_{m}" for m in sorted(paired)]
        return codes

    def to_dict(self) -> dict:
        return {
            "template": self.template,
            "note": self.note,
            "channels": [{"label": c.label, "muscle": c.muscle, "side": c.side}
                         for c in self.channels],
        }


def build_montage(
    channels: list[dict],
    *,
    template: str | None = None,
    note: str = "",
) -> SessionMontage:
    """Собирает монтаж из ручной прописи, проверяя каждый канал.

    Проверки не формальность. Канал, подписанный недоступной поверхностно
    мышцей, объявил бы измеренным то, что этим методом не измеряется; две
    записи на один провод молча перетёрли бы друг друга при разборе.
    """
    catalog = load_muscles()
    seen_labels: dict[str, str] = {}
    seen_channels: set[tuple[str, str]] = set()
    specs: list[ChannelSpec] = []
    warnings: list[str] = []

    for raw in channels:
        label = str(raw.get("label", "")).strip()
        muscle_code = str(raw.get("muscle", "")).strip()
        side = str(raw.get("side", "")).strip().upper()
        if not label:
            raise MontageError("у канала нет метки: нечего сопоставлять со столбцом файла")
        muscle = catalog.get(muscle_code)
        if muscle is None:
            raise MontageError(f"мышцы {muscle_code!r} нет в каталоге")
        if not muscle.surface:
            raise MontageError(
                f"{muscle.code} не снимается поверхностными электродами"
                + (f": {muscle.note}" if muscle.note else "")
            )
        if side not in SIDES:
            raise MontageError(f"канал {label!r}: сторона должна быть L или R, а не {side!r}")

        key = normalize_label(label)
        if key in seen_labels:
            raise MontageError(
                f"метка {label!r} назначена дважды ({seen_labels[key]} и "
                f"{muscle.code}_{side}): при разборе одна запись перетёрла бы другую"
            )
        if (muscle.code, side) in seen_channels:
            raise MontageError(f"{muscle.code} {side} записана дважды под разными метками")
        seen_labels[key] = f"{muscle.code}_{side}"
        seen_channels.add((muscle.code, side))
        specs.append(ChannelSpec(label=label, muscle=muscle.code, side=side))

    if not specs:
        raise MontageError("монтаж пуст: ни одного канала")

    one_sided = sorted({m for m, in ((c.muscle,) for c in specs)
                        if {x.side for x in specs if x.muscle == m} != set(SIDES)})
    if one_sided:
        # Не ошибка: односторонний монтаж пишут осознанно. Но асимметрии по нему
        # не будет, и узнать об этом лучше сейчас, чем при пустой колонке.
        warnings.append(
            "записаны с одной стороны, асимметрия по ним не считается: "
            + ", ".join(one_sided)
        )
    return SessionMontage(channels=tuple(specs), template=template, note=note,
                          warnings=tuple(warnings))


def montage_from_channels(
    channels: list[dict], *, code: str, label_ru: str,
    labels: dict[str, str] | None = None,
) -> SessionMontage:
    """Разворачивает произвольный набор «мышца + сторона» в монтаж (Р-45).

    Тот же путь, что у встроенного шаблона: `side: both` даёт два отвода.
    Своим шаблонам отдельная арифметика не нужна и была бы вредна — она
    разошлась бы с поставляемыми в первый же месяц.
    """
    catalog = load_muscles()
    labels = labels or {}
    out: list[dict] = []
    for ch in channels:
        muscle = catalog.get(str(ch.get("muscle", "")))
        if muscle is None:
            raise MontageError(f"мышцы {ch.get('muscle')!r} нет в каталоге")
        side = str(ch.get("side", "both"))
        if side not in ("L", "R", "both"):
            raise MontageError(f"{muscle.code}: сторона {side!r} недопустима")
        for s in (SIDES if side == "both" else (side,)):
            default = f"{muscle.code}_{s}"
            out.append({"label": labels.get(default, default), "muscle": muscle.code, "side": s})
    return build_montage(out, template=code, note=f"из шаблона «{label_ru}»")


def from_template(code: str, *, labels: dict[str, str] | None = None) -> SessionMontage:
    """Разворачивает шаблон в монтаж.

    По умолчанию меткой канала становится «<КОД>_<СТОРОНА>» — так подписывает
    большинство выгрузок, и такой монтаж работает без правки. Если миограф
    подписывает иначе, оператор передаёт `labels`: код канала → своя метка.
    """
    montage: Montage | None = load_montages().get(code)
    if montage is None:
        raise MontageError(f"шаблона {code!r} нет в библиотеке монтажей")
    labels = labels or {}
    channels = []
    for ch in montage.channels:
        for side in ch.sides():
            default = f"{ch.muscle}_{side}"
            channels.append({"label": labels.get(default, default),
                             "muscle": ch.muscle, "side": side})
    return build_montage(channels, template=montage.code,
                         note=f"из шаблона «{montage.label_ru}»")


def unresolved_channels(headers: list[str], montage: SessionMontage | None) -> list[str]:
    """Столбцы файла, которые не опознаются ни каталогом, ни монтажом.

    Возвращаются оператору как список к ручной прописи. Пустой список — не
    повод для тишины: значит, прописывать нечего.
    """
    from importers.emg_csv import resolve_channel      # локально: слой выше домена

    channel_map = montage.channel_map() if montage else None
    out = []
    for h in headers:
        if not h.strip():
            continue
        if resolve_channel(h, channel_map) is None:
            out.append(h)
    return out


def apply_montage(result, montage: SessionMontage | None):
    """Достраивает разбор ЭМГ по монтажу сессии.

    Работает ПОСЛЕ парсера, а не внутри него, и это не компромисс. Парсер
    обязан оставаться чистой функцией от байтов: тот же файл даёт тот же
    разбор всегда, иначе воспроизводимость §7 держится на состоянии сессии.
    Монтаж — знание оператора, а не свойство файла, поэтому он и применяется
    отдельным шагом, со своим следом в флагах качества.

    Неопознанные столбцы парсер сохранил в `unmapped` (§5.1 запрещает терять
    молча) — здесь они и разбираются.
    """
    if montage is None or result.modality != "emg" or not result.unmapped:
        return result
    channel_map = montage.channel_map()
    resolved: dict[str, float] = {}
    leftover: dict[str, str] = {}
    for header, raw in result.unmapped.items():
        hit = channel_map.get(normalize_label(header))
        if hit is None:
            leftover[header] = raw
            continue
        try:
            value = float(str(raw).replace(",", ".").strip())
        except (TypeError, ValueError):
            leftover[header] = raw
            continue
        resolved[f"EMG_RMS_{hit[0]}_{hit[1]}"] = value

    if not resolved:
        return result
    result.params.update(resolved)
    result.unmapped = leftover
    _recompute_asymmetry(result.params)
    result.quality_flags.append(f"channels_from_montage:{len(resolved)}")
    if montage.template:
        result.quality_flags.append(f"montage:{montage.template}")
    return result


def _recompute_asymmetry(params: dict[str, float]) -> None:
    """Асимметрия по той же формуле, что у силы и мыщелков: 200·(R−L)/(|R|+|L|)."""
    bases = {c[len("EMG_RMS_"):-2] for c in params
             if c.startswith("EMG_RMS_") and c.endswith(("_L", "_R"))}
    for base in bases:
        r, l = params.get(f"EMG_RMS_{base}_R"), params.get(f"EMG_RMS_{base}_L")
        if r is None or l is None or (abs(r) + abs(l)) == 0:
            continue
        params[f"EMG_ASYM_{base}"] = round(200 * (r - l) / (abs(r) + abs(l)), 2)
