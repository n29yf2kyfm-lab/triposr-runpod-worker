#!/usr/bin/env python3
"""Category pages for cars the 2021 parts sitemap cannot cover: 1995-1997 and 2022-2026.

    python3 platform/catalogue/oem/gap_queue.py N

The sitemap is a 2021 snapshot, so parts introduced since 2022, and older parts
dropped before 2021, only come from crawling those cars' own category pages.
CATS is engine internals first (pistons, block, valve train, bearings), then
the categories in greedy set-cover order measured on the fully crawled 2019
Golf (about 100 categories cover 99 percent of that car's parts). Prints the
next N URLs, rotating across GAP cars; pages/ already crawled are skipped and
404s are recorded in gap_missing.txt so they are not retried.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = 'https://vw.oempartsonline.com'
GAP = ['v-2026-volkswagen-jetta--gli-autobahn--2-0l-l4-gas',
 'v-2025-volkswagen-tiguan--sel-r-line--2-0l-l4-gas',
 'v-2025-volkswagen-atlas--sel-premium-r-line--2-0l-l4-gas',
 'v-2025-volkswagen-taos--sel--1-5l-l4-gas',
 'v-2024-volkswagen-id-4--pro-s-plus--electric',
 'v-2025-volkswagen-golf-r--base--2-0l-l4-gas',
 'v-2024-volkswagen-atlas-cross-sport--sel-premium-r-line--2-0l-l4-gas',
 'v-2025-volkswagen-id-buzz--pro-s-plus--electric',
 'v-1996-volkswagen-jetta--glx--2-8l-v6-gas',
 'v-1996-volkswagen-jetta--gl--2-0l-l4-gas',
 'v-1997-volkswagen-passat--glx--2-8l-v6-gas',
 'v-1997-volkswagen-passat--tdi--1-9l-l4-diesel',
 'v-1997-volkswagen-cabrio--high-line--2-0l-l4-gas']
CATS = ['engine--engine-parts', 'engine--cylinder-block-components', 'engine--valve-train-components',
 'engine--bearings', 'engine--engine', 'engine--oil-pan', 'engine--pumps',
 'engine--gaskets-and-sealing-systems', 'engine--sensors', 'engine--turbocharger-and-components',
 'engine--engine-and-trans-mounting', 'engine--engine-appearance-cover', 'ignition--secondary-ignition',
 'emission-control--crankcase-ventilation-system', 'cooling-system--water-pump',
 'transmission--transmission-hard-parts', 'driveline-and-axles--cv-components',
 'steering--steering-gear-and-linkage', 'suspension--front-suspension', 'brakes--front-brakes',
 'hvac--blower-motor-and-fan', 'electrical--wiring-harness', 'body--roof', 'electrical--lumbar-control-seats',
 'body--rear-seat-components', 'body--interior-trim-pillars', 'body--interior-trim-front-door',
 'engine--mounts', 'body--universal', 'body--fenders', 'body--bumper-and-components-rear', 'body--front-door',
 'brakes--sensors', 'electrical--flasher-units-fuses-and-circuit-breakers',
 'body--brackets-flanges-and-hangers', 'brakes--brackets-flanges-and-hangers', 'body--seats',
 'body--interior-trim-rear-body', 'electrical--battery-and-related-components', 'body--glass-windshield',
 'body--hood-and-components', 'body--glass-windows-and-related-components', 'suspension--rear-suspension',
 'body--wiper-and-washer-components', 'body--inner-structure', 'electrical--brackets-flanges-and-hangers',
 'body--gate-and-hardware', 'body--bumper-and-components-front', 'body--sunroof',
 'hvac--a-c-clutch-and-compressor', 'body--instrument-panel-components', 'body--cowl', 'brakes--rear-brakes',
 'body--gaskets-and-sealing-systems', 'body--master-cylinder-components-on-dash-panel',
 'air-and-fuel-delivery--sensors', 'exhaust--exhaust-components', 'body--radiator-support', 'body--seat-belt',
 'electrical--ignition-lock', 'belts-and-cooling--hoses-and-pipes', 'electrical--lighting-exterior',
 'body--fender-and-components', 'engine--air-intake', 'engine--filters', 'body--jack-and-components',
 'brakes--bushings', 'body--outside-mirrors', 'electrical--lighting-instrumentation',
 'body--lock-and-hardware', 'body--instrument-panel', 'cooling-system--cooling-system',
 'air-and-fuel-delivery--gaskets-and-sealing-systems', 'driveline-and-axles--service-kits', 'body--ducts',
 'body--interior-trim-rear-door', 'body--quarter-panel-and-components', 'ignition--ignition-coil',
 'body--aperture-panel', 'body--roof-and-components',
 'wiper-and-washer--wiper-arm-blade-and-related-components', 'body--glove-box', 'body--rear-body',
 'belts-and-cooling--sensors', 'brakes--wire-cable-and-related-components', 'body--rocker-panel',
 'electrical--air-bag-components', 'body--glass-front-door', 'body--interior-trim',
 'belts-and-cooling--gaskets-and-sealing-systems', 'body--cluster-and-switches',
 'brakes--gaskets-and-sealing-systems', 'body--bushings', 'body--quarter-panel',
 'air-and-fuel-delivery--information-labels', 'body--spoiler', 'body--door-and-components',
 'electrical--keyless-entry-components', 'body--steering-wheel', 'electrical--tail-lamps',
 'electrical--backup-lamps', 'electrical--fuse-and-relay', 'body--exterior-trim-windshield',
 'electrical--anti-theft-components', 'body--exterior-trim-front-door', 'electrical--horn',
 'electrical--fog-lamps', 'electrical--electrical-components',
 'driveline-and-axles--cv-boots-and-related-components', 'clutch--clutch-and-flywheel',
 'electrical--license-lamps', 'cooling-system--intercooler',
 'belts-and-cooling--cooling-fan-clutch-and-motor', 'cooling-system--belts-and-pulleys',
 'electrical--starter', 'electrical--antenna-and-radio', 'clutch--hydraulic-system',
 'belts-and-cooling--thermostat-and-housing', 'automatic-transaxle--case-and-related-parts',
 'body--exterior-trim-lift-gate', 'automatic-transmission--automatic-transmission',
 'brakes--anti-lock-brakes', 'body--exterior-trim-pillars', 'electrical--automatic-transaxle',
 'body--splash-shields', 'body--grille-and-components', 'electrical--high-mounted-stop-lamp',
 'steering--steering-gear', 'body--glass-lift-gate', 'air-and-fuel-delivery--service-kits',
 'body--exterior-trim-quarter-panel', 'electrical--headlamp-washers-wipers',
 'automatic-transaxle--valve-body', 'automatic-transmission--gear-shift-control', 'electrical--alternator',
 'body--exterior-trim-fender']


def main():
    missing = set()
    mf = os.path.join(HERE, 'gap_missing.txt')
    if os.path.exists(mf):
        missing = {l.strip() for l in open(mf) if l.strip()}
    todo = []
    for c in CATS:
        for v in GAP:
            if os.path.exists(os.path.join(HERE, 'pages', v, c + '.json')) or f'{v}/{c}' in missing:
                continue
            todo.append(f'{SITE}/{v}/{c}')
    print(len(todo), 'gap pages left')
    for u in todo[:int(sys.argv[1]) if len(sys.argv) > 1 else 10]:
        print(u)


if __name__ == '__main__':
    main()
