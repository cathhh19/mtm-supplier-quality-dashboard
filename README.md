# Publish the existing MTM Streamlit dashboard

This package contains application code only. No supplier Excel workbooks,
confidential research reports, local environment, or credentials are included.

1. Extract this ZIP and place its contents in a GitHub repository you control.
2. Sign in at https://share.streamlit.io/ and choose Create app.
3. Select the repository/branch and app.py as the entrypoint. Use Python 3.12.
4. Choose an available streamlit.app subdomain and deploy.
5. In sharing settings, enable public access if you want anyone with the URL to
   try it. Share the URL returned by Streamlit, not a localhost URL.

Visitors upload their processed QC workbook (Data Bersih) and confirm mappings.
The AHP workbook is deliberately omitted from this public code package because
it contains supplier data. Upload the approved workbook in Supplier Evaluation
to use its weights/method with active QC, or supply a separately approved public
reference before deployment. No supplier snapshot is published by this package.
The existing QC/AHP uploads, English UI and top-three shortlists remain in code.
Uploaded source files are not deliberately saved to disk by the dashboard;
Streamlit processes them in server memory/session and caches. Do not treat a
public deployment as permission to upload confidential company data. Use approved
or anonymized workbooks when sharing a public demonstration.

The public hosting account/repository must be authorized by its owner. This ZIP
is deployment-ready source, not evidence that the app has already been deployed.
