"""Studio Pemaj - standard grafico: percorsi, costanti e utilita' comuni a tutti gli script."""
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
RIF = BASE / "riferimenti"
OUT = BASE / "out"
BACKUP = BASE / "_backup"
MANIFEST = BASE / "manifest.json"
STATO = OUT / "stato.json"

MASTER = RIF / "PEMAJ_stili_master.xlsx"
CARTIGLIO = RIF / "CARTIGLIO BASE.dxf"
# dove cercare il cartiglio se manca in riferimenti/ (skill planimetria-impianto)
CARTIGLIO_ALTERNATIVI = [
    BASE.parent / "planimetria-impianto" / "riferimenti" / "CARTIGLIO BASE.dxf",
    BASE.parent / "planimetria-impianto" / "riferimenti" / "CARTIGLIO_BASE.dxf",
]
TEMPLATE = OUT / "PEMAJ_TEMPLATE_mm.dxf"
STILI = ("PROGETTI", "DIRI", "SCHEMI")

SCRIPT = ["comune.py", "genera_ctb.py", "genera_template.py", "verifica_tavola.py",
          "dottore.py", "tests/run_lock.py", "PEMAJ_FOGLIO.lsp", "prepara_base.py"]

# Layer standard dello studio (nome, colore ACI, tipo linea). Fonte: LEGENDA100, Tabcolo, tavola E01.
LAYERS = [
    ("FM", 240, "Continuous"), ("LC", 3, "Continuous"), ("EM", 4, "Continuous"),
    ("EMERGENZA", 4, "Continuous"), ("SER", 204, "Continuous"), ("SERVIZI", 204, "Continuous"),
    ("RI", 232, "Continuous"), ("IMP. ANTINCENDIO", 4, "Continuous"), ("EVAC", 6, "Continuous"),
    ("R", 2, "Continuous"), ("QUADRI", 5, "Continuous"), ("CAN", 30, "Continuous"),
    ("CANALINA", 6, "Continuous"), ("RIEMP", 131, "Continuous"), ("BLINDO", 154, "Continuous"),
    ("TUB", 14, "BORDER"), ("TERRA", 14, "INGOMBRO"), ("TERRA1", 14, "Continuous"),
    ("ELETTR", 4, "Continuous"), ("RETE", 14, "Continuous"), ("VENT", 40, "Continuous"),
    ("MACCHINE", 6, "Continuous"), ("SANIT", 2, "Continuous"), ("MURI", 170, "Continuous"),
    ("INF", 8, "Continuous"), ("INFISSI", 8, "Continuous"), ("ARREDI", 33, "Continuous"),
    ("SCRITTE", 7, "Continuous"), ("SCRITTE1", 90, "Continuous"), ("TESTI", 7, "Continuous"),
    ("SEGNAGR", 4, "Continuous"), ("SEZ", 170, "Continuous"), ("ZONA", 246, "TRATTEGGIO"),
    ("LOCALI", 9, "Continuous"),
    # cavo di terra giallo-verde (due polilinee sovrapposte o multilinea PE_GIALLO_VERDE)
    ("PE_GIALLO", 50, "Continuous"), ("PE_VERDE", 94, "PE_TRATTO"),
]
# layer del cartiglio e di servizio, ammessi in ogni tavola
LAYERS_SERVIZIO = {"0", "DEFPOINTS", "VP", "SQUADRATURA", "CARTIGLIO", "TESTO FISSO",
                   "TESTO VARIABILE", "LAYER 2", "TRATTEGGIO", "GUIDE"}

ALTEZZA_MIN_MM = 1.8          # CEI EN 61082-1, 5.11 / ISO 3098
CTB_AMMESSI = {f"PEMAJ_{s}.ctb".upper() for s in STILI} | {"PEMAJ_IP.CTB"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blocco in iter(lambda: f.read(1 << 16), b""):
            h.update(blocco)
    return h.hexdigest()


def leggi_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def scrivi_json(path, dati):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(dati, indent=2, ensure_ascii=False), encoding="utf-8")


def esci(dati, ok=True):
    """Stampa un unico oggetto JSON (come check_autocad.py) ed esce con 0/1."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # console Windows (cp1252): niente errori su ° e accenti
    except Exception:
        pass
    print(json.dumps(dati, indent=2, ensure_ascii=False))
    sys.exit(0 if ok else 1)


def importa_dxf_writer():
    """Libreria condivisa del workspace (tools/cad-output/dxf_writer.py), se presente."""
    p = BASE.parent / "cad-output"
    if (p / "dxf_writer.py").exists():
        sys.path.insert(0, str(p))
        try:
            import dxf_writer as dw   # noqa: E402
            return dw
        except Exception:
            return None
    return None
