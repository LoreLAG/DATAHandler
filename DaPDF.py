import collections
import os
import sys
import logging
import re
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from pathlib import Path
from typing import Optional
from PyPDF2 import PdfReader
from datetime import datetime
import ctypes

# ==========================================
# 1. CONFIGURAZIONE E REGEX
# ==========================================
logging.getLogger("PyPDF2").setLevel(logging.ERROR)

RECINTO_ORDER = re.compile(r"Order number(.*?)Variant", flags=re.IGNORECASE | re.DOTALL)
RECINTO_IDENT = re.compile(r"Part ident(.*?)Time/Date", flags=re.IGNORECASE | re.DOTALL)
PATTERN_LOTTO = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{6})(?![A-Za-z0-9])")


# ==========================================
# 2. FUNZIONE DI ESTRAZIONE
# ==========================================
def estrai_lotto_pdf(percorso_pdf: Path) -> Optional[str]:
    try:
        reader = PdfReader(percorso_pdf)
        if not reader.pages: return None
        testo_pagina = reader.pages[0].extract_text()
        if not testo_pagina: return None

        codice = re.split(r"[_\s-]+", percorso_pdf.stem)[0]
        match_order = RECINTO_ORDER.search(testo_pagina)
        match_ident = RECINTO_IDENT.search(testo_pagina)

        frammenti = []
        if match_ident: frammenti.append(match_ident.group(1))
        if match_order: frammenti.append(match_order.group(1))

        for frammento in frammenti:
            possibili_lotti = PATTERN_LOTTO.findall(frammento)
            for candidato in possibili_lotti:
                candidato = candidato.upper()
                if candidato == codice.upper():
                    continue
                if any(c.isalpha() for c in candidato) and any(c.isdigit() for c in candidato):
                    return candidato
        return None
    except Exception:
        return None


