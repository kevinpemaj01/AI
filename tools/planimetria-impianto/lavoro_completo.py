"""
Lavoro completo: dalla pianta architettonica alle tavole impianto finite.

Esegue in ordine, leggendo un file di lavoro JSON del progetto:
  1. prepara_tavola   - una tavola per voce di "tavole" (cornice, cartiglio, piante)
  2. aggiungi_locali  - contorni locali + tabella <P>_locali.xlsx
  3. dotazioni        - quantità per locale dal file di regole (solo celle vuote)
  4. posa             - simboli nei locali, per ogni tavola solo i suoi impianti
  5. legenda          - legenda automatica su ogni tavola
  6. computo          - <tavola>_computo.xlsx
  7. anteprima        - PNG di controllo di ogni tavola

Uso:
    python lavoro_completo.py Projects/<P>/lavoro_<P>.json

Esempio di file di lavoro: Projects/VJN001/lavoro_VJN001.json
"""

import json
import logging
import sys
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))
logging.getLogger("ezdxf").setLevel(logging.ERROR)

import aggiungi_locali as al   # noqa: E402
import computo as cp           # noqa: E402
import dotazioni as dt         # noqa: E402
import legenda as lg           # noqa: E402
import posa as ps              # noqa: E402
import prepara_tavola as pt    # noqa: E402


def esegui(lavoro_json):
    lavoro_json = Path(lavoro_json).resolve()
    L = json.loads(lavoro_json.read_text(encoding="utf-8"))
    base = lavoro_json.parent                       # percorsi relativi alla cartella del progetto
    P = L["progetto"]
    pianta = (base / L["pianta"]).resolve()         # senza estensione: .dwg + .dxf
    regole = (QUI / L["regole"]).resolve() if L.get("regole") else None
    cart = json.loads((base / L["cartiglio_dati"]).read_text(encoding="utf-8")) if L.get("cartiglio_dati") else None
    finestre = [{"finestra": tuple(f["finestra"]), "etichetta": f.get("etichetta")} for f in L["finestre"]]
    rapporto = {"progetto": P, "tavole": []}

    tavole = []
    for t in L["tavole"]:
        r = pt.prepara(P, t["numero"], t["titolo"], pianta, L.get("unita", "cm"),
                       finestre=finestre, cartiglio_dati=cart, scala=L.get("scala", 100), out_dir=base)
        if r["avvisi"]:
            rapporto.setdefault("avvisi", []).extend(r["avvisi"])
        al.aggiungi(r["tavola"], pianta.with_suffix(".dxf"), P, L.get("unita", "cm"), out_dir=base)
        tavole.append((t, Path(r["tavola"])))

    tabella = base / f"{P}_locali.xlsx"
    if regole:
        d = dt.compila(tabella, regole, P)
        rapporto["dotazioni"] = {"regole": d["regole"], "totali_aggiunti": d["totali_aggiunti"],
                                 "avvisi": d["avvisi"]}

    for t, tav in tavole:
        r = ps.posa(tav, tabella, pianta.with_suffix(".dxf"), set(t["impianti"]))
        g = lg.genera(tav, regole)
        extra = json.loads(regole.read_text(encoding="utf-8")).get("descrizioni", {}) if regole else None
        c = cp.computo(tav, descrizioni_extra=extra)
        xlsx = cp.scrivi_excel(c, tav.with_name(f"{tav.stem}_computo.xlsx"))
        png = pt.salva_anteprima(tav, pianta.with_suffix(".dxf"), Path(), pianta.stem, None)
        rapporto["tavole"].append({
            "tavola": tav.name, "impianti": t["impianti"], "posati": r["posati"],
            "avvisi_posa": r["avvisi"], "voci_legenda": g["voci_legenda"],
            "senza_descrizione": g["senza_descrizione"], "computo": xlsx.name,
            "simboli_a_computo": c["totale_simboli"], "anteprima": png.name})
    return rapporto


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    print(json.dumps(esegui(sys.argv[1]), ensure_ascii=False, indent=2))
