from datetime import datetime

from sqlalchemy import text


MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def clasificacion_usuario(siniestro):
    cantidad = siniestro["tipos_afectados"]
    if cantidad == 1:
        return siniestro["unico_tipo"]
    if cantidad > 1:
        return "multiples_con_vulnerables" if siniestro["vulnerable"] else "multiples_sin_vulnerables"
    return "sin_victimas"


def refrescar_analitica(conexion, pesos):
    siniestros = conexion.execute(text("""
        SELECT s.id, s.fecha_hora, s.tipo_siniestro, s.gravedad, s.num_muertos,
               s.num_heridos, s.latitud, s.longitud, s.calidad_geo, s.fuente,
               COUNT(v.tipo_usuario_id) AS tipos_afectados,
               COUNT(t.id) AS tipos_validos,
               COALESCE(SUM(v.num_muertos), 0) AS muertos_victimas,
               COALESCE(SUM(v.num_heridos), 0) AS heridos_victimas,
               MIN(t.nombre) AS unico_tipo,
               MAX(CASE WHEN t.nombre IN ('peaton', 'ciclista')
                        THEN 1 ELSE 0 END) AS vulnerable
        FROM analytics_siniestro s
        LEFT JOIN siniestro_victima v ON v.siniestro_id = s.id
        LEFT JOIN tipo_usuario_victima t ON t.id = v.tipo_usuario_id
        GROUP BY s.id, s.fecha_hora, s.tipo_siniestro, s.gravedad, s.num_muertos,
                 s.num_heridos, s.latitud, s.longitud, s.calidad_geo, s.fuente
        ORDER BY s.id
    """)).mappings().all()
    if not siniestros:
        raise RuntimeError("No hay siniestros reales cargados para construir el modelo analitico.")
    if any(s["fuente"] != "inegi_atus" for s in siniestros):
        raise RuntimeError("La carga analitica real requiere exclusivamente siniestros INEGI ATUS.")
    for gravedad in {s["gravedad"] for s in siniestros}:
        peso = pesos.get(gravedad)
        if isinstance(peso, bool) or not isinstance(peso, int) or not 0 <= peso <= 255:
            raise RuntimeError(f"Peso de gravedad invalido o ausente: {gravedad}.")
    if any(not s["calidad_geo"] for s in siniestros):
        raise RuntimeError("Hay siniestros sin calidad geografica; corrija la fuente antes de cargar.")
    if any(s["tipos_afectados"] != s["tipos_validos"] or
           s["num_muertos"] != s["muertos_victimas"] or
           s["num_heridos"] != s["heridos_victimas"] for s in siniestros):
        raise RuntimeError("Los conteos o tipos de victimas no coinciden con los siniestros.")
    horas = {fila[0] for fila in conexion.execute(text("SELECT hora_key FROM dim_hora"))}

    fechas_existentes = {
        fila["tiempo_key"]: fila["fecha"]
        for fila in conexion.execute(text("SELECT tiempo_key, fecha FROM dim_tiempo")).mappings()
    }
    fechas = {}
    tipos = {}
    for s in siniestros:
        fecha = s["fecha_hora"]
        if isinstance(fecha, str):
            fecha = datetime.fromisoformat(fecha)
        if fecha.hour not in horas:
            raise RuntimeError(f"Falta la hora {fecha.hour} en dim_hora.")
        dia = fecha.date()
        clave = int(dia.strftime("%Y%m%d"))
        previa = fechas_existentes.get(clave)
        if previa is not None and str(previa) != dia.isoformat():
            raise RuntimeError(f"Clave de fecha inconsistente en dim_tiempo: {clave}.")
        if clave not in fechas_existentes:
            fechas[clave] = {
                "clave": clave, "fecha": dia, "anio": dia.year, "mes": dia.month,
                "nombre_mes": MESES[dia.month - 1], "dia_semana": DIAS[dia.weekday()],
                "fin_semana": dia.weekday() >= 5,
            }
        usuario = clasificacion_usuario(s)
        tipo = (s["tipo_siniestro"], s["gravedad"], usuario, int(s["vulnerable"]))
        tipos[tipo] = {
            "tipo": tipo[0], "gravedad": tipo[1], "usuario": tipo[2], "vulnerable": tipo[3],
        }

    if fechas:
        conexion.execute(text("""
            INSERT INTO dim_tiempo
            (tiempo_key,fecha,anio,mes,nombre_mes,dia_semana,es_fin_de_semana)
            VALUES (:clave,:fecha,:anio,:mes,:nombre_mes,:dia_semana,:fin_semana)
        """), list(fechas.values()))
    existentes = {
        (f["tipo_siniestro"], f["gravedad"], f["tipo_usuario"]): f
        for f in conexion.execute(text("""
            SELECT siniestro_tipo_key,tipo_siniestro,gravedad,tipo_usuario,es_vulnerable
            FROM dim_siniestro_tipo
        """)).mappings()
    }
    nuevos = []
    for tipo, valores in tipos.items():
        previo = existentes.get(tipo[:3])
        if previo is not None and int(previo["es_vulnerable"]) != tipo[3]:
            raise RuntimeError(f"Dimension de tipo con vulnerabilidad inconsistente: {tipo[:3]}.")
        if previo is None:
            nuevos.append(valores)
    if nuevos:
        conexion.execute(text("""
            INSERT INTO dim_siniestro_tipo (tipo_siniestro,gravedad,tipo_usuario,es_vulnerable)
            VALUES (:tipo,:gravedad,:usuario,:vulnerable)
        """), nuevos)
    claves_tipo = {
        (f["tipo_siniestro"], f["gravedad"], f["tipo_usuario"]): f["siniestro_tipo_key"]
        for f in conexion.execute(text("""
            SELECT siniestro_tipo_key,tipo_siniestro,gravedad,tipo_usuario
            FROM dim_siniestro_tipo
        """)).mappings()
    }
    hechos = []
    publicos = []
    for s in siniestros:
        fecha = s["fecha_hora"]
        if isinstance(fecha, str):
            fecha = datetime.fromisoformat(fecha)
        cantidad = s["tipos_afectados"]
        usuario = clasificacion_usuario(s)
        hechos.append({
            "id": s["id"], "tiempo": int(fecha.strftime("%Y%m%d")), "hora": fecha.hour,
            "tipo": claves_tipo[(s["tipo_siniestro"], s["gravedad"], usuario)],
            "muertos": s["num_muertos"], "heridos": s["num_heridos"],
            "peso": pesos[s["gravedad"]], "calidad": s["calidad_geo"], "fuente": s["fuente"],
        })
        publicos.append({
            "id": s["id"], "fecha": fecha, "tipo": s["tipo_siniestro"],
            "usuario": s["unico_tipo"] if cantidad == 1 else None,
            "gravedad": s["gravedad"], "latitud": s["latitud"], "longitud": s["longitud"],
        })
    conexion.execute(text("DELETE FROM fact_siniestro"))
    conexion.execute(text("""
        INSERT INTO fact_siniestro
        (siniestro_id,tiempo_key,hora_key,ubicacion_key,siniestro_tipo_key,
         num_siniestros,num_muertos,num_heridos,peso_gravedad,calidad_geo,fuente)
        VALUES (:id,:tiempo,:hora,-1,:tipo,1,:muertos,:heridos,:peso,:calidad,:fuente)
    """), hechos)
    conexion.execute(text("DELETE FROM mart_ciudadania_siniestros_publicos"))
    conexion.execute(text("""
        INSERT INTO mart_ciudadania_siniestros_publicos
        (id,fecha_hora,tipo_siniestro,tipo_usuario,gravedad,latitud,longitud)
        VALUES (:id,:fecha,:tipo,:usuario,:gravedad,:latitud,:longitud)
    """), publicos)
    conexion.execute(text("DELETE FROM mart_autoridades_kpi_resumen"))
    conexion.execute(text("""
        INSERT INTO mart_autoridades_kpi_resumen (id,total_siniestros,muertos,heridos)
        VALUES (1,:total,:muertos,:heridos)
    """), {
        "total": len(siniestros), "muertos": sum(s["num_muertos"] for s in siniestros),
        "heridos": sum(s["num_heridos"] for s in siniestros),
    })
    return {"hechos": len(hechos), "siniestros_publicos": len(publicos),
            "muertos": sum(s["num_muertos"] for s in siniestros),
            "heridos": sum(s["num_heridos"] for s in siniestros)}
