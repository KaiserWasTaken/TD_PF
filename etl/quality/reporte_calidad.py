import json
from pathlib import Path

def guardar(calidad, reportes):
    archivos = sorted(reportes.glob("calidad_*.json"))
    if archivos:
        datos = json.loads(archivos[-1].read_text(encoding="utf-8"))
    else:
        datos = calidad
    return datos
