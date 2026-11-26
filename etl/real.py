from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml
from sqlalchemy import create_engine, inspect, text
from shapely.geometry import LineString, mapping
from shapely.ops import polygonize_full, unary_union

RAIZ = Path(__file__).resolve().parents[1]
MUNICIPIO = "20"
MUNICIPIO_ID = "067"


def cargar_config():
    with open(RAIZ / "config.yaml", encoding="utf-8") as archivo:
        return yaml.safe_load(archivo)


def cargar_env():
    ruta = RAIZ / ".env"
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea and not linea.lstrip().startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                os.environ.setdefault(clave.strip(), valor.strip())


def configurar_logging():
    (RAIZ / "reports").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("etl-real")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    formato = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    consola = logging.StreamHandler()
    consola.setFormatter(formato)
    archivo = logging.FileHandler(RAIZ / "reports" / "etl.log", encoding="utf-8")
    archivo.setFormatter(formato)
    log.addHandler(consola)
    log.addHandler(archivo)
    return log


def detectar_codificacion(ruta: Path):
    from .georreferenciar import codificacion_completa
    encoding = codificacion_completa(ruta)
    muestra = pd.read_csv(ruta, nrows=20, encoding=encoding)
    return encoding, list(muestra.columns)


def columna_mapeada(df: pd.DataFrame, nombres):
    normal = {str(c).strip().upper(): c for c in df.columns}
    for nombre in nombres:
        if str(nombre).strip().upper() in normal:
            return normal[str(nombre).strip().upper()]
    return None


def es_municipio(frame: pd.DataFrame, config):
    mapeo = config["atus"]["mapeo_columnas"]
    entidad = columna_mapeada(frame, mapeo["entidad"])
    municipio = columna_mapeada(frame, mapeo["municipio"])
    clave_geo = columna_mapeada(frame, mapeo["clave_geo"])
    mask = pd.Series(True, index=frame.index)
    if entidad:
        numeros = pd.to_numeric(frame[entidad], errors="coerce")
        mask &= numeros.eq(20)
    elif clave_geo:
        geo = frame[clave_geo].astype(str).str.zfill(5)
        mask &= geo.str.startswith("20")
    else:
        raise RuntimeError("Falta columna de entidad municipal.")
    if municipio:
        numericos = pd.to_numeric(frame[municipio].astype(str).str.replace(r"\.0$", "", regex=True),
                                   errors="coerce")
        mask &= numericos.isin([67, 20067])
    elif clave_geo:
        geo = frame[clave_geo].astype(str).str.zfill(5)
        mask &= geo.str.endswith("067")
    else:
        raise RuntimeError("Falta columna de municipio.")
    return mask


def copiar_raw(ruta: Path, filas: int, filas_municipio: int, log):
    destino_dir = RAIZ / "data/raw/inegi_atus"
    destino_dir.mkdir(parents=True, exist_ok=True)
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    destino = destino_dir / f"{fecha}_{ruta.name}"
    shutil.copy2(ruta, destino)
    contenido = destino.read_bytes()
    hash_sha = hashlib.sha256(contenido).hexdigest()
    (destino.with_suffix(destino.suffix + ".sha256")).write_text(hash_sha, encoding="ascii")
    log.info("ATUS crudo: %s filas=%s municipio=%s sha256=%s",
             destino, filas, filas_municipio, hash_sha)
    return destino, hash_sha


def mapear_tipo(valor):
    texto = str(valor).strip().lower()
    if "atropell" in texto:
        return "atropellamiento"
    if "ciclista" in texto and "caida" in texto:
        return "caida de ciclista"
    if "colisi" in texto or "choque" in texto:
        return "colision"
    return "otro"


def registrar_catalogo(conexion, fuente, ruta, formato, hash_sha, filas, municipio, log):
    existe = conexion.execute(text(
        "SELECT id FROM raw_catalogo_fuentes WHERE hash_sha256=:hash LIMIT 1"
    ), {"hash": hash_sha}).first()
    if existe:
        conexion.execute(text("""
            UPDATE raw_catalogo_fuentes SET filas=:filas, filas_municipio=:municipio,
            estatus='completo', fecha_descarga=:fecha
            WHERE hash_sha256=:hash
        """), {"filas": filas, "municipio": municipio, "fecha": datetime.now(timezone.utc), "hash": hash_sha})
    else:
        conexion.execute(text("""
            INSERT INTO raw_catalogo_fuentes
            (fuente,url,formato,licencia,fecha_descarga,hash_sha256,filas,filas_municipio,estatus)
            VALUES ('inegi_atus',:ruta,:formato,
                    'Libre uso de la información del INEGI',:fecha,:hash,:filas,:municipio,'completo')
        """),
        {"ruta": str(ruta), "formato": formato, "fecha": datetime.now(timezone.utc),
         "hash": hash_sha, "filas": filas, "municipio": municipio})
    log.info("Catalogo raw registrado: %s", ruta)


