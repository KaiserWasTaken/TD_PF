from pathlib import Path
import csv, io, math, os, hashlib, json, time
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from jose import JWTError, jwt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
import requests
import yaml
from .riesgo import exposicion_rutas
from shapely.geometry import LineString, Point, shape

RAIZ = Path(__file__).resolve().parents[1]
app = FastAPI(title="Mapas Seguros Oaxaca", version="1.0.0")
bearer = HTTPBearer(auto_error=False)
USUARIO = os.getenv("ADMIN_USER", "autoridad")
CLAVE = os.getenv("ADMIN_PASSWORD", "autoridad123")
SECRETO = os.getenv("JWT_SECRET", "modificar-en-produccion")


def cargar_env():
    global USUARIO, CLAVE, SECRETO
    ruta = RAIZ / ".env"
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea and not linea.lstrip().startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                os.environ.setdefault(clave.strip(), valor.strip())
    USUARIO = os.getenv("ADMIN_USER", USUARIO)
    CLAVE = os.getenv("ADMIN_PASSWORD", CLAVE)
    SECRETO = os.getenv("JWT_SECRET", SECRETO)


cargar_env()


def datos():
    cargar_env()
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("mysql"):
        raise HTTPException(503, "No hay una base MySQL real disponible")
    engine = create_engine(url, pool_pre_ping=True)
    df = pd.read_sql(text("""
        SELECT s.fecha_hora,s.tipo_siniestro,s.tipo_usuario,s.gravedad,s.num_muertos,s.num_heridos,
               s.latitud,s.longitud,s.calidad_geo,s.fuente,s.id_origen,
               (SELECT GROUP_CONCAT(t.nombre)
                FROM siniestro_victima v
                JOIN tipo_usuario_victima t ON t.id=v.tipo_usuario_id
                WHERE v.siniestro_id=s.id) AS usuarios_afectados
        FROM analytics_siniestro s
    """), engine)
    if "fecha_hora" in df.columns:
        df["fecha_hora"] = pd.to_datetime(df["fecha_hora"], errors="coerce")
    return df


def validar_periodo(fecha_ini, fecha_fin):
    if fecha_ini and fecha_fin and fecha_ini > fecha_fin:
        raise HTTPException(422, "fecha_ini no puede ser posterior a fecha_fin.")


def filtrar_periodo(df, fecha_ini=None, fecha_fin=None):
    validar_periodo(fecha_ini, fecha_fin)
    if fecha_ini:
        df = df[df["fecha_hora"] >= pd.Timestamp(fecha_ini)]
    if fecha_fin:
        df = df[df["fecha_hora"] < pd.Timestamp(fecha_fin + timedelta(days=1))]
    return df


