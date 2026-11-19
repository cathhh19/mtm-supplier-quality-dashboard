"""Explicit contract for the output of pengolahan_qc_mtm.py; no guessed aliases."""
CORE = {'date', 'supplier', 'defect', 'adverse'}


def is_processed_qc(columns):
    names = set(columns)
    return CORE.issubset(names) or {'source_sheet', 'source_excel_row'}.issubset(names)


def processed_mapping(columns):
    names = set(columns)
    mapping = {key: key if key in names else None for key in ('date', 'supplier', 'adverse')}
    mapping['category'] = 'defect' if 'defect' in names else None
    mapping['product'] = 'part_number' if 'part_number' in names else 'product' if 'product' in names else None
    return mapping


def processed_flags(raw):
    errors, notes = [], []
    if 'valid_for_adverse_summary' in raw:
        values = raw['valid_for_adverse_summary'].astype('string').str.strip().str.casefold()
        invalid = ~values.isin(['true', '1'])
        if invalid.any():
            errors.append(f"Data Bersih: {int(invalid.sum())} records are not marked valid in valid_for_adverse_summary. "
                          'Review validation_note, correct the raw source and process it again. Records are not silently discarded.')
    if 'possible_duplicate' in raw:
        count = raw['possible_duplicate'].astype('string').str.strip().str.casefold().isin(['true', '1']).sum()
        if count:
            notes.append(f'{count} records are flagged as possible duplicates by QC processing. They are retained for review and are not automatically deleted.')
    return errors, notes
