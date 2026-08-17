"""Обработка потока поверхностной ЭМГ до RMS-огибающей (§9.8, Р-44).

Чистая арифметика, без ввода-вывода: та же последовательность отсчётов даёт тот
же результат всегда. Это и делает канал беспроводных датчиков пригодным для
исследования — иначе воспроизводимость §7 держалась бы на состоянии соединения.

Цепочка задана §9.8 и здесь не изобретается: снятие постоянной составляющей →
полосовой фильтр 20–450 Гц → подавление сети 50 Гц → выпрямление → RMS-окно
100–250 мс. Каждый шаг проверяем по отдельности, потому что молчаливо
испорченный сигнал выглядит как сигнал.

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Ни одного «умного» решения о качестве. Канал с плохим
сигналом помечается, но не выбрасывается: решение о пригодности принимает
человек на слепом экране разбора (Р-17), а систематически плохой канал означает
ошибку расстановки электродов — это данные, а не мусор.

SNR §9.8 считается ТОЛЬКО при записанной эпохе покоя. Оценить шум по самой
активной записи нельзя: любая такая оценка измеряет долю отфильтрованного,
то есть свойство фильтра, а не канала. Без покоя величина не определена, и
об этом говорит флаг, а не подставленное число.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

#: §9.8. Границы полосы и сеть — не настройки, а часть метода.
BAND_LOW_HZ = 20.0
BAND_HIGH_HZ = 450.0
MAINS_HZ = 50.0
#: Окно RMS: 100–250 мс по §9.8. Берём середину — 150 мс.
RMS_WINDOW_SEC = 0.150
#: Ниже этой частоты дискретизации полоса 20–450 Гц физически недостижима:
#: по теореме отсчётов для 450 Гц нужно строго больше 900 Гц.
MIN_FS_HZ = 1000.0


class StreamError(ValueError):
    """Поток не поддаётся обработке заявленным методом."""


@dataclass(frozen=True, slots=True)
class Biquad:
    """Секция второго порядка. Коэффициенты нормированы на a0."""

    b0: float
    b1: float
    b2: float
    a1: float
    a2: float

    def apply(self, xs: list[float]) -> list[float]:
        y = [0.0] * len(xs)
        x1 = x2 = y1 = y2 = 0.0
        for i, x in enumerate(xs):
            out = self.b0 * x + self.b1 * x1 + self.b2 * x2 - self.a1 * y1 - self.a2 * y2
            y[i] = out
            x2, x1 = x1, x
            y2, y1 = y1, out
        return y


def _rbj(kind: str, f0: float, fs: float, q: float) -> Biquad:
    """Коэффициенты по формулам RBJ (Robert Bristow-Johnson).

    Взяты готовыми намеренно: это стандартная и проверяемая форма, а
    самодельный вывод в измерительном тракте — источник ошибок, которые
    проявляются как «странная биология».
    """
    w0 = 2.0 * math.pi * f0 / fs
    cos_w0, sin_w0 = math.cos(w0), math.sin(w0)
    alpha = sin_w0 / (2.0 * q)
    if kind == "highpass":
        b0, b1, b2 = (1 + cos_w0) / 2, -(1 + cos_w0), (1 + cos_w0) / 2
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif kind == "lowpass":
        b0, b1, b2 = (1 - cos_w0) / 2, 1 - cos_w0, (1 - cos_w0) / 2
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif kind == "notch":
        b0, b1, b2 = 1.0, -2 * cos_w0, 1.0
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    else:                                              # pragma: no cover
        raise StreamError(f"неизвестный тип фильтра {kind!r}")
    return Biquad(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def remove_dc(xs: list[float]) -> list[float]:
    """Снятие постоянной составляющей вычитанием среднего.

    Смещение усилителя иначе целиком уходит в RMS и выглядит как активность
    покоящейся мышцы — самая правдоподобная из возможных ошибок.
    """
    if not xs:
        return []
    mean = sum(xs) / len(xs)
    return [x - mean for x in xs]


def bandpass(xs: list[float], fs: float) -> list[float]:
    """Полоса 20–450 Гц: два каскада по второму порядку на каждую границу."""
    if fs < MIN_FS_HZ:
        raise StreamError(
            f"частота дискретизации {fs:g} Гц: полоса до {BAND_HIGH_HZ:g} Гц "
            f"требует более {2 * BAND_HIGH_HZ:g} Гц"
        )
    q = math.sqrt(0.5)                                 # Баттерворт, 2-й порядок
    out = _rbj("highpass", BAND_LOW_HZ, fs, q).apply(xs)
    out = _rbj("highpass", BAND_LOW_HZ, fs, q).apply(out)
    out = _rbj("lowpass", BAND_HIGH_HZ, fs, q).apply(out)
    return _rbj("lowpass", BAND_HIGH_HZ, fs, q).apply(out)


def notch_mains(xs: list[float], fs: float, harmonics: int = 3) -> list[float]:
    """Подавление сети и её гармоник внутри полосы (50, 100, 150 Гц).

    Гармоники обязательны: наводка редко бывает чистой синусоидой, а вторая и
    третья попадают ровно в рабочую полосу ЭМГ.
    """
    out = xs
    for k in range(1, harmonics + 1):
        f0 = MAINS_HZ * k
        if f0 >= min(BAND_HIGH_HZ, fs / 2 - 1):
            break
        out = _rbj("notch", f0, fs, q=30.0).apply(out)
    return out


def rms_envelope(xs: list[float], fs: float, window_sec: float = RMS_WINDOW_SEC) -> list[float]:
    """Скользящее среднеквадратичное. Окно в отсчётах, не меньше одного."""
    n = max(1, int(round(window_sec * fs)))
    if not xs:
        return []
    out: list[float] = []
    acc = 0.0
    for i, x in enumerate(xs):
        acc += x * x
        if i >= n:
            acc -= xs[i - n] * xs[i - n]
        out.append(math.sqrt(acc / min(i + 1, n)))
    return out


def mains_share_db(raw: list[float], filtered: list[float]) -> float | None:
    """Сколько мощности убрал тракт по отношению к оставшейся, в дБ.

    Это НЕ отношение сигнал/шум, и называть его так было бы прямой ошибкой:
    на чистой записи с сильной сетевой наводкой такая величина уходит в минус,
    и канал выглядел бы негодным именно потому, что фильтр отработал.

    Что она действительно измеряет: насколько сырая запись состояла из того,
    что тракт обязан выбросить — постоянной составляющей, сети и всего вне
    полосы 20–450 Гц. Большая величина означает наводку или плохой контакт
    электрода, и это повод посмотреть на расстановку, а не на биологию.
    """
    if len(raw) < 2 or len(filtered) < 2:
        return None
    p_kept = sum(x * x for x in filtered) / len(filtered)
    removed = [r - f for r, f in zip(remove_dc(raw), filtered)]
    p_removed = sum(x * x for x in removed) / len(removed)
    if p_kept <= 0 or p_removed <= 0:
        return None
    return round(10.0 * math.log10(p_removed / p_kept), 2)


def snr_db(active: list[float], rest: list[float], fs: float) -> float | None:
    """Отношение сигнал/шум по §9.8: активность против ЗАПИСАННОГО покоя.

    Покой обязателен и подменить его нечем. Оценить шум по самой активной
    записи нельзя: любая такая оценка — это доля отфильтрованного, то есть
    свойство фильтра, а не канала. Нет эпохи покоя — SNR не определён, и об
    этом говорится флагом `snr_not_assessable`, а не подставленным числом.
    """
    if len(active) < 2 or len(rest) < 2:
        return None
    a = notch_mains(bandpass(remove_dc(active), fs), fs)
    r = notch_mains(bandpass(remove_dc(rest), fs), fs)
    p_a = sum(x * x for x in a) / len(a)
    p_r = sum(x * x for x in r) / len(r)
    if p_a <= 0 or p_r <= 0:
        return None
    return round(10.0 * math.log10(p_a / p_r), 2)


@dataclass(frozen=True, slots=True)
class ChannelResult:
    label: str
    rms_uv: float
    peak_uv: float
    #: SNR по эпохе покоя. None — покой не записан, величина не определена.
    snr_db: float | None
    #: Доля выброшенного трактом, в дБ: наводка и контакт, а не сигнал/шум.
    mains_share_db: float | None
    samples: int
    flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CaptureResult:
    fs_declared: float
    fs_actual: float | None
    duration_sec: float
    channels: tuple[ChannelResult, ...]
    flags: tuple[str, ...] = field(default_factory=tuple)

    def params(self, channel_map: dict[str, tuple[str, str]]) -> dict[str, float]:
        """Канонические значения по монтажу: метка канала → код параметра.

        Канал без прописи в параметры НЕ попадает: догадаться, что за мышца
        под меткой «CH3», нельзя (Р-42). Он остаётся в результате захвата, и
        оператор либо допишет монтаж, либо решит, что канал лишний.
        """
        out: dict[str, float] = {}
        for ch in self.channels:
            hit = channel_map.get(_norm(ch.label))
            if hit is None:
                continue
            out[f"EMG_RMS_{hit[0]}_{hit[1]}"] = round(ch.rms_uv, 2)
        _add_asymmetry(out)
        return out

    def unmapped_labels(self, channel_map: dict[str, tuple[str, str]]) -> list[str]:
        return [ch.label for ch in self.channels if _norm(ch.label) not in channel_map]


def _norm(label: str) -> str:
    return " ".join(label.strip().lower().replace("-", " ").replace("_", " ").split())


def _add_asymmetry(params: dict[str, float]) -> None:
    """Та же формула, что у ЭМГ из файла, силы и мыщелков: 200·(R−L)/(|R|+|L|)."""
    bases = {c[len("EMG_RMS_"):-2] for c in params
             if c.startswith("EMG_RMS_") and c.endswith(("_L", "_R"))}
    for base in bases:
        r, l = params.get(f"EMG_RMS_{base}_R"), params.get(f"EMG_RMS_{base}_L")
        if r is None or l is None or (abs(r) + abs(l)) == 0:
            continue
        params[f"EMG_ASYM_{base}"] = round(200 * (r - l) / (abs(r) + abs(l)), 2)


def process_capture(
    channels: dict[str, list[float]],
    fs_declared: float,
    *,
    timestamps_ms: list[float] | None = None,
    unit_scale_uv: float = 1.0,
    rest: dict[str, list[float]] | None = None,
) -> CaptureResult:
    """Поток датчиков → RMS по каналам, с проверками §9.8.

    `unit_scale_uv` — множитель к мкВ из профиля устройства: датчики отдают
    сырые отсчёты АЦП, и подставлять «обычно так» вместо заявленного
    коэффициента значило бы выдумать амплитуду.

    `timestamps_ms` — метки прихода пакетов, если устройство их даёт. По ним
    считается ФАКТИЧЕСКАЯ частота и потери: заявленная частота у беспроводных
    датчиков расходится с фактической, и §5.2 требует сравнивать их, а не
    доверять заголовку.

    `rest` — эпоха покоя по тем же каналам. Без неё SNR §9.8 не вычисляется:
    подставить оценку по самой записи значит выдать свойство фильтра за
    свойство канала.
    """
    if not channels:
        raise StreamError("в захвате нет ни одного канала")
    lengths = {len(v) for v in channels.values()}
    if len(lengths) != 1:
        raise StreamError(f"каналы разной длины: {sorted(lengths)}")
    n = lengths.pop()
    if n < 2:
        raise StreamError("в захвате меньше двух отсчётов")

    flags: list[str] = []
    fs_actual: float | None = None
    duration = n / fs_declared
    if timestamps_ms and len(timestamps_ms) >= 2:
        span = (timestamps_ms[-1] - timestamps_ms[0]) / 1000.0
        if span > 0:
            fs_actual = round((len(timestamps_ms) - 1) / span, 2)
            duration = span
            # MUST §5.2: расхождение заявленной и фактической частоты — флаг,
            # а не повод молча пересчитать. Пересчёт скрыл бы потерю пакетов.
            if abs(fs_actual - fs_declared) / fs_declared > 0.05:
                flags.append(f"resample_suspected:{fs_actual:g}vs{fs_declared:g}")
        gaps = sum(
            1 for a, b in zip(timestamps_ms, timestamps_ms[1:])
            if (b - a) > 1.5 * 1000.0 / fs_declared
        )
        if gaps:
            # Беспроводной канал теряет пакеты — это его свойство, а не сбой.
            # Скрыть потери значило бы выдать рваную запись за непрерывную.
            flags.append(f"packet_loss:{gaps}")

    results: list[ChannelResult] = []
    for label, raw in channels.items():
        scaled = [x * unit_scale_uv for x in raw]
        try:
            filtered = notch_mains(bandpass(remove_dc(scaled), fs_declared), fs_declared)
        except StreamError:
            raise
        env = rms_envelope([abs(x) for x in filtered], fs_declared)
        rms = math.sqrt(sum(x * x for x in filtered) / len(filtered))
        ch_flags: list[str] = []
        share = mains_share_db(scaled, filtered)
        rest_samples = (rest or {}).get(label)
        snr = None
        if rest_samples:
            snr = snr_db(scaled, [x * unit_scale_uv for x in rest_samples], fs_declared)
        if snr is None:
            # §9.8 требует SNR до интерпретации. Мы не подставляем оценку:
            # сказать «не определён» честнее, чем назвать свойство фильтра
            # свойством канала.
            ch_flags.append("snr_not_assessable")
        elif snr < 6.0:
            # Канал помечается и НЕ интерпретируется; выбрасывать его
            # автоматически нельзя — систематически плохой канал означает
            # ошибку расстановки электродов, и это данные, а не мусор (Р-17).
            ch_flags.append("low_snr")
        if share is not None and share > 10.0:
            ch_flags.append("mains_interference")
        if max((abs(x) for x in scaled), default=0.0) == 0.0:
            ch_flags.append("flat_channel")
        results.append(ChannelResult(
            label=label, rms_uv=round(rms, 3),
            peak_uv=round(max(env) if env else 0.0, 3),
            snr_db=snr, mains_share_db=share, samples=n, flags=tuple(ch_flags),
        ))

    # MUST §9.8: амплитуды в мкВ сравнимы только внутри сессии — электроды
    # переклеиваются. Для беспроводных датчиков это верно тем более: между
    # записями меняется и прижим, и положение датчика на мышце.
    flags.append("emg_amplitude_session_scoped")
    return CaptureResult(
        fs_declared=fs_declared, fs_actual=fs_actual, duration_sec=round(duration, 3),
        channels=tuple(results), flags=tuple(flags),
    )
