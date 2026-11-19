from pathlib import Path
import hashlib
import pandas as pd
import streamlit as st
from utils.data_loader import read_data, sheet_names, suggest_header
from utils.column_mapping import FIELDS, suggest_mapping, mapping_errors
from utils.data_cleaning import prepare_data
from utils.validation import quality_summary, qc_source_errors
from utils.calculations import filter_data
from utils import views
from utils.research_period import reporting_dates
from utils.processed_qc import is_processed_qc, processed_mapping, processed_flags
from utils.theme import apply_theme, welcome

st.set_page_config(page_title="MTM Supplier Quality Dashboard", page_icon="📊", layout="wide")
apply_theme()


@st.cache_data(show_spinner=False, max_entries=5, ttl=3600)
def cached_read(blob, name, sheet, header, delimiter, encoding):
    return read_data(blob, name, sheet, header, delimiter, encoding)


def data_context():
    with st.sidebar:
        st.markdown("## ◈ MTM\nSupplier Quality Intelligence")
        st.markdown("**Data source**")
        st.caption("Upload your processed QC workbook to begin. Any reporting year is supported.")
        upload = st.file_uploader("Upload QC data", type=["xlsx", "xls", "csv"])
        # Discover supported local files; never depend on a fixed source filename.
        local = sorted(p for folder in (Path.cwd(), Path.cwd() / "data") if folder.exists()
                       for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".xlsx", ".xls", ".csv"}
                       and not p.name.startswith("~$"))
        if upload:
            blob, name = upload.getvalue(), upload.name
        elif local:
            chosen = st.selectbox("Local dataset", local, index=None, placeholder="Select a QC source from any period", format_func=lambda p: p.name)
            if chosen is None:
                st.info("Upload a QC file or select a local dataset. Only the selected source is analyzed; files are never merged automatically.")
                return None
            blob, name = chosen.read_bytes(), chosen.name
        else:
            st.info("Upload an Excel or CSV file, or place one in the project/data folder.")
            return None
        file_id = hashlib.sha256(blob).hexdigest()[:16]
        try:
            sheets = sheet_names(blob, name)
            sheet = st.selectbox("Worksheet", sheets, index=sheets.index('Data Bersih') if 'Data Bersih' in sheets else 0, key=f"sheet_{file_id}")
            suggested = suggest_header(blob, name, sheet)
            header = int(st.number_input("Header row (1-based)", 1, 1000, suggested, key=f"header_{file_id}_{sheet}"))
            delimiter, encoding = "Auto", "Auto"
            if name.lower().endswith(".csv"):
                delimiter = st.selectbox("CSV delimiter", ["Auto", ",", ";", "\t", "|"], format_func=lambda x: "Tab" if x == "\t" else x)
                encoding = st.selectbox("CSV encoding", ["Auto", "utf-8-sig", "utf-16", "cp1252", "big5", "gb18030"])
            raw = cached_read(blob, name, sheet, header, delimiter, encoding)
        except Exception as exc:
            st.error(f"Cannot import this source: {exc}. Check the worksheet, header row, delimiter or encoding.")
            return None
    scope = f"{file_id}_{sheet}_{header}_{delimiter}_{encoding}"
    suggestions = suggest_mapping(raw.columns)
    processed_source = is_processed_qc(raw.columns)
    if processed_source:
        suggestions.update(processed_mapping(raw.columns))
    elif 'Data Bersih' in sheets and sheet != 'Data Bersih':
        st.error('Select the Data Bersih worksheet for processed QC workbooks. Summary and validation worksheets are not record-level QC sources.')
        return None
    with st.expander("Data management · preview, mapping & validation", expanded=False):
        if processed_source:
            st.caption('Processed QC workbook detected · using clean records from Data Bersih. Summary worksheets are not counted again.')
        st.caption(f"{name} / {sheet} · {len(raw):,} rows × {len(raw.columns)} columns · header row {header}. "
                   "Pre-header title rows are not records. Source files are never changed.")
        st.dataframe(raw.head(30), hide_index=True, width="stretch")
        st.markdown("**Map source fields** · suggestions require review")
        st.caption("Required template fields: Date of opening, Responsible unit, Adverse number, Bad reasons. "
                   "Explicitly map equivalent headers below. Product and inspection/accepted/rejected quantities are optional. "
                   "Required values must be complete and valid; optional metrics remain unavailable when their fields are absent.")
        mapping = {}
        columns = st.columns(2)
        unmapped = "(Not mapped)"
        while unmapped in raw.columns:
            unmapped = "_" + unmapped
        options = [unmapped] + list(raw.columns)
        for i, (field, label) in enumerate(FIELDS.items()):
            selected = columns[i % 2].selectbox(label, options,
                 index=options.index(suggestions[field] or unmapped), key=f"map_{scope}_{field}")
            mapping[field] = None if selected == unmapped else selected
        errors = mapping_errors(mapping, raw.columns)
        for error in errors:
            st.error(error)
        if errors:
            return None
        st.dataframe(pd.DataFrame([{"Internal field": k, "Original column": v or "Unmapped"} for k, v in mapping.items()]), hide_index=True)
        dayfirst = st.checkbox("Parse ambiguous text dates as day/month/year", key=f"dayfirst_{scope}")
        st.caption("ISO dates remain ISO; Excel numeric dates use the 1899-12-30 origin. Verify the parsed range below.")
        # Verification keys include the mapping: a changed mapping cannot inherit an old confirmation.
        mapping_id = hashlib.sha256(str(mapping).encode()).hexdigest()[:12]
        verification = f"{scope}_{mapping_id}"
        supplier_ok = st.checkbox("I confirm the mapped supplier field identifies suppliers", key=f"supplier_ok_{verification}", disabled=not mapping["supplier"])
        adverse_ok = st.checkbox("I confirm the mapped adverse field is an additive recorded quantity", key=f"adverse_ok_{verification}", disabled=not mapping["adverse"])
        inspection_ok = st.checkbox("I confirm inspected quantity is additive and is not repeated across defect-category rows", key=f"inspection_ok_{verification}", disabled=not mapping["inspection"])
        defect_ok = st.checkbox("I confirm adverse counts unique defective units in the same inspected population and units", key=f"defect_ok_{verification}", disabled=not (mapping["adverse"] and mapping["inspection"]))
        rates_ok = st.checkbox("I confirm accepted/rejected quantities match the same inspected population and units", key=f"rates_ok_{verification}", disabled=not mapping["inspection"])
        processed = prepare_data(raw, mapping, dayfirst, header)
        summary, warnings = quality_summary(raw, processed, mapping)
        st.markdown("**Data quality**")
        st.dataframe(summary, hide_index=True, width="stretch")
        for warning in warnings:
            st.caption(warning)
        dates = processed.date.dropna()
        st.write(f"Parsed date coverage: {dates.min().date()} to {dates.max().date()}" if not dates.empty else "No valid dates; dated analyses are unavailable.")
        invalid = processed[processed.issues.ne("")]
        st.write(f"{len(invalid):,} records have validation notes; all source records are retained.")
        if not invalid.empty:
            st.dataframe(invalid[["source_row", "issues"]], hide_index=True, width="stretch")
        st.caption("Whitespace is trimmed from mapped categories. Missing suppliers stay missing and do not count as suppliers; "
                   "missing products/categories are displayed as (Missing). Invalid/negative quantities are excluded only from their own sums. "
                   "Quantity totals may therefore be partial; inspect diagnostics. Rates require complete quantities. "
                   "Case variants are flagged, never silently merged. Duplicate-looking records are retained.")
        st.markdown("**Processed data · before filters**")
        st.dataframe(processed.head(30), hide_index=True, width="stretch")
        views.download(processed, "processed_dataset.csv", "Download complete processed dataset")
        st.caption("Processed values include mapped fields before business verification; diagnostic values are not approved metrics.")
    source_errors = qc_source_errors(raw, processed, mapping)
    if processed_source:
        flag_errors, flag_notes = processed_flags(raw)
        source_errors.extend(flag_errors)
    if source_errors:
        for error in source_errors:
            st.error(error)
        return None
    try:
        source_dates = reporting_dates(processed)
    except ValueError as exc:
        st.error(f"QC source {name} / {sheet}: {exc}")
        return None
    analytical = processed.copy()
    if not (supplier_ok and mapping["supplier"]):
        analytical["supplier"] = pd.Series(pd.NA, index=analytical.index, dtype="string")
    if not (adverse_ok and mapping["adverse"]):
        analytical["adverse"] = float("nan")
    with st.sidebar:
        st.divider()
        st.markdown("**Shared filters**")
        dates = source_dates
        period = None
        include_undated = False
        if not dates.empty:
            period = st.date_input("Reporting period", value=(dates.min().date(), dates.max().date()),
                                   min_value=dates.min().date(), max_value=dates.max().date(), key=f"period_{scope}_{dayfirst}")
            if len(period) != 2:
                st.info("Select both the start and end date.")
                return None
        selections = {}
        for field in ("supplier", "product", "category"):
            if mapping[field] and (field != "supplier" or supplier_ok):
                options_ = sorted(analytical[field].fillna("(Missing)").unique())
                selections[field] = st.multiselect(FIELDS[field], options_, key=f"filter_{verification}_{field}")
        st.caption("No selections means all values. All four pages use this scope.")
    filtered = filter_data(analytical, period, selections, include_undated)
    period_label = f"{period[0]:%d %b %Y} – {period[1]:%d %b %Y}" if period else "All records · no valid reporting dates"
    st.caption(f"ACTIVE DATASET  ·  {name} / {sheet}    |    {period_label}" + (" · includes undated records in totals" if include_undated else ""))
    if filtered.empty:
        st.warning("No records match the active filters. Change the shared filters to continue.")
    excluded = len(processed) - len(filtered)
    st.caption(f"{len(filtered):,} of {len(processed):,} source records in scope; {excluded:,} outside the selected scope.")
    if filtered.adverse.isna().any() and adverse_ok:
        st.warning(f"{filtered.adverse.isna().sum():,} records in scope have unavailable adverse quantities. Sums use valid values only and may be partial.")
    with st.expander("Metric definitions & scope export"):
        st.caption(f"Detected source coverage: {source_dates.min():%d %b %Y} – {source_dates.max():%d %b %Y} "
                   f"· {source_dates.dt.to_period('M').nunique()} month(s) with records. Source dates are preserved.")
        if processed_source:
            for note in flag_notes:
                st.warning(note)
        st.write("Total suppliers = distinct nonblank confirmed supplier names. Total adverse = sum of valid nonnegative confirmed recorded adverse quantities. "
                 "Monthly adverse = same quantity grouped by parsed record month. Category share = category adverse / scope adverse × 100. "
                 "Pareto cumulative % = cumulative sorted category adverse / scope adverse × 100. "
                 "Defect, reject and acceptance rates = verified numerator / verified inspected quantity × 100, using the same complete filtered population. "
                 "Zero denominators, incomplete quantities and invalid quantity relationships yield unavailable rates.")
        st.caption("Record date may be a case-opening date rather than an inspection date. Confirm with the data owner. "
                   "Debit and repair flags do not establish accepted or rejected quantities.")
        views.download(filtered, "filtered_processed_records.csv", "Download filtered analytical records")
    return dict(data=filtered, raw=raw, reporting_period=period_label,
                supplier_ok=bool(supplier_ok and mapping["supplier"]),
                adverse_ok=bool(adverse_ok and mapping["adverse"]), inspection_ok=bool(inspection_ok and mapping["inspection"]),
                defect_ok=bool(defect_ok and adverse_ok and inspection_ok), rates_ok=bool(rates_ok and inspection_ok))


with st.container(key='brand_header'):
    st.caption('MTM · QUALITY CONTROL')
    st.title("MTM Supplier Quality Dashboard")
    st.markdown("Recorded quality insights. Clearer supplier decisions.")
    st.caption("Your uploaded QC data · Dynamic reporting periods · AHP decision support")
ctx = data_context()
def qc_page(view):
    if ctx is None:
        welcome()
        st.info("Choose a valid data source and resolve any template/value errors in Data management. QC accepts any reporting year. The AHP workbook can still be inspected separately on Supplier Evaluation.")
    else:
        view(ctx)

def evaluation_page():
    views.evaluation(ctx if ctx is not None else dict(qc_missing=True, supplier_ok=False, adverse_ok=False))

pages = [st.Page(lambda: qc_page(views.overview), title="Overview", icon="📊", default=True, url_path="overview"),
         st.Page(lambda: qc_page(views.performance), title="Supplier Performance", icon="🏭", url_path="suppliers"),
         st.Page(lambda: qc_page(views.defects), title="Defect Analysis", icon="🔎", url_path="defects"),
         st.Page(evaluation_page, title="Supplier Evaluation", icon="📋", url_path="evaluation")]
page = st.navigation(pages, position='top')
page.run()
