"""
Computo simboli di una planimetria impianto.

Legge una tavola DXF, conta i simboli (blocchi) per tipo e per impianto
(layer) e assegna la descrizione da:
  1. catalogo_simboli.csv (verificato dall'utente)  -> fonte "CATALOGO"
  2. la legenda presente nella tavola stessa         -> fonte "LEGENDA TAVOLA"
  3. nessuna                                         -> "DA CLASSIFICARE"

I blocchi dinamici (*U41, *U30...) vengono ricondotti al blocco originale.
Vengono contati solo i simboli DENTRO la cornice della tavola (la polilinea
chiusa più grande nello spazio modello): i simboli "parcheggiati" fuori
foglio non finiscono a computo. Non vengono contati i riferimenti esterni
(xref: pianta base, cartiglio) né i simboli disegnati nella legenda.

Uso:
    python computo.py <tavola.dxf> <PROGETTO> [--layer-legenda "LEGENDA EM"] [--senza-cornice] [--json]

Output:
    Projects/<PROGETTO>/<nome tavola>_computo.xlsx
    (con --json stampa anche il risultato in JSON, usato dai test LOCK)
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import ezdxf

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))
sys.path.insert(0, str(QUI.parent / "cad-output"))

import simboli as sm  # noqa: E402

WORKSPACE = QUI.parents[1]


def blocchi_esclusi(doc):
    """xref e blocchi di servizio da non contare."""
    escl = set()
    for b in doc.blocks:
        if b.block.dxf.flags & 4:            # xref
            escl.add(b.name)
        elif b.name.upper().startswith("CARTIGLIO"):   # cartiglio incorporato
            escl.add(b.name)
    return escl


def cornice(msp):
    """Cornice della tavola: la polilinea chiusa più grande nello spazio modello."""
    from ezdxf import bbox
    chiuse = [p for p in msp.query("LWPOLYLINE") if p.closed]
    if not chiuse:
        return None
    def area(p):
        e = bbox.extents([p])
        return e.size.x * e.size.y
    e = bbox.extents([max(chiuse, key=area)])
    return (e.extmin.x, e.extmin.y, e.extmax.x, e.extmax.y)


def dentro(box, x, y):
    return box and box[0] <= x <= box[2] and box[1] <= y <= box[3]


def computo(path: Path, layer_legenda=None, usa_cornice=True, descrizioni_extra=None):
    """descrizioni_extra: {blocco: descrizione} (es. "descrizioni" di un file di regole)"""
    descrizioni_extra = descrizioni_extra or {}
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    escl = blocchi_esclusi(doc)
    catalogo = sm.carica_catalogo()

    # legenda della tavola (se c'è)
    voci, _ = sm.abbina_legenda(doc, msp, layer_testi=layer_legenda, h_min=20.0,
                                distanza_max=400.0) if layer_legenda else ([], [])
    leg_desc = {}
    for v in voci:
        for s in v["simboli"]:
            leg_desc.setdefault(s["blocco"], v["testo"])
    in_legenda = set().union(*(v.get("handles", set()) for v in voci)) if voci else set()
    foglio = cornice(msp) if usa_cornice else None

    conteggi = Counter()                 # (blocco, layer) -> n
    fuori = 0
    for ins in msp.query("INSERT"):
        if ins.dxf.name in escl:
            continue
        nome = sm.nome_simbolo(doc, ins)
        if nome.startswith(sm.IGNORA_PREFISSI):
            continue
        if ins.dxf.handle in in_legenda:  # simbolo di legenda, non di impianto
            continue
        try:                              # simbolo della legenda automatica (legenda.py)
            if ins.get_xdata("PLANIMETRIA_IMPIANTO")[0][1] == "LEGENDA":
                continue
        except ezdxf.DXFValueError:
            pass
        cx, cy, _, _ = sm.centro(ins)
        if foglio and not dentro(foglio, cx, cy):
            fuori += 1
            continue
        conteggi[(nome, ins.dxf.layer)] += 1

    righe = []
    for (nome, layer), n in sorted(conteggi.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        cat = catalogo.get(nome) or catalogo.get(nome.upper())
        if cat:
            descr = sorted({r["DESCRIZIONE"] for r in cat})
            a_computo = all(r["A_COMPUTO"].strip().upper() != "NO" for r in cat)
            fonte = "CATALOGO"
            nota = "" if len(descr) == 1 else "blocco usato per piu' voci: separare (soluzione A)"
            descrizione = descr[0] if len(descr) == 1 else " / ".join(descr)
        elif nome in descrizioni_extra:
            descrizione, fonte, a_computo, nota = descrizioni_extra[nome], "REGOLE", True, "aggiungere al catalogo"
        elif nome in leg_desc:
            descrizione, fonte, a_computo, nota = leg_desc[nome], "LEGENDA TAVOLA", True, "aggiungere al catalogo"
        else:
            descrizione, fonte, a_computo, nota = "", "DA CLASSIFICARE", True, "blocco non in catalogo ne' in legenda"
        righe.append({"impianto": layer, "blocco": nome, "descrizione": descrizione,
                      "quantita": n, "a_computo": a_computo, "fonte": fonte, "note": nota})

    return {
        "tavola": path.name,
        "righe": righe,
        "totale_simboli": sum(r["quantita"] for r in righe if r["a_computo"]),
        "da_classificare": sum(1 for r in righe if r["fonte"] == "DA CLASSIFICARE"),
        "voci_legenda_trovate": len(voci),
        "cornice": [round(v) for v in foglio] if foglio else None,
        "simboli_fuori_cornice": fuori,
    }


def scrivi_excel(res, out: Path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Computo"
    ws.append([f"COMPUTO SIMBOLI - {res['tavola']}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    intest = ["IMPIANTO (layer)", "BLOCCO", "DESCRIZIONE", "QUANTITA'", "A COMPUTO", "FONTE", "NOTE"]
    ws.append(intest)
    for c in range(1, len(intest) + 1):
        ws.cell(row=3, column=c).font = Font(bold=True)
        ws.cell(row=3, column=c).fill = PatternFill("solid", fgColor="D9D9D9")
    giallo = PatternFill("solid", fgColor="FFF2CC")
    rosso = PatternFill("solid", fgColor="F8CBAD")
    for r in res["righe"]:
        ws.append([r["impianto"], r["blocco"], r["descrizione"], r["quantita"],
                   "SI" if r["a_computo"] else "NO", r["fonte"], r["note"]])
        riga = ws.max_row
        if r["fonte"] == "DA CLASSIFICARE":
            for c in range(1, 8):
                ws.cell(row=riga, column=c).fill = rosso
        elif r["note"]:
            for c in range(1, 8):
                ws.cell(row=riga, column=c).fill = giallo

    # riepilogo per impianto
    ws2 = wb.create_sheet("Riepilogo impianti")
    ws2.append(["IMPIANTO (layer)", "N. SIMBOLI A COMPUTO"])
    for c in (1, 2):
        ws2.cell(row=1, column=c).font = Font(bold=True)
    tot = defaultdict(int)
    for r in res["righe"]:
        if r["a_computo"]:
            tot[r["impianto"]] += r["quantita"]
    for k in sorted(tot):
        ws2.append([k, tot[k]])
    ws2.append(["TOTALE", sum(tot.values())])
    ws2.cell(row=ws2.max_row, column=1).font = Font(bold=True)

    for sheet, larghezze in ((ws, [20, 28, 80, 11, 11, 18, 45]), (ws2, [24, 22])):
        for i, w in enumerate(larghezze, 1):
            sheet.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=4, min_col=3, max_col=3):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tavola")
    ap.add_argument("progetto")
    ap.add_argument("--layer-legenda", action="append",
                    help="layer dei testi della legenda nella tavola (ripetibile)")
    ap.add_argument("--senza-cornice", action="store_true",
                    help="conta anche i simboli fuori dalla cornice della tavola")
    ap.add_argument("--regole", help="file di regole: usa le sue descrizioni dei simboli")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    extra = json.loads(Path(a.regole).read_text(encoding="utf-8")).get("descrizioni", {}) if a.regole else None

    path = Path(a.tavola)
    res = computo(path, layer_legenda=set(a.layer_legenda) if a.layer_legenda else None,
                  usa_cornice=not a.senza_cornice, descrizioni_extra=extra)
    out = WORKSPACE / "Projects" / a.progetto / f"{path.stem}_computo.xlsx"
    scrivi_excel(res, out)
    res["file"] = str(out)
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(f"Computo salvato: {out}")
        print(f"Simboli a computo: {res['totale_simboli']}  |  "
              f"tipi da classificare: {res['da_classificare']}  |  "
              f"voci legenda tavola: {res['voci_legenda_trovate']}  |  "
              f"esclusi fuori cornice: {res['simboli_fuori_cornice']}")


if __name__ == "__main__":
    main()
