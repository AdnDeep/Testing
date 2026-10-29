"""Mapa de Guayaquil: lluvia prevista (rojo) y posible anegamiento de calles (azul)."""
from __future__ import annotations

import io
import json
import math
import os
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap, BoundaryNorm  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch  # noqa: E402
from PIL import Image  # noqa: E402
from scipy.interpolate import RegularGridInterpolator  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402

from . import config as C
from .fetch import SESSION

R = 6378137.0
ZOOM = 13
# Teselas de OpenStreetMap. Se descargan una sola vez y se guardan en assets/ para respetar la
# política de uso de OSM (nada de descargas repetidas).
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
BASE_PNG = os.path.join(ASSETS, f"mapa_base_z{ZOOM}.png")
BASE_JSON = os.path.join(ASSETS, f"mapa_base_z{ZOOM}.json")
ATRIBUCION = "Mapa base © OpenStreetMap contributors"

NIVEL_COLOR = {
    "Moderado": ("#6FA8E8", 0.88),
    "Alto": ("#2F74C9", 0.90),
    "Muy alto": ("#0B3D91", 0.92),
}
LLUVIA_NIVELES = [1, 5, 10, 25, 50, 100, 200, 10000]
LLUVIA_COLORES = ["#FFC9C9", "#FF9C9C", "#FF6B6B", "#E8383D", "#C4141E", "#900C15", "#5E0610"]
LLUVIA_ALFA = [0.20, 0.26, 0.32, 0.38, 0.44, 0.50, 0.56]

INK = "#17222D"
MUTED = "#5B6875"
PAPER = "#FFFFFF"


def merc(lon, lat):
    x = R * np.radians(lon)
    y = R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    return x, y


def _tile_xy(lon, lat, z):
    n = 2 ** z
    xt = (lon + 180.0) / 360.0 * n
    yt = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return xt, yt


def _tile_bounds_merc(x, y, z):
    n = 2 ** z
    x0 = (x / n * 2 - 1) * math.pi * R
    x1 = ((x + 1) / n * 2 - 1) * math.pi * R
    y0 = (1 - (y + 1) / n * 2) * math.pi * R
    y1 = (1 - y / n * 2) * math.pi * R
    return x0, x1, y0, y1


def mapa_base():
    """Mapa base aclarado (OSM). Devuelve (imagen, extent_merc, atribución) o None."""
    from PIL import ImageEnhance

    if os.path.exists(BASE_PNG) and os.path.exists(BASE_JSON):
        with open(BASE_JSON) as fh:
            ext = tuple(json.load(fh)["extent_merc"])
        return np.asarray(Image.open(BASE_PNG).convert("RGB")), ext, ATRIBUCION

    e = C.EXTENT
    xa, ya = _tile_xy(e["lon_min"], e["lat_max"], ZOOM)
    xb, yb = _tile_xy(e["lon_max"], e["lat_min"], ZOOM)
    xs = range(int(xa), int(xb) + 1)
    ys = range(int(ya), int(yb) + 1)
    try:
        tiles = {}
        for x in xs:
            for y in ys:
                r = SESSION.get(TILE_URL.format(z=ZOOM, x=x, y=y), timeout=30)
                r.raise_for_status()
                tiles[(x, y)] = Image.open(io.BytesIO(r.content)).convert("RGB")
        tw, th = next(iter(tiles.values())).size
        mosaico = Image.new("RGB", (tw * len(xs), th * len(ys)))
        for (x, y), im in tiles.items():
            mosaico.paste(im, ((x - xs[0]) * tw, (y - ys[0]) * th))
        # Aclarar y quitar saturación para que el rojo y el azul se lean encima
        mosaico = ImageEnhance.Color(mosaico).enhance(0.22)
        mosaico = ImageEnhance.Contrast(mosaico).enhance(0.9)
        mosaico = ImageEnhance.Brightness(mosaico).enhance(1.06)
        x0, _, _, y1 = _tile_bounds_merc(xs[0], ys[0], ZOOM)
        _, x1, y0, _ = _tile_bounds_merc(xs[-1], ys[-1], ZOOM)
        os.makedirs(ASSETS, exist_ok=True)
        mosaico.save(BASE_PNG, optimize=True)
        with open(BASE_JSON, "w") as fh:
            json.dump({"extent_merc": [x0, x1, y0, y1], "zoom": ZOOM, "fuente": TILE_URL,
                       "atribucion": ATRIBUCION}, fh)
        return np.asarray(mosaico), (x0, x1, y0, y1), ATRIBUCION
    except Exception as ex:
        print(f"[mapa] mapa base no disponible: {ex}")
        return None


