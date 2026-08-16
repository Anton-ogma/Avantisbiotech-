"""Загрузка версионированной конфигурации (§10 ТЗ).

Конфигурации неизменяемы в пределах версии, поэтому кэшируются навсегда по ключу
версии — это же снимает нагрузку при масштабировании: пять справочников читаются
на каждый анализ, но с диска берутся один раз на процесс.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config"

Direction = Literal["two_sided", "higher_worse", "lower_worse", "unknown"]


class ConfigError(RuntimeError):
    """Невалидная конфигурация. MUST §10: роняет запуск, а не деградирует молча."""


@dataclass(frozen=True, slots=True)
class ParamSpec:
    code: str
    label_ru: str
    modality: str
    unit: str
    domain: str
    direction: Direction
    in_pi: bool
    weight: float
    direction_evidence: str | None = None

    @property
    def direction_known(self) -> bool:
        return self.direction != "unknown"


@dataclass(frozen=True, slots=True)
class ParamRegistry:
    version: str
    params: dict[str, ParamSpec]

    def get(self, code: str) -> ParamSpec | None:
        return self.params.get(code)

    def in_index(self) -> list[ParamSpec]:
        """Параметры, участвующие в индексах. Структурные (leg_axis) исключены §9.2."""
        return [p for p in self.params.values() if p.in_pi and p.weight > 0]


@dataclass(frozen=True, slots=True)
class Profile:
    version: str
    z_cap: float
    ri_cap: float
    z_categories: dict[str, float]
    domain_weights: dict[str, float]


@dataclass(frozen=True, slots=True)
class Thresholds:
    version: str
    source: str
    values: dict[str, float]

    @property
    def is_demo(self) -> bool:
        """MUST §10: пока source содержит demo — предупреждение на всех экранах."""
        return "demo" in self.source.lower()

    def sdc(self, code: str) -> float | None:
        v = self.values.get(code)
        return float(v) if v is not None and float(v) > 0 else None


@dataclass(frozen=True, slots=True)
class NormSpec:
    mean: float | None
    sd: float | None
    strata: list[str] = field(default_factory=list)

    @property
    def defined(self) -> bool:
        return self.mean is not None and self.sd is not None and self.sd > 0


@dataclass(frozen=True, slots=True)
class Norms:
    version: str
    source: str
    params: dict[str, NormSpec]

    def get(self, code: str) -> NormSpec | None:
        n = self.params.get(code)
        return n if n and n.defined else None

    @property
    def empty(self) -> bool:
        """Штатное состояние (Р-13): норм нет, PI не считается, RI работает."""
        return not any(n.defined for n in self.params.values())


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    code: str
    label_ru: str
    group: str
    role: str
    settle_sec: int
    carryover_min: int
    modes: tuple[str, ...]
    is_neutral: bool = False
    requires_effort: bool = False
    requires_excursion: bool = False
    shams_group: str | None = None
    modality: str = "formetric"
    #: Метки условия, как их пишет клиника в протоколе прибора («лев окк»).
    #: Сопоставление живёт здесь, а не в парсере: догадываться в разборе, что
    #: значит сокращение оператора, нельзя (Р-36).
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProbeRegistry:
    version: str
    probes: dict[str, ProbeSpec]

    def get(self, code: str) -> ProbeSpec | None:
        return self.probes.get(code)

    def by_alias(self, label: str) -> ProbeSpec | None:
        """Разрешение метки протокола в код пробы. None — метка неизвестна,
        и это повод спросить, а не угадать."""
        needle = " ".join(label.lower().split())
        for spec in self.probes.values():
            if needle in {a.lower() for a in spec.aliases} or needle == spec.code.lower():
                return spec
        return None

    def shams_for(self, group: str) -> list[ProbeSpec]:
        return [p for p in self.probes.values() if p.shams_group == group]


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"конфигурация не найдена: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"ожидался объект в {path}")
    return data


@lru_cache(maxsize=32)
def load_param_registry(version: str) -> ParamRegistry:
    raw = _read(CONFIG_ROOT / "registry" / f"param_registry_{version}.yaml")
    params: dict[str, ParamSpec] = {}
    for code, spec in (raw.get("params") or {}).items():
        direction = spec.get("direction", "unknown")
        if direction not in ("two_sided", "higher_worse", "lower_worse", "unknown"):
            raise ConfigError(f"{code}: недопустимое direction={direction!r}")
        params[code] = ParamSpec(
            code=code,
            label_ru=spec.get("label_ru", code),
            modality=spec.get("modality", "unknown"),
            unit=spec.get("unit", ""),
            domain=spec.get("domain", "unknown"),
            direction=direction,
            in_pi=bool(spec.get("in_pi", True)),
            weight=float(spec.get("weight", 1.0)),
            direction_evidence=spec.get("direction_evidence"),
        )
    if not params:
        raise ConfigError("реестр параметров пуст")
    return ParamRegistry(version=str(raw.get("version", version)), params=params)


@lru_cache(maxsize=32)
def load_profile(version: str) -> Profile:
    raw = _read(CONFIG_ROOT / "profiles" / f"profile_{version}.yaml")
    weights = raw.get("domain_weights") or {}
    if not weights:
        raise ConfigError("profile: domain_weights обязательны")
    return Profile(
        version=str(raw.get("version", version)),
        z_cap=float(raw.get("z_cap", 4.0)),
        ri_cap=float(raw.get("ri_cap", 4.0)),
        z_categories=dict(raw.get("z_categories") or {}),
        domain_weights={k: float(v) for k, v in weights.items()},
    )


@lru_cache(maxsize=32)
def load_thresholds(version: str) -> Thresholds:
    raw = _read(CONFIG_ROOT / "thresholds" / f"sdc_{version}.yaml")
    source = str(raw.get("source") or "")
    if not source.strip():
        # MUST §10: source обязателен и не может быть пустым.
        raise ConfigError("thresholds: поле source обязательно")
    return Thresholds(
        version=str(raw.get("version", version)),
        source=source,
        values={k: float(v) for k, v in (raw.get("values") or {}).items() if v is not None},
    )


@lru_cache(maxsize=32)
def load_norms(version: str) -> Norms:
    raw = _read(CONFIG_ROOT / "norms" / f"norms_{version}.yaml")
    source = str(raw.get("source") or "")
    if not source.strip():
        raise ConfigError("norms: поле source обязательно")
    params = {
        code: NormSpec(
            mean=None if spec.get("mean") is None else float(spec["mean"]),
            sd=None if spec.get("sd") is None else float(spec["sd"]),
            strata=list(spec.get("strata") or []),
        )
        for code, spec in (raw.get("params") or {}).items()
    }
    return Norms(version=str(raw.get("version", version)), source=source, params=params)


@lru_cache(maxsize=32)
def load_probe_registry(version: str) -> ProbeRegistry:
    raw = _read(CONFIG_ROOT / "probes" / "probe_registry.yaml")
    probes = {
        p["code"]: ProbeSpec(
            code=p["code"],
            label_ru=p.get("label_ru", p["code"]),
            group=p.get("group", "unknown"),
            role=p.get("role", "diagnostic"),
            settle_sec=int(p.get("settle_sec", 0)),
            carryover_min=int(p.get("carryover_min", 0)),
            modes=tuple(p.get("modes") or ("static",)),
            is_neutral=bool(p.get("is_neutral", False)),
            requires_effort=bool(p.get("requires_effort", False)),
            requires_excursion=bool(p.get("requires_excursion", False)),
            shams_group=p.get("shams_group"),
            modality=p.get("modality", "formetric"),
            aliases=tuple(p.get("aliases") or ()),
        )
        for p in (raw.get("probes") or [])
    }
    if not probes:
        raise ConfigError("реестр проб пуст")
    return ProbeRegistry(version=str(raw.get("version", version)), probes=probes)


@dataclass(frozen=True, slots=True)
class ConfigBundle:
    """Пять версий, входящих в input_hash (Р-3), плюс реестр проб."""

    registry: ParamRegistry
    profile: Profile
    thresholds: Thresholds
    norms: Norms
    probes: ProbeRegistry
    rules_version: str

    @property
    def versions(self) -> dict[str, str]:
        return {
            "norms_version": self.norms.version,
            "thresholds_version": self.thresholds.version,
            "rules_version": self.rules_version,
            "profile_version": self.profile.version,
            "registry_version": self.registry.version,
        }


def load_bundle(
    *,
    registry_version: str,
    profile_version: str,
    thresholds_version: str,
    norms_version: str,
    protocol_version: str,
    rules_version: str = "none",
) -> ConfigBundle:
    return ConfigBundle(
        registry=load_param_registry(registry_version),
        profile=load_profile(profile_version),
        thresholds=load_thresholds(thresholds_version),
        norms=load_norms(norms_version),
        probes=load_probe_registry(protocol_version),
        rules_version=rules_version,
    )


@dataclass(frozen=True, slots=True)
class Region:
    """Область тела для обзора «от сустава до стоп» (§14.3)."""

    key: str
    order: int
    label_ru: str
    hint: str
    codes: tuple[str, ...]
    muscles: tuple[str, ...]
    prefixes: tuple[str, ...]
    structural: bool


@dataclass(frozen=True, slots=True)
class Anatomy:
    version: str
    regions: tuple[Region, ...]

    def region_of(self, code: str) -> Region | None:
        for r in self.regions:
            if code in r.codes or code in r.muscles:
                return r
        for r in self.regions:
            if any(code.startswith(p) for p in r.prefixes):
                return r
        return None

    def ordered(self) -> list[Region]:
        return sorted(self.regions, key=lambda r: r.order)


@lru_cache(maxsize=4)
def load_anatomy(version: str = "2026.1") -> Anatomy:
    """Конфигурация ОТОБРАЖЕНИЯ: в input_hash не входит (§14.3, Р-39).

    Группировка по областям тела не меняет ни одного вычисляемого значения.
    Включить её в хэш значило бы объявлять переанализ всех сессий при
    переименовании заголовка раздела.
    """
    raw = _read(CONFIG_ROOT / "regions" / "anatomy.yaml")
    # Мышцы подмешиваются из каталога (Р-42): принадлежность области задана там,
    # и дублировать списки здесь значило бы завести второй источник правды.
    catalog = load_muscles()
    by_region: dict[str, list[str]] = {}
    for m in catalog.muscles:
        if not m.surface:
            continue
        by_region.setdefault(m.region, []).extend(
            (f"EMG_RMS_{m.code}_L", f"EMG_RMS_{m.code}_R", f"EMG_ASYM_{m.code}")
        )
    regions = tuple(
        Region(
            key=r["key"], order=int(r.get("order", 99)), label_ru=r.get("label_ru", r["key"]),
            hint=r.get("hint", ""), codes=tuple(r.get("codes") or ()),
            muscles=tuple(r.get("muscles") or ()) + tuple(by_region.get(r["key"], ())),
            prefixes=tuple(r.get("prefixes") or ()),
            structural=bool(r.get("structural", False)),
        )
        for r in (raw.get("regions") or [])
    )
    orphans = sorted(set(by_region) - {r.key for r in regions})
    if orphans:
        # Мышца, чьей области нет в раскладке, выпала бы из обзора §14.3 молча.
        raise ConfigError(f"каталог мышц ссылается на неизвестные области: {orphans}")
    if not regions:
        raise ConfigError("анатомическая раскладка пуста")
    return Anatomy(version=str(raw.get("version", version)), regions=regions)


# ── Каталог мышц и монтажи ЭМГ (Р-42) ────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Muscle:
    code: str
    label_ru: str
    latin: str
    region: str
    #: Снимается ли поверхностными электродами. False — мышца в каталоге есть,
    #: но подписать ею канал нельзя: измерение этим методом не производится.
    surface: bool
    note: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MuscleCatalog:
    version: str
    muscles: tuple[Muscle, ...]

    def get(self, code: str) -> Muscle | None:
        return next((m for m in self.muscles if m.code == code), None)

    def by_alias(self, text: str) -> Muscle | None:
        """Метка вендора → мышца. Совпадение точное по нормализованному алиасу.

        Частичное совпадение здесь запрещено намеренно: «gastroc» подошло бы и
        к общему отводу, и к обеим головкам, а это разные каналы (Р-40 о том же
        для перекоса таза). Не опознали — пусть оператор пропишет вручную.
        """
        needle = " ".join(text.strip().lower().replace("-", " ").replace("_", " ").split())
        if not needle:
            return None
        for m in self.muscles:
            if needle == m.code.lower().replace("_", " "):
                return m
            if any(needle == a.lower() for a in m.aliases):
                return m
        return None

    def surface_codes(self) -> tuple[str, ...]:
        return tuple(m.code for m in self.muscles if m.surface)


@dataclass(frozen=True, slots=True)
class MontageChannel:
    muscle: str
    #: "L" | "R" | "both". Односторонний монтаж законен: так пишут, когда
    #: интересует сторона поражения.
    side: str

    def sides(self) -> tuple[str, ...]:
        return ("L", "R") if self.side == "both" else (self.side,)


@dataclass(frozen=True, slots=True)
class Montage:
    code: str
    label_ru: str
    purpose: str
    channels: tuple[MontageChannel, ...]

    def param_codes(self) -> list[str]:
        out: list[str] = []
        for ch in self.channels:
            out.extend(f"EMG_RMS_{ch.muscle}_{s}" for s in ch.sides())
            if ch.side == "both":
                out.append(f"EMG_ASYM_{ch.muscle}")
        return out


@dataclass(frozen=True, slots=True)
class MontageLibrary:
    version: str
    montages: tuple[Montage, ...]

    def get(self, code: str) -> Montage | None:
        return next((m for m in self.montages if m.code == code), None)


@lru_cache(maxsize=4)
def load_muscles(version: str = "2026.1") -> MuscleCatalog:
    raw = _read(CONFIG_ROOT / "emg" / "muscles.yaml")
    muscles = tuple(
        Muscle(
            code=m["code"], label_ru=m.get("label_ru", m["code"]),
            latin=m.get("latin", ""), region=m.get("region", "unknown"),
            surface=bool(m.get("surface", True)), note=m.get("note", ""),
            aliases=tuple(m.get("aliases") or ()),
        )
        for m in (raw.get("muscles") or [])
    )
    if not muscles:
        raise ConfigError("каталог мышц пуст")
    duplicates = {m.code for m in muscles if sum(1 for x in muscles if x.code == m.code) > 1}
    if duplicates:
        raise ConfigError(f"дубликаты кодов мышц: {sorted(duplicates)}")
    return MuscleCatalog(version=str(raw.get("version", version)), muscles=muscles)


@lru_cache(maxsize=4)
def load_montages(version: str = "2026.1") -> MontageLibrary:
    raw = _read(CONFIG_ROOT / "emg" / "montages.yaml")
    catalog = load_muscles()
    montages = []
    for m in (raw.get("montages") or []):
        channels = []
        for ch in (m.get("channels") or []):
            muscle = catalog.get(ch["muscle"])
            if muscle is None:
                raise ConfigError(f"монтаж {m['code']}: мышцы {ch['muscle']} нет в каталоге")
            if not muscle.surface:
                # Шаблон, предлагающий недоступный отвод, породил бы «измерения»
                # там, где метод не работает. Ловим на загрузке, а не в отчёте.
                raise ConfigError(
                    f"монтаж {m['code']}: {muscle.code} не снимается поверхностно")
            side = ch.get("side", "both")
            if side not in ("L", "R", "both"):
                raise ConfigError(f"монтаж {m['code']}: сторона {side!r} недопустима")
            channels.append(MontageChannel(muscle=muscle.code, side=side))
        if not channels:
            raise ConfigError(f"монтаж {m['code']} пуст")
        montages.append(Montage(
            code=m["code"], label_ru=m.get("label_ru", m["code"]),
            purpose=m.get("purpose", ""), channels=tuple(channels),
        ))
    if not montages:
        raise ConfigError("библиотека монтажей пуста")
    return MontageLibrary(version=str(raw.get("version", version)), montages=tuple(montages))
