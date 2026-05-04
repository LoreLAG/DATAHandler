import fitz
import pdfplumber
import re
import os
import time
import threading
import sqlite3
import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext, simpledialog
import multiprocessing
import ctypes

# ── COSTANTI GRAFICHE ────────────────────────────────────────────────────────
CHECKED = "☑"
UNCHECKED = "☐"

# ── REGEX PER L'ESTRAZIONE DELLE MISURE ──
RE_CALYPSO = re.compile(
    r"^(.+?)[ \t]+(-?\d+[,\.]\d+)[ \t]*mm[ \t]+"
    r"(-?\d+[,\.]\d+)[ \t]+(-?\d+[,\.]\d+)[ \t]+(-?\d+[,\.]\d+)[ \t]+(-?\d+[,\.]\d+)"
    r"(?:[ \t]+(-?\d+[,\.]\d+))?$"
)
RE_ANGLE = re.compile(r"^(.+?)[ \t]+(-?\d+[,\.]\d+)°[ \t]+(-?\d+[,\.]\d+)[ \t]+(-?\d+[,\.]\d+)$")
RE_PARTIAL = re.compile(r"^(.+?)[ \t]+(-?\d+[,\.]\d+)[ \t]*mm[ \t]*$")
RE_SECTION = re.compile(r"^(V\d+_F\d+)$")


def parse_number(s):
    if not s: return None
    try:
        return float(s.strip().replace(" mm", "").replace(",", "."))
    except ValueError:
        return None


def pulisci_testo(testo):
    return " ".join(str(testo).split()) if testo else ""


# ── WORKER: ESTRAZIONE MISURE (pdfplumber) ──
def worker_estrazione_misure(args):
    """Estrae le misurazioni e applica il tag fase scelto dall'utente (anche vuoto)."""
    pdf_path_str, codice, lotto, fase = args
    pdf_path = Path(pdf_path_str)

    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n".join([p.extract_text() or "" for p in pdf.pages])
    except Exception as e:
        return {"error": str(e), "file_path": pdf_path_str}

    righe_estratte = []
    seen = set()
    current_section = ""

    for line in full_text.splitlines():
        line = line.strip()
        if RE_SECTION.match(line):
            current_section = RE_SECTION.match(line).group(1)
            continue
        if line.startswith("Velocità") or line.startswith("Zylinderform") and "mm" not in line:
            continue

        m = RE_CALYPSO.match(line)
        if m:
            nome = pulisci_testo(m.group(1))
            meas = parse_number(m.group(2))
            nom = parse_number(m.group(3))
            tp = parse_number(m.group(4))
            tm = parse_number(m.group(5))
            dev = parse_number(m.group(6))
            extra = parse_number(m.group(7)) if len(m.groups()) > 6 else None
            stato = "OK" if (tm is not None and tp is not None and dev is not None and tm <= dev <= tp) else "NON OK"
        else:
            m_angle = RE_ANGLE.match(line)
            if m_angle:
                nome = pulisci_testo(m_angle.group(1))
                meas = parse_number(m_angle.group(2))
                nom = parse_number(m_angle.group(3))
                tp = tm = extra = stato = None
                dev = parse_number(m_angle.group(4))
            else:
                m_part = RE_PARTIAL.match(line)
                if m_part:
                    nome = pulisci_testo(m_part.group(1))
                    meas = parse_number(m_part.group(2))
                    nom = tp = tm = dev = extra = stato = None
                else:
                    continue

        key = (current_section, nome)
        if key not in seen:
            seen.add(key)
            tupla_riga = (pdf_path_str, pdf_path.parent.name, codice, lotto, current_section, nome,
                          meas, nom, tp, tm, dev, extra, stato, fase)
            righe_estratte.append(tupla_riga)

    return {"file_path": pdf_path_str, "data": righe_estratte}


