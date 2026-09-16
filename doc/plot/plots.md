# nov_gnsspq Plots Reference

The `nov_gnsspq.plot` module provides nine plots, each available in two variants: a static variant that accepts a `PqReader` instance and returns a `matplotlib.figure.Figure`, and an interactive variant (named `<plot>_interactive`) that returns a `plotly.graph_objects.Figure`. The same plots are accessible from the CLI via `gnsspq plot`. All variants require the `nov_gnsspq[plot]` optional dependency group.

---

## Installation

```bash
pip install nov_gnsspq[plot]
```

This installs both `matplotlib` (required for static plots) and `plotly` (required for interactive plots). The base `nov_gnsspq` package installs neither; importing any plot function without the appropriate dependency raises `ImportError` with an install hint.

---

## Available Plots

| Plot | Required log(s) | What it shows |
|---|---|---|
| `accuracy` | `BESTPOS` | Horizontal and height position std dev + satellite counts over time |
| `attitude_accuracy` | `INSSTDEV` | Roll, pitch, and heading std dev from the INS Kalman filter |
| `imu` | `RAWIMUSX` / `RAWIMUX` / `RAWIMUS` / `RAWIMU` | Accelerometer and gyroscope timeseries |
| `position` | `BESTPOS` | Fix scatter coloured by position type on an OSM tile basemap, plus altitude timeseries |
| `position_accuracy` | `INSSTDEV` | North, East, Up position std dev and 3D RMS trace |
| `satellite_stats` | `RANGE` (+ optional `SATVIS2`) | Per-PRN C/N0, elevation angle, code noise, and phase noise |
| `signal` | `RANGE` | Mean CN0 per satellite (bar chart with quality bands) and satellite count over time |
| `skyview` | `SATVIS2` | Polar sky view of satellite arcs, labelled by constellation and PRN |
| `tracking` | `RANGE` | Satellite and observation counts per constellation over time |

Every plot in this table also has an `_interactive` variant (e.g. `accuracy_interactive`, `tracking_interactive`) that returns a `plotly.graph_objects.Figure` instead of a matplotlib figure. The required logs and parameters are identical between variants.

---

## Python API

### Static plots (matplotlib)

Load a database with `PqReader`, then call any plot function directly. Each static function returns a `matplotlib.figure.Figure` that you can display, save, or embed.

```python
from nov_gnsspq.reader.frontend import PqReader
import nov_gnsspq.plot as plot

db = PqReader("./my_db")

# Display interactively (calls plt.show() internally, returns None)
plot.position(db)

# Get the figure object for saving or embedding
fig = plot.accuracy(db, plot=False)
fig.savefig("accuracy.png", dpi=150, bbox_inches="tight")
```

All static plot functions accept `plot: bool = True`. Pass `plot=False` to receive the `matplotlib.figure.Figure` for caller-controlled display or saving; the default `plot=True` calls `plt.show()` / `plt.close()` internally and returns `None`.

To generate multiple plots in a loop:

```python
from nov_gnsspq.reader.frontend import PqReader
import nov_gnsspq.plot as plot
import matplotlib.pyplot as plt
from pathlib import Path

db = PqReader("./my_db")
out = Path("./figures")
out.mkdir(exist_ok=True)

for name in ["accuracy", "tracking", "signal", "skyview"]:
    fn = getattr(plot, name)
    try:
        fig = fn(db, plot=False)
        fig.savefig(out / f"{name}.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    except (KeyError, AttributeError) as e:
        print(f"{name}: skipped — {e}")
```

The `run_plot()` function from the CLI module handles this loop for you, including error recovery and directory creation:

```python
from nov_gnsspq.cli.plot import run_plot

# Static PNGs
failures = run_plot(
    db_path="./my_db",
    plots=["accuracy", "tracking", "signal"],  # None = all plots
    out_dir="./figures",                        # None = plt.show()
)

for name, exc in failures.items():
    print(f"  {name} failed: {exc}")
```

### Interactive plots (Plotly)

Each plot function has a `_interactive` counterpart that produces a Plotly figure with hover tooltips, zoom, and pan controls. The call pattern is identical to the static variant:

```python
from nov_gnsspq.reader.frontend import PqReader
import nov_gnsspq.plot as plot

db = PqReader("./my_db")

fig = plot.accuracy_interactive(db)
fig.show()  # opens in the default browser
```

