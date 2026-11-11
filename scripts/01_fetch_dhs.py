"""Download Nigeria DHS indicator data from the DHS Program API.

Saves the API responses unchanged in data/raw/, with a manifest recording
what was asked for and when. Everything downstream is built from these
files, so the analysis can be re-run without touching the network.

    python scripts/01_fetch_dhs.py

Source: The DHS Program Indicator Data API, ICF International.
        https://api.dhsprogram.com
Uses only the Python standard library.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
BASE = "https://api.dhsprogram.com/rest/dhs/"

# The four Nigeria DHS rounds that report results for every state.
SURVEYS = ["NG2008DHS", "NG2013DHS", "NG2018DHS", "NG2024DHS"]

# Indicator IDs from the API's own catalogue (see data/raw/indicator_catalogue.json).
INDICATORS = [
    "RH_ANCN_W_N4P",  # antenatal care: four or more visits
    "RH_ANCP_W_SKP",  # antenatal care from a skilled provider
    "RH_DELP_C_DHF",  # delivery in a health facility
    "RH_DELA_C_SKP",  # delivery assisted by a skilled provider
    "RH_PCMT_W_DY2",  # postnatal check for the mother within two days
    "CH_VACC_C_BAS",  # fully vaccinated, eight basic antigens
    "CH_VACC_C_NON",  # received no vaccinations
    "CN_NUTS_C_HA2",  # children stunted
    "ML_NETC_C_ITN",  # children under five who slept under an insecticide-treated net
    "CM_ECMR_C_U5M",  # under-five mortality rate
    "CM_ECMR_C_NNR",  # neonatal mortality rate
    "FP_CUSM_W_MOD",  # married women using a modern contraceptive method
    "FE_FRTR_W_TFR",  # total fertility rate
    "ED_LITR_W_LIT",  # women who are literate
]


def get(path: str, **params) -> dict:
    """GET one page of JSON, retrying because connections here drop now and then."""
    params.setdefault("f", "json")
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(8):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "portfolio-analysis/1.0"})
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:  # noqa: BLE001 - any network failure is retried
            print(f"  retry {attempt + 1}: {type(error).__name__}", flush=True)
            time.sleep(4 + 3 * attempt)
    raise SystemExit(f"Could not reach {url}")


def get_all_pages(path: str, **params) -> list[dict]:
    first = get(path, page=1, **params)
    rows = list(first["Data"])
    for page in range(2, int(first.get("TotalPages", 1)) + 1):
        rows += get(path, page=page, **params)["Data"]
    if len(rows) != int(first["RecordCount"]):
        raise SystemExit(f"{path}: expected {first['RecordCount']} rows, received {len(rows)}")
    return rows


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    manifest = {"retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "The DHS Program Indicator Data API", "base_url": BASE,
                "surveys": SURVEYS, "indicators": INDICATORS, "files": {}}

    common = {"countryIds": "NG", "surveyIds": ",".join(SURVEYS), "indicatorIds": ",".join(INDICATORS), "perpage": 1000}
    for breakdown in ("national", "subnational"):
        rows = get_all_pages("data", breakdown=breakdown, **common)
        name = f"dhs_data_{breakdown}.json"
        (RAW / name).write_text(json.dumps(rows, indent=1), encoding="utf-8")
        manifest["files"][name] = len(rows)
        print(f"{name:<32} {len(rows):>5} rows")

    catalogue = get_all_pages("indicators", indicatorIds=",".join(INDICATORS), perpage=1000,
                              returnFields="IndicatorId,Label,Definition,MeasurementType,Denominator,Level1,Level2")
    (RAW / "indicator_catalogue.json").write_text(json.dumps(catalogue, indent=1), encoding="utf-8")
    manifest["files"]["indicator_catalogue.json"] = len(catalogue)
    print(f"{'indicator_catalogue.json':<32} {len(catalogue):>5} rows")

    surveys = get_all_pages("surveys", countryIds="NG", perpage=1000)
    surveys = [s for s in surveys if s["SurveyId"] in SURVEYS]
    (RAW / "surveys.json").write_text(json.dumps(surveys, indent=1), encoding="utf-8")
    manifest["files"]["surveys.json"] = len(surveys)
    print(f"{'surveys.json':<32} {len(surveys):>5} rows")

    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
