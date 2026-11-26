import argparse


parser = argparse.ArgumentParser(description="ETL Mapas Seguros Oaxaca")
parser.add_argument("--all", action="store_true", help="Ejecutar ETL real completo")
parser.add_argument("--extract", action="store_true", help="Extraer ATUS, INEGI y Overpass")
parser.add_argument("--transform", action="store_true", help="Transformar registros extraidos")
parser.add_argument("--load", action="store_true", help="Cargar la base principal")
parser.add_argument("--demo", action="store_true",
                    help="Modo explicito; carga datos sinteticos solo en mapas_seguros_demo")
parser.add_argument("--atus", action="store_true",
                    help="Carga solo ATUS municipal real 2020-2025")
parser.add_argument("--georreferenciar", action="store_true",
                    help="Vincula coordenadas reales de ATUS con la base existente")
parser.add_argument("--indicadores", action="store_true",
                    help="Actualiza solo indicadores reales de INEGI")
parser.add_argument("--infraestructura", action="store_true",
                    help="Actualiza solo infraestructura real desde Overpass")
parser.add_argument("--analitica", action="store_true",
                    help="Reconstruye hechos y data marts desde los siniestros reales cargados")
args = parser.parse_args()

if sum(bool(x) for x in (args.demo, args.atus, args.georreferenciar, args.indicadores, args.infraestructura, args.analitica,
                          args.all or args.extract or args.transform or args.load)) > 1:
    parser.error("Los modos de carga no pueden combinarse")

if args.analitica:
    from .real import cargar_analitica_solo
    resultado = cargar_analitica_solo()
    print(resultado)
elif args.infraestructura:
    from .real import cargar_infraestructura_solo
    resultado = cargar_infraestructura_solo()
    print(resultado)
elif args.indicadores:
    from .real import cargar_indicadores_solo
    resultado = cargar_indicadores_solo()
    print(resultado)
elif args.georreferenciar:
    from .georreferenciar import ejecutar
    resultado = ejecutar()
    print(resultado)
elif args.atus:
    from .real import cargar_atus_solo
    resultado = cargar_atus_solo()
    print(resultado)
elif args.demo:
    from .real import ejecutar_demo
    resultado = ejecutar_demo()
    print(resultado)
else:
    if not (args.all or args.extract or args.transform or args.load):
        parser.error("Modo real requiere --all, --extract, --transform o --load")
    from .real import ejecutar_real
    resultado = ejecutar_real()
    print(resultado)
