"""Gráfico de hoy hora por hora: marea del río Guayas y lluvia por zona con riesgo de anegamiento."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from datetime import datetime, timedelta

from . import config as C
from . import marea as MR

INK = "#17222D"
MUTED = "#5B6875"
GRID = "#E3E7EB"
RAIN = "#C4141E"
TIDE = "#1D3A5F"
BAND_LENTO = "#E6EFFA"
BAND_BLOQUEO = "#C9DCF4"
RIESGO = {"Moderado": "#6FA8E8", "Alto": "#2F74C9", "Muy alto": "#0B3D91"}


def dibujar(res: dict, meta: dict, ruta_png: str):
    hoy = res["hoy"]
    horas = hoy["horas"]
    if not horas:
        return False
    xs = list(range(len(horas)))
    marea = [h["marea_m"] for h in horas]
    i_ahora = next((i for i, h in enumerate(horas) if h["actual"]), None)

    fig = plt.figure(figsize=(11, 10.2), dpi=150, facecolor="white")
    fig.text(0.04, 0.975, f"HOY · {hoy['etiqueta'].upper()}", fontsize=19, fontweight="bold", color=INK, va="top")
    fig.text(0.04, 0.945, "Hora por hora: marea del río Guayas y lluvia prevista por zona", fontsize=12.5,
             color=INK, va="top")
    fig.text(0.04, 0.923, f"Emitido {meta['emitido_texto']} (hora de Ecuador) · horas anteriores a la actual: "
             "estimación de los modelos, no medición", fontsize=9.5, color=MUTED, va="top")

    alturas = [1.25, 1, 0.14, 1, 0.14, 1, 0.14]
    gs = fig.add_gridspec(len(alturas), 1, height_ratios=alturas, left=0.10, right=0.83, top=0.885, bottom=0.10,
                          hspace=0.28)
    ax_m = fig.add_subplot(gs[0])
    ejes = [ax_m]

    # ---------------- marea
    clases = [h["marea_clase"] for h in horas]
    if any(m is not None for m in marea):
        # curva fina cada 10 minutos para que pleamar y bajamar caigan sobre la línea
        dia0 = datetime.fromisoformat(hoy["fecha"])
        finos = [dia0 + timedelta(minutes=10 * k) for k in range(24 * 6)]
        nivel_fino = MR.nivel(finos)
        ax_m.plot([k / 6 for k in range(len(finos))], nivel_fino, color=TIDE, lw=2, solid_capstyle="round", zorder=3)
        lo, hi = float(nivel_fino.min()), float(nivel_fino.max())
        ax_m.set_ylim(max(0, lo - 0.9), max(hi + 1.0, MR.NIVEL_BLOQUEO + 0.8))
        sobre = res.get("marea_sobreelevacion_enso_m") or 0.0
        for nivel, txt in ((MR.NIVEL_LENTO, "desagüe lento"), (MR.NIVEL_BLOQUEO, "desagüe bloqueado")):
            ax_m.axhline(nivel - sobre, color=MUTED, lw=0.8, zorder=2)
            ax_m.text(len(horas) - 0.4, nivel - sobre, f" {nivel - sobre:.1f} m: {txt}", fontsize=8, color=MUTED,
                      va="center", ha="left", clip_on=False)
        if sobre:
            ax_m.set_title(f"Marea astronómica, Guayaquil-Río (INOCAR) · umbrales bajados {sobre:.2f} m por El Niño",
                           fontsize=10.5, color=INK, loc="left", pad=6, fontweight="bold")
        for e in res["mareas"]:
            if e["fecha"] != hoy["fecha"]:
                continue
            hh, mm = map(int, e["hora"].split(":"))
            x = hh + mm / 60
            y = e["altura"]
            arriba = e["tipo"] == "pleamar"
            ax_m.plot([x], [y], "o", ms=6, color=TIDE, mec="white", mew=1.5, zorder=4)
            ax_m.annotate(f"{'Pleamar' if arriba else 'Bajamar'} {e['hora']} · {y:.2f} m", (x, y),
                          xytext=(0, 9 if arriba else -10), textcoords="offset points", ha="center",
                          va="bottom" if arriba else "top", fontsize=8.5, color=INK, fontweight="bold",
                          bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85), zorder=8)
    ax_m.set_ylabel("Marea (m)", fontsize=9.5, color=INK)
    if not ax_m.get_title(loc="left"):
        ax_m.set_title("Marea astronómica, Guayaquil-Río (INOCAR)", fontsize=10.5, color=INK, loc="left", pad=6,
                       fontweight="bold")

    # ---------------- lluvia por zona
    ymax = 2.0
    for h in horas:
        for z in h["zonas"].values():
            if z["lluvia_mm"] is not None:
                ymax = max(ymax, z["lluvia_mm"])
    ymax *= 1.25
    for k, zid in enumerate(("norte", "centro", "sur")):
        ax = fig.add_subplot(gs[1 + 2 * k], sharex=ax_m)
        ax_r = fig.add_subplot(gs[2 + 2 * k], sharex=ax_m)
        ejes += [ax, ax_r]
        vals = [h["zonas"][zid]["lluvia_mm"] or 0 for h in horas]
        for i, v in enumerate(vals):
            if v <= 0:
                continue
            ax.bar(i, v, width=0.78, color=RAIN, alpha=0.38 if horas[i]["pasada"] else 1.0, zorder=3)
        futuras = [i for i in xs if not horas[i]["pasada"]]
        if futuras:
            i_max = max(futuras, key=lambda i: vals[i])
            if vals[i_max] >= 0.2:
                ax.text(i_max, vals[i_max] + ymax * 0.03, f"{vals[i_max]:.1f} mm", ha="center", va="bottom",
                        fontsize=8.5, color=INK, fontweight="bold", zorder=5)
        total = sum(vals)
        ax.set_ylim(0, ymax)
        ax.set_ylabel("mm/h", fontsize=9, color=MUTED)
        ax.set_title(f"{C.ZONES[zid]['nombre']} · {total:.1f} mm en el día", fontsize=10.5, color=INK, loc="left",
                     pad=4, fontweight="bold")
        # franja de riesgo
        for i, h in enumerate(horas):
            r = h["zonas"][zid]["riesgo"]
            if r in RIESGO:
                ax_r.add_patch(Rectangle((i - 0.45, 0), 0.9, 1, fc=RIESGO[r], ec="none",
                                         alpha=0.45 if h["pasada"] else 1.0))
            else:
                ax_r.add_patch(Rectangle((i - 0.45, 0.42), 0.9, 0.16, fc="#C3CBD3", ec="none"))
        ax_r.set_ylim(0, 1)
        ax_r.set_yticks([])
        ax_r.set_ylabel("Aneg.", fontsize=8, color=MUTED, rotation=0, ha="right", va="center", labelpad=6)
        for s in ax_r.spines.values():
            s.set_visible(False)

    # ---------------- bandas de marea alta y "ahora" en todos los paneles
    for ax in ejes:
        for i, c in enumerate(clases):
            if c >= 1:
                ax.axvspan(i - 0.5, i + 0.5, color=BAND_BLOQUEO if c >= 2 else BAND_LENTO, zorder=0, lw=0)
        if i_ahora is not None:
            ax.axvline(i_ahora, color=INK, lw=1.1, zorder=6)
        ax.set_xlim(-0.6, len(horas) - 0.4)
        ax.tick_params(axis="both", labelsize=8.5, colors=MUTED, length=0)
        if ax not in [e for e in ejes[2::2]]:
            ax.grid(axis="y", color=GRID, lw=0.8, zorder=1)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            for s in ("left", "bottom"):
                ax.spines[s].set_color(GRID)
        if ax is not ejes[-1]:
            plt.setp(ax.get_xticklabels(), visible=False)
    if i_ahora is not None:
        ax_m.text(i_ahora + 0.15, ax_m.get_ylim()[0] + 0.12, f"ahora {horas[i_ahora]['hora']}", fontsize=8.5,
                  color=INK, va="bottom", ha="left", fontweight="bold", zorder=7,
                  bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))
    ejes[-1].set_xticks(xs[::2])
    ejes[-1].set_xticklabels([horas[i]["hora"][:2] + "h" for i in xs[::2]])

    # ---------------- leyenda
    ly = 0.058
    fig.patches.append(Rectangle((0.10, ly - 0.006), 0.018, 0.012, transform=fig.transFigure, fc=RAIN, ec="none"))
    fig.text(0.122, ly, "Lluvia por hora (más clara: ya pasó)", fontsize=8.5, color=INK, va="center")
    fig.patches.append(Rectangle((0.34, ly - 0.006), 0.018, 0.012, transform=fig.transFigure, fc=BAND_LENTO,
                                 ec=GRID))
    fig.patches.append(Rectangle((0.36, ly - 0.006), 0.018, 0.012, transform=fig.transFigure, fc=BAND_BLOQUEO,
                                 ec=GRID))
    fig.text(0.382, ly, "Marea alta: desagüe lento / bloqueado", fontsize=8.5, color=INK, va="center")
    x0 = 0.62
    for nombre, col in RIESGO.items():
        fig.patches.append(Rectangle((x0, ly - 0.006), 0.018, 0.012, transform=fig.transFigure, fc=col, ec="none"))
        fig.text(x0 + 0.022, ly, nombre, fontsize=8.5, color=INK, va="center")
        x0 += 0.095
    fig.text(0.10, 0.028, "Lluvia: promedio ponderado NOAA GFS, AIGFS, GEFS y ECCC GEM, GEPS (vía Open-Meteo). "
             "Marea: constantes armónicas oficiales de INOCAR. Anegamiento: lluvia de 3 h + intensidad + marea + "
             "susceptibilidad del sector.", fontsize=7.6, color=MUTED, va="center", wrap=True)
    fig.savefig(ruta_png, dpi=150, facecolor="white")
    plt.close(fig)
    return True
