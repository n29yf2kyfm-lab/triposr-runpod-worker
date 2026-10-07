#!/usr/bin/env python3
"""Decode a VIN into make, model, year, trim and engine — and say how sure.

    python3 platform/catalogue/vin/vin.py VIN [--online] [--parts]

What a VIN can and cannot tell, and where each field comes from:

  make, country   WMI, positions 1-3 (international standard; offline table)
  model year      position 10 (standard code; offline)
  model/platform  VW group positions 7-8 type code (offline table below; the
                  usual community-documented codes — VW does not publish them)
  trim, engine    NOT in a European VW VIN. US VINs carry more, and NHTSA's
                  free vPIC service decodes them (--online). Where nothing
                  states a field, it is left empty — never guessed.
  exact parts     NOT possible from a VIN alone: the build's option codes
                  live in the maker's own system. --parts lists catalogue parts
                  for the decoded make/model/year ("fits this model"), which is
                  a shortlist to confirm, not a guarantee for this one car.

PRIVACY: the VIN is decoded and dropped. Nothing here stores or logs it.
"""
import json, os, re, sys, urllib.request

TRANS = {**{str(i): i for i in range(10)},
         **dict(zip('ABCDEFGH', range(1, 9))), **dict(zip('JKLMN', range(1, 6))), 'P': 7, 'R': 9,
         **dict(zip('STUVWXYZ', range(2, 10)))}
WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
YEAR = 'ABCDEFGHJKLMNPRSTVWXY123456789'           # 1980.. / 2010.. on a 30-year cycle

