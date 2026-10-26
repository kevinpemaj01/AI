"""
Legenda automatica della tavola (Fase 3).

Disegna nell'area "LEGENDA" della tavola (sotto il cartiglio) una riga per
ogni simbolo presente: simbolo, descrizione, quantità.

Descrizioni, in ordine di priorità:
  1. "descrizioni" del file di regole (se indicato)
  2. catalogo_simboli.csv (verificato dall'utente)
  3. catalogo_proposte.csv (proposte dalle tavole)
  4. nome del blocco

Rigenerare la legenda sostituisce quella precedente. Con --nota (o se il file
di regole ha una "etichetta") scrive anche un avviso sotto il titolo.

Uso:
    python legenda.py "<tavola.dxf>" [--regole regole/<file>.json]
"""

import argparse
import csv
import json
import logging
import sys
import textwrap
from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))
logging.getLogger("ezdxf").setLevel(logging.ERROR)

import simboli as sm          # noqa: E402

APPID = "PLANIMETRIA_IMPIANTO"
TAG = "LEGENDA"
RIGA = 90.0          # passo righe (cm a 1:100)
TESTO_H = 30.0
X_SIMBOLO = 230.0    # centro simbolo (relativo all'angolo cornice)
X_TESTO = 380.0
CARATTERI = 48       # a capo delle descrizioni (oltre si sovrappone alla colonna "n.")
Y_MIN = 150.0        # non scendere sotto (cornice)


def descrizioni(regole=None):
    d = {}
    for f in (QUI / "catalogo_proposte.csv", QUI / "catalogo_simboli.csv"):
        if f.exists():
            with open(f, encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh, delimiter=";"):
                    if r.get("BLOCCO") and r.get("DESCRIZIONE"):
                        d[r["BLOCCO"].strip()] = r["DESCRIZIONE"].strip()
    if regole:
        d.update(regole.get("descrizioni", {}))
    return d


def _tag(e, valore):
    e.set_xdata(APPID, [(1000, TAG), (1000, valore)])


def _e_legenda(e):
    try:
        return e.get_xdata(APPID)[0][1] == TAG
    except ezdxf.DXFValueError:
        return False


def genera(tavola, regole_file=None, nota=None):
    tavola = Path(tavola)
    doc = ezdxf.readfile(tavola)
    msp = doc.modelspace()
    if APPID not in doc.appids:
        doc.appids.new(APPID)
    regole = json.loads(Path(regole_file).read_text(encoding="utf-8")) if regole_file else None
    nota = nota or (regole or {}).get("etichetta")
    desc = descrizioni(regole)

    for e in list(msp):                                  # legenda precedente
        if _e_legenda(e):
            msp.delete_entity(e)

    # simboli presenti (esclusi xref e blocchi di cartiglio)
    esclusi = {b.name for b in doc.blocks if b.block.dxf.flags & 4 or b.name.upper().startswith("CARTIGLIO")}
    uso, esempio = Counter(), {}
    for ins in msp.query("INSERT"):
        if ins.dxf.name in esclusi:
            continue
        nome = sm.nome_simbolo(doc, ins)
        uso[nome] += 1
        esempio.setdefault(nome, ins)

    # posizione: sotto il testo "LEGENDA"
    t_leg = next((t for t in msp.query("TEXT") if t.dxf.text == "LEGENDA"), None)
    if t_leg is None:
        raise ValueError("Testo 'LEGENDA' non trovato nella tavola (tavola non creata con prepara_tavola?)")
    k = t_leg.dxf.height / 50.0                          # fattore scala tavola (50 = h a 1:100)
    ox = t_leg.dxf.insert.x - 870.0 * k                  # angolo cornice
    y = t_leg.dxf.insert.y - 130.0 * k

    righe = 0
    for nome in sorted(uso, key=lambda n: (esempio[n].dxf.layer, desc.get(n, n))):
        ins = esempio[nome]
        testo = desc.get(nome, nome)
        linee = textwrap.wrap(testo, CARATTERI) or [testo]
        if y - (len(linee) - 1) * TESTO_H * 1.3 * k < Y_MIN * k:
            break
        s = abs(ins.dxf.xscale)
        e = msp.add_blockref(ins.dxf.name, (ox + X_SIMBOLO * k, y),
                             dxfattribs={"layer": ins.dxf.layer, "xscale": s, "yscale": s, "zscale": s})
        _tag(e, nome)
        for i, ln in enumerate(linee):
            t = msp.add_text(ln, height=TESTO_H * k,
                             dxfattribs={"layer": "TESTI", "style": "Standard"})
            t.set_placement((ox + X_TESTO * k, y - i * TESTO_H * 1.3 * k), align=TextEntityAlignment.MIDDLE_LEFT)
            _tag(t, nome)
        q = msp.add_text(f"n. {uso[nome]}", height=TESTO_H * k * 0.8,
                         dxfattribs={"layer": "TESTI", "style": "Standard"})
        q.set_placement((ox + 2020 * k, y), align=TextEntityAlignment.MIDDLE_RIGHT)
        _tag(q, nome)
        y -= RIGA * k + (len(linee) - 1) * TESTO_H * 1.3 * k
        righe += 1

    if nota:                                             # avviso sotto il titolo
        tit = next((t for t in msp.query("TEXT") if t.dxf.text.startswith("%%U") and t.dxf.layer == "0"), None)
        if tit is not None:
            n = msp.add_text(nota, height=32 * k, dxfattribs={"layer": "TESTI", "style": "Standard",
                                                              "color": 1})
            n.dxf.insert = (tit.dxf.insert.x, tit.dxf.insert.y - 80 * k)
            _tag(n, "NOTA")

    doc.saveas(tavola)
    return {"tavola": str(tavola), "voci_legenda": righe, "simboli_diversi": len(uso),
            "non_entrate": len(uso) - righe,
            "senza_descrizione": sorted(n for n in uso if n not in desc)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tavola")
    ap.add_argument("--regole")
    ap.add_argument("--nota")
    a = ap.parse_args()
    print(json.dumps(genera(a.tavola, a.regole, a.nota), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
