;;; ==========================================================================
;;; PEMAJ_FOGLIO - Studio Pemaj - standard grafico
;;; Cambia le misure del foglio nel layout corrente, come un blocco dinamico:
;;;   - il bordo di taglio (polilinea sul layer "cartiglio") e la squadratura si allungano
;;;   - la finestra si allarga insieme al foglio
;;;   - il cartiglio (PEMAJ_CARTIGLIO) resta nello spigolo in basso a destra
;;; Funziona su tutti i layout del template PEMAJ (A3, A2, A1, A0, LIBERO).
;;; Caricamento: APPLOAD -> PEMAJ_FOGLIO.lsp (oppure "Contenuto di avvio" per averlo sempre).
;;; Uso: PEMAJ_FOGLIO -> base e altezza in mm. Poi IMPOSTAPAGINA con lo stesso formato carta.
;;; Usa solo funzioni AutoLISP disponibili anche in AutoCAD LT 2024 e successivi.
;;; ==========================================================================

(defun pemaj:estensione (e / d xs ys)
  (setq d (entget e) xs nil ys nil)
  (foreach p d
    (if (= (car p) 10)
      (setq xs (cons (cadr p) xs) ys (cons (caddr p) ys))
    )
  )
  (list (apply 'min xs) (apply 'min ys) (apply 'max xs) (apply 'max ys))
)

(defun pemaj:bordo (/ ss i e ext best area a)
  ;; il bordo di taglio e' la polilinea piu' grande sul layer "cartiglio" del layout corrente
  (setq ss (ssget "_X" (list '(0 . "LWPOLYLINE") '(8 . "cartiglio") (cons 410 (getvar "CTAB"))))
        best nil area 0.0 i 0)
  (if ss
    (repeat (sslength ss)
      (setq e (ssname ss i)
            ext (pemaj:estensione e)
            a (* (- (caddr ext) (car ext)) (- (cadddr ext) (cadr ext))))
      (if (> a area) (setq area a best ext))
      (setq i (1+ i))
    )
  )
  best
)

(defun c:PEMAJ_FOGLIO (/ *error* vecchi ext x0 y0 x1 y1 W0 H0 W H dW dH)
  (setq vecchi (list (getvar "OSMODE") (getvar "CMDECHO")))
  (defun *error* (msg)
    (setvar "OSMODE" (car vecchi))
    (setvar "CMDECHO" (cadr vecchi))
    (if (and msg (not (wcmatch (strcase msg) "*ANNULL*,*CANCEL*,*QUIT*")))
      (princ (strcat "\nErrore: " msg))
    )
    (princ)
  )
  (cond
    ((= (getvar "TILEMODE") 1)
     (princ "\nPEMAJ_FOGLIO si usa in un layout, non nello spazio modello."))
    (T
     (if (/= (getvar "CVPORT") 1) (command "_.PSPACE"))
     (setq ext (pemaj:bordo))
     (if (null ext)
       (princ "\nNessun bordo del foglio (polilinea sul layer cartiglio) in questo layout.")
       (progn
         (setq x0 (car ext) y0 (cadr ext) x1 (caddr ext) y1 (cadddr ext)
               W0 (- x1 x0) H0 (- y1 y0))
         (setq W (getreal (strcat "\nBase del foglio in mm <" (rtos W0 2 0) ">: ")))
         (if (null W) (setq W W0))
         (setq H (getreal (strcat "\nAltezza del foglio in mm <" (rtos H0 2 0) ">: ")))
         (if (null H) (setq H H0))
         (if (or (< W 250.0) (< H 200.0))
           (princ "\nFoglio troppo piccolo per il cartiglio (minimo 250 x 200 mm).")
           (progn
             (setq dW (- W W0) dH (- H H0))
             (setvar "CMDECHO" 0)
             (setvar "OSMODE" 0)
             (command "_.UNDO" "_BE")
             (command "_.ZOOM" "_W" (list (- x0 20) (- y0 20)) (list (+ x0 (max W W0) 20) (+ y0 (max H H0) 20)))
             ;; lato destro: bordo, squadratura, finestra e cartiglio (punto base in basso a destra)
             (if (/= dW 0.0)
               (command "_.STRETCH" "_C" (list (- x1 12.0) (- y0 1.0)) (list (+ x1 1.0) (+ y1 1.0)) ""
                        (list 0.0 0.0) (list dW 0.0))
             )
             ;; lato in alto: bordo, squadratura e finestra (il cartiglio e' in basso e non si muove)
             (if (/= dH 0.0)
               (command "_.STRETCH" "_C" (list (- x0 1.0) (- y1 12.0)) (list (+ x0 W 1.0) (+ y1 1.0)) ""
                        (list 0.0 0.0) (list 0.0 dH))
             )
             (command "_.UNDO" "_E")
             (command "_.ZOOM" "_E")
             (princ (strcat "\nFoglio " (rtos W 2 0) " x " (rtos H 2 0) " mm."
                            " Ora IMPOSTAPAGINA: formato carta " (rtos W 2 0) " x " (rtos H 2 0)
                            " (se manca: DWG To PDF.pc3 -> Proprieta' -> Formati carta personalizzati)."))
           )
         )
       )
     )
    )
  )
  (*error* nil)
)

(princ "\nCaricato PEMAJ_FOGLIO: cambia le misure del foglio nel layout corrente.")
(princ)
