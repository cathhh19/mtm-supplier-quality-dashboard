"""Shared company dashboard styling; no external assets or network dependencies."""
import streamlit as st


def apply_theme():
    st.markdown('''<style>
:root{--mtm-ink:#163b40;--mtm-teal:#177f75;--mtm-muted:#60777c;--mtm-line:#dce6e7}
.stApp{background:#f3f7f7;color:#18383d}
.block-container{max-width:1500px;padding-top:1.6rem;padding-bottom:3rem}
h1,h2,h3{color:var(--mtm-ink);letter-spacing:-.035em}
h1{font-size:2.55rem!important;font-weight:750!important}
h3{font-size:1.35rem!important;margin-top:.4rem}
p,label{font-size:1rem}
[data-testid="stCaptionContainer"]{color:var(--mtm-muted);line-height:1.6;opacity:1!important}
[data-testid="stCaptionContainer"] p{color:#526f74!important}
.st-key-brand_header{background:#123b40;border-radius:16px;padding:28px 32px;margin-bottom:24px}
.st-key-brand_header h1,.st-key-brand_header p{color:white!important}
.st-key-brand_header [data-testid="stCaptionContainer"] p{color:#d2e7e5!important}
[data-testid="stMetric"]{background:#fff;border:1px solid var(--mtm-line);border-radius:14px;padding:22px 24px;min-height:128px;box-shadow:0 3px 10px #143b4004}
[data-testid="stMetricLabel"]{color:#526e73;font-weight:600}
[data-testid="stMetricLabel"] p{white-space:normal;overflow:visible;text-overflow:clip}
[data-testid="stMetricValue"]{font-size:2rem;font-weight:700;color:#123b40}
[data-testid="stSidebar"]{background:#edf4f3;border-right:1px solid #d8e4e3}
[data-testid="stSidebar"] h2{font-size:1.6rem}
[data-testid="stExpander"]{background:white;border:1px solid var(--mtm-line);border-radius:12px}
[data-testid="stVerticalBlockBorderWrapper"]>div{border-radius:14px}
[data-testid="stPlotlyChart"],[data-testid="stDataFrame"]{background:white;border:1px solid #e2ebeb;border-radius:14px;box-sizing:border-box}
[data-testid="stFileUploader"]{background:white;border-radius:12px}
[data-testid="stFileUploaderDropzone"]{border:1px dashed #8cb7b1;border-radius:12px}
div.stButton>button,div.stDownloadButton>button{border-radius:8px;border-color:#cadcda;color:#185951;font-weight:600}
div.stButton>button:hover,div.stDownloadButton>button:hover{border-color:#177f75;background:#edf7f5}
[data-testid="stAlert"]{border-radius:10px}
[data-testid="stTopNav"]{border-bottom:1px solid #dce6e7;background:#fff}
[data-testid="stTopNav"] a{font-weight:600}
hr{border-color:#e0e9e9}
@media(max-width:1100px){[data-testid="stHorizontalBlock"]{flex-wrap:wrap}[data-testid="stColumn"]{min-width:min(100%,250px)!important;flex:1 1 250px!important}}
@media(max-width:640px){.block-container{padding:1rem}.st-key-brand_header{padding:20px}h1{font-size:1.9rem!important}[data-testid="stMetric"]{padding:16px}}
</style>''', unsafe_allow_html=True)


def welcome():
    with st.container(border=True):
        st.subheader('Start with your processed QC workbook')
        st.write('Upload the Excel output from your QC processing workflow in the sidebar. Your charts, supplier comparisons and recommendations will follow that file.')
        cols = st.columns(3)
        for col, title, text in zip(cols,
                ['Upload your workbook','Review the mapped fields','Explore your dashboard'],
                ['Use the Data Bersih worksheet, or a compatible QC Excel / CSV file.',
                 'Check the source preview, then confirm the supplier and recorded adverse fields.',
                 'Filter the period, review defect patterns and compare product-specific supplier shortlists.']):
            with col:
                st.markdown('**' + title + '**')
                st.caption(text)
        st.caption('AHP uses the configured reference workbook. Uploaded QC data is kept separate from the reference snapshot.')
