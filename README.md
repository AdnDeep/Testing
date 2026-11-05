# Pronóstico de lluvias · Guayaquil

Agente que reúne pronósticos de lluvia de centros meteorológicos norteamericanos, los promedia y entrega un
reporte para el **Norte, Centro y Sur** de Guayaquil con un mapa de la ciudad: **rojo** donde va a llover y
**azul** donde podría haber anegamiento de calles. Sigue de cerca El Niño con los índices de NOAA.

## Cómo llamarlo

- **Desde Claude:** ejecuta la tarea programada *Agente Lluvias Guayaquil* (botón "Ejecutar ahora") o pídeselo a
  Claude en cualquier chat. El agente dispara este flujo, espera el resultado y publica el reporte con el mapa.
- **Desde GitHub:** pestaña *Actions* → *Pronóstico lluvias Guayaquil* → *Run workflow*.
- **Automático:** corre solo 4 veces al día (≈ 23:35, 05:35, 11:35 y 17:35 hora de Ecuador).

Cada corrida deja en `output/latest/`:

| Archivo | Contenido |
|---|---|
| `mapa.png` | Mapa de Guayaquil: lluvia prevista (rojo), posible anegamiento (azul) y pleamares |
| `hoy_por_hora.png` | Hoy hora por hora: marea del río y lluvia por zona con riesgo de anegamiento |
| `reporte.html` | Reporte completo: hoy hora por hora, 8 días por zona, mareas, El Niño y fuentes |
| `reporte.md` | Resumen en texto |
| `reporte.json` | Todos los números, para análisis |

El historial de corridas (solo JSON) queda en `output/historial/`.

## Fuentes

| Fuente | Centro | Uso |
|---|---|---|
| GFS 0,25° | NOAA/NCEP (EE. UU.) | Solo intensidad horaria; fuera del promedio de lluvia |
| AIGFS | NOAA/NCEP (EE. UU.) | Modelo de IA de NOAA |
| GEM Global | ECCC (Canadá) | Solo intensidad horaria; fuera del promedio de lluvia |
| GEFS, 31 miembros | NOAA/NCEP (EE. UU.) | Media del ensamble y probabilidades |
| GEPS, 21 miembros | ECCC (Canadá) | Media del ensamble y probabilidades |
| Índices Niño semanales, ONI, discusión ENSO | NOAA CPC (EE. UU.) | Seguimiento de El Niño |
| POWER | NASA (EE. UU.) | Normales mensuales de lluvia |
| Constantes armónicas Guayaquil-Río | INOCAR (Ecuador) | Marea del río Guayas hora por hora |
| Boletín diario Guayaquil-Durán | INAMHI (Ecuador) | Lluvia medida en 24 h en 25 estaciones, comparada con los modelos |
| Anuarios meteorológicos 2011–2012 | INAMHI (Ecuador) | Red de 21 estaciones con pluviómetro en el Guayas (`src/estaciones_inamhi_guayas.csv`), como referencia |

Los datos de los modelos se descargan a través de la API pública de [Open-Meteo](https://open-meteo.com).

## Método

1. **Promedio ponderado.** Para cada zona y día se promedia la lluvia de AIGFS (peso 1) y de las medias de GEFS
   y GEPS (peso 1,5 cada una). GFS y GEM quedaron fuera porque son los que más se han alejado del promedio
   general; para volver a incluirlos, basta darles peso en `src/config.py`.
2. **Probabilidades.** Se cuentan los miembros de GEFS y GEPS que superan 1, 10, 25 y 50 mm.
3. **Marea.** Se calcula con las 68 constantes armónicas oficiales de INOCAR para Guayaquil-Río
   (`src/marea_inocar_guayaquil.json`). Las horas coinciden al minuto con las pleamares publicadas por INOCAR
   y las alturas se ajustan +0,19 m a su escala. Desde 3,6 m el desagüe de las calles bajas es lento y desde
   4,3 m queda bloqueado; con 4,8 m o más la marea sola puede anegar orillas bajas.
4. **Riesgo de anegamiento, hora por hora.** En 28 puntos críticos se cruza la lluvia de las últimas 3 horas
   y la intensidad con la susceptibilidad del sector. El riesgo sube un nivel cuando coinciden agravantes:
   marea alta en el río (en sectores que desaguan al Guayas o al Estero Salado) y suelo saturado (más de 30 mm
   en las 72 h previas). El riesgo del día es el peor de sus horas.
5. **Lluvia medida.** Cada corrida descarga el boletín diario Guayaquil-Durán del INAMHI (pluviómetros de
   Emapag/Interagua y estaciones del INAMHI, DGAC y universidades), lee la lluvia de 24 h de cada estación y la
   compara, por zona, con lo que estimaron los modelos para las mismas horas. La zona de cada estación está en
   `ESTACIONES_OBS_ZONA` de `src/config.py`.
6. **Corrección con pluviómetros.** Cada boletín se guarda en `output/historial/boletines.json`. Por zona se
   calcula la razón medido/modelos (limitada entre 0,2 y 2) y el pronóstico final es un promedio entre modelos y
   medición: factor = 1 + w·(razón − 1), con w = n/(n + 2). Con 1 boletín lo medido pesa 33 %; con 8, 80 %.
   Todo el reporte (mapa, gráficos, riesgo) usa las cifras corregidas (`src/correccion.py`).
7. **El Niño.** Los modelos ya usan la temperatura del mar observada, así que la lluvia extra de El Niño está
   dentro de sus números. Además El Niño eleva el nivel del mar: con un El Niño costero fuerte (Niño 1+2 ≥ +1,7 °C,
   umbrales ENFEN) se suman 0,20 m a la marea al calcular el bloqueo del desagüe (0,10 m si es moderado).

Los parámetros (zonas, puntos críticos, pesos, umbrales) están en `src/config.py` y `src/analisis.py`.

## Limitaciones

- Los modelos globales tienen entre 13 y 28 km de resolución: distinguen zonas de la ciudad, no calles.
- La ubicación de los puntos críticos es aproximada.
- Es un pronóstico orientativo. Las alertas oficiales son de INAMHI y la Secretaría Nacional de Gestión de Riesgos.
