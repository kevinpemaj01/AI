"""
Studio Pemaj - Autodiagnosi e autoriparazione dello standard grafico.

Uso:
  python dottore.py              controlla tutto e dice cosa non va (non modifica niente)
  python dottore.py --ripara     controlla e ripara da solo cio' che si puo' riparare in sicurezza
  python dottore.py --apri       dopo il controllo apre il template in AutoCAD LT (dxf_writer.open_in_lt)
  python dottore.py --congela    SOLO in Building Mode, dopo un LOCK superato: salva impronte e copie
                                 di sicurezza (manifest.json + _backup/) usate per le riparazioni future

Cosa controlla (in ordine):
  D1 dipendenze Python (ezdxf, openpyxl)            -> con --ripara: pip install
  D2 integrita' degli script (impronte SHA-256)      -> con --ripara: ripristino da _backup/
  D3 file di riferimento (master Excel, cartiglio)   -> con --ripara: recupero da planimetria-impianto
                                                       o da _backup/ (il file danneggiato viene conservato)
  D4 output aggiornati rispetto ai riferimenti        -> con --ripara: rigenera CTB e template
  D5 output corretti (CTB = master colore per colore, template integro)
Stampa un JSON: status ok | riparato | errore, azioni eseguite, problemi residui con "fix".
"""
import argparse
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comune import (BASE, RIF, OUT, BACKUP, MANIFEST, STATO, MASTER, CARTIGLIO,  # noqa: E402
                    CARTIGLIO_ALTERNATIVI, TEMPLATE, STILI, SCRIPT, sha256, leggi_json,
                    scrivi_json, esci, importa_dxf_writer)

azioni, problemi = [], []


def problema(code, msg, fix):
    problemi.append({"code": code, "message": msg, "fix": fix})


