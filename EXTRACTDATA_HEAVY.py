import collections
import os
import sys
import logging
import re
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk, simpledialog
from pathlib import Path
from typing import Optional
from PyPDF2 import PdfReader
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import ctypes

import fitz  # PyMuPDF
import pdfplumber
import sqlite3
import json

# ── GRAPHICAL CONSTANTS ──────────────────────────────────────────────────────
CHECKED = "☑"
UNCHECKED = "☐"

# ── REGEX FOR MEASURE EXTRACTION ──
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


def clean_text(text):
    return " ".join(str(text).split()) if text else ""


# ── WORKER: MEASURE EXTRACTION (pdfplumber) ──
def worker_extract_measures(args):
    """Extracts measurements and applies the phase tag chosen by the user (even empty)."""
    pdf_path_str, code, batch, phase = args
    pdf_path = Path(pdf_path_str)

    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n".join([p.extract_text() or "" for p in pdf.pages])
    except Exception as e:
        return {"error": str(e), "file_path": pdf_path_str}

    extracted_rows = []
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
            name = clean_text(m.group(1))
            meas = parse_number(m.group(2))
            nom = parse_number(m.group(3))
            tp = parse_number(m.group(4))
            tm = parse_number(m.group(5))
            dev = parse_number(m.group(6))
            extra = parse_number(m.group(7)) if len(m.groups()) > 6 else None
            status = "OK" if (tm is not None and tp is not None and dev is not None and tm <= dev <= tp) else "NON OK"
        else:
            m_angle = RE_ANGLE.match(line)
            if m_angle:
                name = clean_text(m_angle.group(1))
                meas = parse_number(m_angle.group(2))
                nom = parse_number(m_angle.group(3))
                tp = tm = extra = status = None
                dev = parse_number(m_angle.group(4))
            else:
                m_part = RE_PARTIAL.match(line)
                if m_part:
                    name = clean_text(m_part.group(1))
                    meas = parse_number(m_part.group(2))
                    nom = tp = tm = dev = extra = status = None
                else:
                    continue

        key = (current_section, name)
        if key not in seen:
            seen.add(key)
            row_tuple = (pdf_path_str, pdf_path.parent.name, code, batch, current_section, name,
                          meas, nom, tp, tm, dev, extra, status, phase)
            extracted_rows.append(row_tuple)

    return {"file_path": pdf_path_str, "data": extracted_rows}


