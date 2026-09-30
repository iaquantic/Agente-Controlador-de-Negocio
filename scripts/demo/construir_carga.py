"""Genera el SQL que carga el catálogo (gen.catalogo) y las tasas (public.tasas_cambio) desde los CSV."""
import csv, pathlib, sys

base = pathlib.Path(__file__).parent / "datos"
q = lambda s: "'" + s.replace("'", "''") + "'"

filas = []
for r in csv.DictReader(open(base / "catalogo.csv", encoding="utf-8")):
    filas.append("(" + ",".join([q(r["sku"]), q(r["nombre"]), q(r["linea"]), q(r["categoria"]), q(r["subcategoria"]),
                                 r["precio_usd"], r["demanda_dia"], q(r["perfil"]), q(r["proveedor"])]) + ")")
tasas = list(csv.DictReader(open(base / "tasas_eltoque.csv")))

sql = ["insert into gen.catalogo values\n" + ",\n".join(filas) + ";",
       "insert into tasas_cambio (fecha, usd_cup, fuente, obtenida_en)\n"
       f"select date '{tasas[0]['fecha']}' + (i - 1)::int, v, 'elTOQUE', ((date '{tasas[0]['fecha']}' + (i - 1)::int)::timestamp + interval '8 hours') at time zone 'America/Havana'\n"
       "from unnest(array[" + ",".join(t["usd_cup"] for t in tasas) + "]::numeric[]) with ordinality as t(v, i);"]
sys.stdout.write("\n".join(sql) + "\n")
