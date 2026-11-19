"""Criteria AHP and explicitly non-pairwise inverse-adverse simulation.

No expert judgements are generated. Workbook outputs are independently recomputed.
"""
from io import BytesIO
import hashlib
import numpy as np
import pandas as pd
import openpyxl
from utils.data_cleaning import prepare_data

SIMULATION = "SIMULATION — NOT OFFICIAL MTM SUPPLIER EVALUATION"
CRITERIA = ("Abnormal Function", "Abnormal Withstand Voltage", "Inaccurate Size",
            "Bad Appearance", "Poor Plating")
RI_FIVE = 1.12
ALIASES = {name.casefold(): name for name in CRITERIA}
ALIASES["bad apperance"] = "Bad Appearance"


def criterion_name(value):
    return ALIASES.get(str(value).strip().casefold())


def criteria_ahp(matrix):
    """Principal right eigenvector, lambda max, CI and CR for five criteria."""
    a = np.asarray(matrix, dtype=float)
    if a.shape != (5, 5) or not np.isfinite(a).all() or (a <= 0).any():
        raise ValueError("Criteria matrix must contain 25 finite positive comparisons for the five criteria.")
    if not np.allclose(np.diag(a), 1, atol=1e-8, rtol=1e-8) or not np.allclose(a * a.T, 1, atol=1e-8, rtol=1e-8):
        raise ValueError("Criteria matrix must have unit diagonal and reciprocal comparisons (A/B = 1/(B/A)).")
    values, vectors = np.linalg.eig(a)
    index = np.argmax(values.real)
    weights = vectors[:, index].real
    if weights.sum() < 0:
        weights = -weights
    if (weights <= 0).any():
        raise ValueError("Could not derive positive principal priorities.")
    weights /= weights.sum()
    maximum = float(values[index].real)
    ci = max(0.0, (maximum - 5) / 4)
    if ci < 1e-12:
        ci = 0.0  # Roundoff only, not a change to a materially inconsistent matrix.
    return {"weights": pd.Series(weights, index=CRITERIA, name="Simulation weight"),
            "lambda_max": maximum, "CI": ci, "RI": RI_FIVE, "CR": ci / RI_FIVE}


def defect_matrix(data, require_dates=True):
    """Explicit workbook simulation assumption: unrecorded supplier/category = 0.

    Reject incomplete records instead of silently dropping them or inventing inputs.
    """
    if data.empty:
        raise ValueError("No records in this scope; simulation scores are unavailable.")
    work = data.copy()
    work["criterion"] = work.category.map(criterion_name)
    qty = pd.to_numeric(work.adverse, errors="coerce")
    checks = {
        "missing supplier": work.supplier.astype("string").str.strip().fillna("").eq(""),
        "missing, nonnumeric, nonfinite or negative adverse quantity": qty.isna() | ~np.isfinite(qty) | qty.lt(0),
        "missing or unrecognized defect category": work.criterion.isna(),
    }
    if require_dates:
        checks["missing or invalid date"] = work.date.isna()
    problems = [f"{int(mask.sum())} {label}" for label, mask in checks.items() if mask.any()]
    if problems:
        raise ValueError("Cannot calculate simulation: " + "; ".join(problems) + ". Correct the data or narrow the shared filters.")
    work["adverse"] = qty
    return (work.groupby(["supplier", "criterion"]).adverse.sum().unstack(fill_value=0)
            .reindex(columns=CRITERIA, fill_value=0).sort_index())


def inverse_simulation(defects, weights):
    """Reproduce workbook Method B; these are NOT alternative AHP comparisons."""
    if defects.empty or defects.index.has_duplicates or defects.index.isna().any():
        raise ValueError("A nonempty matrix with unique named suppliers is required.")
    if any(not str(name).strip() for name in defects.index):
        raise ValueError("Supplier names cannot be blank.")
    if set(defects.columns) != set(CRITERIA) or set(weights.index) != set(CRITERIA):
        raise ValueError("All five criteria and weights are required; missing inputs are not imputed.")
    d = defects.loc[:, list(CRITERIA)].apply(pd.to_numeric, errors="coerce")
    w = pd.to_numeric(weights.reindex(CRITERIA), errors="coerce")
    if not np.isfinite(d.to_numpy()).all() or (d < 0).any().any():
        raise ValueError("Defect matrix must contain complete nonnegative finite recorded quantities.")
    if not np.isfinite(w.to_numpy()).all() or (w <= 0).any() or not np.isclose(w.sum(), 1):
        raise ValueError("Criteria weights must be positive, finite and sum to one.")
    inverse = 1 / (d + 1)
    local = inverse.div(inverse.sum(axis=0), axis=1)
    contributions = local.mul(w, axis=1)
    scores = contributions.sum(axis=1)
    ranking = pd.DataFrame({"Supplier": d.index, "Simulation score": scores.to_numpy(),
                            "Recorded adverse quantity": d.sum(axis=1).to_numpy()})
    ranking["_sort"] = ranking.Supplier.str.casefold()
    ranking = ranking.sort_values(["Simulation score", "_sort", "Supplier"], ascending=[False, True, True]).drop(columns="_sort")
    ranking.insert(0, "Simulation rank", range(1, len(ranking) + 1))
    ranking["Status"] = SIMULATION
    return {"local": local, "contributions": contributions, "ranking": ranking.reset_index(drop=True)}


