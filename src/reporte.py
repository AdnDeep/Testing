"""Generación del entregable: reporte.html (página), reporte.md (resumen) y reporte.json."""
from __future__ import annotations

import base64
import html
import json
import math

from . import config as C

ESTADOS_ENSO = {
    "el niño advisory": "Aviso de El Niño: El Niño está en curso",
    "el nino advisory": "Aviso de El Niño: El Niño está en curso",
    "el niño watch": "Vigilancia de El Niño: podría formarse en los próximos meses",
    "el nino watch": "Vigilancia de El Niño: podría formarse en los próximos meses",
    "final el niño advisory": "Aviso final de El Niño: el evento terminó",
    "la niña advisory": "Aviso de La Niña: La Niña está en curso",
    "la nina advisory": "Aviso de La Niña: La Niña está en curso",
    "la niña watch": "Vigilancia de La Niña",
    "la nina watch": "Vigilancia de La Niña",
    "final la niña advisory": "Aviso final de La Niña",
    "not active": "Sistema de alerta no activo (condiciones neutras)",
}

E = html.escape


def _pct(p):
    return "–" if p is None or (isinstance(p, float) and math.isnan(p)) else f"{p * 100:.0f}%"


def _mm(v, dec=1):
    return "–" if v is None else f"{v:.{dec}f}"


def _signed(v, dec=1):
    return "–" if v is None else f"{v:+.{dec}f}"


def resumen_zona(z: dict, zid: str | None = None, puntos: list | None = None) -> str:
    dias = z["dias"][:C.MAP_DAYS]
    if not dias:
        return "Sin datos de pronóstico."
    total = sum(d["lluvia_mm"] or 0 for d in dias)
    pico = max(dias, key=lambda d: d["lluvia_mm"] or 0)
    riesgo = max((d["riesgo_inundacion"] for d in dias), key=C.NIVELES_RIESGO.index)
    pmax = max((d["prob_1mm"] for d in dias if d["prob_1mm"] == d["prob_1mm"]), default=float("nan"))
    hasta = dias[-1]["etiqueta"]
    if total < 0.5:
        txt = (f"Sin lluvia significativa prevista hasta el {hasta}. "
               f"Probabilidad máxima de lluvia (≥ 1 mm en un día): {_pct(pmax)}.")
    else:
        txt = (f"{total:.1f} mm esperados en total hasta el {hasta}. "
               f"El día más lluvioso sería el {pico['etiqueta']}: {pico['lluvia_mm']:.1f} mm "
               f"({pico['categoria'].lower()}, probabilidad de lluvia {_pct(pico['prob_1mm'])}).")
    if riesgo != "Bajo" and puntos:
        grupos = []
        for nivel in ("Muy alto", "Alto", "Moderado"):
            nombres = sorted(p["nombre"] for p in puntos if p["zona"] == zid and p["nivel_mapa"] == nivel)
            if nombres:
                grupos.append(f"{nivel.lower()} en {_lista(nombres)}")
        txt += " Riesgo de anegamiento " + "; ".join(grupos) + "."
    elif riesgo != "Bajo":
        txt += f" Riesgo de anegamiento {riesgo.lower()}."
    else:
        txt += " Riesgo de anegamiento de calles: bajo."
    return txt


