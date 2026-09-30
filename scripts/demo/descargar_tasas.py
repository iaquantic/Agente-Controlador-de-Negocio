"""Descarga la tasa USD->CUP de elTOQUE de cada día (a primera hora, 08:00 La Habana)."""
import csv, datetime as dt, json, os, sys, time, urllib.parse, urllib.request

API = "https://tasas.eltoque.com/v1/trmi"
inicio = dt.date.fromisoformat(sys.argv[1])
fin = dt.date.fromisoformat(sys.argv[2])
salida = sys.argv[3]

filas = []
dia = inicio
while dia <= fin:
    params = urllib.parse.urlencode({"date_from": f"{dia} 00:00:01", "date_to": f"{dia} 08:00:00"})
    req = urllib.request.Request(f"{API}?{params}", headers={"Authorization": f"Bearer {os.environ['ELTOQUE_API_KEY']}"})
    for intento in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                usd = json.load(r)["tasas"]["USD"]
            break
        except Exception as e:
            if intento == 3:
                raise
            time.sleep(2 ** (intento + 1))
    filas.append((dia.isoformat(), usd))
    dia += dt.timedelta(days=1)
    time.sleep(0.3)

with open(salida, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["fecha", "usd_cup"])
    w.writerows(filas)
print(len(filas), filas[0], filas[-1])
