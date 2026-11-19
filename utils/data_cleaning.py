"""Retain all records; invalid analytical values become missing with row diagnostics."""
from datetime import datetime, date
import numbers
import numpy as np
import pandas as pd
from utils.column_mapping import FIELDS

TEXT_FIELDS = ("supplier", "product", "category")
NUMERIC_FIELDS = ("adverse", "inspection", "accepted", "rejected")


def parse_date(value, dayfirst=False):
    if pd.isna(value) or str(value).strip() == "":
        return pd.NaT
    try:
        if isinstance(value, (datetime, date, pd.Timestamp)):
            return pd.Timestamp(value).tz_localize(None).normalize()
        if isinstance(value, numbers.Number):
            # Excel serial dates only; numeric YYYYMMDD is handled explicitly.
            if 19000101 <= value <= 21001231:
                return pd.to_datetime(str(int(value)), format="%Y%m%d", errors="coerce")
            if 1 <= value <= 100000:
                return (pd.Timestamp("1899-12-30") + pd.to_timedelta(value, unit="D")).normalize()
            return pd.NaT
        parsed = pd.to_datetime(str(value).strip(), dayfirst=dayfirst, errors="coerce")
        return pd.NaT if pd.isna(parsed) else parsed.tz_localize(None).normalize()
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def prepare_data(raw, mapping, dayfirst=False, header_row=1):
    result = pd.DataFrame(index=raw.index)
    result["source_row"] = np.arange(len(raw)) + header_row + 1
    issues = [[] for _ in range(len(raw))]
    def flag(mask, message):
        for i in np.flatnonzero(mask.to_numpy(dtype=bool)):
            issues[i].append(message)
    for field in FIELDS:
        source = mapping.get(field)
        values = raw[source] if source in raw.columns else pd.Series(pd.NA, index=raw.index)
        if field in TEXT_FIELDS:
            result[field] = values.astype("string").str.strip().replace("", pd.NA)
            if source:
                flag(result[field].isna(), f"Missing {field}")
        elif field in NUMERIC_FIELDS:
            numbers_ = pd.to_numeric(values, errors="coerce").astype(float)
            valid = numbers_.notna() & np.isfinite(numbers_) & numbers_.ge(0)
            result[field] = numbers_.where(valid)
            if source:
                flag(~valid, f"Missing, nonnumeric, nonfinite or negative {field}; excluded from this quantity")
        else:
            result[field] = pd.to_datetime(values.map(lambda v: parse_date(v, dayfirst)), errors="coerce")
            if source:
                flag(result[field].isna(), "Missing / invalid date; excluded from dated analyses")
    flag(raw.duplicated(keep=False), "Duplicate-looking source row retained")
    for f in ("accepted", "rejected"):
        flag(result[f].gt(result["inspection"]), f"{f} exceeds inspection quantity; rate unavailable")
    flag((result.accepted + result.rejected).gt(result.inspection),
         "Accepted + rejected exceeds inspection quantity; rates unavailable")
    result["issues"] = ["; ".join(x) for x in issues]
    return result
