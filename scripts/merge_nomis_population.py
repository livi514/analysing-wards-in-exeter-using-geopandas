#!/usr/bin/env python3
"""
Calculate area (km²) for ward geometries from a shapefile or GeoDataFrame.

Usage:
    python scripts/merge_nomis_population.py --shapefile path/to/wards.shp

The module can also be imported from a Jupyter notebook and used via
`merge_population_with_shapefile`.
"""

import argparse
import pandas as pd
import geopandas as gpd


def detect_local_gss_column(gdf):
    """Attempt to detect a local GeoDataFrame column containing GSS ward codes."""
    def is_gss_code(val):
        return isinstance(val, str) and val.startswith(("E05", "W05", "S01", "N08"))

    for col in gdf.columns:
        if gdf[col].dtype == object or pd.api.types.is_string_dtype(gdf[col]):
            sample_vals = gdf[col].dropna().astype(str).unique()[:1000]
            if any(is_gss_code(v) for v in sample_vals):
                return col

    # fallback: first string-like column with plausible code length
    for col in gdf.columns:
        if gdf[col].dtype == object or pd.api.types.is_string_dtype(gdf[col]):
            sample_vals = gdf[col].dropna().astype(str).unique()[:1000]
            if any(len(v) >= 5 for v in sample_vals):
                return col

    return None


def merge_population_with_shapefile(
    shapefile,
    dataset="NM_144_1",
    output=None,
    join_column=None,
    save_output=True,
):
    """Process ward shapefile or GeoDataFrame and calculate area.

    `shapefile` may be either a file path or a GeoDataFrame.
    Detects GSS code column and projects to EPSG:27700 (BNG).
    Returns a GeoDataFrame containing the ward geometry with area_km2 column.
    """
    if isinstance(shapefile, gpd.GeoDataFrame):
        gdf = shapefile.copy()
    else:
        gdf = gpd.read_file(shapefile)

    if join_column is not None:
        if join_column not in gdf.columns:
            raise ValueError(f"Join column '{join_column}' not found in shapefile columns: {gdf.columns.tolist()}")
        join_col = join_column
    else:
        # Detect the local GSS code column from the GeoDataFrame
        join_col = detect_local_gss_column(gdf)
        if join_col is None:
            raise ValueError(
                "Could not automatically detect a GSS code column in the shapefile. "
                f"Shapefile columns: {gdf.columns.tolist()}"
            )

    gdf[join_col] = gdf[join_col].astype(str)
    
    # Calculate area and return the GeoDataFrame
    merged = gdf.copy()
    merged = merged.to_crs(epsg=27700)
    merged["area_km2"] = merged.geometry.area / 1e6

    if save_output and output:
        merged.to_file(output, driver="GeoJSON")

    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shapefile", required=True, help="Path to local ward shapefile (e.g. wards.shp)")
    parser.add_argument("--dataset", default="NM_144_1", help="Nomis dataset id (default NM_144_1)")
    parser.add_argument("--output", default="merged_wards_population.geojson", help="Output GeoJSON path")
    args = parser.parse_args()

    merged = merge_population_with_shapefile(
        shapefile=args.shapefile,
        dataset=args.dataset,
        output=args.output,
        join_column=None,
        save_output=True,
    )
    print("Merged GeoDataFrame has", len(merged), "rows.")
    print("Saved merged GeoJSON to", args.output)


if __name__ == "__main__":
    main()
