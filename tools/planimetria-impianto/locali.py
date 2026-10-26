"""
Riconoscimento dei locali da una pianta architettonica.

Per ogni etichetta di locale (testo con il nome, es. "CAMERA 1", "BAGNO A")
ricava il contorno del locale dai muri:

  1. i muri (layer indicati) vengono disegnati su una griglia (risoluzione 2 cm)
  2. le aperture delle porte vengono chiuse ingrossando i muri di
     `chiusura` (default 50 cm: chiude porte fino a ~100 cm)
  3. si "riempie" lo spazio a partire dall'etichetta
  4. il locale viene riportato alla sua dimensione reale (si annulla
     l'ingrossamento senza oltrepassare i muri)
  5. il contorno viene semplificato in una polilinea chiusa

Se la pianta ha già i contorni dei locali (polilinee chiuse su un layer,
es. "_SUP"), si possono usare direttamente con `locali_da_polilinee`.

Ogni locale riporta: nome, superficie calcolata, superficie dichiarata in
pianta (se scritta, es. "S = 19,74 m²") e scostamento %.

Uso:
    python locali.py <pianta.dxf> --finestra x0,y0,x1,y1 [--unita cm] [--json]
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import ezdxf
from ezdxf import bbox, path as ezpath
from scipy import ndimage

LAYER_MURI = ("SEZ", "NC_SEZ", "PR_COSTRUZIONI", "INF", "NC linee_10")
LAYER_ETICHETTE = ("Testi", "PR_TESTI")
UNITA_IN_CM = {"cm": 1.0, "mm": 0.1, "m": 100.0}
BORDO_PX = 1

RE_SUPERFICIE = re.compile(r"S\s*=\s*([\d.,]+)\s*m", re.IGNORECASE)


# ── etichette ─────────────────────────────────────────────────────────────

def _testo(e):
    return e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text


def etichette(msp, finestra, layer_etichette=LAYER_ETICHETTE):
    """Testi con il nome di un locale: prima riga con almeno 3 lettere."""
    x0, y0, x1, y1 = finestra
    out = []
    for t in msp.query("TEXT MTEXT"):
        if t.dxf.layer not in layer_etichette:
            continue
        s = _testo(t).strip()
        if not s:
            continue
        righe = [r.strip() for r in s.splitlines() if r.strip()]
        nome = righe[0]
        if sum(c.isalpha() for c in nome) < 3:
            continue
        try:
            b = bbox.extents([t])
            cx, cy = (b.extmin.x + b.extmax.x) / 2, (b.extmin.y + b.extmax.y) / 2
        except Exception:
            cx, cy = t.dxf.insert.x, t.dxf.insert.y
        if not (x0 <= cx <= x1 and y0 <= cy <= y1):
            continue
        # nomi su due righe senza dati (es. "CABINA | ARMADIO")
        if len(righe) > 1 and not any(ch.isdigit() for ch in " ".join(righe[1:])) \
                and not righe[1].lower().startswith(("h ", "h=", "h min", "(")):
            nome = " ".join(righe)
        m = RE_SUPERFICIE.search(s)
        sup = float(m.group(1).replace(".", "").replace(",", ".")) if m else None
        out.append({"nome": nome, "testo": s, "punto": (cx, cy), "superficie_dichiarata": sup})
    return out


# ── rasterizzazione muri ──────────────────────────────────────────────────

def _percorsi(e):
    t = e.dxftype()
    if t == "HATCH":
        return list(ezpath.from_hatch(e)), True
    if t in ("LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE"):
        return [ezpath.make_path(e)], False
    return [], False


def griglia_muri(msp, finestra, layer_muri, res):
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = finestra
    W, H = int(math.ceil((x1 - x0) / res)) + 1, int(math.ceil((y1 - y0) / res)) + 1
    img = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(img)

    def px(v):
        return ((v.x - x0) / res, (y1 - v.y) / res)

    for e in msp:
        if e.dxf.layer not in layer_muri:
            continue
        paths, pieno = _percorsi(e)
        for p in paths:
            pts = [px(v) for v in p.flattening(distance=res / 2)]
            if len(pts) < 2:
                continue
            if pieno and len(pts) >= 3:
                dr.polygon(pts, fill=255)
            dr.line(pts, fill=255, width=2)
    return np.array(img) > 0


# ── contorno ──────────────────────────────────────────────────────────────

def _rdp(punti, tol):
    """Semplificazione Douglas-Peucker di una polilinea aperta."""
    if len(punti) < 3:
        return punti
    a, b = np.array(punti[0]), np.array(punti[-1])
    ab = b - a
    n = np.hypot(*ab)
    pts = np.array(punti[1:-1])
    if n == 0:
        d = np.hypot(*(pts - a).T)
    else:
        d = np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / n
    i = int(np.argmax(d))
    if d[i] > tol:
        sx = _rdp(punti[: i + 2], tol)
        dx = _rdp(punti[i + 1:], tol)
        return sx[:-1] + dx
    return [punti[0], punti[-1]]


def contorno(mask, finestra, res, tol):
    """Poligono (coordinate pianta) del bordo della regione."""
    import contourpy
    x0, y0, x1, y1 = finestra
    z = np.pad(mask.astype(float), 1)
    gen = contourpy.contour_generator(z=z)
    linee = gen.lines(0.5)
    if not linee:
        return []
    ln = max(linee, key=len)                      # contorno esterno
    pts = [((c - 1) * res + x0, y1 - (r - 1) * res) for c, r in ln]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    pts = _rdp(pts, tol)
    return pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else pts


def area(poli):
    if len(poli) < 3:
        return 0.0
    s = 0.0
    for (xa, ya), (xb, yb) in zip(poli, poli[1:] + poli[:1]):
        s += xa * yb - xb * ya
    return abs(s) / 2


# ── riconoscimento ────────────────────────────────────────────────────────

def trova_locali(doc, finestra, unita="cm", layer_muri=LAYER_MURI,
                 layer_etichette=LAYER_ETICHETTE, res=2.0, chiusura=50.0):
    """
    finestra : zona della pianta (x0,y0,x1,y1) in unità del disegno
    res, chiusura : in centimetri reali
    """
    f = UNITA_IN_CM[unita]
    res_u, chiu_u = res / f, chiusura / f
    msp = doc.modelspace()
    muri = griglia_muri(msp, finestra, set(layer_muri), res_u)
    libero = ~muri
    # distanza euclidea dai muri (provate anche varianti "a scacchiera": errore
    # medio maggiore sulle piante di prova, 2.7% contro 1.9%)
    dist = ndimage.distance_transform_edt(libero)
    r_px = chiu_u / res_u
    libero_chiuso = dist > r_px                             # porte chiuse
    lab, _ = ndimage.label(libero_chiuso)
    bordo = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))

    x0, y0, x1, y1 = finestra
    risultati = []
    usati = {}
    for et in etichette(msp, finestra, set(layer_etichette)):
        cx, cy = et["punto"]
        c, r = int(round((cx - x0) / res_u)), int(round((y1 - cy) / res_u))
        rec = {"nome": et["nome"], "superficie_dichiarata": et["superficie_dichiarata"],
               "etichetta": [round(cx, 1), round(cy, 1)], "esito": "OK", "note": ""}
        idx = lab[r, c] if 0 <= r < lab.shape[0] and 0 <= c < lab.shape[1] else 0
        if idx == 0:                                         # etichetta vicino a un muro
            ys, xs = np.nonzero(lab[max(0, r - 60):r + 60, max(0, c - 60):c + 60])
            if len(ys):
                k = int(np.argmin((ys - min(r, 60)) ** 2 + (xs - min(c, 60)) ** 2))
                idx = lab[max(0, r - 60) + ys[k], max(0, c - 60) + xs[k]]
        if idx == 0 or idx in bordo:
            rec.update(esito="NON TROVATO",
                       note="locale aperto verso l'esterno o etichetta fuori dai muri")
            risultati.append(rec)
            continue
        if idx in usati:
            rec["note"] = f"stesso spazio di '{usati[idx]}' (locali non separati da muri/porte)"
            rec["esito"] = "DA VERIFICARE"
        usati.setdefault(idx, et["nome"])
        nucleo = lab == idx
        # NB: provata anche la crescita simultanea di tutti i locali nello spazio
        # libero: peggiora (i bagni inglobano i disimpegni stretti senza etichetta)
        regione = (ndimage.distance_transform_edt(~nucleo) <= r_px + 1) & libero
        # i muri sono disegnati con 2 px di spessore: si riporta il bordo sul filo muro
        regione = ndimage.binary_dilation(regione, iterations=BORDO_PX)
        poli = contorno(regione, finestra, res_u, tol=res_u * 1.5)
        a_m2 = area(poli) * (f / 100) ** 2
        rec["poligono"] = [[round(x, 1), round(y, 1)] for x, y in poli]
        rec["superficie_calcolata"] = round(a_m2, 2)
        if et["superficie_dichiarata"]:
            sc = (a_m2 - et["superficie_dichiarata"]) / et["superficie_dichiarata"] * 100
            rec["scostamento_%"] = round(sc, 1)
            if abs(sc) > 5 and rec["esito"] == "OK":
                rec["esito"] = "DA VERIFICARE"
                rec["note"] = f"superficie diversa da quella in pianta ({sc:+.1f}%)"
        risultati.append(rec)
    # nomi ripetuti nella stessa pianta (es. etichette rimaste dallo stato di fatto)
    from collections import Counter
    doppi = {n for n, k in Counter(r["nome"] for r in risultati).items() if k > 1}
    for r in risultati:
        if r["nome"] in doppi:
            r["esito"] = "DA VERIFICARE" if r["esito"] == "OK" else r["esito"]
            nota = "nome ripetuto nella pianta (etichetta duplicata o rimasta dallo stato di fatto?)"
            r["note"] = f"{r['note']}; {nota}" if r["note"] else nota
    return risultati


def locali_da_polilinee(doc, finestra, layer="_SUP", unita="cm"):
    """Locali già disegnati come polilinee chiuse (es. layer _SUP), abbinati alle etichette."""
    f = UNITA_IN_CM[unita]
    msp = doc.modelspace()
    ets = etichette(msp, finestra)
    from matplotlib.path import Path as MPath
    out = []
    x0, y0, x1, y1 = finestra
    for p in msp.query("LWPOLYLINE"):
        if p.dxf.layer != layer:
            continue
        pts = [(x, y) for x, y in p.get_points("xy")]
        cx, cy = sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)
        if not (x0 <= cx <= x1 and y0 <= cy <= y1):
            continue
        mp = MPath(pts)
        nome = next((e["nome"] for e in ets if mp.contains_point(e["punto"])), None)
        out.append({"nome": nome, "poligono": pts,
                    "superficie": round(area(pts) * (f / 100) ** 2, 2)})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pianta")
    ap.add_argument("--finestra", required=True)
    ap.add_argument("--unita", default="cm", choices=list(UNITA_IN_CM))
    ap.add_argument("--chiusura", type=float, default=50.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    doc = ezdxf.readfile(a.pianta)
    fin = tuple(float(v) for v in a.finestra.split(","))
    res = trova_locali(doc, fin, a.unita, chiusura=a.chiusura)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    for r in res:
        sd = f"{r['superficie_dichiarata']:.2f}" if r["superficie_dichiarata"] else "  -  "
        sc = r.get("superficie_calcolata")
        print(f"{r['esito']:13} {r['nome'][:34]:34} calc={sc if sc is not None else '-':>6}  "
              f"dich={sd}  {r.get('scostamento_%', ''):>6}  {r['note']}")


if __name__ == "__main__":
    main()
