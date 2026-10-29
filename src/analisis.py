"""Combinación de modelos, probabilidades por ensamble y riesgo de anegamiento."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np

from . import config as C
from .fetch import grid_points

DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
            "septiembre", "octubre", "noviembre", "diciembre"]


# ------------------------------------------------------------------ utilidades

def categoria_lluvia(mm: float) -> str:
    if mm is None or (isinstance(mm, float) and math.isnan(mm)):
        return "Sin datos"
    for umbral, nombre in C.CATEGORIAS_LLUVIA:
        if mm < umbral:
            return nombre
    return C.CATEGORIAS_LLUVIA[-1][1]


def clasificar_icen(anom: float) -> str:
    for umbral, nombre in C.ICEN_UMBRALES:
        if anom >= umbral:
            return nombre
    return C.ICEN_UMBRALES[-1][1]


def edad_lunar(dt_utc: datetime) -> float:
    """Días desde la luna nueva más reciente (mes sinódico medio)."""
    ref = datetime(2000, 1, 6, 18, 14)  # luna nueva de referencia (UTC)
    dias = (dt_utc - ref).total_seconds() / 86400.0
    return dias % 29.530588853


def es_aguaje(dia_local: datetime) -> tuple[bool, str]:
    """Aguaje (mareas de sicigia): de 1 día antes a 3 días después de luna nueva o llena."""
    edad = edad_lunar(dia_local.replace(hour=17))  # mediodía local ≈ 17:00 UTC
    sinodico = 29.530588853
    llena = sinodico / 2
    for centro, fase in ((0.0, "luna nueva"), (llena, "luna llena"), (sinodico, "luna nueva")):
        delta = edad - centro
        if -1.0 <= delta <= 3.0:
            return True, fase
    return False, ""


def fecha_larga(d: datetime) -> str:
    return f"{DIAS_ES[d.weekday()]} {d.day} de {MESES_ES[d.month - 1]}"


def _in_rect(lon, lat, rect):
    lo0, lo1, la0, la1 = rect
    return lo0 <= lon <= lo1 and la0 <= lat <= la1


def zona_indices():
    pts = grid_points()
    return {z: [i for i, (lon, lat) in enumerate(pts) if _in_rect(lon, lat, cfg["rect"])]
            for z, cfg in C.ZONES.items()}


def _sum_window(series: np.ndarray, idx: list[int]) -> float:
    if not idx:
        return float("nan")
    v = series[..., idx]
    if np.isnan(v).any():
        return float("nan")
    return float(v.sum(axis=-1)) if v.ndim == 1 else v.sum(axis=-1)


def _weighted(vals: dict[str, float], pesos: dict[str, float]):
    ok = {k: v for k, v in vals.items() if v is not None and not math.isnan(v)}
    if not ok:
        return float("nan")
    w = sum(pesos[k] for k in ok)
    return sum(pesos[k] * v for k, v in ok.items()) / w


# ------------------------------------------------------------------ alineación

def alinear(base_times: list[str], times: list[str], arr: np.ndarray) -> np.ndarray:
    """Reubica `arr` (…, nT_src) sobre el eje horario `base_times` (relleno NaN)."""
    pos = {t: i for i, t in enumerate(base_times)}
    out = np.full(arr.shape[:-1] + (len(base_times),), np.nan)
    for j, t in enumerate(times):
        i = pos.get(t)
        if i is not None:
            out[..., i] = arr[..., j]
    return out


# ------------------------------------------------------------------ análisis

def analizar(base_times, det, ens, ahora_local: datetime, enso: dict | None):
    """det: {id: (npts, nT)}; ens: {id: (npts, nmiem, nT)} ya alineados a base_times."""
    tiempos = [datetime.fromisoformat(t) for t in base_times]
    ahora_h = ahora_local.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    hoy = ahora_h.replace(hour=0)

    # Ventanas diarias (día 0 = resto de hoy)
    dias = []
    for d in range(C.FORECAST_DAYS):
        f = hoy + timedelta(days=d)
        idx = [i for i, t in enumerate(tiempos) if t.date() == f.date() and t >= ahora_h]
        if idx:
            dias.append({"fecha": f, "idx": idx})
    idx_pasado = [i for i, t in enumerate(tiempos) if ahora_h - timedelta(hours=72) <= t < ahora_h]

    pesos = {m["id"]: m["peso"] for m in C.DET_MODELS}
    pesos.update({f"ens:{m['id']}": m["peso"] for m in C.ENS_MODELS})
    intensidad_ok = [m["id"] for m in C.DET_MODELS if m["intensidad"] and m["id"] in det]

    # Series por punto de malla por fuente: (npts, nT)
    fuentes_pt = dict(det)
    for eid, arr in ens.items():
        fuentes_pt[f"ens:{eid}"] = np.nanmean(arr, axis=1) if arr.shape[1] else arr[:, 0]

    zidx = zona_indices()
    npts = len(grid_points())

    # ---------- campo por punto y día (promedio ponderado) para el mapa
    campo = np.full((len(dias), npts), np.nan)
    for di, dia in enumerate(dias):
        for p in range(npts):
            vals = {s: _sum_window(a[p], dia["idx"]) for s, a in fuentes_pt.items()}
            campo[di, p] = _weighted(vals, pesos)

    intens_pt = np.full((len(dias), npts), np.nan)
    for di, dia in enumerate(dias):
        if intensidad_ok:
            maxs = [np.nanmax(det[m][:, dia["idx"]], axis=1) for m in intensidad_ok]
            intens_pt[di] = np.nanmean(np.vstack(maxs), axis=0)

    # ---------- factores agravantes globales
    enso_factor = bool(enso and enso.get("icen_aprox") is not None and enso["icen_aprox"] >= 1.0)

    zonas = {}
    for z, cfg in C.ZONES.items():
        ids = zidx[z]
        serie = {s: np.nanmean(a[ids], axis=0) if a.ndim == 2 else None for s, a in fuentes_pt.items()}
        miembros = []
        for eid, arr in ens.items():
            miembros.append(np.nanmean(arr[ids], axis=0))  # (nmiem, nT)
        miembros = np.vstack(miembros) if miembros else np.zeros((0, len(tiempos)))

        antecedente_vals = [float(np.nansum(det[m][ids][:, idx_pasado].mean(axis=0)))
                            for m in det if idx_pasado and not np.isnan(det[m][ids][:, idx_pasado]).all()]
        antecedente = float(np.mean(antecedente_vals)) if antecedente_vals else float("nan")

        filas = []
        for di, dia in enumerate(dias):
            vals = {s: _sum_window(v, dia["idx"]) for s, v in serie.items() if v is not None}
            media = _weighted(vals, pesos)
            validos = [v for v in vals.values() if not math.isnan(v)]
            tot_m = miembros[:, dia["idx"]]
            tot_m = tot_m[~np.isnan(tot_m).any(axis=1)].sum(axis=1) if len(miembros) else np.array([])
            n = len(tot_m)
            prob = (lambda u: float((tot_m >= u).mean()) if n else float("nan"))
            intens = float(np.nanmax(intens_pt[di, ids])) if intensidad_ok else float("nan")
            gfs = serie.get("gfs_seamless")
            horas = int((gfs[dia["idx"]] >= 0.2).sum()) if gfs is not None and not np.isnan(gfs[dia["idx"]]).all() else None
            aguaje, fase = es_aguaje(dia["fecha"])
            filas.append({
                "fecha": dia["fecha"].strftime("%Y-%m-%d"),
                "etiqueta": fecha_larga(dia["fecha"]),
                "parcial": di == 0 and len(dia["idx"]) < 24,
                "horas_ventana": len(dia["idx"]),
                "lluvia_mm": round(media, 1) if not math.isnan(media) else None,
                "categoria": categoria_lluvia(media),
                "rango_modelos": [round(min(validos), 1), round(max(validos), 1)] if validos else None,
                "por_fuente": {s: (round(v, 1) if not math.isnan(v) else None) for s, v in vals.items()},
                "p10_p50_p90": [round(float(np.percentile(tot_m, q)), 1) for q in (10, 50, 90)] if n else None,
                "miembros": n,
                "prob_1mm": prob(1.0), "prob_10mm": prob(10.0), "prob_25mm": prob(25.0), "prob_50mm": prob(50.0),
                "intensidad_max_mmh": round(intens, 1) if not math.isnan(intens) else None,
                "horas_lluvia_gfs": horas,
                "aguaje": aguaje, "fase_lunar": fase,
            })
        zonas[z] = {"nombre": cfg["nombre"], "sectores": cfg["sectores"],
                    "antecedente_72h_mm": round(antecedente, 1) if not math.isnan(antecedente) else None,
                    "dias": filas}

    # ---------- riesgo por punto crítico
    puntos = []
    for h in C.HOTSPOTS:
        w = _pesos_bilineales(h["lon"], h["lat"])
        z = zonas[h["zona"]]
        ante = z["antecedente_72h_mm"] or 0.0
        dias_h = []
        for di, dia in enumerate(dias):
            mm = float(sum(wi * campo[di, pi] for pi, wi in w))
            inten = float(sum(wi * intens_pt[di, pi] for pi, wi in w)) if intensidad_ok else 0.0
            fila_z = z["dias"][di]
            nivel, motivo = nivel_riesgo(mm, inten, h["sus"], fila_z["aguaje"], ante >= 30.0, enso_factor)
            dias_h.append({"fecha": fila_z["fecha"], "lluvia_mm": round(mm, 1),
                           "intensidad_mmh": round(inten, 1), "nivel": nivel, "motivo": motivo})
        ventana = dias_h[:C.MAP_DAYS]
        peor = max(ventana, key=lambda d: C.NIVELES_RIESGO.index(d["nivel"])) if ventana else None
        puntos.append({**h, "dias": dias_h, "nivel_mapa": peor["nivel"] if peor else "Bajo",
                       "fecha_peor": peor["fecha"] if peor else None})

    # Riesgo máximo por zona y día
    for z in zonas:
        for di, fila in enumerate(zonas[z]["dias"]):
            niveles = [p["dias"][di]["nivel"] for p in puntos if p["zona"] == z]
            fila["riesgo_inundacion"] = max(niveles, key=C.NIVELES_RIESGO.index) if niveles else "Bajo"
            fila["puntos_en_riesgo"] = [p["nombre"] for p in puntos if p["zona"] == z
                                        and C.NIVELES_RIESGO.index(p["dias"][di]["nivel"]) >= 1]

    acumulado_mapa = np.nansum(campo[:C.MAP_DAYS], axis=0) if len(dias) else np.zeros(npts)
    return {
        "dias": [{"fecha": d["fecha"].strftime("%Y-%m-%d"), "etiqueta": fecha_larga(d["fecha"])} for d in dias],
        "zonas": zonas,
        "puntos": puntos,
        "campo_mapa": acumulado_mapa.reshape(len(C.GRID_LATS), len(C.GRID_LONS)),
        "intensidad_mapa": np.nanmax(intens_pt[:C.MAP_DAYS], axis=0).reshape(len(C.GRID_LATS), len(C.GRID_LONS))
        if intensidad_ok else None,
        "enso_factor": enso_factor,
        "pesos": pesos,
    }


def _pesos_bilineales(lon, lat):
    """Pesos bilineales sobre la malla para un punto dentro de ella."""
    lons, lats = C.GRID_LONS, C.GRID_LATS  # lats decrecientes
    nlon = len(lons)
    lon = min(max(lon, lons[0]), lons[-1])
    lat = max(min(lat, lats[0]), lats[-1])
    i = max(j for j in range(nlon - 1) if lons[j] <= lon) if lon < lons[-1] else nlon - 2
    k = max(j for j in range(len(lats) - 1) if lats[j] >= lat) if lat > lats[-1] else len(lats) - 2
    tx = (lon - lons[i]) / (lons[i + 1] - lons[i])
    ty = (lats[k] - lat) / (lats[k] - lats[k + 1])
    p = lambda kk, ii: kk * nlon + ii
    return [(p(k, i), (1 - tx) * (1 - ty)), (p(k, i + 1), tx * (1 - ty)),
            (p(k + 1, i), (1 - tx) * ty), (p(k + 1, i + 1), tx * ty)]


# Matriz de riesgo: filas = nivel de lluvia (0–4), columnas = susceptibilidad (1–3)
_MATRIZ = [
    [0, 0, 0],
    [0, 0, 1],
    [1, 1, 2],
    [1, 2, 3],
    [2, 3, 3],
]


def nivel_lluvia(mm_dia: float, mm_hora: float) -> int:
    d = 0
    for i, u in enumerate((15, 30, 50, 80), start=1):
        if mm_dia >= u:
            d = i
    h = 0
    for i, u in enumerate((8, 15, 25, 40), start=1):
        if mm_hora >= u:
            h = i
    return max(d, h)


def nivel_riesgo(mm_dia, mm_hora, sus, aguaje, suelo_saturado, enso_calido):
    mm_dia = 0.0 if mm_dia is None or math.isnan(mm_dia) else mm_dia
    mm_hora = 0.0 if mm_hora is None or math.isnan(mm_hora) else mm_hora
    nl = nivel_lluvia(mm_dia, mm_hora)
    base = _MATRIZ[nl][sus - 1]
    factores = [n for n, ok in (("aguaje", aguaje), ("suelo saturado", suelo_saturado),
                                ("El Niño costero", enso_calido)) if ok]
    sube = nl >= 1 and (len(factores) >= 2 or (factores and nl >= 2))
    nivel = min(base + (1 if sube else 0), 3)
    motivo = f"lluvia nivel {nl}/4, susceptibilidad {sus}/3"
    if sube:
        motivo += " + " + ", ".join(factores)
    return C.NIVELES_RIESGO[nivel], motivo


# ------------------------------------------------------------------ ENSO

def analizar_enso(semanal: list | None, oni: dict | None, disc: dict | None):
    out = {"semanal": None, "icen_aprox": None, "clase_costera": None, "oni": oni, "discusion": disc}
    if semanal:
        ult = semanal[-1]
        ult4 = semanal[-4:]
        icen = sum(f["nino12"] for f in ult4) / len(ult4)
        out.update({
            "semanal": ult,
            "tendencia_nino12": [{"semana": f["semana"], "anom": f["nino12"]} for f in semanal[-8:]],
            "icen_aprox": round(icen, 2),
            "clase_costera": clasificar_icen(icen),
        })
    return out


def perspectiva_estacional(fechas: list[str] | None, miembros: np.ndarray | None, clim: dict | None, hoy: datetime):
    """Lluvia mensual prevista por CFSv2 frente a la normal de NASA POWER."""
    if fechas is None or miembros is None:
        return None
    media = np.nanmean(miembros, axis=0)
    meses = []
    for k in range(1, 4):
        y, m = hoy.year + (hoy.month - 1 + k) // 12, (hoy.month - 1 + k) % 12 + 1
        idx = [i for i, f in enumerate(fechas) if f.startswith(f"{y:04d}-{m:02d}")]
        if len(idx) < 25 or np.isnan(media[idx]).any():
            continue
        total = float(media[idx].sum())
        por_miembro = [float(miembros[j, idx].sum()) for j in range(miembros.shape[0])
                       if not np.isnan(miembros[j, idx]).any()]
        normal = None
        if clim:
            dias_mes = (datetime(y + (m // 12), m % 12 + 1, 1) - datetime(y, m, 1)).days
            normal = clim[m] * dias_mes
        meses.append({
            "mes": f"{MESES_ES[m - 1]} {y}",
            "cfsv2_mm": round(total, 0),
            "rango_miembros": [round(min(por_miembro), 0), round(max(por_miembro), 0)] if por_miembro else None,
            "normal_nasa_mm": round(normal, 0) if normal is not None else None,
            "porcentaje_normal": round(100 * total / normal) if normal else None,
            "miembros": len(por_miembro),
        })
    return meses or None
