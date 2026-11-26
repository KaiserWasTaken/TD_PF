from pathlib import Path
import hashlib, json
import pandas as pd

from ..core import RAIZ

MAPEO = {
    "entidad": ["ID_ENTIDAD", "entidad"],
    "municipio": ["ID_MUNICIPIO", "municipio"],
}

def detectar():
    carpeta = RAIZ / "data/manual/atus"
    if not carpeta.exists():
        return []
    return sorted([p for p in carpeta.iterdir()
                   if p.suffix.lower() in (".csv", ".json", ".geojson")])

def leer_manual(ruta):
    if ruta.suffix.lower() == ".csv":
        df = pd.read_csv(ruta, encoding="utf-8-sig")
    else:
        df = pd.read_json(ruta)
    columnas = {str(c).upper(): c for c in df.columns}
    faltantes = [nombre for nombre in ("ID_ENTIDAD", "ID_MUNICIPIO")
                 if nombre not in columnas and nombre.lower() not in [str(c).lower() for c in df.columns]]
    if faltantes:
        raise ValueError(f"Archivo ATUS sin columnas requeridas {faltantes}. Columnas disponibles: {list(df.columns)}")
    entidad = columnas.get("ID_ENTIDAD")
    municipio = columnas.get("ID_MUNICIPIO")
    if entidad is None:
        entidad = next(c for c in df.columns if str(c).lower() == "id_entidad")
    if municipio is None:
        municipio = next(c for c in df.columns if str(c).lower() == "id_municipio")
    df = df[(pd.to_numeric(df[entidad], errors="coerce") == 20) &
            (pd.to_numeric(df[municipio], errors="coerce") == 67)].copy()
    destino = RAIZ / "data/raw/inegi_atus"
    destino.mkdir(parents=True, exist_ok=True)
    crudo = ruta.read_bytes()
    nombre = destino / f"{ruta.stem}_copia{ruta.suffix.lower()}"
    nombre.write_bytes(crudo)
    hash = hashlib.sha256(crudo).hexdigest()
    (destino / f"{ruta.stem}.sha256").write_text(hash, encoding="ascii")
    return df, nombre, hash
