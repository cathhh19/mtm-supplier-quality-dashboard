"""Suggestions are lexical hints, never verification of business meaning."""
import re

FIELDS = {
    "date": "Inspection / record date",
    "supplier": "Supplier",
    "product": "Product / part number",
    "adverse": "Recorded adverse quantity",
    "category": "Defect category",
    "inspection": "Inspected quantity",
    "accepted": "Accepted quantity",
    "rejected": "Rejected quantity",
}
# Minimum descriptive QC template; denominators and product identifiers are optional.
QC_REQUIRED = {
    "date": "Date of opening",
    "supplier": "Responsible unit",
    "adverse": "Adverse number",
    "category": "Bad reasons",
}
ALIASES = {
    "date": ["inspection date", "date", "date of opening", "tanggal"],
    "supplier": ["supplier", "supplier name", "vendor", "responsible unit"],
    "product": ["part no", "part number", "product", "product name", "material"],
    "adverse": ["adverse quantity", "adverse number", "defect quantity", "qty adverse"],
    "category": ["defect category", "bad reasons", "bad reason", "defect type"],
    "inspection": ["inspection quantity", "inspected quantity", "inspection qty"],
    "accepted": ["accepted quantity", "accepted qty"],
    "rejected": ["rejected quantity", "rejected qty"],
}


def normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def suggest_mapping(columns):
    normalized = {normalize(c): c for c in columns}
    return {field: next((normalized[a] for a in names if a in normalized), None)
            for field, names in ALIASES.items()}


def mapping_errors(mapping, columns):
    chosen = [v for v in mapping.values() if v is not None]
    errors = []
    if len(set(chosen)) != len(chosen):
        errors.append("Map each source column to only one analytical field.")
    if any(v not in columns for v in chosen):
        errors.append("A mapped column is missing from the selected source.")
    return errors
