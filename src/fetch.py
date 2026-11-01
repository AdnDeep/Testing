"""Descarga de datos: Open-Meteo (modelos NOAA/ECCC), NOAA CPC (ENSO), NASA POWER."""
from __future__ import annotations

import html as _html
import os
import re
import time
from datetime import date, timedelta

import numpy as np
import requests

from . import config as C

SESSION = requests.Session()
SESSION.headers["User-Agent"] = C.USER_AGENT


class FuenteNoDisponible(Exception):
    pass


def _get(url: str, params: dict | None = None, timeout: int = 90, intentos: int = 3, as_json: bool = True):
    ultimo = None
    for i in range(intentos):
        try:
            r = SESSION.get(url, params=params, timeout=timeout)
            if r.status_code == 400:
                # Parámetro o modelo inválido: no tiene sentido reintentar.
                raise FuenteNoDisponible(f"HTTP 400: {r.text[:300]}")
            r.raise_for_status()
            return r.json() if as_json else r.text
        except FuenteNoDisponible:
            raise
        except Exception as e:  # red, 429, 5xx
            ultimo = e
            time.sleep(3 * (i + 1))
    raise FuenteNoDisponible(str(ultimo))


def grid_points():
    """Lista de (lon, lat) de la malla, en orden fila por fila (norte→sur)."""
    return [(lon, lat) for lat in C.GRID_LATS for lon in C.GRID_LONS]


def _coords_params():
    pts = grid_points()
    return {
        "latitude": ",".join(f"{p[1]:.3f}" for p in pts),
        "longitude": ",".join(f"{p[0]:.3f}" for p in pts),
    }


def _as_list(data):
    return data if isinstance(data, list) else [data]


def _to_array(values):
    return np.array([np.nan if v is None else float(v) for v in values], dtype=float)


def fetch_deterministic(model_id: str):
    """Devuelve (times[list[str]], array[npts, nhoras]) de precipitación horaria (mm)."""
    params = {
        **_coords_params(),
        "hourly": "precipitation",
        "models": model_id,
        "timezone": C.TZ,
        "forecast_days": C.FORECAST_DAYS,
        "past_days": C.PAST_DAYS,
    }
    data = _as_list(_get("https://api.open-meteo.com/v1/forecast", params))
    times = data[0]["hourly"]["time"]
    rows = []
    for loc in data:
        h = loc["hourly"]
        key = "precipitation" if "precipitation" in h else next(k for k in h if k.startswith("precipitation"))
        rows.append(_to_array(h[key]))
    arr = np.vstack(rows)
    if np.all(np.isnan(arr)):
        raise FuenteNoDisponible("el modelo no devolvió datos para Guayaquil")
    return times, arr


def fetch_ensemble(model_ids: list[str]):
    """Devuelve (id_usado, times, array[npts, nmiembros, nhoras])."""
    errores = []
    for mid in model_ids:
        params = {
            **_coords_params(),
            "hourly": "precipitation",
            "models": mid,
            "timezone": C.TZ,
            "forecast_days": C.FORECAST_DAYS,
            "past_days": 1,  # para tener las primeras horas de hoy
        }
        try:
            data = _as_list(_get("https://ensemble-api.open-meteo.com/v1/ensemble", params))
        except FuenteNoDisponible as e:
            errores.append(f"{mid}: {e}")
            continue
        times = data[0]["hourly"]["time"]
        per_loc = []
        for loc in data:
            h = loc["hourly"]
            keys = sorted(k for k in h if k == "precipitation" or re.fullmatch(r"precipitation_member\d+", k))
            per_loc.append(np.vstack([_to_array(h[k]) for k in keys]))
        arr = np.stack(per_loc)  # (npts, nmiembros, nhoras)
        if np.all(np.isnan(arr)):
            errores.append(f"{mid}: sin datos")
            continue
        return mid, times, arr
    raise FuenteNoDisponible("; ".join(errores))


