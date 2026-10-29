# Instrucciones del agente (Claude)

Este archivo describe lo que hace el agente de Claude cada vez que se le llama. La tarea programada de Claude
"Agente Lluvias Guayaquil" usa estas mismas instrucciones.

1. Adjuntar el repositorio `AdnDeep/Testing` con permiso de escritura y clonarlo.
2. Pedir un pronóstico nuevo: escribir la fecha y hora UTC en `solicitudes/ultima.txt`, hacer commit y push a
   `main`. Ese push dispara el flujo de GitHub Actions.
3. Esperar el commit del bot `pronostico-bot` (normalmente 2–4 minutos, máximo 15).
4. Leer `output/estado/ultima_corrida.json`. Si `resultado` no es `success`, revisar `output/estado/log.txt`,
   avisar del error y usar el último reporte disponible indicando su hora de emisión.
5. Leer `output/latest/reporte.json` y `reporte.md`.
6. Contexto adicional (sin cambiar los números): estado de El Niño en la discusión de NOAA CPC y alertas
   vigentes de INAMHI o de la Secretaría Nacional de Gestión de Riesgos para Guayaquil.
7. Publicar `output/latest/reporte.html` en la página del reporte y enviar `output/latest/mapa.png` y
   `output/latest/hoy_por_hora.png`.
8. Resumen para el usuario: titular, hoy hora por hora (horas críticas y pleamares), Norte / Centro / Sur,
   El Niño, alertas oficiales y hora de emisión.
