/** Захват с беспроводных датчиков ЭМГ через Web Bluetooth (Р-44).
 *
 *  Почему соединение ведёт браузер, а не сервер: BLE — локальная радиосвязь
 *  между датчиком и машиной оператора. Сервер в стойке радио не имеет, и тянуть
 *  туда датчик значило бы держать оператора у стойки.
 *
 *  Почему на сервер уходят ОТСЧЁТЫ, а не готовые RMS: расчёт §9.8 обязан быть
 *  воспроизводимым, а версия браузера в него входить не должна. Клиент делает
 *  ровно то, что не может сделать сервер, — принимает пакеты, — и ни грамма
 *  арифметики сверх распаковки байтов.
 *
 *  Web Bluetooth есть в Chrome и Edge на настольных системах и Android. В Safari
 *  и на iOS его нет и не планируется: там остаётся файл выгрузки. Экран говорит
 *  это прямо, а не прячет неработающую кнопку.
 */
import { useEffect, useState } from "react";
import type { BleProfile } from "../lib/api";
import { Banner, Card, Empty, Tile } from "../components/ui";

type Nav = Navigator & {
  bluetooth?: {
    requestDevice(o: unknown): Promise<{
      name?: string;
      gatt?: {
        connect(): Promise<{
          getPrimaryService(uuid: string): Promise<{
            getCharacteristic(uuid: string): Promise<{
              startNotifications(): Promise<unknown>;
              stopNotifications(): Promise<unknown>;
              addEventListener(t: string, cb: (e: Event) => void): void;
            }>;
          }>;
        }>;
        disconnect(): void;
      };
    }>;
  };
};

export const bluetoothAvailable = () => Boolean((navigator as Nav).bluetooth);

/** Распаковка пакета по формату профиля. Только байты → числа, без обработки. */
export function decodePacket(
  buffer: ArrayBufferLike, format: string, channels: string[],
): Record<string, number[]> {
  const view = new DataView(buffer as ArrayBuffer);
  const out: Record<string, number[]> = {};
  for (const c of channels) out[c] = [];
  if (format !== "int16_le") return out;      // иных форматов профиль не объявлял
  const perSample = 2;
  const frame = channels.length * perSample;
  for (let off = 0; off + frame <= view.byteLength; off += frame) {
    channels.forEach((c, i) => {
      out[c].push(view.getInt16(off + i * perSample, true));
    });
  }
  return out;
}

export function BleCapture({ profiles, onCapture, disabled }: {
  profiles: BleProfile[];
  onCapture: (payload: {
    profile: string;
    channels: Record<string, number[]>;
    timestamps_ms: number[];
    device_serial?: string;
  }) => Promise<void>;
  disabled?: boolean;
}) {
  // Профили датчиков грузятся запросом и на первом рендере пусты — значение по
  // умолчанию, снятое с пустого списка, осталось бы "" навсегда: в списке
  // нарисован первый профиль, а запись не начинается вовсе (тот же дефект, что
  // и с выбором сессии).
  const [profile, setProfile] = useState("");
  const [state, setState] = useState<"idle" | "connecting" | "recording" | "sending">("idle");
  const [error, setError] = useState<string | null>(null);
  const [device, setDevice] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const available = bluetoothAvailable();
  const spec = profiles.find((p) => p.code === profile);

  useEffect(() => {
    if (profiles.length === 0) return;
    if (!profile || !profiles.some((p) => p.code === profile)) setProfile(profiles[0].code);
  }, [profiles, profile]);

  async function capture() {
    const p = profiles.find((x) => x.code === profile);
    if (!p) return;
    setError(null); setState("connecting"); setCounts({});
    const channels: Record<string, number[]> = {};
    const timestamps: number[] = [];
    p.channel_order.forEach((c) => { channels[c] = []; });

    try {
      const bt = (navigator as Nav).bluetooth!;
      const dev = await bt.requestDevice({ filters: [{ services: [p.service_uuid] }] });
      const gatt = await dev.gatt!.connect();
      const service = await gatt.getPrimaryService(p.service_uuid);
      const data = await service.getCharacteristic(p.data_characteristic);
      setDevice(dev.name ?? "датчик");
      setState("recording");

      const started = performance.now();
      data.addEventListener("characteristicvaluechanged", (e: Event) => {
        const value = (e.target as unknown as { value: DataView }).value;
        const packet = decodePacket(
          value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength),
          p.sample_format, p.channel_order,
        );
        for (const [c, xs] of Object.entries(packet)) channels[c].push(...xs);
        // Метка прихода пакета: по ним сервер считает фактическую частоту и
        // потери. Клиент их только фиксирует — выводов не делает.
        timestamps.push(performance.now() - started);
        setCounts(Object.fromEntries(
          Object.entries(channels).map(([c, xs]) => [c, xs.length])));
      });
      await data.startNotifications();

      // Длительность пробы задаёт протокол, здесь — фиксированное окно записи.
      await new Promise((r) => setTimeout(r, 10_000));
      await data.stopNotifications().catch(() => undefined);
      dev.gatt!.disconnect();

      const total = Object.values(channels).reduce((s, x) => s + x.length, 0);
      if (total === 0) {
        setError("датчик не отправил ни одного пакета: проверьте, включён ли он "
                 + "и совпадает ли профиль");
        setState("idle");
        return;
      }
      setState("sending");
      await onCapture({ profile: p.code, channels, timestamps_ms: timestamps,
                        device_serial: dev.name });
      setState("idle");
    } catch (e) {
      setError((e as Error).message);
      setState("idle");
    }
  }

  return (
    <Card>
      <div className="row">
        <span className="tile-label">Профиль датчика</span>
        <select className="pill" style={{ minWidth: 260 }} value={profile}
                onChange={(e) => setProfile(e.target.value)}>
          {profiles.map((p) => (
            <option key={p.code} value={p.code}>
              {p.label_ru} · {p.channels_per_packet} кан. · {p.fs_hz} Гц
            </option>
          ))}
        </select>
        <button className="pill primary" disabled={disabled || !available || state !== "idle"}
                onClick={capture}>
          {state === "idle" ? "Записать 10 с"
            : state === "connecting" ? "Соединение…"
            : state === "recording" ? "Запись…" : "Отправка…"}
        </button>
      </div>

      {!available && (
        <Banner text={
          "Web Bluetooth в этом браузере недоступен. Он есть в Chrome и Edge на " +
          "настольных системах и Android; в Safari и на iOS его нет и не " +
          "планируется — там данные загружаются файлом выгрузки."
        } />
      )}
      {error && <Banner text={error} />}

      {spec && !spec.verified && (
        <p className="tile-hint">
          Профиль описан по документации, но <strong>на железе не проверен</strong>:
          коэффициент к микровольтам ({spec.unit_scale_uv} мкВ на разряд) взят из
          описания. Ошибка в нём даёт правдоподобные, но неверные амплитуды —
          каждая запись по такому профилю помечается флагом.
        </p>
      )}

      {Object.keys(counts).length > 0 && (
        <div className="grid cols-4" style={{ marginTop: 12 }}>
          {Object.entries(counts).map(([c, n]) => (
            <Tile key={c} label={c} value={n} hint="отсчётов принято" />
          ))}
        </div>
      )}
      {device && state === "idle" && Object.keys(counts).length === 0 && (
        <Empty text={`Датчик «${device}» отсоединён.`} />
      )}
      <p className="tile-hint">
        На сервер уходят отсчёты и метки времени, а не готовые RMS: расчёт §9.8
        должен быть воспроизводимым, и версия браузера в него входить не должна.
      </p>
    </Card>
  );
}
