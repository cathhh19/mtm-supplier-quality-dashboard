"""Reader for Kriteria / Data / Rekap / Pairwise / M_* / Hasil.

Reproduces the workbook's column-normalization / row-average method, NOT
the older inverse-count method. Matrices are simulated data transformations.
"""
import hashlib
import itertools
import math
import numpy as np
import pandas as pd
from utils.ahp import CRITERIA, SIMULATION, criterion_name, defect_matrix
from utils.data_cleaning import prepare_data

MATRIX_SHEETS = {"M_Function": CRITERIA[0], "M_Voltage": CRITERIA[1], "M_Size": CRITERIA[2],
                 "M_Appearance": CRITERIA[3], "M_Plating": CRITERIA[4]}


def matrix_statistics(matrix, ri):
    a = np.asarray(matrix, dtype=float)
    n = len(a)
    if a.ndim != 2 or a.shape != (n, n) or n < 2:
        raise ValueError("A square comparison matrix with at least two alternatives is required.")
    if not np.isfinite(a).all() or (a <= 0).any():
        raise ValueError("Comparison matrices require complete, finite, positive numbers; recalculate and save Excel if formula caches are missing.")
    if not np.allclose(np.diag(a), 1, atol=1e-8, rtol=1e-8) or not np.allclose(a * a.T, 1, atol=1e-8, rtol=1e-8):
        raise ValueError("Comparison matrix must have a unit diagonal and reciprocal off-diagonal values.")
    if not np.isfinite(ri) or ri < 0 or (n > 2 and ri == 0):
        raise ValueError("A documented positive RI is required for matrices larger than two.")
    weights = (a / a.sum(axis=0)).mean(axis=1)
    ratios = (a @ weights) / weights
    estimate = float(ratios.mean())
    eigenvalue = float(np.linalg.eigvals(a).real.max())
    ci = max(0., (estimate - n) / (n - 1))
    exact_ci = max(0., (eigenvalue - n) / (n - 1))
    if ci < 1e-12:
        ci = 0.
    return {"weights": weights, "column_sums": a.sum(axis=0), "ratios": ratios,
            "lambda_max": estimate, "CI": ci, "RI": float(ri), "CR": ci / ri if ri else 0.,
            "eigenvalue_reference": eigenvalue, "eigen_CR_reference": exact_ci / ri if ri else 0.}


def header_table(book, sheet_name, first, required):
    sheet = book[sheet_name]
    for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 30)):
        labels = [str(cell.value).strip() if cell.value is not None else "" for cell in row]
        if labels[0] == first and set(required).issubset(labels):
            named = [label for label in labels if label]
            if len(named) != len(set(named)):
                raise ValueError(f"Worksheet '{sheet_name}' has duplicate column labels.")
            return sheet, row[0].row, labels
    raise ValueError(f"Worksheet '{sheet_name}' has no identifiable '{first}' header with fields: {', '.join(required)}.")


def numeric(sheet, row, column):
    value = sheet.cell(row, column).value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        raise ValueError(f"Missing/non-numeric value at {sheet.title}!{sheet.cell(row,column).coordinate}. Recalculate in Excel and save the workbook if this is a formula.")
    return float(value)


