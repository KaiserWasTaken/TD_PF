from __future__ import annotations

import csv
import hashlib
import math
from collections import defaultdict
from datetime import datetime

from sqlalchemy import text


ANUAL = "atus_anual_2025.csv"
GEO = "BASE_MUNICIPAL_ACCIDENTES_GEORREFERENCIADOS_2025.csv"
COMUNES = (
    "ANIO", "MES", "AUTOMOVIL", "CAMPASAJ", "MICROBUS", "PASCAMION",
    "OMNIBUS", "TRANVIA", "CAMIONETA", "CAMION", "TRACTOR", "FERROCARRI",
    "MOTOCICLET", "BICICLETA", "OTROVEHIC", "CONDMUERTO", "CONDHERIDO",
    "PASAMUERTO", "PASAHERIDO", "PEATMUERTO", "PEATHERIDO", "CICLMUERTO",
    "CICLHERIDO", "OTROMUERTO", "OTROHERIDO",
)


def codificacion_completa(ruta):
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with ruta.open(encoding=encoding) as archivo:
                while archivo.read(1024 * 1024):
                    pass
            return encoding
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"No se pudo decodificar {ruta}")


def clave(fila, geografico):
    campos = ("DIA", "HORA", "MINUTOS") if geografico else ("ID_DIA", "ID_HORA", "ID_MINUTO")
    try:
        return tuple(int(fila[nombre]) for nombre in COMUNES + campos)
    except (KeyError, ValueError, TypeError) as exc:
        raise RuntimeError(f"Datos invalidos en clave de union ATUS: {exc}") from exc


def leer_municipio(ruta, geografico, anio=2025):
    encoding = codificacion_completa(ruta)
    grupos = defaultdict(list)
    total = 0
    municipal = 0
    with ruta.open(encoding=encoding, newline="") as archivo:
        for numero, fila in enumerate(csv.DictReader(archivo), 2):
            total += 1
            try:
                elegible = int(fila["CVE_ENT"]) == 20 and int(fila["CVE_MUN"]) == 67
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"Clave municipal invalida en {ruta}:{numero}") from exc
            if not elegible or fila["ANIO"] != str(anio):
                continue
            municipal += 1
            grupos[clave(fila, geografico)].append((numero, fila))
    return grupos, {"archivo": ruta.name, "filas": total, "filas_municipio": municipal,
                    "codificacion": encoding}


def preparar_archivos(anual, geo, anio, log):
    anuales, resumen_anual = leer_municipio(anual, False, anio)
    geograficos, resumen = leer_municipio(geo, True, anio)
    if not resumen["filas_municipio"] or not resumen_anual["filas_municipio"]:
        raise RuntimeError(f"No hay registros municipales de {anio} en ambas fuentes ATUS.")
    pares = []
    ambiguos = sin_coincidencia = 0
    codigos = defaultdict(set)
    for llave, geos in geograficos.items():
        micros = anuales.get(llave, [])
        if not micros:
            sin_coincidencia += len(geos)
        elif len(geos) != 1 or len(micros) != 1:
            ambiguos += len(geos)
        else:
            pares.append((micros[0], geos[0]))
            codigos[geos[0][1]["TIPACCID"]].add(micros[0][1]["TIPACCID"])
    conflictos = {codigo: sorted(tipos) for codigo, tipos in codigos.items() if len(tipos) != 1}
    if conflictos:
        raise RuntimeError(f"Codigos de accidente inconsistentes en la union ATUS: {conflictos}")
    resultados = []
    for (fila_anual, micro), (fila_geo, geo_fila) in pares:
        try:
            lat, lon = float(geo_fila["LATITUD"]), float(geo_fila["LONGITUD"])
            muertos = sum(int(micro[c]) for c in ("CONDMUERTO", "PASAMUERTO", "PEATMUERTO", "CICLMUERTO", "OTROMUERTO", "NEMUERTO"))
            heridos = sum(int(micro[c]) for c in ("CONDHERIDO", "PASAHERIDO", "PEATHERIDO", "CICLHERIDO", "OTROHERIDO", "NEHERIDO"))
            if (not math.isfinite(lat) or not math.isfinite(lon) or
                    not -90 <= lat <= 90 or not -180 <= lon <= 180 or lat == 0 or lon == 0):
                raise ValueError("coordenadas fuera de rango")
            if muertos != int(geo_fila["TOTMUERTOS"]) or heridos != int(geo_fila["TOTHERIDOS"]):
                raise ValueError("totales de victimas distintos")
        except (KeyError, ValueError, TypeError) as exc:
            raise RuntimeError(f"Registro georreferenciado invalido {geo}:{fila_geo}: {exc}") from exc
        resultados.append({"fila_anual": fila_anual, "fila_geo": fila_geo,
                           "archivo_anual": f"atus_anual_{anio}.csv", "archivo_geo": geo.name,
                           "fecha_hora": datetime(int(micro["ANIO"]), int(micro["MES"]),
                                                  int(micro["ID_DIA"]), int(micro["ID_HORA"]),
                                                  int(micro["ID_MINUTO"])),
                           "tipo_original": micro["TIPACCID"], "muertos": muertos, "heridos": heridos,
                           "latitud": lat, "longitud": lon, "id_geo": geo_fila["ID"],
                           "calle1": geo_fila["CALLE1"], "calle2": geo_fila["CALLE2"]})
    resumen.update({"anio": anio, "coincidencias_unicas": len(resultados), "ambiguos": ambiguos,
                    "sin_coincidencia": sin_coincidencia})
    log.info("Union ATUS: %s", resumen)
    return resultados, resumen


