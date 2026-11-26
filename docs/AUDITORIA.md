# Auditoria tecnica independiente

Fecha: 2026-11-17

> Esta es una auditoría histórica del prototipo anterior, no un diagnóstico del
> estado actual. Posteriormente se cargaron microdatos ATUS reales y fuentes
> georreferenciadas; consulte el panel de calidad para los conteos actuales.

## 1. Veredicto ejecutivo

El sistema arranca y las rutas basicas, MySQL y el ETL ejecutan sin excepciones críticas observadas. Sin embargo, 3922 de 3922 siniestros finales son sintéticos: 100% de los datos de siniestros son inventados. No existe ATUS real en `data/manual/atus/`, no hay red vial ruteable cargada ni infraestructura OSM real; la ruta segura coincide con la corta y el índice/rankings no están implementados sobre tramos reales. Por ello no es utilizable para decisiones públicas todavía y debe entregarse únicamente como demostración técnica.

Veredicto: **CON CORRECCIONES** como prototipo; **NO** listo para presentar como análisis vial real.

## 2. Semaforo por area

| Area | Estado | Hallazgos |
|---|---|---:|
| Arranque | PARCIAL | Docker Compose levanta db y api; el README omite detalles de puerto alterno y Python geoespacial |
| Datos reales | FALLA | 3922 sintéticos / 3922 totales |
| Base MySQL | PARCIAL | Integridad básica correcta; faltan entidades, geometrías, FK y tablas requeridas |
| ETL | PARCIAL | ETL repetible y trazable en disco; faltan pasos reales completos y rechazados en BD |
| Calidad geoespacial | FALLA | 3815 originales, 107 geocodificadas, 0 no resueltas; sin geometrías ni tramos |
| Utilidad y rutas | FALLA | API usa una línea recta; no hay ruta segura distinta ni exposición calculada |
| API y seguridad | PARCIAL | 401 sin token y 200 con token; credenciales por defecto inseguras |
| Frontend | PARCIAL | Mapa y dashboard consumen API; sin estados robustos ni mapa real de tramos |
| Requisitos | FALLA | Faltan modelo estrella completo, clustering/riesgo por tramo y fuentes reales |

## 3. Evidencia ejecutada

### 1. Inventario y arranque

**OK — Docker y API**

Comando:
```powershell
docker compose ps
```

Salida:
```text
proyecto-api-1   Up ... 0.0.0.0:8000->8000/tcp
proyecto-db-1    mysql:8.4   Up (healthy) 127.0.0.1:3307->3306/tcp
```

**OK — Pruebas**

Comando:
```powershell
python -m pytest -q
```

Salida:
```text
.... [100%]
4 passed
1 warning
```

Las pruebas cubren sintético reproducible, limpieza básica, ruta segura trivial y 401 sin token. No cubren reales ATUS, SQL, 401/403 completo, rutas geográficas ni todas las reglas L01-L13.

**PARCIAL — Archivos prometidos**

Existe el árbol principal, pero faltan directorios/implementaciones de `etl/transform/*`, `etl/load/*`, `api/routers/*`, `api/reportes/*`, `data/staging/*` y `db/init` geoespacial completo. El inventario real contiene 89 archivos y el README declara una estructura más extensa.

**OK — Marcadores incompletos**

La búsqueda encontró únicamente `Todos` como coincidencia del término `placeholder`/marcadores en el select del frontend. No encontró TODO/FIXME/NotImplementedError/lorem/dummy/fake en código Python.

### 2. Datos reales

**FALLA CRITICO — Procedencia**

Comando:
```sql
SELECT fuente, COUNT(*), ROUND(COUNT(*)*100/(SELECT COUNT(*) FROM analytics_siniestro),2)
FROM analytics_siniestro GROUP BY fuente;
```

Salida:
```text
sintetico  3922  100.00
```

No existen archivos ATUS reales ni tablas con `fuente_dato` pobladas. El respaldo INEGI contiene solo 3 valores escritos manualmente.

**FALLA CRITICO — Generadores sintéticos**

- [etl/core.py:27] usa `random.Random`.
- [etl/core.py:38] usa `rng.gauss`.
- El archivo genera coordenadas, calles, gravedad, usuarios y fechas.
- El banner sintético sí es visible en [api/static/index.html:12].

**PARCIAL — Trazabilidad**

Diez IDs muestreados como `syn-*` fueron encontrados en `data/raw/sintetico/siniestros.json`. Esto prueba trazabilidad sintética, no trazabilidad de datos reales.

