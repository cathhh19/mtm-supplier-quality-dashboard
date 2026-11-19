"""Reporting dates come exclusively from the active QC source, without year limits."""


def reporting_dates(data):
    dates = data.date.dropna()
    if dates.empty:
        raise ValueError('No valid record dates are available. Map the date column and correct missing or invalid dates in the source.')
    return dates
