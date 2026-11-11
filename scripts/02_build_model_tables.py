"""Turn the raw API responses into the tables the Power BI model reads.

Reads   data/raw/*.json   (written by 01_fetch_dhs.py)
Writes  data/model/*.csv  (one file per table in the data model)

    python scripts/02_build_model_tables.py

Design decisions, each one checked below before anything is written:

1. One fact table per grain. State, zone and national figures are kept in
   three separate tables. Putting them in one table invites a total that
   adds a state to its own zone.
2. One reference period per indicator. The API returns several look-back
   windows for the maternal-care indicators. The row it flags as preferred
   is the two-year window in every survey round, so rounds compare like
   with like.
3. Mortality uses the ten-year rate at every level. States are only
   published as ten-year rates, so the national figure shown beside them
   must be the ten-year rate too, not the five-year headline rate.
4. State results exist for 2013, 2018 and 2024. The 2008 round is
   published by zone only, so it appears in the zone and national tables
   and not in the state table.

Uses only the Python standard library.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MODEL = ROOT / "data" / "model"

# indicator id -> (display name, group, unit, direction, sort order)
# direction: 1 = higher is better, -1 = lower is better, 0 = context only
INDICATORS = {
    "RH_ANCP_W_SKP": ("Antenatal care from a skilled provider", "Care for mothers", "%", 1, 1),
    "RH_ANCN_W_N4P": ("Four or more antenatal visits", "Care for mothers", "%", 1, 2),
    "RH_DELP_C_DHF": ("Delivery in a health facility", "Care for mothers", "%", 1, 3),
    "RH_DELA_C_SKP": ("Skilled attendant at delivery", "Care for mothers", "%", 1, 4),
    "RH_PCMT_W_DY2": ("Postnatal check within two days", "Care for mothers", "%", 1, 5),
    "CH_VACC_C_BAS": ("Fully vaccinated (basic vaccines)", "Care for children", "%", 1, 6),
    "CH_VACC_C_NON": ("No vaccinations received", "Care for children", "%", -1, 7),
    "ML_NETC_C_ITN": ("Children sleeping under a treated net", "Care for children", "%", 1, 8),
    "CN_NUTS_C_HA2": ("Children stunted", "Outcomes", "%", -1, 9),
    "CM_ECMR_C_NNR": ("Neonatal mortality", "Outcomes", "per 1,000 live births", -1, 10),
    "CM_ECMR_C_U5M": ("Under-five mortality", "Outcomes", "per 1,000 live births", -1, 11),
    "ED_LITR_W_LIT": ("Women who are literate", "Context", "%", 1, 12),
    "FP_CUSM_W_MOD": ("Modern contraceptive use", "Context", "%", 1, 13),
    "FE_FRTR_W_TFR": ("Total fertility rate", "Context", "births per woman", 0, 14),
}
MORTALITY = {"CM_ECMR_C_NNR", "CM_ECMR_C_U5M"}
TEN_YEARS = "Ten years preceding the survey"

# state -> (zone, ISO 3166-2 code)
STATES = {
    "Benue": ("North Central", "NG-BE"), "FCT": ("North Central", "NG-FC"), "Kogi": ("North Central", "NG-KO"),
    "Kwara": ("North Central", "NG-KW"), "Nasarawa": ("North Central", "NG-NA"), "Niger": ("North Central", "NG-NI"),
    "Plateau": ("North Central", "NG-PL"),
    "Adamawa": ("North East", "NG-AD"), "Bauchi": ("North East", "NG-BA"), "Borno": ("North East", "NG-BO"),
    "Gombe": ("North East", "NG-GO"), "Taraba": ("North East", "NG-TA"), "Yobe": ("North East", "NG-YO"),
    "Jigawa": ("North West", "NG-JI"), "Kaduna": ("North West", "NG-KD"), "Kano": ("North West", "NG-KN"),
    "Katsina": ("North West", "NG-KT"), "Kebbi": ("North West", "NG-KE"), "Sokoto": ("North West", "NG-SO"),
    "Zamfara": ("North West", "NG-ZA"),
    "Abia": ("South East", "NG-AB"), "Anambra": ("South East", "NG-AN"), "Ebonyi": ("South East", "NG-EB"),
    "Enugu": ("South East", "NG-EN"), "Imo": ("South East", "NG-IM"),
    "Akwa Ibom": ("South South", "NG-AK"), "Bayelsa": ("South South", "NG-BY"), "Cross River": ("South South", "NG-CR"),
    "Delta": ("South South", "NG-DE"), "Edo": ("South South", "NG-ED"), "Rivers": ("South South", "NG-RI"),
    "Ekiti": ("South West", "NG-EK"), "Lagos": ("South West", "NG-LA"), "Ogun": ("South West", "NG-OG"),
    "Ondo": ("South West", "NG-ON"), "Osun": ("South West", "NG-OS"), "Oyo": ("South West", "NG-OY"),
}
ZONES = ["North Central", "North East", "North West", "South East", "South South", "South West"]
STATE_ROUNDS = {2013, 2018, 2024}
ALL_ROUNDS = {2008, 2013, 2018, 2024}


def clean_name(label: str) -> str:
    """'..FCT Abuja' -> 'FCT'; '..Benue' -> 'Benue'; zones are returned unchanged."""
    name = label.lstrip(".").strip()
    return "FCT" if name == "FCT Abuja" else name


def keep(row: dict) -> bool:
    """Apply the reference-period rule (decisions 2 and 3)."""
    if row["IndicatorId"] in MORTALITY:
        return row["ByVariableLabel"] == TEN_YEARS
    return row["IsPreferred"] == 1


def write_csv(name: str, header: list[str], rows: list[list]) -> None:
    MODEL.mkdir(parents=True, exist_ok=True)
    with (MODEL / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"{name:<24} {len(rows):>5} rows")


def main() -> None:
    national_raw = json.loads((RAW / "dhs_data_national.json").read_text(encoding="utf-8"))
    subnational_raw = json.loads((RAW / "dhs_data_subnational.json").read_text(encoding="utf-8"))
    catalogue = {r["IndicatorId"]: r for r in json.loads((RAW / "indicator_catalogue.json").read_text(encoding="utf-8"))}
    surveys = json.loads((RAW / "surveys.json").read_text(encoding="utf-8"))

    # ------------------------------------------------------------ facts
    state_rows, zone_rows, national_rows = [], [], []
    for r in subnational_raw:
        if not keep(r):
            continue
        name = clean_name(r["CharacteristicLabel"])
        record = [int(r["SurveyYear"]), r["IndicatorId"], name, r["Value"],
                  r["DenominatorWeighted"] if r["DenominatorWeighted"] != "" else None,
                  r["DenominatorUnweighted"] if r["DenominatorUnweighted"] != "" else None]
        if r["LevelRank"] == 2:
            state_rows.append(record)
        else:
            zone_rows.append(record)
    for r in national_raw:
        if keep(r):
            national_rows.append([int(r["SurveyYear"]), r["IndicatorId"], r["Value"],
                                  r["DenominatorWeighted"] if r["DenominatorWeighted"] != "" else None])

    # ------------------------------------------------------------ checks
    problems = []
    unknown_states = {row[2] for row in state_rows} - set(STATES)
    unknown_zones = {row[2] for row in zone_rows} - set(ZONES)
    if unknown_states:
        problems.append(f"states not in the lookup: {sorted(unknown_states)}")
    if unknown_zones:
        problems.append(f"zones not in the lookup: {sorted(unknown_zones)}")
    if {row[0] for row in state_rows} != STATE_ROUNDS:
        problems.append(f"state rounds are {sorted({row[0] for row in state_rows})}, expected {sorted(STATE_ROUNDS)}")

    for label, rows, key_width, expected in [
        ("state", state_rows, 3, len(INDICATORS) * len(STATE_ROUNDS) * len(STATES)),
        ("zone", zone_rows, 3, len(INDICATORS) * len(ALL_ROUNDS) * len(ZONES)),
        ("national", national_rows, 2, len(INDICATORS) * len(ALL_ROUNDS)),
    ]:
        keys = Counter(tuple(row[:key_width]) for row in rows)
        duplicates = [k for k, n in keys.items() if n > 1]
        if duplicates:
            problems.append(f"{label}: {len(duplicates)} duplicate keys, e.g. {duplicates[:3]}")
        if len(rows) != expected:
            problems.append(f"{label}: {len(rows)} rows, expected {expected}")

    # a percentage must lie in 0-100; a national figure must lie between the lowest and highest zone
    for year, indicator, _name, value, *_ in state_rows + zone_rows:
        if INDICATORS[indicator][2] == "%" and not 0 <= value <= 100:
            problems.append(f"{indicator} {year}: value {value} outside 0-100")
    zone_range = {}
    for year, indicator, _name, value, *_ in zone_rows:
        low, high = zone_range.get((year, indicator), (value, value))
        zone_range[(year, indicator)] = (min(low, value), max(high, value))
    for year, indicator, value, _n in national_rows:
        low, high = zone_range[(year, indicator)]
        if not low <= value <= high:
            problems.append(f"{indicator} {year}: national {value} is outside the zone range {low}-{high}")

    if problems:
        raise SystemExit("Data checks failed:\n  " + "\n  ".join(problems))
    print("All data checks passed.")

    # ------------------------------------------------------------ write
    write_csv("indicator.csv",
              ["indicator_id", "indicator", "indicator_group", "unit", "direction", "sort_order", "source_label", "definition"],
              [[key, name, group, unit, direction, order, catalogue[key]["Label"], " ".join(catalogue[key]["Definition"].split())]
               for key, (name, group, unit, direction, order) in INDICATORS.items()])
    write_csv("survey.csv", ["survey_year", "survey_id", "survey", "fieldwork", "has_state_results"],
              [[int(s["SurveyYear"]), s["SurveyId"], f"{s['SurveyYear']} DHS",
                f"{s['FieldworkStart'][:7]} to {s['FieldworkEnd'][:7]}", 1 if int(s["SurveyYear"]) in STATE_ROUNDS else 0]
               for s in sorted(surveys, key=lambda s: int(s["SurveyYear"]))])
    write_csv("zone.csv", ["zone", "zone_order"], [[zone, order] for order, zone in enumerate(ZONES, start=1)])
    write_csv("state.csv", ["state", "zone", "iso_code", "map_location"],
              [[state, zone, iso, ("Federal Capital Territory" if state == "FCT" else state) + ", Nigeria"]
               for state, (zone, iso) in sorted(STATES.items())])
    write_csv("state_values.csv", ["survey_year", "indicator_id", "state", "value", "weighted_n", "unweighted_n"],
              sorted(state_rows, key=lambda row: (row[1], row[0], row[2])))
    write_csv("zone_values.csv", ["survey_year", "indicator_id", "zone", "value", "weighted_n", "unweighted_n"],
              sorted(zone_rows, key=lambda row: (row[1], row[0], row[2])))
    write_csv("national_values.csv", ["survey_year", "indicator_id", "value", "weighted_n"],
              sorted(national_rows, key=lambda row: (row[1], row[0])))


if __name__ == "__main__":
    main()