Ejemplo final:
```text
id_origen=syn-000127
fecha_hora=2022-10-22 06:58
gravedad=herido
fuente=sintetico
```

**FALLA — Archivos crudos auténticos**

Hash registrado y archivo coinciden:
```text
561eb86750024e3dad659e437ba35df9e464440d89f1edf6ef1c4a39254087bf
```

No existe ATUS auténtico. `data/manual/atus/` está vacío. Overpass devolvió:
```json
{"elements":[],"error":"ultimo dato no disponible"}
```

El archivo INEGI es respaldo local escrito desde valores conocidos, no una descarga viva registrada por el catálogo. `raw_catalogo_fuentes` devolvió cero filas.

**NO VERIFICADO — API INEGI**

La solicitud viva a la URL sin token devolvió HTTP 404. Sin token no se pudo validar el indicador.

**PARCIAL — OSRM**

OSRM pie vivo:
```text
distance 714.3 m
duration 574 s
```

OSRM bici vivo:
```text
distance 769.3 m
duration 310.2 s
```

La API local Zócalo → Santo Domingo reportó 606.2 m y 7.6 min a pie, diferencia:
- Pie: +17.8% en distancia respecto a la línea recta local.
- La API no consume OSRM ni devuelve la geometría vial real.

**FALLA — Coherencia oficial**

Municipio sintético por año: 979, 1002, 979, 962. No se comparó con municipal real porque no existen siniestros reales municipales.

**PARCIAL — Plausibilidad**

Los 48 meses tienen cantidades sin huecos grandes, lo cual puede parecer uniforme. Distribución de horas oscila entre 145 y 213 sin picos realmente dominantes. Por usuario está casi uniforme: peatón 971, ciclista 984, motociclista 1005, automovilista 962. Gravedad: 69%, 27.4% y 3.6%, casi exactamente artificial. Coordenadas distintas 3901/3922, pero generadas gausianamente alrededor de un centro.

**Veredicto de datos: DATOS SINTETICOS — 0% reales observados**

### 3. Base MySQL

**PARCIAL — Versión y estructura**

Comando:
```sql
SELECT VERSION();
SHOW TABLES FROM mapas_seguros;
```

Salida:
```text
8.4.13
analytics_siniestro, dim_hora, dim_siniestro_tipo, dim_tiempo,
fact_siniestro, mart_autoridades_kpi_resumen,
mart_ciudadania_siniestros_publicos, mart_ciudadania_tramos_riesgo,
raw_catalogo_fuentes, staging_siniestro_rechazado
```

La separación de capas es por prefijos, no por bases/esquemas.

**FALLA — Modelo exigido**

No existen `colonia`, `tramo_vial`, `tipo_infraestructura`, `infraestructura`, `tipo_siniestro`, `tipo_usuario`, `siniestro`, `indicador_anual`, `fact_indicador_anual`, `dim_ubicacion`, `dim_indicador` ni `punto_critico`.

**OK — Integridad básica**

Resultados:
- Fechas futuras: 0
- Coordenadas fuera de rango: 0
- Conteos negativos/incoherentes: 0
- Hash duplicado: 0
- Huérfanos del hecho: 0
- Huérfanos de dimensiones: 0

**FALLA — CHECK de gravedad**

El intento de insertar `gravedad='gravedad_invalida'` devolvió truncamiento de ENUM. [db/init/04_analytics.sql:2] usa ENUM, por lo que la restricción funciona aunque no sea `CHECK`.

**FALLA — Geometrías**

Consultas:
```sql
SELECT COUNT(*) FROM information_schema.COLUMNS WHERE DATA_TYPE IN ('geometry','point','linestring','polygon');
SELECT COUNT(*) FROM information_schema.STATISTICS WHERE INDEX_TYPE='SPATIAL';
```

Salida:
```text
0
0
```

Se usan latitud/longitud separadas y no hay comprobación espacial MySQL.

**PARCIAL — Rendimiento**

- Filtro por fecha: usa `idx_siniestro_fecha` y retorna 979 filas estimadas.
- Filtro por latitud/longitud: `ALL`, sin índice compuesto ni spatial.
- Ranking: `ALL` y `filesort`.
- Respuesta de `/api/siniestros?limite=5000`: 1741.79 ms medida; es inadecuada para una interacción fluida.

**OK — Idempotencia**

Dos ejecuciones consecutivas mantuvieron:
```text
analytics_siniestro 3922
fact_siniestro 3922
mart_ciudadania_siniestros_publicos 3922
```

