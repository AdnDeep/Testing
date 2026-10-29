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
| GFS 0,25° | NOAA/NCEP (EE. UU.) | Modelo determinista, intensidad horaria |
| AIGFS | NOAA/NCEP (EE. UU.) | Modelo de IA de NOAA |
| GEM Global | ECCC (Canadá) | Modelo determinista, intensidad |
| GEFS, 31 miembros | NOAA/NCEP (EE. UU.) | Media del ensamble y probabilidades |
| GEPS, 21 miembros | ECCC (Canadá) | Media del ensamble y probabilidades |
| Índices Niño semanales, ONI, discusión ENSO | NOAA CPC (EE. UU.) | Seguimiento de El Niño |
| POWER | NASA (EE. UU.) | Normales mensuales de lluvia |
| Constantes armónicas Guayaquil-Río | INOCAR (Ecuador) | Marea del río Guayas hora por hora |

Los datos de los modelos se descargan a través de la API pública de [Open-Meteo](https://open-meteo.com).

## Método

1. **Promedio ponderado.** Para cada zona y día se promedia la lluvia de todos los modelos disponibles. Cada
   modelo determinista pesa 1 y cada media de ensamble pesa 1,5.
2. **Probabilidades.** Se cuentan los miembros de GEFS y GEPS que superan 1, 10, 25 y 50 mm.
3. **Marea.** Se calcula con las 68 constantes armónicas oficiales de INOCAR para Guayaquil-Río
   (`src/marea_inocar_guayaquil.json`). Las horas coinciden al minuto con las pleamares publicadas por INOCAR
   y las alturas se ajustan +0,19 m a su escala. Desde 3,6 m el desagüe de las calles bajas es lento y desde
   4,3 m queda bloqueado; con 4,8 m o más la marea sola puede anegar orillas bajas.
4. **Riesgo de anegamiento, hora por hora.** En 28 puntos críticos se cruza la lluvia de las últimas 3 horas
   y la intensidad con la susceptibilidad del sector. El riesgo sube un nivel cuando coinciden agravantes:
   marea alta en el río (en sectores que desaguan al Guayas o al Estero Salado), suelo saturado (más de 30 mm
   en las 72 h previas) o un El Niño costero moderado o mayor (Niño 1+2 ≥ +1,0 °C, umbrales ENFEN). El riesgo
   del día es el peor de sus horas.
5. **El Niño.** Los modelos ya usan la temperatura del mar observada, así que El Niño está dentro de sus números.
   Además, el reporte muestra su evolución y lo usa como agravante porque eleva el nivel del mar y dificulta el
   desagüe de las calles en pleamar.

Los parámetros (zonas, puntos críticos, pesos, umbrales) están en `src/config.py` y `src/analisis.py`.

## Limitaciones

- Los modelos globales tienen entre 13 y 28 km de resolución: distinguen zonas de la ciudad, no calles.
- La ubicación de los puntos críticos es aproximada.
- Es un pronóstico orientativo. Las alertas oficiales son de INAMHI y la Secretaría Nacional de Gestión de Riesgos.