def extraer_atus(config, log):
    import re
    carpeta = RAIZ / "data/manual/atus"
    archivos = sorted([
        p for p in carpeta.iterdir()
        if p.is_file() and p.suffix.lower() in (".csv", ".dbf", ".shp", ".geojson", ".json")
        and p.name.lower() != "leeme.txt"
    ]) if carpeta.exists() else []
    anuales = []
    for ruta in archivos:
        if ruta.suffix.lower() != ".csv":
            raise RuntimeError(f"Formato ATUS no implementado para carga automática: {ruta.name}.")
        encoding, columnas = detectar_codificacion(ruta)
        if {"LATITUD", "LONGITUD", "ID", "CALLE1", "TIPACCID"} <= set(columnas):
            continue
        anuales.append(ruta)
    raw = RAIZ / "data/raw/inegi_atus"
    for anio in config["etl"]["anios"]:
        nombre = f"atus_anual_{anio}.csv"
        if not any(p.name.lower() == nombre for p in anuales):
            copias = sorted(raw.glob(f"*_{nombre}"))
            if copias:
                hashes = {hashlib.sha256(p.read_bytes()).hexdigest() for p in copias}
                if len(hashes) != 1:
                    raise RuntimeError(f"Hay copias crudas distintas de {nombre} en {raw}.")
                anuales.append(copias[-1])
    if not anuales:
        raise RuntimeError("No hay archivos ATUS reales anuales en data/manual/atus/ ni copias en data/raw/inegi_atus/.")
    archivos = sorted(anuales)
    mapeo = config["atus"]["mapeo_columnas"]
    registros = []
    resumen = []
    total_municipio = 0
    for ruta in archivos:
        nombre_origen = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", ruta.name)
        anio_nombre = None
        coincidencia = re.search(r"(20\d{2})", nombre_origen)
        if coincidencia:
            anio_nombre = int(coincidencia.group(1))
        if anio_nombre is not None and anio_nombre not in config["etl"]["anios"]:
            log.info("ATUS ignorado por rango configurado: %s", ruta.name)
            continue
        if ruta.suffix.lower() not in (".csv",):
            raise RuntimeError(
                f"Formato ATUS no implementado para carga automática: {ruta.name}. "
                "Coloque el CSV anual o agregue el soporte específico."
            )
        encoding, columnas = detectar_codificacion(ruta)
        log.info("ATUS %s codificacion=%s columnas=%s", ruta.name, encoding, columnas)

        primeros = pd.read_csv(ruta, nrows=1, encoding=encoding)
        requeridas = {}
        campos_mapeo = ("entidad", "municipio", "anio", "mes", "dia", "hora", "minuto",
                         "tipo_siniestro", "gravedad",
                         "peat_muerto", "peat_herido", "ciclista_muerto", "ciclista_herido",
                         "conductor_muerto", "conductor_herido", "pasajero_muerto", "pasajero_herido",
                         "otro_muerto", "otro_herido", "ne_muerto", "ne_herido")
        for campo in campos_mapeo:
            encontrados = mapeo[campo]
            columna = columna_mapeada(primeros, encontrados)
            if columna:
                requeridas[campo] = columna
        faltantes = [campo for campo in ("entidad", "municipio", "anio", "mes", "dia", "hora", "minuto", "tipo_siniestro",
                                         "peat_muerto", "peat_herido", "ciclista_muerto", "ciclista_herido",
                                         "conductor_muerto", "conductor_herido", "pasajero_muerto", "pasajero_herido",
                                         "otro_muerto", "otro_herido", "ne_muerto", "ne_herido")
                      if campo not in requeridas]
        if faltantes:
            raise RuntimeError(
                f"Columnas ATUS faltantes en {ruta.name}: {faltantes}. "
                f"Columnas detectadas: {list(columnas)}"
            )
        log.info("ATUS %s mapeo=%s", ruta.name, requeridas)

        filas_totales = 0
        filas_municipio = 0
        anios_archivo = set()
        for chunk_num, chunk in enumerate(pd.read_csv(
                ruta, encoding=encoding, chunksize=50000, low_memory=False)):
            filas_totales += len(chunk)
            mask = es_municipio(chunk, config)
            municipal = chunk.loc[mask].copy()
            filas_municipio += len(municipal)
            anios_archivo.update(
                int(v) for v in pd.to_numeric(municipal[requeridas["anio"]], errors="coerce").dropna().unique()
            )
            for _, fila in municipal.iterrows():
                anio = pd.to_numeric(fila[requeridas["anio"]], errors="coerce")
                if pd.isna(anio) or int(anio) not in config["etl"]["anios"]:
                    continue
                mes = pd.to_numeric(fila[requeridas["mes"]], errors="coerce")
                dia = pd.to_numeric(fila[requeridas["dia"]], errors="coerce")
                hora = pd.to_numeric(fila[requeridas["hora"]], errors="coerce")
                minuto = pd.to_numeric(fila[requeridas["minuto"]], errors="coerce")
                try:
                    fecha_hora = pd.Timestamp(
                        int(anio), int(mes), int(dia), int(hora), int(minuto)
                    )
                except (TypeError, ValueError):
                    raise RuntimeError(f"Fecha u hora ATUS invalida en {ruta.name}:{int(fila.name) + 2}")
                victimas = {}
                tipos = (
                    ("peaton", "peat_muerto", "peat_herido"),
                    ("ciclista", "ciclista_muerto", "ciclista_herido"),
                    ("conductor", "conductor_muerto", "conductor_herido"),
                    ("pasajero", "pasajero_muerto", "pasajero_herido"),
                    ("otro", "otro_muerto", "otro_herido"),
                    ("no_especificado", "ne_muerto", "ne_herido"),
                )
                for tipo, cm, ch in tipos:
                    muertos = pd.to_numeric(fila[requeridas[cm]], errors="coerce")
                    heridos = pd.to_numeric(fila[requeridas[ch]], errors="coerce")
                    if (pd.isna(muertos) or pd.isna(heridos) or muertos < 0 or heridos < 0
                            or muertos != int(muertos) or heridos != int(heridos)):
                        raise RuntimeError(f"Conteo de victimas ATUS invalido en {ruta.name}:{int(fila.name) + 2}")
                    victimas[tipo] = (int(muertos), int(heridos))
                total_muertos = sum(v[0] for v in victimas.values())
                total_heridos = sum(v[1] for v in victimas.values())
                if total_muertos > 0:
                    gravedad = "muerto"
                elif total_heridos > 0:
                    gravedad = "herido"
                else:
                    gravedad = "solo danos"
                latitud = None
                longitud = None
                for campo_lat in mapeo["latitud"]:
                    col = next((c for c in fila.index if str(c).upper() == campo_lat.upper()), None)
                    if col:
                        latitud = pd.to_numeric(fila[col], errors="coerce")
                        break
                for campo_lon in mapeo["longitud"]:
                    col = next((c for c in fila.index if str(c).upper() == campo_lon.upper()), None)
                    if col:
                        longitud = pd.to_numeric(fila[col], errors="coerce")
                        break
                if pd.isna(latitud):
                    latitud = None
                if pd.isna(longitud):
                    longitud = None
                tipo_accidente = mapear_tipo(fila[requeridas["tipo_siniestro"]])
                id_origen = f"{nombre_origen}:{int(fila.name) + 2}"
                registro = {
                    "fecha_hora": fecha_hora,
                    "tipo_siniestro": tipo_accidente,
                    "tipo_usuario": "otro",
                    "gravedad": gravedad,
                    "num_muertos": total_muertos,
                    "num_heridos": total_heridos,
                    "latitud": latitud,
                    "longitud": longitud,
                    "calidad_geo": "original" if latitud is not None and longitud is not None else "no_resuelta",
                    "fuente": "inegi_atus",
                    "id_origen": id_origen,
                    "victimas": victimas,
                }
                registro["hash_registro"] = hashlib.sha256(
                    "|".join(str(registro.get(c, "")) for c in (
                        "id_origen", "fecha_hora", "tipo_siniestro", "gravedad",
                        "num_muertos", "num_heridos", "latitud", "longitud"
                    )).encode("utf-8")
                ).hexdigest()
                registros.append(registro)
        if ruta.parent == raw:
            hash_sha = hashlib.sha256(ruta.read_bytes()).hexdigest()
        else:
            destino, hash_sha = copiar_raw(ruta, filas_totales, filas_municipio, log)
        resumen.append({
            "archivo": nombre_origen, "filas": filas_totales, "filas_municipio": filas_municipio,
            "anios": sorted(anios_archivo),
            "codificacion": encoding, "hash": hash_sha,
        })
        log.info("ATUS resumen archivo=%s filas=%s municipio=%s", ruta.name, filas_totales, filas_municipio)
    if not registros:
        raise RuntimeError(
            "Los archivos ATUS no contienen registros con entidad 20 y municipio 67."
        )
    return registros, resumen


