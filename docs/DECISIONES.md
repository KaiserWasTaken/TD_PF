# Decisiones

- Se usa MySQL 8.4 como BD oficial. PostgreSQL/PostGIS/pgRouting quedan fuera de esta implementación porque MySQL no reemplaza las funciones geoespaciales avanzadas de pgRouting.
- Se conserva el fallback por archivos para ejecutar el ETL sin BD disponible.
- Cuando no existen microdatos ATUS locales, se usa una semilla reproducible y se etiqueta cada fila como `sintetico`.
- La primera versión expone una ruta de referencia en línea recta; el adaptador pgRouting/OSRM puede reemplazarla al habilitar la base geoespacial.
- La ruta segura de demostración coincide con la corta hasta integrar una red vial ruteable; nunca se informa mayor exposición.
