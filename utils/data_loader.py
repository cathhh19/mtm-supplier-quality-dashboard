"""Read immutable source bytes. No files are written by this module."""
from io import BytesIO, StringIO
from pathlib import Path
import csv
import pandas as pd
from charset_normalizer import from_bytes


def csv_text(blob, encoding="Auto"):
    if encoding != "Auto":
        return blob.decode(encoding)
    try:
        return blob.decode("utf-8-sig")
    except UnicodeDecodeError:
        match = from_bytes(blob).best()
        if match is None:
            raise ValueError("Could not detect CSV encoding. Select an encoding manually.")
        return str(match)


def sheet_names(blob, filename):
    if Path(filename).suffix.lower() == ".csv":
        return ["CSV"]
    with pd.ExcelFile(BytesIO(blob)) as book:
        return book.sheet_names


def read_data(blob, filename, sheet=None, header_row=1, delimiter="Auto", encoding="Auto"):
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xlsx", ".xls", ".csv"}:
        raise ValueError("Supported formats: .xlsx, .xls, .csv")
    if not blob:
        raise ValueError("The uploaded file is empty.")
    if suffix == ".csv":
        text = csv_text(blob, encoding)
        if delimiter == "Auto":
            try:
                delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
        frame = pd.read_csv(StringIO(text), sep=delimiter, header=header_row - 1,
                            dtype=object, skip_blank_lines=False, keep_default_na=False)
    else:
        frame = pd.read_excel(BytesIO(blob), sheet_name=sheet or 0,
                              header=header_row - 1, dtype=object, keep_default_na=False)
    frame.columns = [str(c) for c in frame.columns]
    if frame.empty:
        raise ValueError("No data records were found below the selected header row.")
    return frame


def suggest_header(blob, filename, sheet=None):
    """Choose the first of 15 rows with at least two recognized field names."""
    from utils.column_mapping import ALIASES, normalize
    if Path(filename).suffix.lower() == ".csv":
        return 1
    preview = pd.read_excel(BytesIO(blob), sheet_name=sheet or 0, header=None, nrows=15)
    aliases = {a for values in ALIASES.values() for a in values}
    for i, row in preview.iterrows():
        if sum(normalize(x) in aliases for x in row) >= 2:
            return int(i) + 1
    return 1
