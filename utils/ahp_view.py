"""A separate simulation section within Supplier Evaluation, not a new page."""
import os
from pathlib import Path
import pandas as pd
import streamlit as st
from utils.ahp import SIMULATION, read_ahp_workbook, defect_matrix, inverse_simulation


@st.cache_data(show_spinner=False, max_entries=3, ttl=3600)
def cached_workbook(blob, schema_version=3):
    return read_ahp_workbook(blob)


def simulation_download(frame, filename, index=False):
    export = frame.copy()
    export["Status"] = SIMULATION
    st.download_button("Download simulation results as CSV", export.to_csv(index=index).encode("utf-8-sig"),
                       file_name=filename, mime="text/csv", key=f"ahp_{filename}")


def render_ahp(ctx):
    with st.expander("AHP Simulation · criteria weights & supplier simulation", expanded=False):
        st.warning(SIMULATION)
        st.caption("Reference-driven calculations with independent verification. The detected workbook format determines the method; all supplier results remain simulation.")
        upload = st.file_uploader("Upload AHP simulation workbook (independent of QC upload)", type=["xlsx"], key="ahp_upload")
        preferred = Path(__file__).resolve().parents[1] / 'AHP_FIX_CAPSTONE (2).xlsx'
        configured = st.text_input("AHP workbook path (relative to project folder or server-accessible path)",
                                   value=os.environ.get("MTM_AHP_WORKBOOK", preferred.name if preferred.is_file() else "AHP_Supplier_Defect_2022_FIX.xlsx" if
                                       (Path(__file__).resolve().parents[1] / "AHP_Supplier_Defect_2022_FIX.xlsx").is_file()
                                       else "hasil_ahp_supplier_simulasi.xlsx"), key="ahp_path")
        try:
            if upload is not None:
                blob, name = upload.getvalue(), upload.name
            else:
                path = Path(configured).expanduser()
                if not path.is_absolute():
                    path = Path(__file__).resolve().parents[1] / path
                if not configured.strip() or not path.is_file():
                    st.info("AHP workbook not found at the configured path. Place a copy in data/, set its relative path above, "
                            "or upload it here. No replacement data or scores are generated.")
                    return
                blob, name = path.read_bytes(), path.name
            source = cached_workbook(blob)
        except Exception as exc:
            st.error(f"Cannot use this AHP source: {exc}")
            return
        st.caption(f"AHP source: {name} · SHA-256: {source['sha256'][:16]}… · all worksheets read; original file unchanged.")
        if source.get('format') == 'capstone_improvement':
            return render_capstone(source, ctx)
        if source.get('format') == 'supplier_pairwise':
            render_new_format(source)
            return
        st.markdown("**Simulation criteria pairwise matrix**")
        st.dataframe(source["matrix"], width="stretch")
        weights = source["ahp"]["weights"]
        st.markdown("**Simulation criteria weights · principal right eigenvector**")
        st.dataframe(weights.rename_axis("Criterion").reset_index(), hide_index=True, width="stretch")
        simulation_download(weights.to_frame(), "simulation_criteria_weights.csv", index=True)
        ahp = source["ahp"]
        st.markdown("**Criteria consistency · simulation**")
        st.dataframe(pd.DataFrame({"Metric": ["Lambda maximum", "CI", "RI (n = 5)", "CR"],
                                   "Value": [ahp['lambda_max'], ahp['CI'], ahp['RI'], ahp['CR']]}), hide_index=True)
        st.caption("Aw = λmax w; CI = (λmax − 5) / 4; RI = 1.12; CR = CI / RI. "
                   "Values below 1e-12 for CI are treated as numerical roundoff. CR ≤ 0.10 is the simulation's consistency check, not an MTM quality threshold. "
                   "The source matrix was generated from assumed weights, so near-zero CR does not validate expert judgement.")
        st.caption("Method reference: [Saaty, Decision making with the analytic hierarchy process (2008)]"
                   "(https://doi.org/10.1504/IJSSCI.2008.017590).")
        st.info(f"Supplier pairwise judgements: {source['supplier_pairwise_filled']:,} filled intensity cells / "
                f"{source['supplier_pairwise_rows']:,} template rows. "
                "Standard alternative-pairwise AHP is unavailable here: complete reciprocal supplier judgements for each criterion are missing. "
                "This feature does not convert adverse counts into pairwise judgements or calculate an alternative-matrix CR.")
        st.markdown("**Workbook verification**")
        st.dataframe(source["audit"], hide_index=True, width="stretch")
        if source["audit"].Result.ne("Matches").any():
            st.warning("Some stored results are missing or disagree with Python. Inspect the checks above. "
                       "Displayed scores are recomputed from Raw Data and Criteria Pairwise, never copied from discrepant stored results.")
        st.caption("Stored controls use absolute tolerance 1e-10 and relative tolerance 1e-8. Original Excel formulas are not executed.")
        with st.expander("Worksheet inventory & source preview"):
            st.dataframe(source["inventory"], hide_index=True, width="stretch")
            sheet = st.selectbox("AHP worksheet preview", list(source["sheets"]), key="ahp_preview")
            st.dataframe(source["sheets"][sheet].head(20), hide_index=True, width="stretch")
            if source["inventory"]["Excel formula cells"].sum():
                st.warning("This source includes formulas. Only saved cached values were read; missing cached inputs prevent calculation. "
                           "Python verifies the mathematical outputs, not Excel formula execution.")
            else:
                st.caption("No Excel formula cells: this workbook stores precomputed values. Verification independently recomputes them in Python.")
        if ahp['CR'] > .10:
            st.warning("Criteria matrix exceeds CR 0.10. Supplier simulation scores are withheld; review the source comparisons.")
            return
        mode = st.radio("Simulation data scope", ["Workbook snapshot", "Active QC filters"], key="ahp_scope", horizontal=True)
        if mode == "Workbook snapshot":
            defects, result = source["defects"], source["simulation"]
            period = source["period"]
            st.info(f"Fixed workbook snapshot · {period}. The main QC filters do not change this historical simulation. "
                    "Choose Active QC filters to recompute using the current QC dataset and scope.")
        else:
            if not ctx["supplier_ok"] or not ctx["adverse_ok"]:
                st.info("Confirm the QC supplier and adverse mappings in Data management before calculating a filtered simulation.")
                return
            if not st.checkbox("Use the workbook's simulation assumption: unrecorded supplier/category combinations count as zero recorded adverse (not proof of no defects)", key="ahp_zero_assumption"):
                st.info("Filtered simulation awaits acceptance of the documented zero-combination assumption. No scores are inferred yet.")
                return
            try:
                defects = defect_matrix(ctx["data"])
                result = inverse_simulation(defects, weights)
            except ValueError as exc:
                st.info(str(exc))
                return
            period = ctx.get("reporting_period", "Current filtered scope")
            st.caption(f"Active QC simulation period: {period}. Supplier/product/category/date filters all apply. "
                       "Changing the alternative set renormalizes priorities and scores; scores from different scopes are not directly comparable.")
        st.warning(SIMULATION)
        st.caption("Method B assumption: u(i,j) = 1 / (recorded adverse(i,j) + 1); "
                   "p(i,j) = u(i,j) / sum over suppliers u(i,j); final score(i) = sum over the five criteria weight(j) × p(i,j). "
                   "Missing supplier/category combinations become zero only under this explicit simulation convention. "
                   "Absent records do not prove zero defects or equal exposure. An all-zero criterion yields equal priorities, not evidence of good quality. "
                   "Category filters can make other criteria all zero while their simulation weights remain unchanged.")
        st.markdown("**Simulation supplier priorities · Method B (not pairwise alternative AHP)**")
        st.dataframe(result["local"], width="stretch")
        simulation_download(result["local"], "simulation_local_priorities.csv", index=True)
        with st.expander("Simulation quantities and weighted score contributions"):
            st.dataframe(defects, width="stretch")
            st.dataframe(result["contributions"], width="stretch")
        ranking = result["ranking"].copy()
        ranking["Reporting period"] = period
        st.markdown("**Simulation final scores & ranking · descending score**")
        st.dataframe(ranking, hide_index=True, width="stretch")
        simulation_download(ranking, "simulation_supplier_scores.csv")
        top_score = ranking["Simulation score"].iloc[0]
        tied = ranking.loc[ranking["Simulation score"].eq(top_score), "Supplier"]
        st.write(f"{SIMULATION}: highest computed score in this scope: {', '.join(tied)} ({top_score:.6f}). "
                 "Review the assumptions, reporting coverage and missing inspection exposure; this is not a supplier approval or replacement recommendation.")
        st.caption("Score ties use supplier name (case-insensitive, then exact spelling). "
                   "Workbook notes claiming user verification do not establish verified defective-unit counts; this app continues to call them recorded adverse quantities.")


