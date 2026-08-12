/**
 * OBD BLE connection for the phone app.
 *
 * Backends:
 *   - Capacitor BLE (@capacitor-community/bluetooth-le)  → iOS + Android (the real app)
 *   - Web Bluetooth                                      → Android/desktop Chrome (dev/testing)
 *
 * iOS Safari has NO Web Bluetooth — ship the app via Capacitor for iPhone. See BLUETOOTH.md.
 *
 * Exposes an ELM327 command interface: initialize(), command(), readDtcs().
 * The heavy coding/UDS logic lives server-side (coding_engine); the app sends
 * high-level intents to the API and uses this only for the live dongle link.
 */
import { DONGLES, DongleProfile, looksLikeObd } from "./dongles";

type Backend = "capacitor" | "web";

export interface ObdTransport {
  connect(): Promise<DongleProfile>;
  write(bytes: Uint8Array): Promise<void>;
  onNotify(cb: (chunk: Uint8Array) => void): void;
  disconnect(): Promise<void>;
}

const PROMPT = 0x3e; // '>'

export class ObdConnection {
  private buf: number[] = [];
  private profile!: DongleProfile;

  constructor(private transport: ObdTransport) {}

  static detectBackend(): Backend {
    // Capacitor injects a global; prefer native BLE when present (works on iOS).
    const w = globalThis as any;
    if (w.Capacitor?.isNativePlatform?.()) return "capacitor";
    return "web";
  }

  async connect(): Promise<DongleProfile> {
    this.profile = await this.transport.connect();
    this.transport.onNotify((chunk) => {
      for (const b of chunk) this.buf.push(b);
    });
    await this.initialize();
    return this.profile;
  }

  /** Send an ELM327 line and read back until the '>' prompt (or timeout). */
  async command(cmd: string, timeoutMs = 5000): Promise<string> {
    this.buf = [];
    await this.transport.write(new TextEncoder().encode(cmd + "\r"));
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (this.buf.includes(PROMPT)) break;
      await sleep(20);
    }
    const text = new TextDecoder().decode(new Uint8Array(this.buf));
    return text.replace(/\r/g, "\n").replace(/>/g, "").trim();
  }

  async initialize(protocol = "0"): Promise<void> {
    for (const cmd of ["ATZ", "ATE0", "ATL0", "ATS0", "ATH1", `ATSP${protocol}`]) {
      await this.command(cmd, cmd === "ATZ" ? 2500 : 1200);
    }
  }

  async readDtcs(): Promise<string[]> {
    return parseDtcs(await this.command("03"));
  }

  async setHeader(hex: string) { await this.command(`ATSH${hex}`); }
  async sendRaw(hex: string, timeoutMs = 5000) { return this.command(hex, timeoutMs); }

  disconnect() { return this.transport.disconnect(); }
}

/* ---- Capacitor BLE backend (iOS + Android) ------------------------------- */
export class CapacitorBleTransport implements ObdTransport {
  private deviceId = "";
  private profile!: DongleProfile;
  private ble: any;

  async connect(): Promise<DongleProfile> {
    // dynamic import so the web build doesn't hard-depend on the native plugin
    const { BleClient } = await import("@capacitor-community/bluetooth-le");
    this.ble = BleClient;
    await this.ble.initialize();
    const device = await this.ble.requestDevice({
      services: DONGLES.map((d) => d.service),
      optionalServices: DONGLES.map((d) => d.service),
    });
    if (!looksLikeObd(device.name) && !device.name) {
      // still allow — user picked it in the native chooser
    }
    await this.ble.connect(device.deviceId);
    this.deviceId = device.deviceId;
    // resolve profile by which service the device advertises
    this.profile =
      DONGLES.find((d) => (device.uuids || []).includes(d.service)) || DONGLES[0];
    return this.profile;
  }

  async write(bytes: Uint8Array) {
    await this.ble.write(
      this.deviceId, this.profile.service, this.profile.writeChar,
      new DataView(bytes.buffer),
    );
  }

  onNotify(cb: (chunk: Uint8Array) => void) {
    this.ble.startNotifications(
      this.deviceId, this.profile.service, this.profile.notifyChar,
      (value: DataView) => cb(new Uint8Array(value.buffer)),
    );
  }

  async disconnect() { if (this.deviceId) await this.ble.disconnect(this.deviceId); }
}

/* ---- Web Bluetooth backend (Android / desktop Chrome — dev/testing) ------ */
export class WebBluetoothTransport implements ObdTransport {
  private char!: any;
  private profile!: DongleProfile;

  async connect(): Promise<DongleProfile> {
    const nav = navigator as any;
    if (!nav.bluetooth) throw new Error("Web Bluetooth unavailable (iOS has none — use Capacitor).");
    const device = await nav.bluetooth.requestDevice({
      filters: DONGLES.map((d) => ({ services: [d.service] })),
      optionalServices: DONGLES.map((d) => d.service),
    });
    const server = await device.gatt.connect();
    for (const p of DONGLES) {
      try {
        const svc = await server.getPrimaryService(p.service);
        this.char = await svc.getCharacteristic(p.notifyChar);
        this.writeChar = await svc.getCharacteristic(p.writeChar);
        this.profile = p;
        return p;
      } catch { /* try next profile */ }
    }
    throw new Error("No known OBD GATT service on this device.");
  }
  private writeChar!: any;

  async write(bytes: Uint8Array) { await this.writeChar.writeValueWithoutResponse(bytes); }

  onNotify(cb: (chunk: Uint8Array) => void) {
    this.char.startNotifications();
    this.char.addEventListener("characteristicvaluechanged", (e: any) =>
      cb(new Uint8Array(e.target.value.buffer)),
    );
  }

  async disconnect() { /* handled by GATT server lifecycle */ }
}

/** Pick the right backend for the current platform. */
export function createObdConnection(): ObdConnection {
  const backend = ObdConnection.detectBackend();
  const transport = backend === "capacitor" ? new CapacitorBleTransport() : new WebBluetoothTransport();
  return new ObdConnection(transport);
}

/* ---- helpers ------------------------------------------------------------- */
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function parseDtcs(resp: string): string[] {
  const hexes = resp.replace(/\n/g, " ").split(/\s+/).filter((h) => h.length === 2);
  const start = hexes.indexOf("43");
  const body = start >= 0 ? hexes.slice(start + 1) : hexes;
  const codes: string[] = [];
  for (let i = 0; i + 1 < body.length; i += 2) {
    const a = parseInt(body[i], 16), b = parseInt(body[i + 1], 16);
    if (!a && !b) continue;
    const letter = "PCBU"[(a & 0xc0) >> 6];
    codes.push(`${letter}${(a >> 4) & 0x3}${(a & 0xf).toString(16).toUpperCase()}${b.toString(16).padStart(2, "0").toUpperCase()}`);
  }
  return codes;
}