def extraer_overpass(log):
    config = cargar_config()
    consulta = """
[out:json][timeout:180];
area["boundary"="administrative"]["INEGI:MUNID"="20067"]["admin_level"~"^(6|8)$"]->.municipio;
.municipio out tags;
rel["boundary"="administrative"]["INEGI:MUNID"="20067"]["admin_level"~"^(6|8)$"]->.limite;
.limite out geom;
(
  node["highway"="crossing"](area.municipio);
  node["highway"="traffic_signals"](area.municipio);
  way["highway"="cycleway"](area.municipio);
  way["cycleway"](area.municipio);
);
out geom;
"""
    servidores = [
        "https://overpass.openstreetmap.fr/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    ultimo_error = None
    for servidor in servidores:
        for intento in range(config["extraccion"]["reintentos"]):
            try:
                respuesta = requests.get(
                    servidor, params={"data": consulta},
                    timeout=config["extraccion"]["timeout_s"],
                    headers={"User-Agent": "MapasSegurosOaxaca/1.0"}
                )
                respuesta.raise_for_status()
                datos = respuesta.json()
                if "elements" not in datos:
                    raise RuntimeError("Respuesta Overpass sin elemento 'elements'")
                areas = [e for e in datos["elements"] if e.get("type") == "area"
                         and e.get("tags", {}).get("INEGI:MUNID") == "20067"]
                if len(areas) != 1:
                    raise RuntimeError("Overpass no identifico un unico limite municipal INEGI 20067.")
                relaciones = [e for e in datos["elements"] if e.get("type") == "relation"
                              and e.get("tags", {}).get("INEGI:MUNID") == "20067"]
                if len(relaciones) != 1:
                    raise RuntimeError("Overpass no devolvio una unica geometria municipal INEGI 20067.")
                if not any(e.get("type") in ("node", "way") for e in datos["elements"]):
                    raise RuntimeError(
                        "Overpass respondió sin elementos dentro del límite municipal; "
                        "no se registró infraestructura real."
                    )
                break
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                ultimo_error = f"{servidor}: {type(exc).__name__}: {exc}"
                log.warning("Overpass intento=%s servidor=%s error=%s",
                            intento + 1, servidor, ultimo_error)
                if intento + 1 < config["extraccion"]["reintentos"]:
                    time.sleep(2 ** intento)
        else:
            continue
        contenido = respuesta.content
        destino_dir = RAIZ / "data/raw/overpass"
        destino_dir.mkdir(parents=True, exist_ok=True)
        fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        hash_sha = hashlib.sha256(contenido).hexdigest()
        destino = destino_dir / f"{fecha}_{hash_sha}_infraestructura.json"
        destino.write_bytes(contenido)
        (destino.with_suffix(destino.suffix + ".sha256")).write_text(hash_sha, encoding="ascii")
        log.info("Overpass crudo: elementos=%s hash=%s timestamp=%s",
                 len(datos["elements"]), hash_sha, datos.get("osm3s", {}).get("timestamp_osm_base"))
        return datos, destino, hash_sha
    raise RuntimeError(
        "Overpass falló en todos los servidores y no hay datos reales de infraestructura. "
        f"Último error: {ultimo_error}"
    )


def preparar_infraestructura(engine):
    if "geometria" not in {col["name"] for col in inspect(engine).get_columns("infraestructura")}:
        with engine.begin() as conexion:
            conexion.execute(text("ALTER TABLE infraestructura ADD COLUMN geometria JSON NULL"))
    with engine.begin() as conexion:
        conexion.execute(text("""
            CREATE TABLE IF NOT EXISTS limite_municipal (
                clave VARCHAR(5) PRIMARY KEY,
                geometria JSON NOT NULL,
                osm_id VARCHAR(100) NOT NULL,
                hash_archivo CHAR(64) NOT NULL
            ) ENGINE=InnoDB
        """))


def poligono_municipal(relacion):
    def poligonos(rol):
        miembros = [m for m in relacion.get("members", []) if m.get("type") == "way" and m.get("role") == rol]
        if not miembros:
            return None
        if any(len(m.get("geometry", [])) < 2 for m in miembros):
            raise RuntimeError(f"El limite OSM tiene vias {rol} sin geometria.")
        lineas = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in miembros]
        poligonos, cortes, colgantes, invalidos = polygonize_full(unary_union(lineas))
        if poligonos.is_empty or not cortes.is_empty or not colgantes.is_empty or not invalidos.is_empty:
            raise RuntimeError(f"El limite municipal OSM {rol} no forma anillos cerrados.")
        return unary_union(poligonos)
    exterior = poligonos("outer")
    if exterior is None:
        raise RuntimeError("El limite municipal OSM no tiene anillo exterior.")
    interior = poligonos("inner")
    limite = exterior.difference(interior) if interior is not None else exterior
    if limite.is_empty or not limite.is_valid or limite.geom_type not in ("Polygon", "MultiPolygon"):
        raise RuntimeError("El poligono municipal OSM es invalido.")
    return limite