def render_new_format(source):
    st.subheader('AHP simulation · supplier comparison workbook')
    st.warning(SIMULATION)
    st.info('Independent workbook snapshot. Data has no date column, so its reporting period cannot be verified from records. '
            'It is not relabelled or combined with the active QC dataset or used as evidence of its reporting period. '
            'Main QC filters do not change these fixed workbook matrices.')
    st.caption('Source period statement: ' + source['period_evidence'])
    st.write('Detected structure: Kriteria, Data, Rekap, Pairwise, five criterion-specific M_* matrices, and Hasil. '
             'Criteria inputs are examples/illustrations; supplier comparisons are data-derived simulation assumptions, not expert judgements.')
    st.markdown('**Criteria pairwise matrix · simulation**')
    st.dataframe(source['matrix'], width='stretch')
    ahp=source['ahp']
    st.markdown('**Criteria weights · column normalization then row average**')
    st.dataframe(ahp['weights'].rename_axis('Criterion').reset_index(), hide_index=True, width='stretch')
    simulation_download(ahp['weights'].to_frame(),'simulation_criteria_weights.csv',index=True)
    st.markdown('**Criteria consistency and mathematical reference**')
    st.dataframe(pd.DataFrame({'Metric':['Lambda estimate (workbook method)','CI (estimate)','RI','CR (estimate)',
                                       'Perron eigenvalue (reference)','Perron CR (reference)'],
                               'Value':[ahp['lambda_max'],ahp['CI'],ahp['RI'],ahp['CR'],ahp['eigenvalue_reference'],ahp['eigen_CR_reference']]}),hide_index=True)
    st.caption('Workbook method: normalize each column by its sum, then average each row to obtain w. '
               'Lambda estimate = mean((A × w) / w); CI = (lambda estimate − n)/(n−1); CR = CI/RI. '
               'This approximation is not the exact principal eigenvector method used by the old workbook. '
               'The independent Perron eigenvalue is shown separately; the difference is a methodological approximation, not silently overwritten.')
    st.markdown('**Supplier matrices and consistency · simulation**')
    st.dataframe(source['supplier_consistency'], hide_index=True, width='stretch')
    st.caption('Criteria RI = 1.12 for n=5. Supplier RI follows the documented Alonso–Lamata approximation '
               '(1.7699n − 4.3513)/(n−1); the supplied workbook has n=26. CR ≤ 0.10 is a consistency convention, not a quality rating. '
               'Each matrix is checked for positive finite values, unit diagonal, reciprocal values and a complete unique supplier set.')
    criterion=st.selectbox('Supplier matrix to inspect',list(source['supplier_matrices']),key='new_ahp_matrix')
    st.dataframe(source['supplier_matrices'][criterion],width='stretch')
    st.caption(f"{source['supplier_pairwise_filled']:,} comparisons read; {source['automatic_pairwise_count']:,} intensity cells contain formulas. "
               'Documented automatic rule: MIN(9, ROUND(MAX(a+1,b+1)/MIN(a+1,b+1),0)); lower recorded adverse is preferred. '
               'Rounding and the cap are research assumptions. They can introduce inconsistency. '
               'These comparisons do not measure defect rates or establish quality independent of inspection exposure.')
    st.markdown('**Workbook verification · independently recomputed**')
    st.dataframe(source['audit'],hide_index=True,width='stretch')
    if source['audit'].Result.ne('Matches').any():
        st.warning('Some saved workbook outputs disagree with Python or are unavailable. See the checks. '
                   'Displayed values are recalculated from the actual matrices using the detected workbook method.')
    st.caption('Tolerance: absolute 1e-10, relative 1e-8. Formula cells are inspected; required matrix inputs use saved caches. '
               'Python does not execute arbitrary Excel formulas. Missing required caches produce a specific error requesting recalculation and saving in Excel.')
    with st.expander('Worksheet inventory, merged cells and source preview'):
        st.dataframe(source['inventory'],hide_index=True,width='stretch')
        sheet=st.selectbox('AHP worksheet preview',list(source['sheets']),key='new_ahp_preview')
        st.dataframe(source['sheets'][sheet].head(20),hide_index=True,width='stretch')
    if ahp['CR'] > .1 or source['supplier_consistency'].CR.gt(.1).any():
        st.warning('One or more matrices exceed CR 0.10; supplier scores are withheld until the comparisons are reviewed.')
        return
    result=source['simulation']
    st.markdown('**Simulation supplier priorities by criterion**')
    st.dataframe(result['local'],width='stretch')
    simulation_download(result['local'],'simulation_local_priorities.csv',index=True)
    with st.expander('Recorded quantities and weighted contributions · simulation'):
        st.dataframe(source['defects'],width='stretch')
        st.dataframe(result['contributions'],width='stretch')
    st.markdown('**Simulation final weighted scores and ranking**')
    st.dataframe(result['ranking'],hide_index=True,width='stretch')
    simulation_download(result['ranking'],'simulation_supplier_scores.csv')
    st.caption('Final score = sum over five criteria (criterion weight × supplier local priority). '
               'Ranks reproduce Excel RANK: equal scores share a rank and leave gaps; names break display-order ties only. '
               'These simulation results are not recommendations to approve, reject or replace suppliers.')


