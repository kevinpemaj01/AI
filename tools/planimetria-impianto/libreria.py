"""
Libreria simboli per la posa automatica.

Crea riferimenti/libreria_simboli.dxf (+ .json) con un blocco statico con
nome per ogni simbolo usato nelle tavole/legende di riferimento:

  - per i blocchi dinamici (*Uxx) si copia la variante effettivamente usata
    nelle tavole, rinominata col nome del blocco originale (es. "16A")
  - il punto base di ogni blocco viene portato al centro del simbolo
  - per ogni simbolo si registra la scala d'inserimento tipica (la più
    frequente nelle tavole dell'utente) e il layer d'impianto più usato

Sorgenti in ordine di priorità (la prima che contiene il simbolo vince):
tavole E02, E01, poi LEGENDA100.

Uso:
    python libreria.py
"""

import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

import ezdxf
from ezdxf import bbox, xref

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))
logging.getLogger("ezdxf").setLevel(logging.ERROR)

import simboli as sm  # noqa: E402

SORGENTI = [
    QUI / "riferimenti" / "ALLEGATO E02 FM E SERVIZI.dxf",
    QUI / "riferimenti" / "ALLEGATO E01 ILL.ORDINARIA E DI SICUREZZA.dxf",
    QUI / "riferimenti" / "LEGENDA100.dxf",
]
LIBRERIA_DXF = QUI / "riferimenti" / "libreria_simboli.dxf"
LIBRERIA_JSON = QUI / "riferimenti" / "libreria_simboli.json"
LAYER_NON_IMPIANTO = {"0", "Defpoints"}


def costruisci(sorgenti=SORGENTI, out_dxf=LIBRERIA_DXF, out_json=LIBRERIA_JSON):
    lib = ezdxf.new("R2018")
    info = {}
    for src in sorgenti:
        doc = ezdxf.readfile(src)
        usi = defaultdict(list)                        # nome -> [insert]
        for ins in doc.modelspace().query("INSERT"):
            blk = doc.blocks.get(ins.dxf.name)
            if blk is None or blk.block.dxf.flags & 4:  # xref
                continue
            nome = sm.nome_simbolo(doc, ins)
            if nome.startswith(sm.IGNORA_PREFISSI) or nome in info:
                continue
            usi[nome].append(ins)
        for nome, lista in usi.items():
            scale = Counter(round(abs(i.dxf.xscale), 3) for i in lista)
            scala = scale.most_common(1)[0][0]
            ref = next(i for i in lista if round(abs(i.dxf.xscale), 3) == scala)
            sblk = doc.blocks.get(ref.dxf.name)
            try:
                e = bbox.extents(sblk)
                if not e.has_data or e.size.x == 0:
                    continue                           # variante vuota
                dim = [round(e.size.x * scala, 1), round(e.size.y * scala, 1)]
            except Exception:
                continue
            layers = Counter(i.dxf.layer for i in lista if i.dxf.layer not in LAYER_NON_IMPIANTO)
            # punto base = centro del simbolo: il punto di posa coincide con il centro
            # (alcuni blocchi, es. "emer", hanno la geometria lontanissima dal punto base)
            tblk = lib.blocks.new(nome, base_point=(e.center.x, e.center.y, 0))
            loader = xref.Loader(doc, lib)
            loader.load_block_layout_into(sblk, tblk)
            loader.execute()
            info[nome] = {"scala": scala, "layer": layers.most_common(1)[0][0] if layers else None,
                          "ingombro_cm": dim, "fonte": src.name, "usi": len(lista)}
    lib.saveas(out_dxf)
    out_json.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return info


if __name__ == "__main__":
    info = costruisci()
    print(f"Simboli in libreria: {len(info)}  -> {LIBRERIA_DXF.name}")
    for n, v in sorted(info.items()):
        print(f"  {n[:34]:34} scala={v['scala']:<8} layer={str(v['layer']):18} {v['ingombro_cm']} ({v['fonte'][:12]})")
