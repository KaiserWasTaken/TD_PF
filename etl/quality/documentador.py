from pathlib import Path
import json

REGLAS = [
 ("L01","Codificacion","Espacios, mayusculas y acentos normalizados"),
 ("L02","Duplicados","Duplicados exactos eliminados"),
 ("L03","Nulos obligatorios","Fecha, tipo y gravedad"),
 ("L04","Tipos de datos","Fechas y coordenadas convertidas"),
 ("L05","Fechas validas","Anios cargados y no futuras"),
 ("L06","Catalogos","Tipos homologados"),
 ("L07","Coherencia","Muertos, heridos y conteos"),
 ("L08","Geocodificacion","Calle/cruce resuelto o no resuelto"),
 ("L09","Validacion espacial","Coordenadas dentro de Mexico"),
 ("L10","Outliers","Mas de 100 m de la red"),
 ("L11","Enriquecimiento","Asignacion vial y colonia"),
 ("L12","Infraestructura","Elementos OSM normalizados"),
 ("L13","Atribucion","Fuente y fecha de extraccion"),
]

def actualizar(raiz):
    reportes = raiz / "reports"
    archivos = sorted(reportes.glob("calidad_*.json"))
    calidad = json.loads(archivos[-1].read_text(encoding="utf-8")) if archivos else {}
    filas = "\n".join(f"| {codigo} | {criterio} | {accion} | {calidad.get(codigo, 0)} |" for codigo, criterio, accion in REGLAS)
    texto = f"""# Documentacion ETL

## Extraccion
La ejecución actual usa datos ATUS reales si existen en `data/manual/atus/`; de lo contrario usa datos sintéticos.
No se usan ERP, CRM ni redes sociales. Las fuentes contempladas son INEGI, Overpass, OSRM y el municipio de estudio.

## Transformacion
| Regla | Criterio | Accion | Registros afectados |
|---|---|---|---|
{filas}

Antes/después: {calidad.get('registros_leidos', 0)} registros leídos, {calidad.get('registros_cargables', 0)} registros cargables.

## Carga
```mermaid
flowchart LR
  Extraer --> Transformar --> Calidad
  Calidad --> MySQL
  MySQL --> Marts
  Marts --> API
```

## Calidad
- Completitud y consistencia documentadas por reglas L01-L13.
- Fuente sintética visible en el reporte y dashboard.
- Comparación OSRM disponible en `data/raw/osrm`.

## Limitaciones
Subregistro de incidentes leves, desfase temporal, falta de aforos, aproximación del índice de riesgo y sin datos personales.
"""
    (raiz / "docs").mkdir(exist_ok=True)
    (raiz / "docs/ETL_documentacion.md").write_text(texto, encoding="utf-8")
