"""
Prepara tavola impianto (Fase 2).

Crea una tavola DXF vuota pronta per disegnare l'impianto in AutoCAD LT,
con l'impaginazione delle tavole dell'utente (ricavata da ALLEGATO E01):

  - cornice A1 (doppia polilinea) nello spazio modello
  - cartiglio come xref (CARTIGLIO BASE.dwg) a scala 10
  - pianta architettonica come xref, ritagliata (XCLIP) sulla zona scelta
    e centrata nell'area disegno; layer della pianta in grigio (colore 8)
  - layer degli impianti con i colori dell'utente
  - testi: "ALLEGATO Exx", titolo tavola, titolo sottolineato, "LEGENDA"

Unità: come nelle tavole dell'utente lo spazio modello è in CENTIMETRI e la
stampa è a 1:100 (cornice A1 x10). Le piante sono spesso in cm anche se il
file dichiara "mm": l'unità reale va indicata con --unita (cm|mm).
Lo script controlla le quote della pianta e avvisa se l'unità sembra sbagliata.

AutoCAD accetta come xref solo file DWG: servono sia il .dwg (xref) sia il
.dxf (letto dallo script per layer e ingombri) con lo stesso nome.
I DWG vengono copiati nella cartella del progetto e collegati con percorso
relativo, così la cartella del progetto è autonoma.

Uso:
    python prepara_tavola.py --progetto VJN001 --numero E01 ^
        --titolo "DISTRIBUZIONE ILLUMINAZIONE ORDINARIA E DI SICUREZZA" ^
        --pianta "riferimenti/Planimetria di Base" --unita cm ^
        [--finestra x0,y0,x1,y1] [--cartiglio "riferimenti/CARTIGLIO BASE"] ^
        [--scala 100] [--anteprima]

--finestra : zona della pianta da mostrare, in coordinate della pianta
             (default: ingombro di tutto lo spazio modello della pianta)
--anteprima: salva anche un PNG di controllo con la pianta incorporata
"""

import argparse
import json
import shutil
import statistics
import sys
from pathlib import Path

import ezdxf
from ezdxf import bbox, xclip, xref
from ezdxf.enums import TextEntityAlignment

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI.parent / "cad-output"))
import dxf_writer as dw  # noqa: E402

# ── Impaginazione (da ALLEGATO E01, scala 1:100, coordinate relative al
#    vertice in basso a sinistra della cornice esterna, unità = cm) ─────────
CORNICE = (8440.0, 5970.0)
CORNICE_OFFSET_INTERNA = 50.0
CARTIGLIO_INS = (-19968.0, -11134.0)
CARTIGLIO_SCALA = 10.0
AREA_PIANTA = (2122.0, 438.0, 8310.0, 5385.0)       # x0, y0, x1, y1
TESTI = {
    # chiave: (x, y, altezza, layer)
    "numero":      (758.0, 4211.0, 60.0, "Testo Fisso"),
    "sottotitolo": (239.0, 4116.0, 40.0, "Testo Fisso"),
    "titolo":      (4073.0, 5517.0, 54.0, "0"),
    "legenda":     (870.0, 2945.0, 50.0, "TESTI"),
}

# Layer impianti dell'utente: nome -> (colore ACI, tipo linea, spessore)
LAYER_IMPIANTI = {
    "LC":               (3,   "Continuous", -3),
    "FM":               (240, "Continuous", -3),
    "EM":               (4,   "Continuous", -3),
    "SER":              (204, "Continuous", -3),
    "SERVIZI":          (204, "Continuous", -3),
    "QUADRI":           (164, "Continuous", -3),
    "IMP. ANTINCENDIO": (4,   "Continuous", -3),
    "EVAC":             (6,   "Continuous", -3),
    "RETE":             (14,  "Continuous", -3),
    "TERRA":            (12,  "Continuous", -3),
    "CAN":              (30,  "Continuous", -3),
    "VENT":             (40,  "Continuous", -3),
    "TESTI":            (7,   "Continuous", -3),
    "Testo Fisso":      (244, "Continuous", 30),
    "LEGENDA":          (7,   "Continuous", -3),
    "LOCALI":           (8,   "Continuous", -3),
}
COLORE_PIANTA = 8
UNITA_IN_CM = {"cm": 1.0, "mm": 0.1, "m": 100.0}


def _scala_pos(p, k):
    return (p[0] * k, p[1] * k)