WMI = {
    'WVW': ('Volkswagen', 'Germany', 'car'), 'WV1': ('Volkswagen', 'Germany', 'commercial'),
    'WV2': ('Volkswagen', 'Germany', 'bus/van'), 'WVG': ('Volkswagen', 'Germany', 'SUV'),
    '1VW': ('Volkswagen', 'USA', 'car'), '3VW': ('Volkswagen', 'Mexico', 'car'),
    '3VV': ('Volkswagen', 'Mexico', 'SUV'), '1V2': ('Volkswagen', 'USA', 'SUV'), '9BW': ('Volkswagen', 'Brazil', 'car'),
    'WAU': ('Audi', 'Germany', 'car'), 'WA1': ('Audi', 'Germany', 'SUV'), 'TRU': ('Audi', 'Hungary', 'car'),
    'VSS': ('SEAT', 'Spain', 'car'), 'TMB': ('Skoda', 'Czech Republic', 'car'), 'WP0': ('Porsche', 'Germany', 'car'),
    'WP1': ('Porsche', 'Germany', 'SUV'), 'WBA': ('BMW', 'Germany', 'car'), 'WBS': ('BMW M', 'Germany', 'car'),
    'WMW': ('MINI', 'Germany/UK', 'car'), 'WDD': ('Mercedes-Benz', 'Germany', 'car'),
    'WDB': ('Mercedes-Benz', 'Germany', 'car'), 'W1K': ('Mercedes-Benz', 'Germany', 'car'),
    'WF0': ('Ford', 'Germany', 'car'), 'SFA': ('Ford', 'UK', 'car'), 'W0L': ('Opel/Vauxhall', 'Germany', 'car'),
    'VF1': ('Renault', 'France', 'car'), 'VF3': ('Peugeot', 'France', 'car'), 'VF7': ('Citroen', 'France', 'car'),
    'ZFA': ('Fiat', 'Italy', 'car'), 'SAJ': ('Jaguar', 'UK', 'car'), 'SAL': ('Land Rover', 'UK', 'SUV'),
    'SB1': ('Toyota', 'UK', 'car'), 'JTD': ('Toyota', 'Japan', 'car'), 'VNK': ('Toyota', 'France', 'car'),
    'SJN': ('Nissan', 'UK', 'car'), 'JN1': ('Nissan', 'Japan', 'car'), 'SHH': ('Honda', 'UK', 'car'),
    'JHM': ('Honda', 'Japan', 'car'), 'KMH': ('Hyundai', 'Korea', 'car'), 'KNA': ('Kia', 'Korea', 'car'),
    'JMZ': ('Mazda', 'Japan', 'car'), 'YV1': ('Volvo', 'Sweden', 'car'), 'TSM': ('Suzuki', 'Hungary', 'car'),
    # rest of the VW Group (2026-10-07)
    'WUA': ('Audi', 'Germany (Audi Sport / quattro GmbH)', 'car'),
    'SCB': ('Bentley', 'UK', 'car'), 'SJA': ('Bentley', 'UK', 'SUV'), 'ZHW': ('Lamborghini', 'Italy', 'car'),
    'ZPB': ('Lamborghini', 'Italy', 'SUV'), '8AW': ('Volkswagen', 'Argentina', 'car'), 'AAV': ('Volkswagen', 'South Africa', 'car'),
    'LSV': ('Volkswagen', 'China (SAIC VW)', 'car'), 'LFV': ('Volkswagen', 'China (FAW-VW)', 'car'),
}
VW_GROUP = {'Volkswagen', 'Audi', 'SEAT', 'Skoda', 'Porsche', 'Bentley', 'Lamborghini', 'Cupra'}
# VW group type code, VIN positions 7-8 -> model and generation.
TYPE = {
    '1H': 'Golf Mk3 / Vento', '1J': 'Golf Mk4 / Bora', '1K': 'Golf Mk5 / Jetta Mk5', '5K': 'Golf Mk6', 'AU': 'Golf Mk7',
    'CD': 'Golf Mk8', '6R': 'Polo Mk5', '6C': 'Polo Mk5 (facelift)', 'AW': 'Polo Mk6',
    '5N': 'Tiguan Mk1', '3C': 'Passat B6/B7', '3G': 'Passat B8', '3H': 'Arteon', 'A1': 'T-Roc',
    '1T': 'Touran Mk1', '5T': 'Touran Mk2', '7N': 'Sharan Mk2', '13': 'Scirocco Mk3',
    '8P': 'Audi A3 Mk2', '8V': 'Audi A3 Mk3', '8Y': 'Audi A3 Mk4', '8X': 'Audi A1 Mk1',
    '1Z': 'Skoda Octavia Mk2', '5E': 'Skoda Octavia Mk3', 'NX': 'Skoda Octavia Mk4',
    '1P': 'SEAT Leon Mk2', '5F': 'SEAT Leon Mk3', 'KL': 'SEAT/Cupra Leon Mk4',
    # Euro VW, commercial vehicles, Skoda, SEAT (community-documented type codes)
    '9N': 'Polo Mk4', '6N': 'Polo Mk3', '1U': 'Skoda Octavia Mk1', '3T': 'Skoda Superb Mk2',
    '3V': 'Skoda Superb Mk3', '5J': 'Skoda Fabia Mk2', 'NJ': 'Skoda Fabia Mk3', '5L': 'Skoda Yeti',
    'NS': 'Skoda Kodiaq', '1M': 'SEAT Leon Mk1', '6L': 'SEAT Ibiza Mk3', '6J': 'SEAT Ibiza Mk4', 'KJ': 'SEAT Ibiza Mk5',
    '7D': 'Transporter T4', '7H': 'Transporter T5', '2E': 'Crafter Mk1', '2H': 'Amarok Mk1', '2K': 'Caddy Mk3',
}

# rough production span per type code: only used to pick which 30-year cycle
# position 10 means, never shown as a fact about the car
SPAN = {'1H': (1991, 1999), '1J': (1997, 2006), '1K': (2003, 2014), '5K': (2008, 2014),
        'AU': (2012, 2021), 'CD': (2019, 2030)}