# ── GRAPHICAL USER INTERFACE ──
class UniversalExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MACRO Data Extractor - SQLite DB")
        self.root.geometry("1400x800")
        self.root.minsize(1050, 700)

        try:
            self.root.state('zoomed')
        except tk.TclError:
            self.root.attributes('-zoomed', True)

        self.db_path = tk.StringVar()
        self.folder_data = {}
        self.last_clicked_item = None
        self.stop_flag = threading.Event()

        self.setup_ui()

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Treeview", rowheight=28, font=("Arial", 10))
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"), background="#d5d8dc")

        # --- HEADER (Dark Top Bar) ---
        frame_header = tk.Frame(self.root, pady=15, padx=20, bg="#1c2833")
        frame_header.pack(fill="x")

        # ROW 1: DB Selection
        frame_db_sel = tk.Frame(frame_header, bg="#1c2833")
        frame_db_sel.pack(fill="x", pady=(0, 10))
        tk.Label(frame_db_sel, text="1. SQLite Database:", font=("Arial", 11, "bold"), bg="#1c2833", fg="white",
                 width=20, anchor="w").pack(side="left")
        tk.Entry(frame_db_sel, textvariable=self.db_path, state="readonly", font=("Arial", 10)).pack(side="left",
                                                                                                     fill="x",
                                                                                                     expand=True,
                                                                                                     padx=(0, 10))

        tk.Button(frame_db_sel, text="➕ Create New DB...", command=self.create_db, bg="#f39c12", fg="white",
                  font=("Arial", 9, "bold"), bd=0, padx=10, pady=4).pack(side="right", padx=(5, 0))
        tk.Button(frame_db_sel, text="📂 Open Existing...", command=self.choose_db, bg="#3498db", fg="white",
                  font=("Arial", 9, "bold"), bd=0, padx=10, pady=4).pack(side="right")

        # ROW 2: Sources Selection
        frame_dir_sel = tk.Frame(frame_header, bg="#1c2833")
        frame_dir_sel.pack(fill="x")
        tk.Label(frame_dir_sel, text="2. Data Sources:", font=("Arial", 11, "bold"), bg="#1c2833", fg="white",
                 width=20, anchor="w").pack(side="left")

        tk.Button(frame_dir_sel, text="Add Folder", font=("Arial", 10, "bold"),
                  bg="#27ae60", fg="white", bd=0, padx=10, pady=4,
                  command=self.add_single_folder).pack(side="left", padx=(0, 5))

        tk.Button(frame_dir_sel, text="Import Separate Subfolders", font=("Arial", 10, "bold"),
                  bg="#16a085", fg="white", bd=0, padx=10, pady=4,
                  command=self.add_macrofolder).pack(side="left")

        # --- BODY (Table and Controls) ---
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True, padx=15, pady=15)

        # LEFT: Treeview
        frame_left = tk.LabelFrame(paned, text="Folders in Queue (Select to set Phase/Batch)", padx=10,
                                 pady=10, bg="#ecf0f1")
        paned.add(frame_left, weight=2)

        frame_btn_tree = tk.Frame(frame_left, bg="#ecf0f1")
        frame_btn_tree.pack(fill="x", pady=(0, 8))
        tk.Button(frame_btn_tree, text="☑ Select All", command=self.select_all, bd=0, bg="#bdc3c7", padx=8,
                  pady=3).pack(side="left", padx=(0, 5))
        tk.Button(frame_btn_tree, text="☐ Deselect All", command=self.deselect_all, bd=0, bg="#bdc3c7",
                  padx=8, pady=3).pack(side="left", padx=(0, 5))
        tk.Button(frame_btn_tree, text="🗑 Remove", command=self.remove_selected_folder, bd=0, bg="#e74c3c",
                  fg="white", padx=8, pady=3).pack(side="left")

        tk.Button(frame_btn_tree, text="✏️ Force Batch", bg="#f1c40f", font=("Arial", 9, "bold"), bd=0, padx=10, pady=3,
                  command=self.set_batch).pack(side="right")
        tk.Button(frame_btn_tree, text="🏷️ Set Phase", bg="#3498db", fg="white", font=("Arial", 9, "bold"), bd=0,
                  padx=10, pady=3,
                  command=self.set_phase).pack(side="right", padx=(0, 5))

        cols = ("check", "folder_display", "count", "phase", "forced_batch", "full_path")
        self.tree = ttk.Treeview(frame_left, columns=cols, show="headings", selectmode="extended")

        self.tree.heading("check", text="Export")
        self.tree.heading("folder_display", text="Folder Path")
        self.tree.heading("count", text="PDFs Found")
        self.tree.heading("phase", text="Phase (Tag)")
        self.tree.heading("forced_batch", text="Forced Batch")
        self.tree.heading("full_path", text="")

        self.tree.column("check", width=65, anchor="center")
        self.tree.column("folder_display", width=350, anchor="w")
        self.tree.column("count", width=80, anchor="center")
        self.tree.column("phase", width=90, anchor="center")
        self.tree.column("forced_batch", width=130, anchor="center")
        self.tree.column("full_path", width=0, minwidth=0, stretch=tk.NO)

        scroll_tree = ttk.Scrollbar(frame_left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll_tree.set)
        scroll_tree.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<ButtonRelease-1>", self.on_tree_click)

        # RIGHT: Dashboard and Commands
        frame_right = tk.Frame(paned, bg="#ecf0f1")
        paned.add(frame_right, weight=1)

        self.btn_start = tk.Button(frame_right, text="▶ START DB WRITING", font=("Arial", 12, "bold"), bg="#27ae60",
                                   fg="white", height=2, bd=0, command=self.start_extraction)
        self.btn_start.pack(fill="x", pady=(0, 5))

        self.btn_stop = tk.Button(frame_right, text="⏹ STOP", font=("Arial", 12, "bold"), bg="#c0392b", fg="white",
                                  height=2, bd=0, command=self.stop, state="disabled")
        self.btn_stop.pack(fill="x", pady=(5, 15))

        frame_dash = tk.LabelFrame(frame_right, text="Performance Dashboard", padx=10, pady=10, bg="#ffffff")
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
        frame_log = tk.LabelFrame(frame_right, text="Operations Log", bg="#ecf0f1")
        frame_log.pack(fill="both", expand=True)
        self.log_text = scrolledtext.ScrolledText(frame_log, state='disabled', bg="#1e1e1e", fg="#2ecc71",
                                                  font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

        self.load_cache()

    # --- CACHE AND MEMORY METHODS ---
    def save_cache(self):
        cache_data = {"db_path": self.db_path.get(), "folders": {}}
        for path, data in self.folder_data.items():
            cache_data["folders"][path] = {
                "is_rglob": data["is_rglob"],
                "check": data["check"],
                "forced_batch": data["forced_batch"],
                "phase": data.get("phase", "POST")
            }
        try:
            with open("cache_extractor.json", "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=4)
        except Exception:
            pass

    def load_cache(self):
        cache_file = Path("cache_extractor.json")
        if not cache_file.exists(): return
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            if cache_data.get("db_path") and Path(cache_data["db_path"]).exists():
                self.db_path.set(cache_data["db_path"])
            for path, info in cache_data.get("folders", {}).items():
                p = Path(path)
                if p.exists():
                    is_rglob = info.get("is_rglob", False)
                    pdfs = list(p.rglob("*.pdf")) if is_rglob else list(p.glob("*.pdf"))
                    if pdfs:
                        old_check = info.get("check", CHECKED)
                        if old_check == "[X]": old_check = CHECKED
                        if old_check == "[ ]": old_check = UNCHECKED

                        self._add_to_folder_data(p, pdfs, is_rglob=is_rglob, check=old_check,
                                                 forced_batch=info.get("forced_batch", ""),
                                                 phase=info.get("phase", "POST"))
            self.populate_treeview()
            self.log("✅ Cache restored.")
        except Exception:
            pass

    def choose_db(self):
        if p := filedialog.askopenfilename(parent=self.root, title="Select SQLite Database",
                                           filetypes=[("SQLite DB", "*.db")]):
            self.db_path.set(p)
            self.save_cache()

    def create_db(self):
        if p := filedialog.asksaveasfilename(parent=self.root, title="Create New DB", defaultextension=".db",
                                             filetypes=[("SQLite DB", "*.db")],
                                             initialfile="New_Calypso_Database.db"):
            try:
                sqlite3.connect(p).close()
                self.db_path.set(p)
                self.save_cache()
                self.log(f"✅ DB created: {Path(p).name}")
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=self.root)

    def _add_to_folder_data(self, path, pdfs, is_rglob=False, check=CHECKED, forced_batch="", phase="POST"):
        path_str = str(path)
        p = Path(path)
        display_path = f"...\\{p.parts[-2]}\\{p.parts[-1]}" if len(p.parts) >= 2 else p.name

        if path_str not in self.folder_data:
            self.folder_data[path_str] = {"pdfs": pdfs, "is_rglob": is_rglob, "check": check,
                                          "forced_batch": forced_batch, "display_path": display_path,
                                          "phase": phase}
            return True
        else:
            self.folder_data[path_str].update({"pdfs": pdfs, "is_rglob": is_rglob})
            return False

    def add_macrofolder(self):
        if folder := filedialog.askdirectory(parent=self.root, title="Select Macrofolder"):
            base_dir = Path(folder)
            self.log(f"Recursive Batch Scan: {base_dir.name}...")
            new_rows = sum(1 for sub in base_dir.iterdir() if
                        sub.is_dir() and (pdfs := list(sub.rglob("*.pdf"))) and self._add_to_folder_data(sub,
                                                                                                         pdfs,
                                                                                                         is_rglob=True))
            if root_pdfs := list(base_dir.glob("*.pdf")):
                if self._add_to_folder_data(base_dir, root_pdfs, is_rglob=False): new_rows += 1
            self.populate_treeview()
            self.log(f"Added {new_rows} new separate rows.")

    def add_single_folder(self):
        if folder := filedialog.askdirectory(parent=self.root, title="Select folder"):
            sub_dir = Path(folder)
            inc_sub = messagebox.askyesno("Subfolders",
                                          "Include PDFs found in internal subfolders in this single block?",
                                          parent=self.root)
            if pdfs := list(sub_dir.rglob("*.pdf") if inc_sub else sub_dir.glob("*.pdf")):
                if self._add_to_folder_data(sub_dir, pdfs, is_rglob=inc_sub):
                    self.populate_treeview()
                    self.log(f"Added single block from: {sub_dir.name} ({len(pdfs)} PDFs).")
            else:
                messagebox.showinfo("No PDF", "The folder is empty.", parent=self.root)

    def remove_selected_folder(self):
        for item in self.tree.selection():
            if (pa := self.tree.item(item, "values")[5]) in self.folder_data:
                del self.folder_data[pa]
            self.tree.delete(item)
        self.save_cache()

    def populate_treeview(self):
        self.tree.delete(*self.tree.get_children())
        for p, d in sorted(self.folder_data.items()):
            batch_text = d["forced_batch"]
            self.tree.insert("", tk.END, values=(d["check"], d["display_path"], len(d["pdfs"]), d.get("phase", "POST"),
                                                 batch_text, p))
        self.save_cache()

    def on_tree_click(self, event):
        if self.tree.identify("region", event.x, event.y) == "cell" and self.tree.identify_column(event.x) == '#1':
            item = self.tree.identify_row(event.y)
            pa = self.tree.item(item, "values")[5]
            new_state = UNCHECKED if self.folder_data[pa]["check"] == CHECKED else CHECKED
            items_to_update = [item]

            if event.state & 0x0001 and getattr(self, "last_clicked_item", None):
                items = self.tree.get_children()
                try:
                    i1, i2 = items.index(self.last_clicked_item), items.index(item)
                    items_to_update = items[min(i1, i2):max(i1, i2) + 1]
                except ValueError:
                    pass

            for c_item in items_to_update:
                pa = self.tree.item(c_item, "values")[5]
                self.folder_data[pa]["check"] = new_state
                d = self.folder_data[pa]
                batch_text = d["forced_batch"]
                self.tree.item(c_item, values=(d["check"], d["display_path"], len(d["pdfs"]), d.get("phase", "POST"),
                                               batch_text, pa))

            self.last_clicked_item = item
            self.save_cache()

    def select_all(self):
        for item in self.tree.get_children():
            pa = self.tree.item(item, "values")[5]
            self.folder_data[pa]["check"] = CHECKED
            d = self.folder_data[pa]
            batch_text = d["forced_batch"]
            self.tree.item(item, values=(d["check"], d["display_path"], len(d["pdfs"]), d.get("phase", "POST"),
                                         batch_text, pa))
        self.save_cache()

    def deselect_all(self):
        for item in self.tree.get_children():
            pa = self.tree.item(item, "values")[5]
            self.folder_data[pa]["check"] = UNCHECKED
            d = self.folder_data[pa]
            batch_text = d["forced_batch"]
            self.tree.item(item, values=(d["check"], d["display_path"], len(d["pdfs"]), d.get("phase", "POST"),
                                         batch_text, pa))
        self.save_cache()

    def set_batch(self):
        if not (sel := self.tree.selection()):
            return messagebox.showinfo("Info", "Select rows from the table.", parent=self.root)
        first = self.tree.item(sel[0], "values")[5]
        if (
                n_batch := simpledialog.askstring("Force Batch",
                                                  "Enter batch (leave empty to read from FILE NAME):",
                                                  initialvalue=self.folder_data[first]["forced_batch"],
                                                  parent=self.root)) is not None:
            clean_batch = n_batch.strip().upper()
            for item in sel:
                pa = self.tree.item(item, "values")[5]
                self.folder_data[pa]["forced_batch"] = clean_batch
                d = self.folder_data[pa]
                batch_text = clean_batch
                self.tree.item(item, values=(d["check"], d["display_path"], len(d["pdfs"]), d.get("phase", "POST"),
                                             batch_text, pa))
            self.save_cache()

    def set_phase(self):
        if not (sel := self.tree.selection()):
            return messagebox.showinfo("Info", "Select rows from the table.", parent=self.root)
        first = self.tree.item(sel[0], "values")[5]

        if (n_phase := simpledialog.askstring("Set Phase", "Enter the Phase (e.g. PRE, POST, SCRAP):",
                                             initialvalue=self.folder_data[first].get("phase", "POST"),
                                             parent=self.root)) is not None:
            clean_phase = n_phase.strip().upper()
            for item in sel:
                pa = self.tree.item(item, "values")[5]
                self.folder_data[pa]["phase"] = clean_phase
                d = self.folder_data[pa]
                batch_text = d["forced_batch"]
                self.tree.item(item,
                               values=(d["check"], d["display_path"], len(d["pdfs"]), d["phase"], batch_text,
                                       pa))
            self.save_cache()

    def log(self, m):
        current_time = time.strftime("%H:%M:%S")
        formatted_text = f"[{current_time}] {m}"

        def a():
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, formatted_text + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')

        self.root.after(0, a)

    # --- GRACEFUL SHUTDOWN ---
    def stop(self):
        answer = messagebox.askyesno("Confirm Stop",
                                       "Do you want to stop extraction and close the application?\n\nFiles in queue will be cancelled, while those currently being processed will be saved.",
                                       parent=self.root)
        if answer:
            self.stop_flag.set()
            self.btn_stop.config(state="disabled", text="CLOSING IN PROGRESS...")
            self.log("⚠️ Stop request. Emptying queue...")

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
        self.btn_stop.config(state="disabled", text="⏹ STOP")

    # --- EXTRACTION PROCESS ---
    def start_extraction(self):
        if not self.db_path.get() or not self.folder_data:
            return messagebox.showwarning("Error", "Configure the DB and add at least one folder!", parent=self.root)

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.stop_flag.clear()
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state='disabled')

        threading.Thread(target=self.extraction_process, daemon=True).start()

    def extraction_process(self):
        self.log("🚀 Starting Universal Multi-Tag Extraction.")
        self.log("⚙️ Connecting to Database...")

        conn = sqlite3.connect(self.db_path.get(), check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA temp_store = MEMORY;")

        # keeping Italian database column names to maintain compatibility with other scripts
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
        done_files = set(r[0] for r in cursor.fetchall())

        job_list = []
        for p_abs, data in self.folder_data.items():
            if data["check"] == CHECKED:
                folder_phase = data.get("phase", "POST")
                for pdf_path in data["pdfs"]:
                    if str(pdf_path) not in done_files:
                        parts = pdf_path.stem.split('_')
                        if len(parts) >= 2:
                            code = parts[0].upper()
                            batch = data["forced_batch"] if data["forced_batch"] else parts[1].upper()
                            job_list.append((str(pdf_path), code, batch, folder_phase))
                        else:
                            self.log(f"⚠️ Ignored non-compliant file: {pdf_path.name}")

        if not job_list:
            self.log("✅ No new valid files to extract.")
            self.root.after(0, self.reset_ui)
            return

        total_jobs = len(job_list)
        self.log(f"🎯 Ready {total_jobs} files for extraction.")

        start_t = time.time()
        processed_files, saved_measures = 0, 0

        # Parallel extraction workers
        with ProcessPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(worker_extract_measures, job): job for job in job_list}
            for f in as_completed(futs):

                if self.stop_flag.is_set():
                    for future in futs:
                        future.cancel()
                    break

                processed_files += 1
                res = f.result()
                if "data" in res and res["data"]:
                    cursor.executemany(
                        "INSERT INTO misurazioni (file_pdf, cartella_padre, codice_pezzo, lotto, sezione, nome_misura, misurato_mm, nominale_mm, tolleranza_piu, tolleranza_meno, deviazione, extra_dev, stato, fase) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        res["data"])
                    cursor.execute("INSERT OR IGNORE INTO registro_file (file_pdf) VALUES (?)", (res["file_path"],))
                    saved_measures += len(res["data"])

                if processed_files % 20 == 0:
                    conn.commit()
                    self.update_dash(processed_files, total_jobs, start_t)

        conn.commit()
        conn.close()

        total_time = time.time() - start_t
        m_tot, s_tot = divmod(int(total_time), 60)

        if self.stop_flag.is_set():
            self.log("🛑 Extraction stopped safely. Closing app in 2 seconds...")
            self.root.after(2000, self.root.destroy)
        else:
            self.log(f"🏁 FINISHED IN {total_time:.1f} SECONDS")
            self.log(f"📄 Processed files: {processed_files} | Measures: {saved_measures}")
            self.root.after(0, lambda: messagebox.showinfo("Completed",
                                                           f"DB extraction completed!\n\nMeasures added: {saved_measures}",
                                                           parent=self.root))
            self.root.after(0, self.reset_ui)


if __name__ == "__main__":
    try:
        # Add ID for Windows Taskbar
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Calypso.Extractor.Macro")
    except Exception:
        pass

    multiprocessing.freeze_support()
    root = tk.Tk()
    app = UniversalExtractorApp(root)
    root.mainloop()