def read_new_ahp(formulas, cached, previews, inventory, blob):
    required = {"Kriteria", "Data", "Rekap", "Pairwise", "Hasil"}
    missing = required - set(cached.sheetnames)
    if missing:
        raise ValueError("New AHP format lacks required worksheets: " + ", ".join(sorted(missing)))
    # Discover criterion from the matrix title; explicit names remain a safe fallback.
    mapping = {}
    for name in cached.sheetnames:
        if not name.startswith("M_"):
            continue
        title = str(cached[name].cell(1, 1).value)
        criterion = criterion_name(title.split(" - ")[-1]) or MATRIX_SHEETS.get(name)
        if criterion is None or criterion in mapping:
            raise ValueError(f"Ambiguous or duplicate supplier-matrix criterion in '{name}'.")
        mapping[criterion] = name
    if set(mapping) != set(CRITERIA):
        raise ValueError("Missing supplier comparison matrices for: " + ", ".join(set(CRITERIA) - set(mapping)))
    audit = []
    def check(label, actual, expected):
        try:
            a, e = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
            equal = a.shape == e.shape and np.allclose(a, e, atol=1e-10, rtol=1e-8)
            delta = float(np.abs(a-e).max()) if a.shape == e.shape and a.size else None
        except (ValueError, TypeError):
            equal, delta = False, None
        audit.append({"Check": label, "Result": "Matches" if equal else "Mismatch / missing", "Maximum absolute difference": delta})

    data_sheet, data_row, data_labels = header_table(cached, 'Data', 'Responsible unit', ['Bad reasons', 'Adverse number'])
    rows = [list(row) for row in data_sheet.iter_rows(min_row=data_row+1, values_only=True) if any(x is not None for x in row)]
    raw = pd.DataFrame(rows, columns=data_labels)
    processed = prepare_data(raw, {'supplier':'Responsible unit','category':'Bad reasons','adverse':'Adverse number'})
    defects = defect_matrix(processed, require_dates=False)
    recap, recap_row, recap_labels = header_table(cached, 'Rekap', 'Supplier', list(CRITERIA))
    suppliers = []
    r = recap_row + 1
    while r <= recap.max_row and recap.cell(r, 1).value in defects.index:
        suppliers.append(str(recap.cell(r, 1).value).strip())
        r += 1
    if len(suppliers) != len(set(suppliers)) or set(suppliers) != set(defects.index):
        raise ValueError("Rekap must list each Data supplier exactly once; blank, duplicate or mismatched supplier names were found.")
    defects = defects.reindex(suppliers)
    recap_values = [[numeric(recap, recap_row+1+i, recap_labels.index(c)+1) for c in CRITERIA] for i in range(len(suppliers))]
    check('Rekap: quantity aggregation from Data', recap_values, defects)
    if not np.allclose(recap_values, defects.to_numpy(), atol=1e-10, rtol=1e-8):
        raise ValueError("Rekap quantity caches disagree with Data. Recalculate and save the source; do not use stale matrices.")

    def read_matrix(sheet_name, first, labels):
        sheet, header_row, headers = header_table(cached, sheet_name, first, labels + ['Bobot', '(A.w)/w'])
        n = len(labels)
        matrix_columns=headers[1:headers.index('Bobot')]
        if len(matrix_columns)!=n or set(matrix_columns)!=set(labels):
            raise ValueError(f"'{sheet_name}' matrix column names/dimensions do not match its alternatives.")
        row_names = [str(sheet.cell(header_row+1+i, 1).value).strip() for i in range(n)]
        if len(set(row_names)) != n or set(row_names) != set(labels):
            raise ValueError(f"'{sheet_name}' matrix row names/dimensions do not match its alternatives.")
        row_map = {name:header_row+1+i for i,name in enumerate(row_names)}
        values = [[numeric(sheet, row_map[a], headers.index(b)+1) for b in labels] for a in labels]
        a=np.asarray(values)
        if (a < 1/9-1e-8).any() or (a > 9+1e-8).any():
            raise ValueError(f"'{sheet_name}' contains comparisons outside the documented 1/9–9 scale.")
        # Metric rows are found by labels, not fixed row coordinates.
        metrics = {str(sheet.cell(i,1).value):i for i in range(header_row+n+1, sheet.max_row+1) if sheet.cell(i,1).value is not None}
        ri_labels = [label for label in metrics if label.startswith('RI')]
        if len(ri_labels) != 1:
            raise ValueError(f"'{sheet_name}' requires one documented RI row.")
        ri_label = ri_labels[0]
        if n == 5 and first == 'Kriteria':
            ri = 1.12
        elif 'Alonso-Lamata' in ri_label and n > 2:
            ri = (1.7699*n-4.3513)/(n-1)
        elif n == 2:
            ri = 0.
        else:
            raise ValueError(f"'{sheet_name}': unsupported or undocumented RI convention for n={n}.")
        stats = matrix_statistics(values, ri)
        check(f'{sheet_name}: stored weights', [numeric(sheet,row_map[a],headers.index('Bobot')+1) for a in labels], stats['weights'])
        check(f'{sheet_name}: weighted-sum ratios', [numeric(sheet,row_map[a],headers.index('(A.w)/w')+1) for a in labels], stats['ratios'])
        for metric, expected in [('Lambda max',stats['lambda_max']),('n',n),('CI',stats['CI']),(ri_label,ri),('CR',stats['CR'])]:
            if metric not in metrics:
                raise ValueError(f"'{sheet_name}' lacks metric '{metric}'.")
            check(f'{sheet_name}: {metric}', numeric(sheet,metrics[metric],2), expected)
        return pd.DataFrame(values,index=labels,columns=labels), stats

    matrix, ahp = read_matrix('Kriteria', 'Kriteria', list(CRITERIA))
    ahp['weights'] = pd.Series(ahp['weights'], index=CRITERIA, name='Simulation weight')
    supplier_matrices, local, consistency = {}, pd.DataFrame(index=suppliers), []
    for criterion in CRITERIA:
        supplier_matrices[criterion], stats = read_matrix(mapping[criterion], 'Supplier', suppliers)
        local[criterion] = stats['weights']
        consistency.append({'Criterion':criterion,'Worksheet':mapping[criterion],'n':len(suppliers),
                            'Lambda estimate (row-average method)':stats['lambda_max'],'CI':stats['CI'],'RI':stats['RI'],'CR':stats['CR'],
                            'Perron eigenvalue (reference)':stats['eigenvalue_reference'],'Perron CR (reference)':stats['eigen_CR_reference']})

    pair, pair_row, pair_labels = header_table(cached,'Pairwise','Criterion',['Supplier A','Supplier B','Cacat A (pcs)','Cacat B (pcs)','Saaty intensity (1-9)','Preferred supplier'])
    pairs, filled, auto_count = set(), 0, 0
    mismatch_counts, mismatch_transforms = 0, 0
    for r in range(pair_row+1, pair.max_row+1):
        values = {label:pair.cell(r,i+1).value for i,label in enumerate(pair_labels)}
        criterion = criterion_name(values.get('Criterion'))
        if criterion is None:
            raise ValueError(f"Pairwise row {r}: unknown/missing criterion.")
        a,b = values['Supplier A'],values['Supplier B']
        if a not in suppliers or b not in suppliers or a == b:
            raise ValueError(f"Pairwise row {r}: invalid supplier pair.")
        key=(criterion,tuple(sorted([a,b])))
        if key in pairs:
            raise ValueError(f"Pairwise row {r}: duplicate supplier pair.")
        pairs.add(key)
        intensity = numeric(pair,r,pair_labels.index('Saaty intensity (1-9)')+1)
        if not intensity.is_integer() or not 1 <= intensity <= 9:
            raise ValueError(f"Pairwise row {r}: intensity must be an integer from 1 to 9.")
        preferred = values['Preferred supplier']
        if preferred not in [a,b,'Sama'] or (preferred == 'Sama' and intensity != 1):
            raise ValueError(f"Pairwise row {r}: preferred supplier must identify the pair or Sama with intensity 1.")
        comparison = 1. if preferred == 'Sama' else intensity if preferred == a else 1/intensity
        if not np.isclose(supplier_matrices[criterion].loc[a,b], comparison, atol=1e-8,rtol=1e-8):
            raise ValueError(f"{mapping[criterion]} disagrees with Pairwise row {r}; recalculate and save the workbook.")
        da,db = float(defects.loc[a,criterion]),float(defects.loc[b,criterion])
        mismatch_counts += not (np.isclose(numeric(pair,r,pair_labels.index('Cacat A (pcs)')+1),da) and
                                np.isclose(numeric(pair,r,pair_labels.index('Cacat B (pcs)')+1),db))
        expected_intensity = min(9,math.floor(max(da+1,db+1)/min(da+1,db+1)+.5))
        expected_preferred = a if da < db else b if db < da else 'Sama'
        automatic = formulas['Pairwise'].cell(r,pair_labels.index('Saaty intensity (1-9)')+1).data_type == 'f'
        auto_count += automatic
        mismatch_transforms += automatic and (intensity != expected_intensity or preferred != expected_preferred)
        filled += 1
    expected_pairs = {(c,tuple(sorted(pair))) for c in CRITERIA for pair in itertools.combinations(suppliers,2)}
    if pairs != expected_pairs:
        raise ValueError(f"Pairwise is incomplete: expected {len(expected_pairs)} unique comparisons, got {len(pairs)}.")
    check('Pairwise: quantities from Data', mismatch_counts,0)
    check('Pairwise: automatic rounded +1 ratio, capped at 9',mismatch_transforms,0)
    if mismatch_counts or mismatch_transforms:
        raise ValueError('Pairwise cached quantities or automatic comparisons disagree with Data and the documented +1/round/cap rule. Recalculate and save Excel; changed transformation rules need an explicit reader revision.')

    contributions = local.mul(ahp['weights'],axis=1)
    scores = contributions.sum(axis=1)
    ranks = scores.round(12).rank(method='min',ascending=False).astype(int)
    result = pd.DataFrame({'Supplier':suppliers,'Simulation score':scores.to_numpy(),
                           'Recorded adverse quantity':defects.sum(axis=1).to_numpy(), 'Simulation rank':ranks.to_numpy()})
    result['_sort']=result.Supplier.str.casefold()
    result=result.sort_values(['Simulation rank','_sort','Supplier']).drop(columns='_sort').reset_index(drop=True)
    result=result[['Simulation rank','Supplier','Simulation score','Recorded adverse quantity']]
    result['Status']=SIMULATION
    final,fr,fl = header_table(cached,'Hasil','Supplier',list(CRITERIA)+['Skor akhir','Peringkat'])
    final_names=[str(final.cell(fr+1+i,1).value).strip() for i in range(len(suppliers))]
    if len(set(final_names)) != len(suppliers) or set(final_names)!=set(suppliers):
        raise ValueError('Hasil supplier names do not match Rekap / supplier matrices.')
    lookup={name:fr+1+i for i,name in enumerate(final_names)}
    for criterion in CRITERIA:
        check(f'Hasil: {criterion} local priorities',[numeric(final,lookup[s],fl.index(criterion)+1) for s in suppliers],local[criterion])
    check('Hasil: weighted final scores',[numeric(final,lookup[s],fl.index('Skor akhir')+1) for s in suppliers],scores)
    check('Hasil: competition ranks (equal scores share rank)',[numeric(final,lookup[s],fl.index('Peringkat')+1) for s in suppliers],ranks)
    notes=[str(cell.value) for sheet in cached for row in sheet for cell in row if cell.data_type=='s' and cell.value is not None]
    previews={name:pd.DataFrame(list(cached[name].values)) for name in cached.sheetnames}
    return {'format':'supplier_pairwise','sheets':previews,'inventory':pd.DataFrame(inventory),
            'matrix':matrix,'ahp':ahp,'defects':defects,'processed':processed,
            'simulation':{'local':local,'contributions':contributions,'ranking':result},'audit':pd.DataFrame(audit),
            'supplier_matrices':supplier_matrices,'supplier_consistency':pd.DataFrame(consistency),
            'supplier_pairwise_rows':len(pairs),'supplier_pairwise_filled':filled,'automatic_pairwise_count':auto_count,
            'sha256':hashlib.sha256(blob).hexdigest(),
            'period':'Workbook snapshot: Data has no dates; reporting period cannot be verified from records',
            'period_evidence':str(cached['Petunjuk'].cell(1,1).value) if 'Petunjuk' in cached.sheetnames else 'No period documentation supplied',
            'method':'Column normalization followed by row average; lambda is mean((A @ w) / w), an estimate, not the Perron eigenvalue'}