def autoridad_actual(credencial: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credencial is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Se requiere autenticacion")
    try:
        contenido = jwt.decode(credencial.credentials, SECRETO, algorithms=["HS256"])
        if contenido.get("rol") != "autoridad":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Rol no autorizado")
        return contenido
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token invalido o vencido") from exc


class Credenciales(BaseModel):
    usuario: str
    clave: str


@app.post("/api/auth/login")
def login(credenciales: Credenciales):
    cargar_env()
    if credenciales.usuario != USUARIO or credenciales.clave != CLAVE:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o clave incorrectos")
    contenido = {"sub": credenciales.usuario, "rol": "autoridad", "exp": datetime.now(timezone.utc) + timedelta(hours=8)}
    token = jwt.encode(contenido, SECRETO, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_in": 28800}


@app.get("/", response_class=HTMLResponse)
def inicio():
    return (RAIZ / "api/static/index.html").read_text(encoding="utf-8")


@app.get("/autoridades", response_class=HTMLResponse)
def vista_autoridades():
    ruta = RAIZ / "api/static/autoridades.html"
    if ruta.exists():
        return ruta.read_text(encoding="utf-8")
    return "<h1>Panel de autoridades</h1>"


@app.get("/api/catalogos")
def catalogos():
    return {
        "gravedades": ["solo danos", "herido", "muerto"],
        "tipos_usuario": ["peaton", "ciclista", "conductor", "pasajero", "otro", "no_especificado"],
        "tipos_siniestro": ["atropellamiento", "colision", "caida de ciclista", "otro"],
    }


@app.get("/api/modo")
def modo():
    cargar_env()
    url = os.getenv("DATABASE_URL", "")
    modo_actual = "demo" if url and make_url(url).database == "mapas_seguros_demo" else "real"
    return {"modo": modo_actual, "banner_demo": modo_actual == "demo"}


@app.get("/api/siniestros")
def siniestros(
    fecha_ini: date | None = None,
    fecha_fin: date | None = None,
    hora_ini: int | None = Query(None, ge=0, le=23),
    hora_fin: int | None = Query(None, ge=0, le=23),
    gravedad: str | None = None,
    tipo_usuario: str | None = None,
    tipo_siniestro: str | None = None,
    bbox: str | None = None,
    limite: int = Query(5000, ge=1, le=20000),
):
    df = filtrar_periodo(datos(), fecha_ini, fecha_fin)
    if df.empty:
        return {"type": "FeatureCollection", "features": [], "fuente": "ninguna",
                "total_georreferenciados": 0}
    if hora_ini is not None:
        df = df[df["fecha_hora"].dt.hour >= hora_ini]
    if hora_fin is not None:
        df = df[df["fecha_hora"].dt.hour <= hora_fin]
    if gravedad:
        df = df[df["gravedad"] == gravedad]
    if tipo_usuario:
        usuarios = df["usuarios_afectados"].fillna("").str.split(",")
        df = df[usuarios.map(lambda tipos: tipo_usuario in tipos) |
                ((df["fuente"] == "sintetico") & (df["tipo_usuario"] == tipo_usuario))]
    if tipo_siniestro:
        df = df[df["tipo_siniestro"] == tipo_siniestro]
    if bbox:
        try:
            lon_min, lat_min, lon_max, lat_max = map(float, bbox.split(","))
            df = df[df["longitud"].between(lon_min, lon_max) & df["latitud"].between(lat_min, lat_max)]
        except ValueError as exc:
            raise HTTPException(400, "bbox debe ser lon_min,lat_min,lon_max,lat_max") from exc
    df = df.dropna(subset=["latitud", "longitud"])
    features = []
    for _, fila in df.head(limite).iterrows():
        latitud = float(fila["latitud"])
        longitud = float(fila["longitud"])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [longitud, latitud]},
            "properties": {
                "fecha_hora": fila["fecha_hora"].isoformat() if hasattr(fila["fecha_hora"], "isoformat") else str(fila["fecha_hora"]),
                "gravedad": fila["gravedad"],
                "tipo_usuario": fila["tipo_usuario"],
                "tipo_siniestro": fila["tipo_siniestro"],
                "fuente": fila.get("fuente", "desconocida"),
                "id_origen": fila["id_origen"],
            },
        })
    return {"type": "FeatureCollection", "features": features, "fuente": "inegi_atus",
            "total_georreferenciados": len(df)}


@app.get("/api/mapa-calor")
def mapa_calor():
    df = datos()
    if df.empty:
        return []
    pesos = {"solo danos": 1, "herido": 3, "muerto": 10}
    return [{"latitud": fila.latitud, "longitud": fila.longitud,
             "peso": pesos.get(fila.gravedad, 1)}
            for fila in df.itertuples()
            if pd.notna(fila.latitud) and pd.notna(fila.longitud)]


@app.get("/api/tramos-riesgo")
def tramos_riesgo():
    raise HTTPException(503, "El riesgo por tramo aun no esta calculado sobre una red vial.")


@app.get("/api/infraestructura")
def infraestructura():
    cargar_env()
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("mysql"):
        raise HTTPException(503, "No hay una base MySQL real disponible")
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conexion:
        filas = conexion.execute(text("""
            SELECT osm_id,tipo,latitud,longitud,tags,geometria
            FROM infraestructura
        """)).mappings().all()
    return [{
        "osm_id": fila["osm_id"],
        "tipo": fila["tipo"],
        "latitud": float(fila["latitud"]),
        "longitud": float(fila["longitud"]),
        "tags": fila["tags"],
        "geometria": json.loads(fila["geometria"]) if isinstance(fila["geometria"], str) else fila["geometria"],
        "atribucion": "© OpenStreetMap contributors",
    } for fila in filas]


