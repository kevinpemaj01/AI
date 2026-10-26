"""
Funzioni comuni per riconoscere i simboli impiantistici nei DXF.

- nome_simbolo(): nome "vero" di un blocco, risolvendo i blocchi dinamici
  (i riferimenti *U41, *U30... puntano al blocco originale, es. 1584_2_1, 16A)
- centro(): centro geometrico di un INSERT
- abbina_legenda(): abbina ogni simbolo di una legenda alla voce sulla stessa riga
- carica_catalogo(): legge catalogo_simboli.csv (verificato dall'utente)
"""

import csv
import math
import statistics
from pathlib import Path

from ezdxf import bbox

QUI = Path(__file__).resolve().parent
CATALOGO = QUI / "catalogo_simboli.csv"

# entità di rendering o di servizio che non sono simboli
IGNORA_PREFISSI = ("AVE_", "A$C")


def nome_simbolo(doc, ins) -> str:
    """Nome del blocco; per i blocchi dinamici (*Uxx) restituisce il blocco originale."""
    nome = ins.dxf.name
    if not nome.startswith("*"):
        return nome
    blk = doc.blocks.get(nome)
    if blk is None:
        return nome
    try:
        for code, val in blk.block_record.get_xdata("AcDbBlockRepBTag"):
            if code == 1005:
                rec = doc.entitydb.get(val)
                if rec is not None:
                    return rec.dxf.name
    except Exception:
        pass
    return nome


def centro(ins):
    """(cx, cy, larghezza, altezza) dell'ingombro di un INSERT."""
    try:
        bb = bbox.extents([ins])
        c = bb.center
        if not any(math.isnan(v) for v in (c.x, c.y)):
            return c.x, c.y, bb.size.x, bb.size.y
    except Exception:
        pass
    return ins.dxf.insert.x, ins.dxf.insert.y, 0.0, 0.0


def _testo(t):
    if t.dxftype() == "MTEXT":
        righe = t.plain_text().strip().splitlines()
        return righe[0].strip() if righe else "", t.dxf.char_height
    return t.dxf.text.strip(), t.dxf.height


def _centro_testo_y(t, h):
    """Quota y del centro della prima riga di testo."""
    y = t.dxf.insert.y
    if t.dxftype() == "MTEXT":
        ap = t.dxf.get("attachment_point", 1)
        if ap in (1, 2, 3):          # in alto
            return y - h / 2
        if ap in (7, 8, 9):          # in basso
            return y + h / 2
        return y
    return y + h / 2                 # TEXT: punto di inserimento sulla linea di base


def voci_legenda(msp, layer_testi=None, h_min=20.0):
    """
    Voci di legenda = testi principali (esclude sotto-righe "- n. 2 ..." e
    lettere singole dentro i simboli). Se layer_testi è dato, considera solo
    quei layer.
    """
    voci = []
    for t in msp.query("TEXT MTEXT"):
        if layer_testi and t.dxf.layer not in layer_testi:
            continue
        s, h = _testo(t)
        if not s or h < h_min or s.startswith("-") or s.startswith("%%u") or s.startswith("%%U"):
            continue
        if len(s) <= 2:
            continue
        voci.append({"x": t.dxf.insert.x, "y": _centro_testo_y(t, h), "testo": s, "simboli": []})
    if not voci:
        return voci
    chiavi = sorted({round(v["x"] / 100) * 100 for v in voci})
    for v in voci:
        v["colonna"] = chiavi.index(round(v["x"] / 100) * 100) + 1
    return voci


def _tolleranza_riga(voci, colonna):
    ys = sorted((v["y"] for v in voci if v["colonna"] == colonna), reverse=True)
    passi = [a - b for a, b in zip(ys, ys[1:]) if a - b > 1]
    return (statistics.median(passi) / 2) if passi else 40.0


def abbina_legenda(doc, msp, layer_testi=None, h_min=20.0, distanza_max=400.0):
    """
    Abbina i simboli alle voci di legenda.
    Ritorna (voci, orfani). Ogni voce ha 'simboli': [{blocco, layer, ...}].
    """
    voci = voci_legenda(msp, layer_testi, h_min)
    if not voci:
        return [], []
    colonne = sorted({v["colonna"] for v in voci})
    col_x = {c: min(v["x"] for v in voci if v["colonna"] == c) for c in colonne}
    tol = {c: _tolleranza_riga(voci, c) for c in colonne}
    y_min = min(v["y"] for v in voci) - max(tol.values()) * 2
    y_max = max(v["y"] for v in voci) + max(tol.values()) * 2

    orfani = []
    for ins in msp.query("INSERT"):
        nome = nome_simbolo(doc, ins)
        if nome.startswith(IGNORA_PREFISSI):
            continue
        cx, cy, w, h = centro(ins)
        if not (y_min <= cy <= y_max):
            continue
        destra = sorted((x, c) for c, x in col_x.items() if x > cx)
        if not destra or destra[0][0] - cx > distanza_max:
            continue
        c = destra[0][1]
        cand = [v for v in voci if v["colonna"] == c and abs(v["y"] - cy) <= tol[c]]
        if not cand:
            orfani.append((nome, ins.dxf.layer, cx, cy))
            continue
        v = min(cand, key=lambda v: abs(v["y"] - cy))
        v.setdefault("handles", set()).add(ins.dxf.handle)   # simboli disegnati nella legenda
        if not any(s["blocco"] == nome for s in v["simboli"]):
            v["simboli"].append({"blocco": nome, "layer": ins.dxf.layer,
                                 "w": w, "h": h, "scala": ins.dxf.xscale})
    return voci, orfani


def carica_catalogo(path=CATALOGO):
    """
    Catalogo verificato -> {blocco: [righe]}.
    Un blocco può avere più descrizioni (es. 'P' usato per più pulsanti).
    """
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            b = r["BLOCCO"].strip()
            if b:
                out.setdefault(b, []).append(r)
    return out
