import csv
import logging
from pathlib import Path
import shutil

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from etl.georreferenciar import ANUAL, GEO, preparar_georreferencias, preparar_todos


FIXTURES = Path(__file__).parent / "fixtures"


def fuentes(tmp_path):
    shutil.copy(FIXTURES / "geo_2025_micro.csv", tmp_path / ANUAL)
    shutil.copy(FIXTURES / "geo_2025_geografico.csv", tmp_path / GEO)


def agregar_fila(ruta, **cambios):
    with ruta.open(encoding="utf-8", newline="") as archivo:
        lector = csv.DictReader(archivo)
        columnas = lector.fieldnames
        fila = next(lector)
    fila.update(cambios)
    with ruta.open("a", encoding="utf-8", newline="") as archivo:
        csv.DictWriter(archivo, fieldnames=columnas).writerow(fila)


def test_union_real_y_filtro_municipal(tmp_path):
    fuentes(tmp_path)
    agregar_fila(tmp_path / GEO, CVE_MUN="068", ID="otro")
    pares, resumen = preparar_georreferencias(tmp_path, logging.getLogger("test"))
    assert resumen["filas"] == 2
    assert resumen["filas_municipio"] == 1
    assert resumen["coincidencias_unicas"] == 1
    assert pares[0]["fila_anual"] == pares[0]["fila_geo"] == 2
    assert pares[0]["longitud"] == float("-96.730975979999997")
    assert pares[0]["calle1"] == "FERROCARRIL"


def test_no_asigna_coordenadas_a_coincidencias_ambiguas(tmp_path):
    fuentes(tmp_path)
    agregar_fila(tmp_path / ANUAL)
    pares, resumen = preparar_georreferencias(tmp_path, logging.getLogger("test"))
    assert pares == []
    assert resumen["ambiguos"] == 1


def test_falla_sin_microdatos(tmp_path):
    fuentes(tmp_path)
    (tmp_path / ANUAL).unlink()
    with pytest.raises(RuntimeError, match="Falta"):
        preparar_georreferencias(tmp_path, logging.getLogger("test"))


def test_falla_con_coordenadas_invalidas(tmp_path):
    fuentes(tmp_path)
    ruta = tmp_path / GEO
    contenido = ruta.read_text(encoding="utf-8").replace("17.049406319999999", "999")
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(RuntimeError, match="coordenadas fuera de rango"):
        preparar_georreferencias(tmp_path, logging.getLogger("test"))


def test_encuentra_geograficos_de_otros_anios_y_microdatos_crudos(tmp_path):
    manual = tmp_path / "data" / "manual" / "atus"
    raw = tmp_path / "data" / "raw" / "inegi_atus"
    manual.mkdir(parents=True)
    raw.mkdir(parents=True)
    micro = (FIXTURES / "geo_2025_micro.csv").read_text(encoding="utf-8").replace("2025", "2020")
    geo = (FIXTURES / "geo_2025_geografico.csv").read_text(encoding="utf-8").replace("2025", "2020")
    (raw / "2026-11-18_atus_anual_2020.csv").write_text(micro, encoding="utf-8")
    (manual / "BASE GEORREFERENCIADOS_2020.csv").write_text(geo, encoding="utf-8")
    resultados = preparar_todos(tmp_path, logging.getLogger("test"))
    assert len(resultados) == 1
    pares, resumen = resultados[0]
    assert resumen["anio"] == 2020
    assert len(pares) == 1
    assert pares[0]["archivo_anual"] == "atus_anual_2020.csv"


def test_api_aplica_limite_despues_de_filtrar_coordenadas(monkeypatch):
    from api import main
    comun = {"fecha_hora": pd.Timestamp("2025-01-01 20:00"), "gravedad": "solo danos",
             "tipo_usuario": "otro", "tipo_siniestro": "colision",
             "fuente": "inegi_atus", "id_origen": "archivo:2"}
    filas = pd.DataFrame([{**comun, "latitud": None, "longitud": None},
                          {**comun, "latitud": 17.04940632, "longitud": -96.73097598}])
    monkeypatch.setattr(main, "datos", lambda: filas)
    respuesta = TestClient(main.app).get("/api/siniestros?limite=1")
    assert respuesta.status_code == 200
    assert respuesta.json()["total_georreferenciados"] == 1
    assert len(respuesta.json()["features"]) == 1


def test_filtro_tipo_usuario_usa_victimas(monkeypatch):
    from api import main
    filas = pd.DataFrame([{
        "fecha_hora": pd.Timestamp("2025-01-01 20:00"), "gravedad": "herido",
        "tipo_usuario": "otro", "usuarios_afectados": "peaton,pasajero",
        "tipo_siniestro": "colision", "fuente": "inegi_atus", "id_origen": "archivo:2",
        "latitud": 17.04940632, "longitud": -96.73097598,
    }])
    monkeypatch.setattr(main, "datos", lambda: filas)
    cliente = TestClient(main.app)
    assert len(cliente.get("/api/siniestros?tipo_usuario=peaton").json()["features"]) == 1
    assert not cliente.get("/api/siniestros?tipo_usuario=ciclista").json()["features"]
    assert not cliente.get("/api/siniestros?tipo_usuario=otro").json()["features"]
