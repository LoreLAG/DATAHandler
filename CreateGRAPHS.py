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
#  Helper – allowance parsing and Natural Sorting
# ──────────────────────────────────────────────────────────────────────────────
def _parse_allowance(entry_widget: ttk.Entry) -> float:
    try:
        return max(0.0, float(entry_widget.get().strip()))
    except ValueError:
        return 0.0


def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]


class DataAnalyzerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Statistical Measurement Analyzer (PRE vs POST) - Pro Edition")
        self.root.geometry("1400x850")
        self.root.minsize(1000, 700)
        self.root.configure(bg="#ecf0f1")

        try:
            self.root.state('zoomed')
        except tk.TclError:
            self.root.attributes('-zoomed', True)

        self.db_path = tk.StringVar()

        # --- NEW IN-MEMORY DATA ENGINE (Pandas) ---
        self.df_complete = pd.DataFrame()

        self._debounce_id: dict[str, str | None] = {"A": None, "B": None}
        self._last_fig: Figure | None = None
        self._lockable_widgets: list = []

        self._setup_ui()

    # ══════════════════════════════════════════════════════════════════════════
    #  UI Construction
    # ══════════════════════════════════════════════════════════════════════════
    def _setup_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Treeview", rowheight=25, font=("Arial", 10))
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"), background="#bdc3c7")

        # ── Top: DB selection (Dark Header) ──────────────────────────────────
        frame_top = tk.Frame(self.root, pady=15, padx=20, bg="#1c2833")
        frame_top.pack(fill="x", side="top")

        tk.Label(frame_top, text="📊 1. Analysis Database:", font=("Arial", 12, "bold"),
                 bg="#1c2833", fg="white").pack(side="left")
        tk.Entry(frame_top, textvariable=self.db_path, state="readonly", font=("Arial", 10),
                 width=65).pack(side="left", padx=15)

        self._btn_browse = tk.Button(frame_top, text="📂 Browse DB...",
                                      command=self._load_db, bg="#3498db", fg="white", font=("Arial", 10, "bold"),
                                      bd=0, padx=15, pady=4)
        self._btn_browse.pack(side="left")

        # ── Main body ───────────────────────────────────────────────────────────
        paned_main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned_main.pack(fill="both", expand=True, padx=15, pady=15)

        # ── Left: batches dashboard ─────────────────────────────────────────
        frame_dash = tk.LabelFrame(paned_main, text=" Complete Batches (PRE + POST) ", font=("Arial", 10, "bold"),
                                   bg="#ecf0f1", padx=8, pady=8)
        paned_main.add(frame_dash, weight=1)

        tk.Label(frame_dash, text="Double click to autofill", font=("Arial", 9, "italic"), bg="#ecf0f1",
                 fg="#7f8c8d").pack(
            anchor="w", pady=(0, 5))

        self.tree_complete = ttk.Treeview(frame_dash, columns=("code", "batch"), show="headings", selectmode="browse")
        self.tree_complete.heading("code", text="Part Code")
        self.tree_complete.heading("batch", text="Batch")
        self.tree_complete.column("code", width=120, anchor="center")
        self.tree_complete.column("batch", width=120, anchor="center")

        sb = ttk.Scrollbar(frame_dash, orient="vertical", command=self.tree_complete.yview)
        self.tree_complete.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree_complete.pack(fill="both", expand=True)
        self.tree_complete.bind("<Double-1>", self._on_double_click_dashboard)

        # ── Right: comparison engine ───────────────────────────────────────
        frame_compare = tk.Frame(paned_main, bg="#ecf0f1")
        paned_main.add(frame_compare, weight=4)

        paned_compare = ttk.PanedWindow(frame_compare, orient=tk.HORIZONTAL)
        paned_compare.pack(fill="both", expand=True, pady=(0, 8))

        self.frame_A = tk.LabelFrame(paned_compare, text=" SET A (Reference) ", font=("Arial", 10, "bold"), padx=15,
                                     pady=10, bg="#d6eaf8")
        paned_compare.add(self.frame_A, weight=1)
        self.ui_set_A = self._create_panel(self.frame_A, "A")

        self.frame_B = tk.LabelFrame(paned_compare, text=" SET B (Comparison) ", font=("Arial", 10, "bold"), padx=15,
                                     pady=10, bg="#d5f5e3")
        paned_compare.add(self.frame_B, weight=1)
        self.ui_set_B = self._create_panel(self.frame_B, "B")

        # ── Pairs panel ───────────────────────────────────────────────────
        frame_pairs = tk.LabelFrame(frame_compare, text=" Measures to Analyze ", font=("Arial", 10, "bold"),
                                     bg="#ecf0f1", padx=10, pady=10)
        frame_pairs.pack(fill="both", expand=True, pady=8)

        btn_row = tk.Frame(frame_pairs, bg="#ecf0f1")
        btn_row.pack(fill="x", pady=(0, 8))

        self._btn_add = tk.Button(btn_row, text="⬇ Add Measure", font=("Arial", 10, "bold"), bd=0, padx=15,
                                       pady=4,
                                       bg="#3498db", fg="white", command=self._add_pair)
        self._btn_add.pack(side="left", padx=(0, 10))

        self._btn_remove = tk.Button(btn_row, text="🗑 Remove Selected", font=("Arial", 10, "bold"), bd=0, padx=15,
                                      pady=4,
                                      bg="#e74c3c", fg="white", command=self._remove_pair)
        self._btn_remove.pack(side="left")

        tk.Label(btn_row, text="💡 Double click on the lists above to quick add.",
                 fg="#7f8c8d", bg="#ecf0f1", font=("Arial", 9, "italic")).pack(side="right")

        self.tree_pairs = ttk.Treeview(frame_pairs, columns=("measure_A", "measure_B"), show="headings",
                                        selectmode="extended", height=5)
        self.tree_pairs.heading("measure_A", text="Measure (SET A)")
        self.tree_pairs.heading("measure_B", text="Measure (SET B)")
        self.tree_pairs.column("measure_A", width=260, anchor="w")
        self.tree_pairs.column("measure_B", width=260, anchor="w")

        sb2 = ttk.Scrollbar(frame_pairs, orient="vertical", command=self.tree_pairs.yview)
        self.tree_pairs.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self.tree_pairs.pack(fill="both", expand=True)

        # ── Bottom buttons panel ─────────────────────────────────────────────
        frame_bottom = tk.Frame(frame_compare, pady=10, bg="#ecf0f1")
        frame_bottom.pack(fill="x")

        self._btn_clear = tk.Button(frame_bottom, text="🔄 CLEAR ALL", font=("Arial", 11, "bold"),
                                      bg="#f39c12", fg="white", height=2, width=18, bd=0, command=self._clear_all)
        self._btn_clear.pack(side="left", padx=(0, 10))

        self._btn_generate = tk.Button(frame_bottom, text="📈 GENERATE GRAPHS", font=("Arial", 14, "bold"),
                                     bg="#8e44ad", fg="white", height=2, bd=0, command=self._start_generate_graphs)
        self._btn_generate.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self._btn_save = tk.Button(frame_bottom, text="💾 SAVE IMAGE", font=("Arial", 11, "bold"),
                                    bg="#2c3e50", fg="white", height=2, width=18, bd=0, command=self._save_graphs)
        self._btn_save.pack(side="left")

        # ── Status bar with indeterminate progressbar ──────────────────────────
        frame_status = tk.Frame(self.root, bg="#bdc3c7", pady=4, padx=10)
        frame_status.pack(side="bottom", fill="x")
        self._status_var = tk.StringVar(value="Ready.")
        tk.Label(frame_status, textvariable=self._status_var, bg="#bdc3c7", fg="#2c3e50",
                 anchor="w", font=("Arial", 9, "bold")).pack(side="left", fill="x", expand=True)
        self._progressbar = ttk.Progressbar(frame_status, mode="indeterminate", length=150)
        self._progressbar.pack(side="right")

        self._busy = False
        self._lockable_widgets = [
            self._btn_browse,
            self._btn_add, self._btn_remove,
            self._btn_clear, self._btn_generate, self._btn_save,
            self.tree_complete, self.tree_pairs,
        ]
        for ui in (self.ui_set_A, self.ui_set_B):
            self._lockable_widgets += [
                ui["phase"], ui["code"], ui["batch"], ui["allowance"], ui["btn_clear"], ui["search"]
            ]

        self._listboxes = [self.ui_set_A["measures"], self.ui_set_B["measures"]]

    def _create_panel(self, parent: tk.LabelFrame, tag: str) -> dict:
        ui: dict = {}
        bg = parent["bg"]

        for label, key in [("Phase:", "phase"), ("Part Code:", "code"), ("Batch:", "batch")]:
            tk.Label(parent, text=label, bg=bg, font=("Arial", 9, "bold")).pack(anchor="w")
            cb = ttk.Combobox(parent, state="normal")
            cb.pack(fill="x", pady=(0, 6))
            ui[key] = cb

        tk.Label(parent, text="Symmetrical Allowance (mm):", bg=bg, font=("Arial", 9, "bold")).pack(anchor="w")
        allowance_entry = ttk.Entry(parent)
        allowance_entry.insert(0, "0.0")
        allowance_entry.pack(fill="x", pady=(0, 8))
        ui["allowance"] = allowance_entry

        tk.Label(parent, text="🔍 Search Measure:", bg=bg, font=("Arial", 9, "bold")).pack(anchor="w")
        search_var = tk.StringVar()
        search_entry = ttk.Entry(parent, textvariable=search_var)
        search_entry.pack(fill="x", pady=(0, 4))
        ui["search"] = search_entry
        ui["search_var"] = search_var
        ui["all_measures"] = []

        frame_list = tk.Frame(parent)
        frame_list.pack(fill="both", expand=True)
        lb = tk.Listbox(frame_list, selectmode="single", exportselection=False, font=("Arial", 10), bd=0)
        sb = ttk.Scrollbar(frame_list, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)
        ui["measures"] = lb

        btn_bg = "#2980b9" if tag == "A" else "#27ae60"
        btn_clear = tk.Button(parent, text=f"🧹 Clear SET {tag}", font=("Arial", 9, "bold"), bd=0, bg=btn_bg,
                                fg="white", pady=4,
                                command=lambda t=tag: self._clear_panel(t))
        btn_clear.pack(fill="x", pady=(8, 0))
        ui["btn_clear"] = btn_clear

        for field in ("phase", "code", "batch"):
            cb = ui[field]
            cb.bind("<<ComboboxSelected>>", lambda e, t=tag: self._schedule_update(t))
            cb.bind("<FocusOut>", lambda e, t=tag: self._schedule_update(t))
            cb.bind("<Return>", lambda e, t=tag: self._schedule_update(t))

        search_var.trace_add("write", lambda *args, t=tag: self._filter_measures_list(t))
        lb.bind("<Double-Button-1>", lambda e: self._add_pair())

        return ui

    # ══════════════════════════════════════════════════════════════════════════
    #  UI Logic and Search
    # ══════════════════════════════════════════════════════════════════════════
    def _filter_measures_list(self, tag: str):
        ui = self.ui_set_A if tag == "A" else self.ui_set_B
        text = ui["search_var"].get().lower()

        ui["measures"].delete(0, tk.END)
        for m in ui["all_measures"]:
            if text in m.lower():
                ui["measures"].insert(tk.END, m)

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

    def _unlock_ui(self, status_msg: str = "Ready."):
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
        f = ui["phase"].get().strip().upper()
        c = ui["code"].get().strip().upper()
        l = ui["batch"].get().strip().upper()

        self._debounce_id[tag] = self.root.after(
            delay_ms, lambda: self._dynamic_update_thread(tag, f, c, l))

    # ══════════════════════════════════════════════════════════════════════════
    #  Filters Update (IN MEMORY WITH PANDAS)
    # ══════════════════════════════════════════════════════════════════════════
    def _dynamic_update_thread(self, tag: str, f: str, c: str, l: str):
        self._lock_ui("Updating filters...")
        threading.Thread(target=self._dynamic_update_worker, args=(tag, f, c, l), daemon=True).start()

    def _dynamic_update_worker(self, tag: str, f: str, c: str, l: str):
        if self.df_complete.empty: return
        try:
            def fetch_valid(field: str, filters: dict) -> list[str]:
                temp_df = self.df_complete
                for col, val in filters.items():
                    if val:
                        temp_df = temp_df[temp_df[col].astype(str).str.upper() == val]
                result = temp_df[field].unique().tolist()
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

            measures: list[str] = []
            if f2 and c2 and l2:
                # Fast extraction with Pandas
                df_filtered = self.df_complete[
                    (self.df_complete['codice_pezzo'].astype(str).str.upper() == c2) &
                    (self.df_complete['lotto'].astype(str).str.upper() == l2) &
                    (self.df_complete['fase'].astype(str).str.upper() == f2)
                    ]
                raw_measures = df_filtered["nome_misura"].unique().tolist()
                measures = sorted([str(m) for m in raw_measures if m], key=natural_sort_key)

            self.root.after(0, lambda: self._update_ui(tag, valid_f, valid_c, valid_l, f2, c2, l2, measures))
        except Exception as exc:
            self.root.after(0, lambda: self._unlock_ui(f"Filter error: {exc}"))

    def _update_ui(self, tag: str, valid_f, valid_c, valid_l, f: str, c: str, l: str, measures: list[str]):
        ui = self.ui_set_A if tag == "A" else self.ui_set_B
        ui["phase"]["values"] = valid_f
        ui["code"]["values"] = valid_c
        ui["batch"]["values"] = valid_l
        ui["phase"].set(f)
        ui["code"].set(c)
        ui["batch"].set(l)

        ui["all_measures"] = measures
        self._filter_measures_list(tag)

        if tag == "A" and f and c and l:
            self._auto_fill_B(f, c, l)
        else:
            self._unlock_ui()

    def _auto_fill_B(self, phase_A: str, code_A: str, batch_A: str):
        mapping = {"PRE": "POST", "POST": "PRE"}
        phase_B = mapping.get(phase_A, "")
        if phase_B: self.ui_set_B["phase"].set(phase_B)
        self.ui_set_B["code"].set(code_A)
        self.ui_set_B["batch"].set(batch_A)

        if self._debounce_id["B"]: self.root.after_cancel(self._debounce_id["B"])

        f = self.ui_set_B["phase"].get().strip().upper()
        c = self.ui_set_B["code"].get().strip().upper()
        l = self.ui_set_B["batch"].get().strip().upper()
        self._debounce_id["B"] = self.root.after(50, lambda: self._dynamic_update_thread("B", f, c, l))

    # ══════════════════════════════════════════════════════════════════════════
    #  Load Database IN MEMORY
    # ══════════════════════════════════════════════════════════════════════════
    def _load_db(self):
        p = filedialog.askopenfilename(
            parent=self.root,
            title="Select SQLite database",
            filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")]
        )
        if not p: return

        self.db_path.set(p)
        self._last_fig = None
        self._lock_ui("Loading DB into memory (Pandas)...")

        threading.Thread(target=self._load_db_worker, args=(p,), daemon=True).start()

    def _load_db_worker(self, path):
        try:
            conn = sqlite3.connect(path)
            self.df_complete = pd.read_sql_query("SELECT * FROM misurazioni", conn)
            conn.close()

            # String optimization to speed up in-memory queries
            self.df_complete = self.df_complete.fillna("")
            for col in ['codice_pezzo', 'lotto', 'fase', 'nome_misura']:
                if col in self.df_complete.columns:
                    self.df_complete[col] = self.df_complete[col].astype(str).str.strip()

            self._populate_dashboard_worker()
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("DB Error", str(exc), parent=self.root))
            self.root.after(0, lambda: self._unlock_ui("Error loading database."))

    def _populate_dashboard_worker(self):
        try:
            df = self.df_complete
            if 'codice_pezzo' not in df.columns or 'lotto' not in df.columns or 'fase' not in df.columns:
                self.root.after(0, lambda: self._populate_dashboard_ui([]))
                return

            # Quickly find Batches that have BOTH PRE and POST phases using crosstab
            cross = pd.crosstab([df['codice_pezzo'], df['lotto']], df['fase'])
            if 'PRE' in cross.columns and 'POST' in cross.columns:
                valid_pairs = cross[(cross['PRE'] > 0) & (cross['POST'] > 0)].index.tolist()
            else:
                valid_pairs = []

            rows = sorted(valid_pairs, key=lambda x: (natural_sort_key(x[0]), natural_sort_key(x[1])))
            self.root.after(0, lambda: self._populate_dashboard_ui(rows))

        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("DB Error", str(exc), parent=self.root))
            self.root.after(0, lambda: self._unlock_ui("Error processing dashboard."))

    def _populate_dashboard_ui(self, rows: list[tuple]):
        self.tree_complete.delete(*self.tree_complete.get_children())
        for code, batch in rows:
            self.tree_complete.insert("", tk.END, values=(code, batch))
        self._unlock_ui("Database successfully loaded into memory.")
        self._schedule_update("A")
        self._schedule_update("B")

    # ══════════════════════════════════════════════════════════════════════════
    #  UI Actions
    # ══════════════════════════════════════════════════════════════════════════
    def _on_double_click_dashboard(self, _event):
        if self._busy: return
        sel = self.tree_complete.selection()
        if not sel: return
        code, batch = self.tree_complete.item(sel[0], "values")
        self.ui_set_A["phase"].set("PRE")
        self.ui_set_A["code"].set(code)
        self.ui_set_A["batch"].set(batch)
        self._schedule_update("A", delay_ms=50)

    def _clear_panel(self, tag: str):
        if self._debounce_id[tag]:
            self.root.after_cancel(self._debounce_id[tag])
            self._debounce_id[tag] = None

        ui = self.ui_set_A if tag == "A" else self.ui_set_B
        ui["phase"].set("")
        ui["code"].set("")
        ui["batch"].set("")
        ui["allowance"].delete(0, tk.END)
        ui["allowance"].insert(0, "0.0")
        ui["search_var"].set("")
        ui["all_measures"] = []
        ui["measures"].delete(0, tk.END)
        for field in ("phase", "code", "batch"):
            ui[field]["values"] = []

        if not self.df_complete.empty:
            self._schedule_update(tag)

    def _clear_all(self):
        self._clear_panel("A")
        self._clear_panel("B")
        self._last_fig = None
        self.tree_pairs.delete(*self.tree_pairs.get_children())

    def _add_pair(self):
        sel_A = self.ui_set_A["measures"].curselection()
        sel_B = self.ui_set_B["measures"].curselection()

        if not sel_A and not sel_B:
            return

        m_A = self.ui_set_A["measures"].get(sel_A[0]) if sel_A else "-"
        m_B = self.ui_set_B["measures"].get(sel_B[0]) if sel_B else "-"

        for item in self.tree_pairs.get_children():
            if self.tree_pairs.item(item, "values") == (m_A, m_B): return

        self.tree_pairs.insert("", tk.END, values=(m_A, m_B))

        if sel_A: self.ui_set_A["measures"].selection_clear(sel_A[0])
        if sel_B: self.ui_set_B["measures"].selection_clear(sel_B[0])

    def _remove_pair(self):
        for item in self.tree_pairs.selection(): self.tree_pairs.delete(item)

    # ══════════════════════════════════════════════════════════════════════════
    #  Graph Generation (IN MEMORY WITH PANDAS)
    # ══════════════════════════════════════════════════════════════════════════
    def _start_generate_graphs(self):
        if self.df_complete.empty:
            messagebox.showwarning("Missing DB", "Please load a database first.", parent=self.root)
            return
        items = self.tree_pairs.get_children()
        if not items:
            messagebox.showwarning("No measure", "Add at least one measure/pair.", parent=self.root)
            return

        pair_list = [tuple(self.tree_pairs.item(i, "values")) for i in items]
        cod_A, lot_A, fas_A = (self.ui_set_A["code"].get().strip().upper(),
                               self.ui_set_A["batch"].get().strip().upper(),
                               self.ui_set_A["phase"].get().strip().upper())
        cod_B, lot_B, fas_B = (self.ui_set_B["code"].get().strip().upper(),
                               self.ui_set_B["batch"].get().strip().upper(),
                               self.ui_set_B["phase"].get().strip().upper())
        allowance_A = _parse_allowance(self.ui_set_A["allowance"])
        allowance_B = _parse_allowance(self.ui_set_B["allowance"])

        self._lock_ui("Generating graphs...")
        threading.Thread(
            target=self._generate_graphs_worker,
            args=(pair_list, cod_A, lot_A, fas_A, cod_B, lot_B, fas_B, allowance_A, allowance_B),
            daemon=True
        ).start()

    def _generate_graphs_worker(self, pair_list: list[tuple], cod_A: str, lot_A: str, fas_A: str, cod_B: str, lot_B: str,
                               fas_B: str, allowance_A: float, allowance_B: float):
        try:
            valid_A = [m for m, _ in pair_list if m != "-"]
            valid_B = [m for _, m in pair_list if m != "-"]

            # Super fast Pandas extraction
            df_all_A = self.df_complete[
                (self.df_complete['codice_pezzo'].astype(str).str.upper() == cod_A) &
                (self.df_complete['lotto'].astype(str).str.upper() == lot_A) &
                (self.df_complete['fase'].astype(str).str.upper() == fas_A) &
                (self.df_complete['nome_misura'].isin(valid_A))
                ].copy()

            df_all_B = self.df_complete[
                (self.df_complete['codice_pezzo'].astype(str).str.upper() == cod_B) &
                (self.df_complete['lotto'].astype(str).str.upper() == lot_B) &
                (self.df_complete['fase'].astype(str).str.upper() == fas_B) &
                (self.df_complete['nome_misura'].isin(valid_B))
                ].copy()

            # Cleans the data and ensures values are numeric
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
                    self._draw_tolerance(ax, df_A, allowance_A, color="#2980b9", label_prefix="A", line_style="--")

                if not df_B.empty:
                    sns.histplot(df_B["misurato_mm"], color="#27ae60", label=f"B · {fas_B} · n={len(df_B)}",
                                 kde=True, stat="density", linewidth=0, alpha=0.4, ax=ax, kde_kws={'gridsize': 100})
                    self._draw_tolerance(ax, df_B, allowance_B, color="#229954", label_prefix="B", line_style="-.")

                if m_A != "-" and m_B != "-":
                    ax_title = f"{m_A}  ↔  {m_B}"
                elif m_A != "-":
                    ax_title = m_A
                else:
                    ax_title = m_B

                ax.set_title(ax_title, fontsize=10, fontweight="bold")
                ax.set_xlabel("Measure (mm)", fontsize=9)
                ax.set_ylabel("Density", fontsize=9)
                ax.legend(fontsize=7.5, loc="best")

            for i in range(n, len(axes_flat)): axes_flat[i].set_visible(False)

            title_parts = []
            if valid_A: title_parts.append(f"A: {cod_A} · {lot_A} · {fas_A}")
            if valid_B: title_parts.append(f"B: {cod_B} · {lot_B} · {fas_B}")

            allowance_parts = []
            if allowance_A and valid_A: allowance_parts.append(f"A={allowance_A:+.3f} mm")
            if allowance_B and valid_B: allowance_parts.append(f"B={allowance_B:+.3f} mm")
            if allowance_parts: title_parts.append("Allowance  " + "   ".join(allowance_parts))

            fig.suptitle("   |   ".join(title_parts), fontsize=14, fontweight="bold")
            fig.tight_layout(rect=[0, 0, 1, 0.95], h_pad=3.0)

            self._last_fig = fig
            self.root.after(0, lambda: self._show_graphs(fig))

        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            self.root.after(0, lambda: messagebox.showerror("Graph Error", f"{exc}\n\n{tb}", parent=self.root))
            self.root.after(0, lambda: self._unlock_ui("Error during generation."))

    @staticmethod
    def _draw_tolerance(ax, df: pd.DataFrame, allowance: float, color: str, label_prefix: str, line_style: str):
        if df.empty: return
        row0 = df.iloc[0]

        # Robust casting using pd.to_numeric to avoid errors with strings
        nom = pd.to_numeric(row0["nominale_mm"], errors='coerce')
        tp = pd.to_numeric(row0["tolleranza_piu"], errors='coerce')
        tm = pd.to_numeric(row0["tolleranza_meno"], errors='coerce')

        if pd.isna(nom): return

        ax.axvline(nom, color=color, linestyle=line_style, linewidth=1.4, label=f"Nom.{label_prefix} {nom:.3f}")

        if pd.notna(tp) and pd.notna(tm):
            lsl = nom + tm - allowance
            usl = nom + tp + allowance
            ax.axvspan(lsl, usl, color=color, alpha=0.07, label=f"Tol.{label_prefix} [{lsl:.3f} … {usl:.3f}]")
            ax.axvline(lsl, color=color, linestyle=":", linewidth=0.9)
            ax.axvline(usl, color=color, linestyle=":", linewidth=0.9)

    def _show_graphs(self, fig: Figure):
        win_graphs = tk.Toplevel(self.root)
        win_graphs.title("Comparison Graphs - Analysis")
        win_graphs.geometry("1200x800")
        try:
            win_graphs.state('zoomed')
        except tk.TclError:
            win_graphs.attributes('-zoomed', True)

        canvas = FigureCanvasTkAgg(fig, master=win_graphs)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

        toolbar = NavigationToolbar2Tk(canvas, win_graphs)
        toolbar.update()
        canvas.get_tk_widget().pack(fill="both", expand=True)

        self._unlock_ui("Graphs displayed successfully.")

    # ══════════════════════════════════════════════════════════════════════════
    #  Saving
    # ══════════════════════════════════════════════════════════════════════════
    def _save_graphs(self):
        if self._last_fig is None:
            messagebox.showwarning("No graph", "Generate graphs first with 📊.", parent=self.root)
            return

        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save Graphs As...",
            defaultextension=".png",
            filetypes=[("High Resolution PNG", "*.png"), ("Vector PDF", "*.pdf"), ("Vector SVG", "*.svg"),
                       ("JPEG", "*.jpg")]
        )
        if not path: return

        fig = self._last_fig
        self._lock_ui("Saving in progress...")
        threading.Thread(target=self._save_worker, args=(fig, path), daemon=True).start()

    def _save_worker(self, fig: Figure, path: str):
        try:
            fig.savefig(path, dpi=200, bbox_inches="tight")
            self.root.after(0, lambda: self._unlock_ui(f"Saved: {path}"))
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("Save Error", str(exc), parent=self.root))
            self.root.after(0, lambda: self._unlock_ui("Error while saving."))

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
