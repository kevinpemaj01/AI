"""
Studio Pemaj - Template AutoCAD (disegno 1:1 con annotazioni) costruito sul CARTIGLIO BASE dello studio.

Uso:   python genera_template.py ["riferimenti/CARTIGLIO BASE.dxf"] [out/PEMAJ_TEMPLATE_mm.dxf]
Poi in AutoCAD LT: aprire il DXF -> SALVA CON NOME -> Modello di disegno (*.dwt), formato 2018.

Layout (in mm su carta, CTB PEMAJ_PROGETTI):
  A4      intestazione dell'allegato: il frontalino (blocco PEMAJ_CARTIGLIO_BASE) a tutta pagina
  A3      tavola che segue l'intestazione A4: SOLO il cartiglio (blocco PEMAJ_CARTIGLIO = "cartiglio kevin")
          in basso a destra (in A3 mai frontalino e pianta sullo stesso foglio)
  A2..A0  allegato a se': lo stesso frontalino dell'A4 in alto a sinistra, pianta a destra (come la E01)
  LIBERO  come A2..A0, misure del foglio da cambiare con il comando PEMAJ_FOGLIO (PEMAJ_FOGLIO.lsp)
  Tutte: linea di taglio sul bordo foglio, squadratura a 3,46 mm, finestra 1:100.

- Frontalino: il blocco "cartiglio kevin" viene esploso dentro, tutti i campi sono attributi
  (COMMITTENTE_n, OGGETTO_n, FASE, TAVOLA, TITOLO_TAVOLA + i campi del cartiglio).
- Linee guida per centrare i testi: layer GUIDE, non stampabile, disegnate per prime (dietro a tutto).
- Retino grigio del logo (effetto ombra): disegnato subito dopo le guide, dietro a tutto il resto.
- Tabelle di base: layer dello studio, tipi di linea (INGOMBRO, BORDER, TRATTEGGIO, PE_TRATTO),
  stili di testo PEMAJ_1.8/2.5/3.5/5, stile di quota PEMAJ, multilinea PE_GIALLO_VERDE (cavo di terra).
"""
import sys
import json
from pathlib import Path
import ezdxf
from ezdxf.math import Matrix44
from ezdxf.enums import TextEntityAlignment

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comune import LAYERS, CARTIGLIO, TEMPLATE  # noqa: E402

CTB = "PEMAJ_PROGETTI.ctb"
NOME_BLOCCO = "PEMAJ_CARTIGLIO_BASE"      # frontalino A4 (intestazione)
NOME_CARTIGLIO = "PEMAJ_CARTIGLIO"        # solo cartiglio, per le tavole
LAYER_GUIDE = "GUIDE"

# tipi di linea: lunghezze in mm su carta (PSLTSCALE=1, LTSCALE=1: la finestra li scala da sola)
LINETYPES = {
    "INGOMBRO": ("Ingombro - - - - -", [2.0, 1.0, -1.0]),
    "BORDER": ("Tubazione __ __ . __ __ .", [22.0, 8.0, -2.0, 8.0, -2.0, 0.0, -2.0]),
    "TRATTEGGIO": ("Tratteggio __ __ __", [4.5, 3.0, -1.5]),
    "PE_TRATTO": ("Cavo di terra: tratto verde 3 mm, vuoto 3 mm", [6.0, 3.0, -3.0]),
}
TEXTSTYLES = [("PEMAJ_1.8", 1.8), ("PEMAJ_2.5", 2.5), ("PEMAJ_3.5", 3.5), ("PEMAJ_5", 5.0)]
# cavo di terra giallo-verde con un solo oggetto: multilinea con giallo continuo e verde tratteggiato sopra
MLINE_PE = ("PE_GIALLO_VERDE", "Cavo di terra giallo-verde", [(0.0, 50, "Continuous"), (0.0, 94, "PE_TRATTO")])

# righe aggiunte, in mm rispetto allo spigolo in alto a sinistra del frontalino (posizioni della tavola E01).
# x = None -> centrate sulla linea guida verticale del frontalino (o a meta' larghezza se manca)
RIGHE_TAVOLA = [
    ("TAVOLA", "Numero tavola (es. ALLEGATO E01)", (None, -166.57), 6.0, "ALLEGATO E00", "MIDDLE_CENTER"),
    ("TITOLO_TAVOLA", "Titolo tavola", (None, -179.07), 4.0, "TITOLO DELLA TAVOLA", "MIDDLE_CENTER"),
]
# linee guida del frontalino (servono a centrare TAVOLA e TITOLO_TAVOLA): verticale a meta' frontalino
# e orizzontali sotto le due righe. Sono guide anche le linee che nel CARTIGLIO BASE stanno su un layer
# il cui nome contiene "GUID".
GUIDE_Y = (-174.35, -183.83)
TOLL = 0.5