# ---------------------------------------------------------------- D1 dipendenze
def d1_dipendenze(ripara):
    for mod in ("ezdxf", "openpyxl"):
        try:
            importlib.import_module(mod)
        except ImportError:
            if ripara:
                r = subprocess.run([sys.executable, "-m", "pip", "install", mod],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                try:
                    importlib.invalidate_caches()
                    importlib.import_module(mod)
                    azioni.append(f"installato {mod}")
                    continue
                except ImportError:
                    pass
            problema(f"NO_{mod.upper()}", f"Libreria {mod} mancante",
                     f"python -m pip install {mod}")
    return not any(p["code"].startswith("NO_") for p in problemi)


# ---------------------------------------------------------------- D2 integrita' script
def d2_script(ripara):
    man = leggi_json(MANIFEST)
    if not man:
        problema("MANIFEST_MANCANTE", "Impronte degli script assenti: autoriparazione degli script non disponibile",
                 "Building Mode: superare il LOCK e poi 'python dottore.py --congela'")
        return
    for nome, atteso in man.get("script", {}).items():
        f = BASE / nome
        if f.exists() and sha256(f) == atteso:
            continue
        copia = BACKUP / nome
        if ripara and copia.exists() and sha256(copia) == atteso:
            if f.exists():
                shutil.copy2(f, f.with_suffix(f.suffix + ".modificato"))
            f.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(copia, f)
            azioni.append(f"ripristinato {nome} dalla copia di sicurezza")
            continue
        stato = "mancante" if not f.exists() else "modificato rispetto al LOCK"
        problema("SCRIPT_MODIFICATO", f"{nome} {stato}",
                 "python dottore.py --ripara (ripristina la versione LOCK); se la modifica e' voluta: "
                 "Building Mode, LOCK, poi --congela")


# ---------------------------------------------------------------- D3 riferimenti
def _master_valido(path):
    try:
        import genera_ctb
        stili, righe = genera_ctb.leggi_master(path)
        return len(righe) == 255 and all(s in stili for s in STILI)
    except BaseException:
        return False


def _cartiglio_valido(path):
    try:
        import ezdxf
        import genera_template
        doc = ezdxf.readfile(str(path))
        genera_template.trova_estensione(doc.modelspace())
        genera_template.classifica_testi(doc.modelspace())
        return True
    except BaseException:
        return False


def d3_riferimenti(ripara):
    RIF.mkdir(parents=True, exist_ok=True)
    # master Excel degli stili di stampa
    if not (MASTER.exists() and _master_valido(MASTER)):
        copia = BACKUP / "riferimenti" / MASTER.name
        if ripara and copia.exists() and _master_valido(copia):
            if MASTER.exists():
                shutil.copy2(MASTER, MASTER.with_suffix(".danneggiato.xlsx"))
            shutil.copy2(copia, MASTER)
            azioni.append("master stili ripristinato dalla copia di sicurezza (le modifiche "
                          "successive al LOCK vanno reinserite; il file danneggiato e' conservato)")
        else:
            problema("MASTER_NON_VALIDO", f"{MASTER.name} mancante o danneggiato",
                     "Ripristinare il file in riferimenti/ oppure 'python dottore.py --ripara'")
    # cartiglio base
    if not (CARTIGLIO.exists() and _cartiglio_valido(CARTIGLIO)):
        candidati = [p for p in CARTIGLIO_ALTERNATIVI if p.exists()] + [BACKUP / "riferimenti" / CARTIGLIO.name]
        fonte = next((p for p in candidati if p.exists() and _cartiglio_valido(p)), None)
        if ripara and fonte:
            if CARTIGLIO.exists():
                shutil.copy2(CARTIGLIO, CARTIGLIO.with_suffix(".danneggiato.dxf"))
            shutil.copy2(fonte, CARTIGLIO)
            azioni.append(f"cartiglio recuperato da {fonte.relative_to(BASE.parent)}")
        else:
            problema("CARTIGLIO_NON_VALIDO", "CARTIGLIO BASE.dxf mancante o non riconoscibile "
                     "(serve la cornice sul layer 'cartiglio' e il testo 'Oggetto:')",
                     "In LT aprire CARTIGLIO BASE.dwg -> SALVACOME AutoCAD 2018 DXF in "
                     "tools/standard-pemaj/riferimenti/")


# ---------------------------------------------------------------- D4/D5 output
def _impronte_sorgenti():
    imp = {}
    for nome, f in (("master", MASTER), ("cartiglio", CARTIGLIO),
                    ("genera_ctb", BASE / "genera_ctb.py"), ("genera_template", BASE / "genera_template.py")):
        imp[nome] = sha256(f) if f.exists() else None
    return imp


def _impronte_output():
    """Impronte dei file prodotti: se un output non e' quello generato dall'ultima rigenerazione
    (sostituito a mano, non sovrascritto perche' aperto in LT...), viene considerato vecchio."""
    imp = {}
    for f in [OUT / f"PEMAJ_{s}.ctb" for s in STILI] + [TEMPLATE]:
        imp[f.name] = sha256(f) if f.exists() else None
    return imp


def d4_d5_output(ripara):
    if any(p["code"] in ("MASTER_NON_VALIDO", "CARTIGLIO_NON_VALIDO") for p in problemi):
        return
    import genera_ctb
    import genera_template
    importlib.reload(genera_ctb)
    importlib.reload(genera_template)
    stato = leggi_json(STATO, {}) or {}
    imp = _impronte_sorgenti()
    old = stato.get("sorgenti", {})

    out_old = stato.get("output", {})
    out_imp = _impronte_output()
    ctb_vecchi = (any(not (OUT / f"PEMAJ_{s}.ctb").exists() for s in STILI)
                  or old.get("master") != imp["master"] or old.get("genera_ctb") != imp["genera_ctb"]
                  or any(out_old.get(f"PEMAJ_{s}.ctb") != out_imp[f"PEMAJ_{s}.ctb"] for s in STILI))
    tpl_vecchio = (not TEMPLATE.exists() or old.get("cartiglio") != imp["cartiglio"]
                   or old.get("genera_template") != imp["genera_template"]
                   or out_old.get(TEMPLATE.name) != out_imp[TEMPLATE.name])

    def ctb_errati():
        return {k: v for k, v in genera_ctb.confronta(MASTER, OUT).items() if v}

    def tpl_errato():
        return genera_template.controlla(TEMPLATE) if TEMPLATE.exists() else ["TEMPLATE_MANCANTE"]

    err_ctb = {} if ctb_vecchi else ctb_errati()
    err_tpl = [] if tpl_vecchio else tpl_errato()

    def bloccato(ex):
        problema("FILE_APERTO", f"Impossibile scrivere {ex.filename}: e' aperto in un altro programma",
                 "Chiudere il file in AutoCAD LT e ripetere 'python tools/standard-pemaj/dottore.py --ripara'")

    if ctb_vecchi or err_ctb:
        if ripara:
            try:
                genera_ctb.genera(MASTER, OUT)
            except PermissionError as ex:
                bloccato(ex)
                return
            azioni.append("rigenerati PEMAJ_PROGETTI/DIRI/SCHEMI.ctb dal master")
            err_ctb = ctb_errati()
        if err_ctb or not ripara:
            problema("CTB_NON_ALLINEATI", f"Stili di stampa assenti, vecchi o diversi dal master: "
                     f"{err_ctb or 'da rigenerare'}", "python dottore.py --ripara")
    if tpl_vecchio or err_tpl:
        if ripara:
            try:
                genera_template.genera(CARTIGLIO, TEMPLATE)
            except PermissionError as ex:
                bloccato(ex)
                return
            azioni.append("rigenerato PEMAJ_TEMPLATE_mm.dxf dal cartiglio base")
            err_tpl = tpl_errato()
        if err_tpl or not ripara:
            problema("TEMPLATE_NON_VALIDO", f"Template assente, vecchio o difettoso: {err_tpl or 'da rigenerare'}",
                     "python dottore.py --ripara; se persiste: Building Mode")
    if ripara and not any(p["code"] in ("CTB_NON_ALLINEATI", "TEMPLATE_NON_VALIDO") for p in problemi):
        scrivi_json(STATO, {"sorgenti": _impronte_sorgenti(), "output": _impronte_output()})


# ---------------------------------------------------------------- congela
def congela():
    r = subprocess.run([sys.executable, str(BASE / "tests" / "run_lock.py")], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        esci({"status": "errore", "code": "LOCK_NON_SUPERATO",
              "fix": "Correggere in Building Mode finche' run_lock.py passa, poi ripetere --congela",
              "output_lock": r.stdout[-2000:]}, False)
    man = {"script": {}}
    for nome in SCRIPT:
        f = BASE / nome
        man["script"][nome] = sha256(f)
        dst = BACKUP / nome
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
    for f in (MASTER, CARTIGLIO):
        dst = BACKUP / "riferimenti" / f.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
    scrivi_json(MANIFEST, man)
    esci({"status": "ok", "congelati": list(man["script"]), "lock": r.stdout.strip().splitlines()[-1:]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ripara", action="store_true")
    ap.add_argument("--apri", action="store_true")
    ap.add_argument("--congela", action="store_true")
    a = ap.parse_args()
    if a.congela:
        congela()
    if d1_dipendenze(a.ripara):
        d2_script(a.ripara)
        d3_riferimenti(a.ripara)
        d4_d5_output(a.ripara)
    out = {"status": "ok" if not problemi else "errore", "azioni": azioni, "problemi": problemi,
           "output": {"ctb": [str(OUT / f"PEMAJ_{s}.ctb") for s in STILI], "template": str(TEMPLATE)}}
    if azioni and not problemi:
        out["status"] = "riparato"
    if a.apri and not problemi:
        dw = importa_dxf_writer()
        out["apertura"] = dw.open_in_lt(str(TEMPLATE)) if dw else "dxf_writer non trovato: aprire a mano"
    esci(out, not problemi)


if __name__ == "__main__":
    main()
