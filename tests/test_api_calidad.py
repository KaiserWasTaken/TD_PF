from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import main
from etl import real


def datos_por_periodo():
    return pd.DataFrame([
        {"fecha_hora": "2025-01-31 00:00:00", "gravedad": "herido",
         "num_muertos": 0, "num_heridos": 1, "usuarios_afectados": "peaton"},
        {"fecha_hora": "2025-01-31 23:59:00", "gravedad": "muerto",
         "num_muertos": 1, "num_heridos": 0, "usuarios_afectados": "ciclista"},
        {"fecha_hora": "2025-02-01 00:00:00", "gravedad": "solo danos",
         "num_muertos": 0, "num_heridos": 0, "usuarios_afectados": ""},
    ]).assign(fecha_hora=lambda df: pd.to_datetime(df["fecha_hora"]))


def test_kpis_filtra_periodo_inclusivo(monkeypatch):
    monkeypatch.setattr(main, "datos", datos_por_periodo)

    resultado = main.kpis(fecha_ini=date(2025, 1, 31), fecha_fin=date(2025, 1, 31))

    assert resultado["total_siniestros"] == 2
    assert resultado["muertos"] == 1
    assert resultado["heridos"] == 1
    assert resultado["porcentaje_vulnerables"] == 100


def test_tendencia_filtra_el_mismo_periodo(monkeypatch):
    monkeypatch.setattr(main, "datos", datos_por_periodo)

    resultado = main.tendencia(fecha_ini=date(2025, 1, 31), fecha_fin=date(2025, 1, 31))

    assert resultado == [{"periodo": "2025-01", "siniestros": 2}]


def test_kpis_rechaza_periodo_invertido(monkeypatch):
    monkeypatch.setattr(main, "datos", datos_por_periodo)

    with pytest.raises(main.HTTPException) as error:
        main.kpis(fecha_ini=date(2025, 2, 1), fecha_fin=date(2025, 1, 31))

    assert error.value.status_code == 422


def test_kpis_y_reportes_cuentan_personas_no_accidentes(monkeypatch):
    datos = pd.DataFrame([
        {"gravedad": "muerto", "num_muertos": 2, "num_heridos": 3,
         "usuarios_afectados": "peaton,pasajero"},
        {"gravedad": "herido", "num_muertos": 0, "num_heridos": 2,
         "usuarios_afectados": "ciclista"},
    ])
    monkeypatch.setattr(main, "datos", lambda: datos)
    kpis = main.kpis()
    assert (kpis["muertos"], kpis["heridos"], kpis["porcentaje_vulnerables"]) == (2, 5, 100)
    respuesta = main.reporte_csv()
    assert respuesta.media_type == "text/csv"


def test_funciones_sin_datos_reales_no_son_fabricadas():
    cliente = TestClient(main.app)
    assert cliente.get("/api/geocodificar?q=Centro").status_code == 503
    assert cliente.get("/api/tramos-riesgo").status_code == 503


def test_login_acepta_cuerpo_y_no_query():
    cliente = TestClient(main.app)
    respuesta = cliente.post("/api/auth/login", json={"usuario": main.USUARIO, "clave": main.CLAVE})
    assert respuesta.status_code == 200
    assert "access_token" in respuesta.json()
    assert cliente.post("/api/auth/login", params={"usuario": main.USUARIO, "clave": main.CLAVE}).status_code == 422


def test_indicador_sin_token_ni_respaldo_falla(monkeypatch, tmp_path):
    monkeypatch.setattr(real, "RAIZ", tmp_path)
    monkeypatch.delenv("INEGI_TOKEN", raising=False)
    monkeypatch.setattr(real, "cargar_config", lambda: {
        "extraccion": {"inegi_indicador_url": "https://example.invalid", "timeout_s": 1}
    })
    with pytest.raises(RuntimeError, match="Falta respaldo manual real"):
        real.extraer_indicador(__import__("logging").getLogger("test"))


def test_filtro_municipio_clave_completa():
    datos = pd.DataFrame({"CVE_ENT": [20, 20, 19], "CVE_MUN": [20067, 67, 20067]})
    assert real.es_municipio(datos, real.cargar_config()).tolist() == [True, True, False]