# ── INTERFACCIA GRAFICA ──
class UniversalExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Estrattore Dati MACRO - DB SQLite")
        self.root.geometry("1400x800")
        self.root.minsize(1050, 700)

        try:
            self.root.state('zoomed')
        except tk.TclError:
            self.root.attributes('-zoomed', True)

        self.db_path = tk.StringVar()
        self.dati_cartelle = {}
        self.last_clicked_item = None
        self.stop_flag = threading.Event()

        self.setup_ui()

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Treeview", rowheight=28, font=("Arial", 10))
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"), background="#d5d8dc")

        # --- HEADER (Top Bar Scura) ---
        frame_header = tk.Frame(self.root, pady=15, padx=20, bg="#1c2833")
        frame_header.pack(fill="x")

        # RIGA 1: Selezione DB
        frame_db_sel = tk.Frame(frame_header, bg="#1c2833")
        frame_db_sel.pack(fill="x", pady=(0, 10))
        tk.Label(frame_db_sel, text="1. Database SQLite:", font=("Arial", 11, "bold"), bg="#1c2833", fg="white",
                 width=20,
                 anchor="w").pack(side="left")
        tk.Entry(frame_db_sel, textvariable=self.db_path, state="readonly", font=("Arial", 10)).pack(side="left",
                                                                                                     fill="x",
                                                                                                     expand=True,
                                                                                                     padx=(0, 10))

        tk.Button(frame_db_sel, text="➕ Crea Nuovo DB...", command=self.crea_db, bg="#f39c12", fg="white",
                  font=("Arial", 9, "bold"), bd=0, padx=10, pady=4).pack(side="right", padx=(5, 0))
        tk.Button(frame_db_sel, text="📂 Apri Esistente...", command=self.scegli_db, bg="#3498db", fg="white",
                  font=("Arial", 9, "bold"), bd=0, padx=10, pady=4).pack(side="right")

        # RIGA 2: Selezione Sorgenti
        frame_dir_sel = tk.Frame(frame_header, bg="#1c2833")
        frame_dir_sel.pack(fill="x")
        tk.Label(frame_dir_sel, text="2. Sorgenti Dati:", font=("Arial", 11, "bold"), bg="#1c2833", fg="white",
                 width=20,
                 anchor="w").pack(side="left")

        tk.Button(frame_dir_sel, text="Aggiungi Cartella", font=("Arial", 10, "bold"),
                  bg="#27ae60", fg="white", bd=0, padx=10, pady=4,
                  command=self.aggiungi_cartella_singola).pack(side="left", padx=(0, 5))

        tk.Button(frame_dir_sel, text="Importa Sottocartelle Separate", font=("Arial", 10, "bold"),
                  bg="#16a085", fg="white", bd=0, padx=10, pady=4,
                  command=self.aggiungi_macrocartella).pack(side="left")

        # --- BODY (Tabella e Controlli) ---
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True, padx=15, pady=15)

        # SINISTRA: Treeview
        frame_sx = tk.LabelFrame(paned, text="Elenco Cartelle in Coda (Seleziona per impostare Fase/Lotto)", padx=10,
                                 pady=10, bg="#ecf0f1")
        paned.add(frame_sx, weight=2)

        frame_btn_tree = tk.Frame(frame_sx, bg="#ecf0f1")
        frame_btn_tree.pack(fill="x", pady=(0, 8))
        tk.Button(frame_btn_tree, text="☑ Seleziona Tutto", command=self.seleziona_tutto, bd=0, bg="#bdc3c7", padx=8,
                  pady=3).pack(side="left", padx=(0, 5))
        tk.Button(frame_btn_tree, text="☐ Deseleziona Tutto", command=self.deseleziona_tutto, bd=0, bg="#bdc3c7",
                  padx=8, pady=3).pack(side="left", padx=(0, 5))
        tk.Button(frame_btn_tree, text="🗑 Rimuovi", command=self.rimuovi_cartella_selezionata, bd=0, bg="#e74c3c",
                  fg="white", padx=8, pady=3).pack(side="left")

        tk.Button(frame_btn_tree, text="✏️ Forza Lotto", bg="#f1c40f", font=("Arial", 9, "bold"), bd=0, padx=10, pady=3,
                  command=self.imposta_lotto).pack(side="right")
        tk.Button(frame_btn_tree, text="🏷️ Imposta Fase", bg="#3498db", fg="white", font=("Arial", 9, "bold"), bd=0,
                  padx=10, pady=3,
                  command=self.imposta_fase).pack(side="right", padx=(0, 5))

        cols = ("check", "cartella_display", "conteggio", "fase", "lotto_forzato", "percorso_full")
        self.tree = ttk.Treeview(frame_sx, columns=cols, show="headings", selectmode="extended")

        self.tree.heading("check", text="Esporta")
        self.tree.heading("cartella_display", text="Percorso Cartella")
        self.tree.heading("conteggio", text="PDF Trovati")
        self.tree.heading("fase", text="Fase (Tag)")
        self.tree.heading("lotto_forzato", text="Lotto Forzato")
        self.tree.heading("percorso_full", text="")

        self.tree.column("check", width=65, anchor="center")
        self.tree.column("cartella_display", width=350, anchor="w")
        self.tree.column("conteggio", width=80, anchor="center")
        self.tree.column("fase", width=90, anchor="center")
        self.tree.column("lotto_forzato", width=130, anchor="center")
        self.tree.column("percorso_full", width=0, minwidth=0, stretch=tk.NO)

        scroll_tree = ttk.Scrollbar(frame_sx, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll_tree.set)
        scroll_tree.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<ButtonRelease-1>", self.on_tree_click)

        # DESTRA: Cruscotto e Comandi
        frame_dx = tk.Frame(paned, bg="#ecf0f1")
        paned.add(frame_dx, weight=1)

        self.btn_start = tk.Button(frame_dx, text="▶ AVVIA SCRITTURA DB", font=("Arial", 12, "bold"), bg="#27ae60",
                                   fg="white", height=2, bd=0, command=self.avvia_estrazione)
        self.btn_start.pack(fill="x", pady=(0, 5))

        self.btn_stop = tk.Button(frame_dx, text="⏹ FERMA", font=("Arial", 12, "bold"), bg="#c0392b", fg="white",
                                  height=2, bd=0, command=self.ferma, state="disabled")
        self.btn_stop.pack(fill="x", pady=(5, 15))

        frame_dash = tk.LabelFrame(frame_dx, text="Cruscotto Prestazioni", padx=10, pady=10, bg="#ffffff")
        frame_dash.pack(fill="x", pady=(0, 10))

        self.lbl_file = tk.Label(frame_dash, text="File: 0 / 0", bg="#ffffff", font=("Consolas", 11))
        self.lbl_file.pack(anchor="w")
        self.lbl_eta = tk.Label(frame_dash, text="ETA: --:--", bg="#ffffff", font=("Consolas", 11, "bold"),
                                fg="#d35400")
        self.lbl_eta.pack(anchor="w")

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(frame_dash, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", pady=(10, 0))

        # Log Console Style
        frame_log = tk.LabelFrame(frame_dx, text="Log Operazioni", bg="#ecf0f1")
        frame_log.pack(fill="both", expand=True)
        self.log_text = scrolledtext.ScrolledText(frame_log, state='disabled', bg="#1e1e1e", fg="#2ecc71",
                                                  font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

        self.carica_cache()

    # --- METODI CACHE E MEMORIA ---
    def salva_cache(self):
        cache_data = {"db_path": self.db_path.get(), "cartelle": {}}
        for percorso, data in self.dati_cartelle.items():
            cache_data["cartelle"][percorso] = {
                "is_rglob": data["is_rglob"],
                "check": data["check"],
                "lotto_forzato": data["lotto_forzato"],
                "fase": data.get("fase", "POST")
            }
        try:
            with open("cache_extractor.json", "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=4)
        except Exception:
            pass

    def carica_cache(self):
        cache_file = Path("cache_extractor.json")
        if not cache_file.exists(): return
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            if cache_data.get("db_path") and Path(cache_data["db_path"]).exists():
                self.db_path.set(cache_data["db_path"])
            for percorso, info in cache_data.get("cartelle", {}).items():
                p = Path(percorso)
                if p.exists():
                    is_rglob = info.get("is_rglob", False)
                    pdfs = list(p.rglob("*.pdf")) if is_rglob else list(p.glob("*.pdf"))
                    if pdfs:
                        old_check = info.get("check", CHECKED)
                        if old_check == "[X]": old_check = CHECKED
                        if old_check == "[ ]": old_check = UNCHECKED

                        self._aggiungi_a_dati_cartelle(p, pdfs, is_rglob=is_rglob, check=old_check,
                                                       lotto_forzato=info.get("lotto_forzato", ""),
                                                       fase=info.get("fase", "POST"))
            self.popola_treeview()
            self.log("✅ Cache ripristinata.")
        except Exception:
            pass

    def scegli_db(self):
        # FIX: Aggiunto parent=self.root
        if p := filedialog.askopenfilename(parent=self.root, title="Database SQLite",
                                           filetypes=[("DB SQLite", "*.db")]):
            self.db_path.set(p)
            self.salva_cache()

    def crea_db(self):
        # FIX: Aggiunto parent=self.root
        if p := filedialog.asksaveasfilename(parent=self.root, title="Crea Nuovo DB", defaultextension=".db",
                                             filetypes=[("DB SQLite", "*.db")],
                                             initialfile="Nuovo_Database_Calypso.db"):
            try:
                sqlite3.connect(p).close()
                self.db_path.set(p)
                self.salva_cache()
                self.log(f"✅ DB creato: {Path(p).name}")
            except Exception as e:
                # FIX: Aggiunto parent=self.root
                messagebox.showerror("Errore", str(e), parent=self.root)

    def _aggiungi_a_dati_cartelle(self, percorso, pdfs, is_rglob=False, check=CHECKED, lotto_forzato="", fase="POST"):
        percorso_str = str(percorso)
        p = Path(percorso)
        display_path = f"...\\{p.parts[-2]}\\{p.parts[-1]}" if len(p.parts) >= 2 else p.name

        if percorso_str not in self.dati_cartelle:
            self.dati_cartelle[percorso_str] = {"pdfs": pdfs, "is_rglob": is_rglob, "check": check,
                                                "lotto_forzato": lotto_forzato, "display_path": display_path,
                                                "fase": fase}
            return True
        else:
            self.dati_cartelle[percorso_str].update({"pdfs": pdfs, "is_rglob": is_rglob})
            return False

    def aggiungi_macrocartella(self):
        # FIX: Aggiunto parent=self.root
        if cartella := filedialog.askdirectory(parent=self.root, title="Seleziona la Macrocartella"):
            base_dir = Path(cartella)
            self.log(f"Scansione Ricorsiva Batch: {base_dir.name}...")
            nuove = sum(1 for sub in base_dir.iterdir() if
                        sub.is_dir() and (pdfs := list(sub.rglob("*.pdf"))) and self._aggiungi_a_dati_cartelle(sub,
                                                                                                               pdfs,
                                                                                                               is_rglob=True))
            if root_pdfs := list(base_dir.glob("*.pdf")):
                if self._aggiungi_a_dati_cartelle(base_dir, root_pdfs, is_rglob=False): nuove += 1
            self.popola_treeview()
            self.log(f"Aggiunte {nuove} nuove righe separate.")

    def aggiungi_cartella_singola(self):
        # FIX: Aggiunto parent=self.root
        if cartella := filedialog.askdirectory(parent=self.root, title="Seleziona cartella"):
            sub_dir = Path(cartella)
            # FIX: Aggiunto parent=self.root
            inc_sub = messagebox.askyesno("Sottocartelle",
                                          "Includere i PDF presenti anche nelle sottocartelle interne in questo unico blocco?",
                                          parent=self.root)
            if pdfs := list(sub_dir.rglob("*.pdf") if inc_sub else sub_dir.glob("*.pdf")):
                if self._aggiungi_a_dati_cartelle(sub_dir, pdfs, is_rglob=inc_sub):
                    self.popola_treeview()
                    self.log(f"Aggiunto blocco unico da: {sub_dir.name} ({len(pdfs)} PDF).")
            else:
                # FIX: Aggiunto parent=self.root
                messagebox.showinfo("Nessun PDF", "La cartella è vuota.", parent=self.root)

    def rimuovi_cartella_selezionata(self):
        for item in self.tree.selection():
            if (pa := self.tree.item(item, "values")[5]) in self.dati_cartelle:
                del self.dati_cartelle[pa]
            self.tree.delete(item)
        self.salva_cache()

    def popola_treeview(self):
        self.tree.delete(*self.tree.get_children())
        for p, d in sorted(self.dati_cartelle.items()):
            testo_lotto = d["lotto_forzato"]
            self.tree.insert("", tk.END, values=(d["check"], d["display_path"], len(d["pdfs"]), d.get("fase", "POST"),
                                                 testo_lotto, p))
        self.salva_cache()

    def on_tree_click(self, event):
        if self.tree.identify("region", event.x, event.y) == "cell" and self.tree.identify_column(event.x) == '#1':
            item = self.tree.identify_row(event.y)
            pa = self.tree.item(item, "values")[5]
            n_stato = UNCHECKED if self.dati_cartelle[pa]["check"] == CHECKED else CHECKED
            items_agg = [item]

            if event.state & 0x0001 and getattr(self, "last_clicked_item", None):
                items = self.tree.get_children()
                try:
                    i1, i2 = items.index(self.last_clicked_item), items.index(item)
                    items_agg = items[min(i1, i2):max(i1, i2) + 1]
                except ValueError:
                    pass

            for c_item in items_agg:
                pa = self.tree.item(c_item, "values")[5]
                self.dati_cartelle[pa]["check"] = n_stato
                d = self.dati_cartelle[pa]
                testo_lotto = d["lotto_forzato"]
                self.tree.item(c_item, values=(d["check"], d["display_path"], len(d["pdfs"]), d.get("fase", "POST"),
                                               testo_lotto, pa))

            self.last_clicked_item = item
            self.salva_cache()

    def seleziona_tutto(self):
        for item in self.tree.get_children():
            pa = self.tree.item(item, "values")[5]
            self.dati_cartelle[pa]["check"] = CHECKED
            d = self.dati_cartelle[pa]
            testo_lotto = d["lotto_forzato"]
            self.tree.item(item, values=(d["check"], d["display_path"], len(d["pdfs"]), d.get("fase", "POST"),
                                         testo_lotto, pa))
        self.salva_cache()

    def deseleziona_tutto(self):
        for item in self.tree.get_children():
            pa = self.tree.item(item, "values")[5]
            self.dati_cartelle[pa]["check"] = UNCHECKED
            d = self.dati_cartelle[pa]
            testo_lotto = d["lotto_forzato"]
            self.tree.item(item, values=(d["check"], d["display_path"], len(d["pdfs"]), d.get("fase", "POST"),
                                         testo_lotto, pa))
        self.salva_cache()

    def imposta_lotto(self):
        if not (sel := self.tree.selection()):
            # FIX: Aggiunto parent=self.root
            return messagebox.showinfo("Info", "Seleziona righe dalla tabella.", parent=self.root)
        primo = self.tree.item(sel[0], "values")[5]
        # FIX: Aggiunto parent=self.root
        if (
                n_lotto := simpledialog.askstring("Forza Lotto",
                                                  "Inserisci lotto (lascia vuoto per leggere dal NOME FILE):",
                                                  initialvalue=self.dati_cartelle[primo]["lotto_forzato"],
                                                  parent=self.root)) is not None:
            l_pulito = n_lotto.strip().upper()
            for item in sel:
                pa = self.tree.item(item, "values")[5]
                self.dati_cartelle[pa]["lotto_forzato"] = l_pulito
                d = self.dati_cartelle[pa]
                testo_lotto = l_pulito
                self.tree.item(item, values=(d["check"], d["display_path"], len(d["pdfs"]), d.get("fase", "POST"),
                                             testo_lotto, pa))
            self.salva_cache()

    def imposta_fase(self):
        if not (sel := self.tree.selection()):
            # FIX: Aggiunto parent=self.root
            return messagebox.showinfo("Info", "Seleziona righe dalla tabella.", parent=self.root)
        primo = self.tree.item(sel[0], "values")[5]

        # FIX: Aggiunto parent=self.root
        if (n_fase := simpledialog.askstring("Imposta Fase", "Inserisci la Fase (es. PRE, POST, SCARTO):",
                                             initialvalue=self.dati_cartelle[primo].get("fase", "POST"),
                                             parent=self.root)) is not None:
            f_pulita = n_fase.strip().upper()
            for item in sel:
                pa = self.tree.item(item, "values")[5]
                self.dati_cartelle[pa]["fase"] = f_pulita
                d = self.dati_cartelle[pa]
                testo_lotto = d["lotto_forzato"]
                self.tree.item(item,
                               values=(d["check"], d["display_path"], len(d["pdfs"]), d["fase"], testo_lotto,
                                       pa))
            self.salva_cache()

    def log(self, m):
        ora = time.strftime("%H:%M:%S")
        testo_formattato = f"[{ora}] {m}"

        def a():
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, testo_formattato + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')

        self.root.after(0, a)

    # --- GRACEFUL SHUTDOWN (CHIUSURA PULITA) ---
    def ferma(self):
        # FIX: Aggiunto parent=self.root
        risposta = messagebox.askyesno("Conferma Arresto",
                                       "Vuoi interrompere l'estrazione e chiudere l'applicazione?\n\nI file in coda verranno cancellati, mentre quelli attualmente in lavorazione verranno salvati.",
                                       parent=self.root)
        if risposta:
            self.stop_flag.set()
            self.btn_stop.config(state="disabled", text="CHIUSURA IN CORSO...")
            self.log("⚠️ Richiesta di arresto. Svuotamento coda in corso...")

    def update_dash(self, p, t, s):
        def a():
            el = time.time() - s
            vel = p / el if el > 0 else 0
            eta = (t - p) / vel if vel > 0 else 0
            m_eta, s_eta = divmod(int(eta), 60)
            eta_str = f"{m_eta}m {s_eta}s"

            self.lbl_file.config(text=f"File: {p} / {t}")
            self.lbl_eta.config(text=f"ETA: {eta_str}")
            self.progress_var.set((p / t) * 100 if t > 0 else 0)

        self.root.after(0, a)

    def reset_ui(self):
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled", text="⏹ FERMA")

    # --- PROCESSO DI ESTRAZIONE ---
    def avvia_estrazione(self):
        if not self.db_path.get() or not self.dati_cartelle:
            # FIX: Aggiunto parent=self.root
            return messagebox.showwarning("Errore", "Configura il DB e aggiungi almeno una cartella!", parent=self.root)

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.stop_flag.clear()
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state='disabled')

        threading.Thread(target=self.processo_estrazione, daemon=True).start()

    def processo_estrazione(self):
        self.log("🚀 Avvio Estrazione Universale Multi-Tag.")
        self.log("⚙️ Connessione al Database...")

        conn = sqlite3.connect(self.db_path.get(), check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA temp_store = MEMORY;")

        cursor.execute("""CREATE TABLE IF NOT EXISTS misurazioni
                          (
                              id
                              INTEGER
                              PRIMARY
                              KEY
                              AUTOINCREMENT,
                              file_pdf
                              TEXT,
                              cartella_padre
                              TEXT,
                              codice_pezzo
                              TEXT,
                              lotto
                              TEXT,
                              sezione
                              TEXT,
                              nome_misura
                              TEXT,
                              misurato_mm
                              REAL,
                              nominale_mm
                              REAL,
                              tolleranza_piu
                              REAL,
                              tolleranza_meno
                              REAL,
                              deviazione
                              REAL,
                              extra_dev
                              REAL,
                              stato
                              TEXT,
                              fase
                              TEXT
                              DEFAULT
                              ''
                          )""")
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS registro_file (file_pdf TEXT PRIMARY KEY, data_elaborazione TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

        cursor.execute("PRAGMA table_info(misurazioni)")
        if 'fase' not in [col[1] for col in cursor.fetchall()]:
            cursor.execute("ALTER TABLE misurazioni ADD COLUMN fase TEXT DEFAULT ''")
            conn.commit()

        cursor.execute("SELECT file_pdf FROM registro_file")
        fatti = set(r[0] for r in cursor.fetchall())

        lista_lavori = []
        for p_ass, data in self.dati_cartelle.items():
            if data["check"] == CHECKED:
                fase_cartella = data.get("fase", "POST")
                for pdf_path in data["pdfs"]:
                    if str(pdf_path) not in fatti:
                        parts = pdf_path.stem.split('_')
                        if len(parts) >= 2:
                            codice = parts[0].upper()
                            lotto = data["lotto_forzato"] if data["lotto_forzato"] else parts[1].upper()
                            lista_lavori.append((str(pdf_path), codice, lotto, fase_cartella))
                        else:
                            self.log(f"⚠️ Ignorato file non conforme: {pdf_path.name}")

        if not lista_lavori:
            self.log("✅ Nessun nuovo file valido da estrarre.")
            self.root.after(0, self.reset_ui)
            return

        totale_lavori = len(lista_lavori)
        self.log(f"🎯 Pronti {totale_lavori} file per l'estrazione.")

        start_t = time.time()
        file_p, misure_s = 0, 0

        # Worker per estrazione parallela
        with ProcessPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(worker_estrazione_misure, job): job for job in lista_lavori}
            for f in as_completed(futs):

                if self.stop_flag.is_set():
                    for future in futs:
                        future.cancel()
                    break

                file_p += 1
                res = f.result()
                if "data" in res and res["data"]:
                    cursor.executemany(
                        "INSERT INTO misurazioni (file_pdf, cartella_padre, codice_pezzo, lotto, sezione, nome_misura, misurato_mm, nominale_mm, tolleranza_piu, tolleranza_meno, deviazione, extra_dev, stato, fase) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        res["data"])
                    cursor.execute("INSERT OR IGNORE INTO registro_file (file_pdf) VALUES (?)", (res["file_path"],))
                    misure_s += len(res["data"])

                if file_p % 20 == 0:
                    conn.commit()
                    self.update_dash(file_p, totale_lavori, start_t)

        conn.commit()
        conn.close()

        tempo_totale = time.time() - start_t
        m_tot, s_tot = divmod(int(tempo_totale), 60)

        if self.stop_flag.is_set():
            self.log("🛑 Estrazione fermata in sicurezza. Chiusura app tra 2 secondi...")
            self.root.after(2000, self.root.destroy)
        else:
            self.log(f"🏁 FINITO IN {tempo_totale:.1f} SECONDI")
            self.log(f"📄 File processati: {file_p} | Misure: {misure_s}")
            # FIX: Aggiunto parent=self.root
            self.root.after(0, lambda: messagebox.showinfo("Completato",
                                                           f"Estrazione DB completata!\n\nMisure aggiunte: {misure_s}",
                                                           parent=self.root))
            self.root.after(0, self.reset_ui)


if __name__ == "__main__":
    try:
        # Aggiunta ID per Windows Taskbar
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Calypso.Extractor.Macro")
    except Exception:
        pass

    multiprocessing.freeze_support()
    root = tk.Tk()
    app = UniversalExtractorApp(root)
    root.mainloop()