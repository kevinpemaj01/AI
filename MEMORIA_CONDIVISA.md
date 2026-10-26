# Memoria condivisa — Design & Draft (Studio Pemaj)

Questo file è la memoria comune di **tutti gli assistenti** che lavorano in questo workspace
(Claude Code, ChatGPT/Codex, …). È la fonte di verità su decisioni, stato dei lavori e fatti
scoperti sui disegni. Va letto all'inizio di ogni sessione, insieme ad `AGENTS.md`.

**Regola di aggiornamento:** quando si scopre un fatto utile, si prende una decisione con Kevin o
si chiude un lavoro, aggiornare questo file (sezione giusta, con la data), poi fare commit e push
sul repository GitHub (vedi `AGENTS.md` → "Lavoro con GitHub"). Non scrivere qui dati personali
dei clienti oltre a quelli già presenti nei disegni.

---

## 1. Chi è l'utente e come lavora

- Kevin Pemaj, Per. Ind., **Studio Pemaj** (Asti): progettazione di **impianti elettrici**.
- Lavora in **italiano**: rispondere sempre in italiano, in modo semplice e pratico.
- Norma di riferimento: **CEI 64-8**; simboli CEI EN 60617. Altre norme citate dallo studio:
  CEI 0-2:2025, CEI EN 61082-1, CEI EN IEC 81346. Non citare articoli di norma a memoria.
- Relazioni di progetto: verbi al futuro ("verranno installati").
- Spesso delega le scelte ("fai tu"): decidere in modo ragionevole, dichiarare le scelte fatte.
- Mette spesso i file in `Projects/` invece che nella cartella indicata: controllare lì.

## 2. AutoCAD e strumenti

- La postazione ha **AutoCAD LT 2025**: **niente COM/automazione**, nessun collegamento "live".
  Gli script producono file **DXF** (libreria `tools/cad-output/dxf_writer.py`, ezdxf) che Kevin
  apre in LT. Non avviare una seconda istanza di LT. (`.dwg` è associato a SPAC Start 26.)
- Gli script leggono solo **DXF veri**: un DWG rinominato in .dxf non va (inizia con `AC10..`).
  Far fare a Kevin `SALVACOME` → **AutoCAD 2018 DXF**.
- Un xref deve essere **DWG**: gli script non scrivono DWG, quindi un cartiglio compilato dagli
  script va **incorporato** come blocco.
- LT 2025 non ha il comando MLINE: non proporlo.
- Python 3.15 (install manager), librerie: ezdxf, openpyxl, matplotlib, scipy, pywin32.
  scikit-image NON è disponibile per Python 3.15.

## 3. Standard delle tavole — DECISIONE IN VIGORE

- **26/10/2026 — Kevin: "lavora in scala 1:10 per il momento"** = convenzione **"base al 10"**
  delle tavole esistenti dello studio:
  - spazio modello in **centimetri** (anche se il file dichiara INSUNITS = mm),
  - stampa **1:100**, cornice **A1 × 10** nello spazio modello, cartiglio a **scala 10**,
  - simboli impiantistici a scala ~1–1,6 (circa 40 cm di ingombro in pianta = 4 mm su carta).
  È la convenzione usata da `tools/planimetria-impianto/` e dal progetto VJN001.
- Esiste anche il nuovo **standard Pemaj 1:1 in mm** (`tools/standard-pemaj/`, template
  `out/PEMAJ_TEMPLATE_mm.dxf`, regole sotto). I due metodi convivono: **non convertire** tavole
  dal metodo "base al 10" al metodo mm senza richiesta esplicita di Kevin.

### Regole globali Pemaj (dal file personale di Kevin, valgono per ogni disegno nel metodo mm)

1. Layer solo da `tools/standard-pemaj/comune.py` → `LAYERS` (colore ACI e tipo linea). Non inventare layer.
   Muri MURI 170, infissi INF 8, arredi ARREDI 33, sanitari SANIT 2, testi SCRITTE/TESTI 7,
   intestazioni SCRITTE1 90, locali LOCALI 9. Impianti: LC 3, FM 240, EM 4, QUADRI 5, RI 232,
   SER 204, CAN 30, TUB 14 BORDER, TERRA 14 INGOMBRO.
2. Colori/spessori di stampa da `riferimenti/PEMAJ_stili_master.xlsx`; CTB `PEMAJ_PROGETTI.ctb`
   (planimetrie), `PEMAJ_DIRI.ctb` (DI.RI.), `PEMAJ_SCHEMI.ctb` (schemi quadri).
3. Testi: stili PEMAJ_1.8 / 2.5 / 3.5 / 5 (romans.shx, larghezza 0,9), minimo 1,8 mm su carta.
   Quote stile PEMAJ (2,5 mm, virgola decimale).
4. Disegno 1:1 in mm (INSUNITS 4), annotazioni in spazio carta.
5. Tavole sul template dello studio; frontalino `PEMAJ_CARTIGLIO_BASE` con COMMITTENTE, OGGETTO,
   FASE, TAVOLA, TITOLO_TAVOLA compilati; squadratura 3,46 mm; in A3 solo il cartiglio.
