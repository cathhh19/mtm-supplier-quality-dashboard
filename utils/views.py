"""Four analytical pages share one prepared and filtered application context."""
import pandas as pd
import streamlit as st
from utils import calculations as calc
from utils import charts
from utils.ahp_view import render_ahp
from utils.recommendations import render_recommendations


def download(frame, name, label=None):
    st.download_button(label or "Download table as CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name=name, mime="text/csv", key=f"download_{name}")


def details(ctx, data=None, suffix="scope"):
    data = ctx["data"] if data is None else data
    # Position is retained through filtering, so original values remain traceable.
    raw = ctx["raw"].loc[data.index].copy()
    trace_column = "_source_row"
    while trace_column in raw.columns:
        trace_column = "_" + trace_column
    raw.insert(0, trace_column, data.source_row)
    search = st.text_input("Search original records", key=f"search_{suffix}",
                           placeholder="Search supplier, part, remark or any source field…")
    if search:
        mask = raw.astype("string").apply(lambda s: s.str.contains(search, case=False, regex=False, na=False)).any(axis=1)
        raw = raw.loc[mask]
    st.caption(f"{len(raw):,} original records · click a column header to sort. Search also applies to this download.")
    st.dataframe(raw, hide_index=True, width="stretch")
    download(raw, f"filtered_records_{suffix}.csv", "Download these original records")


def supplier_notice(ctx):
    if not ctx["supplier_ok"]:
        st.info("Confirm the supplier mapping in Data management to enable supplier analysis.")
        return True
    return False


def kpis(ctx, data=None):
    data = ctx["data"] if data is None else data
    columns = st.columns(4)
    total = calc.total_adverse(data)
    columns[0].metric("Total suppliers", f"{calc.supplier_count(data):,}" if ctx["supplier_ok"] else "Confirm mapping")
    quantity = (f"{total:,.2f}" if pd.notna(total) else "No records" if data.empty else "Check data")
    columns[1].metric("Total recorded adverse", quantity if ctx['adverse_ok'] else "Confirm mapping")
    columns[2].metric("QC records", f"{len(data):,}")
    columns[3].metric("Defect categories", f"{data.category.nunique(dropna=True):,}")
    st.caption("All cards follow the active filters. QC records count source rows, not inspections or inspected units. "
               "Defect categories count distinct recorded category labels; adverse is the recorded quantity, not a defect rate.")


def overview(ctx):
    st.subheader("Overview")
    st.caption("A clear view of recorded quality observations.")
    data = ctx["data"]
    kpis(ctx)
    left, right = st.columns([1.4, 1])
    with left:
        charts.trend(calc.monthly(data))
    with right:
        charts.bar(calc.grouped(data, "category"), "category", "Top 5 defect categories", top=5)
    left, right = st.columns(2)
    with left:
        if not supplier_notice(ctx):
            charts.bar(calc.grouped(data[data.supplier.notna()], "supplier"), "supplier",
                       "Top 5 suppliers by recorded adverse", top=5)
    with right:
        charts.distribution(calc.category_shares(data))
    if not ctx["adverse_ok"]:
        st.info("Review and confirm the adverse quantity field in Data management to calculate quantity-based metrics.")


def performance(ctx):
    st.subheader("Supplier Performance")
    if supplier_notice(ctx):
        return
    data = ctx["data"]
    st.info("Recorded adverse quantities reflect exposure as well as quality. These comparisons do not establish which supplier has poorer quality.")
    table = calc.supplier_table(data)
    metric = st.selectbox("Compare suppliers by", ["Recorded adverse quantity", "QC records"])
    charts.bar(table, "Supplier", "Supplier comparison", metric=metric)
    charts.trend(calc.monthly(data[data.supplier.notna()], "supplier"), "Monthly adverse by supplier", "supplier")
    st.markdown("**Supplier ranking · highest recorded adverse quantity first**")
    st.dataframe(table, hide_index=True, width="stretch")
    download(table, "supplier_ranking.csv")
    if ctx["rates_ok"]:
        rates = []
        for supplier, group in data[data.supplier.notna()].groupby("supplier"):
            rates.append({"Supplier": supplier,
                          "Reject rate (%)": calc.verified_rate(group, "rejected", True),
                          "Acceptance rate (%)": calc.verified_rate(group, "accepted", True)})
        st.dataframe(pd.DataFrame(rates), hide_index=True)
        st.caption("Rates are blank where complete valid matched quantities are unavailable.")
    breakdown = (data[data.supplier.notna()].assign(category=data.category.fillna("(Missing)"))
                 .groupby(["supplier", "category"]).adverse.sum(min_count=1).dropna().reset_index())
    charts.bar(breakdown, "supplier", "Supplier category profile", color="category")


def defects(ctx):
    st.subheader("Defect Analysis")
    data = ctx["data"]
    table = calc.category_shares(data)
    left, right = st.columns(2)
    with left:
        charts.distribution(table)
    with right:
        charts.pareto(table)
    st.caption("Shares and Pareto measure recorded adverse quantity, which is not assumed to count unique defective units. Patterns do not establish root causes.")
    st.dataframe(table, hide_index=True, width="stretch")
    download(table, "pareto_results.csv")
    if not supplier_notice(ctx):
        split = st.checkbox("Break down suppliers by defect category", value=True)
        if split:
            table_ = (data[data.supplier.notna()].assign(category=data.category.fillna("(Missing)"))
                      .groupby(["supplier", "category"]).adverse.sum(min_count=1).dropna().reset_index())
        else:
            table_ = calc.grouped(data[data.supplier.notna()], "supplier")
        charts.bar(table_, "supplier", "Adverse by supplier", color="category" if split else None)
    charts.bar(calc.grouped(data, "product"), "product", "Top 10 products / parts by recorded adverse", top=10)
    st.markdown("**Drill-down detail**")
    details(ctx, suffix="defect_analysis")


def evaluation_rankings(ctx):
    st.subheader("Supplier Ranking & Recommendations")
    st.caption("Descriptive ranking by recorded adverse quantity, not a verified defect rate or overall supplier quality score. "
               "Inspection exposure is unknown. A lower recorded total does not establish better quality.")
    data = ctx["data"]
    if not ctx["adverse_ok"]:
        st.info("Confirm the adverse quantity mapping in Data management to enable rankings and quantity observations.")
        return
    period = ctx.get("reporting_period")
    lowest = calc.supplier_ranking(data, ascending=True, reporting_period=period)
    highest = calc.supplier_ranking(data, ascending=False, reporting_period=period)
    if lowest.empty:
        st.info("No suppliers have valid dated adverse records in the active filters. Rankings and lowest/highest observations are unavailable.")
        return
    all_ranked = calc.supplier_ranking(data, limit=len(data), reporting_period=period)
    all_ranked, cuts = calc.adverse_statuses(all_ranked)
    statuses = all_ranked.set_index("Supplier")["Recorded adverse status"]
    for table in (lowest, highest):
        table["Recorded adverse status"] = table.Supplier.map(statuses)
    st.markdown("**Supplier Ranking · lowest recorded adverse first**")
    display = all_ranked.copy()
    display["Ranking explanation"] = "Ascending valid recorded adverse quantity; alphabetical supplier tie-break. Not an inspection-adjusted quality score."
    st.dataframe(display, hide_index=True, width="stretch")
    download(display, "supplier_complete_adverse_ranking.csv")
    st.caption(f"Descriptive status rule within this filtered supplier population: Low ≤ 25th percentile ({cuts.loc[.25]:,.2f}); "
               f"Moderate ≤ median ({cuts.loc[.5]:,.2f}); High ≤ 75th percentile ({cuts.loc[.75]:,.2f}); Highest > 75th percentile. "
               "Tied quantities receive the same status; if all totals are equal, every supplier is labelled Same Recorded Adverse. "
               "These labels describe relative quantities, not official MTM ratings, and recalculate with the filters.")
    st.caption("Only records with a nonblank supplier, valid date and nonnegative finite adverse quantity are ranked. "
               "Months count distinct months containing these eligible records, not inspected months. "
               "Undated and invalid-quantity records are excluded; totals may be partial. "
               "Ties are ordered alphabetically by supplier name, ignoring case first, then exact spelling. "
               "All equally frequent defect categories are shown; frequency counts eligible QC records.")
    if all_ranked["Months with records"].nunique() > 1:
        st.warning("Supplier records cover different numbers of months in this scope. Compare the coverage column before reviewing adverse totals.")
    if all_ranked["Excluded quantity records"].sum():
        st.warning("Some ranked suppliers have excluded quantities. Their totals are partial; see Excluded quantity records and the data-quality notes.")
    for table, title, suffix in [(lowest, "A. Top 5 — Lowest Recorded Adverse", "lowest"),
                                 (highest, "B. Top 5 — Highest Recorded Adverse · Suppliers Requiring Further Review", "highest")]:
        st.markdown(f"**{title}**")
        st.dataframe(table, hide_index=True, width="stretch")
        download(table, f"supplier_{suffix}_adverse.csv")
        with st.expander(f"Monthly trends · {title}"):
            eligible = calc.ranking_records(data)
            charts.trend(calc.monthly(eligible[eligible.supplier.isin(table.Supplier)], "supplier"),
                         f"Monthly recorded adverse · {suffix} ranked suppliers", "supplier")
    st.markdown("**Data-Based Observations · active filtered scope**")
    low, high = lowest.iloc[0], highest.iloc[0]
    for row, label in [(low, "Lowest"), (high, "Highest")]:
        tied = all_ranked[all_ranked["Recorded adverse quantity"].eq(row["Recorded adverse quantity"])]
        names = ", ".join(tied.Supplier)
        st.write(f"{label} recorded adverse quantity: {names} — {row['Recorded adverse quantity']:,.2f} "
                 f"during {row['Reporting period']}." + (" These suppliers are tied." if len(tied) > 1 else ""))
    st.caption("Recommendations for Further Review: check missing records, differences in reporting coverage and inspection exposure "
               "before interpreting these comparisons. These observations do not recommend approving, rejecting or replacing suppliers.")


def evaluation(ctx):
    st.subheader("Supplier Evaluation")
    st.caption("Descriptive review · human decision support")
    ahp_source = render_ahp(ctx)
    if ctx.get('qc_missing'):
        st.info('A valid QC source has not been supplied or validated. Descriptive supplier rankings remain unavailable. Upload a QC file from any reporting period; the independent AHP snapshot above is kept separate.')
        render_recommendations(ctx, ahp_source)
        return
    if supplier_notice(ctx):
        render_recommendations(ctx, ahp_source)
        return
    data = ctx["data"]
    evaluation_rankings(ctx)
    st.markdown("**Individual supplier review**")
    names = sorted(data.supplier.dropna().unique())
    if not names:
        st.info("No valid suppliers match these filters.")
        return
    supplier = st.selectbox("Supplier to review", names)
    selected = data[data.supplier.eq(supplier)]
    st.markdown("**Data-Based Observations · selected supplier**")
    eligible = calc.ranking_records(selected)
    st.caption("Active reporting period: " + ctx.get("reporting_period", "Current filtered scope"))
    st.write(f"Months with valid dated adverse records: {eligible.date.dt.to_period('M').nunique()}.")
    if eligible.empty:
        st.info("No valid dated adverse records are available for this supplier; category and monthly observations are unavailable.")
    else:
        st.write("Most frequently recorded defect category (eligible QC records): " + calc.frequent_categories(eligible) + ".")
        change = calc.monthly_observation(selected)
        if not change["available"]:
            st.info(change["reason"])
        else:
            movement = "was unchanged" if change["direction"] == "unchanged" else change["direction"]
            st.write(f"Recorded adverse quantity {movement} from {change['first_total']:,.2f} in "
                     f"{change['first_month']:%b %Y} to {change['last_total']:,.2f} in {change['last_month']:%b %Y}.")
            st.caption("This compares the first and last recorded monthly totals; intervening months can vary. "
                       "Missing months are not assumed to have zero adverse quantities. Partial first/last reporting months can affect comparisons.")
    kpis(ctx, selected)
    charts.trend(calc.monthly(selected), f"Monthly recorded adverse · {supplier}")
    charts.bar(calc.grouped(selected, "category"), "category", "Supplier defect-category profile")
    st.write("Related products / parts: " + (", ".join(sorted(selected['product'].dropna().unique())) or "Unavailable"))
    total = calc.total_adverse(selected)
    quantity = f"{total:,.2f} recorded adverse quantity" if pd.notna(total) else "an unverified adverse quantity"
    st.write(f"{supplier} has {len(selected):,} QC source records and {quantity} in the selected scope. "
             "Review exposure, inspection volumes and source definitions before drawing quality conclusions.")
    st.info("Formal evaluation is unavailable for these QC records: supplier scores and the original approved evaluation document were not supplied. "
            "No classifications or automatic supplier decisions are generated.")
    details(ctx, selected, "supplier_review")
    render_recommendations(ctx, ahp_source)
