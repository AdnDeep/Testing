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

def _rolling3(x: np.ndarray) -> np.ndarray:
    """Suma de la hora y las dos anteriores: el agua que se acumula en la calle."""
    out = np.full(x.shape, np.nan)
    for i in range(x.shape[-1]):
        v = x[..., max(0, i - 2): i + 1]
        if not np.isnan(v).all():
            out[..., i] = np.nansum(v, axis=-1)
    return out


def _centrada3(x: np.ndarray) -> np.ndarray:
    """Suma de la hora anterior, la actual y la siguiente."""
    out = np.full(x.shape, np.nan)
    n = x.shape[-1]
    for i in range(n):
        v = x[..., max(0, i - 1): min(n, i + 2)]
        if not np.isnan(v).all():
            out[..., i] = np.nansum(v, axis=-1)
    return out


def _ponderada_horaria(series: dict, pesos: dict) -> np.ndarray:
    """Promedio ponderado hora a hora de varias series (nT,), ignorando las que no tienen dato."""
    claves = [k for k, v in series.items() if v is not None]
    A = np.vstack([series[k] for k in claves])
    W = np.array([pesos[k] for k in claves])[:, None] * (~np.isnan(A))
    den = W.sum(axis=0)
    num = (np.nan_to_num(A) * W).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def _rangos_horas(horas: list[tuple[datetime, str]]) -> str:
    """[(hora, nivel)] consecutivas → '14:00–17:00 (alto), 21:00 (moderado)'."""
    if not horas:
        return ""
    partes, ini, prev, niv = [], horas[0][0], horas[0][0], horas[0][1]
    for t, n in horas[1:] + [(None, None)]:
        if t is not None and t - prev == timedelta(hours=1) and n == niv:
            prev = t
            continue
        txt = ini.strftime("%H:%M") if ini == prev else f"{ini.strftime('%H:%M')}–{(prev + timedelta(hours=1)).strftime('%H:%M')}"
        partes.append(f"{txt} ({niv.lower()})")
        if t is not None:
            ini, prev, niv = t, t, n
    return ", ".join(partes)


