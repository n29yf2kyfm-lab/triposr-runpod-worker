/**
 * "Scan my car" — guided reverse-engineering flow (React).
 *
 * Connects the BLE dongle, sweeps for every ECU with live progress, decodes the
 * VIN, lists what it found, and offers to onboard the vehicle (POST to the API,
 * which creates the platform + ecu rows). Drop into the Lovable app.
 *
 * Read-only scan (UDS 0x3E / 0x22).
 */
import React, { useState } from "react";
import { createObdConnection } from "../bluetooth/obdBle";
import { scanModules, decodeVin, findVin, DiscoveredModule } from "./moduleDiscovery";

type Phase = "idle" | "connecting" | "scanning" | "done" | "error";

const API = (path: string) => `${(globalThis as any).ECC_API_BASE ?? ""}${path}`;

export function ScanMyCar() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [pct, setPct] = useState(0);
  const [count, setCount] = useState(0);
  const [modules, setModules] = useState<DiscoveredModule[]>([]);
  const [vehicle, setVehicle] = useState<{ vin?: string; make: string | null; family: string | null }>();
  const [error, setError] = useState<string>();
  const [onboarded, setOnboarded] = useState(false);

  async function run() {
    setPhase("connecting"); setError(undefined); setModules([]); setOnboarded(false);
    try {
      const obd = createObdConnection();
      await obd.connect();
      setPhase("scanning");
      const found = await scanModules(obd, (p) => {
        setPct(Math.round(((p.address - 0x700) / p.total) * 100));
        setCount(p.found);
      });
      await obd.disconnect();
      const vin = findVin(found);
      setModules(found);
      setVehicle({ vin, ...decodeVin(vin) });
      setPhase("done");
    } catch (e: any) {
      setError(e?.message ?? String(e));
      setPhase("error");
    }
  }

  async function onboard() {
    const res = await fetch(API("/onboard"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ vin: vehicle?.vin, make: vehicle?.make, modules }),
    });
    if (res.ok) setOnboarded(true);
  }

  return (
    <div className="scan-my-car">
      {phase === "idle" && (
        <button className="scan-btn" onClick={run}>Scan my car</button>
      )}

      {phase === "connecting" && <p>Connecting to your OBD dongle…</p>}

      {phase === "scanning" && (
        <div className="scan-progress">
          <p>Finding control units… {count} found</p>
          <div className="bar"><div className="fill" style={{ width: `${pct}%` }} /></div>
          <small>{pct}%</small>
        </div>
      )}

      {phase === "error" && (
        <div className="scan-error">
          <p>Couldn’t scan: {error}</p>
          {/iOS|Web Bluetooth/.test(error ?? "") && (
            <small>On iPhone the app needs the native (Capacitor) build — see BLUETOOTH.md.</small>
          )}
          <button onClick={run}>Try again</button>
        </div>
      )}

      {phase === "done" && (
        <div className="scan-result">
          <h3>{vehicle?.make ? `${vehicle.make} ${vehicle.family ?? ""}` : "Vehicle scanned"}</h3>
          {vehicle?.vin && <p className="vin">VIN {vehicle.vin}</p>}
          <p>{modules.length} control units found</p>
          <ul>
            {modules.map((m) => (
              <li key={m.respId}>
                <b>{m.name}</b>
                {m.part && <span> · {m.part}</span>}
                {m.sw && <span> · sw {m.sw}</span>}
              </li>
            ))}
          </ul>
          {!onboarded ? (
            <button onClick={onboard}>Add this car to my garage</button>
          ) : (
            <p className="ok">✓ Car onboarded — coding features are being prepared.</p>
          )}
        </div>
      )}
    </div>
  );
}
