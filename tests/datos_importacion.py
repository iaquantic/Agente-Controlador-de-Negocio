"""Genera una carpeta de importación sintética (como la exportaría un sistema de caja) para las pruebas."""
from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path


def generar(carpeta: Path, productos: int = 30, dias: int = 60, tickets_dia: int = 20, fin: date = date(2026, 10, 4),
            semilla: int = 7) -> dict:
    rnd = random.Random(semilla)
    carpeta.mkdir(parents=True, exist_ok=True)
    cats = [("Alimentos", "Granos y básicos"), ("Alimentos", "Despensa y conservas"), ("Aseo e higiene", "Limpieza"),
            ("Electrodomésticos", "Cocina")]
    catalogo = []
    for i in range(productos):
        cat, sub = cats[i % len(cats)]
        precio = round(rnd.uniform(1, 80), 2)
        catalogo.append({"sku": f"P-{i:04d}", "nombre": f"Producto {i}", "categoria": cat, "subcategoria": sub,
                         "precio_usd": precio, "coste_usd": round(precio * rnd.uniform(0.6, 0.85), 2),
                         "stock_minimo": rnd.randint(2, 10)})
    with open(carpeta / "productos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(catalogo[0]))
        w.writeheader()
        w.writerows(catalogo)

    inicio = fin - timedelta(days=dias - 1)
    with open(carpeta / "tasas.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fecha", "usd_cup"])
        for k in range(dias):
            w.writerow([(inicio + timedelta(days=k)).isoformat(), 700 + k * 0.5])

    vendidos = {p["sku"]: 0 for p in catalogo}
    lineas = 0
    # Un archivo de ventas por mes, como una exportación mensual.
    por_mes: dict[str, list] = {}
    n = 0
    for k in range(dias):
        d = inicio + timedelta(days=k)
        for _ in range(tickets_dia):
            n += 1
            momento = datetime.combine(d, datetime.min.time()) + timedelta(minutes=rnd.randint(9 * 60, 19 * 60 - 1))
            anulada = rnd.random() < 0.02
            cup = rnd.random() < 0.3
            for p in rnd.sample(catalogo, rnd.randint(1, 4)):
                q = rnd.randint(1, 3)
                if not anulada:
                    vendidos[p["sku"]] += q
                precio = round(p["precio_usd"] * (700 + k * 0.5)) if cup else p["precio_usd"]
                por_mes.setdefault(f"{d:%Y-%m}", []).append(
                    [f"T{n:07d}", momento.strftime("%d/%m/%Y %H:%M"), p["sku"], q, str(precio).replace(".", ","),
                     "CUP" if cup else "USD", "transferencia" if cup and rnd.random() < 0.5 else "efectivo",
                     "anulada" if anulada else "completada"])
                lineas += 1
    for mes, filas in por_mes.items():
        with open(carpeta / f"ventas_{mes}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Ticket", "Fecha", "Código", "Cantidad", "Precio", "Moneda", "Forma de pago", "Estado"])
            w.writerows(filas)

    with open(carpeta / "compras.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["referencia", "fecha", "proveedor", "sku", "cantidad", "coste_unitario"])
        for i, p in enumerate(catalogo):
            w.writerow([f"C{i}", inicio.isoformat(), "Proveedor A" if i % 2 else "Proveedor B", p["sku"],
                        vendidos[p["sku"]] // 2 + 5, p["coste_usd"]])
    with open(carpeta / "inventario.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku", "stock", "fecha"])
        for p in catalogo:
            w.writerow([p["sku"], rnd.randint(0, 40), fin.isoformat()])
    return {"tickets": n, "lineas": lineas, "productos": productos}