def controlla_unita(doc):
    """
    Stima l'unità reale dalla mediana delle quote: in cm le quote tipiche di
    muri/porte sono 50-2000, in mm 500-20000. Ritorna 'cm', 'mm' o None.
    """
    misure = []
    for d in doc.modelspace().query("DIMENSION"):
        try:
            m = d.get_measurement()
        except Exception:
            continue
        if isinstance(m, float) and m > 1:
            misure.append(m)
    if len(misure) < 5:
        return None
    med = statistics.median(misure)
    if 40 <= med <= 2500:
        return "cm"
    if 400 <= med <= 25000:
        return "mm"
    return None


def ingombro(doc):
    e = bbox.extents(doc.modelspace(), fast=True)
    return (e.extmin.x, e.extmin.y, e.extmax.x, e.extmax.y)


GAP_PIANTE = 300.0          # distanza tra piante affiancate (cm a 1:100)
ETICHETTA_H = 40.0          # altezza etichetta sotto ogni pianta
ETICHETTA_GAP = 120.0       # distanza etichetta dal bordo inferiore della pianta


def incorpora_cartiglio(doc, cartiglio_dxf: Path, nome_blocco: str, dati: dict, attributi: dict):
    """
    Copia il cartiglio (DXF) dentro la tavola come blocco, sostituendo i testi
    variabili (dati["testi"]: {testo originale: testo nuovo}, "" = elimina) e
    compilando gli attributi del blocco interno (es. SCALA, N°DISEGNO, DATA1).
    Ritorna i testi da sostituire che non sono stati trovati.
    """
    sdoc = ezdxf.readfile(cartiglio_dxf)
    smsp = sdoc.modelspace()
    sostituzioni = dati.get("testi", {})
    trovati = set()
    for t in list(smsp.query("TEXT")):
        if t.dxf.text in sostituzioni:
            trovati.add(t.dxf.text)
            nuovo = sostituzioni[t.dxf.text]
            if nuovo == "":
                smsp.delete_entity(t)
            else:
                t.dxf.text = nuovo
    mancanti = [k for k in sostituzioni if k not in trovati]
    attr = {**dati.get("attributi", {}), **attributi}
    for ins in smsp.query("INSERT"):
        for a in ins.attribs:
            if a.dxf.tag in attr:
                a.dxf.text = str(attr[a.dxf.tag])
    blk = doc.blocks.new(nome_blocco)
    loader = xref.Loader(sdoc, doc)
    loader.load_modelspace(target_layout=blk)
    loader.execute()
    return mancanti


