"""
Dashboard charts (Plotly) built from the parsed transactions.

Every function takes the already-filtered transactions, so the charts, the
KPIs and the exports always show the same rows.
"""

from __future__ import annotations

from io import BytesIO
from typing import Dict, List

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from payees import counterparty

NAVY = "#1D2844"
BLUE = "#246094"
TAUPE = "#918E81"
RISK_COLORS = {"High": "#B42318", "Medium": "#D97706", "Low": "#15803D"}
CATEGORY_COLORS = [NAVY, BLUE, TAUPE, "#5B8DB8", "#B9A57A", "#3F4E73", "#7A8C99", "#A65E46", "#6F9E7A", "#C2B8A3", "#8E6C8A"]
FONT = "Inter, system-ui, -apple-system, Segoe UI, sans-serif"
GRANULARITY = {"Daily": "D", "Weekly": "W-MON", "Monthly": "MS"}
PLOTLY_CONFIG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}}


def prepare(transactions: pd.DataFrame, category_names: Dict[str, str]) -> pd.DataFrame:
    """Add the columns the dashboard filters and charts on."""
    df = transactions.copy()
    df["date"] = pd.to_datetime(df["txn_date"], errors="coerce")
    for col in ("amount", "debit", "credit", "running_balance", "risk_score"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df["money_in"] = df["credit"].fillna(0.0)
    df["money_out"] = df["debit"].fillna(0.0)
    df["net"] = df["money_in"] - df["money_out"]
    df["category"] = df["txn_category"].map(lambda c: category_names.get(c, str(c).replace("_", " ").title()))
    df["risk"] = df["risk_level"].fillna("low").str.title()
    df["account"] = df["statement_id"].astype(str) + df["account_number"].map(lambda a: f" · {a}" if pd.notna(a) and a else "")
    # One line per real account across monthly statements: file name (without the month) + account.
    base = df["statement_id"].astype(str).str.split(" · ").str[0]
    acct = df["account_number"].map(lambda a: str(a) if pd.notna(a) and a else "Account")
    df["series"] = acct if base.nunique() == 1 else base + " · " + acct
    df["payee"] = [counterparty(d, c) for d, c in zip(df["description"], df["txn_category"])]
    df["flagged"] = df["risk_level"].isin(["high", "medium"])
    return df


def _style(fig: go.Figure, height: int = 340) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        font=dict(family=FONT, size=12, color="#1F2937"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title=None),
        hoverlabel=dict(font_family=FONT),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#ECEEF2", zeroline=False)
    return fig


def cash_flow(df: pd.DataFrame, granularity: str) -> go.Figure:
    """Money in vs. money out per period, with the net change as a line."""
    frame = df.dropna(subset=["date"]).set_index("date").resample(GRANULARITY[granularity])[["money_in", "money_out", "net"]].sum().reset_index()
    fig = go.Figure()
    fig.add_bar(x=frame["date"], y=frame["money_in"], name="Money in", marker_color=BLUE, hovertemplate="%{x|%b %d, %Y}<br>In: $%{y:,.2f}<extra></extra>")
    fig.add_bar(x=frame["date"], y=-frame["money_out"], name="Money out", marker_color=TAUPE, hovertemplate="%{x|%b %d, %Y}<br>Out: $%{customdata:,.2f}<extra></extra>", customdata=frame["money_out"])
    fig.add_scatter(x=frame["date"], y=frame["net"], name="Net change", mode="lines+markers", line=dict(color=NAVY, width=2), hovertemplate="%{x|%b %d, %Y}<br>Net: $%{y:,.2f}<extra></extra>")
    fig.update_layout(barmode="relative")
    fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    return _style(fig)


def balance_over_time(df: pd.DataFrame) -> go.Figure:
    """Running balance per account where the statement prints one, otherwise the cumulative net change."""
    fig = go.Figure()
    for i, (account, grp) in enumerate(df.dropna(subset=["date"]).sort_values(["date", "source_page", "source_line"]).groupby("series")):
        color = CATEGORY_COLORS[i % len(CATEGORY_COLORS)]
        balances = grp.dropna(subset=["running_balance"])
        if not balances.empty:
            fig.add_scatter(x=balances["date"], y=balances["running_balance"], name=f"{account} (balance)", mode="lines", line=dict(color=color, width=2, shape="hv"), hovertemplate="%{x|%b %d, %Y}<br>Balance: $%{y:,.2f}<extra>%{fullData.name}</extra>")
        else:
            fig.add_scatter(x=grp["date"], y=grp["net"].cumsum(), name=f"{account} (cumulative net)", mode="lines", line=dict(color=color, width=2, dash="dot", shape="hv"), hovertemplate="%{x|%b %d, %Y}<br>Cumulative net: $%{y:,.2f}<extra>%{fullData.name}</extra>")
    fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    return _style(fig)


def category_totals(df: pd.DataFrame) -> go.Figure:
    """Dollar total and count per transaction type."""
    frame = df.assign(total=df["money_in"] + df["money_out"]).groupby("category").agg(total=("total", "sum"), count=("total", "size")).reset_index().sort_values("total")
    fig = px.bar(frame, x="total", y="category", orientation="h", text="count", custom_data=["count"], color_discrete_sequence=[NAVY])
    fig.update_traces(texttemplate="%{text} txns", textposition="outside", cliponaxis=False, hovertemplate="%{y}<br>$%{x:,.2f} across %{customdata[0]} transactions<extra></extra>")
    fig.update_xaxes(tickprefix="$", tickformat=",.0f", title=None, range=[0, frame["total"].max() * 1.22])
    fig.update_yaxes(title=None)
    return _style(fig, height=max(260, 34 * len(frame) + 60))


def category_over_time(df: pd.DataFrame, granularity: str) -> go.Figure:
    """Money out per period, stacked by transaction type."""
    out = df[df["money_out"] > 0].dropna(subset=["date"])
    frame = out.groupby([pd.Grouper(key="date", freq=GRANULARITY[granularity]), "category"])["money_out"].sum().reset_index()
    fig = px.bar(frame, x="date", y="money_out", color="category", color_discrete_sequence=CATEGORY_COLORS)
    fig.update_traces(hovertemplate="%{x|%b %d, %Y}<br>%{fullData.name}: $%{y:,.2f}<extra></extra>")
    fig.update_xaxes(title=None)
    fig.update_yaxes(title=None, tickprefix="$", tickformat=",.0f")
    return _style(fig)


def flag_reasons(df: pd.DataFrame) -> go.Figure:
    """How often each red-flag reason fired on higher-risk transactions."""
    reasons = df.loc[df["flagged"], "risk_reasons"].dropna().str.split(";").explode().str.strip()
    frame = reasons[reasons.ne("") & reasons.ne("baseline profile")].value_counts().rename_axis("reason").reset_index(name="count").sort_values("count")
    fig = px.bar(frame, x="count", y="reason", orientation="h", color_discrete_sequence=[RISK_COLORS["High"]])
    fig.update_layout(bargap=0.45)
    fig.update_traces(hovertemplate="%{y}: %{x} transactions<extra></extra>")
    fig.update_xaxes(title=None, dtick=1 if frame["count"].max() < 10 else None)
    fig.update_yaxes(title=None)
    return _style(fig, height=max(240, 34 * len(frame) + 60))


def risk_timeline(df: pd.DataFrame) -> go.Figure:
    """Every transaction by date and size, colored by risk; hover shows why it scored that way."""
    frame = df.dropna(subset=["date", "amount"]).copy()
    frame["direction_label"] = frame["direction"].map({"credit": "Money in", "debit": "Money out"}).fillna("")
    fig = px.scatter(
        frame, x="date", y="amount", color="risk", size=frame["risk_score"].clip(lower=5), size_max=22,
        color_discrete_map=RISK_COLORS, category_orders={"risk": ["High", "Medium", "Low"]},
        custom_data=["description", "risk_score", "risk_reasons", "direction_label", "account"],
    )
    fig.update_traces(
        marker=dict(line=dict(width=0.5, color="#FFFFFF"), opacity=0.85),
        hovertemplate="<b>%{customdata[0]}</b><br>%{x|%b %d, %Y} · %{customdata[3]} $%{y:,.2f}<br>"
        "Risk score %{customdata[1]}: %{customdata[2]}<br>%{customdata[4]}<extra></extra>",
    )
    fig.update_yaxes(tickprefix="$", tickformat=",.0f", title=None, type="log" if frame["amount"].max() > 50 * max(frame["amount"].median(), 1) else "linear")
    fig.update_xaxes(title=None)
    return _style(fig, height=380)


def top_payees(df: pd.DataFrame, limit: int = 12) -> go.Figure:
    """Where the most money went (merchants and payees)."""
    frame = df[df["money_out"] > 0].groupby("payee").agg(total=("money_out", "sum"), count=("money_out", "size")).nlargest(limit, "total").reset_index().sort_values("total")
    fig = px.bar(frame, x="total", y="payee", orientation="h", custom_data=["count"], color_discrete_sequence=[BLUE])
    fig.update_traces(hovertemplate="%{y}<br>$%{x:,.2f} in %{customdata[0]} transactions<extra></extra>")
    fig.update_xaxes(tickprefix="$", tickformat=",.0f", title=None)
    fig.update_yaxes(title=None)
    return _style(fig, height=max(260, 30 * len(frame) + 60))


def weekday_pattern(df: pd.DataFrame) -> go.Figure:
    """Number of transactions and money out by day of the week (weekend activity is a common review point)."""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    frame = df.dropna(subset=["date"]).assign(day=lambda d: d["date"].dt.day_name()).groupby("day").agg(count=("amount", "size"), out=("money_out", "sum")).reindex(days, fill_value=0).reset_index()
    colors = [TAUPE if d in ("Saturday", "Sunday") else NAVY for d in frame["day"]]
    fig = go.Figure(go.Bar(x=frame["day"], y=frame["count"], marker_color=colors, customdata=frame["out"], hovertemplate="%{x}: %{y} transactions<br>Money out $%{customdata:,.2f}<extra></extra>"))
    return _style(fig, height=280)


EXPORT_COLUMNS = {
    "date": "Date", "account": "Statement / account", "description": "Description", "payee": "Payee", "category": "Type",
    "money_in": "Money in", "money_out": "Money out", "running_balance": "Balance", "risk": "Risk",
    "risk_score": "Risk score", "risk_reasons": "Why flagged", "redacted": "Redacted",
}


def export_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df[list(EXPORT_COLUMNS)].rename(columns=EXPORT_COLUMNS).copy()
    out["Date"] = out["Date"].dt.date
    return out.sort_values(["Statement / account", "Date"])


def to_excel(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        export_frame(df).to_excel(writer, sheet_name="Filtered transactions", index=False)
        sheet = writer.sheets["Filtered transactions"]
        for column, width in zip("ABCDEFGHIJKL", (12, 34, 48, 24, 20, 12, 12, 12, 9, 10, 48, 10)):
            sheet.column_dimensions[column].width = width
        for row in sheet.iter_rows(min_row=2, min_col=6, max_col=8):
            for cell in row:
                cell.number_format = '"$"#,##0.00'
    return buffer.getvalue()


def to_html_report(title: str, subtitle: str, figures: List[tuple]) -> str:
    """One self-contained HTML file with every chart (interactive, works offline)."""
    parts = []
    for i, (heading, fig) in enumerate(figures):
        chart = fig.to_html(full_html=False, include_plotlyjs=(i == 0), config=PLOTLY_CONFIG)
        parts.append(f"<section><h2>{heading}</h2>{chart}</section>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>body{{font-family:{FONT};margin:0;background:#F3F3F3;color:#1F2937}}
header{{background:{NAVY};color:#fff;padding:24px 32px}}header h1{{margin:0;font-size:24px}}header p{{margin:6px 0 0;opacity:.85}}
main{{max-width:1100px;margin:0 auto;padding:16px}}section{{background:#fff;border:1px solid #E2E2E2;border-radius:12px;padding:16px;margin:16px 0}}
h2{{font-size:16px;color:{NAVY};margin:0 0 8px}}</style></head><body><header><h1>{title}</h1><p>{subtitle}</p></header><main>{''.join(parts)}</main></body></html>"""