To combine multiple interactive figures into a single self-contained HTML dashboard, use `build_tabbed_html` from `nov_gnsspq.plot.dashboard`. The function accepts an ordered dict of `{name: plotly_figure}` pairs — names must contain only letters, digits, underscores, or hyphens — and returns a complete HTML string. The output embeds the Plotly JS bundle and the nov_gnsspq logomark as base64, so the resulting file has no external dependencies. Each tab additionally exposes a collapsible threshold-line editor for annotating any panel with horizontal or vertical reference lines.

```python
from nov_gnsspq.plot.dashboard import build_tabbed_html
import nov_gnsspq.plot as plot
from nov_gnsspq.reader.frontend import PqReader
from pathlib import Path

db = PqReader("./my_db")

figs = {
    "accuracy": plot.accuracy_interactive(db),
    "tracking": plot.tracking_interactive(db),
    "signal":   plot.signal_interactive(db),
}

html = build_tabbed_html(figs, title="My Recording")
Path("dashboard.html").write_text(html, encoding="utf-8")
```

`run_plot()` automates this for you via the `html=True` flag. When `out_dir` is set, the dashboard is written to `<out_dir>/dashboard.html`; when `out_dir` is `None`, it is opened in the default browser via a temporary file.

```python
from nov_gnsspq.cli.plot import run_plot

failures = run_plot(
    db_path="./my_db",
    plots=["accuracy", "tracking", "signal"],
    out_dir="./figures",
    html=True,  # renders interactive Plotly figures; writes dashboard.html
)
```

---

## CLI