def cargar_infraestructura(conexion, datos, ruta, hash_sha):
    relaciones = [e for e in datos["elements"] if e.get("type") == "relation"
                  and e.get("tags", {}).get("INEGI:MUNID") == "20067"]
    if len(relaciones) != 1:
        raise RuntimeError("Se necesita una unica relacion municipal OSM 20067.")
    limite = poligono_municipal(relaciones[0])
    filas = []
    for elemento in datos["elements"]:
        etiquetas = elemento.get("tags", {})
        highway = etiquetas.get("highway")
        if elemento.get("type") not in ("node", "way"):
            continue
        if highway == "traffic_signals":
            tipo = "semaforo"
        elif highway == "crossing":
            tipo = "cruce_peatonal"
        elif highway == "cycleway" or etiquetas.get("cycleway") not in (None, "no", "separate"):
            tipo = "ciclovia"
        else:
            continue
        puntos = elemento.get("geometry", [])
        if elemento["type"] == "way":
            if len(puntos) < 2:
                raise RuntimeError(f"Via OSM {elemento['id']} sin geometria completa.")
            lat, lon = puntos[0]["lat"], puntos[0]["lon"]
            geometria = {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in puntos]}
        else:
            lat, lon = elemento.get("lat"), elemento.get("lon")
            if lat is None or lon is None:
                raise RuntimeError(f"Nodo OSM {elemento['id']} sin coordenadas.")
            geometria = {"type": "Point", "coordinates": [lon, lat]}
        filas.append({"osm_id": f"{elemento['type']}:{elemento['id']}", "tipo": tipo,
                      "latitud": float(lat), "longitud": float(lon),
                      "tags": json.dumps(etiquetas, ensure_ascii=False),
                      "geometria": json.dumps(geometria, ensure_ascii=False)})
    if not filas:
        raise RuntimeError("Overpass no devolvio infraestructura utilizable para el municipio.")
    conexion.execute(text("DELETE FROM infraestructura"))
    conexion.execute(text("""
        INSERT INTO infraestructura (osm_id,tipo,latitud,longitud,tags,geometria)
        VALUES (:osm_id,:tipo,:latitud,:longitud,:tags,:geometria)
    """), filas)
    conexion.execute(text("DELETE FROM limite_municipal WHERE clave='20067'"))
    conexion.execute(text("""
        INSERT INTO limite_municipal (clave,geometria,osm_id,hash_archivo)
        VALUES ('20067',:geometria,:osm_id,:hash)
    """), {"geometria": json.dumps(mapping(limite)), "osm_id": f"relation:{relaciones[0]['id']}",
           "hash": hash_sha})
    existe = conexion.execute(text("""
        SELECT id FROM raw_catalogo_fuentes WHERE fuente='overpass' AND hash_sha256=:hash LIMIT 1
    """), {"hash": hash_sha}).first()
    if existe:
        conexion.execute(text("""
            UPDATE raw_catalogo_fuentes SET filas=:filas, filas_municipio=:municipio
            WHERE id=:id
        """), {"filas": len(datos["elements"]), "municipio": len(filas), "id": existe[0]})
    else:
        conexion.execute(text("""
            INSERT INTO raw_catalogo_fuentes
            (fuente,url,formato,licencia,fecha_descarga,hash_sha256,filas,filas_municipio,estatus)
            VALUES ('overpass',:ruta,'json','OpenStreetMap ODbL',:fecha,:hash,:filas,:municipio,'completo')
        """), {"ruta": str(ruta), "fecha": datetime.now(timezone.utc), "hash": hash_sha,
               "filas": len(datos["elements"]), "municipio": len(filas)})
    return len(filas)


