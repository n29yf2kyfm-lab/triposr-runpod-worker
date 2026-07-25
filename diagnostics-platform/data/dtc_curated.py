"""
DTC Database — generic OBD-II (SAE J2012) codes + manufacturer-specific highlights.

Structure:  CODE: (short description, plain-language explanation, common causes)
Generic codes (P0/P2 etc.) are standardized and identical on every car.
Manufacturer codes (P1xxx etc.) vary by brand — the most common are included here.
"""

# Each entry: (title, plain-english explanation, common causes)
GENERIC = {
    "P0100": ("Mass Air Flow (MAF) Circuit Malfunction",
              "The engine computer (ECU) is getting no signal or a bad signal from the "
              "mass air flow sensor, which measures how much air enters the engine.",
              "Faulty MAF sensor, dirty sensor element, broken wiring, air leak after the sensor."),
    "P0101": ("MAF Circuit Range/Performance",
              "The MAF sensor reading is outside the expected range for current engine conditions.",
              "Dirty MAF sensor, intake air leak, clogged air filter."),
    "P0113": ("Intake Air Temperature Sensor Circuit High",
              "The intake air temperature sensor is reporting an unrealistically cold reading "
              "(high voltage), usually an open circuit.",
              "Disconnected sensor, broken wire, faulty sensor."),
    "P0116": ("Coolant Temperature Sensor Range/Performance",
              "The coolant temperature reading doesn't match how the engine is actually running.",
              "Faulty coolant temp sensor, stuck thermostat, low coolant."),
    "P0121": ("Throttle Position Sensor Range/Performance",
              "The throttle position signal is implausible compared to other engine data.",
              "Dirty throttle body, worn TPS, wiring fault."),
    "P0130": ("O2 Sensor Circuit (Bank 1 Sensor 1)",
              "The upstream oxygen sensor on bank 1 is not producing a valid signal.",
              "Faulty O2 sensor, wiring damage, exhaust leak."),
    "P0135": ("O2 Sensor Heater Circuit (Bank 1 Sensor 1)",
              "The heater inside the upstream oxygen sensor isn't working, so the sensor "
              "warms up too slowly after a cold start.",
              "Blown fuse, faulty sensor heater element, wiring fault."),
    "P0171": ("System Too Lean (Bank 1)",
              "The engine is running with too much air / too little fuel on bank 1.",
              "Vacuum leak, weak fuel pump, clogged injectors, dirty MAF."),
    "P0172": ("System Too Rich (Bank 1)",
              "The engine is running with too much fuel on bank 1.",
              "Leaking injector, faulty fuel pressure regulator, bad O2 sensor."),
    "P0300": ("Random/Multiple Cylinder Misfire",
              "Multiple cylinders are misfiring — the air/fuel mixture isn't igniting properly.",
              "Worn spark plugs/coils, vacuum leak, low fuel pressure, compression issues."),
    "P0301": ("Cylinder 1 Misfire Detected",
              "Cylinder 1 specifically is misfiring.",
              "Bad spark plug, failed ignition coil, faulty injector on cylinder 1."),
    "P0302": ("Cylinder 2 Misfire Detected",
              "Cylinder 2 specifically is misfiring.",
              "Bad spark plug, failed ignition coil, faulty injector on cylinder 2."),
    "P0303": ("Cylinder 3 Misfire Detected",
              "Cylinder 3 specifically is misfiring.",
              "Bad spark plug, failed ignition coil, faulty injector on cylinder 3."),
    "P0304": ("Cylinder 4 Misfire Detected",
              "Cylinder 4 specifically is misfiring.",
              "Bad spark plug, failed ignition coil, faulty injector on cylinder 4."),
    "P0325": ("Knock Sensor Circuit (Bank 1)",
              "The knock sensor, which detects engine knocking/pre-ignition, has a circuit fault.",
              "Faulty knock sensor, damaged wiring, poor sensor ground."),
    "P0340": ("Camshaft Position Sensor Circuit (Bank 1)",
              "The ECU can't see a valid camshaft position signal.",
              "Faulty cam sensor, wiring fault, timing chain/belt problem."),
    "P0401": ("EGR Flow Insufficient",
              "The exhaust gas recirculation system isn't flowing enough exhaust gas back "
              "into the intake.",
              "Clogged EGR valve or passages, faulty EGR valve/solenoid."),
    "P0420": ("Catalyst System Efficiency Below Threshold (Bank 1)",
              "The catalytic converter on bank 1 isn't cleaning the exhaust as well as it should.",
              "Worn-out catalytic converter, exhaust leak, faulty downstream O2 sensor, "
              "engine misfire damaging the cat."),
    "P0440": ("EVAP System Malfunction",
              "A general fault in the evaporative emissions system (fuel vapor control).",
              "Loose/damaged fuel cap, cracked EVAP hose, faulty purge or vent valve."),
    "P0442": ("EVAP Small Leak Detected",
              "There's a small leak in the fuel vapor system — often the fuel cap.",
              "Loose or worn fuel cap, small crack in a vapor hose, faulty purge valve seal."),
    "P0455": ("EVAP Large Leak Detected",
              "There's a large leak in the fuel vapor system.",
              "Fuel cap missing/very loose, disconnected or split vapor hose, stuck vent valve."),
    "P0500": ("Vehicle Speed Sensor Malfunction",
              "The ECU isn't getting a valid road-speed signal.",
              "Faulty speed sensor, wiring fault, ABS module issue."),
    "P0505": ("Idle Control System Malfunction",
              "The engine can't hold a steady idle speed.",
              "Dirty throttle body/idle valve, vacuum leak, faulty idle air control valve."),
    "P0600": ("Serial Communication Link Malfunction",
              "The ECU has a problem communicating over its internal data bus.",
              "Wiring fault on the CAN bus, failing control module, poor grounds."),
    "P0700": ("Transmission Control System Malfunction",
              "The transmission control module has requested the check-engine light — "
              "there's a transmission fault stored; scan the gearbox module for details.",
              "Various — read transmission module codes."),
    "P0705": ("Transmission Range Sensor Circuit",
              "The sensor reporting which gear selector position is chosen (P/R/N/D) is faulty.",
              "Faulty range sensor, misadjusted linkage, wiring fault."),
    "U0100": ("Lost Communication with ECM/PCM",
              "A module on the car's network can't talk to the engine computer.",
              "CAN bus wiring fault, blown ECU fuse, failing module."),
    "U0101": ("Lost Communication with TCM",
              "A module can't talk to the transmission control module.",
              "CAN wiring fault, TCM power/ground issue, failing TCM."),
    "U0121": ("Lost Communication with ABS Module",
              "A module can't talk to the ABS/brake control module.",
              "CAN wiring fault, ABS module power issue, failing ABS module."),
    "B0001": ("Driver Airbag Circuit (Stage 1)",
              "There's a fault in the driver's frontal airbag deployment circuit.",
              "Clockspring failure, disconnected airbag connector, faulty airbag unit."),
    "C0035": ("Left Front Wheel Speed Sensor Circuit",
              "The ABS system sees a fault in the left-front wheel speed sensor circuit.",
              "Faulty sensor, damaged tone ring, wiring fault."),
}

