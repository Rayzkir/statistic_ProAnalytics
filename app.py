import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import re
from datetime import datetime, date

st.set_page_config(page_title="Мониторинг цен", page_icon="📊", layout="wide")

PRICE_COLS = [
    "Цена Озон", "Цена Озон по карте", "Цена Озон до скидки",
    "Цена WB", "Цена WB кошелек", "Цена WB до скидки",
]
DATE_COL_MAP = {
    "Цена Озон": "Дата цены озон",
    "Цена Озон по карте": "Дата цены Озон по карте",
    "Цена WB": "Дата цены WB",
    "Цена WB кошелек": "Дата цены WB кошелек",
}


def parse_time_from_filename(name: str) -> str:
    m = re.search(r"prices_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})", name)
    if m:
        return f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)}"
    return name


@st.cache_data
def load_from_folder(folder: str) -> dict[str, pd.DataFrame]:
    data = {}
    for f in sorted(Path(folder).glob("prices_*.xlsx")):
        ts = parse_time_from_filename(f.name)
        df = pd.read_excel(f, engine="calamine")
        df["Артикул"] = df["Артикул"].astype(str)
        data[ts] = df
    return data


def load_uploaded(files) -> dict[str, pd.DataFrame]:
    data = {}
    for f in sorted(files, key=lambda x: x.name):
        ts = parse_time_from_filename(f.name)
        df = pd.read_excel(f, engine="calamine")
        df["Артикул"] = df["Артикул"].astype(str)
        data[ts] = df
    return data


def compute_changes(snapshots: dict[str, pd.DataFrame]) -> pd.DataFrame:
    times = list(snapshots.keys())
    rows = []
    for i in range(1, len(times)):
        prev_t, curr_t = times[i - 1], times[i]
        prev_df = snapshots[prev_t].set_index("Артикул")
        curr_df = snapshots[curr_t].set_index("Артикул")
        common = prev_df.index.intersection(curr_df.index)
        for col in PRICE_COLS:
            if col not in prev_df.columns or col not in curr_df.columns:
                continue
            pp = prev_df.loc[common, col]
            cp = curr_df.loc[common, col]
            mask = (pp != cp) & pp.notna() & cp.notna()
            for art in common[mask]:
                name = curr_df.loc[art, "Наименование"]
                old_p = pp.loc[art]
                new_p = cp.loc[art]
                if isinstance(name, pd.Series):
                    name = name.iloc[0]
                if isinstance(old_p, pd.Series):
                    old_p = old_p.iloc[0]
                if isinstance(new_p, pd.Series):
                    new_p = new_p.iloc[0]
                date_col = DATE_COL_MAP.get(col, "")
                upd_date = ""
                if date_col and date_col in curr_df.columns:
                    nd = curr_df.loc[art, date_col]
                    if isinstance(nd, pd.Series):
                        nd = nd.iloc[0]
                    if pd.notna(nd):
                        upd_date = str(nd).replace("T", " ").replace("Z", "")
                platform = "Озон" if "Озон" in col else "WB"
                rows.append({
                    "Артикул": art,
                    "Наименование": name,
                    "Площадка": platform,
                    "Тип цены": col,
                    "Старая цена": old_p,
                    "Новая цена": new_p,
                    "Разница ₽": new_p - old_p,
                    "Разница %": round((new_p - old_p) / old_p * 100, 1) if old_p else 0,
                    "Забор до": prev_t,
                    "Забор после": curr_t,
                    "Дата обновления": upd_date,
                })
    return pd.DataFrame(rows)