6. Prima di consegnare: `verifica_tavola.py` + anteprima.
7. BIMCraft: stessi colori/spessori; se qualcosa non è riproducibile, dirlo.
- Dati del cartiglio mancanti (committente, numero tavola, data): chiederli o prenderli dalla
  tavola di progetto, **mai inventarli**.

## 4. Fatti scoperti sui disegni di Kevin

- Le piante degli architetti e le tavole dello studio sono in **cm** anche con INSUNITS = 4 (mm):
  verificato dalle quote (porte 90, muri 350/410). Gli script stimano l'unità dalle quote.
- Tavole tipo (ALLEGATO E01/E02, progetto Chieri – Aura Automotive): impaginate nello spazio
  modello; cornice = polilinea chiusa più grande sul layer 0; `CARTIGLIO BASE` e
  `Planimetria di Base` come xref; il blocco "cartiglio kevin" ha gli attributi SCALA, N°DISEGNO,
  DATA1-6, PROGETTO1-6.
- Nelle tavole vere i simboli sono soprattutto blocchi **non** presenti in LEGENDA100 (codici
  produttore 1584_2_1, 4960_2_1…, blocchi dinamici 16A, INT, PROIETTORE SU BINARIO):
  i blocchi dinamici `*Uxx` vanno sempre ricondotti al nome originale.
- Il blocco "emer" ha la geometria a ~140 m dal punto base: la libreria simboli ricentra i blocchi.
- La legenda di E01 è geometria importata da PDF; quella di E02 (layer LEGENDA EM) è fatta di blocchi.
- **Soluzione A** (scelta di Kevin): ogni voce di legenda ha il suo blocco; niente blocchi
  condivisi distinti da lettere accanto.

## 5. Numerazione progetti e progetti in corso

- Numerazione `VJN001`, `VJN002`… (scelta da Claude su delega di Kevin). Output in `Projects/<numero>/`.
- **VJN001 — Isola d'Asti, casa rustico / B&B** (pianta `PT_Isola_dAsti_casa_rustico_standard`,
  in cm, 6 viste: PT/P1 × stato di fatto / demolizioni / progetto).
  - Tavole E01 (illuminazione), E02 (FM + rivelazione incendi), E03 (dati, accessi, domotica)
    a 1:100, PT + P1 di progetto affiancati, con legenda e computo.
  - **DIMOSTRATIVO**: le dotazioni sono di Claude (`regole/esempio_dimostrativo.json`), NON
    progettuali; le tavole lo dichiarano in rosso. Cartiglio con dati segnaposto "Mario Rossi".
  - Locali da verificare: sala colazioni + corridoio + pianerottolo = spazio unico; camera B e C
    −15% rispetto alla superficie in pianta; "CAMERA 1 B&B" ripetuta al piano primo.
  - Rigenerare tutto: `python tools/planimetria-impianto/lavoro_completo.py Projects/VJN001/lavoro_VJN001.json`

## 6. Stato degli strumenti (skill)

| Skill | Stato | Note |
|---|---|---|
| `check-autocad` | utilità | verifica la catena DXF → LT |
| `cad-output` | LOCKED (34/34) | libreria DXF comune |
| `planimetria-impianto` | UNLOCKED, LOCK 42/42 | catalogo, tavola, locali, posa, dotazioni, legenda, computo |
| `standard-pemaj` | UNLOCKED, LOCK 13/13, congelato | CTB, template mm, verifica tavola, base pulita, autoriparazione |

## 7. In attesa da Kevin

- Verifica in LT: tavole VJN001 e tavola di prova E01 (xref caricati, pianta in grigio, ritaglio);
  template `PEMAJ_TEMPLATE_mm.dxf`, CTB, comando PEMAJ_FOGLIO.
- `tools/planimetria-impianto/catalogo_proposte.csv` da verificare (16 blocchi senza descrizione).
- Valori **CEI 64-8** (cap. 37, dotazioni per livello) per un file di regole vero.
- Due o tre conteggi controllati in LT per i test LOCK del computo.
- Computi metrici di esempio (Excel) e prezzario usato, per il computo metrico estimativo.
- Dati reali del committente VJN001.

## 8. Registro decisioni

- 12/10/2026 — Restare su AutoCAD LT con flusso DXF (niente AutoCAD completo).
- 12/10/2026 — Lo studio fa impianti elettrici: workspace convertito da strutturale a elettrico (CEI 64-8).
- 12/10/2026 — Soluzione A per i blocchi della legenda.
- 13/10/2026 — VJN001: 1:100, una tavola per impianto, PT e P1 affiancati; tavole dimostrative su richiesta.
- 26/10/2026 — "Base al 10" (cm, A1 ×10, 1:100) per il momento; memoria condivisa via GitHub con ChatGPT.