INTESTAZIONE = ("A4", (210, 297))
FORMATI = {"A3": (420, 297), "A2": (594, 420), "A1": (841, 594), "A0": (1189, 841)}
SOLO_CARTIGLIO = {"A3"}                   # gli altri formati portano il frontalino (allegato a se')
LIBERO = ("LIBERO", (1189, 841))          # misure iniziali; si cambiano con PEMAJ_FOGLIO
MARGINE = 3.46     # squadratura interna, come nella tavola E01 (34,6 unita' a base 10)
LAYOUT_APERTO = "A4"


def trova_estensione(msp):
    pl = next(e for e in msp.query("LWPOLYLINE") if e.dxf.layer == "cartiglio")
    xs = [p[0] for p in pl.get_points()]
    ys = [p[1] for p in pl.get_points()]
    return min(xs), max(ys), max(xs) - min(xs), max(ys) - min(ys)


def _attdef_da_testo(blk, e, tag, prompt, m):
    att = blk.add_attdef(tag, (0, 0), text=e.dxf.text,
                         dxfattribs={k: e.dxf.get(k) for k in
                                     ("layer", "height", "style", "width", "rotation",
                                      "halign", "valign", "color") if e.dxf.hasattr(k)})
    att.dxf.insert = e.dxf.insert
    if e.dxf.hasattr("align_point"):
        att.dxf.align_point = e.dxf.align_point
    att.dxf.prompt = prompt
    att.transform(m)


def classifica_testi(msp):
    """Riconosce i testi variabili del frontalino: committente, oggetto, fase."""
    testi = list(msp.query("TEXT"))
    y_ogg = next((t.dxf.insert.y for t in testi if t.dxf.text.strip().lower().startswith("oggetto")), None)
    if y_ogg is None:
        raise ValueError("CARTIGLIO_NON_RICONOSCIUTO: manca il testo 'Oggetto:'")
    var = sorted((t for t in testi if t.dxf.layer.lower() == "testo variabile"),
                 key=lambda t: -t.dxf.insert.y)
    tags = {}
    nc = no = 0
    for t in var:
        if t.dxf.insert.y > y_ogg + 1:
            nc += 1
            tags[t.dxf.handle] = (f"COMMITTENTE_{nc}", f"Committente - riga {nc}")
        else:
            no += 1
            tags[t.dxf.handle] = (f"OGGETTO_{no}", f"Oggetto - riga {no}")
    fase = [t for t in testi if t.dxf.layer.lower() == "testo fisso" and t.dxf.height >= 7]
    for t in fase[:1]:
        tags[t.dxf.handle] = ("FASE", "Fase (PROGETTO ESECUTIVO, AS-BUILT, DI.RI...)")
    return tags


def ordine_di_disegno(doc, nome_blocco):
    """Entita' del blocco nell'ordine in cui AutoCAD le disegna (tabella SORTENTS del blocco, se c'e')."""
    blk = doc.blocks.get(nome_blocco)
    chiavi = {}
    br = doc.block_records.get(nome_blocco)
    if br is not None and br.has_extension_dict:
        xd = br.get_extension_dict()
        if "ACAD_SORTENTS" in xd:
            chiavi = dict(xd["ACAD_SORTENTS"].table.items())
    ents = list(blk)
    return sorted(ents, key=lambda e: (int(chiavi.get(e.dxf.handle, e.dxf.handle), 16), ents.index(e)))


def e_sfondo_grigio(e, doc):
    """Retino grigio dell'effetto ombra del logo: va disegnato sotto a tutto."""
    if e.dxftype() != "HATCH":
        return False
    tc = e.dxf.get("true_color")
    if tc is not None:
        r, g, b = (tc >> 16) & 255, (tc >> 8) & 255, tc & 255
        return r == g == b and 40 < r < 250
    c = e.dxf.get("color", 256)
    if c == 256 and e.dxf.layer in doc.layers:
        c = doc.layers.get(e.dxf.layer).dxf.color
    return c in (8, 9, 250, 251, 252, 253, 254)