# US VW type codes 1995-2026 -> the dealer catalogue's model names, so a VIN can
# pick parts by model + year from each part's fitment. Usual community-documented
# codes; VW does not publish them. Kept identical to VWMODELS in catalogue.html.
VWMODELS = {
    '1H': (['Golf', 'GTI', 'Jetta'], (1993, 1999), 'Golf / GTI / Jetta Mk3'),
    '1E': (['Cabrio'], (1995, 2002), 'Cabrio'),
    '1J': (['Golf', 'GTI', 'R32'], (1999, 2006), 'Golf / GTI Mk4'),
    '9M': (['Jetta'], (1999, 2005), 'Jetta Mk4'),
    '1C': (['Beetle'], (1998, 2010), 'New Beetle'),
    '1Y': (['Beetle'], (2003, 2010), 'New Beetle Convertible'),
    '1K': (['Rabbit', 'GTI', 'Jetta', 'R32', 'Golf'], (2005, 2014), 'Golf Mk5 / Rabbit / GTI / Jetta Mk5'),
    '5K': (['Golf', 'GTI', 'Golf R'], (2010, 2014), 'Golf / GTI Mk6'),
    'AJ': (['Jetta'], (2011, 2018), 'Jetta Mk6'),
    'BU': (['Jetta'], (2019, 2030), 'Jetta Mk7'),
    'AT': (['Beetle'], (2012, 2019), 'Beetle (A5)'),
    'AU': (['Golf', 'GTI', 'Golf R', 'Golf SportWagen', 'Golf Alltrack', 'e-Golf'], (2015, 2021), 'Golf Mk7 family'),
    'CD': (['Golf', 'GTI', 'Golf R'], (2019, 2030), 'Golf Mk8'),
    '3B': (['Passat'], (1998, 2005), 'Passat B5'),
    '3C': (['Passat', 'CC'], (2006, 2017), 'Passat B6 / CC'),
    'A3': (['Passat'], (2012, 2022), 'Passat (US-built)'),
    '5N': (['Tiguan', 'Tiguan Limited'], (2009, 2018), 'Tiguan Mk1'),
    'AX': (['Tiguan'], (2018, 2030), 'Tiguan Mk2'),
    'CA': (['Atlas', 'Atlas Cross Sport'], (2018, 2030), 'Atlas'),
    '7L': (['Touareg'], (2004, 2010), 'Touareg Mk1'),
    'BP': (['Touareg'], (2011, 2017), 'Touareg Mk2'),
    '1F': (['Eos'], (2007, 2016), 'Eos'),
    '3D': (['Phaeton'], (2004, 2006), 'Phaeton'),
    '70': (['Eurovan'], (1993, 2003), 'EuroVan'),
    '3H': (['Arteon'], (2019, 2030), 'Arteon'),
}
# Audi type codes -> the Audi dealer catalogue's models ("Audi A4" matches
# "Audi A4 allroad" etc. by prefix). Same caveat: community-documented codes.
AUDIMODELS = {
    '8L': (['Audi A3', 'Audi S3'], (1997, 2003), 'Audi A3 Mk1 (8L)'),
    '8P': (['Audi A3', 'Audi S3', 'Audi RS 3'], (2004, 2013), 'Audi A3 Mk2 (8P)'),
    '8V': (['Audi A3', 'Audi S3', 'Audi RS 3'], (2013, 2020), 'Audi A3 Mk3 (8V)'),
    '8Y': (['Audi A3', 'Audi S3', 'Audi RS 3'], (2020, 2030), 'Audi A3 Mk4 (8Y)'),
    '8D': (['Audi A4', 'Audi S4'], (1995, 2001), 'Audi A4 B5'),
    '8E': (['Audi A4', 'Audi S4', 'Audi RS 4'], (2001, 2008), 'Audi A4 B6/B7'),
    '8K': (['Audi A4', 'Audi S4', 'Audi RS 4'], (2008, 2016), 'Audi A4 B8'),
    '8W': (['Audi A4', 'Audi S4', 'Audi RS 4'], (2016, 2030), 'Audi A4 B9'),
    '8T': (['Audi A5', 'Audi S5', 'Audi RS 5'], (2007, 2017), 'Audi A5 Mk1'),
    'F5': (['Audi A5', 'Audi S5', 'Audi RS 5'], (2017, 2030), 'Audi A5 Mk2'),
    '4B': (['Audi A6', 'Audi S6', 'Audi RS 6', 'Audi allroad'], (1997, 2005), 'Audi A6 C5'),
    '4F': (['Audi A6', 'Audi S6', 'Audi RS 6'], (2004, 2011), 'Audi A6 C6'),
    '4G': (['Audi A6', 'Audi S6', 'Audi RS 6', 'Audi A7', 'Audi S7', 'Audi RS 7'], (2011, 2018), 'Audi A6/A7 C7'),
    '4D': (['Audi A8', 'Audi S8'], (1994, 2003), 'Audi A8 D2'),
    '4E': (['Audi A8', 'Audi S8'], (2002, 2010), 'Audi A8 D3'),
    '4H': (['Audi A8', 'Audi S8'], (2010, 2017), 'Audi A8 D4'),
    '4N': (['Audi A8', 'Audi S8'], (2018, 2030), 'Audi A8 D5'),
    '8N': (['Audi TT'], (1998, 2006), 'Audi TT Mk1'),
    '8J': (['Audi TT', 'Audi TTS', 'Audi TT RS'], (2006, 2014), 'Audi TT Mk2'),
    'FV': (['Audi TT', 'Audi TTS', 'Audi TT RS'], (2014, 2023), 'Audi TT Mk3'),
    '8U': (['Audi Q3'], (2011, 2018), 'Audi Q3 Mk1'),
    'F3': (['Audi Q3', 'Audi RS Q3'], (2018, 2030), 'Audi Q3 Mk2'),
    '8R': (['Audi Q5', 'Audi SQ5'], (2008, 2017), 'Audi Q5 Mk1'),
    'FY': (['Audi Q5', 'Audi SQ5'], (2017, 2030), 'Audi Q5 Mk2'),
    '4L': (['Audi Q7'], (2006, 2015), 'Audi Q7 Mk1'),
    '4M': (['Audi Q7', 'Audi SQ7', 'Audi Q8', 'Audi SQ8', 'Audi RS Q8'], (2016, 2030), 'Audi Q7 Mk2 / Q8'),
    '42': (['Audi R8'], (2007, 2015), 'Audi R8 Mk1'),
    '4S': (['Audi R8'], (2016, 2024), 'Audi R8 Mk2'),
}
# make -> type code -> (dealer catalogue models, usual span, label). Porsche,
# Bentley and Lamborghini VINs are decoded to make and year only: their
# positions 7-8 are not a type code we can map with confidence, and an
# unknown code is reported, never guessed.
BRANDMODELS = {'Volkswagen': VWMODELS, 'Audi': AUDIMODELS}
for _tab in BRANDMODELS.values():
    for _c, (_m, _span, _l) in _tab.items():
        SPAN.setdefault(_c, _span)


