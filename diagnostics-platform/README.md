# Expert Car Check — Diagnostics & Coding Platform

The engineering foundation for a Carly/OBDeleven-class **diagnostics + coding** engine:
read fault codes, live data, and **program manufacturer features** (BMW FDL coding, VAG
long-coding & adaptations) over **CAN and CAN-FD**, with everything stored in **Supabase**
and an **AI layer grounded on that data**.

> ⚠️ **Read [`SAFETY.md`](./SAFETY.md) before writing to any vehicle.** Coding is legitimate,
> but writes to ABS/airbag or module flashing can permanently brick a control unit, and some
> operations are legally gated (SFD, secure gateway, emissions). This framework is built
> defensively: every write is previewed, reversible, and logged.

---

## The three layers

| Layer | What it is | Status here |
|-------|-----------|-------------|
| **1. Talk to the car** | OBD-II + UDS (ISO 14229) over CAN / CAN-FD | ✅ Built (`coding_engine/transport.py`, `uds_client.py`) |
| **2. The coding map** | Per-ECU definitions: which DID/bit does what | 🗄️ Schema built; **you supply the data** (your licensed defs → `ingest/`) |
| **3. Intelligence** | AI that explains faults & guides coding | ✅ RAG design built (`ai/`) |

The protocol (Layer 1) is free and standardised. The **value and the moat is Layer 2** — the
per-car coding definitions. This repo gives you the schema, the ingest pipeline, and the
runtime engine that *applies* those definitions. The definitions themselves come from your
licensed sources (BMW PSdZData/CAFD, VCDS labels, your own reverse-engineering).

---

## Architecture

```
                    ┌─────────────────────────────┐
   Phone app  ◄────►│  API (edge fn / FastAPI)     │
 (Lovable UI)       └──────────────┬──────────────┘
                                   │
              ┌────────────────────┼─────────────────────┐
              ▼                    ▼                     ▼
   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
   │  coding_engine/  │  │    Supabase      │  │      ai/         │
   │  UDS over        │  │  Postgres +      │  │  RAG over the    │
   │  CAN / CAN-FD    │◄─┤  pgvector        ├─►│  coding KB       │
   │  BMW + VAG       │  │  defs · DTC ·    │  │  (Claude)        │
   │                  │  │  audit log       │  │                  │
   └────────┬─────────┘  └──────────────────┘  └──────────────────┘
            ▼
   OBD-II dongle (ELM327 / OBDLink / J2534)  ──►  Vehicle
```

### Why CAN **and** CAN-FD
A single transport factory (`transport.py`) picks the bus + ISO-TP parameters from the
**vehicle profile** stored in Supabase:

| Make | Chassis / platform | Bus |
|------|--------------------|-----|
| BMW  | E / F series (≈ pre-2018) | Classic CAN 500 kbps |
| BMW  | G / I series (2018+) | **CAN-FD** (500k/2M); Ethernet/DoIP for flashing |
| VAG  | MQB, PQ | Classic CAN |
| VAG  | MQB-Evo, MEB (2020+) | **CAN-FD** + SFD lock |

### Why RAG, not fine-tuning (for coding)
Fine-tuning a model to output coding *values* is dangerous — a hallucinated byte can brick a
module. Instead:
- Coding definitions live as **exact rows** in Postgres.
- We embed their **descriptions** (pgvector) so the AI can *find* the right definition from a
  natural-language request ("fold the mirrors when I lock it").
- The AI **explains and guides**; the **write value is read verbatim from the DB row**, never
  generated. Every answer cites the exact `coding_definition.id` it used.
- Fine-tuning is reserved later for *tone* of fault explanations, not for values.

See [`ai/README.md`](./ai/README.md).

---

## Layout

