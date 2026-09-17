import pandas as pd
import sqlite3
from pathlib import Path
import panel as pn
from bokeh.plotting import figure,curdoc
from bokeh.models import LinearAxis, Range1d

# panel serve --autoreload --address 0.0.0.0 --port 8000 --allow-websocket-origin=0.0.0.0:8000 panel_dashboard.py

curdoc().theme = "carbon"
pn.extension(design="fast", theme="dark", sizing_mode="stretch_width")

DAYS_S = 60 * 60 * 24  # how many seconds in a day
NUM_DAYS = 2  # how many days of data to read
FREQ = "15min"  # frequency to group data items by

COLORS = ["#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A", "#19D3F3", "#FF6692"]

db = sorted(Path(".").glob("*.sqlite"))[-1]  # most recent database

with sqlite3.connect(db) as con:
    df = pd.read_sql_query(f"SELECT * from readings order by date desc limit {int(DAYS_S*NUM_DAYS)}", con)

df.date = pd.to_datetime(df.date, format="mixed", errors="coerce")
df.set_index("date", inplace=True)
df.sort_index(inplace=True)
df_sel = df.groupby(pd.Grouper(freq=FREQ)).mean().dropna(how="all")

fig_conf = dict(height=400, x_axis_type="datetime", tools="reset,xpan,xbox_zoom", sizing_mode="stretch_width")

trends = []
for c, col in zip(["temperature", "humidity", "pressure", "iaq"], COLORS):
    data = {"x": df_sel.index, "y": df_sel[c].to_numpy()}
    n = pn.indicators.Trend(label=c.title(), data=data, layout="row", height=100, plot_type="area", plot_color=col)
    trends.append(n)

gasfig = figure(**fig_conf)
gasfig.yaxis.visible = False
gasfig.toolbar.logo = None

for g, color in zip(["oxidising", "reducing", "nh3"], COLORS[len(trends) :]):
    yg = df_sel[g]
    gasfig.extra_y_ranges[g] = Range1d(yg.min(), yg.max())
    ax = LinearAxis(y_range_name=g, axis_label=g.replace("_", " ").title())
    ax.axis_label_text_color = color
    gasfig.add_layout(ax, "left")
    gasfig.line(yg.index, yg, color=color)

rgbfig = figure(x_range=gasfig.x_range, y_axis_label="RGBC Values", **fig_conf)
rgbfig.xaxis.visible = False
rgbfig.toolbar.logo = None

for c, color in zip(["r", "g", "b", "c"], ["red", "green", "blue", "white"]):
    yc = df_sel[c]
    rgbfig.line(yc.index, yc, color=color, line_width=2)
    rgbfig.varea(yc.index, y1=yc * 0, y2=yc, fill_color=color, fill_alpha=0.25)

pn.Column("# Sensor Monitor", pn.Row(trends[0], trends[1]), pn.Row(trends[2], trends[3]), gasfig, rgbfig).servable()
