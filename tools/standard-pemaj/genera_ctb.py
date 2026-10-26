"""
Studio Pemaj - Generatore stili di stampa CTB dalla tabella master.

Uso:   python genera_ctb.py PEMAJ_stili_master.xlsx [cartella_uscita]
Richiede:  pip install ezdxf openpyxl

Ogni coppia di colonne "Colore NOME" / "Spessore NOME (mm)" del foglio MASTER
genera il file PEMAJ_NOME.ctb (es. PROGETTI, DIRI, SCHEMI).
Colore: #RRGGBB oppure OGGETTO. Spessore: mm (punto decimale) oppure OGGETTO.
"""
import sys
import zlib
import json
from io import StringIO
from pathlib import Path
from struct import pack

from ezdxf.addons import acadctb
from openpyxl import load_workbook

OBJ = "OGGETTO"


def leggi_master(path):
    ws = load_workbook(path, data_only=True)["MASTER"]
    hdr = [str(c.value or "").strip() for c in ws[1]]
    stili = {}
    for i, h in enumerate(hdr):
        if h.upper().startswith("COLORE "):
            nome = h[7:].strip().upper()
            j = next((k for k, hh in enumerate(hdr) if hh.upper().startswith("SPESSORE " + nome)), None)
            if j is None:
                sys.exit(f"ERRORE: manca la colonna 'Spessore {nome} (mm)'")
            stili[nome] = (i, j)
    if not stili:
        sys.exit("ERRORE: nessuna coppia di colonne Colore/Spessore trovata")
    righe = {int(r[0]): r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] is not None}
    mancanti = set(range(1, 256)) - set(righe)
    if mancanti:
        sys.exit(f"ERRORE: mancano nel master gli ACI {sorted(mancanti)}")
    return stili, righe


def norm_lw(v, aci):
    if v is None or str(v).strip().upper() == OBJ:
        return 0.0
    try:
        return round(float(str(v).replace(",", ".")), 3)
    except ValueError:
        sys.exit(f"ERRORE: spessore non valido per ACI {aci}: {v!r}")


def norm_col(v, aci):
    s = str(v).strip().upper() if v is not None else OBJ
    if s == OBJ:
        return None
    s = s.lstrip("#")
    if len(s) != 6:
        sys.exit(f"ERRORE: colore non valido per ACI {aci}: {v!r}")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def salva_ctb(ctb, out):
    """Scrittura CTB (header a 4 byte, spessori con 3 decimali)."""
    mem = StringIO()
    ctb.write_content(mem)
    body = mem.getvalue()
    ini = body.index("custom_lineweight_table{")
    fine = body.index("}", ini) + 1
    tab = "custom_lineweight_table{\n" + "".join(
        f" {i}={w:.3f}\n" for i, w in enumerate(ctb.lineweights)) + "}"
    body = body[:ini] + tab + body[fine:] + chr(0)
    comp = zlib.compress(body.encode())
    with open(out, "wb") as f:
        f.write(b"PIAFILEVERSION_2.0,CTBVER1,compress\r\npmzlibcodec")
        f.write(pack("<III", zlib.adler32(comp), len(body), len(comp)))
        f.write(comp)


def crea_ctb(valori, descrizione, out):
    ctb = acadctb.new_ctb()
    ctb.description = descrizione
    usati = sorted({lw for _, lw in valori.values()})
    if len(usati) > 27:
        sys.exit(f"ERRORE: {descrizione}: {len(usati)} spessori diversi, massimo 27")
    tabella = usati + [usati[-1]] * (27 - len(usati))
    for i, lw in enumerate(tabella):
        ctb.set_table_lineweight(i, lw)
    for aci, (col, lw) in valori.items():
        st = ctb[aci]
        if col is None:
            st.set_object_color()
        else:
            st.color = col
        st.lineweight = usati.index(lw)
        st.dithering = True
        st.grayscale = False
        st.screen = 100
    salva_ctb(ctb, out)
    return out


def genera(master, outdir):
    """Crea un CTB per ogni coppia di colonne del master. Ritorna l'elenco dei file creati."""
    stili, righe = leggi_master(master)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    creati = []
    for nome, (ic, il) in stili.items():
        val = {a: (norm_col(r[ic], a), norm_lw(r[il], a)) for a, r in righe.items()}
        out = outdir / f"PEMAJ_{nome}.ctb"
        crea_ctb(val, f"Studio Pemaj - {nome.lower()} (disegno 1:1, annotativo)", out)
        creati.append(str(out))
    return creati


def confronta(master, outdir):
    """Rilegge i CTB e li confronta colore per colore con il master. Ritorna {stile: [discrepanze]}."""
    stili, righe = leggi_master(master)
    esito = {}
    for nome, (ic, il) in stili.items():
        f = Path(outdir) / f"PEMAJ_{nome}.ctb"
        if not f.exists():
            esito[nome] = ["FILE_MANCANTE"]
            continue
        ctb = acadctb.load(str(f))
        diff = []
        for a, r in righe.items():
            st = ctb[a]
            col = None if st.has_object_color() else tuple(st.color)
            lw = round(st.get_lineweight(), 3)
            if col != norm_col(r[ic], a) or abs(lw - norm_lw(r[il], a)) > 0.0005:
                diff.append(a)
        esito[nome] = diff
    return esito


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    creati = genera(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ".")
    print(json.dumps({"status": "ok", "creati": creati}, indent=2))
