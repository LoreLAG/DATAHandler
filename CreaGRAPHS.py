import sqlite3
import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import matplotlib
import re
import ctypes
import threading

matplotlib.use("TkAgg")
import seaborn as sns

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


# ──────────────────────────────────────────────────────────────────────────────
#  Helper – lettura deroga e Ordinamento Naturale
# ──────────────────────────────────────────────────────────────────────────────
def _parse_deroga(entry_widget: ttk.Entry) -> float:
    try:
        return max(0.0, float(entry_widget.get().strip()))
    except ValueError:
        return 0.0


def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]


class DataAnalyzerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Analizzatore Statistico Misure (PRE vs POST) - Pro Edition")
        self.root.geometry("1400x850")
        self.root.minsize(1000, 700)
        self.root.configure(bg="#ecf0f1")

        try:
            self.root.state('zoomed')
        except tk.TclError:
            self.root.attributes('-zoomed', True)

        self.db_path = tk.StringVar()

        # --- NUOVO MOTORE DATI IN MEMORIA (Pandas) ---
        self.df_completo = pd.DataFrame()

        self._debounce_id: dict[str, str | None] = {"A": None, "B": None}
        self._last_fig: Figure | None = None
        self._lockable_widgets: list = []

        self._setup_ui()

    # ══════════════════════════════════════════════════════════════════════════
    #  Costruzione UI
    # ══════════════════════════════════════════════════════════════════════════
    def _setup_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Treeview", rowheight=25, font=("Arial", 10))
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"), background="#bdc3c7")

        # ── Top: selezione DB (Dark Header) ──────────────────────────────────
        frame_top = tk.Frame(self.root, pady=15, padx=20, bg="#1c2833")
        frame_top.pack(fill="x", side="top")

        tk.Label(frame_top, text="📊 1. Database Analisi:", font=("Arial", 12, "bold"),
                 bg="#1c2833", fg="white").pack(side="left")
        tk.Entry(frame_top, textvariable=self.db_path, state="readonly", font=("Arial", 10),
                 width=65).pack(side="left", padx=15)

        self._btn_sfoglia = tk.Button(frame_top, text="📂 Sfoglia DB...",
                                      command=self._carica_db, bg="#3498db", fg="white", font=("Arial", 10, "bold"),
                                      bd=0, padx=15, pady=4)
        self._btn_sfoglia.pack(side="left")

        # ── Body principale ───────────────────────────────────────────────────
        paned_main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned_main.pack(fill="both", expand=True, padx=15, pady=15)

        # ── Sinistra: dashboard lotti ─────────────────────────────────────────
        frame_dash = tk.LabelFrame(paned_main, text=" Lotti Completi (PRE + POST) ", font=("Arial", 10, "bold"),
                                   bg="#ecf0f1", padx=8, pady=8)
        paned_main.add(frame_dash, weight=1)

        tk.Label(frame_dash, text="Doppio clic per autocompilare", font=("Arial", 9, "italic"), bg="#ecf0f1",
                 fg="#7f8c8d").pack(
            anchor="w", pady=(0, 5))

        self.tree_completi = ttk.Treeview(frame_dash, columns=("codice", "lotto"), show="headings", selectmode="browse")
        self.tree_completi.heading("codice", text="Codice Pezzo")
        self.tree_completi.heading("lotto", text="Lotto")
        self.tree_completi.column("codice", width=120, anchor="center")
        self.tree_completi.column("lotto", width=120, anchor="center")

        sb = ttk.Scrollbar(frame_dash, orient="vertical", command=self.tree_completi.yview)
        self.tree_completi.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree_completi.pack(fill="both", expand=True)
        self.tree_completi.bind("<Double-1>", self._on_doppio_clic_dashboard)

        # ── Destra: motore di confronto ───────────────────────────────────────
        frame_compare = tk.Frame(paned_main, bg="#ecf0f1")
        paned_main.add(frame_compare, weight=4)

        paned_confronto = ttk.PanedWindow(frame_compare, orient=tk.HORIZONTAL)
        paned_confronto.pack(fill="both", expand=True, pady=(0, 8))

        self.frame_A = tk.LabelFrame(paned_confronto, text=" SET A (Riferimento) ", font=("Arial", 10, "bold"), padx=15,
                                     pady=10, bg="#d6eaf8")
        paned_confronto.add(self.frame_A, weight=1)
        self.ui_set_A = self._crea_pannello(self.frame_A, "A")

        self.frame_B = tk.LabelFrame(paned_confronto, text=" SET B (Confronto) ", font=("Arial", 10, "bold"), padx=15,
                                     pady=10, bg="#d5f5e3")
        paned_confronto.add(self.frame_B, weight=1)
        self.ui_set_B = self._crea_pannello(self.frame_B, "B")

        # ── Pannello coppie ───────────────────────────────────────────────────
        frame_coppie = tk.LabelFrame(frame_compare, text=" Misure da Analizzare ", font=("Arial", 10, "bold"),
                                     bg="#ecf0f1", padx=10, pady=10)
        frame_coppie.pack(fill="both", expand=True, pady=8)

        btn_row = tk.Frame(frame_coppie, bg="#ecf0f1")
        btn_row.pack(fill="x", pady=(0, 8))

        self._btn_aggiungi = tk.Button(btn_row, text="⬇ Aggiungi Misura", font=("Arial", 10, "bold"), bd=0, padx=15,
                                       pady=4,
                                       bg="#3498db", fg="white", command=self._aggiungi_coppia)
        self._btn_aggiungi.pack(side="left", padx=(0, 10))

        self._btn_rimuovi = tk.Button(btn_row, text="🗑 Rimuovi Selezionate", font=("Arial", 10, "bold"), bd=0, padx=15,
                                      pady=4,
                                      bg="#e74c3c", fg="white", command=self._rimuovi_coppia)
        self._btn_rimuovi.pack(side="left")

        tk.Label(btn_row, text="💡 Doppio clic sulle liste sopra per aggiunta rapida.",
                 fg="#7f8c8d", bg="#ecf0f1", font=("Arial", 9, "italic")).pack(side="right")

        self.tree_coppie = ttk.Treeview(frame_coppie, columns=("misura_A", "misura_B"), show="headings",
                                        selectmode="extended", height=5)
        self.tree_coppie.heading("misura_A", text="Misura (SET A)")
        self.tree_coppie.heading("misura_B", text="Misura (SET B)")
        self.tree_coppie.column("misura_A", width=260, anchor="w")
        self.tree_coppie.column("misura_B", width=260, anchor="w")

        sb2 = ttk.Scrollbar(frame_coppie, orient="vertical", command=self.tree_coppie.yview)
        self.tree_coppie.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self.tree_coppie.pack(fill="both", expand=True)

        # ── Pulsantiera inferiore ─────────────────────────────────────────────
        frame_bottom = tk.Frame(frame_compare, pady=10, bg="#ecf0f1")
        frame_bottom.pack(fill="x")

        self._btn_pulisci = tk.Button(frame_bottom, text="🔄 PULISCI TUTTO", font=("Arial", 11, "bold"),
                                      bg="#f39c12", fg="white", height=2, width=18, bd=0, command=self._pulisci_tutto)
        self._btn_pulisci.pack(side="left", padx=(0, 10))

        self._btn_genera = tk.Button(frame_bottom, text="📈 GENERA GRAFICI", font=("Arial", 14, "bold"),
                                     bg="#8e44ad", fg="white", height=2, bd=0, command=self._avvia_genera_grafici)
        self._btn_genera.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self._btn_salva = tk.Button(frame_bottom, text="💾 SALVA IMMAGINE", font=("Arial", 11, "bold"),
                                    bg="#2c3e50", fg="white", height=2, width=18, bd=0, command=self._salva_grafici)
        self._btn_salva.pack(side="left")

        # ── Status bar con progressbar indeterminata ──────────────────────────
        frame_status = tk.Frame(self.root, bg="#bdc3c7", pady=4, padx=10)
        frame_status.pack(side="bottom", fill="x")
        self._status_var = tk.StringVar(value="Pronto.")
        tk.Label(frame_status, textvariable=self._status_var, bg="#bdc3c7", fg="#2c3e50",
                 anchor="w", font=("Arial", 9, "bold")).pack(side="left", fill="x", expand=True)
        self._progressbar = ttk.Progressbar(frame_status, mode="indeterminate", length=150)
        self._progressbar.pack(side="right")

        self._busy = False
        self._lockable_widgets = [
            self._btn_sfoglia,
            self._btn_aggiungi, self._btn_rimuovi,
            self._btn_pulisci, self._btn_genera, self._btn_salva,
            self.tree_completi, self.tree_coppie,
        ]
        for ui in (self.ui_set_A, self.ui_set_B):
            self._lockable_widgets += [
                ui["fase"], ui["codice"], ui["lotto"], ui["deroga"], ui["btn_pulisci"], ui["search"]
            ]

        self._listboxes = [self.ui_set_A["misure"], self.ui_set_B["misure"]]

    def _crea_pannello(self, parent: tk.LabelFrame, tag: str) -> dict:
        ui: dict = {}
        bg = parent["bg"]

        for label, key in [("Fase:", "fase"), ("Codice Pezzo:", "codice"), ("Lotto:", "lotto")]:
            tk.Label(parent, text=label, bg=bg, font=("Arial", 9, "bold")).pack(anchor="w")
            cb = ttk.Combobox(parent, state="normal")
            cb.pack(fill="x", pady=(0, 6))
            ui[key] = cb

        tk.Label(parent, text="Deroga simmetrica (mm):", bg=bg, font=("Arial", 9, "bold")).pack(anchor="w")
        deroga_entry = ttk.Entry(parent)
        deroga_entry.insert(0, "0.0")
        deroga_entry.pack(fill="x", pady=(0, 8))
        ui["deroga"] = deroga_entry

        tk.Label(parent, text="🔍 Cerca Misura:", bg=bg, font=("Arial", 9, "bold")).pack(anchor="w")
        search_var = tk.StringVar()
        search_entry = ttk.Entry(parent, textvariable=search_var)
        search_entry.pack(fill="x", pady=(0, 4))
        ui["search"] = search_entry
        ui["search_var"] = search_var
        ui["all_misure"] = []

        frame_list = tk.Frame(parent)
        frame_list.pack(fill="both", expand=True)
        lb = tk.Listbox(frame_list, selectmode="single", exportselection=False, font=("Arial", 10), bd=0)
        sb = ttk.Scrollbar(frame_list, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)
        ui["misure"] = lb

        btn_bg = "#2980b9" if tag == "A" else "#27ae60"
        btn_pulisci = tk.Button(parent, text=f"🧹 Svuota SET {tag}", font=("Arial", 9, "bold"), bd=0, bg=btn_bg,
                                fg="white", pady=4,
                                command=lambda t=tag: self._pulisci_pannello(t))
        btn_pulisci.pack(fill="x", pady=(8, 0))
        ui["btn_pulisci"] = btn_pulisci

        for field in ("fase", "codice", "lotto"):
            cb = ui[field]
            cb.bind("<<ComboboxSelected>>", lambda e, t=tag: self._schedule_update(t))
            cb.bind("<FocusOut>", lambda e, t=tag: self._schedule_update(t))
            cb.bind("<Return>", lambda e, t=tag: self._schedule_update(t))

        search_var.trace_add("write", lambda *args, t=tag: self._filtra_lista_misure(t))
        lb.bind("<Double-Button-1>", lambda e: self._aggiungi_coppia())

        return ui

    # ══════════════════════════════════════════════════════════════════════════
    #  Logica UI e Ricerca
    # ══════════════════════════════════════════════════════════════════════════
    def _filtra_lista_misure(self, tag: str):
        ui = self.ui_set_A if tag == "A" else self.ui_set_B
        testo = ui["search_var"].get().lower()

        ui["misure"].delete(0, tk.END)
        for m in ui["all_misure"]:
            if testo in m.lower():
                ui["misure"].insert(tk.END, m)

    def _lock_ui(self, status_msg: str):
        self._busy = True
        self._set_status(f"⏳  {status_msg}")
        self.root.config(cursor="watch")
        self._progressbar.start(12)
        for w in self._lockable_widgets:
            try:
                w.configure(state="disabled")
            except tk.TclError:
                pass
        for lb in self._listboxes:
            lb.configure(bg="#ECECEC", fg="#888888")

    def _unlock_ui(self, status_msg: str = "Pronto."):
        self._busy = False
        self.root.config(cursor="")
        self._progressbar.stop()
        for w in self._lockable_widgets:
            try:
                w.configure(state="normal")
            except tk.TclError:
                pass
        for lb in self._listboxes:
            lb.configure(bg="white", fg="black")
        self._set_status(status_msg)

    # ══════════════════════════════════════════════════════════════════════════
    #  Debounce & scheduling
    # ══════════════════════════════════════════════════════════════════════════
    def _schedule_update(self, tag: str, delay_ms: int = 200):
        if self._busy: return
        if self._debounce_id[tag]: self.root.after_cancel(self._debounce_id[tag])

        ui = self.ui_set_A if tag == "A" else self.ui_set_B
        f = ui["fase"].get().strip().upper()
        c = ui["codice"].get().strip().upper()
        l = ui["lotto"].get().strip().upper()

        self._debounce_id[tag] = self.root.after(
            delay_ms, lambda: self._aggiorna_dinamico_thread(tag, f, c, l))

    # ══════════════════════════════════════════════════════════════════════════
    #  Aggiornamento filtri (IN MEMORIA CON PANDAS)
    # ══════════════════════════════════════════════════════════════════════════
    def _aggiorna_dinamico_thread(self, tag: str, f: str, c: str, l: str):
        self._lock_ui("Aggiornamento filtri…")
        threading.Thread(target=self._aggiorna_dinamico_worker, args=(tag, f, c, l), daemon=True).start()

    def _aggiorna_dinamico_worker(self, tag: str, f: str, c: str, l: str):
        if self.df_completo.empty: return
        try:
            def fetch_valid(campo: str, filtri: dict) -> list[str]:
                temp_df = self.df_completo
                for col, val in filtri.items():
                    if val:
                        temp_df = temp_df[temp_df[col].astype(str).str.upper() == val]
                result = temp_df[campo].unique().tolist()
                return sorted([str(r) for r in result if r], key=natural_sort_key)

            valid_f = fetch_valid("fase", {"codice_pezzo": c, "lotto": l})
            valid_c = fetch_valid("codice_pezzo", {"fase": f, "lotto": l})
            valid_l = fetch_valid("lotto", {"fase": f, "codice_pezzo": c})

            f2 = f if f in valid_f else ""
            c2 = c if c in valid_c else ""
            l2 = l if l in valid_l else ""

            if not f2 and len(valid_f) == 1: f2 = valid_f[0]
            if not c2 and len(valid_c) == 1: c2 = valid_c[0]
            if not l2 and len(valid_l) == 1: l2 = valid_l[0]

            misure: list[str] = []
            if f2 and c2 and l2:
                # Estrazione veloce con Pandas
                df_filtrato = self.df_completo[
                    (self.df_completo['codice_pezzo'].astype(str).str.upper() == c2) &
                    (self.df_completo['lotto'].astype(str).str.upper() == l2) &
                    (self.df_completo['fase'].astype(str).str.upper() == f2)
                    ]
                misure_grezze = df_filtrato["nome_misura"].unique().tolist()
                misure = sorted([str(m) for m in misure_grezze if m], key=natural_sort_key)

            self.root.after(0, lambda: self._aggiorna_ui(tag, valid_f, valid_c, valid_l, f2, c2, l2, misure))
        except Exception as exc:
            self.root.after(0, lambda: self._unlock_ui(f"Errore filtri: {exc}"))

    def _aggiorna_ui(self, tag: str, valid_f, valid_c, valid_l, f: str, c: str, l: str, misure: list[str]):
        ui = self.ui_set_A if tag == "A" else self.ui_set_B
        ui["fase"]["values"] = valid_f
        ui["codice"]["values"] = valid_c
        ui["lotto"]["values"] = valid_l
        ui["fase"].set(f)
        ui["codice"].set(c)
        ui["lotto"].set(l)

        ui["all_misure"] = misure
        self._filtra_lista_misure(tag)

        if tag == "A" and f and c and l:
            self._auto_fill_B(f, c, l)
        else:
            self._unlock_ui()

    def _auto_fill_B(self, fase_A: str, codice_A: str, lotto_A: str):
        mapping = {"PRE": "POST", "POST": "PRE"}
        fase_B = mapping.get(fase_A, "")
        if fase_B: self.ui_set_B["fase"].set(fase_B)
        self.ui_set_B["codice"].set(codice_A)
        self.ui_set_B["lotto"].set(lotto_A)

        if self._debounce_id["B"]: self.root.after_cancel(self._debounce_id["B"])

        f = self.ui_set_B["fase"].get().strip().upper()
        c = self.ui_set_B["codice"].get().strip().upper()
        l = self.ui_set_B["lotto"].get().strip().upper()
        self._debounce_id["B"] = self.root.after(50, lambda: self._aggiorna_dinamico_thread("B", f, c, l))

    # ══════════════════════════════════════════════════════════════════════════
    #  Caricamento Database IN MEMORIA
    # ══════════════════════════════════════════════════════════════════════════
    def _carica_db(self):
        p = filedialog.askopenfilename(
            parent=self.root,
            title="Seleziona database SQLite",
            filetypes=[("Database SQLite", "*.db"), ("Tutti i file", "*.*")]
        )
        if not p: return

        self.db_path.set(p)
        self._last_fig = None
        self._lock_ui("Caricamento DB in memoria (Pandas) in corso…")

        threading.Thread(target=self._carica_db_worker, args=(p,), daemon=True).start()

    def _carica_db_worker(self, path):
        try:
            conn = sqlite3.connect(path)
            self.df_completo = pd.read_sql_query("SELECT * FROM misurazioni", conn)
            conn.close()

            # Ottimizzazione stringhe per velocizzare le query in memoria
            self.df_completo = self.df_completo.fillna("")
            for col in ['codice_pezzo', 'lotto', 'fase', 'nome_misura']:
                if col in self.df_completo.columns:
                    self.df_completo[col] = self.df_completo[col].astype(str).str.strip()

            self._popola_cruscotto_worker()
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("Errore DB", str(exc), parent=self.root))
            self.root.after(0, lambda: self._unlock_ui("Errore caricamento database."))

    def _popola_cruscotto_worker(self):
        try:
            df = self.df_completo
            if 'codice_pezzo' not in df.columns or 'lotto' not in df.columns or 'fase' not in df.columns:
                self.root.after(0, lambda: self._popola_cruscotto_ui([]))
                return

            # Cerca rapidamente i Lotti che hanno SIA fase PRE che POST usando crosstab
            cross = pd.crosstab([df['codice_pezzo'], df['lotto']], df['fase'])
            if 'PRE' in cross.columns and 'POST' in cross.columns:
                valid_pairs = cross[(cross['PRE'] > 0) & (cross['POST'] > 0)].index.tolist()
            else:
                valid_pairs = []

            rows = sorted(valid_pairs, key=lambda x: (natural_sort_key(x[0]), natural_sort_key(x[1])))
            self.root.after(0, lambda: self._popola_cruscotto_ui(rows))

        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("Errore DB", str(exc), parent=self.root))
            self.root.after(0, lambda: self._unlock_ui("Errore elaborazione cruscotto."))

    def _popola_cruscotto_ui(self, rows: list[tuple]):
        self.tree_completi.delete(*self.tree_completi.get_children())
        for codice, lotto in rows:
            self.tree_completi.insert("", tk.END, values=(codice, lotto))
        self._unlock_ui("Database caricato in memoria con successo.")
        self._schedule_update("A")
        self._schedule_update("B")

    # ══════════════════════════════════════════════════════════════════════════
    #  Azioni UI
    # ══════════════════════════════════════════════════════════════════════════
    def _on_doppio_clic_dashboard(self, _event):
        if self._busy: return
        sel = self.tree_completi.selection()
        if not sel: return
        codice, lotto = self.tree_completi.item(sel[0], "values")
        self.ui_set_A["fase"].set("PRE")
        self.ui_set_A["codice"].set(codice)
        self.ui_set_A["lotto"].set(lotto)
        self._schedule_update("A", delay_ms=50)

    def _pulisci_pannello(self, tag: str):
        if self._debounce_id[tag]:
            self.root.after_cancel(self._debounce_id[tag])
            self._debounce_id[tag] = None

        ui = self.ui_set_A if tag == "A" else self.ui_set_B
        ui["fase"].set("")
        ui["codice"].set("")
        ui["lotto"].set("")
        ui["deroga"].delete(0, tk.END)
        ui["deroga"].insert(0, "0.0")
        ui["search_var"].set("")
        ui["all_misure"] = []
        ui["misure"].delete(0, tk.END)
        for field in ("fase", "codice", "lotto"):
            ui[field]["values"] = []

        if not self.df_completo.empty:
            self._schedule_update(tag)

    def _pulisci_tutto(self):
        self._pulisci_pannello("A")
        self._pulisci_pannello("B")
        self._last_fig = None
        self.tree_coppie.delete(*self.tree_coppie.get_children())

    def _aggiungi_coppia(self):
        sel_A = self.ui_set_A["misure"].curselection()
        sel_B = self.ui_set_B["misure"].curselection()

        if not sel_A and not sel_B:
            return

        m_A = self.ui_set_A["misure"].get(sel_A[0]) if sel_A else "-"
        m_B = self.ui_set_B["misure"].get(sel_B[0]) if sel_B else "-"

        for item in self.tree_coppie.get_children():
            if self.tree_coppie.item(item, "values") == (m_A, m_B): return

        self.tree_coppie.insert("", tk.END, values=(m_A, m_B))

        if sel_A: self.ui_set_A["misure"].selection_clear(sel_A[0])
        if sel_B: self.ui_set_B["misure"].selection_clear(sel_B[0])

    def _rimuovi_coppia(self):
        for item in self.tree_coppie.selection(): self.tree_coppie.delete(item)

    # ══════════════════════════════════════════════════════════════════════════
    #  Generazione grafici (IN MEMORIA CON PANDAS)
    # ══════════════════════════════════════════════════════════════════════════
    def _avvia_genera_grafici(self):
        if self.df_completo.empty:
            messagebox.showwarning("DB mancante", "Carica prima un database.", parent=self.root)
            return
        items = self.tree_coppie.get_children()
        if not items:
            messagebox.showwarning("Nessuna misura", "Aggiungi almeno una misura/coppia.", parent=self.root)
            return

        pair_list = [tuple(self.tree_coppie.item(i, "values")) for i in items]
        cod_A, lot_A, fas_A = (self.ui_set_A["codice"].get().strip().upper(),
                               self.ui_set_A["lotto"].get().strip().upper(),
                               self.ui_set_A["fase"].get().strip().upper())
        cod_B, lot_B, fas_B = (self.ui_set_B["codice"].get().strip().upper(),
                               self.ui_set_B["lotto"].get().strip().upper(),
                               self.ui_set_B["fase"].get().strip().upper())
        deroga_A = _parse_deroga(self.ui_set_A["deroga"])
        deroga_B = _parse_deroga(self.ui_set_B["deroga"])

        self._lock_ui("Generazione grafici in corso…")
        threading.Thread(
            target=self._genera_grafici_worker,
            args=(pair_list, cod_A, lot_A, fas_A, cod_B, lot_B, fas_B, deroga_A, deroga_B),
            daemon=True
        ).start()

    def _genera_grafici_worker(self, pair_list: list[tuple], cod_A: str, lot_A: str, fas_A: str, cod_B: str, lot_B: str,
                               fas_B: str, deroga_A: float, deroga_B: float):
        try:
            valid_A = [m for m, _ in pair_list if m != "-"]
            valid_B = [m for _, m in pair_list if m != "-"]

            # Estrazione Pandas super veloce
            df_all_A = self.df_completo[
                (self.df_completo['codice_pezzo'].astype(str).str.upper() == cod_A) &
                (self.df_completo['lotto'].astype(str).str.upper() == lot_A) &
                (self.df_completo['fase'].astype(str).str.upper() == fas_A) &
                (self.df_completo['nome_misura'].isin(valid_A))
                ].copy()

            df_all_B = self.df_completo[
                (self.df_completo['codice_pezzo'].astype(str).str.upper() == cod_B) &
                (self.df_completo['lotto'].astype(str).str.upper() == lot_B) &
                (self.df_completo['fase'].astype(str).str.upper() == fas_B) &
                (self.df_completo['nome_misura'].isin(valid_B))
                ].copy()

            # Pulisce i dati e assicura che i valori siano numerici
            df_all_A['misurato_mm'] = pd.to_numeric(df_all_A['misurato_mm'], errors='coerce')
            df_all_A = df_all_A.dropna(subset=['misurato_mm'])

            df_all_B['misurato_mm'] = pd.to_numeric(df_all_B['misurato_mm'], errors='coerce')
            df_all_B = df_all_B.dropna(subset=['misurato_mm'])

            n = len(pair_list)
            ncols = 2 if n > 1 else 1
            nrows = (n + ncols - 1) // ncols

            sns.set_theme(style="whitegrid")

            fig = Figure(figsize=(ncols * 7.5, nrows * 5), facecolor="#F8F8F8")
            axes = fig.subplots(nrows, ncols)

            if n == 1:
                axes_flat = [axes]
            elif nrows == 1:
                axes_flat = list(axes)
            else:
                axes_flat = list(axes.flatten())

            for idx, (m_A, m_B) in enumerate(pair_list):
                ax = axes_flat[idx]

                df_A = df_all_A[df_all_A["nome_misura"] == m_A] if m_A != "-" else pd.DataFrame()
                df_B = df_all_B[df_all_B["nome_misura"] == m_B] if m_B != "-" else pd.DataFrame()

                if not df_A.empty:
                    sns.histplot(df_A["misurato_mm"], color="#3498db", label=f"A · {fas_A} · n={len(df_A)}",
                                 kde=True, stat="density", linewidth=0, alpha=0.4, ax=ax, kde_kws={'gridsize': 100})
                    self._disegna_tolleranza(ax, df_A, deroga_A, color="#2980b9", label_prefix="A", line_style="--")

                if not df_B.empty:
                    sns.histplot(df_B["misurato_mm"], color="#27ae60", label=f"B · {fas_B} · n={len(df_B)}",
                                 kde=True, stat="density", linewidth=0, alpha=0.4, ax=ax, kde_kws={'gridsize': 100})
                    self._disegna_tolleranza(ax, df_B, deroga_B, color="#229954", label_prefix="B", line_style="-.")

                if m_A != "-" and m_B != "-":
                    ax_title = f"{m_A}  ↔  {m_B}"
                elif m_A != "-":
                    ax_title = m_A
                else:
                    ax_title = m_B

                ax.set_title(ax_title, fontsize=10, fontweight="bold")
                ax.set_xlabel("Misura (mm)", fontsize=9)
                ax.set_ylabel("Densità", fontsize=9)
                ax.legend(fontsize=7.5, loc="best")

            for i in range(n, len(axes_flat)): axes_flat[i].set_visible(False)

            title_parts = []
            if valid_A: title_parts.append(f"A: {cod_A} · {lot_A} · {fas_A}")
            if valid_B: title_parts.append(f"B: {cod_B} · {lot_B} · {fas_B}")

            deroga_parts = []
            if deroga_A and valid_A: deroga_parts.append(f"A={deroga_A:+.3f} mm")
            if deroga_B and valid_B: deroga_parts.append(f"B={deroga_B:+.3f} mm")
            if deroga_parts: title_parts.append("Deroga  " + "   ".join(deroga_parts))

            fig.suptitle("   |   ".join(title_parts), fontsize=14, fontweight="bold")
            fig.tight_layout(rect=[0, 0, 1, 0.95], h_pad=3.0)

            self._last_fig = fig
            self.root.after(0, lambda: self._mostra_grafici(fig))

        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            self.root.after(0, lambda: messagebox.showerror("Errore Grafici", f"{exc}\n\n{tb}", parent=self.root))
            self.root.after(0, lambda: self._unlock_ui("Errore durante la generazione."))

    @staticmethod
    def _disegna_tolleranza(ax, df: pd.DataFrame, deroga: float, color: str, label_prefix: str, line_style: str):
        if df.empty: return
        row0 = df.iloc[0]

        # Casting robusto usando pd.to_numeric per evitare errori con stringhe
        nom = pd.to_numeric(row0["nominale_mm"], errors='coerce')
        tp = pd.to_numeric(row0["tolleranza_piu"], errors='coerce')
        tm = pd.to_numeric(row0["tolleranza_meno"], errors='coerce')

        if pd.isna(nom): return

        ax.axvline(nom, color=color, linestyle=line_style, linewidth=1.4, label=f"Nom.{label_prefix} {nom:.3f}")

        if pd.notna(tp) and pd.notna(tm):
            lsl = nom + tm - deroga
            usl = nom + tp + deroga
            ax.axvspan(lsl, usl, color=color, alpha=0.07, label=f"Tol.{label_prefix} [{lsl:.3f} … {usl:.3f}]")
            ax.axvline(lsl, color=color, linestyle=":", linewidth=0.9)
            ax.axvline(usl, color=color, linestyle=":", linewidth=0.9)

    def _mostra_grafici(self, fig: Figure):
        win_grafici = tk.Toplevel(self.root)
        win_grafici.title("Grafici di Confronto - Analisi")
        win_grafici.geometry("1200x800")
        try:
            win_grafici.state('zoomed')
        except tk.TclError:
            win_grafici.attributes('-zoomed', True)

        canvas = FigureCanvasTkAgg(fig, master=win_grafici)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

        toolbar = NavigationToolbar2Tk(canvas, win_grafici)
        toolbar.update()
        canvas.get_tk_widget().pack(fill="both", expand=True)

        self._unlock_ui("Grafici mostrati con successo.")

    # ══════════════════════════════════════════════════════════════════════════
    #  Salvataggio
    # ══════════════════════════════════════════════════════════════════════════
    def _salva_grafici(self):
        if self._last_fig is None:
            messagebox.showwarning("Nessun grafico", "Genera prima i grafici con 📊.", parent=self.root)
            return

        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Salva Grafici Come…",
            defaultextension=".png",
            filetypes=[("PNG ad alta risoluzione", "*.png"), ("PDF vettoriale", "*.pdf"), ("SVG vettoriale", "*.svg"),
                       ("JPEG", "*.jpg")]
        )
        if not path: return

        fig = self._last_fig
        self._lock_ui("Salvataggio in corso…")
        threading.Thread(target=self._salva_worker, args=(fig, path), daemon=True).start()

    def _salva_worker(self, fig: Figure, path: str):
        try:
            fig.savefig(path, dpi=200, bbox_inches="tight")
            self.root.after(0, lambda: self._unlock_ui(f"Salvato: {path}"))
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("Errore salvataggio", str(exc), parent=self.root))
            self.root.after(0, lambda: self._unlock_ui("Errore nel salvataggio."))

    def _set_status(self, msg: str):
        self.root.after(0, lambda: self._status_var.set(msg))


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Calypso.Graphs.Pro")
    except Exception:
        pass

    root = tk.Tk()
    app = DataAnalyzerApp(root)
    root.mainloop()