import hashlib, json, time
import requests

from ..core import RAIZ, cargar_config

def extraer_referencia(origen=(17.0609,-96.7254), destino=(17.0658,-96.7229), modo="pie"):
    config = cargar_config()
    perfiles = {"pie": config["extraccion"]["osrm_foot_url"], "bici": config["extraccion"]["osrm_bike_url"]}
    url_base = perfiles.get(modo, perfiles["pie"])
    lat1, lon1 = origen
    lat2, lon2 = destino
    url = f"{url_base}/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson&steps=true&alternatives=true"
    time.sleep(1)
    try:
        respuesta = requests.get(url, timeout=config["extraccion"]["timeout_s"])
        respuesta.raise_for_status()
        contenido = respuesta.content
        estado = "osrm"
    except requests.RequestException:
        contenido = json.dumps({"code": "Error", "routes": []}).encode("utf-8")
        estado = "fallback"
    carpeta = RAIZ / "data/raw/osrm"
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / f"{time.strftime('%Y-%m-%d')}_{modo}.json"
    archivo.write_bytes(contenido)
    return archivo, hashlib.sha256(contenido).hexdigest(), estado