def render_capstone(source, ctx):
    st.subheader('AHP · Supplier Improvement Priorities')
    st.caption('Five defect criteria · Principal eigenvector weights · Max-normalized improvement index')
    mode = st.radio('Improvement score source', ['Active QC data', 'Reference workbook snapshot'],
                    index=0 if ctx.get('supplier_ok') and ctx.get('adverse_ok') and not ctx.get('qc_missing') else 1,
                    key='capstone_calculation_scope', horizontal=True)
    if mode == 'Active QC data':
        if ctx.get('qc_missing') or not ctx.get('supplier_ok') or not ctx.get('adverse_ok'):
            st.info('Upload QC data and confirm supplier/adverse mappings to calculate active-data scores.')
            return None
        from utils.ahp_capstone import active_qc_improvement
        try:
            source = active_qc_improvement(source, ctx['data'], ctx.get('reporting_period', 'active reporting period'))
        except ValueError as exc:
            st.error('Active QC scores cannot be calculated: ' + str(exc))
            return None
        st.info('Weights and formulas follow the reference workbook. Quantities, maximum normalization, scores and rankings are recalculated from active QC records. '
                'Unrecorded supplier/category combinations use zero recorded adverse under the reference convention; this does not establish zero defects. '
                'Scores depend on the compared population and filters and cannot be compared directly across populations.')
    else:
        source = {**source, 'reference_snapshot': True, 'scope_label': 'reference workbook snapshot; QC filters do not apply.'}
    st.caption('RESULT SOURCE · ' + source['scope_label'])
    st.info('Higher scores mean higher improvement priority. AHP determines criterion weights; the supplier index uses normalized recorded quantities, not defect rates or overall quality scores.')
    ahp = source['ahp']
    cols = st.columns(3)
    cols[0].metric('Suppliers in score scope', len(source['defects']))
    cols[1].metric('Consistency Ratio', f"{ahp['CR']:.2%}")
    cols[2].metric('Criteria consistency', 'Passes CR ≤ 10%' if ahp['CR'] <= .1 else 'Review required')
    st.dataframe(ahp['weights'].rename('Criterion weight').rename_axis('Criterion').reset_index(), hide_index=True, width='stretch')
    st.caption('Weights are independently calculated using the principal eigenvector; the workbook uses 15 power iterations. '
               'Nij = Xij / maximum X for criterion j × 100; Pi = sum(Wj × Nij). All-zero criteria contribute zero. '
               'A zero cell means no recorded adverse for that combination, not proof of no defects. '
               'Maximum normalization can give a rare category considerable influence: a count of one normalizes to 100 when the category maximum is one.')
    with st.expander('Method details, matrices and workbook verification'):
        st.dataframe(source['matrix'], width='stretch')
        st.dataframe(pd.DataFrame({'Metric':['Lambda maximum','CI','RI','CR'], 'Value':[ahp['lambda_max'],ahp['CI'],ahp['RI'],ahp['CR']]}),hide_index=True)
        st.dataframe(source['audit'],hide_index=True,width='stretch')
        st.dataframe(source['inventory'],hide_index=True,width='stretch')
        st.dataframe(source['simulation']['normalized'],width='stretch')
        st.dataframe(source['simulation']['contributions'],width='stretch')
        sheet = st.selectbox('Reference worksheet preview',list(source['sheets']),key='capstone_sheet')
        st.dataframe(source['sheets'][sheet].head(35).astype('string').fillna(''),width='stretch')
    st.caption('Reference weights and the workbook audit remain independent. Active QC mode applies those weights to filtered records; snapshot mode uses reference quantities. '
               'The original workbook is unchanged. Saved Excel values are independently verified in Python. '
               'Results remain labelled as simulation and are not official company evaluations.')
    if ahp['CR'] > .1:
        st.warning('Scores are withheld because the criteria matrix exceeds the consistency threshold.')
        return
    st.markdown('**Improvement priorities · highest score first**')
    displayed = source['simulation']['ranking'].assign(Scope=source['scope_label'])
    st.dataframe(displayed,hide_index=True,width='stretch')
    simulation_download(displayed,'simulation_capstone_improvement.csv')
    return source
