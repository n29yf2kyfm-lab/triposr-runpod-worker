// Known BLE OBD dongle GATT UUIDs (shared with the Python registry).
// BLE OBD dongles use a "serial over BLE" pattern: write commands to one
// characteristic, receive NOTIFY responses on another (sometimes the same).

export interface DongleProfile {
  name: string;
  service: string;
  writeChar: string;
  notifyChar: string;
  stn: boolean; // STN chip → monitor mode / CAN filters (coding + RE)
}

const u16 = (x: string) => `0000${x.toLowerCase()}-0000-1000-8000-00805f9b34fb`;

export const DONGLES: DongleProfile[] = [
  { name: "Vgate/ELM327 FFE0", service: u16("ffe0"), writeChar: u16("ffe1"), notifyChar: u16("ffe1"), stn: false },
  { name: "ELM327 FFF0",       service: u16("fff0"), writeChar: u16("fff2"), notifyChar: u16("fff1"), stn: false },
  {
    name: "OBDLink STN (NUS)",
    service: "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
    writeChar: "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
    notifyChar: "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
    stn: true,
  },
];

export const NAME_HINTS = ["obd", "elm", "vlink", "obdlink", "vgate", "icar", "viecar", "konnwei"];

export const looksLikeObd = (name?: string | null) =>
  !!name && NAME_HINTS.some((h) => name.toLowerCase().includes(h));
