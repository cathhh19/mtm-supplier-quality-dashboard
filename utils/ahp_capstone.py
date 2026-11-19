"""Criteria AHP plus max-normalized improvement index; higher means more review.

No supplier pairwise judgements or exposure-adjusted quality scores are inferred.
"""
import hashlib
import numpy as np
import pandas as pd
from utils.ahp import CRITERIA, SIMULATION, criteria_ahp, defect_matrix
from utils.ahp_new import header_table, numeric


def improvement_index(defects, weights):
    d = defects.loc[:, list(CRITERIA)].apply(pd.to_numeric, errors='coerce')
    w = weights.reindex(CRITERIA)
    if d.empty or d.index.has_duplicates or any(not str(s).strip() for s in d.index):
        raise ValueError('Unique named suppliers and nonempty quantities are required.')
    if not np.isfinite(d.to_numpy()).all() or (d < 0).any().any():
        raise ValueError('Recorded quantities must be complete, finite and nonnegative.')
    if not np.isfinite(w).all() or (w <= 0).any() or not np.isclose(w.sum(), 1):
        raise ValueError('Five positive criterion weights summing to one are required.')
    normalized = d.div(d.max().replace(0, np.nan)).fillna(0) * 100
    contributions = normalized.mul(w, axis=1)
    scores = contributions.sum(axis=1)
    # Match workbook SUMPRODUCT(ROUND(scores,6)>ROUND(score,6))+1.
    ranks = scores.round(6).rank(method='min', ascending=False).astype(int)
    ranking = pd.DataFrame({'Supplier': d.index, 'Improvement priority score': scores.to_numpy(),
                            'Recorded adverse quantity': d.sum(axis=1).to_numpy(),
                            'Review priority rank': ranks.to_numpy(),
                            'Largest weighted contributor': contributions.idxmax(axis=1).where(scores.gt(0), 'None').to_numpy()})
    ranking['_name'] = ranking.Supplier.str.casefold()
    ranking = ranking.sort_values(['Review priority rank', '_name', 'Supplier']).drop(columns='_name').reset_index(drop=True)
    return dict(normalized=normalized, contributions=contributions, ranking=ranking)


def active_qc_improvement(source, data, period):
    """Apply fixed reference weights/method to current records, never old scores.

    Missing supplier/category combinations follow the reference's recorded-zero
    convention, not an assertion of defect-free units or comparable exposure.
    """
    if source['ahp']['CR'] > .1:
        raise ValueError('Reference criteria matrix exceeds CR 0.10; scores are withheld.')
    defects = defect_matrix(data)
    return {**source, 'defects': defects,
            'simulation': improvement_index(defects, source['ahp']['weights']),
            'scope_label': 'Active QC data · ' + period,
            'reference_snapshot': False}