def fetch_seasonal(model_ids: list[str], lon: float, lat: float):
    """Pronóstico estacional diario (miembros). Devuelve (id, dates, array[nmiembros, ndias])."""
    errores = []
    for mid in model_ids:
        base = {"latitude": f"{lat:.3f}", "longitude": f"{lon:.3f}", "timezone": C.TZ, "models": mid}
        for extra in ({"daily": "precipitation_sum", "forecast_days": 183}, {"daily": "precipitation_sum"},
                      {"six_hourly": "precipitation", "forecast_days": 183}):
            params = {**base, **extra}
            try:
                data = _get("https://seasonal-api.open-meteo.com/v1/seasonal", params, intentos=2)
            except FuenteNoDisponible as e:
                errores.append(f"{mid} {list(extra)}: {e}")
                continue
            bloque = "daily" if "daily" in extra else "six_hourly"
            d = data.get(bloque) or {}
            keys = sorted(k for k in d if k.startswith("precipitation"))
            if not keys:
                errores.append(f"{mid} {list(extra)}: respuesta sin precipitación ({list(data)[:8]})")
                continue
            arr = np.vstack([_to_array(d[k]) for k in keys])
            times = d["time"]
            if bloque == "six_hourly":  # agregar a días locales
                dias = sorted({t[:10] for t in times})
                pos = {f: i for i, f in enumerate(dias)}
                diario = np.zeros((arr.shape[0], len(dias)))
                for j, t in enumerate(times):
                    diario[:, pos[t[:10]]] += np.nan_to_num(arr[:, j])
                arr, times = diario, dias
            if np.all(np.isnan(arr)):
                errores.append(f"{mid}: sin datos")
                continue
            return mid, times, arr
    raise FuenteNoDisponible(" | ".join(errores))


# ---------------------------------------------------------------- NASA POWER

def fetch_nasa_climatologia(lon: float, lat: float):
    """Climatología mensual de NASA POWER (PRECTOTCORR, mm/día)."""
    url = "https://power.larc.nasa.gov/api/temporal/climatology/point"
    params = {"parameters": "PRECTOTCORR", "community": "AG", "longitude": lon, "latitude": lat, "format": "JSON"}
    data = _get(url, params, timeout=120)
    p = data["properties"]["parameter"]["PRECTOTCORR"]
    meses = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    return {i + 1: float(p[m]) for i, m in enumerate(meses)}


def fetch_nasa_reciente(lon: float, lat: float, dias: int = 10):
    """Lluvia diaria reciente estimada por NASA POWER (puede tener rezago de días)."""
    fin = date.today()
    ini = fin - timedelta(days=dias)
    url = "https://power.larc.nasa.gov/api/temporal/daily/point"
    params = {
        "parameters": "PRECTOTCORR", "community": "AG", "longitude": lon, "latitude": lat,
        "start": ini.strftime("%Y%m%d"), "end": fin.strftime("%Y%m%d"), "format": "JSON",
    }
    data = _get(url, params, timeout=120)
    serie = data["properties"]["parameter"]["PRECTOTCORR"]
    return {k: v for k, v in serie.items() if v is not None and v > -900}


# ---------------------------------------------------------------- NOAA CPC

def fetch_cpc_semanal():
    """Índices semanales de TSM de NOAA CPC (OISST v2.1, base 1991–2020).

    Devuelve lista de dicts {semana, nino12, nino3, nino34, nino4} (anomalías °C).
    """
    txt = _get("https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for", as_json=False)
    filas = []
    for line in txt.splitlines():
        m = re.match(r"\s*(\d{2}[A-Z]{3}\d{4})(.*)", line)
        if not m:
            continue
        nums = re.findall(r"-?\d+\.\d", m.group(2))
        if len(nums) < 8:
            continue
        v = [float(x) for x in nums[:8]]
        filas.append({"semana": m.group(1), "nino12_sst": v[0], "nino12": v[1], "nino3": v[3],
                      "nino34": v[5], "nino4": v[7]})
    if not filas:
        raise FuenteNoDisponible("no se pudo leer wksst9120.for")
    return filas


def fetch_cpc_oni():
    txt = _get("https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt", as_json=False)
    filas = []
    for line in txt.splitlines():
        p = line.split()
        if len(p) == 4 and re.fullmatch(r"[A-Z]{3}", p[0]) and p[1].isdigit():
            filas.append({"temporada": p[0], "anio": int(p[1]), "anom": float(p[3])})
    if not filas:
        raise FuenteNoDisponible("no se pudo leer oni.ascii.txt")
    return filas[-1]