def _lista(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def _chip_lluvia(cat):
    clase = {"Sin lluvia": "r0", "Llovizna o garúa": "r1", "Lluvia ligera": "r2", "Lluvia moderada": "r3",
             "Lluvia fuerte": "r4", "Lluvia muy fuerte": "r5"}.get(cat, "r0")
    return f'<span class="chip {clase}">{E(cat)}</span>'


def _chip_riesgo(nivel):
    clase = {"Bajo": "f0", "Moderado": "f1", "Alto": "f2", "Muy alto": "f3"}[nivel]
    return f'<span class="chip {clase}">{E(nivel)}</span>'


def _tabla_zona(z):
    filas = []
    for d in z["dias"]:
        rango = f"{d['rango_modelos'][0]:.1f}–{d['rango_modelos'][1]:.1f}" if d["rango_modelos"] else "–"
        pr = d["p10_p50_p90"]
        ens = f"{pr[0]:.0f}–{pr[2]:.0f}" if pr else "–"
        etiqueta = d["etiqueta"] + (" <small>(resto del día)</small>" if d["parcial"] else "")
        pm = d.get("pleamar_max_m")
        clase_pm = next((p["clase"] for p in d.get("pleamares", []) if p["altura"] == pm), "normal")
        marea = (f' <span class="tide" title="Pleamar {E(clase_pm)}">pleamar {pm:.1f} m</span>'
                 if pm is not None and clase_pm != "normal" else "")
        filas.append(
            "<tr>"
            f"<th scope=\"row\">{etiqueta}{marea}</th>"
            f"<td class=\"num strong\">{_mm(d['lluvia_mm'])}</td>"
            f"<td>{_chip_lluvia(d['categoria'])}</td>"
            f"<td class=\"num\">{rango}</td>"
            f"<td class=\"num\">{ens}</td>"
            f"<td class=\"num\">{_pct(d['prob_1mm'])}</td>"
            f"<td class=\"num\">{_pct(d['prob_10mm'])}</td>"
            f"<td class=\"num\">{_pct(d['prob_25mm'])}</td>"
            f"<td class=\"num\">{_mm(d['intensidad_max_mmh'])}</td>"
            f"<td class=\"num\">{_mm(d.get('pleamar_max_m'), 2)}</td>"
            f"<td>{_chip_riesgo(d['riesgo_inundacion'])}</td>"
            "</tr>")
    return (
        '<div class="table-wrap"><table>'
        "<thead><tr><th scope=\"col\">Día</th><th scope=\"col\">Lluvia (mm)</th><th scope=\"col\">Tipo</th>"
        "<th scope=\"col\">Rango modelos</th><th scope=\"col\">Ensamble P10–P90</th>"
        "<th scope=\"col\">Prob. ≥1 mm</th><th scope=\"col\">≥10 mm</th><th scope=\"col\">≥25 mm</th>"
        "<th scope=\"col\">Intens. máx. (mm/h)</th><th scope=\"col\">Pleamar máx. (m)</th>"
        "<th scope=\"col\">Anegamiento</th></tr></thead>"
        f"<tbody>{''.join(filas)}</tbody></table></div>")


def _sparkline(serie):
    if not serie:
        return ""
    vals = [s["anom"] for s in serie]
    lo, hi = min(min(vals), 0.0), max(max(vals), 0.5)
    w, h, pad = 240, 64, 6
    xs = [pad + i * (w - 2 * pad) / max(len(vals) - 1, 1) for i in range(len(vals))]
    ys = [h - pad - (v - lo) / (hi - lo) * (h - 2 * pad) for v in vals]
    y0 = h - pad - (0 - lo) / (hi - lo) * (h - 2 * pad)
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{y0:.1f} " + pts + f" {xs[-1]:.1f},{y0:.1f}"
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" role="img" aria-label="Anomalía Niño 1+2, últimas semanas">'
            f'<line x1="{pad}" x2="{w - pad}" y1="{y0:.1f}" y2="{y0:.1f}" class="spark-zero"/>'
            f'<polygon points="{area}" class="spark-area"/>'
            f'<polyline points="{pts}" class="spark-line"/>'
            f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="3.5" class="spark-dot"/></svg>')


def construir_html(res, meta, enso, estacional, fuentes, png_bytes, hoy_bytes=None, man_bytes=None) -> str:
    img64 = base64.b64encode(png_bytes).decode()
    hoy_html = _seccion_hoy(res, hoy_bytes) + _seccion_hoy(res, man_bytes, "manana")
    obs_html = _seccion_correccion(res) + _seccion_observado(res)
    red_html = _seccion_red()
    mareas_html = _seccion_mareas(res)
    zonas_html = []
    for zid in ("norte", "centro", "sur"):
        z = res["zonas"][zid]
        dias = z["dias"][:C.MAP_DAYS]
        total = sum(d["lluvia_mm"] or 0 for d in dias)
        semana = sum(d["lluvia_mm"] or 0 for d in z["dias"])
        riesgo = max((d["riesgo_inundacion"] for d in dias), key=C.NIVELES_RIESGO.index) if dias else "Bajo"
        ante = z["antecedente_72h_mm"]
        zonas_html.append(f"""
<section class="zone" id="{zid}" aria-labelledby="h-{zid}">
  <div class="zone-head">
    <h2 id="h-{zid}">{E(z['nombre'])}</h2>
    <div class="zone-figs">
      <div><span class="fig rain">{total:.1f}</span><span class="unit">mm hasta pasado mañana</span></div>
      <div><span class="fig">{semana:.0f}</span><span class="unit">mm en 8 días</span></div>
      <div>{_chip_riesgo(riesgo)}<span class="unit">anegamiento</span></div>
    </div>
  </div>
  <p class="sectors">{E(z['sectores'])}</p>
  <p class="summary">{E(resumen_zona(z, zid, res["puntos"]))}</p>
  <p class="note">Lluvia de las últimas 72 h según los modelos: {_mm(ante)} mm{' · suelo probablemente saturado' if ante and ante >= 30 else ''}</p>
  {_tabla_zona(z)}
</section>""")

    # puntos críticos en riesgo
    criticos = [p for p in res["puntos"] if p["nivel_mapa"] != "Bajo"]
    if criticos:
        filas = "".join(
            f"<tr><th scope=\"row\">{E(p['nombre'])}</th><td>{E(C.ZONES[p['zona']]['nombre'])}</td>"
            f"<td>{_chip_riesgo(p['nivel_mapa'])}</td><td>{E(p['fecha_peor'] or '')}</td>"
            f"<td class=\"num\">{p['sus']}/3</td></tr>"
            for p in sorted(criticos, key=lambda p: -C.NIVELES_RIESGO.index(p["nivel_mapa"])))
        puntos_html = ('<div class="table-wrap"><table><thead><tr><th scope="col">Sector</th><th scope="col">Zona</th>'
                       '<th scope="col">Nivel</th><th scope="col">Día más crítico</th><th scope="col">Susceptibilidad</th>'
                       f'</tr></thead><tbody>{filas}</tbody></table></div>')
    else:
        puntos_html = ('<p>Ninguno de los 28 puntos críticos vigilados alcanza riesgo moderado entre hoy y '
                       'pasado mañana.</p>')

    # ENSO
    disc = (enso or {}).get("discusion") or {}
    sem = (enso or {}).get("semanal") or {}
    estado_en = (disc.get("estado") or "").strip()
    estado_es = ESTADOS_ENSO.get(estado_en.lower(), estado_en or "No disponible")
    oni = (enso or {}).get("oni")
    enso_impl = ""
    if res["enso_factor"]:
        enso_impl = ("<p>El mar frente a la costa está más caliente de lo normal. Para Guayaquil eso significa "
                     "aguaceros más intensos y frecuentes, una estación lluviosa que puede adelantarse y un nivel del "
                     "mar más alto, que frena el desagüe de las calles en pleamar. Los modelos ya incluyen la lluvia "
                     "extra; la sobreelevación del mar se suma a la marea en el cálculo de anegamiento.</p>")
    enso_html = f"""
<section class="panel" aria-labelledby="h-enso">
  <h2 id="h-enso">El Niño: seguimiento</h2>
  <div class="enso-grid">
    <div class="metric"><span class="label">Estado NOAA</span><span class="value">{E(estado_es)}</span>
      <span class="sub">{E(estado_en)}{(' · ' + E(disc.get('fecha'))) if disc.get('fecha') else ''}</span></div>
    <div class="metric"><span class="label">Niño 1+2 (frente a Ecuador)</span>
      <span class="value num">{_signed(sem.get('nino12'))} °C</span>
      <span class="sub">semana del {E(sem.get('semana', '–'))}</span>{_sparkline((enso or {}).get('tendencia_nino12'))}</div>
    <div class="metric"><span class="label">Índice costero aprox. (4 semanas)</span>
      <span class="value num">{_signed((enso or {}).get('icen_aprox'), 2)} °C</span>
      <span class="sub">Condición {E((enso or {}).get('clase_costera') or '–')} (umbrales ENFEN)</span></div>
    <div class="metric"><span class="label">Niño 3.4 · ONI</span>
      <span class="value num">{_signed(sem.get('nino34'))} °C · {_signed(oni['anom'] if oni else None)}</span>
      <span class="sub">ONI {E(oni['temporada'] + ' ' + str(oni['anio'])) if oni else '–'}</span></div>
  </div>
  {('<blockquote lang="en">' + E(disc['sinopsis']) + '<cite>NOAA CPC, texto original</cite></blockquote>') if disc.get('sinopsis') else ''}
  {enso_impl}
</section>"""

    # perspectiva estacional
    if estacional:
        filas = "".join(
            f"<tr><th scope=\"row\">{E(m['mes'])}</th><td class=\"num strong\">{m['cfsv2_mm']:.0f}</td>"
            f"<td class=\"num\">{(str(int(m['rango_miembros'][0])) + '–' + str(int(m['rango_miembros'][1]))) if m['rango_miembros'] else '–'}</td>"
            f"<td class=\"num\">{_mm(m['normal_nasa_mm'], 0)}</td>"
            f"<td class=\"num\">{(str(m['porcentaje_normal']) + '%') if m['porcentaje_normal'] is not None else '–'}</td></tr>"
            for m in estacional)
        est_html = ('<section class="panel" aria-labelledby="h-est"><h2 id="h-est">Próximos meses</h2>'
                    '<p>Lluvia mensual en el centro de la ciudad según el modelo estacional NOAA CFSv2 (acoplado '
                    'océano-atmósfera, incorpora El Niño), comparada con la normal de NASA POWER.</p>'
                    '<div class="table-wrap"><table><thead><tr><th scope="col">Mes</th><th scope="col">CFSv2 (mm)</th>'
                    '<th scope="col">Rango miembros</th><th scope="col">Normal NASA (mm)</th><th scope="col">% de la normal</th>'
                    f'</tr></thead><tbody>{filas}</tbody></table></div></section>')
    else:
        est_html = ""

    fuentes_li = "".join(
        f"<li><span class=\"ok-{'si' if f['ok'] else 'no'}\">{'✓' if f['ok'] else '✕'}</span> "
        f"<strong>{E(f['nombre'])}</strong> · {E(f['centro'])}"
        f"{(' · corrida ' + E(f['corrida'])) if f.get('corrida') else ''}"
        f"{(' · peso ' + str(f['peso'])) if f.get('peso') else ''}"
        f"{(' · <em>' + E(f['detalle']) + '</em>') if f.get('detalle') else ''}</li>"
        for f in fuentes)

    titular = meta["titular"]
    return f"""<title>Lluvias Guayaquil</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
{CSS}
</style>
<div class="wrap">
  <header class="top">
    <p class="eyebrow">Agente de pronóstico · Norte, Centro y Sur</p>
    <h1>Lluvias Guayaquil</h1>
    <p class="issued">Emitido el {E(meta['emitido_texto'])} (hora de Ecuador) · {E(meta['ventana_texto'])}</p>
    <p class="headline">{E(titular)}</p>
  </header>

  <figure class="map">
    <img src="data:image/png;base64,{img64}" alt="Mapa de Guayaquil con la lluvia prevista en rojo y los puntos con posible anegamiento de calles en azul">
    <figcaption>Rojo: lluvia acumulada prevista de hoy a pasado mañana (promedio ponderado de modelos). Azul: sectores
    con posible anegamiento de calles. Círculos grises: puntos críticos vigilados sin riesgo previsto.</figcaption>
  </figure>

  {hoy_html}

  <div class="zones">{''.join(zonas_html)}</div>

  <section class="panel" aria-labelledby="h-pts">
    <h2 id="h-pts">Puntos con posible anegamiento</h2>
    {puntos_html}
  </section>

  {obs_html}
  {mareas_html}
  {enso_html}
  {est_html}

  {red_html}

  <section class="panel method" aria-labelledby="h-met">
    <h2 id="h-met">Cómo se calcula</h2>
    <p>La lluvia de cada zona es el promedio ponderado de los modelos de NOAA (EE. UU.) y ECCC (Canadá) disponibles en esta
    corrida. Las medias de los ensambles GEFS y GEPS pesan 1,5 y AIGFS pesa 1, porque a partir del segundo
    día la media de un ensamble acierta más que una corrida única. Las probabilidades salen de contar cuántos de los
    {meta['miembros_total']} miembros de los ensambles superan cada umbral. La intensidad máxima horaria viene de GFS y GEM,
    que no entran en el promedio de lluvia porque son los que más se han alejado de él.</p>
    <p>El riesgo de anegamiento se calcula hora por hora en 28 sectores. Cruza la lluvia de las últimas 3 horas y la
    intensidad con la susceptibilidad de cada sector, y sube un nivel cuando coinciden agravantes: marea alta en el río
    (en los sectores que desaguan al Guayas o al Estero Salado) y suelo saturado (más de 30 mm en 72 h). El riesgo del día
    es el peor de sus horas. El Niño ya está dentro de la lluvia que dan los modelos; además eleva el nivel del mar, por
    eso con un El Niño costero fuerte se suman 0,20 m a la marea (0,10 m si es moderado) al calcular el bloqueo del desagüe. Los modelos globales tienen entre 13 y 28 km de
    resolución: distinguen el norte del sur de la ciudad, pero no una calle de otra.</p>
    <p>La marea se calcula con las 68 constantes armónicas oficiales de INOCAR para Guayaquil-Río. Las horas coinciden
    con las pleamares que publica INOCAR y las alturas están en su misma escala. Es la marea astronómica: no incluye el
    caudal del río ni la sobreelevación del mar por El Niño, que pueden sumar varios centímetros.</p>
    <h3>Fuentes de esta corrida</h3>
    <ul class="sources">{fuentes_li}</ul>
    <p class="fine">Orientativo y automático. Para alertas oficiales: INAMHI (inamhi.gob.ec) y Secretaría Nacional de
    Gestión de Riesgos (gestionderiesgos.gob.ec). Mapa base © OpenStreetMap contributors.</p>
  </section>
</div>
"""


def _seccion_hoy(res, hoy_bytes, clave="hoy") -> str:
    hoy = res.get(clave) or {}
    horas = hoy.get("horas") or []
    if not horas:
        return ""
    img = ""
    if hoy_bytes:
        img = ('<figure class="chart"><img src="data:image/png;base64,' + base64.b64encode(hoy_bytes).decode() +
               f'" alt="Gráfico de {"hoy" if clave == "hoy" else "mañana"} hora por hora: marea del río Guayas y lluvia por zona con riesgo de anegamiento">'
               '<figcaption>Barras rojas: lluvia por hora (más claras: horas que ya pasaron, estimadas por los modelos). '
               'Franjas celestes: marea alta en el río. Franja azul bajo cada zona: riesgo de anegamiento.</figcaption>'
               '</figure>')
    resumen = "".join(
        f'<div class="today-zone"><h3>{E(C.ZONES[z]["nombre"])}</h3><p>{E(hoy["resumen"].get(z) or "")}</p></div>'
        for z in ("norte", "centro", "sur"))
    filas = []
    for h in horas:
        clase = "now" if h["actual"] else ("past" if h["pasada"] else "")
        est = {"sube": "↑ sube", "baja": "↓ baja", "pleamar": "pleamar", "bajamar": "bajamar"}.get(h["marea_estado"], "")
        marea_cls = ["", " tide-mid", " tide-high"][h["marea_clase"]]
        celdas = [f'<th scope="row">{h["hora"]}{" <small>ahora</small>" if h["actual"] else ""}</th>',
                  f'<td class="num{marea_cls}">{_mm(h["marea_m"], 2)}</td><td class="state">{est}</td>']
        for z in ("norte", "centro", "sur"):
            d = h["zonas"][z]
            celdas.append(f'<td class="num">{_mm(d["lluvia_mm"])}</td><td class="num">{_pct(d["prob"])}</td>'
                          f'<td>{_chip_riesgo(d["riesgo"])}</td>')
        filas.append(f'<tr class="{clase}">{"".join(celdas)}</tr>')
    cab = ('<thead><tr><th scope="col" rowspan="2">Hora</th><th scope="colgroup" colspan="2">Marea</th>'
           '<th scope="colgroup" colspan="3">Norte</th><th scope="colgroup" colspan="3">Centro</th>'
           '<th scope="colgroup" colspan="3">Sur</th></tr><tr><th scope="col">m</th><th scope="col">estado</th>'
           + '<th scope="col">mm</th><th scope="col">prob.</th><th scope="col">anegamiento</th>' * 3 + '</tr></thead>')
    return f"""
  <section class="panel today" aria-labelledby="h-{clave}">
    <h2 id="h-{clave}">{'Hoy' if clave == 'hoy' else 'Mañana'}, {E(hoy['etiqueta'])}, hora por hora</h2>
    <div class="today-grid">{resumen}</div>
    {img}
    <div class="table-wrap"><table class="hourly">{cab}<tbody>{''.join(filas)}</tbody></table></div>
    <p class="note">La probabilidad es la proporción de los miembros de los ensambles GEFS y GEPS con al menos 0,5 mm
    entre la hora anterior y la siguiente. Las horas que ya pasaron son estimaciones de los modelos, no mediciones.</p>
  </section>"""


def _seccion_mareas(res) -> str:
    mareas = res.get("mareas") or []
    if not mareas:
        return ""
    u = res.get("marea_umbrales") or {}
    filas = "".join(
        f'<tr class="{"past" if m["pasada"] else ""}"><th scope="row">{E(m["etiqueta"])}</th>'
        f'<td>{"Pleamar" if m["tipo"] == "pleamar" else "Bajamar"}</td><td class="num">{m["hora"]}</td>'
        f'<td class="num strong">{m["altura"]:.2f}</td>'
        f'<td>{E(m["clase"]) if m["tipo"] == "pleamar" else ""}</td></tr>'
        for m in mareas)
    return f"""
  <section class="panel" aria-labelledby="h-mar">
    <h2 id="h-mar">Mareas del río Guayas</h2>
    <p>En pleamar el nivel del río y del Estero Salado sube por encima de muchas salidas de drenaje: el agua de lluvia no
    puede salir y se acumula en las calles bajas. Desde unos {u.get('lento', 3.6):.1f} m el desagüe se vuelve lento y desde
    {u.get('bloqueo', 4.3):.1f} m queda prácticamente bloqueado en el Sur, el Suburbio y las orillas. Con
    {u.get('desborde', 4.8):.1f} m o más, la marea por sí sola puede anegar las orillas más bajas.
    {('Con El Niño actual, el cálculo de riesgo suma ' + f"{res.get('marea_sobreelevacion_enso_m'):.2f}".replace('.', ',') + ' m a estas alturas.') if res.get('marea_sobreelevacion_enso_m') else ''}</p>
    <div class="table-wrap"><table><thead><tr><th scope="col">Día</th><th scope="col">Marea</th><th scope="col">Hora</th>
    <th scope="col">Altura (m)</th><th scope="col">Pleamar</th></tr></thead><tbody>{filas}</tbody></table></div>
    <p class="note">{E(res.get('marea_fuente') or '')}.</p>
  </section>"""


ZONA_TXT = {"norte": "Norte", "centro": "Centro", "sur": "Sur", "duran": "Durán", "oeste": "Vía a la Costa",
            "rural": "Parroquia rural", None: "–"}
TIPO_OBS = {"PVA": "Pluviómetro automático", "EMA": "Estación automática", "EMC": "Estación convencional"}


def _fecha_corta(iso):
    if not iso:
        return "–"
    from datetime import datetime as _dt
    d = _dt.fromisoformat(iso)
    return d.strftime("%d/%m %H:%M")


def resumen_observado(o) -> str:
    c = (o.get("ciudad") or {}).get("obs")
    if not c:
        return "El boletín no trae datos de lluvia."
    txt = (f"Del {_fecha_corta(o['inicio'])} al {_fecha_corta(o['fin'])}: el mayor acumulado fue {c['max_mm']:.1f} mm "
           f"en {c['max_estacion']}; {c['con_lluvia']} de {c['n']} estaciones urbanas midieron 1 mm o más "
           f"(promedio {c['prom_mm']:.1f} mm).")
    m = o["ciudad"].get("modelo_mm")
    if m is not None:
        dif = m - c["prom_mm"]
        if abs(dif) < 1.0:
            txt += f" Los modelos acertaron: estimaron {m:.1f} mm para la ciudad."
        elif dif > 0:
            txt += f" Los modelos estimaron {m:.1f} mm para la ciudad: sobreestimaron {dif:.1f} mm."
        else:
            txt += f" Los modelos estimaron {m:.1f} mm para la ciudad: subestimaron {-dif:.1f} mm."
    return txt


def _seccion_observado(res) -> str:
    o = res.get("observado")
    if not o:
        return ""
    filas_z = ""
    for z in ("norte", "centro", "sur"):
        d = o["zonas"][z]
        ob = d["obs"]
        dif = ""
        if ob and d["modelo_mm"] is not None:
            v = d["modelo_mm"] - ob["prom_mm"]
            dif = f"{v:+.1f}"
        filas_z += (f"<tr><th scope=\"row\">{E(d['nombre'])}</th><td class=\"num\">{ob['n'] if ob else 0}</td>"
                    f"<td class=\"num strong\">{_mm(ob['prom_mm'] if ob else None)}</td>"
                    f"<td class=\"num\">{_mm(ob['max_mm'] if ob else None)}</td>"
                    f"<td>{E(ob['max_estacion']) if ob else '–'}</td>"
                    f"<td class=\"num\">{_mm(d['modelo_mm'])}</td><td class=\"num\">{dif or '–'}</td></tr>")
    tabla_z = ('<div class="table-wrap"><table><thead><tr><th scope="col">Zona</th><th scope="col">Estaciones</th>'
               '<th scope="col">Medido, promedio (mm)</th><th scope="col">Máximo (mm)</th><th scope="col">Dónde</th>'
               '<th scope="col">Modelos (mm)</th><th scope="col">Modelos − medido</th></tr></thead>'
               f'<tbody>{filas_z}</tbody></table></div>')
    est = sorted(o["estaciones"], key=lambda e: (-e["mm"], e["nombre"]))
    filas_e = "".join(
        f"<tr><th scope=\"row\">{E(e['nombre'])}</th><td>{E(TIPO_OBS.get(e['tipo'], e['tipo']))}</td>"
        f"<td>{E(ZONA_TXT.get(e['zona'], '–'))}</td>"
        f"<td class=\"num strong\">{'traza' if e['traza'] else _mm(e['mm'])}</td></tr>" for e in est)
    tabla_e = ('<details><summary>Las ' + str(len(est)) + ' estaciones del boletín</summary>'
               '<div class="table-wrap"><table><thead><tr><th scope="col">Estación</th><th scope="col">Tipo</th>'
               '<th scope="col">Zona</th><th scope="col">Lluvia 24 h (mm)</th></tr></thead>'
               f'<tbody>{filas_e}</tbody></table></div></details>')
    viejo = ""
    if o.get("horas_desde_fin") is not None and o["horas_desde_fin"] > 36:
        viejo = (f'<p class="note">El último boletín publicado cubre hasta hace {o["horas_desde_fin"]} horas; '
                 'el INAMHI no lo publica todos los días.</p>')
    return f"""
  <section class="panel" aria-labelledby="h-obs">
    <h2 id="h-obs">Lluvia medida: boletín del INAMHI</h2>
    <p>{E(resumen_observado(o))}</p>
    {viejo}
    {tabla_z}
    {tabla_e}
    <p class="note">Boletín Nro {E(o.get('numero') or '–')} Guayaquil-Durán, emitido el {E(o.get('emision') or '–')}.
    Red de pluviómetros automáticos de Emapag/Interagua y estaciones del INAMHI, la Aviación Civil y universidades.
    La zona de cada estación se asignó por el sector que indica su nombre; las que no se pueden ubicar con certeza
    cuentan solo en el total de la ciudad. "Modelos" es lo que estimaron los modelos para las mismas 24 horas.</p>
  </section>"""


_EXCLUIR_RED = {"M0619", "M0782", "M0783", "M0780", "M0247", "M1086"}


def _seccion_red() -> str:
    import csv
    import os
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estaciones_inamhi_guayas.csv")
    if not os.path.exists(ruta):
        return ""
    with open(ruta, encoding="utf-8") as fh:
        filas = [r for r in csv.DictReader(fh) if r["codigo"] not in _EXCLUIR_RED]
    cuerpo = "".join(
        f"<tr><td class=\"num\">{E(r['codigo'])}</td><th scope=\"row\">{E(r['nombre'].title())}</th>"
        f"<td>{E(r['tipo_nombre'])}</td><td class=\"num\">{float(r['lat']):.3f}</td>"
        f"<td class=\"num\">{float(r['lon']):.3f}</td></tr>" for r in filas)
    return f"""
  <section class="panel" aria-labelledby="h-red">
    <h2 id="h-red">Red de estaciones del INAMHI en el Guayas</h2>
    <p>{len(filas)} estaciones con pluviómetro de la red nacional, según el último índice publicado (anuarios
    2011 y 2012). No publican sus datos en línea, así que el agente no las usa en el cálculo; quedan como referencia.</p>
    <details><summary>Ver las {len(filas)} estaciones</summary>
    <div class="table-wrap"><table><thead><tr><th scope="col">Código</th><th scope="col">Estación</th>
    <th scope="col">Tipo</th><th scope="col">Latitud</th><th scope="col">Longitud</th></tr></thead>
    <tbody>{cuerpo}</tbody></table></div></details>
    <p class="note">Se omiten Manglaralto, Barcelona, Salanguillo y Colonche (hoy en Santa Elena), Murucumba (coordenadas
    fuera de la provincia) y La Florida (sin coordenadas). La estación Guayaquil Aeropuerto (M0056) es de la Aviación
    Civil y aparece en el boletín como “Aeropuerto (DGAC)”.</p>
  </section>"""


def resumen_correccion(c) -> str:
    if not c or not c.get("ciudad"):
        return "Sin boletines comparables todavía: el pronóstico es el de los modelos, sin corregir."
    ci = c["ciudad"]
    pct = round((ci["factor"] - 1) * 100)
    txt = (f"Pronóstico corregido con {ci['n']} boletín(es) del INAMHI: en esos días la lluvia medida fue "
           f"{ci['razon'] * 100:.0f} % de lo que estimaron los modelos. El pronóstico final es un promedio entre los "
           f"modelos y lo medido (lo medido pesa {ci['peso_medido'] * 100:.0f} %), así que las cantidades de los "
           f"modelos se multiplican por {ci['factor']:.2f} ({pct:+d} %).")
    return txt


def _seccion_correccion(res) -> str:
    c = res.get("correccion")
    if not c:
        return ""
    filas = ""
    if c.get("ciudad"):
        for z in ("norte", "centro", "sur"):
            fz = c["zonas"].get(z) or {}
            crudo = (c.get("sin_corregir") or {}).get(z) or []
            corr = [d["lluvia_mm"] for d in res["zonas"][z]["dias"][:3]]
            def fmt(v):
                return " · ".join(_mm(x) for x in v) if v else "–"
            filas += (f"<tr><th scope=\"row\">{E(C.ZONES[z]['nombre'])}</th>"
                      f"<td class=\"num\">{(fz.get('razon') or 0) * 100:.0f} %</td>"
                      f"<td class=\"num strong\">{fz.get('factor', 1):.2f}</td>"
                      f"<td class=\"num\">{fmt(crudo)}</td><td class=\"num strong\">{fmt(corr)}</td></tr>")
        tabla = ('<div class="table-wrap"><table><thead><tr><th scope="col">Zona</th><th scope="col">Medido / modelos</th>'
                 '<th scope="col">Factor aplicado</th><th scope="col">Modelos: hoy · mañana · pasado (mm)</th>'
                 '<th scope="col">Corregido (mm)</th></tr></thead>' f'<tbody>{filas}</tbody></table></div>')
    else:
        tabla = ""
    return f"""
  <section class="panel" aria-labelledby="h-corr">
    <h2 id="h-corr">Corrección con pluviómetros de Guayaquil</h2>
    <p>{E(resumen_correccion(c))}</p>
    {tabla}
    <p class="note">Factor = 1 + w × (medido/modelos − 1), con w = n / (n + 2) y n = boletines comparados (se usan los
    últimos 20). La razón se limita entre 20 % y 200 %. Todas las cifras de este reporte, mapa y gráficos ya están
    corregidas; la columna "Modelos" muestra lo que habrían dado sin corregir.</p>
  </section>"""


CSS = r"""
/* Layout: una columna de lectura; mapa protagonista; tres zonas en rejilla que se apila en teléfono */
:root {
  --bg: #F2F5F7; --surface: #FFFFFF; --ink: #15212C; --muted: #5A6774; --line: #D6DDE3;
  --rain: #C4141E; --rain-soft: #FBE3E4; --flood: #1F5FBF; --flood-soft: #DCE8F8; --flood-deep: #0B3D91;
  --tide: #6A4FB3;
  --display: "Barlow Semi Condensed", "Arial Narrow", "Helvetica Neue", Arial, sans-serif;
  --body: "Public Sans", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0D141A; --surface: #141E27; --ink: #E3E9EE; --muted: #97A5B1; --line: #273541;
  --rain: #FF6166; --rain-soft: #3A1518; --flood: #78AEF5; --flood-soft: #15284A; --flood-deep: #B3D0FF;
  --tide: #B9A5F2; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #0D141A; --surface: #141E27; --ink: #E3E9EE; --muted: #97A5B1; --line: #273541;
  --rain: #FF6166; --rain-soft: #3A1518; --flood: #78AEF5; --flood-soft: #15284A; --flood-deep: #B3D0FF;
  --tide: #B9A5F2; color-scheme: dark; }
body { background: var(--bg); color: var(--ink); font-family: var(--body); font-size: 15px; line-height: 1.55; }
.wrap { max-width: 1120px; margin: 0 auto; padding-block: 28px 48px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 28px; }
h1, h2, h3 { font-family: var(--display); text-wrap: balance; margin: 0; line-height: 1.1; }
h1 { font-size: clamp(2.4rem, 6vw, 3.6rem); font-weight: 700; letter-spacing: -0.01em; }
h2 { font-size: 1.7rem; font-weight: 700; }
h3 { font-size: 1.15rem; font-weight: 600; margin-top: 8px; }
p { margin: 0; max-width: 68ch; }
.top { display: grid; gap: 6px; }
.eyebrow { font-family: var(--display); text-transform: uppercase; letter-spacing: 0.12em; font-weight: 600;
  color: var(--rain); font-size: 0.9rem; }
.issued { color: var(--muted); font-size: 0.92rem; }
.headline { font-size: 1.12rem; font-weight: 500; margin-top: 6px; max-width: 75ch; }
.map { margin: 0; display: grid; gap: 8px; }
.map img { width: 100%; max-width: 900px; height: auto; border: 1px solid var(--line); border-radius: 6px;
  background: #fff; justify-self: start; }
.map figcaption { color: var(--muted); font-size: 0.88rem; max-width: 900px; }
.zones { display: grid; gap: 28px; }
.zone { display: grid; gap: 10px; min-width: 0; padding-top: 18px; border-top: 3px solid var(--ink); }
.zone-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 12px 24px; }
.zone-head h2 { font-size: 2.1rem; text-transform: uppercase; letter-spacing: 0.04em; }
.zone-figs { display: flex; flex-wrap: wrap; gap: 8px 24px; align-items: baseline; }
.zone-figs > div { display: flex; align-items: baseline; gap: 6px; }
.fig { font-family: var(--display); font-size: 1.9rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.fig.rain { color: var(--rain); }
.unit { color: var(--muted); font-size: 0.85rem; }
.sectors { color: var(--muted); font-size: 0.88rem; }
.summary { font-size: 1.02rem; }
.note { color: var(--muted); font-size: 0.88rem; }
.table-wrap { overflow-x: auto; min-width: 0; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); }
table { border-collapse: collapse; width: 100%; font-size: 0.88rem; }
th, td { padding: 8px 9px; text-align: left; border-bottom: 1px solid var(--line); white-space: nowrap; vertical-align: middle; }
thead th { font-family: var(--display); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em;
  font-size: 0.78rem; color: var(--muted); background: var(--bg); }
tbody th { font-weight: 500; position: sticky; left: 0; background: var(--surface); z-index: 1; }
thead th:first-child { position: sticky; left: 0; z-index: 2; }
tbody tr:last-child th, tbody tr:last-child td { border-bottom: none; }
td.num { font-family: var(--mono); font-variant-numeric: tabular-nums; text-align: right; }
td.strong { font-weight: 500; }
small { color: var(--muted); font-weight: 400; }
.chip { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 0.78rem; font-weight: 600;
  letter-spacing: 0.01em; border: 1px solid transparent; }
.r0 { color: var(--muted); border-color: var(--line); }
.r1, .r2 { color: var(--rain); background: var(--rain-soft); }
.r3 { color: var(--rain); background: var(--rain-soft); border-color: var(--rain); }
.r4 { color: var(--surface); background: var(--rain); }
.r5 { color: var(--surface); background: var(--rain); box-shadow: 0 0 0 2px var(--rain-soft); }
.f0 { color: var(--muted); border-color: var(--line); }
.f1 { color: var(--flood); background: var(--flood-soft); }
.f2 { color: var(--surface); background: var(--flood); }
.f3 { color: var(--surface); background: var(--flood-deep); }
.tide { font-family: var(--display); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--tide); border: 1px solid currentColor; border-radius: 3px; padding: 0 4px; margin-left: 6px; }
.panel { display: grid; gap: 12px; min-width: 0; padding-top: 18px; border-top: 1px solid var(--line); }
.enso-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.metric { display: grid; gap: 4px; align-content: start; padding: 14px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 6px; min-width: 0; }
.metric .label { font-family: var(--display); text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.78rem;
  color: var(--muted); font-weight: 600; }
.metric .value { font-family: var(--display); font-size: 1.35rem; font-weight: 700; line-height: 1.2; }
.metric .value.num { font-variant-numeric: tabular-nums; }
.metric .sub { color: var(--muted); font-size: 0.82rem; }
.spark { width: 100%; max-width: 240px; height: auto; margin-top: 4px; }
.spark-zero { stroke: var(--line); stroke-width: 1; }
.spark-area { fill: var(--rain-soft); }
.spark-line { fill: none; stroke: var(--rain); stroke-width: 2; }
.spark-dot { fill: var(--rain); }
blockquote { margin: 0; padding: 10px 14px; border-left: 3px solid var(--rain); background: var(--surface);
  font-style: italic; max-width: 75ch; }
blockquote cite { display: block; font-style: normal; color: var(--muted); font-size: 0.8rem; margin-top: 4px; }
.sources { margin: 0; padding: 0; list-style: none; display: grid; gap: 6px; font-size: 0.9rem; }
.ok-si { color: #2E8B57; font-weight: 700; }
.ok-no { color: var(--rain); font-weight: 700; }
.fine { color: var(--muted); font-size: 0.82rem; }
.today-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px; }
.today-zone { display: grid; gap: 4px; align-content: start; padding: 12px 14px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 6px; min-width: 0; }
.today-zone h3 { font-size: 1.05rem; text-transform: uppercase; letter-spacing: 0.06em; margin: 0; }
.today-zone p { font-size: 0.92rem; }
.chart { margin: 0; display: grid; gap: 8px; }
.chart img { width: 100%; max-width: 900px; height: auto; border: 1px solid var(--line); border-radius: 6px; background: #fff; }
.chart figcaption { color: var(--muted); font-size: 0.85rem; max-width: 900px; }
table.hourly th, table.hourly td { padding: 6px 8px; }
table.hourly thead tr:first-child th { text-align: center; }
tr.past th, tr.past td { color: var(--muted); }
tr.past .chip { opacity: 0.6; }
tr.now th, tr.now td { background: var(--rain-soft); }
tr.now th { box-shadow: inset 3px 0 0 var(--rain); }
td.state { color: var(--muted); font-size: 0.8rem; }
td.tide-mid { color: var(--flood); font-weight: 500; }
td.tide-high { color: var(--flood-deep); font-weight: 700; }
details { min-width: 0; }
details > summary { cursor: pointer; font-weight: 600; padding: 6px 0; color: var(--flood); }
details > summary:focus-visible { outline: 2px solid var(--flood); outline-offset: 2px; }
details[open] > summary { margin-bottom: 8px; }
@media (min-width: 900px) {
  .zone { grid-template-columns: minmax(0, 1fr); }
}
"""


def construir_md(res, meta, enso) -> str:
    lineas = [f"# Lluvias Guayaquil — {meta['emitido_texto']}", "", meta["titular"], ""]
    hoy = res.get("hoy") or {}
    if hoy.get("horas"):
        lineas.append(f"## Hoy, {hoy['etiqueta']}, hora por hora")
        for z in ("norte", "centro", "sur"):
            lineas.append(f"- **{C.ZONES[z]['nombre']}:** {hoy['resumen'].get(z, '')}")
        lineas.append("")
        lineas.append("| Hora | Marea (m) | Norte mm · aneg. | Centro mm · aneg. | Sur mm · aneg. |")
        lineas.append("|---|---|---|---|---|")
        for h in hoy["horas"]:
            marca = " (ahora)" if h["actual"] else (" (pasó)" if h["pasada"] else "")
            celdas = [f"{_mm(h['zonas'][z]['lluvia_mm'])} · {h['zonas'][z]['riesgo']}" for z in ("norte", "centro", "sur")]
            lineas.append(f"| {h['hora']}{marca} | {_mm(h['marea_m'], 2)} {h['marea_estado']} | " + " | ".join(celdas) + " |")
        lineas.append("")
    man = res.get("manana") or {}
    if man.get("horas"):
        lineas.append(f"## Mañana, {man['etiqueta']}, hora por hora")
        for z in ("norte", "centro", "sur"):
            lineas.append(f"- **{C.ZONES[z]['nombre']}:** {man['resumen'].get(z, '')}")
        lineas.append("")
        lineas.append("| Hora | Marea (m) | Norte mm · aneg. | Centro mm · aneg. | Sur mm · aneg. |")
        lineas.append("|---|---|---|---|---|")
        for h in man["horas"]:
            celdas = [f"{_mm(h['zonas'][z]['lluvia_mm'])} · {h['zonas'][z]['riesgo']}" for z in ("norte", "centro", "sur")]
            lineas.append(f"| {h['hora']} | {_mm(h['marea_m'], 2)} {h['marea_estado']} | " + " | ".join(celdas) + " |")
        lineas.append("")
    lineas.append("## Corrección con pluviómetros")
    lineas.append(resumen_correccion(res.get("correccion")))
    lineas.append("")
    o = res.get("observado")
    if o:
        lineas.append(f"## Lluvia medida (boletín INAMHI {o.get('numero') or ''})")
        lineas.append(resumen_observado(o))
        for z in ("norte", "centro", "sur"):
            d = o["zonas"][z]
            ob = d["obs"]
            lineas.append(f"- {d['nombre']}: medido {_mm(ob['prom_mm'] if ob else None)} mm promedio "
                          f"(máx. {_mm(ob['max_mm'] if ob else None)} en {ob['max_estacion'] if ob else '–'}); "
                          f"modelos {_mm(d['modelo_mm'])} mm")
        lineas.append("")
    if res.get("mareas"):
        lineas.append("## Mareas (INOCAR)")
        for m in res["mareas"]:
            if m["tipo"] == "pleamar":
                lineas.append(f"- Pleamar {m['etiqueta']} {m['hora']}: {m['altura']:.2f} m ({m['clase']})")
        lineas.append("")
    for zid in ("norte", "centro", "sur"):
        z = res["zonas"][zid]
        lineas.append(f"## {z['nombre']}")
        lineas.append(resumen_zona(z, zid, res["puntos"]))
        lineas.append("")
        lineas.append("| Día | Lluvia (mm) | Prob. ≥1 mm | ≥10 mm | Intens. máx (mm/h) | Anegamiento |")
        lineas.append("|---|---|---|---|---|---|")
        for d in z["dias"]:
            lineas.append(f"| {d['etiqueta']}{' (aguaje)' if d['aguaje'] else ''} | {_mm(d['lluvia_mm'])} | "
                          f"{_pct(d['prob_1mm'])} | {_pct(d['prob_10mm'])} | {_mm(d['intensidad_max_mmh'])} | "
                          f"{d['riesgo_inundacion']} |")
        lineas.append("")
    if enso and enso.get("semanal"):
        disc = enso.get("discusion") or {}
        lineas.append("## El Niño")
        lineas.append(f"- Estado NOAA: {disc.get('estado') or 'no disponible'}")
        lineas.append(f"- Niño 1+2 semanal: {enso['semanal']['nino12']:+.1f} °C ({enso['semanal']['semana']}); "
                      f"índice costero aprox.: {enso['icen_aprox']:+.2f} °C → {enso['clase_costera']}")
        lineas.append(f"- Niño 3.4 semanal: {enso['semanal']['nino34']:+.1f} °C")
    return "\n".join(lineas) + "\n"


def _limpiar(o):
    if isinstance(o, float):
        return None if math.isnan(o) else round(o, 3)
    if isinstance(o, dict):
        return {k: _limpiar(v) for k, v in o.items() if k not in ("campo_mapa", "intensidad_mapa")}
    if isinstance(o, (list, tuple)):
        return [_limpiar(v) for v in o]
    if hasattr(o, "tolist"):
        return _limpiar(o.tolist())
    return o


def construir_json(res, meta, enso, estacional, fuentes, clim) -> str:
    return json.dumps(_limpiar({"meta": meta, "hoy": res.get("hoy"), "manana": res.get("manana"),
                                "observado": res.get("observado"), "correccion": res.get("correccion"),
                                "mareas": res.get("mareas"),
                                "marea_umbrales": res.get("marea_umbrales"),
                                "marea_sobreelevacion_enso_m": res.get("marea_sobreelevacion_enso_m"),
                                "zonas": res["zonas"], "puntos": res["puntos"], "enso": enso,
                                "estacional": estacional, "fuentes": fuentes, "climatologia_nasa_mm_dia": clim,
                                "pesos": res["pesos"]}), ensure_ascii=False, indent=1)