def read_capstone_ahp(formulas, cached, previews, inventory, blob):
    required = ['Ringkasan', 'Matriks_AHP', 'Bobot_Konsistensi', 'Data_Jan', 'Data_Feb',
                'Data_Mar', 'Data_Cacat', 'Normalisasi', 'Skor_Peringkat', 'Peringkat']
    missing = set(required) - set(cached.sheetnames)
    if missing:
        raise ValueError('Capstone AHP missing worksheets: ' + ', '.join(sorted(missing)))
    audit = []

    def check(label, stored, expected):
        matches = np.allclose(stored, expected, atol=1e-9, rtol=1e-8)
        audit.append({'Check': label, 'Result': 'Matches' if matches else 'Mismatch'})
        if not matches:
            raise ValueError(label + ': saved values disagree with independently computed inputs. Recalculate and save Excel.')

    sheet, row, headers = header_table(cached, 'Matriks_AHP', 'Kriteria', list(CRITERIA))
    labels = [sheet.cell(row+1+i, 1).value for i in range(5)]
    if labels != list(CRITERIA):
        raise ValueError('Matriks_AHP criterion rows must match the five named criterion columns.')
    a = np.array([[numeric(sheet, row+1+i, headers.index(c)+1) for c in CRITERIA] for i in range(5)])
    if (a < 1/9-1e-8).any() or (a > 9+1e-8).any():
        raise ValueError('Criteria comparisons must be within 1/9–9.')
    ahp = criteria_ahp(a)
    stats, sr, sh = header_table(cached, 'Bobot_Konsistensi', 'No', ['Kriteria', 'Bobot (Wj)'])
    if [stats.cell(sr+i+1, sh.index('Kriteria')+1).value for i in range(5)] != list(CRITERIA):
        raise ValueError('Stored weight criteria do not match Matriks_AHP.')
    check('Principal eigenvector weights', [numeric(stats, sr+i+1, sh.index('Bobot (Wj)')+1) for i in range(5)], ahp['weights'])
    # Find consistency metrics by their documented labels, not row positions.
    for metric, value in [('Nilai eigen maksimum', ahp['lambda_max']), ('Consistency Index', ahp['CI']), ('Random Index', ahp['RI']), ('Consistency Ratio', ahp['CR'])]:
        found = [r for r in range(1, stats.max_row+1) if str(stats.cell(r, 2).value).strip().startswith(metric)]
        if len(found) != 1:
            raise ValueError('Missing or ambiguous consistency metric: ' + metric)
        check('Consistency ' + metric, numeric(stats, found[0], 3), value)

    def quantities(name):
        ws, hr, hs = header_table(cached, name, 'No', ['Supplier', *CRITERIA])
        names, values, rows = [], [], []
        for r in range(hr+1, ws.max_row+1):
            if not isinstance(ws.cell(r, 1).value, (int, float)):
                if names:
                    break
                continue
            supplier = ws.cell(r, hs.index('Supplier')+1).value
            if not isinstance(supplier, str) or not supplier.strip():
                raise ValueError(f'{name}: missing supplier at row {r}.')
            names.append(supplier.strip()); rows.append(r)
            values.append([numeric(ws, r, hs.index(c)+1) for c in CRITERIA])
        if not names or len(set(names)) != len(names):
            raise ValueError(f'{name}: missing or duplicate supplier labels.')
        data = pd.DataFrame(values, index=names, columns=CRITERIA)
        if (data < 0).any().any():
            raise ValueError(f'{name}: negative quantities are invalid.')
        return data, ws, rows, hs

    defects, ws, rows, hs = quantities('Data_Cacat')
    monthly = {}
    for name in ['Data_Jan', 'Data_Feb', 'Data_Mar']:
        d, _, _, _ = quantities(name)
        if set(d.index) != set(defects.index):
            raise ValueError(name + ': supplier coverage differs from Data_Cacat.')
        monthly[name] = d.reindex(defects.index)
    check('Monthly quantities sum to Data_Cacat', defects, sum(monthly.values()))
    check('Data_Cacat supplier totals', [numeric(ws,r,hs.index('Total')+1) for r in rows], defects.sum(axis=1))
    result = improvement_index(defects, ahp['weights'])
    for name, expected in [('Normalisasi', result['normalized']), ('Skor_Peringkat', result['contributions'])]:
        stored, _, _, _ = quantities(name)
        if set(stored.index) != set(defects.index):
            raise ValueError(name + ': supplier labels differ from Data_Cacat.')
        check(name + ' all criterion values', stored.reindex(defects.index), expected)
    _, scores_ws, score_rows, score_headers = quantities('Skor_Peringkat')
    scores = result['contributions'].sum(axis=1)
    check('Weighted improvement scores', [numeric(scores_ws,r,score_headers.index('Skor Prioritas (Pi)')+1) for r in score_rows], scores)
    check('Competition ranks (six decimal comparison)', [numeric(scores_ws,r,score_headers.index('Peringkat')+1) for r in score_rows], scores.round(6).rank(method='min',ascending=False))
    final, fr, fh = header_table(cached, 'Peringkat', 'Urutan', ['Supplier','Skor prioritas','Peringkat'])
    lookup = result['ranking'].set_index('Supplier')
    final_names = [final.cell(fr+i+1, fh.index('Supplier')+1).value for i in range(len(defects))]
    if len(set(final_names)) != len(defects) or set(final_names) != set(defects.index):
        raise ValueError('Peringkat: supplier labels differ from Data_Cacat.')
    check('Displayed final scores', [numeric(final,fr+i+1,fh.index('Skor prioritas')+1) for i in range(len(defects))], lookup.loc[final_names,'Improvement priority score'])
    check('Displayed final ranks', [numeric(final,fr+i+1,fh.index('Peringkat')+1) for i in range(len(defects))], lookup.loc[final_names,'Review priority rank'])
    previews = {name: pd.DataFrame(list(cached[name].values)) for name in cached.sheetnames}
    return dict(format='capstone_improvement', matrix=pd.DataFrame(a,index=CRITERIA,columns=CRITERIA), ahp=ahp,
                defects=defects, simulation=result, monthly=monthly, audit=pd.DataFrame(audit),
                sheets=previews, inventory=inventory, sha256=hashlib.sha256(blob).hexdigest(),
                period_evidence=str(cached['Ringkasan'].cell(2,1).value))
