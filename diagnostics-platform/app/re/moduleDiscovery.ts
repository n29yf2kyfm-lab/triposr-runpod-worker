/**
 * Phone-side module discovery — the "scan my car" reverse-engineering flow.
 *
 * Mirrors re_tools/module_discovery.py but runs over the BLE dongle from the app:
 * sweep 0x700-0x7FF with UDS TesterPresent, read each responder's identity, decode
 * the VIN. Read-only (0x3E / 0x22). Results can be POSTed to the API to onboard the
 * vehicle (create platform + ecu rows).
 */
import { ObdConnection } from "../bluetooth/obdBle";

export interface DiscoveredModule {
  respId: number;
  name: string;
  vin?: string;
  part?: string;
  sw?: string;
}

const MODULE_NAMES: Record<number, string> = {
  0x700: "OBD gateway", 0x701: "Engine ECU", 0x703: "ABS / ESP", 0x704: "Transmission",
  0x706: "Instrument cluster", 0x707: "Airbag (SRS)", 0x709: "Body / BCM",
  0x70c: "Power steering", 0x70e: "Climate", 0x712: "Infotainment", 0x713: "Radar / ACC",
  0x715: "Immobilizer / ESL", 0x717: "Headlights", 0x718: "TPMS", 0x71a: "Camera / lane",
  0x71f: "Battery mgmt", 0x7e0: "Engine ECU", 0x7e1: "Transmission",
};

const IDENTS: Record<string, keyof DiscoveredModule> = { F190: "vin", F187: "part", F189: "sw" };

/** Header-aware ELM327 parse (ATH1 + ATCAF1): "7E8 7E 00" → {rid, data}. */
export function parseResponse(text: string): { rid: number; data: number[] }[] {
  const out: { rid: number; data: number[] }[] = [];
  for (const line of text.split(/\r?\n/)) {
    const toks = line.trim().split(/\s+/);
    if (toks.length < 2 || !/^[0-9a-fA-F]+$/.test(toks[0])) continue;
    const rid = parseInt(toks[0], 16);
    const data = toks.slice(1).filter((t) => t.length === 2).map((t) => parseInt(t, 16));
    if (data.length) out.push({ rid, data });
  }
  return out;
}

const hex3 = (n: number) => n.toString(16).toUpperCase().padStart(3, "0");
const ascii = (bytes: number[]) =>
  bytes.filter((b) => b >= 32 && b < 127).map((b) => String.fromCharCode(b)).join("").trim();

export interface ScanProgress { address: number; total: number; found: number; }

export async function scanModules(
  obd: ObdConnection,
  onProgress?: (p: ScanProgress) => void,
  range: [number, number] = [0x700, 0x7ff],
): Promise<DiscoveredModule[]> {
  await obd.command("ATCAF1"); // auto ISO-TP framing + multi-frame reassembly
  await obd.command("ATH1");   // show responder header
  const [lo, hi] = range;
  const found: DiscoveredModule[] = [];

  for (let mid = lo; mid <= hi; mid++) {
    await obd.setHeader(hex3(mid));
    const resp = await obd.sendRaw("3E00", 800);
    for (const { rid, data } of parseResponse(resp)) {
      if (data[0] === 0x7e) {
        found.push({ respId: rid, name: MODULE_NAMES[rid] ?? MODULE_NAMES[mid] ?? `Module ${hex3(rid)}` });
        break;
      }
    }
    onProgress?.({ address: mid, total: hi - lo + 1, found: found.length });
  }

  // read identity from each responder
  for (const m of found) {
    const req = m.respId >= 0x7e8 ? m.respId - 8 : m.respId;
    await obd.setHeader(hex3(req));
    for (const [did, field] of Object.entries(IDENTS)) {
      const resp = await obd.sendRaw("22" + did, 1200);
      for (const { data } of parseResponse(resp)) {
        if (data[0] === 0x62 && data.length > 3) {
          const v = ascii(data.slice(3));
          if (v) (m as any)[field] = v;
          break;
        }
      }
    }
  }
  return found;
}

/** VIN → make (World Manufacturer Identifier, first 3 chars). Mirrors onboard.py. */
export function decodeVin(vin?: string): { make: string | null; family: string | null } {
  const WMI: Record<string, [string, string]> = {
    WVW: ["VAG", "VW"], WAU: ["VAG", "Audi"], TMB: ["VAG", "Skoda"], VSS: ["VAG", "SEAT"],
    WBA: ["BMW", "BMW"], WBS: ["BMW", "BMW-M"], WBY: ["BMW", "BMW-i"], "5UX": ["BMW", "BMW-X"],
    JTD: ["Toyota", "Toyota"], JTH: ["Toyota", "Lexus"], VF1: ["Renault", "Renault"],
    VF3: ["PSA", "Peugeot"], VF7: ["PSA", "Citroen"], WF0: ["Ford", "Ford"], WDD: ["Mercedes", "Mercedes"],
  };
  const [make, family] = WMI[(vin ?? "").slice(0, 3).toUpperCase()] ?? [null, null];
  return { make, family };
}

export function findVin(modules: DiscoveredModule[]): string | undefined {
  return modules.find((m) => m.vin)?.vin;
}