def prepara(progetto, numero, titolo, pianta, unita, finestra=None,
            cartiglio=QUI / "riferimenti" / "CARTIGLIO BASE", scala=100,
            sottotitolo=None, out_dir=None, anteprima=False,
            finestre=None, cartiglio_dati=None):
    """
    finestra       : una sola zona di pianta (x0,y0,x1,y1)
    finestre       : piu' zone sulla stessa tavola, affiancate:
                     [{"finestra": (x0,y0,x1,y1), "etichetta": "PIANTA PIANO TERRA"}, ...]
    cartiglio_dati : None -> cartiglio come xref (DWG);
                     dict -> cartiglio incorporato e compilato (vedi incorpora_cartiglio)
    """
    pianta = Path(pianta)
    cartiglio = Path(cartiglio)
    p_dwg, p_dxf = pianta.with_suffix(".dwg"), pianta.with_suffix(".dxf")
    c_dwg, c_dxf = cartiglio.with_suffix(".dwg"), cartiglio.with_suffix(".dxf")
    richiesti = [p_dwg, p_dxf] + ([c_dxf] if cartiglio_dati is not None else [c_dwg])
    for f in richiesti:
        if not f.exists():
            raise FileNotFoundError(f"File mancante: {f}")
    if unita not in UNITA_IN_CM:
        raise ValueError("--unita deve essere cm, mm o m")

    k = scala / 100.0                      # fattore impaginazione rispetto a 1:100
    pdoc = ezdxf.readfile(p_dxf)
    avvisi = []
    stima = controlla_unita(pdoc)
    if stima and stima != unita:
        avvisi.append(f"ATTENZIONE: dalle quote la pianta sembra in {stima}, "
                      f"ma e' stata indicata in {unita}.")

    f = UNITA_IN_CM[unita]
    if finestre is None:
        finestre = [{"finestra": tuple(finestra) if finestra else ingombro(pdoc), "etichetta": None}]

    # ingombro del gruppo di piante (in cm sulla tavola)
    dims = [((w[2] - w[0]) * f, (w[3] - w[1]) * f) for w in (z["finestra"] for z in finestre)]
    con_etichette = any(z.get("etichetta") for z in finestre)
    extra_basso = (ETICHETTA_GAP + ETICHETTA_H) * k if con_etichette else 0.0
    gap = GAP_PIANTE * k
    larg = sum(d[0] for d in dims) + gap * (len(dims) - 1)
    alt = max(d[1] for d in dims) + extra_basso
    ax0, ay0, ax1, ay1 = (v * k for v in AREA_PIANTA)
    if larg > (ax1 - ax0) + 1e-6 or alt > (ay1 - ay0) + 1e-6:
        serve = max(larg / (ax1 - ax0) * scala, alt / (ay1 - ay0) * scala)
        raise ValueError(
            f"La zona di pianta ({larg / 100:.1f} x {alt / 100:.1f} m) non entra nell'area "
            f"disegno a 1:{scala}. Serve almeno 1:{serve:.0f}, oppure una --finestra piu' piccola.")

    # ── disegno ──────────────────────────────────────────────────────────
    doc, msp = dw.new_drawing(text_height=2.5, scale=scala / 10.0, layers=LAYER_IMPIANTI)
    doc.header["$VISRETAIN"] = 1           # mantiene i colori impostati sui layer dell'xref
    doc.header["$XCLIPFRAME"] = 2          # bordo del ritaglio visibile ma non stampato (come E01)
    doc.header["$LTSCALE"] = 1.0           # come E01

    W, H = CORNICE[0] * k, CORNICE[1] * k
    o = CORNICE_OFFSET_INTERNA * k
    dw.rect(msp, 0, 0, W, H, layer="0")
    dw.rect(msp, o, o, W - 2 * o, H - 2 * o, layer="0")

    # cartiglio: xref (DWG) oppure incorporato e compilato
    cart_attr = {"scala": CARTIGLIO_SCALA * k}
    cart_attribs = {"SCALA": f"1:{scala}", "N°DISEGNO": numero}
    if cartiglio_dati is None:
        nome_cart = cartiglio.stem
        xref.define(doc, nome_cart, f".\\{c_dwg.name}")
        cart_attr["xref"] = c_dwg.name
    else:
        nome_cart = cartiglio_dati.get("nome_blocco", f"CARTIGLIO {progetto}")
        mancanti = incorpora_cartiglio(doc, c_dxf, nome_cart, cartiglio_dati, cart_attribs)
        if mancanti:
            avvisi.append("Testi del cartiglio non trovati (non sostituiti): " + "; ".join(mancanti))
        cart_attr["incorporato"] = nome_cart
    msp.add_blockref(nome_cart, _scala_pos(CARTIGLIO_INS, k),
                     dxfattribs={"xscale": CARTIGLIO_SCALA * k, "yscale": CARTIGLIO_SCALA * k,
                                 "zscale": CARTIGLIO_SCALA * k, "layer": "0"})

    # piante (xref) affiancate, gruppo centrato nell'area disegno, ognuna ritagliata
    nome_pianta = pianta.stem
    xref.define(doc, nome_pianta, f".\\{p_dwg.name}")
    gx = (ax0 + ax1) / 2 - larg / 2
    gy_top = (ay0 + ay1) / 2 + alt / 2
    piante = []
    for z, (dl, da) in zip(finestre, dims):
        x0, y0, x1, y1 = z["finestra"]
        if len(finestre) == 1 and not z.get("etichetta"):
            cx, cy = (ax0 + ax1) / 2, (ay0 + ay1) / 2      # pianta singola: centrata
        else:
            cx, cy = gx + dl / 2, gy_top - da / 2          # allineate in alto
        ins_pt = (cx - (x0 + x1) / 2 * f, cy - (y0 + y1) / 2 * f)
        ins = msp.add_blockref(nome_pianta, ins_pt,
                               dxfattribs={"xscale": f, "yscale": f, "zscale": f, "layer": "0"})
        xclip.XClip(ins).set_block_clipping_path([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        if z.get("etichetta"):
            t = msp.add_text(f"%%U{z['etichetta']}", height=ETICHETTA_H * k,
                             dxfattribs={"layer": "TESTI", "style": "Standard"})
            t.set_placement((cx, cy - da / 2 - ETICHETTA_GAP * k),
                            align=TextEntityAlignment.TOP_CENTER)
        piante.append({"finestra": [round(v, 1) for v in (x0, y0, x1, y1)],
                       "inserimento": [round(v, 1) for v in ins_pt],
                       "scala_xref": f,
                       "etichetta": z.get("etichetta"),
                       "ingombro_tavola": [round(cx - dl / 2, 1), round(cy - da / 2, 1),
                                           round(cx + dl / 2, 1), round(cy + da / 2, 1)]})
        gx += dl + gap

    # layer della pianta in grigio (override salvati nella tavola, VISRETAIN=1)
    for lay in pdoc.layers:
        n = lay.dxf.name
        if n in ("0", "Defpoints") or "|" in n:
            continue
        xl = doc.layers.add(f"{nome_pianta}|{n}", color=COLORE_PIANTA)
        xl.dxf.flags |= 16 | 32            # dipendente da xref, risolto

    # testi
    def scrivi(chiave, contenuto):
        x, y, h, layer = TESTI[chiave]
        return msp.add_text(contenuto, height=h * k,
                            dxfattribs={"layer": layer, "style": "Standard", "insert": (x * k, y * k)})

    scrivi("numero", f"ALLEGATO {numero}")
    scrivi("sottotitolo", sottotitolo or titolo)
    scrivi("titolo", f"%%U{titolo}")
    scrivi("legenda", "LEGENDA")

    # ── salvataggio ──────────────────────────────────────────────────────
    nome_file = f"ALLEGATO {numero} {titolo}"
    if out_dir is None:
        out_dir = dw.project_dir(progetto)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    da_copiare = [p_dwg] + ([c_dwg] if cartiglio_dati is None else [])
    for src in da_copiare:                 # xref accanto alla tavola
        dst = out_dir / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
    out = dw.save_to(doc, out_dir / f"{nome_file}.dxf")

    res = {
        "tavola": str(out),
        "scala": f"1:{scala}",
        "pianta": {"xref": p_dwg.name, "unita": unita, "unita_stimata": stima,
                   "finestra": piante[0]["finestra"], "inserimento": piante[0]["inserimento"],
                   "scala_xref": f},
        "piante": piante,
        "cartiglio": cart_attr,
        "cornice": [0, 0, W, H],
        "avvisi": avvisi,
    }
    if anteprima:
        res["anteprima"] = str(salva_anteprima(out, p_dxf, c_dxf, nome_pianta,
                                               nome_cart if cartiglio_dati is None else None))
    return res


def salva_anteprima(tavola: Path, pianta_dxf: Path, cartiglio_dxf: Path, nome_pianta, nome_cart):
    """PNG di controllo: copia della tavola con gli xref incorporati dai DXF."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    import logging
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy

    logging.getLogger("ezdxf").setLevel(logging.ERROR)   # avvisi della sola copia di anteprima
    doc = ezdxf.readfile(tavola)
    sorgenti = {nome_pianta: pianta_dxf, nome_cart: cartiglio_dxf}
    for nome, src in sorgenti.items():
        if nome and src.exists() and doc.blocks.get(nome) is not None:
            xref.embed(doc.blocks.get(nome), load_fn=lambda _p, s=src: ezdxf.readfile(s))
    # come in LT con VISRETAIN: pianta in grigio
    for lay in doc.layers:
        if lay.dxf.name.startswith(nome_pianta):
            lay.dxf.color = COLORE_PIANTA
            lay.dxf.discard("true_color")
    fig = plt.figure(figsize=(16.8, 11.9), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE)
    Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=True)
    png = tavola.with_name(tavola.stem + "_anteprima.png")
    fig.savefig(png, dpi=100, facecolor="white")
    plt.close(fig)
    return png


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--progetto", required=True)
    ap.add_argument("--numero", required=True, help="es. E01")
    ap.add_argument("--titolo", required=True)
    ap.add_argument("--sottotitolo")
    ap.add_argument("--pianta", required=True, help="percorso senza estensione: servono .dwg e .dxf")
    ap.add_argument("--unita", required=True, choices=list(UNITA_IN_CM))
    ap.add_argument("--finestra", help="x0,y0,x1,y1 in coordinate della pianta")
    ap.add_argument("--cartiglio", default=str(QUI / "riferimenti" / "CARTIGLIO BASE"))
    ap.add_argument("--scala", type=int, default=100)
    ap.add_argument("--anteprima", action="store_true")
    a = ap.parse_args()
    fin = tuple(float(v) for v in a.finestra.split(",")) if a.finestra else None
    try:
        res = prepara(a.progetto, a.numero, a.titolo, a.pianta, a.unita, fin,
                      a.cartiglio, a.scala, a.sottotitolo, anteprima=a.anteprima)
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)
    res["status"] = "ok"
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