def cargar_infraestructura_solo():
    cargar_env()
    log = configurar_logging()
    datos, ruta, hash_sha = extraer_overpass(log)
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("mysql"):
        raise RuntimeError("DATABASE_URL no apunta a MySQL.")
    engine = create_engine(url, pool_pre_ping=True)
    preparar_infraestructura(engine)
    with engine.begin() as conexion:
        cargados = cargar_infraestructura(conexion, datos, ruta, hash_sha)
    return {"infraestructura": cargados, "sha256": hash_sha,
            "osm_timestamp": datos.get("osm3s", {}).get("timestamp_osm_base")}


def extraer_indicador(log):
    cargar_env()
    token = os.getenv("INEGI_TOKEN", "").strip()
    config = cargar_config()
    url = f"{config['extraccion']['inegi_indicador_url']}/{token}?type=json"
    ultimo_error = None
    datos = None
    contenido = None
    if token:
        for intento in range(3):
            try:
                respuesta = requests.get(url, timeout=config["extraccion"]["timeout_s"])
                respuesta.raise_for_status()
                datos = respuesta.json()
                contenido = respuesta.content
                break
            except requests.RequestException as exc:
                if exc.response is not None:
                    ultimo_error = f"HTTP {exc.response.status_code}: {exc.response.reason}"
                else:
                    ultimo_error = f"{type(exc).__name__}: error de conexion o tiempo de espera"
                log.warning("INEGI API intento=%s error=%s", intento + 1, ultimo_error)
                if intento < 2:
                    time.sleep(2 ** intento)
            except ValueError:
                ultimo_error = "INEGI API devolvio JSON invalido"
                log.warning("INEGI API intento=%s error=%s", intento + 1, ultimo_error)
                if intento < 2:
                    time.sleep(2 ** intento)
    else:
        ultimo_error = "INEGI_TOKEN no definido"
    if datos is None:
        respaldo = RAIZ / "data/manual/inegi_indicador.json"
        if not respaldo.is_file():
            raise RuntimeError(
                f"INEGI API fallo ({ultimo_error}). Falta respaldo manual real: {respaldo}."
            )
        log.warning("INEGI API fallo; usando respaldo manual %s: %s", respaldo, ultimo_error)
        contenido = respaldo.read_bytes()
        try:
            datos = json.loads(contenido)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Respaldo INEGI invalido: {respaldo}") from exc
        fuente = "respaldo_manual"
    else:
        fuente = "inegi_api"
    try:
        observaciones = datos["Series"][0]["OBSERVATIONS"]
        if not observaciones:
            raise ValueError("sin observaciones")
        for observacion in observaciones:
            int(observacion["TIME_PERIOD"])
            float(str(observacion["OBS_VALUE"]).replace(",", "."))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError(f"El indicador INEGI no contiene observaciones anuales numericas validas: {exc}") from exc
    destino_dir = RAIZ / "data/raw/inegi_bise"
    destino_dir.mkdir(parents=True, exist_ok=True)
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hash_sha = hashlib.sha256(contenido).hexdigest()
    destino = destino_dir / f"{fecha}_{hash_sha}_indicador.json"
    destino.write_bytes(contenido)
    (destino.with_suffix(destino.suffix + ".sha256")).write_text(hash_sha, encoding="ascii")
    return datos, destino, hash_sha, fuente, ultimo_error


def cargar_indicador(conexion, datos, ruta, hash_sha, fuente, error, anios):
    observaciones = datos["Series"][0]["OBSERVATIONS"]
    cargados = 0
    for observacion in observaciones:
        anio = int(observacion["TIME_PERIOD"])
        if anio not in anios:
            continue
        valor = float(str(observacion["OBS_VALUE"]).replace(",", "."))
        conexion.execute(text("""
            INSERT INTO indicador_anual (clave_indicador,descripcion,anio,valor,fuente_dato)
            VALUES ('1006000039','Accidentes de tránsito terrestres en zonas urbanas y suburbanas',
                    :anio,:valor,:fuente)
            ON DUPLICATE KEY UPDATE valor=VALUES(valor),fuente_dato=VALUES(fuente_dato)
        """), {"anio": anio, "valor": valor, "fuente": fuente})
        cargados += 1
    if not cargados:
        raise RuntimeError("INEGI no devolvio observaciones para los años configurados.")
    existente = conexion.execute(text("""
        SELECT id FROM raw_catalogo_fuentes WHERE fuente='inegi_bise' AND hash_sha256=:hash LIMIT 1
    """), {"hash": hash_sha}).first()
    if not existente:
        conexion.execute(text("""
            INSERT INTO raw_catalogo_fuentes
            (fuente,url,formato,licencia,fecha_descarga,hash_sha256,filas,filas_municipio,estatus)
            VALUES ('inegi_bise',:ruta,'json','Libre uso de la información del INEGI',
                    :fecha,:hash,:filas,NULL,:estatus)
        """), {"ruta": str(ruta), "fecha": datetime.now(timezone.utc), "hash": hash_sha,
               "filas": len(observaciones), "estatus": "completo" if error is None else "respaldo_manual"})
    return cargados


