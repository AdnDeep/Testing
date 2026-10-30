"""Punto de entrada: python -m src.run  → output/latest/{mapa.png, reporte.html, reporte.md, reporte.json}"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import analisis as A
from . import config as C
from . import fetch as F
from . import grafico_hoy as G
from . import mapa as M
from . import marea as MR
from . import reporte as R

SALIDA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
CENTRO = (-79.89, -2.19)

META_DATASETS = {
    "gfs_seamless": "ncep_gfs025", "gfs_graphcast025": "ncep_gfs_graphcast025", "ncep_aigfs025": "ncep_aigfs025",
    "gem_global": "cmc_gem_gdps", "ens:gfs025": "ncep_gefs025", "ens:gem_global": "cmc_gem_geps",
}


def corrida(dataset: str, tz) -> str | None:
    try:
        meta = F._get(f"https://api.open-meteo.com/data/{dataset}/static/meta.json", intentos=1, timeout=20)
        t = datetime.fromtimestamp(meta["last_run_initialisation_time"], tz=timezone.utc)
        if (datetime.now(timezone.utc) - t).total_seconds() > 2 * 86400:
            return None  # metadato desactualizado: no mostrarlo
        return t.strftime("%d/%m %H UTC")
    except Exception:
        return None


def main() -> int:
    tz = ZoneInfo(C.TZ)
    ahora = datetime.now(tz)
    fuentes = []
    base_times, det, ens = None, {}, {}

    for m in C.DET_MODELS:
        try:
            times, arr = None, None
            errores = []
            for mid in [m["id"], *m.get("alt_ids", [])]:
                try:
                    times, arr = F.fetch_deterministic(mid)
                    break
                except F.FuenteNoDisponible as e:
                    errores.append(f"{mid}: {e}")
            if arr is None:
                raise F.FuenteNoDisponible(" | ".join(errores))
            if base_times is None:
                base_times = times
            det[m["id"]] = A.alinear(base_times, times, arr)
            fuentes.append({"id": m["id"], "nombre": m["nombre"], "centro": m["centro"], "peso": m["peso"], "ok": True,
                            "corrida": corrida(META_DATASETS[m["id"]], tz)})
            print(f"[ok] {m['nombre']}")
        except F.FuenteNoDisponible as e:
            fuentes.append({"id": m["id"], "nombre": m["nombre"], "centro": m["centro"], "ok": False,
                            "detalle": "no disponible en esta corrida"})
            print(f"[--] {m['nombre']}: {e}")
        time.sleep(1.5)

    if not det:
        print("ERROR: ningún modelo determinista respondió", file=sys.stderr)
        return 1

    miembros_total = 0
    for m in C.ENS_MODELS:
        try:
            usado, times, arr = F.fetch_ensemble([m["id"], *m["alt_ids"]])
            ens[m["id"]] = A.alinear(base_times, times, arr)
            miembros_total += arr.shape[1]
            fuentes.append({"id": f"ens:{m['id']}", "nombre": f"{m['nombre']} — {arr.shape[1]} miembros",
                            "centro": m["centro"], "peso": m["peso"], "ok": True,
                            "corrida": corrida(META_DATASETS[f"ens:{m['id']}"], tz)})
            print(f"[ok] {m['nombre']} ({usado}, {arr.shape[1]} miembros)")
        except F.FuenteNoDisponible as e:
            fuentes.append({"id": f"ens:{m['id']}", "nombre": m["nombre"], "centro": m["centro"], "ok": False,
                            "detalle": "no disponible en esta corrida"})
            print(f"[--] {m['nombre']}: {e}")
        time.sleep(1.5)

    # ---- ENSO (NOAA CPC)
    semanal = oni = disc = None
    try:
        semanal = F.fetch_cpc_semanal()
        print(f"[ok] CPC semanal: {semanal[-1]}")
    except Exception as e:
        print(f"[--] CPC semanal: {e}")
    try:
        oni = F.fetch_cpc_oni()
        print(f"[ok] ONI: {oni}")
    except Exception as e:
        print(f"[--] ONI: {e}")
    try:
        disc = F.fetch_cpc_discusion()
        print(f"[ok] Discusión ENSO: {disc}")
    except Exception as e:
        print(f"[--] Discusión ENSO: {e}")
    enso = A.analizar_enso(semanal, oni, disc)
    fuentes.append({"id": "cpc", "nombre": "NOAA CPC — índices Niño semanales, ONI y discusión ENSO",
                    "centro": "Climate Prediction Center (EE. UU.)", "ok": bool(semanal or oni or disc)})

    # ---- NASA POWER
    clim = None
    try:
        clim = F.fetch_nasa_climatologia(*CENTRO)
        print(f"[ok] NASA POWER climatología: {clim}")
    except Exception as e:
        print(f"[--] NASA POWER: {e}")
    fuentes.append({"id": "nasa", "nombre": "NASA POWER — climatología mensual de lluvia",
                    "centro": "NASA Langley (EE. UU.)", "ok": clim is not None})

    # ---- Estacional (desactivado si no hay modelo norteamericano disponible)
    estacional = None
    if C.SEASONAL_MODEL:
        try:
            usado, fechas, miembros = F.fetch_seasonal([C.SEASONAL_MODEL["id"], *C.SEASONAL_MODEL.get("alt_ids", [])],
                                                       *CENTRO)
            estacional = A.perspectiva_estacional(fechas, miembros, clim, ahora)
            print(f"[ok] estacional con {usado}: {miembros.shape[0]} miembros")
        except Exception as e:
            print(f"[--] estacional: {e}")
        fuentes.append({"id": "estacional", "nombre": C.SEASONAL_MODEL["nombre"], "centro": C.SEASONAL_MODEL["centro"],
                        "ok": estacional is not None,
                        "detalle": None if estacional else "no disponible en esta corrida"})

    # ---- Marea (INOCAR, constantes armónicas de Guayaquil-Río)
    marea = None
    try:
        hoy0 = ahora.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        marea = MR.predecir(base_times, hoy0, C.FORECAST_DAYS)
        prox = [e for e in marea["extremos"] if e["tipo"] == "pleamar"][:4]
        print("[ok] Marea INOCAR: " + ", ".join(f"{e['hora']:%d/%m %H:%M} {e['altura']:.2f} m" for e in prox))
    except Exception as e:
        print(f"[--] Marea: {e}")
    fuentes.append({"id": "marea", "nombre": "INOCAR — marea astronómica de Guayaquil (río Guayas)",
                    "centro": "Instituto Oceanográfico y Antártico de la Armada (Ecuador)", "ok": marea is not None})

    # ---- análisis
    res = A.analizar(base_times, det, ens, ahora, enso, marea)
    dias = res["dias"]
    ventana = f"de hoy, {dias[0]['etiqueta']}, al {dias[min(C.MAP_DAYS, len(dias)) - 1]['etiqueta']}" if dias else ""
    meta = {
        "emitido_iso": ahora.isoformat(timespec="minutes"),
        "emitido_texto": ahora.strftime("%d/%m/%Y %H:%M"),
        "ventana_texto": ventana[0].upper() + ventana[1:] if ventana else "",
        "miembros_total": miembros_total,
        "modelos_ok": [f["nombre"] for f in fuentes if f["ok"]],
        "titular": titular(res, enso),
        "fuentes_texto": "Modelos: " + ", ".join(f["nombre"] for f in fuentes if f["ok"] and f["id"] not in ("cpc", "nasa", "estacional", "marea"))
                         + " (vía Open-Meteo) · El Niño: NOAA CPC · Normales: NASA POWER · Marea: INOCAR",
    }
    os.makedirs(os.path.join(SALIDA, "latest"), exist_ok=True)
    os.makedirs(os.path.join(SALIDA, "historial"), exist_ok=True)
    png = os.path.join(SALIDA, "latest", "mapa.png")
    M.dibujar(res, meta, png)
    with open(png, "rb") as fh:
        png_bytes = fh.read()
    png_hoy = os.path.join(SALIDA, "latest", "hoy_por_hora.png")
    hoy_bytes = None
    if G.dibujar(res, meta, png_hoy, "hoy"):
        with open(png_hoy, "rb") as fh:
            hoy_bytes = fh.read()
    png_man = os.path.join(SALIDA, "latest", "manana_por_hora.png")
    man_bytes = None
    if G.dibujar(res, meta, png_man, "manana"):
        with open(png_man, "rb") as fh:
            man_bytes = fh.read()

    html_txt = R.construir_html(res, meta, enso, estacional, fuentes, png_bytes, hoy_bytes, man_bytes)
    md_txt = R.construir_md(res, meta, enso)
    js_txt = R.construir_json(res, meta, enso, estacional, fuentes, clim)
    for nombre, txt in (("reporte.html", html_txt), ("reporte.md", md_txt), ("reporte.json", js_txt)):
        with open(os.path.join(SALIDA, "latest", nombre), "w", encoding="utf-8") as fh:
            fh.write(txt)
    with open(os.path.join(SALIDA, "historial", ahora.strftime("%Y-%m-%d_%H%M") + ".json"), "w", encoding="utf-8") as fh:
        fh.write(js_txt)
    print(md_txt)
    return 0


def titular(res, enso) -> str:
    dias = res["dias"][:C.MAP_DAYS]
    if not dias:
        return "Sin datos suficientes para el pronóstico."
    hasta = dias[-1]["etiqueta"]
    tot = {z: sum(d["lluvia_mm"] or 0 for d in res["zonas"][z]["dias"][:C.MAP_DAYS]) for z in ("norte", "centro", "sur")}
    riesgos = {z: max((d["riesgo_inundacion"] for d in res["zonas"][z]["dias"][:C.MAP_DAYS]), key=C.NIVELES_RIESGO.index)
               for z in tot}
    nombres = {z: C.ZONES[z]["nombre"] for z in tot}
    if max(tot.values()) < 1.0:
        txt = f"No se prevé lluvia significativa en Guayaquil hasta el {hasta}."
    else:
        partes = ", ".join(f"{nombres[z]} {tot[z]:.0f} mm" for z in tot)
        txt = f"Lluvia prevista hasta el {hasta}: {partes}."
    peor = max(riesgos, key=lambda z: C.NIVELES_RIESGO.index(riesgos[z]))
    if riesgos[peor] != "Bajo":
        zonas_r = [nombres[z] for z in riesgos if riesgos[z] == riesgos[peor]]
        txt += f" Riesgo de anegamiento {riesgos[peor].lower()} en {R._lista(zonas_r)}."
    else:
        txt += " Riesgo de anegamiento de calles bajo en toda la ciudad."
    ples = [m for m in res.get("mareas", []) if m["tipo"] == "pleamar" and m["fecha"] == res["hoy"]["fecha"]]
    if ples:
        txt += " Pleamares de hoy: " + R._lista([f"{m['hora']} ({m['altura']:.2f} m)" for m in ples]) + "."
    if enso and enso.get("semanal"):
        txt += (f" El Niño costero: Niño 1+2 en {enso['semanal']['nino12']:+.1f} °C "
                f"({(enso.get('clase_costera') or '').lower()}).")
    return txt


if __name__ == "__main__":
    sys.exit(main())