def _campo_fino(campo: np.ndarray, n=260):
    lats = np.array(C.GRID_LATS)[::-1]  # creciente
    lons = np.array(C.GRID_LONS)
    interp = RegularGridInterpolator((lats, lons), campo[::-1, :], method="linear",
                                     bounds_error=False, fill_value=None)
    e = C.EXTENT
    flon = np.linspace(e["lon_min"], e["lon_max"], n)
    flat = np.linspace(e["lat_min"], e["lat_max"], int(n * 1.42))
    LON, LAT = np.meshgrid(flon, flat)
    val = interp(np.column_stack([LAT.ravel(), LON.ravel()])).reshape(LON.shape)
    val = np.clip(gaussian_filter(np.nan_to_num(val), sigma=6), 0, None)
    X, Y = merc(LON, LAT)
    return X, Y, val


def _texto_zona(z: dict) -> list[str]:
    dias = z["dias"][:C.MAP_DAYS]
    lineas = []
    for d, nombre in zip(dias, ["Hoy" + (" (resto)" if dias and dias[0]["parcial"] else ""), "Mañana", "Pasado"]):
        mm = d["lluvia_mm"]
        p = d["prob_1mm"]
        ptxt = f" · prob. {p * 100:.0f}%" if p is not None and p == p else ""
        lineas.append(f"{nombre}: {mm:.1f} mm{ptxt}" if mm is not None else f"{nombre}: s/d")
    return lineas