def e_guida(e, w):
    """Linea guida del frontalino (coordinate gia' riferite allo spigolo in alto a sinistra)."""
    if "GUID" in e.dxf.layer.upper():
        return True
    if e.dxftype() != "LINE":
        return False
    s, f = e.dxf.start, e.dxf.end
    if abs(s.x - f.x) < 0.01 and abs(s.x - w / 2) < TOLL:            # verticale a meta' frontalino
        return True
    if abs(s.y - f.y) < 0.01 and any(abs(s.y - y) < TOLL for y in GUIDE_Y):
        return True
    return False


def _copia_pulita(x):
    v = x.copy()
    if v.dxftype() == "HATCH":            # niente riferimenti a contorni del file originale
        v.dxf.associative = 0
        for pth in v.paths:
            if hasattr(pth, "source_boundary_objects"):
                pth.source_boundary_objects = []
    return v


def costruisci_blocco(doc):
    """Frontalino A4 -> blocco PEMAJ_CARTIGLIO_BASE (punto base = spigolo in alto a sinistra)."""
    msp = doc.modelspace()
    x0, y0, w, h = trova_estensione(msp)
    m = Matrix44.translate(-x0, -y0, 0)
    tags = classifica_testi(msp)
    blk = doc.blocks.new(NOME_BLOCCO, base_point=(0, 0))
    guide, sfondo, resto = [], [], []     # ordine di disegno: guide, retini grigi del logo, tutto il resto
    for e in list(msp):
        if e.dxftype() == "INSERT":           # blocco "cartiglio kevin": esploso dentro il frontalino
            mi = e.matrix44()
            for x in ordine_di_disegno(doc, e.dxf.name):
                if x.dxftype() in ("ATTDEF", "ATTRIB"):
                    continue
                v = _copia_pulita(x)
                v.transform(mi)
                v.transform(m)
                (sfondo if e_sfondo_grigio(v, doc) else resto).append(v)
            valori = {a.dxf.tag: a.dxf.text for a in e.attribs}
            sb = doc.blocks.get(e.dxf.name)
            for ad in sb.query("ATTDEF"):
                c = ad.copy()
                c.transform(mi)
                c.transform(m)
                c.dxf.text = valori.get(ad.dxf.tag, ad.dxf.text)
                resto.append(c)
            continue
        if e.dxftype() == "TEXT" and e.dxf.handle in tags:
            resto.append(("ATTDEF", e))
            continue
        c = e.copy()
        c.transform(m)
        if e_guida(c, w):
            c.dxf.layer = LAYER_GUIDE
            c.dxf.color = 256
            guide.append(c)
        else:
            (sfondo if e_sfondo_grigio(c, doc) else resto).append(c)
    for v in guide + sfondo + resto:
        if isinstance(v, tuple):
            _attdef_da_testo(blk, v[1], *tags[v[1].dxf.handle], m)
        else:
            blk.add_entity(v)
    verticali = [g.dxf.start.x for g in guide if g.dxftype() == "LINE"
                 and abs(g.dxf.start.x - g.dxf.end.x) < 0.01]
    xc = verticali[0] if verticali else w / 2
    for tag, prompt, (px, py), hh, testo, allin in RIGHE_TAVOLA:
        a = blk.add_attdef(tag, (0, 0), text=testo,
                           dxfattribs={"layer": "Testo Variabile", "height": hh, "style": "Standard"})
        a.set_placement((xc if px is None else px, py), align=getattr(TextEntityAlignment, allin))
        a.dxf.prompt = prompt
    return w, h, xc


def costruisci_cartiglio(doc, nome_src, valori):
    """Solo cartiglio ("cartiglio kevin") -> blocco PEMAJ_CARTIGLIO con punto base nello spigolo
    in basso a destra: si inserisce nello spigolo della squadratura e segue il foglio quando si stira."""
    src = doc.blocks.get(nome_src)
    pl = [p for e in src.query("LWPOLYLINE") if e.dxf.layer.lower() == "cartiglio" for p in e.get_points()]
    xmax, ymin = max(p[0] for p in pl), min(p[1] for p in pl)
    xmin, ymax = min(p[0] for p in pl), max(p[1] for p in pl)
    m = Matrix44.translate(-xmax, -ymin, 0)
    blk = doc.blocks.new(NOME_CARTIGLIO, base_point=(0, 0))
    sfondo, resto = [], []
    for x in ordine_di_disegno(doc, nome_src):
        if x.dxftype() == "ATTRIB":
            continue
        v = _copia_pulita(x)
        v.transform(m)
        if v.dxftype() == "ATTDEF":
            v.dxf.text = valori.get(v.dxf.tag, v.dxf.text)
        (sfondo if e_sfondo_grigio(v, doc) else resto).append(v)
    for v in sfondo + resto:
        blk.add_entity(v)
    return xmax - xmin, ymax - ymin


