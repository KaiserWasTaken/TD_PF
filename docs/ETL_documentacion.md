# Documentación ETL

El ETL real lee microdatos ATUS anuales de 2020–2025, limita el ámbito a entidad
20 y municipio 067 y conserva las fuentes y sus hashes. Si no existen microdatos
en `data/manual/atus/`, puede usar las copias originales de `data/raw/inegi_atus/`.
No se sustituyen archivos reales con datos sintéticos.

Las bases georreferenciadas disponibles se comparan con los microdatos del mismo
año usando fecha, hora, vehículos y víctimas. Solo se asignan coordenadas a
coincidencias únicas; las ambiguas se mantienen sin coordenadas. El catálogo
conserva el hash del archivo geográfico y la tabla `siniestro_georreferencia`
registra su fila de origen. La unión es una coincidencia por atributos, no un
identificador común inequívoco publicado en ambos archivos.

`python -m etl.run --atus` carga los microdatos y vincula los archivos
geográficos disponibles. `python -m etl.run --georreferenciar` actualiza las
coordenadas de una carga existente sin duplicar siniestros. `--all` también
requiere Overpass e indicadores INEGI; falla si no hay fuente real disponible.
`python -m etl.run --indicadores` y `python -m etl.run --infraestructura`
permiten actualizar esas fuentes independientemente. La primera consulta la API
con `INEGI_TOKEN`; si falla, usa únicamente un respaldo manual real y registra
el error. La infraestructura y el límite municipal se consultan en Overpass,
con reintentos y servidores alternativos. El límite se identifica por
`INEGI:MUNID=20067`; OSM lo registra actualmente con `admin_level=6`. Se guarda
la respuesta original con hash y timestamp OSM.

La carga `--atus` y la carga completa actualizan transaccionalmente la tabla
de hechos y dos data marts. `python -m etl.run --analitica` los reconstruye
desde los siniestros ya cargados, sin repetir la extracción; `--georreferenciar`
también los actualiza después de cambiar coordenadas. Cada hecho representa un
siniestro y conserva la fecha y hora reales, conteos de víctimas, gravedad,
fuente y calidad geográfica. Las dimensiones de fecha, hora y tipo permiten
agregarlos. La ubicación usa la clave de desconocido -1: todavía no hay una
dimensión de ubicación vinculada al hecho.

La dimensión de tipo distingue una sola categoría de víctima, múltiples
categorías o ausencia de víctimas. La tabla `siniestro_victima` conserva el
detalle y conteo de cada categoría; no se asigna un único tipo cuando hay varios.
El mart público usa `NULL` cuando no hay una categoría única y guarda las
coordenadas con cinco decimales según su esquema. El mart de autoridades resume
siniestros, muertos y heridos. Los paneles actuales consultan directamente las
tablas analíticas. El mart de tramos no se llena sin una red vial vinculada y
una metodología de riesgo por tramo verificable.

El respaldo manual del indicador, si se necesita, debe ser JSON real con la
estructura `Series`/`OBSERVATIONS`, en `data/manual/inegi_indicador.json`.

La API compara alternativas OSRM dentro del límite municipal sumando los pesos
de gravedad de siniestros georreferenciados a 50 m de cada ruta. El resultado es
un índice histórico, no una probabilidad ni una optimización de toda la red.
Los conteos por vialidad y cruce utilizan los nombres de ATUS, no tramos
geométricos; aún no hay asignación de colonias ni ranking por tramo. La cobertura
geográfica puede ser incompleta y no sustituye datos de exposición o aforos.
El modo sintético solo se ejecuta con `--demo` y usa una base separada.