def dibujar(res: dict, meta: dict, ruta_png: str):
    e = C.EXTENT
    fig = plt.figure(figsize=(11, 12.4), dpi=150, facecolor=PAPER)

    # ---------------- encabezado
    fig.text(0.03, 0.972, "GUAYAQUIL", fontsize=25, fontweight="bold", color=INK, va="top")
    fig.text(0.03, 0.937, "Lluvia prevista (rojo) y posible anegamiento de calles (azul)",
             fontsize=13.5, color=INK, va="top")
    fig.text(0.03, 0.913, f"{meta['ventana_texto']}   ·   emitido {meta['emitido_texto']} (hora de Ecuador)",
             fontsize=10.5, color=MUTED, va="top")

    # ---------------- mapa
    ax = fig.add_axes([0.03, 0.075, 0.60, 0.812])
    ax.set_anchor("N")
    xmin, ymin = merc(e["lon_min"], e["lat_min"])
    xmax, ymax = merc(e["lon_max"], e["lat_max"])
    base = mapa_base()
    if base is not None:
        img, ext, atrib = base
        ax.imshow(img, extent=[ext[0], ext[1], ext[2], ext[3]], origin="upper", zorder=0, interpolation="lanczos")
    else:
        ax.set_facecolor("#EEF1F3")
        atrib = ""
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#B9C2CA")

    # lluvia (rojo)
    X, Y, val = _campo_fino(res["campo_mapa"])
    hay_lluvia = float(np.nanmax(val)) >= 1.0
    if hay_lluvia:
        rgba = [matplotlib.colors.to_rgba(c, a) for c, a in zip(LLUVIA_COLORES, LLUVIA_ALFA)]
        cmap = ListedColormap(rgba)
        norm = BoundaryNorm(LLUVIA_NIVELES, cmap.N)
        ax.contourf(X, Y, val, levels=LLUVIA_NIVELES, cmap=cmap, norm=norm, zorder=2, antialiased=True)
        lineas = [v for v in (5, 10, 25, 50, 75, 100, 150, 200) if val.min() < v < val.max()]
        if lineas:
            cs = ax.contour(X, Y, val, levels=lineas, colors=["#9E0F18"], linewidths=0.8, alpha=0.75, zorder=3)
            ax.clabel(cs, fmt="%d mm", fontsize=8, inline=True, colors="#7A0A12")
    else:
        bx, by = merc(-79.94, -2.300)
        ax.text(bx, by, "Sin lluvia ≥ 1 mm prevista en la ciudad\nen este periodo",
                fontsize=10.5, color=INK, ha="center", va="bottom", zorder=6,
                bbox=dict(boxstyle="round,pad=0.5", fc="white", ec="#B9C2CA", alpha=0.92))

    # divisiones de zona
    def linea(lon0, lat0, lon1, lat1):
        a, b = merc(np.array([lon0, lon1]), np.array([lat0, lat1]))
        ax.plot(a, b, ls=(0, (6, 4)), lw=1.3, color=INK, alpha=0.7, zorder=3)
    linea(e["lon_min"], -2.175, e["lon_max"], -2.175)
    linea(-79.95, -2.212, e["lon_max"], -2.212)
    linea(-79.95, -2.175, -79.95, e["lat_min"])

    for nombre, lon, lat in (("NORTE", -80.027, -2.043), ("CENTRO", -80.027, -2.184), ("SUR", -80.027, -2.222)):
        a, b = merc(lon, lat)
        ax.text(a, b, nombre, fontsize=15, fontweight="bold", color=INK, ha="left", va="top", zorder=6,
                bbox=dict(boxstyle="square,pad=0.25", fc="white", ec="none", alpha=0.8))

    # puntos críticos (azul)
    etiquetas, anclas_x, anclas_y = [], [], []
    for p in sorted(res["puntos"], key=lambda q: C.NIVELES_RIESGO.index(q["nivel_mapa"])):
        cx, cy = merc(p["lon"], p["lat"])
        k = 1 / math.cos(math.radians(p["lat"]))  # escala de Mercator
        nivel = p["nivel_mapa"]
        if nivel in NIVEL_COLOR:
            col, alfa = NIVEL_COLOR[nivel]
            ax.add_patch(Circle((cx, cy), 560 * k, fc="white", ec="none", alpha=0.9, zorder=4))
            ax.add_patch(Circle((cx, cy), 470 * k, fc=matplotlib.colors.to_rgba(col, alfa),
                                ec="#0B3D91", lw=1.0, zorder=4))
            etiquetas.append(ax.text(cx + 600 * k, cy, p["nombre"], fontsize=7.6, color="#0B2A5C", va="center",
                                     zorder=5, fontweight="bold",
                                     bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8)))
            anclas_x.append(cx)
            anclas_y.append(cy)
        else:
            ax.add_patch(Circle((cx, cy), 230 * k, fc="white", ec="#6B7785", lw=0.9, alpha=0.9, zorder=4))
    if len(etiquetas) > 1:
        try:
            from adjustText import adjust_text
            adjust_text(etiquetas, x=anclas_x, y=anclas_y, ax=ax, expand=(1.15, 1.4),
                        arrowprops=dict(arrowstyle="-", color="#0B3D91", lw=0.6))
        except Exception as ex:
            print(f"[mapa] etiquetas sin reacomodar: {ex}")

    # escala gráfica 2 km
    sx, sy = merc(-79.872, -2.298)
    k = 1 / math.cos(math.radians(-2.3))
    ax.plot([sx - 2000 * k, sx], [sy, sy], color=INK, lw=2.5, zorder=6, solid_capstyle="butt")
    ax.text(sx - 1000 * k, sy + 250, "2 km", ha="center", va="bottom", fontsize=8.5, color=INK, zorder=6)
    ax.text(xmax - 250, ymin + 250, atrib, ha="right", va="bottom", fontsize=6.5, color=MUTED, zorder=6)

    # ---------------- columna derecha: leyenda + zonas
    _leyenda(fig, hay_lluvia)
    y = 0.69
    for z in ("norte", "centro", "sur"):
        y = _tarjeta_zona(fig, res["zonas"][z], y)

    # ---------------- pie
    fig.text(0.03, 0.058, "\n".join(textwrap.wrap(meta["fuentes_texto"], 165)), fontsize=7.6, color=MUTED,
             va="top", linespacing=1.4)
    fig.text(0.03, 0.020, "Pronóstico orientativo generado automáticamente. Para alertas oficiales consulte "
             "INAMHI y la Secretaría Nacional de Gestión de Riesgos.", fontsize=7.6, color=MUTED, va="top")

    fig.savefig(ruta_png, dpi=150, facecolor=PAPER)
    plt.close(fig)


