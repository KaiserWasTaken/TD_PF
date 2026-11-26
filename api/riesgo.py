import numpy as np
from pyproj import Transformer
from shapely import distance, points
from shapely.geometry import LineString


def exposicion_rutas(geometrias, siniestros, pesos, radio_m):
    """Cuenta siniestros a una distancia de la geometría, sin estimar probabilidad."""
    validos = siniestros.dropna(subset=["latitud", "longitud"]).copy()
    if validos.empty:
        raise ValueError("No hay siniestros georreferenciados para calcular exposicion.")
    validos = validos[
        np.isfinite(validos["latitud"]) & np.isfinite(validos["longitud"])
        & validos["latitud"].between(-90, 90) & validos["longitud"].between(-180, 180)
    ]
    if validos.empty:
        raise ValueError("No hay siniestros georreferenciados para calcular exposicion.")
    if radio_m <= 0 or not np.isfinite(radio_m):
        raise ValueError("El radio de proximidad debe ser positivo y finito.")
    desconocidas = set(validos["gravedad"]) - set(pesos)
    if desconocidas:
        raise ValueError(f"Gravedades sin peso configurado: {sorted(desconocidas)}")
    transformar = Transformer.from_crs("EPSG:4326", "EPSG:32614", always_xy=True)
    x, y = transformar.transform(validos["longitud"].to_numpy(), validos["latitud"].to_numpy())
    ubicaciones = points(x, y)
    ponderaciones = validos["gravedad"].map(pesos).to_numpy()
    resultados = []
    for geometria in geometrias:
        if geometria.get("type") != "LineString" or len(geometria.get("coordinates", [])) < 2:
            raise ValueError("OSRM devolvio una geometria de ruta invalida.")
        coordenadas = geometria["coordinates"]
        xs, ys = transformar.transform([c[0] for c in coordenadas], [c[1] for c in coordenadas])
        linea = LineString(zip(xs, ys))
        cercanos = distance(ubicaciones, linea) <= radio_m
        resultados.append({"siniestros_cercanos": int(cercanos.sum()),
                           "indice_historico": float(ponderaciones[cercanos].sum())})
    return resultados