def read_ahp_workbook(blob):
    """Read every sheet, validate the known source schema, audit stored outputs.

    openpyxl does not evaluate Excel formulas. Formula cells, if present in a
    replacement, are flagged; missing cached required values prevent calculation.
    """
    formulas = openpyxl.load_workbook(BytesIO(blob), data_only=False)
    cached = openpyxl.load_workbook(BytesIO(blob), data_only=True)
    sheets = {}
    inventory = []
    for sheet in cached:
        rows = list(sheet.values)
        sheets[sheet.title] = pd.DataFrame(rows[1:], columns=rows[0]) if rows else pd.DataFrame()
        count = sum(cell.data_type == "f" for row in formulas[sheet.title] for cell in row)
        inventory.append({"Worksheet": sheet.title, "Rows including header": sheet.max_row,
                          "Columns": sheet.max_column, "Excel formula cells": count,
                          "Merged ranges": ', '.join(str(r) for r in formulas[sheet.title].merged_cells.ranges),
                          "Formula cells without cache": sum(cell.data_type == 'f' and sheet[cell.coordinate].value is None
                                                             for row in formulas[sheet.title] for cell in row)})
    if "Matriks_AHP" in sheets:
        from utils.ahp_capstone import read_capstone_ahp
        try:
            return read_capstone_ahp(formulas, cached, sheets, pd.DataFrame(inventory), blob)
        finally:
            formulas.close()
            cached.close()
    if "Kriteria" in sheets or "Pairwise" in sheets:
        from utils.ahp_new import read_new_ahp
        try:
            return read_new_ahp(formulas, cached, sheets, inventory, blob)
        finally:
            formulas.close()
            cached.close()
    formulas.close()
    cached.close()
    for required in ("Criteria Pairwise", "Raw Data"):
        if required not in sheets:
            raise ValueError(f"Missing worksheet '{required}'. Expected the supplied AHP simulation workbook layout.")
    pairwise = sheets["Criteria Pairwise"].set_index("Criteria")
    if pairwise.index.has_duplicates or not set(CRITERIA).issubset(pairwise.index) or not set(CRITERIA).issubset(pairwise.columns):
        raise ValueError("Criteria Pairwise must identify every criterion once in both rows and columns.")
    matrix = pairwise.loc[list(CRITERIA), list(CRITERIA)].astype(float)
    ahp = criteria_ahp(matrix)
    raw = sheets["Raw Data"]
    mapping = {"date": "Date of opening", "supplier": "Responsible unit", "category": "Bad reasons", "adverse": "Adverse number", "product": "Part No"}
    missing = set(mapping.values()) - set(raw.columns)
    if missing:
        raise ValueError(f"Raw Data lacks required fields: {', '.join(sorted(missing))}")
    processed = prepare_data(raw, mapping)
    defects = defect_matrix(processed)
    simulation = inverse_simulation(defects, ahp["weights"])
    audit = []

    def check(label, actual, expected):
        try:
            left, right = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
            passed = left.shape == right.shape and np.allclose(left, right, atol=1e-10, rtol=1e-8, equal_nan=False)
            difference = float(np.max(np.abs(left - right))) if left.shape == right.shape and left.size else None
        except (ValueError, TypeError):
            passed, difference = False, None
        audit.append({"Check": label, "Result": "Matches" if passed else "Mismatch / missing", "Maximum absolute difference": difference})

    summary = sheets.get("Ringkasan", pd.DataFrame())
    if summary.shape[1] >= 2:
        controls = dict(zip(summary.iloc[:, 0], summary.iloc[:, 1]))
        for key, expected in [("Jumlah supplier", len(defects)), ("Jumlah baris data valid", len(processed)),
                              ("Total Adverse number tercatat", defects.sum().sum())]:
            check(f"Ringkasan: {key}", controls.get(key), expected)

    # Stored outputs are controls, not the source of calculated scores.
    try:
        stored = sheets["Criteria Weights"].set_index("Criterion")
        check("Criteria Weights: weights", stored.loc[list(CRITERIA), "Weight"], ahp["weights"])
        check("Criteria Weights: weight percentages", stored.loc[list(CRITERIA), "Weight (%)"], ahp["weights"] * 100)
        for sheet, label, key in [("Consistency Check", "Metric", "Value"), ("Criteria Weights", "Criterion", "Weight")]:
            params = sheets[sheet].set_index(label)[key]
            for metric, expected in [("Lambda max", ahp["lambda_max"]), ("n", 5), ("CI", ahp["CI"]), ("RI", RI_FIVE), ("CR", ahp["CR"])]:
                check(f"{sheet}: {metric}", params.loc[metric], expected)
    except (KeyError, ValueError):
        check("Criteria weights / consistency controls available", [], [1])
    try:
        source = sheets["Defect Matrix"].set_index("Supplier")
        check("Defect Matrix: supplier set", len(source.index.symmetric_difference(defects.index)), 0)
        check("Defect Matrix: all category quantities from Raw Data", source.reindex(defects.index)[list(CRITERIA)], defects)
        check("Defect Matrix: totals", source.reindex(defects.index)["Total Defect Recorded"], defects.sum(axis=1))
        clean = sheets["Clean Data"]
        check("Clean Data: original field values and record order", clean[raw.columns].equals(raw), True)
        check("Clean Data: normalized categories", clean["Category Normalized"].eq(processed.category.map(criterion_name)).all(), True)
        local = sheets["Local Priorities"]
        index = pd.MultiIndex.from_product([defects.index, CRITERIA], names=["Supplier", "Criterion"])
        local = local.set_index(["Supplier", "Criterion"])
        check("Local Priorities: row coverage", len(local.index.symmetric_difference(index)), 0)
        check("Local Priorities: quantities", local.reindex(index)["Defect count"], defects.to_numpy().ravel())
        check("Local Priorities: inverse-count normalized priorities", local.reindex(index)["Local priority"], simulation["local"].to_numpy().ravel())
        final = sheets["Final Ranking"].set_index("Supplier")
        scores = simulation["ranking"].set_index("Supplier")
        check("Final Ranking: supplier set", len(final.index.symmetric_difference(defects.index)), 0)
        check("Final Ranking: weighted scores", final.reindex(scores.index)["Final Score"], scores["Simulation score"])
        check("Final Ranking: ordered ranks (deterministic name tie-break)", final.reindex(scores.index)["Rank"], scores["Simulation rank"])
        check("Final Ranking: category quantities", final.reindex(defects.index)[list(CRITERIA)], defects)
    except (KeyError, ValueError):
        check("Supplier output controls available and unique", [], [1])
    try:
        inputs = sheets["Pairwise Input Simulasi"]
        inputs = inputs[inputs["Criteria A"].isin(CRITERIA) & inputs["Criteria B"].isin(CRITERIA)]
        check("Pairwise Input Simulasi: ten unique upper comparisons", len(set(zip(inputs["Criteria A"], inputs["Criteria B"]))), 10)
        check("Pairwise Input Simulasi: ratios", inputs["Pairwise value A/B"],
              [matrix.loc[row["Criteria A"], row["Criteria B"]] for _, row in inputs.iterrows()])
    except KeyError:
        check("Pairwise input controls available", [], [1])
    optional = sheets.get("Supplier Pairwise (Opsional)", pd.DataFrame())
    filled = int(optional.get("Saaty intensity (1-9)", pd.Series(dtype=float)).notna().sum())
    dates = processed.date.dropna()
    return {"format": "legacy_inverse", "sheets": sheets, "inventory": pd.DataFrame(inventory), "matrix": matrix,
            "ahp": ahp, "defects": defects, "processed": processed, "simulation": simulation,
            "audit": pd.DataFrame(audit), "supplier_pairwise_rows": len(optional),
            "supplier_pairwise_filled": filled, "sha256": hashlib.sha256(blob).hexdigest(),
            "period": f"{dates.min():%d %b %Y} – {dates.max():%d %b %Y}"}
