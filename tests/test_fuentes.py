import json
import logging

import pytest
from sqlalchemy import create_engine, text

from etl import real


def test_infraestructura_preserva_geometria_y_falla_sin_fuente():
    engine = create_engine("sqlite://")
    with engine.begin() as conexion:
        conexion.execute(text("""CREATE TABLE infraestructura (
            osm_id TEXT PRIMARY KEY, tipo TEXT, latitud REAL, longitud REAL, tags TEXT, geometria TEXT)"""))
        conexion.execute(text("""CREATE TABLE raw_catalogo_fuentes (
            id INTEGER PRIMARY KEY, fuente TEXT, url TEXT, formato TEXT, licencia TEXT,
            fecha_descarga TEXT, hash_sha256 TEXT, filas INTEGER, filas_municipio INTEGER, estatus TEXT)"""))
        conexion.execute(text("""CREATE TABLE limite_municipal (
            clave TEXT PRIMARY KEY, geometria TEXT, osm_id TEXT, hash_archivo TEXT)"""))
        limite = {"type": "relation", "id": 123, "tags": {"INEGI:MUNID": "20067"},
                  "members": [{"type": "way", "role": "outer", "geometry": [
                      {"lon": -96.1, "lat": 16.9}, {"lon": -95.9, "lat": 16.9},
                      {"lon": -95.9, "lat": 17.1}, {"lon": -96.1, "lat": 17.1},
                      {"lon": -96.1, "lat": 16.9}]}]}
        entrada = {"elements": [
            {"type": "area", "id": 1, "tags": {"INEGI:MUNID": "20067"}},
            limite,
            {"type": "node", "id": 2, "lat": 17, "lon": -96, "tags": {"highway": "traffic_signals"}},
            {"type": "way", "id": 3, "geometry": [{"lat": 17, "lon": -96},
                                                     {"lat": 17.01, "lon": -96.01}],
             "tags": {"highway": "cycleway"}},
            {"type": "way", "id": 4, "geometry": [{"lat": 17, "lon": -96},
                                                     {"lat": 17.01, "lon": -96.01}],
             "tags": {"highway": "residential", "cycleway": "no"}},
        ]}
        assert real.cargar_infraestructura(conexion, entrada, "osm.json", "abc") == 2
        assert real.cargar_infraestructura(conexion, entrada, "osm.json", "abc") == 2
        assert conexion.execute(text("SELECT COUNT(*) FROM raw_catalogo_fuentes")).scalar_one() == 1
        assert conexion.execute(text("SELECT filas_municipio FROM raw_catalogo_fuentes")).scalar_one() == 2
        via = conexion.execute(text("SELECT geometria FROM infraestructura WHERE osm_id='way:3'")).scalar_one()
        assert json.loads(via)["coordinates"] == [[-96, 17], [-96.01, 17.01]]
        with pytest.raises(RuntimeError, match="infraestructura utilizable"):
            real.cargar_infraestructura(conexion, {"elements": [limite]}, "osm.json", "def")
        assert conexion.execute(text("SELECT COUNT(*) FROM infraestructura")).scalar_one() == 2


def test_overpass_rechaza_limite_incorrecto(monkeypatch, tmp_path):
    class Respuesta:
        content = b'{"elements":[]}'
        def raise_for_status(self):
            pass
        def json(self):
            return {"elements": [{"type": "area", "tags": {"INEGI:MUNID": "20068"}},
                                  {"type": "node", "id": 1}]}
    monkeypatch.setattr(real, "RAIZ", tmp_path)
    monkeypatch.setattr(real, "cargar_config", lambda: {"extraccion": {"reintentos": 1, "timeout_s": 1}})
    monkeypatch.setattr(real.requests, "get", lambda *args, **kwargs: Respuesta())
    with pytest.raises(RuntimeError, match="unico limite municipal INEGI 20067"):
        real.extraer_overpass(logging.getLogger("test"))


def test_limite_con_hueco_y_limite_incompleto():
    from shapely.geometry import Point
    def via(rol, coordenadas):
        return {"type": "way", "role": rol,
                "geometry": [{"lon": lon, "lat": lat} for lon, lat in coordenadas]}
    exterior = [(0, 0), (3, 0), (3, 3), (0, 3), (0, 0)]
    interior = [(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)]
    limite = real.poligono_municipal({"members": [via("outer", exterior), via("inner", interior)]})
    assert limite.covers(Point(0.5, 0.5))
    assert not limite.covers(Point(1.5, 1.5))
    with pytest.raises(RuntimeError, match="anillos cerrados"):
        real.poligono_municipal({"members": [via("outer", exterior[:-1])]})