@app.get("/api/geocodificar")
def geocodificar(q: str = Query(min_length=3)):
    raise HTTPException(503, "Geocodificacion no disponible: no hay un proveedor configurado.")


@app.get("/api/ruta")
def ruta(modo: str = "pie", origen: str = "17.0609,-96.7254",
         destino: str = "17.0658,-96.7229"):
    try:
        lat1, lon1 = map(float, origen.split(","))
        lat2, lon2 = map(float, destino.split(","))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "origen y destino deben ser latitud,longitud") from exc
    if modo not in ("pie", "bici"):
        raise HTTPException(400, "modo debe ser pie o bici")
    if not all(math.isfinite(valor) for valor in (lat1, lon1, lat2, lon2)):
        raise HTTPException(400, "Las coordenadas deben ser numeros finitos.")
    limite = limite_oaxaca()
    if not limite.covers(Point(lon1, lat1)) or not limite.covers(Point(lon2, lat2)):
        raise HTTPException(400, "Origen o destino fuera del municipio Oaxaca de Juárez.")
    perfil = "routed-foot" if modo == "pie" else "routed-bike"
    url = (
        f"https://routing.openstreetmap.de/{perfil}/route/v1/driving/"
        f"{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson&"
        "steps=false&alternatives=true"
    )
    cache_dir = RAIZ / "data/processed/rutas"
    cache_dir.mkdir(parents=True, exist_ok=True)
    clave = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cache = cache_dir / f"{clave}.json"
    datos_osrm = None
    if cache.exists():
        try:
            datos_osrm = json.loads(cache.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            datos_osrm = None
    if datos_osrm is None:
        time.sleep(1)
        try:
            respuesta = requests.get(url, timeout=30, headers={"User-Agent": "MapasSegurosOaxaca/1.0"})
            respuesta.raise_for_status()
            datos_osrm = respuesta.json()
            cache.write_text(json.dumps(datos_osrm, ensure_ascii=False), encoding="utf-8")
        except requests.RequestException as exc:
            raise HTTPException(503, f"OSRM no disponible: {exc}") from exc
    rutas = datos_osrm.get("routes", [])
    if datos_osrm.get("code") != "Ok" or not rutas:
        raise HTTPException(502, "OSRM no devolvió una ruta válida")
    rutas_municipales = []
    for candidata in rutas:
        geometria = candidata.get("geometry", {})
        if geometria.get("type") != "LineString" or len(geometria.get("coordinates", [])) < 2:
            raise HTTPException(502, "OSRM devolvio una geometria de ruta invalida.")
        if limite.covers(LineString(geometria["coordinates"])):
            rutas_municipales.append(candidata)
    if not rutas_municipales:
        raise HTTPException(422, "OSRM no devolvio rutas completamente dentro del municipio.")
    rutas = sorted(rutas_municipales, key=lambda candidata: float(candidata["distance"]))
    corta = rutas[0]
    geometria_corta = corta["geometry"]
    distancia_corta = float(corta["distance"])
    duracion_corta = float(corta["duration"])
    propiedades_corta = {
        "distancia_m": round(distancia_corta, 1),
        "duracion_min": round(duracion_corta / 60, 1),
        "indice_historico": None,
        "siniestros_cercanos": None,
    }
    with (RAIZ / "config.yaml").open(encoding="utf-8") as archivo:
        configuracion_riesgo = yaml.safe_load(archivo)["riesgo"]
    radio = configuracion_riesgo["proximidad_ruta_m"]
    df = datos()
    error_exposicion = None
    try:
        exposiciones = exposicion_rutas(
            [candidata["geometry"] for candidata in rutas], df,
            configuracion_riesgo["pesos_gravedad"], radio)
        propiedades_corta.update(indice_historico=exposiciones[0]["indice_historico"],
                                  siniestros_cercanos=exposiciones[0]["siniestros_cercanos"])
    except ValueError as exc:
        error_exposicion = str(exc)
    ruta_corta = {"type": "Feature", "geometry": geometria_corta, "properties": propiedades_corta}
    ruta_alternativa = None
    if len(rutas) > 1:
        indice_alternativa = (min(range(1, len(rutas)),
                                  key=lambda i: (exposiciones[i]["indice_historico"],
                                                 float(rutas[i]["distance"])))
                              if error_exposicion is None else 1)
        alternativa = rutas[indice_alternativa]
        propiedades_alternativa = {
            "distancia_m": round(float(alternativa["distance"]), 1),
            "duracion_min": round(float(alternativa["duration"]) / 60, 1),
            "indice_historico": None, "siniestros_cercanos": None,
        }
        if error_exposicion is None:
            propiedades_alternativa.update(exposiciones[indice_alternativa])
        ruta_alternativa = {"type": "Feature", "geometry": alternativa["geometry"],
                            "properties": propiedades_alternativa}
    menor_exposicion = None
    reduccion = None
    if error_exposicion is None:
        menor_exposicion = ruta_corta
        if (ruta_alternativa and
                ruta_alternativa["properties"]["indice_historico"] < propiedades_corta["indice_historico"]):
            menor_exposicion = ruta_alternativa
        if propiedades_corta["indice_historico"] > 0:
            reduccion = round(100 * (propiedades_corta["indice_historico"] -
                              menor_exposicion["properties"]["indice_historico"]) /
                              propiedades_corta["indice_historico"], 2)
    return {
        "ruta_corta": ruta_corta,
        "ruta_alternativa": ruta_alternativa,
        "ruta_menor_exposicion": menor_exposicion,
        "reduccion_indice_historico_pct": reduccion,
        "radio_m": radio,
        "rutas_comparadas": len(rutas),
        "error_exposicion": error_exposicion,
        "nota": "Ruta más corta y comparación de siniestros históricos cercanos entre las alternativas devueltas por OSRM; "
                "no optimiza todas las rutas posibles, no es probabilidad de accidente ni garantiza seguridad. No incluye aforos, "
                "accidentes sin coordenadas ni riesgo fuera de Oaxaca de Juárez.",
        "modo": modo,
        "atribucion": "© OpenStreetMap contributors",
    }


def limite_oaxaca():
    cargar_env()
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("mysql"):
        raise HTTPException(503, "No hay una base MySQL real disponible")
    engine = create_engine(url, pool_pre_ping=True)
    if not inspect(engine).has_table("limite_municipal"):
        raise HTTPException(503, "Falta el limite municipal OSM 20067; ejecute el ETL de infraestructura.")
    with engine.connect() as conexion:
        geometria = conexion.execute(text(
            "SELECT geometria FROM limite_municipal WHERE clave='20067'"
        )).scalar_one_or_none()
    if not geometria:
        raise HTTPException(503, "Falta el limite municipal OSM 20067; ejecute el ETL de infraestructura.")
    limite = shape(json.loads(geometria) if isinstance(geometria, str) else geometria)
    if limite.is_empty or not limite.is_valid:
        raise HTTPException(503, "El limite municipal OSM almacenado es invalido.")
    return limite


@app.get("/api/autoridades/kpis")
def kpis(fecha_ini: date | None = None, fecha_fin: date | None = None,
         usuario=Depends(autoridad_actual)):
    df = filtrar_periodo(datos(), fecha_ini, fecha_fin)
    if df.empty:
        return {"total_siniestros": 0, "muertos": 0, "heridos": 0, "porcentaje_vulnerables": 0,
                "fuente": "inegi_atus"}
    vulnerables = df["usuarios_afectados"].fillna("").str.split(",").map(
        lambda tipos: bool({"peaton", "ciclista"}.intersection(tipos))
    ).sum()
    return {"total_siniestros": len(df),
            "muertos": int(df["num_muertos"].sum()),
            "heridos": int(df["num_heridos"].sum()),
            "porcentaje_vulnerables": round(vulnerables/len(df)*100, 2),
            "nota_vulnerables": "Porcentaje de siniestros con peatones o ciclistas lesionados o fallecidos; motociclistas no identificables por tipo de victima.",
            "fuente": "inegi_atus"}


@app.get("/api/autoridades/ranking-tramos")
def ranking_tramos(usuario=Depends(autoridad_actual)):
    raise HTTPException(503, "El ranking por tramo aun no esta disponible.")


@app.get("/api/autoridades/ranking-vialidades")
def ranking_vialidades(fecha_ini: date | None = None, fecha_fin: date | None = None,
                       usuario=Depends(autoridad_actual)):
    validar_periodo(fecha_ini, fecha_fin)
    cargar_env()
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("mysql"):
        raise HTTPException(503, "No hay una base MySQL real disponible")
    engine = create_engine(url, pool_pre_ping=True)
    condiciones = ["g.calle1 IS NOT NULL", "TRIM(g.calle1)<>''", "s.fuente='inegi_atus'"]
    parametros = {}
    if fecha_ini:
        condiciones.append("s.fecha_hora >= :fecha_ini")
        parametros["fecha_ini"] = fecha_ini
    if fecha_fin:
        condiciones.append("s.fecha_hora < :fecha_fin")
        parametros["fecha_fin"] = fecha_fin + timedelta(days=1)
    with engine.connect() as conexion:
        filas = conexion.execute(text("""
            SELECT TRIM(g.calle1) AS calle1, NULLIF(TRIM(g.calle2),'') AS calle2,
                   COUNT(*) AS siniestros, SUM(s.num_muertos) AS muertos,
                   SUM(s.num_heridos) AS heridos
            FROM siniestro_georreferencia g
            JOIN analytics_siniestro s ON s.id=g.siniestro_id
            WHERE """ + " AND ".join(condiciones) + """
            GROUP BY TRIM(g.calle1), NULLIF(TRIM(g.calle2),'')
            ORDER BY siniestros DESC, calle1, calle2
            LIMIT 20
        """), parametros).mappings().all()
    return {"resultados": [dict(fila) for fila in filas],
            "nota": "Conteos por nombres de vialidades reportados por ATUS; "
                    "no representan tramos geométricos ni riesgo ajustado por tráfico."}


@app.get("/api/autoridades/ranking-colonias")
def ranking_colonias(usuario=Depends(autoridad_actual)):
    raise HTTPException(503, "No hay una fuente de colonias vinculada a los siniestros.")


@app.get("/api/autoridades/puntos-criticos")
def puntos_criticos(fecha_ini: date | None = None, fecha_fin: date | None = None,
                    usuario=Depends(autoridad_actual)):
    df = filtrar_periodo(datos(), fecha_ini, fecha_fin)
    if df.empty:
        return []
    agrupado = df.groupby([df["latitud"].round(3), df["longitud"].round(3)]).size().sort_values(ascending=False)
    return [{"ranking": i, "latitud": lat, "longitud": lon, "siniestros": int(cantidad)}
            for i, ((lat, lon), cantidad) in enumerate(agrupado.head(20).items(), 1)]


@app.get("/api/autoridades/tendencia")
def tendencia(fecha_ini: date | None = None, fecha_fin: date | None = None,
              usuario=Depends(autoridad_actual)):
    df = filtrar_periodo(datos(), fecha_ini, fecha_fin)
    if df.empty:
        return []
    serie = df.groupby(df["fecha_hora"].dt.to_period("M").astype(str)).size()
    return [{"periodo": periodo, "siniestros": int(cantidad)} for periodo, cantidad in serie.items()]


@app.get("/api/autoridades/matriz-hora-dia")
def matriz(fecha_ini: date | None = None, fecha_fin: date | None = None,
           usuario=Depends(autoridad_actual)):
    df = filtrar_periodo(datos(), fecha_ini, fecha_fin)
    if df.empty:
        return []
    dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    matriz = df.assign(dia=df["fecha_hora"].dt.dayofweek, hora=df["fecha_hora"].dt.hour).groupby(["dia", "hora"]).size()
    return [{"dia": dias[dia], "hora": hora, "siniestros": int(cantidad)}
            for (dia, hora), cantidad in matriz.items()]


@app.get("/api/autoridades/comparativo-inegi")
def comparativo(fecha_ini: date | None = None, fecha_fin: date | None = None,
                usuario=Depends(autoridad_actual)):
    df = filtrar_periodo(datos(), fecha_ini, fecha_fin)
    if df.empty:
        return []
    municipal = df.groupby(df["fecha_hora"].dt.year).size()
    cargar_env()
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("mysql"):
        raise HTTPException(503, "No hay una base MySQL real disponible")
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conexion:
        indicadores = conexion.execute(text("""
            SELECT anio, valor, fuente_dato FROM indicador_anual
            WHERE clave_indicador='1006000039'
        """)).mappings().all()
    por_anio = {
        fila["anio"]: fila for fila in indicadores
        if (not fecha_ini or fecha_ini <= date(fila["anio"], 1, 1))
        and (not fecha_fin or fecha_fin >= date(fila["anio"], 12, 31))
    }
    return [{"anio": int(anio), "municipal_dw": int(municipal.get(anio, 0)),
             "inegi_estatal": por_anio[anio]["valor"] if anio in por_anio else None,
             "fuente_dato": por_anio[anio]["fuente_dato"] if anio in por_anio else None,
             "nota": ("INEGI estatal anual no comparable con el periodo seleccionado"
                      if anio not in por_anio and (fecha_ini or fecha_fin)
                      else "Indicador estatal no disponible" if anio not in por_anio
                      else "INEGI estatal; ATUS municipal")}
            for anio in sorted(set(municipal.index).union(por_anio))]


@app.get("/api/autoridades/calidad-datos")
def calidad(fecha_ini: date | None = None, fecha_fin: date | None = None,
            usuario=Depends(autoridad_actual)):
    df = filtrar_periodo(datos(), fecha_ini, fecha_fin)
    if df.empty:
        return {"siniestros": 0, "georreferenciados": 0, "por_anio": []}
    df = df.assign(georreferenciado=df["latitud"].notna() & df["longitud"].notna())
    anios = df.groupby(df["fecha_hora"].dt.year).agg(
        siniestros=("fecha_hora", "size"), georreferenciados=("georreferenciado", "sum"))
    return {
        "siniestros": len(df),
        "georreferenciados": int(df["georreferenciado"].sum()),
        "fuentes": {str(k): int(v) for k, v in df["fuente"].value_counts().items()},
        "por_anio": [{"anio": int(anio), "siniestros": int(fila["siniestros"]),
                      "georreferenciados": int(fila["georreferenciados"])}
                     for anio, fila in anios.iterrows()],
        "nota": "La georreferenciacion se basa en coincidencias unicas de atributos; puede haber siniestros sin coordenadas.",
    }


@app.get("/api/autoridades/reporte.csv")
def reporte_csv(fecha_ini: date | None = None, fecha_fin: date | None = None,
                usuario=Depends(autoridad_actual)):
    df = filtrar_periodo(datos(), fecha_ini, fecha_fin)
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["kpi", "valor"])
    escritor.writerow(["fecha_ini", fecha_ini.isoformat() if fecha_ini else "inicio"])
    escritor.writerow(["fecha_fin", fecha_fin.isoformat() if fecha_fin else "fin"])
    escritor.writerow(["total_siniestros", len(df)])
    escritor.writerow(["muertos", int(df["num_muertos"].sum()) if not df.empty else 0])
    escritor.writerow(["heridos", int(df["num_heridos"].sum()) if not df.empty else 0])
    return StreamingResponse(io.BytesIO(salida.getvalue().encode("utf-8-sig")),
                             media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=reporte_siniestros.csv"})


@app.get("/api/autoridades/reporte.pdf")
def reporte_pdf(fecha_ini: date | None = None, fecha_fin: date | None = None,
                usuario=Depends(autoridad_actual)):
    df = filtrar_periodo(datos(), fecha_ini, fecha_fin)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.setTitle("Reporte de siniestros")
    pdf.drawString(50, 750, "Reporte de siniestros viales - Oaxaca de Juarez")
    pdf.drawString(50, 735, "Fuente: INEGI ATUS")
    pdf.drawString(50, 720, f"Periodo: {fecha_ini or 'inicio'} a {fecha_fin or 'fin'}")
    pdf.drawString(50, 705, f"Total: {len(df)}")
    pdf.drawString(50, 690, f"Muertos: {int(df['num_muertos'].sum()) if not df.empty else 0}")
    pdf.drawString(50, 675, f"Heridos: {int(df['num_heridos'].sum()) if not df.empty else 0}")
    pdf.drawString(50, 660, "Limitacion: subregistro y falta de aforos.")
    pdf.drawString(50, 645, "© OpenStreetMap contributors")
    pdf.save()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf",
                             headers={"Content-Disposition": "attachment; filename=reporte_siniestros.pdf"})
