# Mapas Seguros Oaxaca

ETL y prototipo web para analizar siniestros viales en Oaxaca de Juárez.
Motor configurado: **MySQL 8.4** con Docker. La base principal usa ATUS real;
los datos sintéticos solo se generan en la base separada de demostración.

## Inicio rápido

```powershell
Copy-Item .env.example .env
docker compose up -d db
python -m pip install -r requirements.txt
python -m etl.run --all
pytest -q
docker compose up -d api
```

Abrir `http://localhost:8000` y `http://localhost:8000/docs`. Para MySQL: iniciar Docker Desktop y ejecutar `docker compose up -d db`, ajustar `DATABASE_URL` y ejecutar el ETL.
`--all` necesita acceso a Overpass y un token INEGI o respaldo manual real; si
faltan, falla explícitamente. Para cargar solo ATUS use `python -m etl.run --atus`.

## Datos reales

Colocar CSV/GeoJSON ATUS en `data/manual/atus/`. El ETL detecta, filtra entidad 20/municipio 67 y conserva los archivos originales con hash.
Si no existe ATUS local, el ETL real falla: no sustituye datos. El modo sintético
requiere `python -m etl.run --demo` y usa exclusivamente `mapas_seguros_demo`.

Las bases georreferenciadas 2020–2025 se vinculan con el microdato anual mediante campos
compartidos; las coincidencias ambiguas no reciben coordenadas. Cada vínculo
conserva el archivo, la fila y el hash de la fuente geográfica. Para agregarla a
una carga ATUS existente, ejecute `python -m etl.run --georreferenciar`. Los
registros sin una coincidencia inequívoca no aparecen como puntos en el mapa.
Si los microdatos anuales ya fueron cargados, el ETL puede usar las copias crudas
conservadas en `data/raw/inegi_atus/`.

El panel no inventa valores cuando faltan fuentes: el comparativo estatal necesita
`INEGI_TOKEN` o un respaldo real en `data/manual/inegi_indicador.json` con la
respuesta JSON de la API. Para actualizar por separado los indicadores o la
infraestructura, ejecute `python -m etl.run --indicadores` o
`python -m etl.run --infraestructura`. Overpass debe estar accesible para cargar
infraestructura y el límite municipal OSM, identificado por `INEGI:MUNID=20067`
(actualmente `admin_level=6`). Se prueban tres servidores y se conserva la
respuesta cruda con su hash.

La comparación de rutas a pie o en bicicleta usa las alternativas que devuelve
OSRM y descarta rutas que salgan del polígono municipal. La ruta presentada como
más corta es la más corta **entre esas alternativas**, no necesariamente entre
todas las rutas posibles. El índice histórico suma los pesos de gravedad
configurados para siniestros georreferenciados a 50 m o menos de la ruta;
no es una probabilidad ni garantiza seguridad. No utiliza aforos ni los siniestros
sin coordenadas y no optimiza el riesgo sobre toda la red vial.

El panel de autoridades muestra conteos por nombres de vialidad y cruce
reportados por ATUS y el comparativo anual municipal/estatal de INEGI.
El ranking por tramos geométricos y el ranking de colonias aún no están
implementados; este último requiere una fuente de colonias vinculable.
El panel permite filtrar por fecha inicial y final (ambas inclusivas); el filtro
se comparte entre KPI, vialidades, calidad de datos y reportes. La comparación
estatal solo se muestra para años completos, porque INEGI aporta un valor anual.
El panel visualiza tendencia mensual, concentración por día/hora y el ranking de
vialidades; Chart.js se carga desde jsDelivr. Los endpoints de puntos críticos
también aceptan el mismo periodo para su futura representación.

La carga de ATUS reconstruye la tabla de hechos y los data marts de siniestros
públicos y resumen de autoridades. Para reconstruirlos a partir de la base
existente sin descargar fuentes, ejecute `python -m etl.run --analitica`.
El data mart de tramos permanece vacío porque no existe una fuente de tramos
viales vinculados a los siniestros; no se generan tramos ni riesgos ficticios.
Actualmente los paneles consultan las tablas analíticas, no los data marts.

## Comandos

`make up`, `make etl`, `make test`, `make api`, `make reset`.

## Limitaciones

El índice de riesgo es aproximado; existe subregistro, falta de aforos y desfase de publicación. No se almacenan datos personales. OSM requiere atribución © OpenStreetMap contributors y los indicadores se atribuyen a INEGI.