# ==========================================
# 3. INTERFACCIA GRAFICA (GUI)
# ==========================================
class CalypsoRenamerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Sistema di Battesimo Report Calypso (Pro Edition)")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)
        self.root.configure(bg="#ecf0f1")

        # Variabili di stato
        self.percorso_radice = tk.StringVar()
        self.modalita_simulazione = tk.BooleanVar(value=True)

        # IL SEMAFORO PER IL GRACEFUL SHUTDOWN E MEDIA MOBILE
        self.stop_event = threading.Event()
        self.finestra_tempi = collections.deque(maxlen=50)

        self.setup_ui()

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        # ==========================================
        # 1. TOP BAR (Dark Header)
        # ==========================================
        frame_header = tk.Frame(self.root, pady=15, padx=20, bg="#1c2833")
        frame_header.pack(fill="x", side="top")

        tk.Label(frame_header, text="1. Seleziona Cartella Madre (PDF):", font=("Arial", 11, "bold"), bg="#1c2833",
                 fg="white", anchor="w").pack(side="left")
        tk.Entry(frame_header, textvariable=self.percorso_radice, state="readonly", font=("Arial", 10)).pack(
            side="left", fill="x", expand=True, padx=(10, 10))

        tk.Button(frame_header, text="📂 Sfoglia...", command=self.scegli_cartella, bg="#3498db", fg="white",
                  font=("Arial", 10, "bold"), bd=0, padx=15, pady=4).pack(side="right")

        # ==========================================
        # 2. BODY PRINCIPALE
        # ==========================================
        frame_body = tk.Frame(self.root, bg="#ecf0f1", padx=20, pady=15)
        frame_body.pack(fill="both", expand=True)

        # --- Sezione Modalità ---
        frame_mod = tk.LabelFrame(frame_body, text="2. Modalità di Esecuzione", font=("Arial", 10, "bold"),
                                  bg="#ecf0f1", padx=15, pady=10)
        frame_mod.pack(fill="x", pady=(0, 15))

        tk.Radiobutton(frame_mod, text="Simulazione (Crea solo il Log, NESSUN file modificato)",
                       variable=self.modalita_simulazione, value=True, bg="#ecf0f1", fg="#2980b9",
                       font=("Arial", 10, "bold")).pack(anchor="w", pady=2)
        tk.Radiobutton(frame_mod, text="Operativa Reale (Rinomina FISICAMENTE i file e applica i lotti)",
                       variable=self.modalita_simulazione, value=False, bg="#ecf0f1", fg="#c0392b",
                       font=("Arial", 10, "bold")).pack(anchor="w", pady=2)

        # --- Sezione Comandi ---
        frame_btns = tk.Frame(frame_body, bg="#ecf0f1")
        frame_btns.pack(fill="x", pady=(0, 15))

        self.btn_avvia = tk.Button(frame_btns, text="▶ AVVIA PROCESSO", font=("Arial", 14, "bold"), bg="#27ae60",
                                   fg="white", height=2, bd=0, command=self.avvia_processo)
        self.btn_avvia.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.btn_stop = tk.Button(frame_btns, text="⏹ FERMA", font=("Arial", 14, "bold"), bg="#c0392b", fg="white",
                                  height=2, bd=0, state="disabled", command=self.ferma_processo)
        self.btn_stop.pack(side="right", fill="x", expand=True)

        # --- Sezione Cruscotto Prestazioni ---
        frame_dash = tk.LabelFrame(frame_body, text="Cruscotto Prestazioni", font=("Arial", 10, "bold"), bg="#ffffff",
                                   padx=15, pady=10)
        frame_dash.pack(fill="x", pady=(0, 15))

        self.lbl_status = tk.Label(frame_dash, text="In attesa... pronti per iniziare.", font=("Consolas", 11, "bold"),
                                   bg="#ffffff", fg="#d35400")
        self.lbl_status.pack(anchor="w", pady=(0, 5))

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(frame_dash, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x")

        # --- Sezione Log di Sistema ---
        frame_log = tk.LabelFrame(frame_body, text="Log di Sistema", font=("Arial", 10, "bold"), bg="#ecf0f1")
        frame_log.pack(fill="both", expand=True)

        self.log_text = scrolledtext.ScrolledText(frame_log, state='disabled', bg="#1e1e1e", fg="#2ecc71",
                                                  font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True, padx=2, pady=2)

    def scegli_cartella(self):
        # FIX: Aggiunto parent=self.root
        cartella = filedialog.askdirectory(parent=self.root, title="Seleziona la cartella madre")
        if cartella:
            self.percorso_radice.set(cartella)

    def log(self, messaggio):
        def append():
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, messaggio + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')

        self.root.after(0, append)

    def update_dashboard(self, percent, testo_status):
        def _update():
            self.progress_var.set(percent)
            self.lbl_status.config(text=testo_status)

        self.root.after(0, _update)

    def avvia_processo(self):
        cartella = self.percorso_radice.get()
        if not cartella:
            # FIX: Aggiunto parent=self.root
            messagebox.showwarning("Attenzione", "Seleziona prima la cartella contenente i PDF!", parent=self.root)
            return

        # Prepara la UI per il processing
        self.stop_event.clear()  # Abbassa il semaforo
        self.btn_avvia.config(state="disabled", text="ELABORAZIONE IN CORSO...")
        self.btn_stop.config(state="normal", text="⏹ FERMA")

        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state='disabled')

        # Avvia il thread
        threading.Thread(target=self.processo_lavoro, args=(Path(cartella),), daemon=True).start()

    def ferma_processo(self):
        """Alza il semaforo per dire al thread di fermarsi gentilmente."""
        self.log("\n⚠️ Richiesta di arresto ricevuta... attesa completamento operazione corrente...")
        self.stop_event.set()
        self.btn_stop.config(state="disabled", text="ARRESTO IN CORSO...")

    def processo_lavoro(self, percorso_radice):
        simulazione = self.modalita_simulazione.get()
        mod_str = "SIMULAZIONE" if simulazione else "REALE"

        self.log(f"🚀 Avvio ESTRAZIONE PROFONDA DA PDF ({mod_str})")
        self.log("🔍 Conteggio preventivo dei file in corso...")

        lista_pdf = list(percorso_radice.rglob("*.pdf"))
        totale_pdf = len(lista_pdf)

        if totale_pdf == 0:
            self.log("⚠️ Nessun PDF trovato in questa cartella o sottocartelle.")
            self.root.after(0, self.fine_processo, False)
            return

        self.log(f"Trovati {totale_pdf} PDF pronti per l'analisi.\n")

        report_log = {
            "pdf_esaminati": 0,
            "pdf_successi": 0,
            "file_falliti": [],
            "accoppiate_trovate": set()
        }

        self.finestra_tempi.clear()  # Reset all'avvio per la media mobile
        start_time = time.time()
        ultimo_aggiornamento_ui = 0  # Cronometro per l'anti-sfarfallio
        interrotto = False

        for indice, pdf in enumerate(lista_pdf, start=1):
            # CONTROLLO DEL SEMAFORO: Se è stato premuto STOP, interrompiamo il ciclo
            if self.stop_event.is_set():
                self.log("\n🛑 ELABORAZIONE INTERROTTA DALL'UTENTE!")
                interrotto = True
                break

            report_log["pdf_esaminati"] += 1
            lotto_estratto = estrai_lotto_pdf(pdf)

            if lotto_estratto:
                codice_pdf = re.split(r"[_\s-]+", pdf.stem)[0]
                nome_base = f"{codice_pdf}_{lotto_estratto}"
                report_log["accoppiate_trovate"].add(nome_base)

                clean = pdf.stem.replace(lotto_estratto, "").replace(codice_pdf, "").replace("__", "_").strip("_")
                nome_finale = f"{nome_base}_{clean}.pdf" if clean else f"{nome_base}.pdf"

                if pdf.name != nome_finale:
                    if simulazione:
                        report_log["pdf_successi"] += 1
                        self.log(f"✅ [SIM] {pdf.name} -> {nome_finale}")
                    else:
                        try:
                            pdf.rename(pdf.parent / nome_finale)
                            report_log["pdf_successi"] += 1
                            self.log(f"✅ [OK] {pdf.name} -> {nome_finale}")
                        except Exception as e:
                            report_log["file_falliti"].append(f"{pdf.name} (Errore OS: {e})")
                            self.log(f"❌ [ERRORE] {pdf.name}: {e}")
            else:
                report_log["file_falliti"].append(f"{pdf.name} (Nessun lotto)")

            # ==========================================
            # DASHBOARD CON THROTTLING (No Sfarfallio)
            # ==========================================
            ora_attuale = time.time()
            self.finestra_tempi.append(ora_attuale)

            # AGGIORNIAMO LA GUI SOLO OGNI 0.5 SECONDI (o se è l'ultimo file in assoluto)
            if (ora_attuale - ultimo_aggiornamento_ui) > 0.5 or indice == totale_pdf:

                # Calcoliamo la velocità basandoci solo sugli ultimi N file salvati in finestra_tempi
                if len(self.finestra_tempi) > 1:
                    tempo_finestra = ora_attuale - self.finestra_tempi[0]
                    n_campioni = len(self.finestra_tempi) - 1
                    vel_reale = n_campioni / tempo_finestra if tempo_finestra > 0 else 0
                else:
                    # Fallback per i primissimi file
                    elapsed_totale = ora_attuale - start_time
                    vel_reale = indice / elapsed_totale if elapsed_totale > 0 else 0

                perc = (indice / totale_pdf) * 100

                if vel_reale > 0:
                    eta_sec = (totale_pdf - indice) / vel_reale
                    mins, secs = divmod(int(eta_sec), 60)
                    eta_str = f"{mins:02d}:{secs:02d}"
                else:
                    eta_str = "--:--"

                nome_troncato = (pdf.name[:25] + '..') if len(pdf.name) > 25 else pdf.name
                status_text = f"ETA: {eta_str} | 🚀 {vel_reale:.1f} p/s | ✅ {report_log['pdf_successi']} ❌ {len(report_log['file_falliti'])} | 📄 {nome_troncato}"

                self.update_dashboard(perc, status_text)

                # Resettiamo il cronometro della GUI
                ultimo_aggiornamento_ui = ora_attuale

        # Fine ciclo (sia naturale che interrotto)
        tempo_trascorso = time.time() - start_time

        # Scriviamo comunque il log con quello che siamo riusciti a fare fino allo stop
        self.scrivi_log_file(percorso_radice, report_log, simulazione, tempo_trascorso, interrotto)

        self.root.after(0, self.fine_processo, interrotto)

    def scrivi_log_file(self, percorso_radice: Path, log_dati: dict, simulazione: bool, tempo_esec: float,
                        interrotto: bool):
        modalita = "SIMULAZIONE" if simulazione else "OPERATIVA REALE"
        stato_finale = " (INTERROTTO INCOMPLETO)" if interrotto else ""

        percorso_file = percorso_radice / f"Log_Calypso_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        velocita = log_dati['pdf_esaminati'] / tempo_esec if tempo_esec > 0 else 0

        with open(percorso_file, "w", encoding="utf-8") as f:
            f.write("=" * 50 + "\n")
            f.write(f" REPORT BATTESIMO CALYPSO - MODALITÀ {modalita}{stato_finale} \n")
            f.write("=" * 50 + "\n\n")
            f.write("--- ⏱️ TELEMETRIA DI PROCESSO ---\n")
            f.write(f"Tempo di esecuzione: {tempo_esec:.2f} secondi\n")
            f.write(f"Velocità media:      {velocita:.2f} PDF/secondo\n\n")
            f.write("--- 📊 STATISTICHE GENERALI ---\n")
            f.write(f"PDF Totali Esaminati:  {log_dati['pdf_esaminati']}\n")
            f.write(f"PDF Gestiti/Rinominati:{log_dati['pdf_successi']}\n")
            f.write(f"PDF Falliti/Ignorati:  {len(log_dati['file_falliti'])}\n\n")
            f.write("--- 🏷️ CODICI E LOTTI TROVATI ---\n")
            if not log_dati['accoppiate_trovate']:
                f.write("Nessun lotto/codice valido identificato.\n")
            else:
                for accoppiata in sorted(log_dati['accoppiate_trovate']):
                    f.write(f"- {accoppiata}\n")
            f.write("\n--- ❌ DETTAGLIO FILE NON RINOMINABILI ---\n")
            if not log_dati['file_falliti']:
                f.write("Perfetto! Nessun file ha generato errori o lotti mancanti.\n")
            else:
                for file in log_dati['file_falliti']:
                    f.write(f"- {file}\n")

        self.log(f"\n📝 File di log salvato in: {percorso_file.name}")
        self.log(f"⏱️ Tempo totale: {tempo_esec:.2f}s | 🚀 Velocità finale: {velocita:.2f} PDF/s")

    def fine_processo(self, interrotto):
        self.btn_avvia.config(state="normal", text="▶ AVVIA PROCESSO")
        self.btn_stop.config(state="disabled", text="⏹ FERMA")

        if interrotto:
            self.lbl_status.config(text="Processo arrestato dall'utente.", fg="#c0392b")
            # FIX: Aggiunto parent=self.root
            messagebox.showinfo("Interrotto",
                                "Elaborazione fermata in sicurezza.\nIl Log è stato salvato con i risultati parziali.", parent=self.root)
        else:
            self.update_dashboard(100, "Operazione Completata con Successo!")
            self.lbl_status.config(fg="#27ae60")
            # FIX: Aggiunto parent=self.root
            messagebox.showinfo("Fatto!", "Operazione completata!\nControlla il Log per i dettagli.", parent=self.root)


if __name__ == "__main__":
    try:
        # ID univoco per mantenere un'icona separata sulla taskbar di Windows
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Calypso.Renamer.Pro")
    except Exception:
        pass

    root = tk.Tk()
    app = CalypsoRenamerApp(root)
    root.mainloop()