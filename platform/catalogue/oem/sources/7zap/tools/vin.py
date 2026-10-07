"""Offline VIN decoder from public standards (ISO 3779 / 3780, US 49 CFR 565).

    python3 vin.py WVWZZZAUZFW123456

Decodes: check digit (North America only), maker from the WMI, model year (position 10),
plant code (position 11) and, for VW Group, the two-character model code (positions 7-8).
Nothing is stored: the VIN is only read from the command line or the function argument.
"""
import re, sys

TRANSLIT = {**{c: i + 1 for i, c in enumerate('ABCDEFGH')}, **{c: i + 1 for i, c in enumerate('JKLMN')},
            'P': 7, 'R': 9, **{c: i + 2 for i, c in enumerate('STUVWXYZ')}, **{str(d): d for d in range(10)}}
WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
YEAR_CODES = 'ABCDEFGHJKLMNPRSTVWXY123456789'  # 1980..2009, then repeats from 2010

# World manufacturer identifiers for the European makes in the catalogue (public SAE/ISO list).
WMI = {
    'WVW': 'Volkswagen (passenger cars)', 'WV1': 'Volkswagen Commercial Vehicles', 'WV2': 'Volkswagen (buses/vans)',
    'WV3': 'Volkswagen (trucks)', '3VW': 'Volkswagen Mexico', '1VW': 'Volkswagen USA', '9BW': 'Volkswagen Brazil',
    '8AW': 'Volkswagen Argentina', 'AAV': 'Volkswagen South Africa', 'LSV': 'SAIC Volkswagen (China)',
    'LFV': 'FAW-Volkswagen (China)', 'WAU': 'Audi', 'WA1': 'Audi SUV', 'WUA': 'Audi Sport / quattro GmbH',
    'TRU': 'Audi Hungary', 'VSS': 'SEAT', 'VSE': 'SEAT (Cupra)', 'TMB': 'Skoda', 'WP0': 'Porsche (cars)',
    'WP1': 'Porsche (SUV)', 'SCB': 'Bentley', 'ZHW': 'Lamborghini',
    'WBA': 'BMW', 'WBS': 'BMW M', 'WBX': 'BMW (SUV)', '5UX': 'BMW USA (SUV)', '4US': 'BMW USA', 'WMW': 'MINI',
    'WDB': 'Mercedes-Benz', 'WDD': 'Mercedes-Benz', 'WDC': 'Mercedes-Benz (SUV)', 'W1K': 'Mercedes-Benz',
    'W1N': 'Mercedes-Benz (SUV)', 'W1V': 'Mercedes-Benz (vans)', 'WDF': 'Mercedes-Benz (vans)', '4JG': 'Mercedes-Benz USA',
    'WME': 'smart', 'WDX': 'Maybach', 'SCA': 'Rolls-Royce',
    'VF1': 'Renault', 'VF6': 'Renault (trucks)', 'UU1': 'Dacia', 'VFA': 'Alpine', 'VF3': 'Peugeot', 'VR3': 'Peugeot',
    'VF7': 'Citroën', 'VR7': 'Citroën', 'W0L': 'Opel / Vauxhall', 'W0V': 'Opel / Vauxhall', 'VXK': 'Opel',
    'ZFA': 'Fiat', 'ZFB': 'Fiat (commercial)', 'ZAR': 'Alfa Romeo', 'ZLA': 'Lancia', 'ZFF': 'Ferrari',
    'YV1': 'Volvo (cars)', 'YV4': 'Volvo (SUV)', 'YS3': 'Saab', 'SAJ': 'Jaguar', 'SAL': 'Land Rover',
}
REGION = [('A', 'H', 'Africa'), ('J', 'R', 'Asia'), ('S', 'Z', 'Europe'), ('1', '5', 'North America'),
          ('6', '7', 'Oceania'), ('8', '9', 'South America')]

