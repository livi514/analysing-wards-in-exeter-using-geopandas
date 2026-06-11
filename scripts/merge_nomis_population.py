#!/usr/bin/env python3
"""
Fetch Nomis population for Exeter wards, merge with local ward shapefile,
compute area (km^2) and population density, and save a merged GeoJSON.

Usage:
    python scripts/merge_nomis_population.py --shapefile path/to/wards.shp

Defaults assume Nomis dataset `NM_144_1` (KS101EW - usual resident population).
"""
import argparse
import sys
import requests
import io
import pandas as pd
import geopandas as gpd

NOMIS_BASE = "https://www.nomisweb.co.uk/api/v01"


def find_exeter_geocodes(dataset_id="NM_144_1"):
    url = f"{NOMIS_BASE}/dataset/{dataset_id}/geography.def.sdmx.json?search=*Exeter*"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    j = r.json()
    # Traverse JSON to find codelist items. SDMX structure varies; try common path.
    codes = []
    try:
        codelists = j["structure"]["codelists"]["codelist"]
        for cl in codelists:
            if "code" in cl:
                for code in cl["code"]:
                    name = ""
                    if isinstance(code.get("name"), dict):
                        name = code["name"].get("value", "")
                    else:
                        name = code.get("name", "")
                    if "Exeter" in name:
                        codes.append((code["id"], name))
    except Exception:
        pass
    # Fallback: look for any occurrences of 'Exeter' in the JSON text and try to extract codes nearby
    if not codes:
        text = r.text
        # crude fallback: pull lines that contain Exeter and try to capture an "id":"E05..." token nearby
        for line in text.splitlines():
            if "Exeter" in line:
                # try to find id token in the previous few lines
                # (not robust but useful as fallback)
                pass
    return codes


def download_population_csv(dataset_id, geocodes):
    # geocodes: list of geography code ids (e.g., E050...)
    geostr = ",".join([c for c in geocodes])
    # select geography_code,geography_name,obs_value and time=latest
    url = f"{NOMIS_BASE}/dataset/{dataset_id}.data.csv?geography={geostr}&time=latest&select=geography_code,geography_name,obs_value"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    return df


def detect_join_column(gdf, pop_codes):
    # Try to find a column in gdf whose values intersect with pop_codes
    pop_set = set(pop_codes)
    for col in gdf.columns:
        if gdf[col].dtype == object or pd.api.types.is_string_dtype(gdf[col]):
            sample_vals = gdf[col].dropna().astype(str).unique()[:1000]
            if any(v in pop_set for v in sample_vals):
                return col
    # No direct match found
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shapefile", required=True, help="Path to local ward shapefile (e.g. wards.shp)")
    parser.add_argument("--dataset", default="NM_144_1", help="Nomis dataset id (default NM_144_1)")
    parser.add_argument("--output", default="merged_wards_population.geojson", help="Output GeoJSON path")
    args = parser.parse_args()

    print("Finding Exeter geocodes in Nomis...")
    codes = find_exeter_geocodes(args.dataset)
    if not codes:
        print("No Exeter geocodes found via Nomis dataset codelist. Exiting.")
        sys.exit(1)
    # codes is list of (id, name)
    geocodes = [cid for cid, _ in codes]
    print(f"Found {len(geocodes)} geocode entries; example: {geocodes[:5]}")

    print("Downloading population CSV from Nomis...")
    pop_df = download_population_csv(args.dataset, geocodes)
    # normalize column names
    pop_df.columns = [c.strip().lower() for c in pop_df.columns]
    if "geography_code" not in pop_df.columns or "obs_value" not in pop_df.columns:
        print("Unexpected columns in Nomis CSV:", pop_df.columns.tolist())
        # try to print first rows for debugging
        print(pop_df.head().to_string())
        sys.exit(1)
    pop_df = pop_df[["geography_code", "geography_name", "obs_value"]].dropna(subset=["geography_code"]) 
    pop_df = pop_df.drop_duplicates(subset=["geography_code"])  # keep latest per geography
    pop_df = pop_df.rename(columns={"geography_code":"gss_code", "obs_value":"population"})
    pop_df["population"] = pd.to_numeric(pop_df["population"], errors="coerce")

    print("Reading shapefile...")
    gdf = gpd.read_file(args.shapefile)

    # Try to detect join column
    join_col = detect_join_column(gdf, pop_df["gss_code"].astype(str).tolist())
    if join_col is None:
        print("Could not automatically detect a matching code column in the shapefile.")
        print("Shapefile columns:", gdf.columns.tolist())
        print("Provide a shapefile with a column containing GSS ward codes (e.g., E050...) or modify this script to set the join column manually.")
        sys.exit(1)
    print(f"Using shapefile column '{join_col}' to join on Nomis GSS codes.")

    # ensure strings
    gdf[join_col] = gdf[join_col].astype(str)
    merged = gdf.merge(pop_df, left_on=join_col, right_on="gss_code", how="left")

    # compute area in km^2 using British National Grid (EPSG:27700)
    merged = merged.to_crs(epsg=27700)
    merged["area_km2"] = merged.geometry.area / 1e6
    merged["population"] = pd.to_numeric(merged["population"], errors="coerce")
    merged["pop_density_per_km2"] = merged["population"] / merged["area_km2"]

    print("Saving merged GeoJSON to", args.output)
    merged.to_file(args.output, driver="GeoJSON")
    print("Done. Output saved.")


if __name__ == "__main__":
    main()
