import pandas as pd
from utils.column_mapping import FIELDS, QC_REQUIRED


def qc_source_errors(raw, data, mapping):
    """Validate mapped template fields without guessing business meaning or dates.

    Required values must be usable for dated supplier/category quantity analysis.
    Optional quantities keep their existing per-metric diagnostics and rate guards.
    Nothing is written back to the source.
    """
    errors = []
    if raw.empty:
        errors.append("QC source has no data records below the selected header row.")
    for field, header in QC_REQUIRED.items():
        source = mapping.get(field)
        if source is None or source not in raw.columns:
            errors.append(f"Missing required column: {header} ({FIELDS[field]}). "
                          "Check the worksheet/header row or explicitly map an equivalent source field in Data management.")
            continue
        invalid = data[field].isna()
        if invalid.any():
            rows = ", ".join(str(int(row)) for row in data.loc[invalid, "source_row"].head(10))
            expectation = ("valid dates" if field == "date" else
                           "finite nonnegative numeric quantities" if field == "adverse" else "nonblank labels")
            errors.append(f"Invalid required column '{source}' ({FIELDS[field]}): "
                          f"{int(invalid.sum())} missing or invalid value(s); expected {expectation}. "
                          f"Source row(s): {rows}" + (" (first 10 shown)." if invalid.sum() > 10 else ".") +
                          " Correct the source or review the mapping/date parsing setting; no records were silently discarded.")
    return errors


def quality_summary(raw, data, mapping):
    missing = [{"Field": c, "Type": str(raw[c].dtype),
                "Observed value type": pd.api.types.infer_dtype(raw[c].dropna()),
                "Missing cells": int((raw[c].isna() | raw[c].astype("string").str.strip().eq("").fillna(False)).sum()),
                "Distinct values": int(raw[c].nunique())} for c in raw]
    warnings = []
    for f in FIELDS:
        if not mapping.get(f):
            warnings.append(f"Unmapped {FIELDS[f]}: related analyses are unavailable.")
    duplicates = int(raw.duplicated().sum())
    if duplicates:
        warnings.append(f"{duplicates} duplicate-looking rows beyond the first occurrence retained.")
    for f in ("supplier", "product", "category"):
        labels = data[f].dropna().unique()
        groups = {}
        for v in labels:
            groups.setdefault(" ".join(v.casefold().split()), []).append(v)
        variants = [v for v in groups.values() if len(v) > 1]
        if variants:
            warnings.append(f"Possible inconsistent {f} labels (not merged): {variants}")
    return pd.DataFrame(missing), warnings