See [cli.md](../cli/cli.md#plot) for the full `gnsspq plot` command reference.

---

## Plot Reference

### `accuracy`

**Required log:** `BESTPOS`

Two-panel figure sharing a GPS time axis:

1. Position std dev — `latitude_std_dev`, `longitude_std_dev`, and `height_std_dev` in metres on a single panel.
2. Solution statistics — total tracked satellites (`num_svs`) and satellites used in solution (`num_soln_svs`). When `diff_age` or `solution_age` columns are present in the log, they are overlaid on this panel as additional traces.

The figure title shows mean std dev values for quick reference. Useful as a first-pass quality check on positioning accuracy and constellation geometry.

```python
fig = plot.accuracy(db)
fig_interactive = plot.accuracy_interactive(db)
```

---

### `attitude_accuracy`

**Required log:** `INSSTDEV`

Two-panel figure:

1. Roll and pitch std dev (degrees) from `roll_std_dev` and `pitch_std_dev`.
2. Heading std dev (degrees) from `azimuth_std_dev`.

All values are INS Kalman filter estimates. This plot is only meaningful for configurations with an IMU; it complements `position_accuracy` for full INS/GNSS solution assessment.

```python
fig = plot.attitude_accuracy(db)
fig_interactive = plot.attitude_accuracy_interactive(db)
```

---

### `imu`

**Required log:** `RAWIMUSX`, `RAWIMUX`, `RAWIMUS`, or `RAWIMU` (tried in that order)

Two-panel figure:

1. Accelerometer: X, Y, Z axes in m/s².
2. Gyroscope: X, Y, Z axes in rad/s.

The time axis uses `gps_seconds` when available (the IMU-internal timestamp), falling back to `header_milliseconds`. The figure title identifies which log variant was found.

```python
fig = plot.imu(db)
fig_interactive = plot.imu_interactive(db)
```

---

### `position`

**Required log:** `BESTPOS`

3×2 figure with six panels sharing a GPS time axis where applicable:

1. Fix scatter in Web Mercator (EPSG:3857) coloured by position type (e.g. RTK Fixed, PPP, Single). Tick labels display in degrees. Rows where both `latitude` and `longitude` are exactly 0.0 are filtered out before plotting.
2. Orthometric height (`orthometric_height`) over GPS time.
3. Position type timeline — a scatter of decoded position type strings over time.
4. Solution status timeline — a scatter of decoded solution status strings over time (only present when a `solution_status` column exists in `BESTPOS`).

Position type and solution status codes are decoded against the full NovAtel OEM7 enumeration.

```python
# Returns the figure without displaying it
fig = plot.position(db, plot=False)

# Displays via plt.show() and returns None (default)
plot.position(db)
```

Pass `osm=True` to overlay OpenStreetMap tiles on the scatter map using `contextily`. If `contextily` is not installed, a warning is logged and the function continues without the basemap.

```python
fig = plot.position(db, plot=False, osm=True)
```

The interactive variant uses Plotly's built-in geographic scatter. Pass `osm=True` to switch to a `go.Scattermap` tile map instead of a plain scatter, and adds position type and solution status timelines as additional rows:

```python
fig_interactive = plot.position_interactive(db)
fig_interactive = plot.position_interactive(db, osm=True)
```

---

### `position_accuracy`

**Required log:** `INSSTDEV`

Single-axes figure showing North, East, and Up position std dev (treating `latitude_std_dev`, `longitude_std_dev`, and `height_std_dev` as N/E/U per NovAtel convention) alongside a 3D RMS trace computed as √(N² + E² + U²). Fixed RTK ambiguity solutions are clearly distinguishable from float solutions by the step-change in all four lines.

```python
fig = plot.position_accuracy(db)
fig_interactive = plot.position_accuracy_interactive(db)
```

---

### `satellite_stats`

**Required log:** `RANGE`  
**Optional log:** `SATVIS2` (adds the elevation panel; omitted gracefully if absent)

Three- or four-panel figure per satellite:

1. C/N0 in dB-Hz (best signal per epoch per PRN).
2. Elevation angle in degrees, forward-filled from `SATVIS2` epochs to `RANGE` epochs using a nearest-match within 10 seconds. *(Only present when `SATVIS2` is available.)*
3. Code measurement noise: mean `sd_psr` in metres.
4. Phase measurement noise: mean `sd_adr` in cycles.

Each line is coloured by constellation. The `prns` parameter restricts plotting to specific PRN numbers when the full constellation is too dense to read.

```python
fig = plot.satellite_stats(db)

# Restrict to specific PRNs
fig = plot.satellite_stats(db, prns=[1, 3, 7, 15])
```

The interactive variant accepts the same `prns` parameter. Clicking a constellation name in the legend hides or shows all satellites of that constellation simultaneously across all panels:

```python
fig_interactive = plot.satellite_stats_interactive(db)
fig_interactive = plot.satellite_stats_interactive(db, prns=[1, 3, 7, 15])
```

---

### `signal`

**Required log:** `RANGE`

Two-panel figure:

1. Bar chart of mean CN0 ± 1σ per satellite PRN, with colour-coded quality bands: Poor (<20 dB-Hz), Warning (20–30 dB-Hz), Good (30–60 dB-Hz), and High Warning (>60 dB-Hz, which may indicate spoofing or severe multipath).
2. Total satellite count over time.

```python
fig = plot.signal(db)
fig_interactive = plot.signal_interactive(db)
```

---

### `skyview`

**Required log:** `SATVIS2`

Polar figure with North at top and clockwise azimuth. Each satellite's track is plotted as an arc from the horizon (outer edge, 0° elevation) to zenith (centre, 90° elevation), coloured by constellation and labelled with a short PRN identifier (e.g. `G07`, `R22`, `E15`). Labels are placed at the point of peak elevation to minimise overlap. Constellations are distinguished by colour: GPS (green), GLONASS (red), BeiDou (blue), Galileo (purple), QZSS (orange), SBAS (grey).

```python
fig = plot.skyview(db)
fig_interactive = plot.skyview_interactive(db)
```

---

### `tracking`

**Required log:** `RANGE`

Two-panel figure sharing a GPS time axis:

1. Satellite count per constellation over time, with a total line in pink.
2. Observation count (total signals tracked, including multi-frequency) per constellation over time.

Constellation identity is decoded from bits 16–18 of the `c_status` field in the `obs` subtable. The figure title shows average counts across the recording for quick comparison.

```python
fig = plot.tracking(db)
fig_interactive = plot.tracking_interactive(db)
```

---

## Error Handling

Static plot functions raise `ImportError` if `matplotlib` is not installed; interactive plot functions raise `ImportError` if `plotly` is not installed. Both direct the user to `pip install nov_gnsspq[plot]`. Functions that require a specific log raise `AttributeError` or `KeyError` if that log is absent in the database.

The static `position` plot does not require `contextily` when called with the default `osm=False`. Passing `osm=True` causes `position()` to call `contextily.add_basemap` internally; if `contextily` is not installed, a warning is logged and the basemap step is skipped rather than raising an error. The `position_interactive` variant uses Plotly's built-in geographic scatter and has no `contextily` dependency at all.

When running plots programmatically, wrap calls in a `try/except` to handle databases that do not contain every log type:

```python
try:
    fig = plot.skyview(db)
except (AttributeError, KeyError):
    pass  # SATVIS2 not present in this recording
```
