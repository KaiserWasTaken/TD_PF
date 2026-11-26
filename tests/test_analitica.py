import pytest
from sqlalchemy import create_engine, text

from etl.analitica import refrescar_analitica


@pytest.fixture
def conexion():
    engine = create_engine("sqlite://")
    with engine.begin() as con:
        for ddl in (
            """CREATE TABLE analytics_siniestro (id INTEGER PRIMARY KEY, fecha_hora TEXT,
               tipo_siniestro TEXT, gravedad TEXT, num_muertos INTEGER, num_heridos INTEGER,
               latitud REAL, longitud REAL, calidad_geo TEXT, fuente TEXT)""",
            "CREATE TABLE tipo_usuario_victima (id INTEGER PRIMARY KEY, nombre TEXT)",
            """CREATE TABLE siniestro_victima (siniestro_id INTEGER, tipo_usuario_id INTEGER,
               num_muertos INTEGER, num_heridos INTEGER)""",
            "CREATE TABLE dim_hora (hora_key INTEGER PRIMARY KEY)",
            """CREATE TABLE dim_tiempo (tiempo_key INTEGER PRIMARY KEY, fecha DATE, anio INTEGER,
               mes INTEGER, nombre_mes TEXT, dia_semana TEXT, es_fin_de_semana INTEGER)""",
            """CREATE TABLE dim_siniestro_tipo (siniestro_tipo_key INTEGER PRIMARY KEY,
               tipo_siniestro TEXT, gravedad TEXT, tipo_usuario TEXT, es_vulnerable INTEGER,
               UNIQUE(tipo_siniestro,gravedad,tipo_usuario))""",
            """CREATE TABLE fact_siniestro (siniestro_id INTEGER PRIMARY KEY, tiempo_key INTEGER,
               hora_key INTEGER, ubicacion_key INTEGER, siniestro_tipo_key INTEGER,
               num_siniestros INTEGER, num_muertos INTEGER, num_heridos INTEGER,
               peso_gravedad INTEGER, calidad_geo TEXT, fuente TEXT)""",
            """CREATE TABLE mart_ciudadania_siniestros_publicos
               (id INTEGER PRIMARY KEY, fecha_hora TEXT, tipo_siniestro TEXT, tipo_usuario TEXT,
                gravedad TEXT, latitud REAL, longitud REAL)""",
            """CREATE TABLE mart_autoridades_kpi_resumen
               (id INTEGER PRIMARY KEY, total_siniestros INTEGER, muertos INTEGER, heridos INTEGER)""",
        ):
            con.execute(text(ddl))
        con.execute(text("""INSERT INTO analytics_siniestro VALUES
            (1,'2024-02-29 12:45:00','colision','herido',0,2,17,-96,'original','inegi_atus'),
            (2,'2024-03-02 09:00:00','colision','solo danos',0,0,NULL,NULL,'no_resuelta','inegi_atus')"""))
        con.execute(text("INSERT INTO tipo_usuario_victima VALUES (1,'peaton'),(2,'conductor')"))
        con.execute(text("INSERT INTO siniestro_victima VALUES (1,1,0,1),(1,2,0,1)"))
        con.execute(text("INSERT INTO dim_hora VALUES (9),(12)"))
        yield con


def test_refresca_hechos_marts_y_fechas_reales_de_forma_idempotente(conexion):
    pesos = {"solo danos": 1, "herido": 3}
    for _ in range(2):
        resumen = refrescar_analitica(conexion, pesos)
        assert resumen == {"hechos": 2, "siniestros_publicos": 2, "muertos": 0, "heridos": 2}
        assert conexion.execute(text("SELECT COUNT(*) FROM fact_siniestro")).scalar_one() == 2
        assert conexion.execute(text("SELECT COUNT(*) FROM mart_ciudadania_siniestros_publicos")).scalar_one() == 2
    fila = conexion.execute(text("""
        SELECT f.tiempo_key,f.hora_key,f.peso_gravedad,t.tipo_usuario,t.es_vulnerable,d.dia_semana
        FROM fact_siniestro f JOIN dim_siniestro_tipo t ON t.siniestro_tipo_key=f.siniestro_tipo_key
        JOIN dim_tiempo d ON d.tiempo_key=f.tiempo_key WHERE f.siniestro_id=1
    """)).one()
    assert tuple(fila) == (20240229, 12, 3, "multiples_con_vulnerables", 1, "jueves")
    assert conexion.execute(text(
        "SELECT tipo_usuario FROM mart_ciudadania_siniestros_publicos WHERE id=1"
    )).scalar_one() is None
    assert tuple(conexion.execute(text(
        "SELECT total_siniestros,muertos,heridos FROM mart_autoridades_kpi_resumen"
    )).one()) == (2, 0, 2)


def test_analitica_rechaza_fuente_sintetica_sin_modificar_marts(conexion):
    refrescar_analitica(conexion, {"solo danos": 1, "herido": 3})
    conexion.execute(text("UPDATE analytics_siniestro SET fuente='sintetico' WHERE id=1"))
    with pytest.raises(RuntimeError, match="exclusivamente siniestros INEGI ATUS"):
        refrescar_analitica(conexion, {"solo danos": 1, "herido": 3})
    assert conexion.execute(text("SELECT COUNT(*) FROM fact_siniestro")).scalar_one() == 2


def test_analitica_falla_sin_datos_o_pesos(conexion):
    with pytest.raises(RuntimeError, match="Peso de gravedad"):
        refrescar_analitica(conexion, {})
    conexion.execute(text("DELETE FROM analytics_siniestro"))
    with pytest.raises(RuntimeError, match="No hay siniestros reales"):
        refrescar_analitica(conexion, {})


def test_analitica_rechaza_victimas_incoherentes_o_horas_faltantes(conexion):
    pesos = {"solo danos": 1, "herido": 3}
    conexion.execute(text("UPDATE siniestro_victima SET num_heridos=0 WHERE tipo_usuario_id=1"))
    with pytest.raises(RuntimeError, match="conteos o tipos de victimas"):
        refrescar_analitica(conexion, pesos)
    conexion.execute(text("UPDATE siniestro_victima SET num_heridos=1 WHERE tipo_usuario_id=1"))
    conexion.execute(text("DELETE FROM dim_hora WHERE hora_key=12"))
    with pytest.raises(RuntimeError, match="Falta la hora 12"):
        refrescar_analitica(conexion, pesos)
