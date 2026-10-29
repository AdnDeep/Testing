"""Marea astronómica del río Guayas en Guayaquil a partir de las constantes armónicas oficiales de INOCAR.

Validación (octubre 2026): las horas de pleamar calculadas coinciden al minuto con las anunciadas por
INOCAR (26/10 19:31, 27/10 07:36 y 20:16). Las alturas del análisis armónico quedan 0,19 m por debajo
de las publicadas por INOCAR (diferencia de nivel de referencia), por eso se suma AJUSTE_INOCAR_M.
Con el ajuste: 25/09 INOCAR 4,28 m → 4,29 m; 30/09 4,35 m → 4,38 m.

La predicción es astronómica: no incluye el caudal del río, el viento ni la sobreelevación del mar por
El Niño, que pueden sumar varios centímetros.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import numpy as np
from utide import reconstruct
from utide._ut_constants import ut_constants
from utide.utilities import Bunch

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "marea_inocar_guayaquil.json")
AJUSTE_INOCAR_M = 0.19

# Nivel del río (m, escala INOCAR) a partir del cual el desagüe de las calles bajas se vuelve lento o se
# bloquea. En 2026 la mediana de las pleamares es 4,36 m y el 10 % supera 4,81 m.
NIVEL_LENTO = 3.6
NIVEL_BLOQUEO = 4.3
NIVEL_DESBORDE = 4.8  # pleamar que por sí sola puede anegar orillas bajas

# Clasificación de cada pleamar
CLASES_PLEAMAR = [(5.0, "extraordinaria"), (4.7, "muy alta"), (4.4, "alta (aguaje)"), (float("-inf"), "normal")]


def _coef():
    with open(RUTA, encoding="utf-8") as fh:
        d = json.load(fh)
    const = ut_constants.const
    nombres = [n.strip() for n in const.name]
    usar = [c for c in d["constituyentes"] if c[0] in nombres]
    lind = np.array([nombres.index(c[0]) for c in usar])
    return Bunch(
        name=np.array([c[0] for c in usar]), A=np.array([c[1] for c in usar]) / 100.0,
        g=np.array([c[2] for c in usar]), A_ci=np.zeros(len(usar)), g_ci=np.zeros(len(usar)),
        mean=d["z0_cm"] / 100.0, slope=0.0,
        aux=Bunch(reftime=0.0, lat=-2.2, frq=const.freq[lind], lind=lind,
                  opt=Bunch(twodim=False, nodsatlint=False, nodsatnone=False, gwchlint=False, gwchnone=False,
                            notrend=True, prefilt=[], nodiagn=True)))


_COEF = None


def nivel(tiempos_locales) -> np.ndarray:
    """Altura de la marea (m, escala INOCAR) para horas locales de Ecuador (datetime sin zona)."""
    global _COEF
    if _COEF is None:
        _COEF = _coef()
    # Las fases de INOCAR están referidas a la hora local (UTC-5): se pasan las horas locales tal cual.
    t = np.array([x.replace(tzinfo=None) for x in tiempos_locales])
    return reconstruct(t, _COEF, verbose=False).h + AJUSTE_INOCAR_M


def clase_pleamar(altura: float) -> str:
    for umbral, nombre in CLASES_PLEAMAR:
        if altura >= umbral:
            return nombre
    return "normal"


def clase_nivel(altura: float) -> int:
    """0 = drenaje libre, 1 = drenaje lento, 2 = drenaje bloqueado en zonas bajas."""
    if altura >= NIVEL_BLOQUEO:
        return 2
    if altura >= NIVEL_LENTO:
        return 1
    return 0


def extremos(inicio: datetime, fin: datetime) -> list[dict]:
    paso = 5
    n = int((fin - inicio).total_seconds() // (paso * 60)) + 1
    ts = [inicio + timedelta(minutes=paso * i) for i in range(n)]
    h = nivel(ts)
    out = []
    for i in range(1, n - 1):
        if h[i] > h[i - 1] and h[i] >= h[i + 1]:
            out.append({"tipo": "pleamar", "hora": ts[i], "altura": round(float(h[i]), 2),
                        "clase": clase_pleamar(float(h[i]))})
        elif h[i] < h[i - 1] and h[i] <= h[i + 1]:
            out.append({"tipo": "bajamar", "hora": ts[i], "altura": round(float(h[i]), 2), "clase": ""})
    return out


def predecir(base_times: list[str], hoy: datetime, dias: int) -> dict:
    tiempos = [datetime.fromisoformat(t) for t in base_times]
    horaria = nivel(tiempos)
    ext = extremos(hoy - timedelta(hours=1), hoy + timedelta(days=dias, hours=1))
    return {
        "horaria": horaria,
        "extremos": ext,
        "umbrales": {"lento": NIVEL_LENTO, "bloqueo": NIVEL_BLOQUEO, "desborde": NIVEL_DESBORDE},
        "fuente": "INOCAR — constantes armónicas Guayaquil-Río (análisis de 2020), ajuste +0,19 m a la escala "
                  "de las tablas publicadas",
    }


def estado(horaria: np.ndarray, i: int) -> str:
    if i <= 0 or i >= len(horaria) - 1:
        return ""
    if horaria[i] >= horaria[i - 1] and horaria[i] >= horaria[i + 1]:
        return "pleamar"
    if horaria[i] <= horaria[i - 1] and horaria[i] <= horaria[i + 1]:
        return "bajamar"
    return "sube" if horaria[i + 1] > horaria[i] else "baja"
