"""Compatibilidad de configuracion para el proyecto; no genera datos sinteticos."""
from __future__ import annotations

import logging
from pathlib import Path
import yaml
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]


def cargar_config():
    with open(RAIZ / "config.yaml", encoding="utf-8") as archivo:
        return yaml.safe_load(archivo)


def logger():
    (RAIZ / "reports").mkdir(parents=True, exist_ok=True)
    salida = logging.getLogger("etl")
    if not salida.handlers:
        salida.setLevel(logging.INFO)
        formato = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        for destino in (
            logging.StreamHandler(),
            logging.FileHandler(RAIZ / "reports" / "etl.log", encoding="utf-8"),
        ):
            destino.setFormatter(formato)
            salida.addHandler(destino)
    return salida


def sintetizar(config):
    raise RuntimeError(
        "El generador sintético no está disponible en el modo por defecto. "
        "Use explícitamente: python -m etl.run --demo"
    )


def limpiar(df, config):
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    obligatorios = [c for c in ("fecha_hora", "tipo_siniestro", "gravedad") if c in df.columns]
    if len(obligatorios) != 3:
        raise RuntimeError(
            "Faltan campos obligatorios para limpiar ATUS: "
            + ", ".join(sorted(set(("fecha_hora", "tipo_siniestro", "gravedad")) - set(obligatorios)))
        )
    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"], errors="coerce", format="mixed")
    df["latitud"] = pd.to_numeric(df.get("latitud"), errors="coerce")
    df["longitud"] = pd.to_numeric(df.get("longitud"), errors="coerce")
    validas = df["fecha_hora"].notna()
    validas &= df["tipo_siniestro"].notna()
    validas &= df["gravedad"].isin(["solo danos", "herido", "muerto"])
    return df.loc[validas].copy(), {
        "registros_leidos": len(df),
        "registros_cargables": int(validas.sum()),
    }


def ejecutar(etapa="all"):
    raise RuntimeError(
        "Use el ETL real con python -m etl.run --all "
        "o el modo explícito python -m etl.run --demo."
    )