def _leyenda(fig, hay_lluvia):
    ax = fig.add_axes([0.66, 0.70, 0.32, 0.20])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0, 0.98, "Lluvia acumulada (mm)", fontsize=10, fontweight="bold", color=INK, va="top")
    etiquetas = ["1", "5", "10", "25", "50", "100", "200+"]
    w = 1 / 7
    for i, (c, a) in enumerate(zip(LLUVIA_COLORES, LLUVIA_ALFA)):
        ax.add_patch(plt.Rectangle((i * w, 0.70), w * 0.96, 0.12, fc=matplotlib.colors.to_rgba(c, min(a + 0.2, 1)),
                                   ec="none"))
        ax.text(i * w, 0.66, etiquetas[i], fontsize=7.5, color=MUTED, va="top")
    ax.text(0, 0.47, "Posible anegamiento de calles", fontsize=10, fontweight="bold", color=INK, va="top")
    for i, (nivel, (c, a)) in enumerate(NIVEL_COLOR.items()):
        ax.scatter([0.04 + i * 0.33], [0.25], s=200, c=[matplotlib.colors.to_rgba(c, a)], edgecolors="#0B3D91",
                   linewidths=1)
        ax.text(0.10 + i * 0.33, 0.25, nivel, fontsize=8.5, color=INK, va="center")
    ax.scatter([0.04], [0.05], s=45, facecolors="white", edgecolors="#6B7785", linewidths=0.9)
    ax.text(0.10, 0.05, "Punto crítico vigilado (sin riesgo previsto)", fontsize=8, color=MUTED, va="center")


def _tarjeta_zona(fig, z: dict, y_top: float) -> float:
    alto = 0.193
    ax = fig.add_axes([0.66, y_top - alto, 0.32, alto])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0.0, 0.02), 1.0, 0.96, boxstyle="round,pad=0,rounding_size=0.03",
                                fc="#F3F6F8", ec="#D3DAE0", lw=0.8))
    ax.text(0.05, 0.92, z["nombre"].upper(), fontsize=13, fontweight="bold", color=INK, va="top")
    dias = z["dias"][:C.MAP_DAYS]
    tot = sum(d["lluvia_mm"] or 0 for d in dias)
    riesgo = max((d["riesgo_inundacion"] for d in dias), key=C.NIVELES_RIESGO.index) if dias else "Bajo"
    ax.text(0.95, 0.92, f"{tot:.0f} mm", fontsize=13, fontweight="bold", color="#C4141E", va="top", ha="right")
    yy = 0.74
    for linea in _texto_zona(z):
        ax.text(0.05, yy, linea, fontsize=9, color=INK, va="top")
        yy -= 0.105
    intens = [d["intensidad_max_mmh"] for d in dias if d["intensidad_max_mmh"] is not None]
    if intens:
        ax.text(0.05, yy, f"Intensidad máx.: {max(intens):.1f} mm/h", fontsize=9, color=MUTED, va="top")
    col = NIVEL_COLOR.get(riesgo, ("#9AA5AF", 1))[0]
    ax.add_patch(FancyBboxPatch((0.05, 0.10), 0.9, 0.15, boxstyle="round,pad=0,rounding_size=0.04",
                                fc=matplotlib.colors.to_rgba(col, 0.35 if riesgo != "Bajo" else 0.18), ec="none"))
    ax.text(0.08, 0.175, f"Anegamiento: {riesgo}", fontsize=9.5, fontweight="bold",
            color="#0B2A5C" if riesgo != "Bajo" else MUTED, va="center")
    return y_top - alto - 0.01