def fetch_cpc_discusion():
    """Estado del Sistema de Alerta ENSO y sinopsis de la discusión mensual de NOAA CPC."""
    html = _get("https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
                as_json=False)
    texto = _html.unescape(re.sub(r"<[^>]+>", " ", html))
    texto = re.sub(r"\s+", " ", texto)
    estado = re.search(r"ENSO Alert System Status:\s*([^.]+?)(?:\s{2,}|Synopsis|$)", texto)
    sinopsis = re.search(r"Synopsis:\s*(.{20,500}?\.)(?=\s+[A-Z]|\s*$)", texto)
    fecha = re.search(r"issued by\s+CLIMATE PREDICTION CENTER.*?(\d{1,2} [A-Z][a-z]+ \d{4})", texto)
    return {
        "estado": estado.group(1).strip() if estado else None,
        "sinopsis": sinopsis.group(1).strip() if sinopsis else None,
        "fecha": fecha.group(1) if fecha else None,
        "url": "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
    }


# ---------------------------------------------------------------- INAMHI: boletín Guayaquil-Durán

def _norm(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", t.replace("ı", "i"))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def leer_boletin_inamhi(texto: str) -> dict:
    """Extrae del texto del boletín (pdftotext -layout) la lluvia de 24 h por estación."""
    import unicodedata
    from datetime import datetime as _dt

    out = {"numero": None, "emision": None, "inicio": None, "fin": None, "estaciones": []}
    m = re.search(r"BOLET\S*N\s+Nro\s+(\d+\s*-\s*\d{4})", texto)
    out["numero"] = m.group(1).replace(" ", "") if m else None
    m = re.search(r"Guayaquil,\s+\w+\s+(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})", texto)
    out["emision"] = m.group(1) if m else None
    m = re.search(r"Desde las (\d{2})h(\d{2}) del (\d{2}-\d{2}-\d{4}) hasta las (\d{2})h(\d{2}) del (\d{2}-\d{2}-\d{4})", texto)
    if m:
        out["inicio"] = _dt.strptime(f"{m.group(3)} {m.group(1)}:{m.group(2)}", "%d-%m-%Y %H:%M").isoformat(timespec="minutes")
        out["fin"] = _dt.strptime(f"{m.group(6)} {m.group(4)}:{m.group(5)}", "%d-%m-%Y %H:%M").isoformat(timespec="minutes")
    a = texto.find("Precipitaci")
    b = texto.find("Tabla 1", a)
    seccion = texto[a:b if b > a else a + 6000]
    vistos = set()
    patron = re.compile(r"(?:(\d{1,2})\.\s+)?\b(PVA|EMA|EMC)\s+(.+?)\s{2,}(\d+[.,]\d+|T)(?=\s|$)")
    for mm in patron.finditer(seccion):
        num, tipo, nombre, valor = mm.groups()
        nombre = re.sub(r"\s+", " ", nombre).strip()
        nombre = unicodedata.normalize("NFC", nombre.replace("\u0131\u0301", "\u00ed").replace("\u0131", "i"))
        if _norm(nombre).startswith("universidad bolivariana"):
            nombre = "Universidad Bolivariana del Ecuador (UBE)"
        clave = _norm(nombre)
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        traza = valor == "T"
        out["estaciones"].append({
            "numero": int(num) if num else None, "tipo": tipo, "nombre": nombre, "clave": clave,
            "mm": 0.0 if traza else float(valor.replace(",", ".")), "traza": traza,
        })
    return out


def fetch_boletin_inamhi() -> dict:
    """Descarga el boletín diario Guayaquil-Durán del INAMHI y lo lee (necesita pdftotext)."""
    import subprocess
    import tempfile

    r = SESSION.get(C.BOLETIN_INAMHI_URL, timeout=120)
    r.raise_for_status()
    if r.content[:4] != b"%PDF":
        raise FuenteNoDisponible("la respuesta no es un PDF")
    with tempfile.TemporaryDirectory() as d:
        pdf = os.path.join(d, "b.pdf")
        txt = os.path.join(d, "b.txt")
        with open(pdf, "wb") as fh:
            fh.write(r.content)
        subprocess.run(["pdftotext", "-layout", pdf, txt], check=True, timeout=60)
        texto = open(txt, encoding="utf-8", errors="replace").read()
    datos = leer_boletin_inamhi(texto)
    datos["publicado"] = r.headers.get("Last-Modified")
    if not datos["estaciones"]:
        raise FuenteNoDisponible("no se encontraron estaciones en el boletín")
    return datos
