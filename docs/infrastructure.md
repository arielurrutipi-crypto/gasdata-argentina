# Infraestructura energética · modelo híbrido C

Inventario aprobado el 13/10/2026: 33 proyectos/etapas. G07 está excluido por decisión del usuario. Los tres antecedentes restantes conservan continuidad por verificar.

## Publicación y frecuencia

El workflow existente se mantiene a las xx:17 UTC, cada hora. `update_infrastructure` se ejecuta tras el colector de noticias y reutiliza sus resultados. No inicia otra consulta a los medios cada hora. El descubrimiento en portales oficiales se consulta cada 24 horas; hasta doce documentos conocidos se revalidan por corrida en rotación con intervalo semanal. Las fallas tienen espera de seis horas antes de reintentar. No se alteran las frecuencias de otros módulos.

`data/infrastructure.json` contiene fichas, fuentes, archivo de noticias, candidatos e historial de consultas. Las noticias permanecen aunque salgan del listado general de 600 registros. Las fechas desconocidas nunca se sustituyen por la fecha de detección. La publicación del archivo es atómica, y el frontend conserva la última versión válida si falla una consulta.

## Estado verificado y posibles cambios

La detección automática NO sobrescribe los hechos estructurales verificados. Las propuestas de cambio se muestran como pendientes, con fuente, fecha de publicación cuando existe, y fecha de detección. Un concurso de capacidad no es una licitación de construcción. El cierre de un contrato de ducto no prueba la habilitación de terminales del mismo sistema.

La validación de cambios compartidos se registra en `data/infrastructure-decisions.json`, mediante una revisión del documento original. No hay controles públicos que permitan modificar la base compartida desde el navegador.

Ejemplo de decisión validada (reemplazar todos los valores por evidencia real; no usar el ejemplo en producción):

```json
{"id":"decision-unica","candidateId":"ID_EXISTENTE","outcome":"accept","value":"Operativo","statusText":"Texto del hito confirmado","effectiveDate":"AAAA-MM-DD","reviewedAt":"AAAA-MM-DDTHH:mm:ss-03:00"}
```

Para un porcentaje, el valor debe ser numérico entre 0 y 100, con fecha efectiva y `scope: "global_physical"`, únicamente después de confirmar que el informe refiere al avance físico global. Rechazar candidatos usa `outcome: "reject"`. Cada decisión se aplica una sola vez y deja historial.

## Imágenes y trazabilidad

Las imágenes principales son esquemas originales SVG, fijos por ID, sin escala ni trazado geográfico. No se reutilizan fotografías externas. Los datos estimados, no disponibles, valores de inversión con horizontes distintos y avances históricos se identifican en la ficha. No se calcula porcentaje a partir de etapas ni se suma la inversión del inventario.

## Comprobaciones

`python -m unittest discover -s scripts -p 'test_infrastructure.py'` comprueba aliases, exclusiones, archivo permanente, fechas, alcance de porcentajes, fallas, frecuencia, revisión y escritura atómica. El workflow incluye estas pruebas además de sus lectores y estimador existentes.

## Exploración geográfica

El mapa general y cada ficha utilizan Leaflet 1.9.4 (BSD-2-Clause, copias locales), fondo OpenStreetMap con atribución ODbL y geometrías Natural Earth de dominio público como respaldo. Sólo se solicitan teselas visibles; no se descargan áreas ni se precargan mapas. La rueda está desactivada para no capturar el desplazamiento de la página.

`data/infrastructure-geography.json` mantiene las referencias cartográficas separadas de los datos actualizados por el colector. Contiene 33 proyectos; G07 no está incluido. Cada punto está identificado como aproximado: centros de localidades o referencias regionales, nunca coordenadas relevadas de plantas ni una polilínea que aparente ser una traza oficial. Los proyectos cercanos se agrupan por proximidad visual, sin desplazar artificialmente sus coordenadas. Los mismos siete filtros controlan mapa, panel y listado.

