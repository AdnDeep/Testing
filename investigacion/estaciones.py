"""Investigación: estaciones con pluviómetro del INAMHI en la provincia del Guayas.

Descarga anuarios meteorológicos, boletines de Guayaquil y el visor hidrometeorológico, y deja
extractos de texto en investigacion/resultados/. No toca el pronóstico.
"""
import json
import os
import re
import subprocess
import urllib.parse

import requests

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
TMP = "/tmp/inv"
os.makedirs(OUT, exist_ok=True)
os.makedirs(TMP, exist_ok=True)
S = requests.Session()
S.headers["User-Agent"] = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0 Safari/537.36")

PDFS = {
    "anuario_2013": ["https://www.inamhi.gob.ec/wp-content/uploads/anuarios/meteorologicos/Am%202013.pdf",
                     "https://www.dundeeprecious.com/site/assets/files/12843/am_2013.pdf"],
    "anuario_2012": ["https://www.inamhi.gob.ec/wp-content/uploads/anuarios/meteorologicos/Am%202012.pdf",
                     "https://dpmmetals.com/site/assets/files/12841/am_2012.pdf"],
    "anuario_2011": ["https://www.inamhi.gob.ec/wp-content/uploads/anuarios/meteorologicos/Am%202011.pdf"],
    "boletin_diario_gye": ["https://www.inamhi.gob.ec/guayaquil/registrodgy.pdf"],
    "boletin_diario_cli_gye": ["https://www.inamhi.gob.ec/guayaquil/bol_dia_cli.pdf"],
    "boletin_mensual_gye": ["https://www.inamhi.gob.ec/guayaquil/bol_men_cli.pdf"],
    "mapa_red_meteorologica": ["https://www.inamhi.gob.ec/docum_institucion/MapasBiblioteca/mapa%20de%20red%20meteorologica%20del%20Ecuador.pdf"],
}

log = {}


def baja(nombre, urls):
    for u in urls:
        try:
            r = S.get(u, timeout=180)
            log[nombre] = {"url": u, "status": r.status_code, "bytes": len(r.content),
                           "last_modified": r.headers.get("Last-Modified")}
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                ruta = os.path.join(TMP, nombre + ".pdf")
                with open(ruta, "wb") as fh:
                    fh.write(r.content)
                return ruta
        except Exception as e:
            log[nombre] = {"url": u, "error": str(e)[:300]}
    return None


def texto(ruta):
    txt = ruta[:-4] + ".txt"
    subprocess.run(["pdftotext", "-layout", ruta, txt], check=False)
    return open(txt, encoding="utf-8", errors="replace").read() if os.path.exists(txt) else ""


for nombre, urls in PDFS.items():
    ruta = baja(nombre, urls)
    if not ruta:
        continue
    t = texto(ruta)
    log[nombre]["chars"] = len(t)
    if nombre.startswith("anuario"):
        lineas = t.splitlines()
        # Líneas del índice de estaciones con provincia GUAYAS
        guayas = [l for l in lineas if re.search(r"\bGUAYAS\b", l, re.I) and re.search(r"M\d{4}", l)]
        with open(os.path.join(OUT, f"{nombre}_guayas.txt"), "w") as fh:
            fh.write("\n".join(guayas) + "\n")
        # Cabecera del índice para entender columnas
        i0 = next((i for i, l in enumerate(lineas) if "NDICE DE ESTACIONES" in l.upper()), None)
        if i0 is not None:
            with open(os.path.join(OUT, f"{nombre}_indice_inicio.txt"), "w") as fh:
                fh.write("\n".join(lineas[i0:i0 + 40]) + "\n")
        log[nombre]["guayas_lineas"] = len(guayas)
    else:
        with open(os.path.join(OUT, f"{nombre}.txt"), "w") as fh:
            fh.write(t[:60000])

# ---------- visor hidrometeorológico: descubrir endpoints
URL_RE = re.compile(r"""(https?://[^\s'"`<>)\\]+|/[A-Za-z0-9_\-./]*(?:api|json|geoserver|wfs|wms|estacion|station|datos)[A-Za-z0-9_\-./?=&]*)""", re.I)
visor = {}
for base in ["https://inamhi.gob.ec/info/", "https://inamhi.gob.ec/ddia/visor/", "https://servicios.inamhi.gob.ec/"]:
    item = {}
    try:
        r = S.get(base, timeout=60)
        item["status"] = r.status_code
        html = r.text
        item["html_head"] = html[:3000]
        scripts = re.findall(r"""<script[^>]+src=["']([^"']+)["']""", html)
        item["scripts"] = scripts
        encontrados = set(URL_RE.findall(html))
        for s in scripts[:15]:
            su = urllib.parse.urljoin(base, s)
            try:
                js = S.get(su, timeout=60).text
                encontrados |= set(URL_RE.findall(js))
                # fragmentos alrededor de palabras clave
                for kw in ("estacion", "station", "precip", "/api", "geoserver", "fetch(", "axios"):
                    for m in list(re.finditer(re.escape(kw), js, re.I))[:8]:
                        item.setdefault("fragmentos", []).append(js[max(0, m.start() - 160): m.end() + 200])
            except Exception as e:
                item.setdefault("errores_js", []).append(f"{su}: {e}"[:200])
        item["urls"] = sorted(u for u in encontrados if len(u) < 300)[:600]
    except Exception as e:
        item["error"] = str(e)[:300]
    visor[base] = item

with open(os.path.join(OUT, "visor_endpoints.json"), "w") as fh:
    json.dump(visor, fh, ensure_ascii=False, indent=1)
with open(os.path.join(OUT, "descargas.json"), "w") as fh:
    json.dump(log, fh, ensure_ascii=False, indent=1)
print(json.dumps(log, ensure_ascii=False, indent=1))
