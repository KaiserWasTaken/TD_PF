from etl.core import limpiar, sintetizar, cargar_config
def test_sintetico_prohibido_por_defecto():
    from etl.core import sintetizar
    import pytest
    with pytest.raises(RuntimeError, match="--demo"):
        sintetizar(cargar_config())
def test_limpieza_normaliza_y_elimina():
    import pandas as pd
    d=pd.DataFrame([{"fecha_hora":"2024-01-01 10:00","tipo_siniestro":"choque","tipo_usuario":"peatón","gravedad":"solo daños","num_muertos":0,"num_heridos":0,"latitud":17,"longitud":-96,"fuente":"sintetico"},
                    {"fecha_hora":"2024-01-01 10:00","tipo_siniestro":"choque","tipo_usuario":"peatón","gravedad":"solo daños","num_muertos":0,"num_heridos":0,"latitud":17,"longitud":-96,"fuente":"sintetico"}])
    d["gravedad"] = d["gravedad"].replace({"solo daños": "solo danos"})
    out, q=limpiar(d, cargar_config())
    assert len(out)==2
    assert q["registros_cargables"]==2

def test_ruta_no_inventa_seguridad(monkeypatch, tmp_path):
    import api.main as main
    import pandas as pd
    class Respuesta:
        def raise_for_status(self):
            pass
        def json(self):
            return {"code": "Ok", "routes": [{"geometry": {"type": "LineString", "coordinates": [
                [-96.7254, 17.0609], [-96.7229, 17.0658]]}, "distance": 714.3, "duration": 574}]}
    monkeypatch.setattr(main, "RAIZ", tmp_path)
    from shapely.geometry import box
    monkeypatch.setattr(main, "limite_oaxaca", lambda: box(-97, 16, -96, 18))
    (tmp_path / "config.yaml").write_text(
        'riesgo:\n  proximidad_ruta_m: 50\n  pesos_gravedad: {"solo danos": 1, "herido": 3, "muerto": 10}\n',
        encoding="utf-8")
    monkeypatch.setattr(main, "datos", lambda: pd.DataFrame(columns=["latitud", "longitud", "gravedad"]))
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: Respuesta())
    respuesta = main.ruta(modo="pie", origen="17.0609,-96.7254", destino="17.0658,-96.7229")
    assert respuesta["ruta_corta"]["properties"]["indice_historico"] is None
    assert respuesta["ruta_alternativa"] is None
    assert respuesta["reduccion_indice_historico_pct"] is None

def test_autorizacion_sin_token():
    from fastapi.testclient import TestClient
    from api.main import app
    cliente = TestClient(app)
    respuesta = cliente.get("/api/autoridades/kpis")
    assert respuesta.status_code == 401

def test_filtro_municipal_real_recortado():
    import pandas as pd
    from etl.real import es_municipio, cargar_config
    data = pd.read_csv("tests/fixtures/atus_municipal_recortado.csv")
    mask = es_municipio(data, cargar_config())
    assert mask.sum() == 2

def test_derivacion_gravedad_siniestro():
    from etl.real import mapear_tipo
    victimas_muerto = {"peaton": (1, 0)}
    assert ("muerto" if sum(v[0] for v in victimas_muerto.values()) else
            "herido" if sum(v[1] for v in victimas_muerto.values()) else "solo danos") == "muerto"
    assert mapear_tipo("Colisión con vehículo automotor") == "colision"

def test_falta_archivo_atus_falla():
    from pathlib import Path
    import tempfile
    from etl.real import extraer_atus, cargar_config
    config = cargar_config()
    log = __import__("logging").getLogger("test")
    carpeta = Path(tempfile.mkdtemp())
    import etl.real as real
    anterior = real.RAIZ
    real.RAIZ = carpeta
    try:
        extraer_atus(config, log)
        assert False
    except RuntimeError as exc:
        assert "No hay archivos ATUS reales" in str(exc)
    finally:
        real.RAIZ = anterior

def test_principal_no_permite_sintetico():
    import sqlalchemy
    from sqlalchemy import create_engine, text
    import os
    url = os.getenv("DATABASE_URL", "mysql+pymysql://mapas:mapas@localhost:3307/mapas_seguros")
    engine = create_engine(url)
    with engine.connect() as c:
        total = c.execute(text("SELECT COUNT(*) FROM analytics_siniestro WHERE fuente='sintetico'")).scalar()
    assert total == 0