```
diagnostics-platform/
├── README.md                  ← you are here
├── SAFETY.md                  ← mandatory read before any write
├── db/
│   ├── schema.sql             ← Supabase schema (Postgres + pgvector)
│   └── seed_example.sql       ← a couple of demo coding defs + DTCs
├── PROTOCOLS.md               ← diagnostic protocol + tool per manufacturer
├── BLUETOOTH.md               ← dongle layer, iOS constraint, RE workflow
├── coding_engine/
│   ├── requirements.txt
│   ├── transport.py           ← CAN / CAN-FD + ISO-TP factory
│   ├── uds_client.py          ← udsoncan wrapper (read/write DID, routines)
│   ├── security.py            ← seed→key & SFD token plug-in interfaces
│   ├── supabase_store.py      ← fetch defs, write audit log
│   ├── ble/                   ← Bluetooth OBD dongle (laptop/RE side, via bleak)
│   │   ├── dongle_registry.py ← known BLE dongle GATT UUIDs
│   │   ├── elm327.py          ← ELM327/STN AT protocol (OBD, raw CAN, monitor)
│   │   └── ble_dongle.py      ← bleak BLE transport
│   ├── platforms/
│   │   ├── coders.py          ← shared coding mechanics + policy gates
│   │   ├── bmw.py  vag.py     ← FDL / long-coding + adaptations
│   │   └── toyota.py french.py← Toyota + Renault/PSA (UDS/CAN; K-Line notes)
│   └── examples/
│       └── read_and_code.py   ← runnable demo (works against ELM327-emulator)
├── re_tools/                  ← reverse-engineering, driven by the dongle
│   ├── can_sniffer.py         ← capture + diff CAN frames (find coding signals)
│   └── uds_scan.py            ← sweep DIDs (0x22) to locate coding blocks
├── app/bluetooth/             ← phone-app BLE (TypeScript)
│   ├── obdBle.ts              ← Capacitor BLE (iOS+Android) + Web Bluetooth fallback
│   └── dongles.ts             ← dongle registry (mirrors the Python one)
├── api/                       ← FastAPI: thin-transport/smart-server keystone
│   ├── main.py                ← DTC decode, coding list+preview+apply, RAG assistant
│   └── models.py              ← request/response schemas
├── ai/
│   ├── README.md              ← RAG vs fine-tune decision
│   ├── embeddings.py          ← build pgvector embeddings from the KB
│   └── rag.py                 ← retrieve + explain/guide with Claude
└── ingest/
    ├── ingest_dtc.py          ← load an open DTC database into Supabase
    ├── ingest_vag_labels.py   ← parse plaintext VCDS labels → coding_definitions
    ├── ingest_coding_csv.py   ← generic coding-definition CSV loader (BMW/any brand)
    └── samples/               ← real-format sample sources (proven working)
        ├── 09-central-electronics.lbl   (VAG plaintext label)
        └── bmw_fem_features.csv          (BMW FDL feature list)
```

### Loading your own BMW / VAG definitions
The pipeline is proven on the sample files (run with `--dry-run` to see it parse
with no DB):

```bash
# VAG — plaintext VCDS labels → coding definitions
python ingest/ingest_vag_labels.py --labels ingest/samples/09-central-electronics.lbl --dry-run
python ingest/ingest_vag_labels.py --labels ./your-plaintext-labels/ --ecu-id <ecu-uuid>

# BMW (or any brand) — export your feature list to CSV, then:
python ingest/ingest_coding_csv.py --csv ingest/samples/bmw_fem_features.csv --dry-run
python ingest/ingest_coding_csv.py --csv ./your-bmw-features.csv --ecu-id <ecu-uuid>

# then make everything RAG-searchable
python ai/embeddings.py
```

> BMW FDL definitions derive from CAFD/PSdZData (proprietary, binary) — don't parse
> that here. Export the human feature list to CSV and load it with `ingest_coding_csv.py`.
> Only ingest plaintext/licensed sources you're entitled to use (see `SAFETY.md`).

## Quick start

```bash
# 1. Create the Supabase schema
psql "$SUPABASE_DB_URL" -f db/schema.sql

# 2. Install the engine
pip install -r coding_engine/requirements.txt

# 3. Seed some data (open DTC DB + your own coding defs)
python ingest/ingest_dtc.py --source ./dtc-database.sqlite
python ingest/ingest_vag_labels.py --labels ./your-vcds-labels/

# 4. Try it (no car needed — runs against the ELM327 emulator)
python coding_engine/examples/read_and_code.py --dry-run
```

Environment (`.env`):
```
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
SUPABASE_DB_URL=postgres://...
ANTHROPIC_API_KEY=...
EMBEDDINGS_PROVIDER=voyage        # or openai
EMBEDDINGS_API_KEY=...
```
