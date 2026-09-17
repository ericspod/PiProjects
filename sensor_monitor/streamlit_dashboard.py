
import streamlit as st
import pandas as pd
import sqlite3
from pathlib import Path

DAYS_S = 60 * 60 * 24  # how many seconds in a day
NUM_DAYS = 2  # how many days of data to read
FREQ = "15min"  # frequency to group data items by

db = sorted(Path(".").glob("*.sqlite"))[-1]  # most recent database

with sqlite3.connect(db) as con:
    df = pd.read_sql_query(f"SELECT * from readings order by date desc limit {int(DAYS_S*NUM_DAYS)}", con)

df.date = pd.to_datetime(df.date, format="mixed", errors="coerce")
df.set_index("date", inplace=True)
df.sort_index(inplace=True)
df_sel = df.groupby(pd.Grouper(freq=FREQ)).mean().dropna(how="all")

st.title("Sensor Data")

left_column, right_column = st.columns(2)

for c in ("temperature", "humidity","pressure", "iaq"):
    data = df_sel[c].to_list()
    with (left_column if c in ("temperature", "humidity") else right_column):
        st.metric(c.title(), data[-1], chart_data=data, height=160, chart_type="area", border=True, format="%.2f")

st.line_chart(df_sel[["c", "b", "g", "r"]], color=["#ffffff55", "#0000ff55", "#00ff0055", "#ff000055"], height=200)
st.line_chart(df_sel[["oxidising", "reducing", "nh3"]], color=["#636EFA", "#EF553B", "#00CC96"], height=200)
st.line_chart(df_sel[["gas_resistance"]], color="#AB63FA", height=150)