def check_digit(v):
    s = sum(TRANS.get(c, 0) * w for c, w in zip(v, WEIGHTS)) % 11
    return 'X' if s == 10 else str(s)


def decode(vin, online=False):
    v = re.sub(r'[\s-]', '', vin).upper()
    out = {'valid': False, 'fields': {}, 'sources': {}, 'notes': []}
    if len(v) != 17 or re.search(r'[^A-HJ-NPR-Z0-9]', v):
        out['notes'].append('not a 17-character VIN (I, O and Q are never used)')
        return out
    out['valid'] = True
    f, src = out['fields'], out['sources']
    wmi = WMI.get(v[:3])
    if wmi:
        f['make'], f['country'], f['kind'] = wmi
        src['make'] = 'WMI (positions 1-3)'
    else:
        out['notes'].append(f'manufacturer code {v[:3]} not in the offline table')
    if v[9] in YEAR:
        i = YEAR.index(v[9])
        cands = [1980 + i, 2010 + i]
        # North-American rule: position 7 is a LETTER from 2010 on. Outside it,
        # take the later cycle unless that is in the future.
        if v[:1] in '12345' and v[6].isdigit():
            year = cands[0]
        else:
            year = cands[1] if cands[1] <= 2027 else cands[0]
        span = SPAN.get(v[6:8])
        if span and wmi and wmi[0] in VW_GROUP:     # the type code settles the 30-year cycle
            inside = [c for c in cands if span[0] <= c <= span[1]]
            if len(inside) == 1:
                year = inside[0]
        f['year'] = year
        src['year'] = 'position 10'
    if f.get('make') in VW_GROUP:
        code = v[6:8]
        tab = BRANDMODELS.get(f.get('make'), {})
        t = (tab[code][2] if code in tab else None) or TYPE.get(code)
        if t:
            f['model'] = t
            src['model'] = 'VW group type code (positions 7-8)'
        else:
            out['notes'].append(f'type code {code} is not in the table, so the model is not decoded')
        if code in tab:
            f['dealer_models'] = tab[code][0]
            y0, y1 = tab[code][1]
            if f.get('year') and not y0 <= f['year'] <= y1:
                out['notes'].append(f'model year {f["year"]} is outside the usual {y0}-{min(y1, 2026)} span for {code}: mistyped VIN?')
        if v[3:6] == 'ZZZ':
            out['notes'].append('European VW Group VIN: trim and engine are not encoded — confirm from the V5C or the car')
    na = v[:1] in '12345'
    if na and check_digit(v) != v[8]:
        out['notes'].append('check digit (position 9) does not match — mistyped VIN?')
    if online:
        try:
            u = f'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{v}?format=json'
            r = json.load(urllib.request.urlopen(u, timeout=20))['Results'][0]
            for k, nk in (('Model', 'model'), ('Trim', 'trim'), ('DisplacementL', 'engine_litres'),
                          ('EngineCylinders', 'cylinders'), ('FuelTypePrimary', 'fuel'), ('BodyClass', 'body')):
                if r.get(k):
                    if nk == 'model' and f.get('model'):
                        f['model_nhtsa'] = r[k]
                    else:
                        f[nk] = r[k]
                        src[nk] = 'NHTSA vPIC'
        except Exception as ex:
            out['notes'].append(f'NHTSA lookup failed: {type(ex).__name__}')
    for k in ('trim', 'engine_litres'):
        f.setdefault(k, None)
    return out