def preparar_georreferencias(carpeta, log):
    anual = carpeta / ANUAL
    geo = carpeta / GEO
    if not geo.exists():
        return [], None
    if not anual.exists():
        raise RuntimeError(f"Falta {anual}: es necesario para vincular {geo.name}.")
    return preparar_archivos(anual, geo, 2025, log)


def preparar_todos(raiz, log):
    carpeta = raiz / "data" / "manual" / "atus"
    raw = raiz / "data" / "raw" / "inegi_atus"
    resultados = []
    for anio in range(2020, 2026):
        geos = []
        for ruta in carpeta.glob("*.csv"):
            if str(anio) not in ruta.name:
                continue
            encoding = codificacion_completa(ruta)
            with ruta.open(encoding=encoding, newline="") as archivo:
                columnas = set(csv.DictReader(archivo).fieldnames or [])
            if {"LATITUD", "LONGITUD", "ID", "CALLE1", "TIPACCID"} <= columnas:
                geos.append(ruta)
        if not geos:
            continue
        if len(geos) != 1:
            raise RuntimeError(f"Se encontro mas de un archivo geografico para {anio}: {geos}")
        nombre = f"atus_anual_{anio}.csv"
        anual = carpeta / nombre
        if not anual.exists():
            copias = sorted(raw.glob(f"*_{nombre}"))
            if not copias:
                raise RuntimeError(f"Falta {nombre} en {carpeta} o su copia original en {raw}")
            hashes = {hashlib.sha256(p.read_bytes()).hexdigest() for p in copias}
            if len(hashes) != 1:
                raise RuntimeError(f"Hay copias crudas distintas de {nombre}; no es posible elegir automaticamente.")
            anual = copias[-1]
        resultados.append(preparar_archivos(anual, geos[0], anio, log))
    return resultados


def crear_tabla(engine):
    with engine.begin() as conexion:
        conexion.execute(text("""
            CREATE TABLE IF NOT EXISTS siniestro_georreferencia (
                siniestro_id BIGINT UNSIGNED PRIMARY KEY,
                archivo VARCHAR(255) NOT NULL,
                fila BIGINT UNSIGNED NOT NULL,
                hash_archivo CHAR(64) NOT NULL,
                id_fuente VARCHAR(100) NOT NULL,
                calle1 VARCHAR(255) NULL,
                calle2 VARCHAR(255) NULL,
                FOREIGN KEY (siniestro_id) REFERENCES analytics_siniestro(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
        """))