def cargar_indicadores_solo():
    cargar_env()
    log = configurar_logging()
    datos, ruta, hash_sha, fuente, error = extraer_indicador(log)
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("mysql"):
        raise RuntimeError("DATABASE_URL no apunta a MySQL.")
    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conexion:
        cargados = cargar_indicador(conexion, datos, ruta, hash_sha, fuente, error,
                                   cargar_config()["etl"]["anios"])
    return {"indicadores": cargados, "fuente": fuente, "error_api": error, "sha256": hash_sha}


def cargar_analitica_solo():
    from .analitica import refrescar_analitica
    cargar_env()
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("mysql"):
        raise RuntimeError("DATABASE_URL no apunta a MySQL.")
    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conexion:
        return refrescar_analitica(conexion, cargar_config()["riesgo"]["pesos_gravedad"])


def cargar_principal(registros, resumen, datos_overpass, ruta_overpass,
                     hash_overpass, datos_indicador, ruta_indicador,
                     hash_indicador, fuente_indicador, error_indicador, log):
    cargar_env()
    url = os.getenv("DATABASE_URL", "")
    if not url or not url.startswith("mysql"):
        raise RuntimeError("DATABASE_URL no apunta a MySQL para el modo real.")
    engine = create_engine(url, pool_pre_ping=True)
    preparar_infraestructura(engine)
    from .analitica import refrescar_analitica
    from .georreferenciar import preparar_todos, crear_tabla, aplicar_georreferencias
    archivos_geo = preparar_todos(RAIZ, log)
    if archivos_geo:
        crear_tabla(engine)
    with engine.begin() as conexion:
        conexion.execute(text("DELETE FROM fact_siniestro"))
        conexion.execute(text("DELETE FROM siniestro_victima"))
        conexion.execute(text("DELETE FROM analytics_siniestro"))
        for item in resumen:
            destino = next(
                (RAIZ / "data/raw/inegi_atus").glob(f"*_{item['archivo']}"),
                None
            )
            if destino is None:
                destino = RAIZ / "data/raw/inegi_atus" / item["archivo"]
            hash_sha = item["hash"]
            existe = conexion.execute(text(
                "SELECT id FROM raw_catalogo_fuentes WHERE hash_sha256=:hash LIMIT 1"
            ), {"hash": hash_sha}).first()
            if not existe:
                conexion.execute(text("""
                    INSERT INTO raw_catalogo_fuentes
                    (fuente,url,formato,licencia,fecha_descarga,hash_sha256,
                     filas,filas_municipio,estatus)
                    VALUES ('inegi_atus',:ruta,'csv',
                            'Libre uso de la información del INEGI',:fecha,:hash,
                            :filas,:municipio,'completo')
                """), {
                    "ruta": str(destino),
                    "fecha": datetime.now(timezone.utc),
                    "hash": hash_sha,
                    "filas": item["filas"],
                    "municipio": item["filas_municipio"],
                })
        for registro in registros:
            resultado = conexion.execute(text("""
                INSERT INTO analytics_siniestro
                (fecha_hora,tipo_siniestro,tipo_usuario,gravedad,num_muertos,num_heridos,
                 latitud,longitud,calidad_geo,fuente,id_origen,hash_registro)
                VALUES (:fecha_hora,:tipo_siniestro,:tipo_usuario,:gravedad,:num_muertos,:num_heridos,
                        :latitud,:longitud,:calidad_geo,:fuente,:id_origen,:hash_registro)
            """), {
                "fecha_hora": registro["fecha_hora"].to_pydatetime(),
                "tipo_siniestro": registro["tipo_siniestro"],
                "tipo_usuario": "otro",
                "gravedad": registro["gravedad"],
                "num_muertos": registro["num_muertos"],
                "num_heridos": registro["num_heridos"],
                "latitud": registro["latitud"],
                "longitud": registro["longitud"],
                "calidad_geo": registro["calidad_geo"],
                "fuente": registro["fuente"],
                "id_origen": registro["id_origen"],
                "hash_registro": registro["hash_registro"],
            })
            siniestro_id = resultado.lastrowid
            for tipo, (muertos, heridos) in registro["victimas"].items():
                if muertos == 0 and heridos == 0:
                    continue
                tipo_id = conexion.execute(text(
                    "SELECT id FROM tipo_usuario_victima WHERE nombre=:nombre"
                ), {"nombre": tipo}).scalar_one()
                conexion.execute(text("""
                    INSERT INTO siniestro_victima
                    (siniestro_id,tipo_usuario_id,num_muertos,num_heridos)
                    VALUES (:siniestro,:tipo,:muertos,:heridos)
                """), {
                    "siniestro": siniestro_id,
                    "tipo": tipo_id,
                    "muertos": muertos,
                    "heridos": heridos,
                })
        for pares_geo, resumen_geo in archivos_geo:
            aplicar_georreferencias(conexion, pares_geo, resumen_geo, RAIZ, log)
        refrescar_analitica(conexion, cargar_config()["riesgo"]["pesos_gravedad"])
        cargar_infraestructura(conexion, datos_overpass, ruta_overpass, hash_overpass)
        cargar_indicador(conexion, datos_indicador, ruta_indicador, hash_indicador,
                          fuente_indicador, error_indicador, cargar_config()["etl"]["anios"])
    log.info("Carga real completada: siniestros=%s infraestructura=%s",
             len(registros), len(datos_overpass["elements"]))
    return len(registros)