def parts_for(dec):
    """Catalogue parts listed for the decoded make, model and year."""
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'oem')
    vehicles = json.load(open(os.path.join(here, 'vehicles.json')))
    parts = json.load(open(os.path.join(here, 'parts.json')))
    f = dec['fields']
    same = [v for v in vehicles if v.get('year') == f.get('year')
            and (v.get('make') or '').lower() == (f.get('make') or '').lower()]
    if f.get('model_nhtsa'):          # an exact model name: match it exactly (Golf is not Golf Alltrack)
        hits = [v['slug'] for v in same if v.get('model', '').lower() == f['model_nhtsa'].lower()]
    else:                             # only the platform is known: every model on it
        model = (f.get('model') or '').lower()
        fam = {'rabbit': 'golf', 'gti': 'golf'}          # US names for Golf models
        hits = [v['slug'] for v in same
                if fam.get(v.get('model', '').lower().split()[0], v.get('model', '').lower().split()[0]) in model]
    out = [p for p in parts if any(a['vehicle'] in hits for a in p['appears_on'])]
    if f.get('dealer_models') and f.get('year'):     # every VW: each part page's own fitment
        models, y = set(f['dealer_models']), f['year']
        prefix = f.get('make') != 'Volkswagen'       # "Audi A4" also covers "Audi A4 allroad"
        ok = lambda m: m in models or (prefix and any(m.startswith(x + ' ') for x in models))
        out += [p for p in parts if p not in out and any(ok(m) and lo <= y <= hi for m, lo, hi in p.get('fits', []))]
    return hits, out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 1:
        print(__doc__)
        return 1
    dec = decode(args[0], online='--online' in sys.argv)
    if '--parts' in sys.argv and dec['valid']:
        veh, parts = parts_for(dec)
        dec['catalogue'] = {'vehicles': veh, 'parts': len(parts),
                            'sample': [f"{p['oem_display']}  {p['name']}" for p in parts[:10]],
                            'note': 'parts that fit this model and year — confirm for the exact car'}
    print(json.dumps(dec, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