def aplicar_georreferencias(conexion, pares, resumen, raiz, log):
    from .real import copiar_raw, mapear_tipo, registrar_catalogo

    ruta = raiz / "data" / "manual" / "atus" / resumen["archivo"]
    destino, hash_archivo = copiar_raw(ruta, resumen["filas"], resumen["filas_municipio"], log)
    registrar_catalogo(conexion, "inegi_atus", destino, "csv", hash_archivo,
                        resumen["filas"], resumen["filas_municipio"], log)
    nombre_anual = f"atus_anual_{resumen['anio']}.csv"
    filas = conexion.execute(text("""
        SELECT id,id_origen,fecha_hora,tipo_siniestro,gravedad,num_muertos,num_heridos
        FROM analytics_siniestro WHERE fuente='inegi_atus' AND id_origen LIKE :prefijo
    """), {"prefijo": nombre_anual + ":%"}).mappings()
    por_origen = defaultdict(list)
    for fila in filas:
        por_origen[fila["id_origen"]].append(fila)
    for par in pares:
        numero = par["fila_anual"]
        correcto = f"{nombre_anual}:{numero}"
        antiguo = f"{nombre_anual}:{numero + ((numero - 2) // 50000) * 50000}"
        candidatos = [fila for origen in {correcto, antiguo} for fila in por_origen[origen]
                      if fila["fecha_hora"] == par["fecha_hora"]
                      and fila["tipo_siniestro"] == mapear_tipo(par["tipo_original"])
                      and fila["num_muertos"] == par["muertos"]
                      and fila["num_heridos"] == par["heridos"]]
        if len(candidatos) != 1:
            raise RuntimeError(f"No se encontro un unico siniestro para {correcto}: {len(candidatos)} candidatos")
        fila = candidatos[0]
        valores_hash = (correcto, fila["fecha_hora"], fila["tipo_siniestro"], fila["gravedad"],
                        fila["num_muertos"], fila["num_heridos"], par["latitud"], par["longitud"])
        hash_registro = hashlib.sha256("|".join(map(str, valores_hash)).encode("utf-8")).hexdigest()
        conexion.execute(text("""
            UPDATE analytics_siniestro
            SET id_origen=:origen,latitud=:latitud,longitud=:longitud,
                calidad_geo='original',hash_registro=:hash
            WHERE id=:id
        """), {"origen": correcto, "latitud": par["latitud"], "longitud": par["longitud"],
               "hash": hash_registro, "id": fila["id"]})
        conexion.execute(text("""
            INSERT INTO siniestro_georreferencia
                (siniestro_id,archivo,fila,hash_archivo,id_fuente,calle1,calle2)
            VALUES (:id,:archivo,:fila,:hash,:id_fuente,:calle1,:calle2)
            ON DUPLICATE KEY UPDATE archivo=VALUES(archivo),fila=VALUES(fila),
                hash_archivo=VALUES(hash_archivo),id_fuente=VALUES(id_fuente),
                calle1=VALUES(calle1),calle2=VALUES(calle2)
        """), {"id": fila["id"], "archivo": resumen["archivo"], "fila": par["fila_geo"], "hash": hash_archivo,
               "id_fuente": par["id_geo"], "calle1": par["calle1"], "calle2": par["calle2"]})
    return len(pares)


def ejecutar():
    import os
    from sqlalchemy import create_engine
    from .real import RAIZ, cargar_env, cargar_config, configurar_logging
    from .analitica import refrescar_analitica

    cargar_env()
    log = configurar_logging()
    archivos = preparar_todos(RAIZ, log)
    if not archivos:
        raise RuntimeError("Faltan archivos ATUS georreferenciados en data/manual/atus/.")
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("mysql"):
        raise RuntimeError("DATABASE_URL no apunta a MySQL.")
    engine = create_engine(url, pool_pre_ping=True)
    crear_tabla(engine)
    with engine.begin() as conexion:
        cargados = sum(aplicar_georreferencias(conexion, pares, resumen, RAIZ, log)
                       for pares, resumen in archivos)
        refrescar_analitica(conexion, cargar_config()["riesgo"]["pesos_gravedad"])
    return {"archivos": [resumen for _, resumen in archivos], "cargados": cargados}
