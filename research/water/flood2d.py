"""A minimal 2-D flood model (local inertial scheme, Bates et al. 2010 / de Almeida et al. 2012).

Rain-on-grid on the USGS 3DEP 2018 1 m DEM resampled to DX metres (mean), plus a measured river
inflow (USGS gauge discharge) injected at the channel cell nearest the gauge. Domain edges are open
(water leaving the grid is lost). Uniform Manning n; rainfall loss = initial abstraction then a
constant rate (a crude stand-in for infiltration + storm drains). Buildings are not represented
(bare-earth DEM). Outputs: max water-surface elevation (m NAVD88) per cell, and the water level time
series at check points.

Inputs: data/harris_mini/B/*2018*.tif, data/water/iemre_hourly_*.csv (IEM reanalysis hourly
precipitation, Stage IV based), data/water/usgs_08068800_00060.csv (inflow), gauge coordinates.
Usage: python flood2d.py RUN_NAME DX N LOSS_IN_PER_H [IA_IN] [HOURS]  (HOURS limits the run, for tests)
"""
import glob
import json
import sys
import time
from pathlib import Path

import numba as nb
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.merge import merge

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data"
G = 9.81
USFT = 1200 / 3937
CFS = 0.0283168
LON0, LAT0, LON1, LAT1 = -95.610, 29.930, -95.465, 30.035  # check gauge >= 4 km from the east edge
T0, T1 = pd.Timestamp("2017-08-25T18:00Z"), pd.Timestamp("2017-08-30T00:00Z")
GAUGES = {"in_08068800": (-95.5985545, 29.9735557), "chk_08068900": (-95.511885, 30.00660994)}


@nb.njit(parallel=True, cache=True)
def step(z, h, qx, qy, dt, dx, n2):
    ny, nx = h.shape
    # x-face fluxes between (i, j) and (i, j+1)
    for i in nb.prange(ny):
        for j in range(nx - 1):
            e1, e2 = z[i, j] + h[i, j], z[i, j + 1] + h[i, j + 1]
            hf = max(e1, e2) - max(z[i, j], z[i, j + 1])
            if hf <= 1e-4:
                qx[i, j] = 0.0
                continue
            q = qx[i, j]
            qn = (q - G * hf * dt * (e2 - e1) / dx) / (1.0 + G * dt * n2 * abs(q) / hf ** (7.0 / 3.0))
            # limit: never drain more than the donor cell holds in one step
            if qn > 0:
                qn = min(qn, h[i, j] * dx / (4 * dt))
            else:
                qn = max(qn, -h[i, j + 1] * dx / (4 * dt))
            qx[i, j] = qn
    for i in nb.prange(ny - 1):
        for j in range(nx):
            e1, e2 = z[i, j] + h[i, j], z[i + 1, j] + h[i + 1, j]
            hf = max(e1, e2) - max(z[i, j], z[i + 1, j])
            if hf <= 1e-4:
                qy[i, j] = 0.0
                continue
            q = qy[i, j]
            qn = (q - G * hf * dt * (e2 - e1) / dx) / (1.0 + G * dt * n2 * abs(q) / hf ** (7.0 / 3.0))
            if qn > 0:
                qn = min(qn, h[i, j] * dx / (4 * dt))
            else:
                qn = max(qn, -h[i + 1, j] * dx / (4 * dt))
            qy[i, j] = qn
    for i in nb.prange(ny):
        for j in range(nx):
            dq = 0.0
            if j > 0:
                dq += qx[i, j - 1]
            if j < nx - 1:
                dq -= qx[i, j]
            if i > 0:
                dq += qy[i - 1, j]
            if i < ny - 1:
                dq -= qy[i, j]
            h[i, j] = max(h[i, j] + dt * dq / dx, 0.0)


@nb.njit(parallel=True, cache=True)
def edges_and_max(z, h, wse_max, rain_m, dt, dx, n):
    ny, nx = h.shape
    for i in nb.prange(ny):
        for j in range(nx):
            h[i, j] += rain_m
            if i == 0 or j == 0 or i == ny - 1 or j == nx - 1:
                # open boundary at normal depth: q = h^(5/3) sqrt(S0) / n with S0 = 0.0005 (Cypress Creek
                # valley slope order), leaving through the outer face
                qo = h[i, j] ** (5.0 / 3.0) * 0.02236 / n
                h[i, j] = max(h[i, j] - min(qo * dt / dx, h[i, j]), 0.0)
            e = z[i, j] + h[i, j]
            if h[i, j] > 0.01 and e > wse_max[i, j]:
                wse_max[i, j] = e


