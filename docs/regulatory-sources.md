# Normativa: consulta y clasificación

La sección técnica incorpora el listado automático de resoluciones técnicas, además de los accesos a las bibliotecas oficiales. Reutiliza los datos de Normativa legal; no consulta fuentes desde el navegador. Permite buscar número, NAG o tema, filtrar por organismo y ver todas las resoluciones sectoriales. Se pagina de diez en diez.

El Boletín Oficial se mantiene como fuente de publicación, con el mismo solapamiento de dos días y las colas de ediciones/documentos pendientes. El catálogo oficial ENARGAS/ENReGE, que ya se consulta para la descarga Excel cada tres horas, se usa como fuente complementaria de descubrimiento. Se recuperan resoluciones históricas desde el 01/01/2026 sin reiniciar la consulta del Boletín ni aumentar frecuencias.

Las resoluciones se cruzan por organismo, número y año: ENARGAS y ENReGE pueden tener el mismo número en un mismo año. Se conservan los enlaces y fechas de publicación verificados. Los registros recuperados sólo desde el catálogo tienen `issuedAt` y `publishedAt: null`; no se infiere publicación, vigencia ni aprobación a partir de la emisión. Tampoco se usan para inferir vigencia tarifaria. Cuando vuelve el Boletín, el registro se enriquece.

La clasificación técnica se basa en el objeto/parte dispositiva: admite NAG con guion o espacios, adendas, seguridad, integridad, medición y consultas públicas técnicas. Una referencia genérica al Reglamento de Comercializadores no convierte una inscripción comercial en una norma técnica. Las sanciones no se incluyen en la vista técnica predeterminada, aunque pueden encontrarse en Todas las resoluciones sectoriales. Los documentos históricos recuperados no generan una avalancha de alertas como si fueran novedades de hoy.

Un catálogo actualizado no resuelve ni oculta una lectura fallida del Boletín: ambas consultas muestran su estado por separado. Las consultas públicas conservan su texto; no se presentan como normas ya aprobadas.