### 4. ETL

**PARCIAL — Extracción**

Se conserva el JSON sintético original y su hash coincide. No hay catálogo poblado ni archivos INEGI reales.

**FALLA ALTO — Cuenta de limpieza**

Última corrida:
```text
4000 leídos
3922 cargables
78 rechazados
1 duplicado
143 tipos
36 fechas
197 catálogos
107 geocodificados
41 fuera de México
22 fuera de radio
```

Las reglas sí realizan parte del trabajo, pero los rechazados no se insertan en `staging_siniestro_rechazado` y no hay total único que explique todas las etapas sin solapamiento.

**FALLA ALTO — Datos limpios**

Los archivos existen, pero 3922 filas son sintéticas.

**FALLA — Carga**

La API usa principalmente `data/processed/siniestros_publicos.json`, no MySQL. Los endpoints no consultan las tablas analíticas.

**PARCIAL — Documentación**

`docs/ETL_documentacion.md` coincide parcialmente con 3922 cargados y 4000 leídos, pero omite el desglose completo por ejecución y no registra catálogo real.

### 5. Calidad geoespacial

- Calidad original: 3815
- Geocodificada: 107
- No resuelta: 0
- Con tramos: no verificable; no existe columna `tramo_id`.
- Con colonias: no hay tabla `colonia`.
- Infraestructura real: 0, el Overpass falló y `/api/infraestructura` devuelve un semáforo fijo en [api/main.py].

### 6. Utilidad

**FALLA ALTO — Índice de riesgo**

No existen tramos ni cálculo de índice/riesgo por tramo.

**FALLA ALTO — Ranking**

Solo existe ranking de colonias sintético y puntos críticos aproximados por redondeo de coordenadas. No hay avenidas reales ni normalización por longitud.

**FALLA — Rutas**

Cinco pares pie/bici devolvieron una línea recta local con riesgo 0 y geometría igual corta/segura.

Zócalo → Santo Domingo:
```text
pie corta=606.2 m / 7.6 min / riesgo=0
bici=606.2 m / 2.4 min / riesgo=0
```

OSRM real:
```text
pie 714.3 m / 574 s
bici 769.3 m / 310.2 s
```

**PARCIAL — Filtros**

La API acepta filtros, pero no usa MySQL y las pruebas no hicieron conteo independiente por filtro.

**PARCIAL — Panel**

Las cifras de KPIs coincidieron con SQL directo:
```text
3922, 141 muertos, 1075 heridos, 75.47% vulnerables
```

### 7. API y seguridad

**OK — Proteccion**

Sin token: 401.
Con login válido: KPIs 200.

**FALLA ALTO — Credenciales**

- Contraseña administradora visible en [api/main.py:17] y [.env.example:10].
- JWT secreto visible con valor por defecto [api/main.py:18].
- Contraseñas no están hasheadas; el login compara texto plano.
- No se pudo verificar bcrypt en el flujo real.

**PARCIAL — Entradas**

Parámetros raros devolvieron 500/400, pero no una validación uniforme.
SQL dinámico no concatenado fue buscado y no se encontraron patrones evidentes.

### 8. Frontend

El mapa carga por CDN, pide `/api/siniestros` y dibuja Leaflet. El banner sintético es visible. Existen limitaciones visibles. No se verificó un navegador visual compartido por herramientas de navegador.

### 9. Contraste de requisitos

| Requisito | Estado | Evidencia |
|---|---|---|
| Mapa interactivo y filtros | PARCIAL | Leaflet y API, sin mapa térmico real en CDN |
| Puntos/tramos críticos | NO CUMPLE | Sin tramos, sin DBSCAN, sin índice |
| Ruta segura | NO CUMPLE | Línea recta idéntica |
| Panel, rankings y reportes | PARCIAL | KPIs y CSV/PDF básicos; rankings incompletos |
| ETL repetible | PARCIAL | CLI funcional e idempotente; fuentes reales incompletas |
| Reporte de calidad | PARCIAL | JSON/MD existen; algunos conteos no cuadran |
| Documentación técnica | PARCIAL | Archivos existentes, incompletos |
| Arquitectura nube | PARCIAL | Documento conceptual |

## 4. Tabla de hallazgos