def ejecutar_real():
    cargar_env()
    log = configurar_logging()
    config = cargar_config()
    registros, resumen = extraer_atus(config, log)
    datos_overpass, ruta_overpass, hash_overpass = extraer_overpass(log)
    datos_indicador, ruta_indicador, hash_indicador, fuente_indicador, error_indicador = extraer_indicador(log)
    cargados = cargar_principal(
        registros, resumen, datos_overpass, ruta_overpass, hash_overpass,
        datos_indicador, ruta_indicador, hash_indicador,
        fuente_indicador, error_indicador, log
    )
    calidad = {
        "modo": "real",
        "registros_leidos": sum(r["filas"] for r in resumen),
        "filas_municipio": sum(r["filas_municipio"] for r in resumen),
        "registros_cargables": cargados,
        "archivos_atus": resumen,
        "fuente_indicador": fuente_indicador,
        "error_indicador": error_indicador,
        "infraestructura_elementos": len(datos_overpass["elements"]),
        "siniestro_sintetico": 0,
        "overpass_timestamp": datos_overpass.get("osm3s", {}).get("timestamp_osm_base"),
        "fecha_ejecucion": datetime.now(timezone.utc).isoformat(),
    }
    fecha = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    (RAIZ / "reports").mkdir(parents=True, exist_ok=True)
    (RAIZ / "reports" / f"calidad_{fecha}.json").write_text(
        json.dumps(calidad, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    md = [
        "# Reporte de calidad",
        "",
        "- Modo: real",
        f"- Archivos ATUS: {len(resumen)}",
        f"- Filas ATUS municipales: {calidad['filas_municipio']}",
        f"- Siniestros cargados: {cargados}",
        f"- Siniestros sinteticos: 0",
        f"- Elementos Overpass: {len(datos_overpass['elements'])}",
        f"- Indicador INEGI: {fuente_indicador}",
    ]
    if error_indicador:
        md.append(f"- Falla API INEGI: {error_indicador}")
    md.extend([
        "- Fuente de siniestros: INEGI ATUS",
        "- Limitaciones: sin aforos; coordenadas no inventadas.",
    ])
    (RAIZ / "reports" / f"calidad_{fecha}.md").write_text(
        "\n".join(md), encoding="utf-8"
    )
    return calidad


def cargar_atus_solo():
    cargar_env()
    log = configurar_logging()
    config = cargar_config()
    registros, resumen = extraer_atus(config, log)
    url = os.getenv("DATABASE_URL", "")
    if not url or not url.startswith("mysql"):
        raise RuntimeError("DATABASE_URL no apunta a MySQL.")
    engine = create_engine(url, pool_pre_ping=True)
    from .analitica import refrescar_analitica
    from .georreferenciar import preparar_todos, crear_tabla, aplicar_georreferencias
    archivos_geo = preparar_todos(RAIZ, log)
    if archivos_geo:
        crear_tabla(engine)
    with engine.begin() as conexion:
        conexion.execute(text("DELETE FROM fact_siniestro"))
        conexion.execute(text("DELETE FROM siniestro_victima"))
        conexion.execute(text("DELETE FROM analytics_siniestro"))
        conexion.execute(text("DELETE FROM mart_ciudadania_siniestros_publicos"))
        conexion.execute(text("DELETE FROM mart_autoridades_kpi_resumen"))
        for item in resumen:
            destino = next((RAIZ / "data/raw/inegi_atus").glob(f"*_{item['archivo']}"), None)
            hash_sha = item["hash"]
            registrar_catalogo(conexion, "inegi_atus",
                               destino or RAIZ / "data/manual/atus" / item["archivo"],
                               "csv", hash_sha, item["filas"], item["filas_municipio"], log)
        for registro in registros:
            resultado = conexion.execute(text("""
                INSERT INTO analytics_siniestro
                (fecha_hora,tipo_siniestro,tipo_usuario,gravedad,num_muertos,num_heridos,
                 latitud,longitud,calidad_geo,fuente,id_origen,hash_registro)
                VALUES (:fecha_hora,:tipo_siniestro,:tipo_usuario,:gravedad,:num_muertos,:num_heridos,
                        :latitud,:longitud,:calidad_geo,:fuente,:id_origen,:hash_registro)
            """), {
                "fecha_hora": registro["fecha_hora"].to_pydatetime(),
                "tipo_siniestro": registro["tipo_siniestro"],
                "tipo_usuario": "otro",
                "gravedad": registro["gravedad"],
                "num_muertos": registro["num_muertos"],
                "num_heridos": registro["num_heridos"],
                "latitud": registro["latitud"],
                "longitud": registro["longitud"],
                "calidad_geo": registro["calidad_geo"],
                "fuente": registro["fuente"],
                "id_origen": registro["id_origen"],
                "hash_registro": registro["hash_registro"],
            })
            siniestro_id = resultado.lastrowid
            for tipo, (muertos, heridos) in registro["victimas"].items():
                if muertos == 0 and heridos == 0:
                    continue
                tipo_id = conexion.execute(text(
                    "SELECT id FROM tipo_usuario_victima WHERE nombre=:nombre"
                ), {"nombre": tipo}).scalar_one()
                conexion.execute(text("""
                    INSERT INTO siniestro_victima
                    (siniestro_id,tipo_usuario_id,num_muertos,num_heridos)
                    VALUES (:siniestro,:tipo,:muertos,:heridos)
                """), {
                    "siniestro": siniestro_id,
                    "tipo": tipo_id,
                    "muertos": muertos,
                    "heridos": heridos,
                })
        for pares_geo, resumen_geo in archivos_geo:
            aplicar_georreferencias(conexion, pares_geo, resumen_geo, RAIZ, log)
        refrescar_analitica(conexion, config["riesgo"]["pesos_gravedad"])
    log.info("Carga ATUS 2020-2025 completada: %s siniestros reales", len(registros))
    return {"modo": "real", "archivos": len(resumen),
            "filas_municipio": sum(r["filas_municipio"] for r in resumen),
            "siniestros": len(registros),
            "georreferenciados": sum(len(pares) for pares, _ in archivos_geo)}


def ejecutar_demo():
    cargar_env()
    log = configurar_logging()
    config = cargar_config()
    import random
    cantidad = int(config["etl"]["registros_sinteticos"])
    rng = random.Random(config["etl"]["semilla"])
    lat0, lon0 = config["zona"]["centro"]
    filas = []
    for i in range(cantidad):
        anio = rng.choice(config["etl"]["anios"])
        hora = rng.choice(list(range(7, 10)) + list(range(18, 22)))
        fila = {
            "fecha_hora": datetime(anio, rng.randint(1, 12), rng.randint(1, 28), hora, rng.randint(0, 59)),
            "tipo_siniestro": rng.choice(["colision", "atropellamiento", "caida de ciclista", "otro"]),
            "tipo_usuario": rng.choice(["peaton", "ciclista", "motociclista", "automovilista"]),
            "gravedad": rng.choices(["solo danos", "herido", "muerto"], [70, 27, 3])[0],
            "latitud": lat0 + rng.gauss(0, .012),
            "longitud": lon0 + rng.gauss(0, .012),
            "fuente": "sintetico",
            "id_origen": f"demo-{i:06d}",
        }
        fila["num_muertos"] = 1 if fila["gravedad"] == "muerto" else 0
        fila["num_heridos"] = 1 if fila["gravedad"] == "herido" else 0
        filas.append(fila)
    url = os.getenv("DATABASE_URL", "")
    demo_url = url.replace("mapas_seguros?", "mapas_seguros_demo?")
    demo_url = demo_url.rsplit("/", 1)[0] + "/mapas_seguros_demo" if "/mapas_seguros/" not in demo_url else demo_url
    root_url = "mysql+pymysql://root:root@localhost:3307"
    root = create_engine(root_url, pool_pre_ping=True)
    with root.begin() as conexion:
        conexion.execute(text("CREATE DATABASE IF NOT EXISTS mapas_seguros_demo"))
    engine = create_engine(root_url + "/mapas_seguros_demo", pool_pre_ping=True)
    with engine.begin() as conexion:
        conexion.execute(text("""
            CREATE TABLE IF NOT EXISTS analytics_siniestro (
              id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
              fecha_hora DATETIME NOT NULL,
              tipo_siniestro VARCHAR(50) NOT NULL,
              tipo_usuario VARCHAR(50) NOT NULL,
              gravedad VARCHAR(20) NOT NULL,
              num_muertos INT UNSIGNED NOT NULL DEFAULT 0,
              num_heridos INT UNSIGNED NOT NULL DEFAULT 0,
              latitud DOUBLE NULL,
              longitud DOUBLE NULL,
              calidad_geo VARCHAR(30) NULL,
              fuente VARCHAR(50) NOT NULL,
              id_origen VARCHAR(100) NULL,
              hash_registro CHAR(64) UNIQUE NOT NULL
            ) ENGINE=InnoDB
        """))
        conexion.execute(text("""
            CREATE TABLE IF NOT EXISTS tipo_usuario_victima (
              id TINYINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
              nombre VARCHAR(40) NOT NULL UNIQUE,
              es_vulnerable BOOLEAN NOT NULL DEFAULT FALSE
            ) ENGINE=InnoDB
        """))
        conexion.execute(text("""
            CREATE TABLE IF NOT EXISTS siniestro_victima (
              siniestro_id BIGINT UNSIGNED NOT NULL,
              tipo_usuario_id TINYINT UNSIGNED NOT NULL,
              num_muertos INT UNSIGNED NOT NULL DEFAULT 0,
              num_heridos INT UNSIGNED NOT NULL DEFAULT 0,
              PRIMARY KEY (siniestro_id,tipo_usuario_id),
              FOREIGN KEY (siniestro_id) REFERENCES analytics_siniestro(id) ON DELETE CASCADE,
              FOREIGN KEY (tipo_usuario_id) REFERENCES tipo_usuario_victima(id)
            ) ENGINE=InnoDB
        """))
        conexion.execute(text("DELETE FROM analytics_siniestro"))
        for fila in filas:
            base = f"{fila['id_origen']}|{fila['fecha_hora']}|{fila['gravedad']}|{fila['latitud']}|{fila['longitud']}"
            hash_sha = hashlib.sha256(base.encode("utf-8")).hexdigest()
            conexion.execute(text("""
                INSERT INTO analytics_siniestro
                (fecha_hora,tipo_siniestro,tipo_usuario,gravedad,num_muertos,num_heridos,
                 latitud,longitud,calidad_geo,fuente,id_origen,hash_registro)
                VALUES (:fecha_hora,:tipo_siniestro,:tipo_usuario,:gravedad,:num_muertos,:num_heridos,
                        :latitud,:longitud,'original','sintetico',:id_origen,:hash)
            """), {**fila, "hash": hash_sha})
    log.warning("MODO DEMO: %s registros sintéticos cargados exclusivamente en mapas_seguros_demo",
                len(filas))
    return {"modo": "demo", "base": "mapas_seguros_demo", "registros": len(filas)}
