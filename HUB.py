# ==============================================================================
# MODULI DA ESCLUDERE IN FASE DI COMPILAZIONE (Aggiornato per salvare i Grafici):
# PyQt5, PyQt6, PySide2, PySide6, IPython, notebook, jupyter, tornado, tkinter.test, pandas.tests, matplotlib.tests, bokeh, plotly
# ==============================================================================

import tkinter as tk
from tkinter import messagebox
import multiprocessing
import sys
import os
import ctypes

# Importiamo i tuoi script direttamente come moduli!
try:
    import DaPDF
    import EstraiDati_LIGHT
    import EstraiDatiMACRO
    import ConsultaDB
    import CreaGRAPHS  # Modulo per i grafici
except ImportError as e:
    messagebox.showerror("Errore di Avvio", f"Impossibile trovare uno degli script:\n{e}")


def resource_path(relative_path):
    """ Ottiene il percorso assoluto delle risorse, compatibile con PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class CalypsoHubApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Gestione Sistema Calypso - Pannello di Controllo")
        self.root.iconbitmap(resource_path("icona.ico"))

        # --- CENTRATURA AUTOMATICA DELLO SCHERMO ---
        window_width = 800
        window_height = 550

        # Ottiene le dimensioni dello schermo del PC
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        # Calcola le coordinate X e Y per il centro
        x_cordinate = int((screen_width / 2) - (window_width / 2))
        y_cordinate = int((screen_height / 2) - (window_height / 2))

        # Applica dimensioni e posizione
        self.root.geometry(f"{window_width}x{window_height}+{x_cordinate}+{y_cordinate}")

        self.root.resizable(False, False)
        self.root.configure(bg="#ecf0f1")

        self.moduli_aperti = {}

        self.setup_ui()

    def avvia_modulo(self, modulo_nome):
        """Apre il modulo richiesto o lo porta in primo piano se già aperto."""

        if modulo_nome in self.moduli_aperti:
            finestra_esistente = self.moduli_aperti[modulo_nome]
            if finestra_esistente.winfo_exists():
                finestra_esistente.lift()
                finestra_esistente.focus_force()
                finestra_esistente.bell()
                return
            else:
                del self.moduli_aperti[modulo_nome]

        finestra_figlia = tk.Toplevel(self.root)

        try:
            finestra_figlia.iconbitmap(resource_path("icona.ico"))
        except:
            pass

        self.moduli_aperti[modulo_nome] = finestra_figlia

        try:
            if modulo_nome == "DaPDF":
                app = DaPDF.CalypsoRenamerApp(finestra_figlia)
            elif modulo_nome == "EstraiDati_LIGHT":
                app = EstraiDati_LIGHT.CalypsoLightApp(finestra_figlia)
            elif modulo_nome == "EstraiDatiMACRO":
                app = EstraiDatiMACRO.UniversalExtractorApp(finestra_figlia)
            elif modulo_nome == "ConsultaDB":
                app = ConsultaDB.NavigatoreSQLiteApp(finestra_figlia)
            elif modulo_nome == "CreaGRAPHS":
                app = CreaGRAPHS.DataAnalyzerApp(finestra_figlia)

            self.root.after(100, lambda: [finestra_figlia.lift(), finestra_figlia.focus_force()])

        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile avviare il modulo {modulo_nome}:\n{str(e)}")
            finestra_figlia.destroy()
            if modulo_nome in self.moduli_aperti:
                del self.moduli_aperti[modulo_nome]

    def crea_card(self, contenitore, riga, colonna, titolo, descrizione, colore_sfondo, icona, identificativo_modulo, colspan=1, pad_interno=12):
        """Crea un bottone grande (Card) e lo posiziona in una griglia."""
        cell_frame = tk.Frame(contenitore, bg="#ecf0f1")
        cell_frame.grid(row=riga, column=colonna, columnspan=colspan, sticky="nsew", padx=12, pady=6)

        frame = tk.Frame(cell_frame, bg=colore_sfondo, bd=0, relief="flat", pady=pad_interno, padx=20)
        frame.pack(fill="both", expand=True)

        inner = tk.Frame(frame, bg=colore_sfondo)
        inner.pack(fill="both", expand=True)

        # L'icona si posiziona a sinistra ed è centrata verticalmente
        lbl_icona = tk.Label(inner, text=icona, font=("Segoe UI Emoji", 32), bg=colore_sfondo, fg="white")
        lbl_icona.pack(side="left", padx=(0, 15), anchor="center")

        frame_testi = tk.Frame(inner, bg=colore_sfondo)
        # FIX: Usiamo fill="x" invece di fill="both" + anchor="center".
        # Così il blocco di testo si allinea perfettamente all'altezza dell'icona!
        frame_testi.pack(side="left", fill="x", expand=True, anchor="center")

        lbl_titolo = tk.Label(frame_testi, text=titolo, font=("Arial", 13, "bold"), bg=colore_sfondo, fg="white", anchor="w")
        lbl_titolo.pack(fill="x")

        lbl_desc = tk.Label(frame_testi, text=descrizione, font=("Arial", 9), bg=colore_sfondo, fg="#ecf0f1", anchor="w", wraplength=700 if colspan==2 else 320, justify="left")
        lbl_desc.pack(fill="x", pady=(3, 0))

        for widget in [frame, inner, lbl_icona, frame_testi, lbl_titolo, lbl_desc]:
            widget.bind("<ButtonRelease-1>", lambda e, s=identificativo_modulo: self.avvia_modulo(s))
            widget.bind("<Enter>", lambda e, f=frame: f.configure(cursor="hand2"))

    def setup_ui(self):
        header = tk.Frame(self.root, bg="#2c3e50", pady=20)
        header.pack(fill="x")
        tk.Label(header, text="⚙️ SISTEMA CENTRALE CALYPSO", font=("Arial", 18, "bold"), bg="#2c3e50",
                 fg="white").pack()
        tk.Label(header, text="Seleziona il modulo da avviare", font=("Arial", 11, "italic"), bg="#2c3e50",
                 fg="#bdc3c7").pack()

        body = tk.Frame(self.root, bg="#ecf0f1", padx=20, pady=10)
        body.pack(fill="both", expand=True)

        body.rowconfigure(0, weight=0)  # Banner fisso
        body.rowconfigure(1, weight=1)  # Spazio condiviso
        body.rowconfigure(2, weight=1)  # Spazio condiviso
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        # RIGA 0 - BANNER SUPERIORE (Schiacciato, due colonne)
        self.crea_card(body, riga=0, colonna=0, colspan=2, pad_interno=8,
                       titolo="Rinomina PDF",
                       descrizione="Riconosce i lotti nei PDF e formatta correttamente i nomi dei file.",
                       colore_sfondo="#e67e22", icona="📄", identificativo_modulo="DaPDF")

        # RIGA 1 - LE DUE ESTRAZIONI (Affiancate)
        self.crea_card(body, riga=1, colonna=0, pad_interno=12,
                       titolo="Estrazione LIGHT",
                       descrizione="Estrazione mirata e selettiva con esportazione veloce in CSV/Excel.",
                       colore_sfondo="#16a085", icona="⚡", identificativo_modulo="EstraiDati_LIGHT")

        self.crea_card(body, riga=1, colonna=1, pad_interno=12,
                       titolo="Estrazione MACRO",
                       descrizione="Estrae grandi moli di PDF e salva i dati nel Database SQLite.",
                       colore_sfondo="#e74c3c", icona="⚙️", identificativo_modulo="EstraiDatiMACRO")

        # RIGA 2 - CONSULTA E GRAFICI (Affiancate)
        self.crea_card(body, riga=2, colonna=0, pad_interno=12,
                       titolo="Consulta Database",
                       descrizione="Analizza i dati salvati, applica filtri incrociati ed esporta report.",
                       colore_sfondo="#27ae60", icona="📊", identificativo_modulo="ConsultaDB")

        self.crea_card(body, riga=2, colonna=1, pad_interno=12,
                       titolo="Genera Grafici",
                       descrizione="Analisi statistica, curve di densità e confronto visivo tra lavorazioni.",
                       colore_sfondo="#8e44ad", icona="📈", identificativo_modulo="CreaGRAPHS")

        footer = tk.Frame(self.root, bg="#ecf0f1")
        footer.pack(side="bottom", fill="x", pady=5)
        tk.Label(footer, text="Sviluppato per automazione di processo.", font=("Arial", 8), fg="gray",
                 bg="#ecf0f1").pack()


if __name__ == "__main__":
    multiprocessing.freeze_support()

    try:
        myappid = 'azienda.calypso.hub.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    root = tk.Tk()

    try:
        root.iconbitmap(resource_path("icona.ico"))
    except:
        pass

    app = CalypsoHubApp(root)
    root.mainloop()