# VW Group model codes in positions 7-8 (public ETKA / VIN guides).
VAG_MODEL = {
    '1J': 'Golf IV / Bora / Audi A3 8L', '1K': 'Golf V / Jetta V', '5K': 'Golf VI', 'AU': 'Golf VII', 'BA': 'Golf VIII',
    'CD': 'Golf VIII', '1T': 'Touran', '3C': 'Passat B6/B7 / CC', '3G': 'Passat B8 / Arteon', '3H': 'Arteon',
    '6R': 'Polo 6R', '6C': 'Polo 6C', 'AW': 'Polo VI', '5N': 'Tiguan I', 'AD': 'Tiguan II', 'BW': 'Tiguan II LWB',
    '7L': 'Touareg I', '7P': 'Touareg II', 'CR': 'Touareg III', '7H': 'Transporter T5', '7J': 'Transporter T5',
    '7E': 'Transporter T5 GP', 'SG': 'Transporter T6', 'SH': 'Transporter T6.1', '2K': 'Caddy III', 'SA': 'Caddy V',
    '2E': 'Crafter I', 'SY': 'Crafter II', '1Z': 'Octavia II', '5E': 'Octavia III', 'NX': 'Octavia IV', '3T': 'Superb II',
    '3V': 'Superb III', '5J': 'Fabia II / Roomster', 'NJ': 'Fabia III', 'PJ': 'Fabia IV', 'NS': 'Kodiaq', 'NU': 'Karoq',
    '1P': 'Leon II', '5F': 'Leon III', 'KL': 'Leon IV / Cupra Leon', '6J': 'Ibiza IV', 'KJ': 'Ibiza V / Arona',
    '5P': 'Altea / Toledo III', 'KH': 'Ateca', 'KM': 'Cupra Formentor', 'K1': 'Cupra Born',
    '8P': 'Audi A3 8P', '8V': 'Audi A3 8V', '8Y': 'Audi A3 8Y', '8E': 'Audi A4 B6/B7', '8H': 'Audi A4 Cabriolet',
    '8K': 'Audi A4 B8', '8W': 'Audi A4 B9', '8T': 'Audi A5 8T', 'F5': 'Audi A5 F5', '4B': 'Audi A6 C5', '4F': 'Audi A6 C6',
    '4G': 'Audi A6/A7 C7', '4A': 'Audi A6 C8', '4K': 'Audi A7 C8', '4E': 'Audi A8 D3', '4H': 'Audi A8 D4', '4N': 'Audi A8 D5',
    '8U': 'Audi Q3 8U', 'F3': 'Audi Q3 F3', '8R': 'Audi Q5 8R', 'FY': 'Audi Q5 FY', '4L': 'Audi Q7 4L', '4M': 'Audi Q7/Q8 4M',
    '8J': 'Audi TT 8J', 'FV': 'Audi TT 8S', '42': 'Audi R8 I', '4S': 'Audi R8 II',
}

def check_digit(v):
    s = sum(TRANSLIT[c] * w for c, w in zip(v, WEIGHTS))
    r = s % 11
    return 'X' if r == 10 else str(r)

def model_year(c, pos7):
    """Position 10. Codes repeat every 30 years; for NA VINs a letter in position 7 means 2010+."""
    if c not in YEAR_CODES: return None
    base = 1980 + YEAR_CODES.index(c)
    years = [base, base + 30]
    if pos7.isalpha(): return years[1]
    if pos7.isdigit(): return years[0]
    return years  # European VINs do not encode the cycle; both candidates returned

def decode(vin):
    v = vin.strip().upper()
    out = {'valid_format': bool(re.fullmatch(r'[A-HJ-NPR-Z0-9]{17}', v))}
    if not out['valid_format']:
        out['error'] = 'A VIN has 17 characters and never uses I, O or Q.'; return out
    wmi = v[:3]
    out['wmi'] = wmi
    out['maker'] = WMI.get(wmi, 'unknown')
    out['region'] = next((r for a, b, r in REGION if a <= v[0] <= b), 'unknown')
    out['check_digit_ok'] = v[8] == check_digit(v)
    out['model_year'] = model_year(v[9], v[6])
    out['plant_code'] = v[10]
    out['serial'] = v[11:]
    if wmi in ('WVW', 'WV1', 'WV2', 'WAU', 'WA1', 'WUA', 'TRU', 'VSS', 'VSE', 'TMB', '3VW', '9BW', '8AW', 'AAV', 'LSV', 'LFV'):
        out['vag_model_code'] = v[6:8]
        out['vag_model'] = VAG_MODEL.get(v[6:8], 'unknown')
    return out

if __name__ == '__main__':
    import json
    for a in sys.argv[1:]:
        print(json.dumps(decode(a), indent=1, ensure_ascii=False))