def analizar(base_times, det, ens, ahora_local: datetime, enso: dict | None, marea: dict | None = None):
    """det: {id: (npts, nT)}; ens: {id: (npts, nmiem, nT)} ya alineados a base_times."""
    from . import marea as MR

    tiempos = [datetime.fromisoformat(t) for t in base_times]
    nT = len(tiempos)
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
        with np.errstate(invalid="ignore"):
            fuentes_pt[f"ens:{eid}"] = np.nanmean(arr, axis=1)

    zidx = zona_indices()
    npts = len(grid_points())

    # Promedio ponderado hora a hora por punto, e intensidad (GFS/GEM) por punto
    pt_hora = np.vstack([_ponderada_horaria({s: a[p] for s, a in fuentes_pt.items()}, pesos) for p in range(npts)])
    if intensidad_ok:
        with np.errstate(invalid="ignore"):
            int_hora = np.nanmean(np.stack([det[m] for m in intensidad_ok]), axis=0)
    else:
        int_hora = np.zeros((npts, nT))

    # ---------- marea
    if marea is not None:
        nivel_m = np.asarray(marea["horaria"], dtype=float)
        extremos = marea["extremos"]
    else:
        nivel_m = np.full(nT, np.nan)
        extremos = []
    # El Niño eleva el nivel medio del mar frente a Ecuador; se suma al nivel astronómico para el riesgo.
    icen = (enso or {}).get("icen_aprox")
    sobre_m = 0.20 if icen is not None and icen >= 1.7 else (0.10 if icen is not None and icen >= 1.0 else 0.0)
    nivel_ef = nivel_m + sobre_m
    clase_m = np.array([MR.clase_nivel(v) if not math.isnan(v) else 0 for v in nivel_ef])

    def pleamares_de(fecha):
        return [e for e in extremos if e["tipo"] == "pleamar" and e["hora"].date() == fecha.date()]

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
    zona_hora = {}
    zona_prob = {}
    for z, cfg in C.ZONES.items():
        ids = zidx[z]
        with np.errstate(invalid="ignore"):
            serie = {s: np.nanmean(a[ids], axis=0) for s, a in fuentes_pt.items()}
            miembros = [np.nanmean(arr[ids], axis=0) for arr in ens.values()]  # (nmiem, nT)
        miembros = np.vstack(miembros) if miembros else np.zeros((0, nT))
        zona_hora[z] = _ponderada_horaria(serie, pesos)
        if len(miembros):
            c3 = _centrada3(miembros)
            validos = ~np.isnan(c3)
            with np.errstate(invalid="ignore"):
                zona_prob[z] = np.where(validos.sum(axis=0) > 0,
                                        ((c3 >= 0.5) & validos).sum(axis=0) / np.maximum(validos.sum(axis=0), 1),
                                        np.nan)
        else:
            zona_prob[z] = np.full(nT, np.nan)

        antecedente_vals = [float(np.nansum(det[m][ids][:, idx_pasado].mean(axis=0)))
                            for m in det if idx_pasado and not np.isnan(det[m][ids][:, idx_pasado]).all()]
        antecedente = float(np.mean(antecedente_vals)) if antecedente_vals else float("nan")

        filas = []
        for di, dia in enumerate(dias):
            vals = {s: _sum_window(v, dia["idx"]) for s, v in serie.items()}
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
            plea = pleamares_de(dia["fecha"])
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
                "pleamares": [{"hora": e["hora"].strftime("%H:%M"), "altura": e["altura"], "clase": e["clase"]}
                              for e in plea],
                "pleamar_max_m": max((e["altura"] for e in plea), default=None),
            })
        zonas[z] = {"nombre": cfg["nombre"], "sectores": cfg["sectores"],
                    "antecedente_72h_mm": round(antecedente, 1) if not math.isnan(antecedente) else None,
                    "dias": filas}

    # ---------- riesgo por punto crítico (por día y por hora)
    puntos = []
    riesgo_hora = {}  # nombre → array (nT,) de índice de nivel
    for h in C.HOTSPOTS:
        w = _pesos_bilineales(h["lon"], h["lat"])
        z = zonas[h["zona"]]
        ante = z["antecedente_72h_mm"] or 0.0
        sat = ante >= 30.0
        lluvia_h = sum(wi * pt_hora[pi] for pi, wi in w)
        r3 = _rolling3(lluvia_h)
        inten_h = sum(wi * int_hora[pi] for pi, wi in w)
        niv_h = np.zeros(nT, dtype=int)
        mot_h = [""] * nT
        for i in range(nT):
            if math.isnan(r3[i]):
                continue
            niv_h[i], mot_h[i] = nivel_riesgo_horario(r3[i], inten_h[i], h["sus"], h["marea"], int(clase_m[i]),
                                                      nivel_ef[i], sat)
        riesgo_hora[h["nombre"]] = niv_h
        dias_h = []
        for di, dia in enumerate(dias):
            mm = float(sum(wi * campo[di, pi] for pi, wi in w))
            inten = float(sum(wi * intens_pt[di, pi] for pi, wi in w)) if intensidad_ok else 0.0
            fila_z = z["dias"][di]
            marea_alta = (h["marea"] >= 1 and fila_z["pleamar_max_m"] is not None
                          and fila_z["pleamar_max_m"] + sobre_m >= MR.NIVEL_BLOQUEO)
            nivel_d, motivo = nivel_riesgo(mm, inten, h["sus"], marea_alta, sat)
            i_max = max(dia["idx"], key=lambda i: niv_h[i])
            if niv_h[i_max] > C.NIVELES_RIESGO.index(nivel_d):
                nivel_d, motivo = C.NIVELES_RIESGO[niv_h[i_max]], mot_h[i_max]
            hora_critica = tiempos[i_max].strftime("%H:%M") if niv_h[i_max] >= 1 else None
            dias_h.append({"fecha": fila_z["fecha"], "lluvia_mm": round(mm, 1), "intensidad_mmh": round(inten, 1),
                           "nivel": nivel_d, "motivo": motivo, "hora_critica": hora_critica})
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

    # ---------- hoy y mañana, hora por hora
    def por_hora(fecha: datetime, es_hoy: bool) -> dict:
        idx_d = [i for i, t in enumerate(tiempos) if t.date() == fecha.date()]
        horas_d = []
        for i in idx_d:
            fila = {"hora": tiempos[i].strftime("%H:%M"), "pasada": tiempos[i] < ahora_h,
                    "actual": tiempos[i] == ahora_h,
                    "marea_m": None if math.isnan(nivel_m[i]) else round(float(nivel_m[i]), 2),
                    "marea_estado": MR.estado(nivel_m, i) if marea is not None else "",
                    "marea_clase": int(clase_m[i]), "zonas": {}}
            for z in zonas:
                nombres = [p["nombre"] for p in puntos if p["zona"] == z]
                niv = max((riesgo_hora[n][i] for n in nombres), default=0)
                en_riesgo = [n for n in nombres if riesgo_hora[n][i] >= max(niv, 1)]
                ints = (float(np.nanmax(int_hora[zidx[z], i]))
                        if intensidad_ok and not np.isnan(int_hora[zidx[z], i]).all() else None)
                ll = zona_hora[z][i]
                pr = zona_prob[z][i]
                fila["zonas"][z] = {
                    "lluvia_mm": None if math.isnan(ll) else round(float(ll), 1),
                    "prob": None if math.isnan(pr) else round(float(pr), 2),
                    "intensidad_mmh": None if ints is None or math.isnan(ints) else round(ints, 1),
                    "riesgo": C.NIVELES_RIESGO[niv], "sectores": en_riesgo,
                }
            horas_d.append(fila)

        resumen = {}
        for z in zonas:
            serie = zona_hora[z]
            rest = [i for i in idx_d if tiempos[i] >= ahora_h]
            total_dia = float(np.nansum(serie[idx_d])) if idx_d else 0.0
            total_rest = float(np.nansum(serie[rest])) if rest else 0.0
            txt = []
            if rest and total_rest >= 0.5:
                inicios = [i for i in rest if i + 2 <= rest[-1]] or [rest[0]]
                ini = max(inicios, key=lambda i: float(np.nansum(serie[i:min(i + 3, rest[-1] + 1)])))
                fin = min(ini + 2, rest[-1])
                pico = float(np.nansum(serie[ini:fin + 1]))
                if es_hoy:
                    txt.append(f"Quedan {total_rest:.1f} mm para el resto del día (total del día {total_dia:.1f} mm).")
                else:
                    txt.append(f"Total del día: {total_dia:.1f} mm.")
                txt.append(f"Lo más fuerte: entre {tiempos[ini].strftime('%H:%M')} y "
                           f"{(tiempos[fin] + timedelta(hours=1)).strftime('%H:%M')}, con {pico:.1f} mm.")
                if any(clase_m[i] >= 1 for i in range(ini, fin + 1)):
                    txt.append("Ese aguacero coincide con marea alta en el río: el agua de las calles bajas saldrá lento.")
                else:
                    txt.append("Ese momento cae con marea baja o media, lo que ayuda al desagüe.")
            elif rest:
                txt.append(f"Sin lluvia significativa{' para el resto del día' if es_hoy else ''} "
                           f"(total del día {total_dia:.1f} mm).")
            criticas = [(tiempos[i], C.NIVELES_RIESGO[max(riesgo_hora[p['nombre']][i] for p in puntos
                                                          if p['zona'] == z)]) for i in rest]
            criticas = [(t, n) for t, n in criticas if n != "Bajo"]
            if criticas:
                txt.append("Horas con riesgo de anegamiento: " + _rangos_horas(criticas) + ".")
            resumen[z] = " ".join(txt)
        return {"fecha": fecha.strftime("%Y-%m-%d"), "etiqueta": fecha_larga(fecha), "ahora": ahora_h.strftime("%H:%M"),
                "horas": horas_d, "resumen": resumen}

    dia_hoy = por_hora(hoy, True)
    dia_manana = por_hora(hoy + timedelta(days=1), False)

    mareas_ventana = [{"tipo": e["tipo"], "fecha": e["hora"].strftime("%Y-%m-%d"), "etiqueta": fecha_larga(e["hora"]),
                       "hora": e["hora"].strftime("%H:%M"), "altura": e["altura"], "clase": e["clase"],
                       "pasada": e["hora"] < ahora_local.replace(tzinfo=None)}
                      for e in extremos if e["hora"].date() <= (hoy + timedelta(days=C.MAP_DAYS - 1)).date()
                      and e["hora"].date() >= hoy.date()]

    acumulado_mapa = np.nansum(campo[:C.MAP_DAYS], axis=0) if len(dias) else np.zeros(npts)
    return {
        "dias": [{"fecha": d["fecha"].strftime("%Y-%m-%d"), "etiqueta": fecha_larga(d["fecha"])} for d in dias],
        "zonas": zonas,
        "puntos": puntos,
        "hoy": dia_hoy,
        "manana": dia_manana,
        "mareas": mareas_ventana,
        "marea_fuente": marea.get("fuente") if marea else None,
        "marea_sobreelevacion_enso_m": sobre_m,
        "marea_umbrales": marea.get("umbrales") if marea else None,
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


def _nivel_por_umbrales(valor: float, umbrales) -> int:
    n = 0
    for i, u in enumerate(umbrales, start=1):
        if valor >= u:
            n = i
    return n


def nivel_lluvia(mm_dia: float, mm_hora: float) -> int:
    return max(_nivel_por_umbrales(mm_dia, (15, 30, 50, 80)), _nivel_por_umbrales(mm_hora, (8, 15, 25, 40)))


def _combinar(nl: int, sus: int, factores: list[str]) -> int:
    base = _MATRIZ[nl][sus - 1]
    sube = nl >= 1 and (len(factores) >= 2 or (factores and nl >= 2))
    nivel = min(base + (1 if sube else 0), 3)
    # "Muy alto" exige lluvia fuerte, salvo en sectores muy susceptibles con dos o más agravantes
    if nivel == 3 and nl < 3 and not (nl == 2 and sus == 3 and len(factores) >= 2):
        nivel = 2
    return nivel


def nivel_riesgo(mm_dia, mm_hora, sus, marea_alta, suelo_saturado):
    """Riesgo diario. marea_alta: el día tiene una pleamar que bloquea el desagüe del sector."""
    mm_dia = 0.0 if mm_dia is None or math.isnan(mm_dia) else mm_dia
    mm_hora = 0.0 if mm_hora is None or math.isnan(mm_hora) else mm_hora
    nl = nivel_lluvia(mm_dia, mm_hora)
    factores = [n for n, ok in (("marea alta", marea_alta), ("suelo saturado", suelo_saturado)) if ok]
    nivel = _combinar(nl, sus, factores)
    motivo = f"lluvia del día nivel {nl}/4, susceptibilidad {sus}/3"
    if nivel > _MATRIZ[nl][sus - 1]:
        motivo += " + " + ", ".join(factores)
    return C.NIVELES_RIESGO[nivel], motivo


def nivel_riesgo_horario(mm_3h, mm_hora, sus, sens_marea, clase_marea, altura_marea, suelo_saturado):
    """Riesgo en una hora: lluvia acumulada en 3 h + intensidad + marea en ese momento."""
    from . import marea as MR

    mm_3h = 0.0 if mm_3h is None or math.isnan(mm_3h) else mm_3h
    mm_hora = 0.0 if mm_hora is None or math.isnan(mm_hora) else mm_hora
    nl = max(_nivel_por_umbrales(mm_3h, (5, 12, 25, 40)), _nivel_por_umbrales(mm_hora, (8, 15, 25, 40)))
    marea_bloquea = sens_marea * clase_marea >= 2
    factores = [n for n, ok in (("marea alta", marea_bloquea), ("suelo saturado", suelo_saturado)) if ok]
    nivel = _combinar(nl, sus, factores)
    motivo = f"lluvia 3 h nivel {nl}/4, susceptibilidad {sus}/3"
    if nivel > _MATRIZ[nl][sus - 1]:
        motivo += " + " + ", ".join(factores)
    if (nl == 0 and sens_marea == 2 and altura_marea is not None and not math.isnan(altura_marea)
            and altura_marea >= MR.NIVEL_DESBORDE):
        nivel = max(nivel, 1)
        motivo = f"pleamar de {altura_marea:.2f} m en orilla baja"
    return nivel, motivo


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
