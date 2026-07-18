#!/usr/bin/env bash
#
# download.sh — fetch licence-clear datasets for BuildScan AI training/fine-tuning.
#
# Downloads into datasets/data/ (git-ignored). These are free and either open
# (CC-BY / OGL / ODC-BY) or research-licensed (flagged NON-COMMERCIAL — usable
# to prototype, NOT to ship a model commercially without re-licensing/own data).
#
# URLs verified reachable 2026-07-18.
#
# Usage:
#   ./datasets/download.sh                 # list datasets + sizes, download nothing
#   ./datasets/download.sh landregistry    # fetch one by key
#   ./datasets/download.sh cracks_ozgenel sdnet2018   # fetch several
#   ./datasets/download.sh all             # fetch every openly-downloadable one (large!)

set -euo pipefail
cd "$(dirname "$0")"
DATA="data"
mkdir -p "$DATA"
DL() { echo ">> $1"; curl -fSL --retry 3 -C - "$2" -o "$DATA/$3"; echo "   saved $DATA/$3"; }

# key | licence | approx size | description | fetch-fn
list() {
  cat <<'TXT'
KEY                LICENCE        SIZE    CONTENT
-----------------  -------------  ------  ------------------------------------------------
landregistry_2023  OGL (open)     ~150MB  HM Land Registry Price Paid, 2023 sales (AVM)
landregistry_all   OGL (open)     ~5GB    HM Land Registry Price Paid, ALL years (AVM)
cracks_ozgenel     CC BY 4.0      ~241MB  40k concrete crack/no-crack images (defect AI)
sdnet2018          CC-BY          ~2GB    56k+ labelled concrete crack patches (defect AI)
objaverse_sample   ODC-BY         varies  3D asset corpus sample (image->3D fine-tune)

AUTH-GATED (register once, then place files in datasets/data/ yourself):
  epc              OGL-style      ~2GB    EPC register — register at epc.opendatacommunities.org
  mbdd2025         open (Nature)  ~3GB    14,471 UAV building-defect imgs — s41597-025-06318-5
  scannet          RESEARCH ONLY  ~1.3TB  indoor RGB-D scans — NON-COMMERCIAL, sign ScanNet ToU
  s3dis            RESEARCH ONLY  ~6GB    Stanford indoor 3D — NON-COMMERCIAL, request access
  structured3d     NON-COMMERCIAL ~20GB   synthetic indoor structured 3D — request access
TXT
}

fetch() {
  case "$1" in
    landregistry_2023) DL "Land Registry 2023" \
      "http://prod.publicdata.landregistry.gov.uk.s3-website-eu-west-1.amazonaws.com/pp-2023.csv" pp-2023.csv ;;
    landregistry_all)  DL "Land Registry (all years)" \
      "http://prod.publicdata.landregistry.gov.uk.s3-website-eu-west-1.amazonaws.com/pp-complete.csv" pp-complete.csv ;;
    cracks_ozgenel)    DL "Ozgenel concrete cracks" \
      "https://data.mendeley.com/public-files/datasets/5y9wdsg2zt/files/8a70d8a5-bce9-4291-bab9-b48cfb3e87c3/file_downloaded" concrete_cracks_ozgenel.rar ;;
    sdnet2018)         DL "SDNET2018" \
      "https://digitalcommons.usu.edu/cgi/viewcontent.cgi?article=1047&context=all_datasets" sdnet2018.zip ;;
    objaverse_sample)  echo ">> Objaverse: use the python API — pip install objaverse; see datasets/README.md" ;;
    *) echo "unknown or auth-gated key: $1 (see: ./download.sh with no args)"; return 1 ;;
  esac
}

if [ $# -eq 0 ]; then list; echo; echo "Run './download.sh <key>' to fetch. 'all' = every open one."; exit 0; fi
if [ "$1" = "all" ]; then
  for k in landregistry_2023 cracks_ozgenel sdnet2018; do fetch "$k"; done
  exit 0
fi
for k in "$@"; do fetch "$k"; done
