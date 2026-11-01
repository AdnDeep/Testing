"""Corrección del pronóstico con los pluviómetros de Guayaquil (boletín diario del INAMHI).

Cada boletín se guarda en output/historial/boletines.json con la lluvia medida y la que estimaron los
modelos para las mismas 24 h. Con ese historial se calcula, por zona, la razón medido / modelos.
El pronóstico corregido es un promedio entre los modelos y esa razón: con pocos boletines pesa más
el modelo; a medida que se acumulan, pesa más lo medido.

    factor = 1 + w · (razón − 1),   w = n / (n + K)
"""
from __future__ import annotations

import json
import os

import numpy as np

from . import config as C
from .analisis import zona_indices

K = 2.0                 # boletines "virtuales" a favor del modelo: con 1 boletín, w = 1/3; con 8, w = 0,8
RAZON_MIN, RAZON_MAX = 0.2, 2.0
MODELO_MIN_MM = 2.0     # un día que los modelos casi no dieron lluvia no informa sobre su sesgo
MAX_BOLETINES = 20      # se usan los más recientes


def ruta_historial(salida: str) -> str:
    return os.path.join(salida, "historial", "boletines.json")


def actualizar_historial(salida: str, observado: dict | None) -> list:
    ruta = ruta_historial(salida)
    hist = []
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as fh:
            hist = json.load(fh)
    if observado and observado.get("numero") and observado.get("comparable"):
        if not any(h["numero"] == observado["numero"] for h in hist):
            hist.append({
                "numero": observado["numero"], "inicio": observado["inicio"], "fin": observado["fin"],
                "ciudad": {"obs": (observado["ciudad"]["obs"] or {}).get("prom_mm"),
                           "modelo": observado["ciudad"]["modelo_mm"]},
                "zonas": {z: {"obs": (v["obs"] or {}).get("prom_mm"), "modelo": v["modelo_mm"]}
                          for z, v in observado["zonas"].items()},
            })
            hist.sort(key=lambda h: h["fin"])
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "w", encoding="utf-8") as fh:
                json.dump(hist, fh, ensure_ascii=False, indent=1)
    return hist


def _razon(pares):
    pares = [(o, m) for o, m in pares if o is not None and m is not None and m >= MODELO_MIN_MM]
    if not pares:
        return None, 0
    r = sum(o for o, _ in pares) / sum(m for _, m in pares)
    return min(max(r, RAZON_MIN), RAZON_MAX), len(pares)


def factores(hist: list) -> dict:
    hist = hist[-MAX_BOLETINES:]
    r_c, n_c = _razon([(h["ciudad"]["obs"], h["ciudad"]["modelo"]) for h in hist])
    out = {"boletines": len(hist), "ciudad": None, "zonas": {}}
    if r_c is not None:
        w = n_c / (n_c + K)
        out["ciudad"] = {"razon": round(r_c, 3), "n": n_c, "peso_medido": round(w, 2), "factor": round(1 + w * (r_c - 1), 3)}
    for z in C.ZONES:
        r, n = _razon([(h["zonas"].get(z, {}).get("obs"), h["zonas"].get(z, {}).get("modelo")) for h in hist])
        if r is None:  # zona sin estaciones ese día: se usa la razón de la ciudad
            out["zonas"][z] = dict(out["ciudad"], fuente="ciudad") if out["ciudad"] else None
            continue
        w = n / (n + K)
        out["zonas"][z] = {"razon": round(r, 3), "n": n, "peso_medido": round(w, 2),
                           "factor": round(1 + w * (r - 1), 3), "fuente": "zona"}
    return out


def factor_por_punto(fac: dict) -> np.ndarray:
    from .fetch import grid_points
    n = len(grid_points())
    base = fac["ciudad"]["factor"] if fac.get("ciudad") else 1.0
    f = np.full(n, base)
    for z, ids in zona_indices().items():
        if fac["zonas"].get(z):
            f[ids] = fac["zonas"][z]["factor"]
    return f


def aplicar(det: dict, ens: dict, fac: dict):
    """Devuelve copias de las series escaladas por el factor de cada punto de la malla."""
    if not fac.get("ciudad"):
        return det, ens
    f = factor_por_punto(fac)
    det2 = {k: v * f[:, None] for k, v in det.items()}
    ens2 = {k: v * f[:, None, None] for k, v in ens.items()}
    return det2, ens2