def build_dem(dx):
    srcs = [rasterio.open(f) for f in glob.glob(str(D / "harris_mini" / "B" / "*2018*.tif"))]
    to = Transformer.from_crs("EPSG:4326", srcs[0].crs, always_xy=True)
    (x0, y0), (x1, y1) = to.transform(LON0, LAT0), to.transform(LON1, LAT1)
    arr, tr = merge(srcs, bounds=(x0, y0, x1, y1), res=dx, resampling=rasterio.enums.Resampling.average, nodata=np.nan)
    z = arr[0].astype(np.float64)
    z[~np.isfinite(z)] = np.nanmax(z)
    return z, tr, srcs[0].crs


def main(run, dx, n, loss_in_h, ia_in=0.5, hours=None):
    z, tr, crs = build_dem(dx)
    ny, nx = z.shape
    to = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inv = ~tr

    def cell(lon, lat, snap_m=60):
        x, y = to.transform(lon, lat)
        c, r = inv * (x, y)
        r, c = int(r), int(c)
        k = int(snap_m / dx)
        win = z[max(r - k, 0): r + k + 1, max(c - k, 0): c + k + 1]
        a, b = np.unravel_index(np.argmin(win), win.shape)  # lowest cell = the channel
        return max(r - k, 0) + a, max(c - k, 0) + b

    gin = cell(*GAUGES["in_08068800"])
    gchk = cell(*GAUGES["chk_08068900"])
    rain = pd.read_csv(sorted(glob.glob(str(D / "water" / "iemre_hourly_*.csv")))[0])
    rain["t"] = pd.to_datetime(rain.t)
    rain = rain.groupby("t").p.mean()  # in/h, mean of the 4 points
    qin = pd.read_csv(D / "water" / "usgs_08068800_00060.csv")
    qin["t"] = pd.to_datetime(qin.t)
    qin = qin.set_index("t").v
    h = np.zeros_like(z); qx = np.zeros((ny, nx)); qy = np.zeros((ny, nx))
    wse_max = np.full_like(z, -1e9)
    t, t_end = 0.0, (T1 - T0).total_seconds() if hours is None else hours * 3600.0
    ia_left = ia_in * 0.0254
    log, wall0, next_log = [], time.time(), 0.0
    while t < t_end:
        hmax = float(h.max())
        dt = min(0.7 * dx / np.sqrt(G * max(hmax, 0.05)), 30.0)
        now = T0 + pd.Timedelta(seconds=t)
        p_in_h = float(rain.asof(now.floor("h"))) if now >= rain.index[0] else 0.0
        p = max(p_in_h, 0.0) * 0.0254 / 3600 * dt  # m this step
        if ia_left > 0:
            take = min(ia_left, p); ia_left -= take; p -= take
        p = max(p - loss_in_h * 0.0254 / 3600 * dt, 0.0)
        step(z, h, qx, qy, dt, dx, n * n)
        q = float(np.interp(now.value, qin.index.view("int64"), qin.values)) * CFS
        h[gin] += q * dt / (dx * dx)
        edges_and_max(z, h, wse_max, p, dt, dx, n)
        t += dt
        if t >= next_log:
            log.append(dict(t=now.isoformat(), wse_chk_ft=float((z[gchk] + h[gchk]) / USFT), wet_cells=int((h > 0.05).sum()),
                            q_in_cfs=q / CFS, dt=dt))
            next_log += 1800
            if len(log) % 12 == 0:
                print(f"{run}: {now} wse@08068900 {log[-1]['wse_chk_ft']:.2f} ft  wet {log[-1]['wet_cells']}  dt {dt:.2f}s  wall {time.time() - wall0:.0f}s", flush=True)
    out = D / "water" / run
    out.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="GTiff", height=ny, width=nx, count=1, dtype="float32", crs=crs, transform=tr, compress="deflate", nodata=-9999)
    with rasterio.open(out / "wse_max_m.tif", "w", **prof) as o:
        o.write(np.where(wse_max > -1e8, wse_max, -9999).astype("float32"), 1)
    with rasterio.open(out / "dem_m.tif", "w", **prof) as o:
        o.write(z.astype("float32"), 1)
    pd.DataFrame(log).to_csv(out / "log.csv", index=False)
    json.dump(dict(run=run, dx=dx, n=n, loss_in_h=loss_in_h, ia_in=ia_in, cells=[ny, nx], wall_s=time.time() - wall0,
                   peak_wse_chk_ft=max(r["wse_chk_ft"] for r in log), gauge_in_cell=list(map(int, gin)), gauge_chk_cell=list(map(int, gchk))),
              open(out / "run.json", "w"), indent=1)
    print(f"{run}: done; peak simulated WSE at 08068900 {max(r['wse_chk_ft'] for r in log):.2f} ft (observed 113.82)")


if __name__ == "__main__":
    a = sys.argv
    main(a[1], float(a[2]), float(a[3]), float(a[4]), float(a[5]) if len(a) > 5 else 0.5,
         float(a[6]) if len(a) > 6 else None)
