import hashlib, time
from pathlib import Path
import requests

from ..core import RAIZ, cargar_config

def extraer():
    config = cargar_config()
    consulta = """
    [out:json][timeout:60];
    area["boundary"="administrative"]["admin_level"="8"]["name"="Oaxaca de Juarez"]->.a;
    (
      node["highway"="crossing"](area.a);
      node["highway"="traffic_signals"](area.a);
      node["place"~"suburb|neighbourhood"](area.a);
      way["highway"~"cycleway|pedestrian|footway"](area.a);
    );
    out geom;
    """
    url = config["extraccion"]["overpass_url"]
    for intento in range(config["extraccion"]["reintentos"]):
        try:
            respuesta = requests.post(url, data=consulta, timeout=config["extraccion"]["timeout_s"])
            respuesta.raise_for_status()
            contenido = respuesta.content
            break
        except requests.RequestException:
            if intento == config["extraccion"]["reintentos"] - 1:
                contenido = b'{"elements":[],"error":"ultimo dato no disponible"}'
    destino = RAIZ / "data/raw/overpass"
    destino.mkdir(parents=True, exist_ok=True)
    archivo = destino / f"{time.strftime('%Y-%m-%d')}_infraestructura.json"
    archivo.write_bytes(contenido)
    return archivo, hashlib.sha256(contenido).hexdigest()