MANUFACTURER = {
    "VAG (VW / Audi / Skoda / Seat)": {
        "P0299": ("Turbo/Supercharger Underboost",
                  "The turbo isn't producing the boost pressure the ECU expects. Very common "
                  "on VW/Audi TSI/TDI engines.",
                  "Boost hose split or loose, sticking VNT turbo vanes, faulty N75 boost valve, "
                  "failing diverter valve."),
        "P2015": ("Intake Manifold Flap Position Sensor (Bank 1)",
                  "The intake manifold runner/flap position is implausible. Classic fault on "
                  "2.0 TSI (EA888) and TDI engines.",
                  "Failed flap motor, broken plastic linkage, carbon buildup jamming the flaps."),
        "P2187": ("System Too Lean at Idle (Bank 1)",
                  "Too much air at idle — usually a vacuum leak. Common on VAG 2.0T engines "
                  "from the PCV valve diaphragm.",
                  "Failed PCV valve, intake gasket leak, split vacuum hose."),
        "P0011": ("Camshaft Timing Over-Advanced (Bank 1)",
                  "The intake cam timing is more advanced than commanded.",
                  "Faulty cam adjuster solenoid (N205), stretched timing chain, low oil."),
        "P053F": ("Cold Start Fuel Pressure Performance",
                  "Fuel pressure behavior during cold start is out of range — seen on "
                  "direct-injection VAG engines.",
                  "Carboned injectors, weak high-pressure fuel pump, faulty fuel pressure sensor."),
        "P2563": ("Turbocharger Boost Control Position Sensor",
                  "The turbo actuator position feedback doesn't match what the ECU commands — "
                  "common on VAG diesels.",
                  "Sticking VNT mechanism, faulty actuator, vacuum/boost control leak."),
    },
    "BMW": {
        "P1188": ("Fuel Control (Bank 1 Sensor 1)",
                  "BMW-specific: fuel trim control fault on bank 1, mixture adaptation at limit.",
                  "Vacuum leak (DISA valve, CCV system), faulty O2 sensor, MAF fault."),
        "P115D": ("Mass Air Flow Plausibility vs. Throttle",
                  "The MAF reading doesn't agree with the throttle opening — BMW plausibility check.",
                  "Charge pipe/boost leak, dirty MAF, throttle body fault."),
        "P0128": ("Coolant Thermostat (Below Regulating Temperature)",
                  "The engine runs too cold — the thermostat is likely stuck open. Very common BMW fault.",
                  "Map thermostat stuck open, faulty coolant sensor."),
        "P1019": ("Valvetronic Eccentric Shaft Sensor",
                  "The Valvetronic variable valve lift system can't control the eccentric shaft.",
                  "Faulty eccentric shaft sensor, worn Valvetronic motor, oil contamination."),
        "P17E0": ("Mechatronic Ratio Monitoring (EGS)",
                  "BMW automatic gearbox (GA6HP/GA8HP) detected an implausible gear ratio.",
                  "Low transmission fluid, worn clutch packs, mechatronic sleeve leak."),
    },
    "Toyota / Lexus": {
        "P0A80": ("Replace Hybrid Battery Pack",
                  "The hybrid (HV) battery is deteriorating below usable capacity. Key Prius/"
                  "Hybrid Synergy Drive fault.",
                  "Aged hybrid battery cells, failed cell modules, cooling fan blockage."),
        "P3000": ("Battery Control System",
                  "Fault in the hybrid battery ECU control system.",
                  "HV battery fault, battery ECU fault, wiring issue — scan the HV battery module."),
        "P1604": ("Startability Malfunction",
                  "Toyota-specific: the engine cranked but failed to start or started poorly.",
                  "Low fuel, weak battery, immobilizer issue, fuel pump fault."),
        "P2714": ("Pressure Control Solenoid 'D' Performance",
                  "Automatic transmission shift solenoid D isn't performing as expected "
                  "(common on Toyota U660/U760 gearboxes).",
                  "Faulty solenoid, dirty valve body, degraded ATF."),
        "C1201": ("Engine Control System Malfunction (request)",
                  "The ABS/VSC module saw an engine fault and disabled stability control. "
                  "It's a 'shadow' code — fix the engine code first.",
                  "Any stored engine ECU fault triggers this."),
    },
    "Ford": {
        "P0316": ("Misfire Detected at Startup (First 1000 Revs)",
                  "Ford-specific: a misfire occurred right at engine start.",
                  "Worn plugs/coils, cold-start fuel trim issue, low compression."),
        "P1000": ("OBD Monitor Testing Not Complete",
                  "Ford-specific status code: the ECU's self-tests haven't finished since the "
                  "battery was disconnected or codes were cleared. Not a fault — drive the car.",
                  "Recent battery disconnect or code clear; needs a full drive cycle."),
        "P0087": ("Fuel Rail/System Pressure Too Low",
                  "Fuel pressure is below target — on Ford EcoBoost diesels and GTDI petrols "
                  "this points at the high-pressure side.",
                  "Weak fuel pump, clogged filter, faulty pressure regulator/sensor."),
        "P132B": ("Turbocharger Boost Control Performance",
                  "Ford Powerstroke/EcoBoost turbo control fault.",
                  "Sticking turbo vanes/actuator, boost leak, faulty boost control solenoid."),
        "U1900": ("CAN Communication Bus Fault (Ford)",
                  "Ford-specific network fault between modules.",
                  "CAN wiring/connector fault, failing module, aftermarket device interference."),
    },
}

CODE_TYPE_INFO = {
    "P": "Powertrain (engine, transmission, emissions)",
    "B": "Body (airbags, seats, climate, lighting)",
    "C": "Chassis (ABS, brakes, suspension, steering)",
    "U": "Network (communication between modules)",
}


def explain(code):
    """Return a full explanation dict for a DTC code."""
    code = code.upper().strip()
    entry = GENERIC.get(code)
    source = "Generic OBD-II (SAE J2012)"
    if not entry:
        for brand, codes in MANUFACTURER.items():
            if code in codes:
                entry = codes[code]
                source = f"Manufacturer-specific — {brand}"
                break
    result = {
        "code": code,
        "system": CODE_TYPE_INFO.get(code[0], "Unknown system"),
        "source": source,
    }
    if entry:
        result["title"], result["explanation"], result["causes"] = entry
    else:
        result["title"] = "Not in built-in database"
        result["explanation"] = (
            "This code isn't in the local database. If the second character is 1 or 3, it's a "
            "manufacturer-specific code — check that brand's service information or an online "
            "DTC database for the exact definition."
        )
        result["causes"] = "Unknown — consult manufacturer documentation."
    return result