def prepara_tabelle(doc):
    h = doc.header
    h["$INSUNITS"] = 4
    h["$LTSCALE"] = 1.0
    h["$PSLTSCALE"] = 1
    h["$MEASUREMENT"] = 1
    for name, (descr, pattern) in LINETYPES.items():
        if name not in doc.linetypes:
            doc.linetypes.add(name, pattern=pattern, description=descr)
    for name, col, lt in LAYERS:
        if name not in doc.layers:
            doc.layers.add(name, color=col, linetype=lt)
    for name, col in (("VP", 9), (LAYER_GUIDE, 9)):    # di servizio: visibili a video, mai stampati
        lay = doc.layers.get(name) if name in doc.layers else doc.layers.add(name, color=col)
        lay.dxf.plot = 0
    for name, hgt in TEXTSTYLES:
        if name not in doc.styles:
            st = doc.styles.add(name, font="romans.shx")
            st.dxf.height = hgt
            st.dxf.width = 0.9
    nome, descr, elementi = MLINE_PE
    if nome not in doc.mline_styles:
        ms = doc.mline_styles.new(nome)
        ms.dxf.description = descr
        for off, col, lt in elementi:      # il verde tratteggiato e' l'ultimo: sta sopra al giallo
            ms.elements.append(off, col, lt)
    if "PEMAJ" not in doc.dimstyles:
        # misure in mm su carta (CEI EN 61082-1 / ISO 129: testo 2,5 mm); "Annotativo" si spunta in LT
        doc.dimstyles.new("PEMAJ", dxfattribs={
            "dimtxt": 2.5, "dimasz": 2.5, "dimexe": 1.25, "dimexo": 0.625, "dimgap": 0.625,
            "dimtxsty": "PEMAJ_2.5", "dimtad": 1, "dimtih": 0, "dimtoh": 0, "dimdec": 0,
            "dimdsep": ord(","), "dimlunit": 2, "dimscale": 1.0, "dimclrd": 256, "dimclre": 256,
            "dimclrt": 256})


def _nuovo_layout(doc, nome, W, H):
    lay = doc.layouts.new(nome)
    lay.page_setup(size=(W, H), margins=(0, 0, 0, 0), units="mm")
    lay.dxf.current_style_sheet = CTB
    return lay


def crea_intestazione(doc, nome, carta):
    """A4 verticale: il frontalino a tutta pagina, spigolo sul bordo del foglio."""
    W, H = carta
    lay = _nuovo_layout(doc, nome, W, H)
    ref = lay.add_blockref(NOME_BLOCCO, (0, H), dxfattribs={"layer": "cartiglio"})
    ref.add_auto_attribs({})


def crea_tavola(doc, nome, carta, wc=210.0):
    """Tavola: linea di taglio sul bordo, squadratura, finestra 1:100.
    A3: solo il cartiglio in basso a destra. Altri formati: frontalino in alto a sinistra, finestra a destra."""
    W, H = carta
    lay = _nuovo_layout(doc, nome, W, H)
    m = MARGINE
    lay.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True, dxfattribs={"layer": "cartiglio"})
    lay.add_lwpolyline([(m, m), (W - m, m), (W - m, H - m), (m, H - m)], close=True,
                       dxfattribs={"layer": "Squadratura"})
    solo = nome in SOLO_CARTIGLIO
    x1 = m + 5 if solo else wc + 5
    x2, y1, y2 = W - m - 5, m + 5, H - m - 5
    lay.add_viewport(center=((x1 + x2) / 2, (y1 + y2) / 2), size=(x2 - x1, y2 - y1),
                     view_center_point=(0, 0), view_height=(y2 - y1) * 100,
                     dxfattribs={"layer": "VP"})
    if solo:
        ref = lay.add_blockref(NOME_CARTIGLIO, (W - m, m), dxfattribs={"layer": "cartiglio"})
    else:   # stesso frontalino dell'A4, spigolo sul bordo del foglio come nelle tavole dello studio
        ref = lay.add_blockref(NOME_BLOCCO, (0, H), dxfattribs={"layer": "cartiglio"})
    ref.add_auto_attribs({})