Las fichas muestran su mapa interactivo y los documentos de origen. La imagen oficial del GPM se reproduce sin modificaciones, con atribución a Secretaría de Energía y licencia CC BY 4.0 según Argentina.gob.ar/terminos-y-condiciones. Material de empresas o medios sin licencia explícita permanece enlazado a su publicación original; no se copia a GasData. Los mapas históricos conservan contexto y denominaciones originales.

Los datos de ubicación y las imágenes documentales no se sustituyen a partir de noticias: requieren revisión, como el resto de los hechos estructurales de la opción C. No se cambió ninguna frecuencia de consulta existente. Si falla el fondo o la carga cartográfica, el inventario, sus fichas y las automatizaciones siguen funcionando.

## Alertas, obras seguidas y comparación

`assets/portal-enhancements.js` escucha los datos ya cargados por el portal: no hace una segunda consulta a medios, normativa o tarifas. Las alertas comparan firmas de contenido (sin `checkedAt` ni `validatedAt`), separan incorporaciones de cambios y muestran el texto anterior/nuevo cuando existe. La primera visita establece una base y sólo destaca publicaciones recientes. Los concursos generan recordatorios locales a 7 días, 3 días y 24 horas; plazos desconocidos, vencidos o concursos cerrados no se consideran próximos vencimientos.

Las suscripciones usan el mismo `gasdata-following-v1` de Mi seguimiento, con tipos `project` y `projectNews`; preservan guardados, notas y archivo anteriores. Marcar la ficha como leída no deja de seguir la obra. Quitar la obra o pulsar “Siguiendo obra” detiene las incorporaciones futuras. Las noticias identificadas después de seguirla (y publicaciones conocidas de las últimas 72 horas) se agregan una sola vez. Quitar una noticia no la recrea en la siguiente actualización. Se conserva el estado de alertas en `gasdata-alerts-v1`; es local al navegador, sin correo ni sincronización entre dispositivos.

Se comparan dos o tres obras con el mismo inventario verificado: estado, titular, recorrido, dimensiones, capacidad, inversión/alcance, fechas y avance publicado. No se calculan razones ni rankings entre unidades o alcances diferentes. `ND` se presenta como “No disponible”, sin conversión a cero.

El panel de vigencia utiliza los metadatos existentes. Distingue última consulta de última exitosa confirmada y fecha/período del dato. Si un lector no publica el éxito por fuente, lo indica expresamente; no deduce éxito de que el proceso global se haya ejecutado. Las fallas, referencias históricas y consultas pendientes de renovación tienen etiquetas diferentes.

## Capas oficiales del sistema

`data/infrastructure-layers.json` contiene cinco conjuntos: red de gasoductos, ENARSA, importación/exportación, plantas compresoras (ENARGAS/ENReGE) y cuencas productivas (CSV geográfico de Secretaría de Energía). Se decodifican dominios ArcGIS para mostrar nombres/transportistas en lugar de códigos. Las geometrías se consultan en EPSG:4326 y se generalizan para visualización. Un registro cartográfico no certifica estado operativo ni vinculación física con una obra.

`scripts/infrastructure_layers.py` se ejecuta desde el colector horario existente, pero consulta las capas sólo una vez por semana. Si falla, conserva el último contenido válido, su fecha de éxito y programa reintento a las 6 horas. Las respuestas vacías, inválidas o incompletas no reemplazan datos válidos; los límites ArcGIS se resuelven por lotes de identificadores. La fecha de edición de origen se deja desconocida cuando el servicio no la informa. El navegador lee la copia de GasData al activar una capa y la revalida cada hora mientras está abierta; no consulta directamente el GIS oficial. Los filtros por transportista se aplican a ductos y compresoras, manteniendo las cuencas como contexto regional.

Validación local: `npm ci --ignore-scripts --no-audit --no-fund && npm run test:portal` y `python -m unittest discover -s scripts -p 'test_infrastructure_layers.py'`. Las pruebas recorren cambios reales frente a revalidaciones, vencimientos, seguimiento automático, deduplicación, notas/archivo existentes, exclusión de noticias quitadas, comparación de tres obras, capas y transportistas. Se ejecutan también antes de cada actualización automática.
