"""Configuración del agente de pronóstico de lluvias para Guayaquil.

Todas las coordenadas son (longitud, latitud) en grados decimales WGS84.
Las ubicaciones de los puntos críticos son aproximadas (centro del sector).
"""

TZ = "America/Guayaquil"
USER_AGENT = "pronostico-lluvias-gye/1.0 (+https://github.com/AdnDeep/pronostico-lluvias-gye)"

# Encuadre del mapa (ciudad de Guayaquil, sin Samborondón ni Durán).
EXTENT = {"lon_min": -80.035, "lon_max": -79.845, "lat_min": -2.305, "lat_max": -2.035}

# Malla de consulta (~4,4 km). Los modelos globales tienen 13–28 km de
# resolución, así que una malla más densa no añade información real.
GRID_LONS = [-80.02, -79.98, -79.94, -79.90, -79.86]
GRID_LATS = [-2.04, -2.08, -2.12, -2.16, -2.20, -2.24, -2.28]

# Zonas: rectángulo (lon_min, lon_max, lat_min, lat_max)
ZONES = {
    "norte": {
        "nombre": "Norte",
        "rect": (-80.035, -79.845, -2.175, -2.035),
        "sectores": "Urdesa, Kennedy, Alborada, Sauces, Samanes, Guayacanes, Mapasingue, "
                    "Prosperina, Bastión Popular, Flor de Bastión, Pascuales, Monte Sinaí",
    },
    "centro": {
        "nombre": "Centro",
        "rect": (-79.950, -79.845, -2.212, -2.175),
        "sectores": "Centro histórico, Las Peñas, Malecón, Barrio Garay, Suburbio Oeste, "
                    "Cristo del Consuelo, Batallón del Suburbio",
    },
    "sur": {
        "nombre": "Sur",
        "rect": (-79.950, -79.845, -2.305, -2.212),
        "sectores": "Centenario, Cuba, La Pradera, La Floresta, Los Esteros, Guasmo, "
                    "Fertisa, Isla Trinitaria, Unión de Bananeros, Puerto Marítimo",
    },
}

# Puntos críticos de anegamiento de calles (ubicación aproximada).
# susceptibilidad: 1 = baja, 2 = media, 3 = alta (zonas bajas, drenaje
# limitado, influencia del estero o de la marea).
HOTSPOTS = [
    # --- Norte ---
    {"nombre": "Pascuales", "zona": "norte", "lon": -79.960, "lat": -2.072, "sus": 3},
    {"nombre": "Flor de Bastión", "zona": "norte", "lon": -79.975, "lat": -2.100, "sus": 3},
    {"nombre": "Bastión Popular", "zona": "norte", "lon": -79.943, "lat": -2.097, "sus": 3},
    {"nombre": "Monte Sinaí", "zona": "norte", "lon": -80.002, "lat": -2.122, "sus": 3},
    {"nombre": "Los Vergeles / Orquídeas", "zona": "norte", "lon": -79.927, "lat": -2.105, "sus": 3},
    {"nombre": "Mucho Lote", "zona": "norte", "lon": -79.903, "lat": -2.086, "sus": 2},
    {"nombre": "Samanes / Guayacanes", "zona": "norte", "lon": -79.899, "lat": -2.114, "sus": 2},
    {"nombre": "Sauces", "zona": "norte", "lon": -79.890, "lat": -2.126, "sus": 2},
    {"nombre": "Alborada", "zona": "norte", "lon": -79.902, "lat": -2.137, "sus": 2},
    {"nombre": "Mapasingue", "zona": "norte", "lon": -79.925, "lat": -2.155, "sus": 2},
    {"nombre": "Prosperina", "zona": "norte", "lon": -79.950, "lat": -2.148, "sus": 2},
    {"nombre": "Urdesa / Kennedy", "zona": "norte", "lon": -79.900, "lat": -2.163, "sus": 1},
    # --- Centro ---
    {"nombre": "Av. Quito y Av. Machala", "zona": "centro", "lon": -79.892, "lat": -2.201, "sus": 2},
    {"nombre": "Barrio Garay", "zona": "centro", "lon": -79.901, "lat": -2.198, "sus": 2},
    {"nombre": "Suburbio Oeste (calle 29)", "zona": "centro", "lon": -79.913, "lat": -2.201, "sus": 3},
    {"nombre": "Batallón del Suburbio", "zona": "centro", "lon": -79.922, "lat": -2.206, "sus": 3},
    {"nombre": "Cristo del Consuelo", "zona": "centro", "lon": -79.916, "lat": -2.211, "sus": 3},
    {"nombre": "Malecón / calle Panamá", "zona": "centro", "lon": -79.879, "lat": -2.190, "sus": 1},
    # --- Sur ---
    {"nombre": "Barrio Centenario", "zona": "sur", "lon": -79.887, "lat": -2.217, "sus": 2},
    {"nombre": "La Pradera", "zona": "sur", "lon": -79.890, "lat": -2.232, "sus": 2},
    {"nombre": "Los Esteros", "zona": "sur", "lon": -79.898, "lat": -2.228, "sus": 2},
    {"nombre": "Isla Trinitaria", "zona": "sur", "lon": -79.922, "lat": -2.238, "sus": 3},
    {"nombre": "La Floresta", "zona": "sur", "lon": -79.884, "lat": -2.245, "sus": 2},
    {"nombre": "Fertisa", "zona": "sur", "lon": -79.902, "lat": -2.259, "sus": 3},
    {"nombre": "Guasmo Norte", "zona": "sur", "lon": -79.881, "lat": -2.252, "sus": 3},
    {"nombre": "Guasmo Central", "zona": "sur", "lon": -79.878, "lat": -2.266, "sus": 3},
    {"nombre": "Guasmo Sur", "zona": "sur", "lon": -79.876, "lat": -2.281, "sus": 3},
    {"nombre": "Unión de Bananeros", "zona": "sur", "lon": -79.890, "lat": -2.286, "sus": 3},
]