| ID | Area | Gravedad | Evidencia | Archivo/linea | Correccion | Esfuerzo |
|---|---|---|---|---|---|---|
| R1 | Datos reales | CRITICO | 3922/3922 sintéticos | [etl/core.py:27] | Incorporar CSV/GeoJSON ATUS reales | L |
| R2 | Modelo MySQL | CRITICO | Faltan 12 tablas exigidas | [db/init/04_analytics.sql] | Crear modelo normalizado y estrella completo | L |
| R3 | Geoespacial | CRITICO | 0 geometrías, 0 índices SPATIAL | [db/init/04_analytics.sql] | Cargar POINT/LINESTRING y SPATIAL | L |
| R4 | Rutas | CRITICO | API usa línea recta, corta=segura | [api/main.py] ruta | Integrar OSRM/OSM/networkx con fallback OSRM | L |
| R5 | Carga | ALTO | API lee JSON local, no MySQL | [api/main.py:30] | Consultar MySQL parametrizado | M |
| R6 | Seguridad | ALTO | Secretos por defecto y clave plana | [api/main.py:17] | Cambiar secretos, bcrypt y login seguro | M |
| R7 | Calidad ETL | ALTO | Rechazados no existen en staging | [db/init/03_staging.sql] | Insertar registro + motivo L01-L13 | M |
| R8 | Catálogo fuente | ALTO | `raw_catalogo_fuentes=0` filas | [etl/core.py] | Registrar cada raw con URL, licencia y hash | M |
| R9 | Índice/tramos | ALTO | No hay tramos ni riesgo | [etl/core.py] | Crear red vial, asignación y riesgo normalizado | L |
| R10 | Rendimiento | MEDIO | `/api/siniestros` 1741.79 ms | [api/main.py] | Índices compuestos, caché y paginación | M |
| R11 | ETL externo | ALTO | Overpass no disponible; INEGI sin token | [etl/extract/*] | Descargar ATUS y configurar token real | L |
| R12 | Reportes | MEDIO | PDF/CSV sin filtros detallados ni firmas gráficas | [api/main.py] | Añadir filtros, fecha, fuentes y gráfico | M |

## 5. Prioridad de correcciones

1. **CRITICO — Obtener datos ATUS reales**
   Prompt: "Añade el extractor ATUS manual a la ejecución real: detecta CSV/GeoJSON, valida ID_ENTIDAD=20 e ID_MUNICIPIO=67, conserva raw con SHA-256, registra en raw_catalogo_fuentes y conserva rechazados."

2. **CRITICO — Completar modelo geoespacial MySQL**
   Prompt: "Crea las tablas exigidas de colonia, tramo_vial, infraestructura, catálogo, siniestro, indicador anual y esquema estrella. Usa POINT/LINESTRING SRID 4326, índices SPATIAL y claves foráneas."

3. **CRITICO — Implementar red y rutas reales**
   Prompt: "Descarga la red con OSMnx, construye las aristas locales, consulta OSRM como referencia y calcula una ruta segura distinta con coste por índice de riesgo."

4. **ALTO — Eliminar fallback local en producción**
   Prompt: "Haz que todos los endpoints de siniestros, KPIs y rankings consulten MySQL. Mantén archivos JSON solo como cache/exportación."

5. **ALTO — Seguridad**
   Prompt: "Elimina credenciales por defecto, usa bcrypt, JWT secreto obligatorio, expiración breve y variables solo desde `.env`."

6. **ALTO — Calcular riesgo y puntos críticos**
   Prompt: "Asigna siniestros a tramos, implementa pesos/gravedad/usuarios vulnerables, normalización y ranking por riesgo por km y conteo."

7. **ALTO — Completar calidad y documentación**
   Prompt: "Inserta todos los rechazados con motivo, cuadrar leídos=cargados+rechazados+duplicados y actualizar el reporte con cifras reales."

## 6. Trabajo manual del equipo

- Obtener token INEGI y configurar `INEGI_TOKEN`.
- Descargar ATUS anual municipal y colocar CSV/GeoJSON en `data/manual/atus/`.
- Validar geocodificación y calles con el municipio.
- Revisar con colectivos ciclistas y peatones las rutas/zonas críticas.
- Configurar secretos reales y cambiar credenciales administrativas.
- Validar la cobertura geoespacial con datos oficiales.

## 7. Limitaciones para la presentacion

- Los datos actuales no representan incidentes reales.
- La ruta segura no está implementada.
- El índice de riesgo no existe por tramo real.
- Overpass no devolvió infraestructura.
- INEGI no pudo consultarse sin token.
- No existen aforos ni datos de exposición.
- Hay subregistro y desfase temporal.
