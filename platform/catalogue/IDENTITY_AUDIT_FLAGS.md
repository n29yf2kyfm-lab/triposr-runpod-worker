# Identity audit — 1,022 live cars reviewed, 163 flagged (2026-08-25)

Three reviewers, 86 captioned contact sheets, every live catalogue entry with a
poster. Flag = the PICTURE contradicts the STORED DATA.

  sheets 001-029   348 tiles   76 flagged   18 uncertain
  sheets 030-058   348 tiles   63 flagged    9 uncertain
  sheets 059-086   326 tiles   24 flagged   10 uncertain
  TOTAL          1,022 tiles  163 flagged   37 uncertain   (15.9%)

## THE ONE DECISION THAT CHANGES THE NUMBER

Most flags are CATEGORY 4: cars never sold in the UK. Nissan Altima/Sentra/
President/Sylphy/Cefiro/Elgrand/Stagea/Kicks/Titan/Frontier/Murano/Pathfinder;
Honda Odyssey/Crosstour/S660/Beat/US-Accord; Hyundai Elantra/Creta/Grand i10
Nios/Veracruz/Encino; the whole BYD Yangwang range plus Song/Tang/Seal 06;
Chrysler Pacifica; Subaru Ascent/BRZ/WRX; Maruti Suzuki Alto/Baleno; Kia
Carnival; Fiat Toro/Linea/147; Citroen C4 Lounge; Dacia Lodgy; Lexus LX;
Mazda CX-8; Jeep Grand Commander; Toyota Vellfire/GR Corolla/LC J300; VW Jetta
and the China Passat.

If non-UK stock is DELIBERATE coverage padding, these collapse to a naming
issue and the real count drops sharply. If it is not deliberate, a UK reg can
never match them and they are dead weight in the serving set. OWNER CALL.

## HARD IDENTITY ERRORS — wrong car for a UK lookup regardless of that call

### Skyline GT-Rs filed under the generic "gt-r" family (15 entries)
nissan-gt-r-nw1-v2/v4/v5/v6/v7/v8, nissan-gt-r-1989-nw1-v1/v2,
nissan-gt-r-1995-nw1-v1, nissan-gt-r-1997-nw1-v1, nissan-gt-r-1999-nw1-v1/v2,
nissan-gt-r-2002-nw1-v1/v2, nissan-gt-r-2005-nw1-v1
R32/R33/R34 and a Hakosuka all filed as "gt-r", so an R35 GT-R lookup can be
served a 1990s Skyline. nissan-gt-r-2005-nw1-v1 is stamped 2005 for a car whose
production ended in 2002.

### Wrong generation vs the stored year window
audi-a4-v1            B5 (1995-2001)      stored 2015-2026
audi-a3-v1            8P (2003-2012)      stored 2015-2026
audi-s3-v1            8P (2006-2012)      stored 2015-2026
honda-cr-v-v1         1st gen (1997-2001) stored 2018-2026
toyota-yaris-2001-v1  Mk1 (1999-2005)     stored 2020-2026
volkswagen-beetle-v1  air-cooled (1968)   stored 1997-2019
skoda-fabia-v1        Mk2 (2007-2014)     stored 2021-2026
bmw-1-series-v1       E82 coupe           stored 2015-2026
bmw-7-series-v1       F01 (2008-2015)     stored 2015-2026
aston-martin-dbs-v1   1st gen (2008-2012) stored 2018-2023
porsche-cayenne-v2    957 (2007-2010)     stored 2017-2026
kia-picanto-2012-v1   2023 facelift       stored 2012-2012 (title ALSO wrong)
mazda-2-v1            DE (2011)           stored 2015-2026
mercedes-benz-vito-v1 W639 (2010)         stored 2015-2026
renault-captur-v1     1st gen             stored 2019-2026
renault-megane-v1     Megane III          stored 2016-2022
toyota-prius-v1       XW50                stored 2023-2026
ford-focus-v1         Mk3 RS              stored 2018-2026
land-rover-range-rover-sport-2018-v1  L494  stored 2022-2026
mitsubishi-l200-v1    2005-2015 cab       stored 2024-2024

### Wrong body style (hard-rejects in the resolver, so it mis-serves AND mis-rejects)
byd-seal-v1              saloon stored "suv"
ssangyong-tivoli-v1      SUV    stored "hatchback"
jeep-compass-v1          SUV    stored "hatchback"
volkswagen-arteon-v1     Shooting Brake stored "saloon"
volkswagen-passat-v1     saloon stored "estate"

### Brand mis-filing
hyundai-i10-v1     pictured car is the India-market Grand i10 Nios
7x jaecoo-*        Chery-badged models filed under the Jaecoo brand
fiat-ducato-fw1-v1 a coachbuilt motorhome, not the Ducato van
nissan-skyline-nw1-v3  R34-fronted estate; no R34 wagon exists

### Vendor watermark plates baked into the car
ferrari-308-v1 (HUMSTER3D), fiat-850-spring-1968-fw1-v1 (HUM3D),
fiat-126-fw1-v1, bmw-8-series-2020-bm2-v1 ("RsDiyer"),
mazda-cx-5-2020-mzw1-v1 ("ItsDwyer"), honda-s2000-1999-hw1-v1 (kanji plate),
fiat-linea-fw1-v1 (Turkish plate), nissan-cefiro-nw1-v1/v2 (Japanese plates)

### Broken meshes on LIVE cars
honda-insight-v1        front half untextured dark grey, rear white
ford-mustang-v1         detached number-plate geometry on the floor
audi-e-tron-gt-v1       baked environment/ground chunk beside the car
honda-accord-1998-hw1-v1 rear lamps render body-white
volvo-740-vow1-v1       uniform white shell (verify against the glTF)
kia-optima-v1           crumpled front mesh