def generate_html_report(
    df_products: pd.DataFrame,
    changes: pd.DataFrame,
    fig_bar: go.Figure | None,
    fig_lines: dict[str, go.Figure],
    period: str,
) -> str:
    today = date.today().strftime("%d.%m.%Y")

    # Product table HTML
    products_html = df_products.to_html(
        index=False, classes="tbl", border=0, na_rep="—",
        float_format=lambda x: f"{x:,.0f}".replace(",", " "),
    )

    # Changes table with color
    if not changes.empty:
        def fmt_row(r):
            color = "#C62828" if r["Разница ₽"] > 0 else "#2E7D32" if r["Разница ₽"] < 0 else "#333"
            sign = "+" if r["Разница ₽"] > 0 else ""
            return (
                f"<tr>"
                f"<td>{r['Артикул']}</td>"
                f"<td>{r['Наименование'][:60]}</td>"
                f"<td>{r['Площадка']}</td>"
                f"<td>{r['Тип цены']}</td>"
                f"<td>{r['Старая цена']:,.0f}</td>"
                f"<td>{r['Новая цена']:,.0f}</td>"
                f"<td style='color:{color};font-weight:bold'>{sign}{r['Разница ₽']:,.0f} ₽</td>"
                f"<td style='color:{color};font-weight:bold'>{sign}{r['Разница %']:.1f}%</td>"
                f"<td>{r['Забор до']}</td>"
                f"<td>{r['Забор после']}</td>"
                f"<td>{r['Дата обновления']}</td>"
                f"</tr>"
            )
        changes_rows = "\n".join(fmt_row(r) for _, r in changes.iterrows())
        changes_html = f"""
        <table class="tbl">
            <thead><tr>
                <th>Артикул</th><th>Наименование</th><th>Площадка</th><th>Тип цены</th>
                <th>Старая цена</th><th>Новая цена</th><th>Разница ₽</th><th>Разница %</th>
                <th>Забор до</th><th>Забор после</th><th>Дата обновления</th>
            </tr></thead>
            <tbody>{changes_rows}</tbody>
        </table>"""
        up_count = len(changes[changes["Разница ₽"] > 0])
        down_count = len(changes[changes["Разница ₽"] < 0])
        summary = f"<p>Изменений: <b>{len(changes)}</b> | Товаров: <b>{changes['Артикул'].nunique()}</b> | Рост: <b>{up_count}</b> | Снижение: <b>{down_count}</b></p>"
    else:
        changes_html = "<p>Изменений цен не обнаружено.</p>"
        summary = ""

    # Charts
    bar_html = fig_bar.to_html(full_html=False, include_plotlyjs=False) if fig_bar else ""
    lines_html = ""
    for label, fig in fig_lines.items():
        lines_html += f"<h3>{label}</h3>\n{fig.to_html(full_html=False, include_plotlyjs=False)}\n"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Отчёт по ценам — {today}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 2rem; color: #333; background: #fafafa; }}
  h1 {{ color: #1F3864; border-bottom: 3px solid #4472C4; padding-bottom: .5rem; }}
  h2 {{ color: #4472C4; margin-top: 2rem; }}
  .tbl {{ border-collapse: collapse; width: 100%; font-size: 13px; margin: 1rem 0; }}
  .tbl th {{ background: #4472C4; color: #fff; padding: 8px 10px; text-align: left; position: sticky; top: 0; }}
  .tbl td {{ padding: 6px 10px; border-bottom: 1px solid #e0e0e0; }}
  .tbl tr:nth-child(even) {{ background: #f5f5f5; }}
  .tbl tr:hover {{ background: #e3f2fd; }}
  .metrics {{ display: flex; gap: 1.5rem; margin: 1rem 0; }}
  .metric {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 1rem 1.5rem; text-align: center; }}
  .metric .val {{ font-size: 1.8rem; font-weight: bold; color: #1F3864; }}
  .metric .lbl {{ font-size: 0.85rem; color: #666; }}
  .period {{ color: #888; font-size: 0.9rem; }}
</style>
</head>
<body>
<h1>📊 Отчёт по ценам Озон / WB</h1>
<p class="period">Дата отчёта: {today} | Период данных: {period}</p>

<h2>📋 Все товары (последний снимок)</h2>
<div style="max-height:500px;overflow:auto;">{products_html}</div>

<h2>📈 Изменения цен</h2>
{summary}
<div style="max-height:500px;overflow:auto;">{changes_html}</div>

{"<h2>Топ изменений</h2>" + bar_html if bar_html else ""}

{"<h2>Динамика цен</h2>" + lines_html if lines_html else ""}

</body>
</html>"""


def build_timeline(snapshots: dict[str, pd.DataFrame], article: str) -> pd.DataFrame:
    rows = []
    for ts, df in snapshots.items():
        df_art = df[df["Артикул"] == article]
        if df_art.empty:
            continue
        row = df_art.iloc[0]
        for col in PRICE_COLS:
            if col in df.columns and pd.notna(row.get(col)):
                rows.append({
                    "Время": ts,
                    "Тип цены": col,
                    "Цена": row[col],
                })
    return pd.DataFrame(rows)


# ── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.title("⚙️ Настройки")

source = st.sidebar.radio("Источник данных", ["Из папки", "Загрузить файлы"])

snapshots = {}
if source == "Из папки":
    folder = st.sidebar.text_input("Путь к папке", value=str(Path(__file__).parent))
    if folder:
        snapshots = load_from_folder(folder)
else:
    uploaded = st.sidebar.file_uploader(
        "Загрузите xlsx-файлы", type=["xlsx"], accept_multiple_files=True
    )
    if uploaded:
        snapshots = load_uploaded(uploaded)

if not snapshots:
    st.warning("Нет данных. Укажите папку с файлами или загрузите xlsx.")
    st.stop()

st.sidebar.markdown(f"**Загружено снимков:** {len(snapshots)}")
st.sidebar.markdown(f"**Период:** {list(snapshots.keys())[0]} — {list(snapshots.keys())[-1]}")

platform_filter = st.sidebar.selectbox("Площадка", ["Все", "Озон", "WB"])
search = st.sidebar.text_input("🔍 Поиск (артикул / название)")

# ── Main ─────────────────────────────────────────────────────────────────────
st.title("📊 Мониторинг цен Озон / WB")

tab1, tab2 = st.tabs(["📋 Все товары", "📈 Изменения цен"])

# ── Tab 1: All products ─────────────────────────────────────────────────────
with tab1:
    last_ts = list(snapshots.keys())[-1]
    df_last = snapshots[last_ts].copy()

    display_cols = ["Артикул", "Наименование"]
    if platform_filter in ("Все", "Озон"):
        display_cols += [c for c in ["Цена Озон", "Цена Озон по карте", "Цена Озон до скидки"] if c in df_last.columns]
    if platform_filter in ("Все", "WB"):
        display_cols += [c for c in ["Цена WB", "Цена WB кошелек", "Цена WB до скидки"] if c in df_last.columns]

    df_show = df_last[display_cols].copy()

    if search:
        mask = (
            df_show["Артикул"].str.contains(search, case=False, na=False)
            | df_show["Наименование"].str.contains(search, case=False, na=False)
        )
        df_show = df_show[mask]

    st.subheader(f"Товары — снимок {last_ts}")

    col1, col2, col3 = st.columns(3)
    col1.metric("Всего товаров", len(df_show))
    ozon_cols = [c for c in df_show.columns if "Озон" in c]
    wb_cols = [c for c in df_show.columns if "WB" in c]
    if ozon_cols:
        col2.metric("Средняя цена Озон", f"{df_show[ozon_cols[0]].mean():.0f} ₽")
    if wb_cols:
        col3.metric("Средняя цена WB", f"{df_show[wb_cols[0]].mean():.0f} ₽")

    st.dataframe(
        df_show.reset_index(drop=True),
        use_container_width=True,
        height=500,
        column_config={
            c: st.column_config.NumberColumn(format="%.0f ₽")
            for c in df_show.columns if "Цена" in c
        },
    )

# ── Tab 2: Price changes ────────────────────────────────────────────────────
with tab2:
    changes = compute_changes(snapshots)

    if changes.empty:
        st.info("Между снимками изменений цен не обнаружено.")
    else:
        if platform_filter != "Все":
            changes = changes[changes["Площадка"] == platform_filter]
        if search:
            mask = (
                changes["Артикул"].str.contains(search, case=False, na=False)
                | changes["Наименование"].str.contains(search, case=False, na=False)
            )
            changes = changes[mask]

        st.subheader("Сводка изменений")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Изменений", len(changes))
        c2.metric("Товаров", changes["Артикул"].nunique())
        up = changes[changes["Разница ₽"] > 0]
        down = changes[changes["Разница ₽"] < 0]
        c3.metric("Рост цен ↑", len(up))
        c4.metric("Снижение цен ↓", len(down))

        # Styled table
        def color_diff(val):
            if val > 0:
                return "color: #C62828; font-weight: bold"
            elif val < 0:
                return "color: #2E7D32; font-weight: bold"
            return ""

        st.dataframe(
            changes.reset_index(drop=True).style.map(color_diff, subset=["Разница ₽", "Разница %"]),
            use_container_width=True,
            height=400,
            column_config={
                "Старая цена": st.column_config.NumberColumn(format="%.0f ₽"),
                "Новая цена": st.column_config.NumberColumn(format="%.0f ₽"),
                "Разница ₽": st.column_config.NumberColumn(format="%+.0f ₽"),
                "Разница %": st.column_config.NumberColumn(format="%+.1f%%"),
            },
        )

        # Bar chart — top changes
        st.subheader("Топ изменений по абсолютной разнице")
        top = changes.copy()
        top["Абс. разница"] = top["Разница ₽"].abs()
        top = top.nlargest(15, "Абс. разница")
        top["Лейбл"] = top["Артикул"] + " — " + top["Тип цены"]
        top["Направление"] = top["Разница ₽"].apply(lambda x: "Рост" if x > 0 else "Снижение")

        fig_bar = px.bar(
            top.sort_values("Разница ₽"),
            x="Разница ₽",
            y="Лейбл",
            color="Направление",
            color_discrete_map={"Рост": "#EF5350", "Снижение": "#66BB6A"},
            orientation="h",
            text="Разница ₽",
        )
        fig_bar.update_layout(height=max(350, len(top) * 35), yaxis_title="", xaxis_title="Разница, ₽", template="plotly")
        fig_bar.update_traces(texttemplate="%{text:+.0f} ₽", textposition="outside")
        st.plotly_chart(fig_bar, use_container_width=True, theme=None)

        # Timeline for selected article
        st.subheader("Динамика цены товара")
        changed_articles = changes[["Артикул", "Наименование"]].drop_duplicates()
        options = {
            f"{r['Артикул']} — {r['Наименование'][:50]}": r["Артикул"]
            for _, r in changed_articles.iterrows()
        }
        selected_label = st.selectbox("Выберите товар", list(options.keys()))
        if selected_label:
            selected_art = options[selected_label]
            timeline = build_timeline(snapshots, selected_art)
            if not timeline.empty:
                fig_line = px.line(
                    timeline,
                    x="Время",
                    y="Цена",
                    color="Тип цены",
                    markers=True,
                )
                fig_line.update_layout(
                    height=400,
                    xaxis_title="Время забора данных",
                    yaxis_title="Цена, ₽",
                    legend_title="",
                    template="plotly",
                )
                st.plotly_chart(fig_line, use_container_width=True, theme=None)

# ── Export to HTML ───────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("📤 Экспорт")

if st.sidebar.button("Скачать HTML-отчёт"):
    last_ts = list(snapshots.keys())[-1]
    df_last = snapshots[last_ts].copy()

    export_cols = ["Артикул", "Наименование"]
    for c in PRICE_COLS:
        if c in df_last.columns:
            export_cols.append(c)
    df_export = df_last[export_cols]

    changes_all = compute_changes(snapshots)

    # Bar chart for export
    export_bar = None
    if not changes_all.empty:
        top_ex = changes_all.copy()
        top_ex["Абс. разница"] = top_ex["Разница ₽"].abs()
        top_ex = top_ex.nlargest(15, "Абс. разница")
        top_ex["Лейбл"] = top_ex["Артикул"] + " — " + top_ex["Тип цены"]
        top_ex["Направление"] = top_ex["Разница ₽"].apply(lambda x: "Рост" if x > 0 else "Снижение")
        export_bar = px.bar(
            top_ex.sort_values("Разница ₽"), x="Разница ₽", y="Лейбл",
            color="Направление", color_discrete_map={"Рост": "#EF5350", "Снижение": "#66BB6A"},
            orientation="h", text="Разница ₽",
        )
        export_bar.update_traces(texttemplate="%{text:+.0f} ₽", textposition="outside")
        export_bar.update_layout(height=max(350, len(top_ex) * 35), yaxis_title="", xaxis_title="Разница, ₽", template="plotly")

    # Line charts for each changed article
    export_lines = {}
    if not changes_all.empty:
        for art in changes_all["Артикул"].unique():
            name = changes_all.loc[changes_all["Артикул"] == art, "Наименование"].iloc[0]
            tl = build_timeline(snapshots, art)
            if not tl.empty:
                fig = px.line(tl, x="Время", y="Цена", color="Тип цены", markers=True)
                fig.update_layout(height=350, xaxis_title="Время забора", yaxis_title="Цена, ₽", legend_title="", template="plotly")
                export_lines[f"{art} — {name[:50]}"] = fig

    period = f"{list(snapshots.keys())[0]} — {list(snapshots.keys())[-1]}"
    html = generate_html_report(df_export, changes_all, export_bar, export_lines, period)

    st.sidebar.download_button(
        label="💾 Сохранить файл",
        data=html.encode("utf-8"),
        file_name=f"отчёт_цены_{date.today().strftime('%Y-%m-%d')}.html",
        mime="text/html",
    )
