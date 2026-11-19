import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

COLORS = ["#177f75", "#406e85", "#7eaaa1", "#adc9c4", "#bd9860", "#697e84"]


def show(fig):
    fig.update_layout(template="plotly_white", colorway=COLORS, height=350,
                      margin=dict(l=15, r=20, t=55, b=15), font=dict(color="#23464b", size=14),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend_title_text="", title_font_size=17)
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#e7edf1")
    st.plotly_chart(fig, width="stretch")


def bar(table, field, title, metric="adverse", color=None, top=None):
    if table.empty or metric not in table or not table[metric].notna().any():
        st.info(f"{title}: no valid quantities in this scope.")
        return
    table = table.head(top) if top else table
    fig = px.bar(table, x=metric, y=field, orientation="h", color=color,
                 title=title, color_discrete_sequence=COLORS,
                 labels={metric: "Recorded adverse quantity" if metric == "adverse" else metric})
    fig.update_yaxes(autorange="reversed", title=None)
    show(fig)


def trend(table, title="Monthly recorded adverse quantity", by=None):
    if table.empty:
        st.info(f"{title}: requires valid dates and adverse quantities.")
        return
    fig = px.line(table, x="month", y="adverse", color=by, markers=True,
                  title=title, labels={"month": "Record month", "adverse": "Recorded adverse quantity"},
                  color_discrete_sequence=COLORS)
    # Explicit observed ticks avoid showing nonexistent months across sparse years.
    months = sorted(table.month.unique())
    fig.update_xaxes(tickformat="%b %Y", tickmode="array", tickvals=months)
    show(fig)
    st.caption("Points represent recorded months. Months without records are not imputed as zero.")


def distribution(table):
    if table.empty or table.adverse.sum() <= 0:
        st.info("Category shares require a positive total adverse quantity.")
        return
    show(px.pie(table, names="category", values="adverse", hole=.68,
                title="Adverse distribution by category", color_discrete_sequence=COLORS))


def pareto(table):
    if table.empty or table.adverse.sum() <= 0:
        st.info("Pareto percentages require a positive total adverse quantity.")
        return
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=table.category, y=table.adverse, name="Adverse quantity",
                         marker_color=COLORS[0]), secondary_y=False)
    fig.add_trace(go.Scatter(x=table.category, y=table["Cumulative (%)"], name="Cumulative share",
                             mode="lines+markers", line=dict(color=COLORS[1])), secondary_y=True)
    fig.update_yaxes(title_text="Recorded adverse quantity", secondary_y=False)
    fig.update_yaxes(title_text="Cumulative (%)", range=[0, 105], secondary_y=True)
    fig.update_layout(title="Pareto · recorded adverse quantity", legend=dict(orientation="h", y=-.5))
    show(fig)
