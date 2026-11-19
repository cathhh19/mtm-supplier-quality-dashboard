"""Review shortlists from eligible observed records, independent of AHP snapshots."""
import pandas as pd
import streamlit as st
from utils import calculations as calc


def shortlist(data, limit=3, period=None):
    return calc.supplier_ranking(data, ascending=True, limit=limit, reporting_period=period)


def render_recommendations(ctx, ahp_source=None):
    st.divider()
    st.subheader('Supplier Recommendations · Review Shortlist')
    st.caption('Review candidates from available records. Check inspection exposure, reporting coverage, price, capacity and qualifications before selecting a supplier.')
    if ahp_source is not None and ahp_source['ahp']['CR'] <= .1:
        ranking = ahp_source['simulation']['ranking']
        if ahp_source.get('format') == 'capstone_improvement':
            top = ranking.iloc[0]
            st.markdown('**Follow-up priority from the AHP model**')
            st.info(f"{top['Supplier']} has the highest improvement-priority index ({top['Improvement priority score']:.4f}). "
                    f"Largest weighted contributor: {top['Largest weighted contributor']}. Review the supporting records and improvement plan. "
                    'This score identifies review priority, not the best supplier. Source: ' + ahp_source.get('scope_label', 'reference AHP snapshot, independent of active QC filters.'))
    if ctx.get('qc_missing') or not ctx.get('supplier_ok') or not ctx.get('adverse_ok'):
        st.info('For supplier and product shortlists, upload QC data and confirm supplier/adverse mappings in Data management. Product relationships must come from QC records.')
        return
    data, period = ctx['data'], ctx.get('reporting_period')
    table = shortlist(data, period=period)
    st.markdown('**Top 3 overall · lowest recorded adverse**')
    st.caption('Source: uploaded QC data and active filters · ' + (period or 'active reporting period'))
    if table.empty:
        st.info('No eligible records are available for a shortlist with these filters.')
        return
    for col, (_, row) in zip(st.columns(len(table)), table.iterrows()):
        with col:
            with st.container(border=True):
                st.markdown(f"**{int(row['Rank'])}. {row['Supplier']}**")
                st.metric('Recorded adverse', f"{row['Recorded adverse quantity']:,.0f}")
                st.caption(f"Months with records: {row['Months with records']} · Valid records: {row['Valid QC records']}")
                st.write('Most frequent category: ' + row['Most frequent category (by records)'])
                st.caption('Shortlisted for a lower recorded adverse total within this filtered supplier population.')
    st.warning('Lower adverse totals do not establish better quality or near-zero defects. Inspection exposure is unknown, and fewer records may produce lower totals. Months with records describe coverage.')
    st.markdown('**Top 3 suppliers by product / component**')
    # Offer explicit source product fields; never join them to the AHP workbook.
    source_columns = [c for c in ('Product name', 'Part No', 'product', 'part_number') if c in ctx['raw'].columns]
    mode = st.selectbox('Product grouping', ['Mapped product / component'] + source_columns, key='recommendation_product_field')
    work = data.copy()
    if mode in source_columns:
        work['product'] = ctx['raw'].loc[work.index, mode].astype('string').str.strip().replace('', pd.NA)
    products = sorted(work['product'].dropna().unique())
    if not products:
        st.info('No mapped product values are available in the current scope. Product shortlists cannot be generated.')
        return
    product = st.selectbox('Select product / component', products, key='recommendation_product')
    selected = work.loc[work['product'].eq(product)]
    result = shortlist(selected, period=period)
    if result.empty:
        st.info('This product has no eligible dated adverse records.')
        return
    st.caption(f'Only suppliers with eligible records for {product} are compared. Lower adverse totals rank first; supplier names determine display order for ties.')
    st.dataframe(result, hide_index=True, width='stretch')
    if len(result) < 3:
        noun = 'supplier has' if len(result) == 1 else 'suppliers have'
        st.info(f'Only {len(result)} {noun} eligible records for this product. No suppliers are added without an observed product relationship.')
    if calc.supplier_ranking(selected, limit=len(selected))['Months with records'].nunique() > 1:
        st.warning('Reporting coverage differs between suppliers. Review Months with records before comparing totals.')
    lead = result.iloc[0]
    st.write(f"Initial review candidate for {product}: {lead['Supplier']}. Recorded adverse: {lead['Recorded adverse quantity']:,.0f}; "
             f"valid records: {lead['Valid QC records']}; months with records: {lead['Months with records']}. "
             'Check record completeness and inspection exposure before procurement decisions.')
    st.caption('Absence from adverse records does not prove a supplier is defect-free. This is a descriptive product shortlist; the reference workbook does not provide product-specific AHP matrices.')
    st.download_button('Download product shortlist',result.to_csv(index=False).encode('utf-8-sig'),file_name='supplier_product_shortlist.csv',mime='text/csv',key='product_shortlist_download')