def genera(src=CARTIGLIO, out=TEMPLATE):
    doc = ezdxf.readfile(str(src))
    msp = doc.modelspace()
    ins = next(e for e in msp.query("INSERT"))
    nome_ck, valori = ins.dxf.name, {a.dxf.tag: a.dxf.text for a in ins.attribs}
    wc, hc, xc = costruisci_blocco(doc)
    cart = costruisci_cartiglio(doc, nome_ck, valori)
    for e in list(msp):
        msp.delete_entity(e)
    prepara_tabelle(doc)
    vecchi = [l.name for l in doc.layouts if l.name != "Model"]
    crea_intestazione(doc, *INTESTAZIONE)
    for nome, carta in list(FORMATI.items()) + [LIBERO]:
        crea_tavola(doc, nome, carta, wc)
    for n in vecchi:
        doc.layouts.delete(n)
    # il file si apre sull'intestazione A4 (lo spazio modello e' vuoto per costruzione)
    doc.layouts.set_active_layout(LAYOUT_APERTO)
    doc.header["$TILEMODE"] = 0
    doc.header["$STYLESHEET"] = CTB
    doc.audit()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(out))
    return {"file": str(out), "frontalino_mm": [round(wc, 1), round(hc, 1)], "centro_testi_x": round(xc, 2),
            "cartiglio_mm": [round(cart[0], 1), round(cart[1], 1)],
            "layout": [INTESTAZIONE[0]] + list(FORMATI) + [LIBERO[0]]}


ATTRIBUTI_ATTESI = {"COMMITTENTE_1", "OGGETTO_1", "FASE", "TAVOLA", "TITOLO_TAVOLA",
                    "SCALA", "N°DISEGNO", "DATA1", "PROGETTO1", "PROGETTO4"}
ATTRIBUTI_CARTIGLIO = {"SCALA", "N°DISEGNO", "DATA1", "PROGETTO1", "PROGETTO4"}


def controlla(path=TEMPLATE):
    """Controlli di integrita' del template, inclusi i difetti che hanno fatto bloccare AutoCAD LT."""
    problemi = []
    try:
        doc = ezdxf.readfile(str(path))
    except Exception as ex:
        return [f"ILLEGGIBILE: {ex}"]
    a = doc.audit()
    if a.errors:
        problemi.append(f"AUDIT: {len(a.errors)} errori")
    for nome, attesi in ((NOME_BLOCCO, ATTRIBUTI_ATTESI), (NOME_CARTIGLIO, ATTRIBUTI_CARTIGLIO)):
        if nome not in doc.blocks:
            problemi.append(f"BLOCCO_MANCANTE: {nome}")
            continue
        tags = {x.dxf.tag for x in doc.blocks.get(nome).query("ATTDEF")}
        if attesi - tags:
            problemi.append(f"ATTRIBUTI_MANCANTI {nome}: {sorted(attesi - tags)}")
    if problemi:
        return problemi
    attesi_layout = {INTESTAZIONE[0]: NOME_BLOCCO}
    attesi_layout.update({n: (NOME_CARTIGLIO if n in SOLO_CARTIGLIO else NOME_BLOCCO)
                          for n in list(FORMATI) + [LIBERO[0]]})
    for nome, blocco in attesi_layout.items():
        if nome not in doc.layouts:
            problemi.append(f"LAYOUT_MANCANTE: {nome}")
            continue
        lay = doc.layouts.get(nome)
        if lay.dxf.current_style_sheet != CTB:
            problemi.append(f"CTB_ERRATO: {nome}")
        if not any(i.dxf.name == blocco for i in lay.query("INSERT")):
            problemi.append(f"CARTIGLIO_MANCANTE: {nome}")
    if LAYER_GUIDE not in doc.layers or doc.layers.get(LAYER_GUIDE).dxf.plot != 0:
        problemi.append("LAYER_GUIDE_STAMPABILE")
    for nome in ("PE_TRATTO",):
        if nome not in doc.linetypes:
            problemi.append(f"TIPO_LINEA_MANCANTE: {nome}")
    if MLINE_PE[0] not in doc.mline_styles:
        problemi.append(f"MULTILINEA_MANCANTE: {MLINE_PE[0]}")
    # difetti noti che mandano in crash LT (0xc0000005): retini associativi con contorni inesistenti
    for b in doc.blocks:
        for e in b:
            if e.dxftype() == "HATCH" and e.dxf.associative:
                for p in e.paths:
                    for h in getattr(p, "source_boundary_objects", []) or []:
                        if h not in doc.entitydb:
                            problemi.append(f"HATCH_RIFERIMENTO_ROTTO: blocco {b.name}")
    return problemi


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else CARTIGLIO
    out = sys.argv[2] if len(sys.argv) > 2 else TEMPLATE
    r = genera(src, out)
    r["problemi"] = controlla(out)
    print(json.dumps(r, indent=2, ensure_ascii=False))
