"""
Estrai catalogo simboli dalla legenda.

Legge una legenda DXF (es. riferimenti/LEGENDA100.dxf), abbina ogni simbolo
alla voce di legenda sulla stessa riga e scrive un catalogo CSV da verificare
a mano (separatore ';', apribile in Excel italiano).

Uso:
    python estrai_catalogo.py riferimenti/LEGENDA100.dxf catalogo_simboli.csv

Il catalogo è la "fonte di verità" per tutte le funzioni della planimetria:
codice blocco -> descrizione, impianto (layer), conteggio a computo.
Dopo l'estrazione l'utente lo verifica e segna la colonna VERIFICATO = SI.
"""

import csv
import math
import sys
from pathlib import Path

import ezdxf
from ezdxf import bbox

ROW_TOL = 37.0          # metà dell'interlinea della legenda (~74 unità)
MIN_HEADING_H = 20.0    # altezza minima testo per una voce (le sotto-righe "- n. 2..." sono escluse)


def voci_legenda(msp):
    """Voci di legenda: testi principali raggruppati per colonna."""
    voci = []
    for t in msp.query("TEXT"):
        s = t.dxf.text.strip()
        if not s or t.dxf.height < MIN_HEADING_H or s.startswith("-") or s.startswith("%%u"):
            continue
        if len(s) <= 2:              # lettere dentro i simboli (P, R, N, ...)
            continue
        voci.append({"x": t.dxf.insert.x, "y": t.dxf.insert.y, "testo": s, "simboli": []})
    # colonne = x di partenza dei testi arrotondata
    colonne = sorted({round(v["x"] / 100) * 100 for v in voci})
    for v in voci:
        v["colonna"] = colonne.index(round(v["x"] / 100) * 100) + 1
    return voci, colonne


def centro(ins):
    try:
        bb = bbox.extents([ins])
        c = bb.center
        if not any(math.isnan(v) for v in (c.x, c.y)):
            return c.x, c.y, bb.size.x, bb.size.y
    except Exception:
        pass
    return ins.dxf.insert.x, ins.dxf.insert.y, 0.0, 0.0


def estrai(legenda: Path):
    doc = ezdxf.readfile(legenda)
    msp = doc.modelspace()
    voci, colonne = voci_legenda(msp)
    col_x = sorted({min(v["x"] for v in voci if v["colonna"] == c) for c in range(1, len(colonne) + 1)})

    orfani = []
    for ins in msp.query("INSERT"):
        nome = ins.dxf.name
        if nome.startswith("AVE_"):                     # entità di rendering, non simboli
            continue
        cx, cy, w, h = centro(ins)
        # colonna: la prima colonna di testo a destra del simbolo
        destra = [x for x in col_x if x > cx]
        if not destra or destra[0] - cx > 400:
            orfani.append((nome, ins.dxf.layer, cx, cy))
            continue
        cx_col = destra[0]
        cand = [v for v in voci if abs(v["x"] - cx_col) < 50 and abs(v["y"] - cy) <= ROW_TOL]
        if not cand:
            orfani.append((nome, ins.dxf.layer, cx, cy))
            continue
        v = min(cand, key=lambda v: abs(v["y"] - cy))
        dati = {"blocco": nome, "layer": ins.dxf.layer,
                "anonimo": nome.startswith("*"), "w": w, "h": h,
                "scala": ins.dxf.xscale}
        if not any(s["blocco"] == nome for s in v["simboli"]):
            v["simboli"].append(dati)
    return voci, orfani


def scrivi_csv(voci, out: Path):
    righe = []
    for v in sorted(voci, key=lambda v: (v["colonna"], -v["y"])):
        if v["simboli"]:
            for s in v["simboli"]:
                if s["anonimo"]:
                    nota = "blocco anonimo/dinamico: da trasformare in blocco con nome"
                else:
                    nota = ""
                righe.append([s["blocco"], v["testo"], s["layer"], v["colonna"],
                              round(s["w"]), round(s["h"]), "SI", nota, "NO"])
        else:
            righe.append(["", v["testo"], "", v["colonna"], "", "", "SI",
                          "simbolo disegnato con linee sciolte: da trasformare in blocco", "NO"])
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["BLOCCO", "DESCRIZIONE", "LAYER", "COLONNA_LEGENDA",
                    "LARGH", "ALT", "A_COMPUTO", "NOTE", "VERIFICATO"])
        w.writerows(righe)
    return righe


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    voci, orfani = estrai(Path(sys.argv[1]))
    righe = scrivi_csv(voci, Path(sys.argv[2]))
    n_ok = sum(1 for r in righe if r[0] and not r[7])
    n_anon = sum(1 for r in righe if r[0] and r[7])
    n_sciolti = sum(1 for r in righe if not r[0])
    print(f"Voci di legenda: {len(voci)}")
    print(f"  con blocco riutilizzabile : {n_ok}")
    print(f"  con blocco anonimo        : {n_anon}")
    print(f"  senza blocco (linee)      : {n_sciolti}")
    if orfani:
        print(f"Simboli non abbinati a nessuna voce: {len(orfani)}")
        for o in orfani:
            print(f"  {o[0]}  layer={o[1]}  ({o[2]:.0f}, {o[3]:.0f})")