# Modelos deterministas (API de pronóstico de Open-Meteo). Todos son de
# centros norteamericanos: NOAA/NCEP (EE. UU.) y ECCC (Canadá).
# peso: contribución al promedio ponderado.
DET_MODELS = [
    {"id": "gfs_seamless", "nombre": "NOAA GFS 0,25°", "centro": "NOAA/NCEP (EE. UU.)", "peso": 1.0, "intensidad": True},
    {"id": "gfs_graphcast025", "nombre": "NOAA GraphCast-GFS (IA)", "centro": "NOAA/NCEP (EE. UU.)", "peso": 1.0, "intensidad": False},
    {"id": "ncep_aigfs025", "nombre": "NOAA AIGFS (IA)", "centro": "NOAA/NCEP (EE. UU.)", "peso": 1.0, "intensidad": False},
    {"id": "gem_global", "nombre": "ECCC GEM Global", "centro": "Environment and Climate Change Canada", "peso": 1.0, "intensidad": True},
]

# Ensambles (API de ensambles de Open-Meteo). Su media pesa más porque,
# pasado el día 2, la media de un ensamble supera a cualquier corrida única.
ENS_MODELS = [
    {"id": "gfs025", "alt_ids": ["ncep_gefs025", "gfs_seamless"], "nombre": "NOAA GEFS (ensamble)", "centro": "NOAA/NCEP (EE. UU.)", "peso": 1.5},
    {"id": "gem_global", "alt_ids": [], "nombre": "ECCC GEPS (ensamble)", "centro": "Environment and Climate Change Canada", "peso": 1.5},
]

SEASONAL_MODEL = {"id": "cfsv2", "nombre": "NOAA CFSv2 (estacional)", "centro": "NOAA/NCEP (EE. UU.)"}

FORECAST_DAYS = 8      # hoy + 7 días
PAST_DAYS = 3          # para lluvia antecedente (suelo saturado)
MAP_DAYS = 3           # hoy, mañana y pasado mañana

# Umbrales de lluvia diaria (mm) para categorías
CATEGORIAS_LLUVIA = [
    (0.5, "Sin lluvia"),
    (2.0, "Llovizna o garúa"),
    (10.0, "Lluvia ligera"),
    (25.0, "Lluvia moderada"),
    (50.0, "Lluvia fuerte"),
    (float("inf"), "Lluvia muy fuerte"),
]

NIVELES_RIESGO = ["Bajo", "Moderado", "Alto", "Muy alto"]

# Umbrales ENFEN (Perú) del Índice Costero El Niño (ICEN, Niño 1+2).
# Se usa la media de las últimas 4 semanas de Niño 1+2 como aproximación.
ICEN_UMBRALES = [
    (3.0, "Cálida extraordinaria"),
    (1.7, "Cálida fuerte"),
    (1.0, "Cálida moderada"),
    (0.4, "Cálida débil"),
    (-1.0, "Neutra"),
    (-1.2, "Fría débil"),
    (-1.4, "Fría moderada"),
    (float("-inf"), "Fría fuerte"),
]
