"""
Proposte di aggiunta al catalogo simboli.

Scansiona una o più tavole DXF, trova i blocchi usati che NON sono in
catalogo_simboli.csv e scrive un CSV di proposte con la descrizione presa
dalla legenda delle tavole (se trovata). L'utente verifica le righe e le
copia nel catalogo.

Uso:
    python proponi_catalogo.py <out.csv> <tavola1.dxf>[::layer legenda] [<tavola2.dxf>[::layer] ...]

Esempio:
    python proponi_catalogo.py catalogo_proposte.csv ^
        "riferimenti/ALLEGATO E02 FM E SERVIZI.dxf::LEGENDA EM" ^
        "riferimenti/ALLEGATO E01 ILL.ORDINARIA E DI SICUREZZA.dxf::1 - Testi"
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))

import computo as cp  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    out = Path(sys.argv[1])
    trovati = defaultdict(lambda: {"layer": set(), "descr": set(), "qta": 0, "tavole": set()})
    for arg in sys.argv[2:]:
        path, _, lay = arg.partition("::")
        res = cp.computo(Path(path), layer_legenda={lay} if lay else None)
        for r in res["righe"]:
            if r["fonte"] == "CATALOGO":
                continue
            t = trovati[r["blocco"]]
            t["layer"].add(r["impianto"])
            if r["descrizione"]:
                t["descr"].add(r["descrizione"])
            t["qta"] += r["quantita"]
            t["tavole"].add(Path(path).stem.split(" ")[1] if " " in Path(path).stem else Path(path).stem)

    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["BLOCCO", "DESCRIZIONE", "LAYER", "COLONNA_LEGENDA", "LARGH", "ALT",
                    "A_COMPUTO", "NOTE", "VERIFICATO", "QTA_NELLE_TAVOLE", "TAVOLE"])
        for nome in sorted(trovati, key=lambda n: (not trovati[n]["descr"], n.lower())):
            t = trovati[nome]
            descr = " / ".join(sorted(t["descr"]))
            nota = "descrizione dalla legenda della tavola" if descr else "DESCRIZIONE MANCANTE: da compilare"
            if len(t["descr"]) > 1:
                nota = "piu' descrizioni trovate: sceglierne una"
            w.writerow([nome, descr, " / ".join(sorted(t["layer"])), "", "", "", "SI", nota, "NO",
                        t["qta"], ", ".join(sorted(t["tavole"]))])
    con = sum(1 for t in trovati.values() if t["descr"])
    print(f"Blocchi non in catalogo: {len(trovati)}  (con descrizione: {con}, senza: {len(trovati) - con})")
    print(f"Proposte salvate in: {out}")


if __name__ == "__main__":
    main()
