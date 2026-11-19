"""All analytical formulas. Quantities are not assumed to count defective units."""
import pandas as pd
import numpy as np


def total_adverse(data):
    return data.adverse.sum(min_count=1)


def supplier_count(data):
    return data.supplier.nunique(dropna=True)


def grouped(data, field, metric="adverse"):
    work = data.assign(**{field: data[field].fillna("(Missing)")})
    return (work.groupby(field, dropna=False)[metric].sum(min_count=1)
            .dropna().reset_index().sort_values([metric, field], ascending=[False, True]))


def category_shares(data):
    table = grouped(data, "category")
    total = table.adverse.sum()
    table["Share (%)"] = table.adverse / total * 100 if total > 0 else float("nan")
    table["Cumulative (%)"] = table.adverse.cumsum() / total * 100 if total > 0 else float("nan")
    return table.reset_index(drop=True)


def monthly(data, by=None):
    work = data[data.date.notna()].copy()
    work["month"] = work.date.dt.to_period("M").dt.to_timestamp()
    keys = ["month"]
    if by:
        work[by] = work[by].fillna("(Missing)")
        keys.append(by)
    return work.groupby(keys).adverse.sum(min_count=1).dropna().reset_index().sort_values(keys)


def supplier_table(data):
    rows = []
    for name, group in data[data.supplier.notna()].groupby("supplier"):
        modes = group.category.dropna().mode()
        rows.append({"Supplier": name, "Recorded adverse quantity": total_adverse(group),
                     "QC records": len(group),
                     "Most frequent category (by records)": ", ".join(modes),
                     "Related products / parts": ", ".join(sorted(group['product'].dropna().unique()))})
    return pd.DataFrame(rows, columns=["Supplier", "Recorded adverse quantity", "QC records",
                                      "Most frequent category (by records)", "Related products / parts"]).sort_values(
                                          ["Recorded adverse quantity", "Supplier"], ascending=[False, True])


def ranking_records(data):
    """Ranking requires a named supplier, a dated record and a valid quantity.

    Undated records are excluded even if the shared scope includes them in totals.
    Zero is valid; missing quantities never become zero.
    """
    quantities = pd.to_numeric(data.adverse, errors="coerce")
    named = data.supplier.astype("string").str.strip().fillna("").ne("")
    mask = named & data.date.notna() & quantities.notna() & np.isfinite(quantities) & quantities.ge(0)
    return data.loc[mask].assign(adverse=quantities.loc[mask])


def frequent_categories(data):
    """All tied most-frequent categories by eligible QC records, in label order."""
    labels = data.category.astype("string").str.strip().replace("", pd.NA).dropna()
    return ", ".join(sorted(labels.mode(), key=lambda s: (s.casefold(), s))) or "Unavailable"


def supplier_ranking(data, ascending=True, limit=5, reporting_period=None):
    """Descriptive totals only; ties use casefolded supplier name then exact name."""
    columns = ["Rank", "Supplier", "Recorded adverse quantity", "Months with records",
               "Most frequent category (by records)", "Reporting period", "Valid QC records",
               "Excluded quantity records"]
    valid = ranking_records(data)
    if reporting_period is None:
        dates = data.date.dropna()
        reporting_period = (f"{dates.min():%d %b %Y} – {dates.max():%d %b %Y}"
                            if not dates.empty else "No dated records")
    rows = []
    for name, group in valid.groupby("supplier"):
        source = data[data.supplier.eq(name) & data.date.notna()]
        rows.append({"Supplier": name, "Recorded adverse quantity": total_adverse(group),
                     "Months with records": group.date.dt.to_period("M").nunique(),
                     "Most frequent category (by records)": frequent_categories(group),
                     "Reporting period": reporting_period, "Valid QC records": len(group),
                     "Excluded quantity records": len(source) - len(group)})
    if not rows:
        return pd.DataFrame(columns=columns)
    table = pd.DataFrame(rows)
    table["_name"] = table.Supplier.str.casefold()
    table = table.sort_values(["Recorded adverse quantity", "_name", "Supplier"],
                              ascending=[ascending, True, True]).head(limit).drop(columns="_name")
    table.insert(0, "Rank", range(1, len(table) + 1))
    return table[columns].reset_index(drop=True)


def monthly_observation(data):
    """Compare first/last recorded monthly totals, without assuming monotonicity."""
    dated = data[data.date.notna()]
    totals = monthly(ranking_records(data))
    if len(totals) < 2:
        return {"available": False, "reason": "At least two months with valid dated adverse quantities are needed for a monthly comparison."}
    first, last = totals.iloc[0], totals.iloc[-1]
    endpoints = dated[dated.date.dt.to_period("M").isin([first.month.to_period("M"), last.month.to_period("M")])]
    if len(ranking_records(endpoints)) != len(endpoints):
        return {"available": False, "reason": "The first or last recorded month has invalid or missing quantities; a complete monthly comparison is unavailable."}
    delta = last.adverse - first.adverse
    return {"available": True, "first_month": first.month, "last_month": last.month,
            "first_total": first.adverse, "last_total": last.adverse,
            "direction": "increased" if delta > 0 else "decreased" if delta < 0 else "unchanged",
            "months": len(totals)}


def adverse_statuses(ranking):
    """Descriptive empirical quartiles, not official quality classifications."""
    result = ranking.copy()
    quantities = result["Recorded adverse quantity"]
    cuts = (quantities.quantile([.25, .5, .75]) if not result.empty else
            pd.Series(float("nan"), index=[.25, .5, .75]))
    if result.empty:
        result["Recorded adverse status"] = pd.Series(dtype="string")
    elif quantities.nunique() == 1:
        result["Recorded adverse status"] = "Same Recorded Adverse"
    else:
        result["Recorded adverse status"] = quantities.map(
            lambda value: "Low Recorded Adverse" if value <= cuts.loc[.25] else
            "Moderate Recorded Adverse" if value <= cuts.loc[.5] else
            "High Recorded Adverse" if value <= cuts.loc[.75] else "Highest Recorded Adverse")
    return result, cuts


def quantity_total(data, field):
    # A scope total requires complete valid values; no imputation of blanks as zero.
    return data[field].sum() if len(data) and data[field].notna().all() else None


def verified_rate(data, numerator, confirmed=False):
    """Ratio of sums for the identical scope. Reject incomplete or impossible scopes."""
    if not confirmed:
        return None
    num, den = quantity_total(data, numerator), quantity_total(data, "inspection")
    if num is None or den is None or den <= 0 or num > den:
        return None
    if (data[numerator] > data.inspection).any():
        return None
    complete = data[["accepted", "rejected", "inspection"]].dropna()
    if ((complete.accepted + complete.rejected) > complete.inspection).any():
        return None
    return num / den * 100


def filter_data(data, period=None, selections=None, include_undated=False):
    mask = pd.Series(True, index=data.index)
    if period and len(period) == 2:
        dated = data.date.between(pd.Timestamp(period[0]), pd.Timestamp(period[1]))
        mask &= dated | (data.date.isna() if include_undated else False)
    for field, values in (selections or {}).items():
        if values:
            mask &= data[field].fillna("(Missing)").isin(values)
    return data.loc[mask].copy()
