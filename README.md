# GasData Argentina

MVP público para consolidar noticias, normativa, tarifas GN/GLP y datos del sector de gas natural argentino.

- Sitio estático preparado para GitHub Pages.
- Actualización automática mediante GitHub Actions.
- Cada dato muestra período de referencia y fecha/hora de validación.
- Producción: validación cada 15 días.
- Noticias recientes: resaltadas durante 48 h.

La fuente original prevalece sobre cualquier resumen o dato derivado.

## Continuidad de las actualizaciones

El cron conserva su ejecución a los 17 minutos de cada hora y cada lector conserva su frecuencia propia. `scripts/pipeline_runner.py` ejecuta los lectores en procesos aislados (Linux/GitHub Actions), guarda `data.json` de forma atómica al completar cada etapa y conserva el último dato si una etapa falla o supera su tiempo máximo. El ciclo de consultas tiene un presupuesto de 20 minutos para dejar margen al guardado y la publicación antes del límite de 30 minutos del trabajo. Una etapa diferida vuelve a intentarse en el siguiente ciclo; no se adelantan los marcadores de consultas que no finalizaron.

Los seis lectores de Mercado también se guardan por separado. Las noticias se guardan antes de traducirlas. Las ediciones y documentos pendientes del Boletín Oficial siguen registrados y se reintentan con concurrencia limitada. Los datos de cada fuente conservan sus propias fechas de intento y validación: completar una etapa no significa que todas sus fuentes hayan respondido. Las interrupciones de etapas se registran en `pipelineStages`, se muestran en Actualizaciones y se imprimen inmediatamente en los registros de Actions.

Pruebas de continuidad: `python -m unittest discover -s scripts -p 'test_pipeline_runner.py'` (demora, excepción, presupuesto agotado e integración de todas las etapas sin red).
