import pandas as pd
import pytest

from api.riesgo import exposicion_rutas


def test_exposicion_cuenta_cada_accidente_cercano_una_vez():
    accidentes = pd.DataFrame([
        {"longitud": -96.725, "latitud": 17.061, "gravedad": "herido"},
        {"longitud": -96.725, "latitud": 17.061, "gravedad": "muerto"},
        {"longitud": -96.735, "latitud": 17.061, "gravedad": "solo danos"},
        {"longitud": None, "latitud": None, "gravedad": "muerto"},
    ])
    rutas = [
        {"type": "LineString", "coordinates": [[-96.726, 17.061], [-96.724, 17.061]]},
        {"type": "LineString", "coordinates": [[-96.736, 17.061], [-96.734, 17.061]]},
    ]
    resultado = exposicion_rutas(rutas, accidentes, {"solo danos": 1, "herido": 3, "muerto": 10}, 50)
    assert resultado == [{"siniestros_cercanos": 2, "indice_historico": 13.0},
                         {"siniestros_cercanos": 1, "indice_historico": 1.0}]


def test_exposicion_sin_coordenadas_falla():
    datos = pd.DataFrame([{"longitud": None, "latitud": None, "gravedad": "muerto"}])
    with pytest.raises(ValueError, match="No hay siniestros georreferenciados"):
        exposicion_rutas([], datos, {"muerto": 10}, 50)


def test_gravedad_desconocida_no_se_inventa():
    datos = pd.DataFrame([{"longitud": -96.725, "latitud": 17.061, "gravedad": "desconocida"}])
    with pytest.raises(ValueError, match="Gravedades sin peso"):
        exposicion_rutas([], datos, {"muerto": 10}, 50)


def test_api_compara_alternativas_sin_afirmar_seguridad(monkeypatch, tmp_path):
    import api.main as main
    (tmp_path / "config.yaml").write_text(
        'riesgo:\n  proximidad_ruta_m: 50\n  pesos_gravedad: {"solo danos": 1, "herido": 3, "muerto": 10}\n',
        encoding="utf-8")
    monkeypatch.setattr(main, "RAIZ", tmp_path)
    from shapely.geometry import box
    monkeypatch.setattr(main, "limite_oaxaca", lambda: box(-97, 16, -96, 18))
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    monkeypatch.setattr(main, "datos", lambda: pd.DataFrame([
        {"longitud": -96.725, "latitud": 17.061, "gravedad": "herido"},
        {"longitud": -96.735, "latitud": 17.061, "gravedad": "herido"},
        {"longitud": -96.745, "latitud": 17.061, "gravedad": "solo danos"}]))
    class Respuesta:
        def raise_for_status(self):
            pass
        def json(self):
            return {"code": "Ok", "routes": [
                {"geometry": {"type": "LineString", "coordinates": [[-96.736, 17.061], [-96.734, 17.061]]},
                 "distance": 300, "duration": 110},
                {"geometry": {"type": "LineString", "coordinates": [[-96.726, 17.061], [-96.724, 17.061]]},
                 "distance": 200, "duration": 120},
                {"geometry": {"type": "LineString", "coordinates": [[-96.746, 17.061], [-96.744, 17.061]]},
                 "distance": 400, "duration": 180}]}
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: Respuesta())
    resultado = main.ruta(origen="17.061,-96.726", destino="17.061,-96.724")
    assert resultado["ruta_corta"]["properties"]["indice_historico"] == 3
    assert resultado["ruta_menor_exposicion"]["properties"]["indice_historico"] == 1
    assert resultado["ruta_alternativa"]["properties"]["distancia_m"] == 400
    assert resultado["rutas_comparadas"] == 3
    assert resultado["reduccion_indice_historico_pct"] == 66.67
    assert "no es probabilidad" in resultado["nota"]


@pytest.mark.parametrize("origen,destino", [
    ("17.0,-98.0", "17.0,-96.7"),
    ("17.0,-96.7", "18.1,-96.7"),
    ("nan,-96.7", "17.0,-96.7"),
])
def test_ruta_rechaza_puntos_fuera_o_no_finitos(monkeypatch, origen, destino):
    import api.main as main
    from fastapi import HTTPException
    from shapely.geometry import box
    monkeypatch.setattr(main, "limite_oaxaca", lambda: box(-97, 16, -96, 18))
    with pytest.raises(HTTPException) as error:
        main.ruta(origen=origen, destino=destino)
    assert error.value.status_code == 400


def test_ruta_rechaza_geometria_que_sale_del_municipio(monkeypatch, tmp_path):
    import api.main as main
    from fastapi import HTTPException
    from shapely.geometry import box
    monkeypatch.setattr(main, "RAIZ", tmp_path)
    monkeypatch.setattr(main, "limite_oaxaca", lambda: box(-97, 16, -96, 18))
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    class Respuesta:
        def raise_for_status(self):
            pass
        def json(self):
            return {"code": "Ok", "routes": [
                {"geometry": {"type": "LineString", "coordinates": [
                    [-96.7, 17], [-98, 17], [-96.8, 17]]}, "distance": 300, "duration": 180}]}
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: Respuesta())
    with pytest.raises(HTTPException) as error:
        main.ruta(origen="17,-96.7", destino="17,-96.8")
    assert error.value.status_code == 422


def test_limite_faltante_informa_como_cargarlo(monkeypatch):
    import api.main as main
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    engine = create_engine("sqlite://")
    monkeypatch.setenv("DATABASE_URL", "mysql://example")
    monkeypatch.setattr(main, "create_engine", lambda *args, **kwargs: engine)
    with pytest.raises(HTTPException, match="ETL de infraestructura") as error:
        main.limite_oaxaca()
    assert error.value.status_code == 503
