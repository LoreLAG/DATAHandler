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
# 1. CONFIGURATION AND REGEX
# ==========================================
logging.getLogger("PyPDF2").setLevel(logging.ERROR)

RECINTO_ORDER = re.compile(r"Order number(.*?)Variant", flags=re.IGNORECASE | re.DOTALL)
RECINTO_IDENT = re.compile(r"Part ident(.*?)Time/Date", flags=re.IGNORECASE | re.DOTALL)
PATTERN_LOTTO = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{6})(?![A-Za-z0-9])")


# ==========================================
# 2. EXTRACTION FUNCTION
# ==========================================
def extract_batch_pdf(pdf_path: Path) -> Optional[str]:
    try:
        reader = PdfReader(pdf_path)
        if not reader.pages: return None
        page_text = reader.pages[0].extract_text()
        if not page_text: return None

        code = re.split(r"[_\s-]+", pdf_path.stem)[0]
        match_order = RECINTO_ORDER.search(page_text)
        match_ident = RECINTO_IDENT.search(page_text)

        fragments = []
        if match_ident: fragments.append(match_ident.group(1))
        if match_order: fragments.append(match_order.group(1))

        for fragment in fragments:
            possible_batches = PATTERN_LOTTO.findall(fragment)
            for candidate in possible_batches:
                candidate = candidate.upper()
                if candidate == code.upper():
                    continue
                if any(c.isalpha() for c in candidate) and any(c.isdigit() for c in candidate):
                    return candidate
        return None
    except Exception:
        return None


# ==========================================
# 3. GRAPHICAL USER INTERFACE (GUI)
# ==========================================
class CalypsoRenamerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Calypso Report Renaming System (Pro Edition)")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)
        self.root.configure(bg="#ecf0f1")

        # State variables
        self.root_path = tk.StringVar()
        self.simulation_mode = tk.BooleanVar(value=True)

        # SEMAPHORE FOR GRACEFUL SHUTDOWN AND MOVING AVERAGE
        self.stop_event = threading.Event()
        self.time_window = collections.deque(maxlen=50)

        self.setup_ui()

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        # ==========================================
        # 1. TOP BAR (Dark Header)
        # ==========================================
        frame_header = tk.Frame(self.root, pady=15, padx=20, bg="#1c2833")
        frame_header.pack(fill="x", side="top")

        tk.Label(frame_header, text="1. Select Root Folder (PDF):", font=("Arial", 11, "bold"), bg="#1c2833",
                 fg="white", anchor="w").pack(side="left")
        tk.Entry(frame_header, textvariable=self.root_path, state="readonly", font=("Arial", 10)).pack(
            side="left", fill="x", expand=True, padx=(10, 10))

        tk.Button(frame_header, text="📂 Browse...", command=self.choose_folder, bg="#3498db", fg="white",
                  font=("Arial", 10, "bold"), bd=0, padx=15, pady=4).pack(side="right")

        # ==========================================
        # 2. MAIN BODY
        # ==========================================
        frame_body = tk.Frame(self.root, bg="#ecf0f1", padx=20, pady=15)
        frame_body.pack(fill="both", expand=True)

        # --- Mode Section ---
        frame_mode = tk.LabelFrame(frame_body, text="2. Execution Mode", font=("Arial", 10, "bold"),
                                  bg="#ecf0f1", padx=15, pady=10)
        frame_mode.pack(fill="x", pady=(0, 15))

        tk.Radiobutton(frame_mode, text="Simulation (Creates Log only, NO files modified)",
                       variable=self.simulation_mode, value=True, bg="#ecf0f1", fg="#2980b9",
                       font=("Arial", 10, "bold")).pack(anchor="w", pady=2)
        tk.Radiobutton(frame_mode, text="Real Operation (PHYSICALLY renames files and applies batches)",
                       variable=self.simulation_mode, value=False, bg="#ecf0f1", fg="#c0392b",
                       font=("Arial", 10, "bold")).pack(anchor="w", pady=2)

        # --- Commands Section ---
        frame_btns = tk.Frame(frame_body, bg="#ecf0f1")
        frame_btns.pack(fill="x", pady=(0, 15))

        self.btn_start = tk.Button(frame_btns, text="▶ START PROCESS", font=("Arial", 14, "bold"), bg="#27ae60",
                                   fg="white", height=2, bd=0, command=self.start_process)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.btn_stop = tk.Button(frame_btns, text="⏹ STOP", font=("Arial", 14, "bold"), bg="#c0392b", fg="white",
                                  height=2, bd=0, state="disabled", command=self.stop_process)
        self.btn_stop.pack(side="right", fill="x", expand=True)

        # --- Performance Dashboard Section ---
        frame_dash = tk.LabelFrame(frame_body, text="Performance Dashboard", font=("Arial", 10, "bold"), bg="#ffffff",
                                   padx=15, pady=10)
        frame_dash.pack(fill="x", pady=(0, 15))

        self.lbl_status = tk.Label(frame_dash, text="Waiting... ready to start.", font=("Consolas", 11, "bold"),
                                   bg="#ffffff", fg="#d35400")
        self.lbl_status.pack(anchor="w", pady=(0, 5))

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(frame_dash, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x")

        # --- System Log Section ---
        frame_log = tk.LabelFrame(frame_body, text="System Log", font=("Arial", 10, "bold"), bg="#ecf0f1")
        frame_log.pack(fill="both", expand=True)

        self.log_text = scrolledtext.ScrolledText(frame_log, state='disabled', bg="#1e1e1e", fg="#2ecc71",
                                                  font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True, padx=2, pady=2)

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self.root, title="Select root folder")
        if folder:
            self.root_path.set(folder)

    def log(self, message):
        def append():
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')

        self.root.after(0, append)

    def update_dashboard(self, percent, status_text):
        def _update():
            self.progress_var.set(percent)
            self.lbl_status.config(text=status_text)

        self.root.after(0, _update)

    def start_process(self):
        folder = self.root_path.get()
        if not folder:
            messagebox.showwarning("Warning", "Please select the folder containing the PDFs first!", parent=self.root)
            return

        # Prepare UI for processing
        self.stop_event.clear()  # Lower the semaphore
        self.btn_start.config(state="disabled", text="PROCESSING IN PROGRESS...")
        self.btn_stop.config(state="normal", text="⏹ STOP")

        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state='disabled')

        # Start the thread
        threading.Thread(target=self.work_process, args=(Path(folder),), daemon=True).start()

    def stop_process(self):
        """Raises the semaphore to tell the thread to stop gracefully."""
        self.log("\n⚠️ Stop request received... waiting for current operation to complete...")
        self.stop_event.set()
        self.btn_stop.config(state="disabled", text="STOPPING...")

    def work_process(self, root_path):
        simulation = self.simulation_mode.get()
        mod_str = "SIMULATION" if simulation else "REAL"

        self.log(f"🚀 Starting DEEP EXTRACTION FROM PDF ({mod_str})")
        self.log("🔍 Preliminary file counting in progress...")

        pdf_list = list(root_path.rglob("*.pdf"))
        total_pdfs = len(pdf_list)

        if total_pdfs == 0:
            self.log("⚠️ No PDFs found in this folder or subfolders.")
            self.root.after(0, self.end_process, False)
            return

        self.log(f"Found {total_pdfs} PDFs ready for analysis.\n")

        report_log = {
            "pdfs_examined": 0,
            "pdfs_successful": 0,
            "failed_files": [],
            "found_pairs": set()
        }

        self.time_window.clear()  # Reset at start for moving average
        start_time = time.time()
        last_ui_update = 0  # Stopwatch for anti-flicker
        interrupted = False

        for index, pdf in enumerate(pdf_list, start=1):
            # SEMAPHORE CHECK: If STOP was pressed, break the loop
            if self.stop_event.is_set():
                self.log("\n🛑 PROCESSING INTERRUPTED BY USER!")
                interrupted = True
                break

            report_log["pdfs_examined"] += 1
            extracted_batch = extract_batch_pdf(pdf)

            if extracted_batch:
                pdf_code = re.split(r"[_\s-]+", pdf.stem)[0]
                base_name = f"{pdf_code}_{extracted_batch}"
                report_log["found_pairs"].add(base_name)

                clean = pdf.stem.replace(extracted_batch, "").replace(pdf_code, "").replace("__", "_").strip("_")
                final_name = f"{base_name}_{clean}.pdf" if clean else f"{base_name}.pdf"

                if pdf.name != final_name:
                    if simulation:
                        report_log["pdfs_successful"] += 1
                        self.log(f"✅ [SIM] {pdf.name} -> {final_name}")
                    else:
                        try:
                            pdf.rename(pdf.parent / final_name)
                            report_log["pdfs_successful"] += 1
                            self.log(f"✅ [OK] {pdf.name} -> {final_name}")
                        except Exception as e:
                            report_log["failed_files"].append(f"{pdf.name} (OS Error: {e})")
                            self.log(f"❌ [ERROR] {pdf.name}: {e}")
            else:
                report_log["failed_files"].append(f"{pdf.name} (No batch)")

            # ==========================================
            # DASHBOARD WITH THROTTLING (No Flicker)
            # ==========================================
            current_time = time.time()
            self.time_window.append(current_time)

            # UPDATE GUI ONLY EVERY 0.5 SECONDS (or if it's the absolute last file)
            if (current_time - last_ui_update) > 0.5 or index == total_pdfs:

                # Calculate speed based only on the last N files saved in time_window
                if len(self.time_window) > 1:
                    window_time = current_time - self.time_window[0]
                    n_samples = len(self.time_window) - 1
                    real_speed = n_samples / window_time if window_time > 0 else 0
                else:
                    # Fallback for the very first files
                    total_elapsed = current_time - start_time
                    real_speed = index / total_elapsed if total_elapsed > 0 else 0

                perc = (index / total_pdfs) * 100

                if real_speed > 0:
                    eta_sec = (total_pdfs - index) / real_speed
                    mins, secs = divmod(int(eta_sec), 60)
                    eta_str = f"{mins:02d}:{secs:02d}"
                else:
                    eta_str = "--:--"

                truncated_name = (pdf.name[:25] + '..') if len(pdf.name) > 25 else pdf.name
                status_text = f"ETA: {eta_str} | 🚀 {real_speed:.1f} p/s | ✅ {report_log['pdfs_successful']} ❌ {len(report_log['failed_files'])} | 📄 {truncated_name}"

                self.update_dashboard(perc, status_text)

                # Reset GUI stopwatch
                last_ui_update = current_time

        # End of loop (whether natural or interrupted)
        elapsed_time = time.time() - start_time

        # Write log file anyway with what we managed to do until stop
        self.write_log_file(root_path, report_log, simulation, elapsed_time, interrupted)

        self.root.after(0, self.end_process, interrupted)

    def write_log_file(self, root_path: Path, log_data: dict, simulation: bool, exec_time: float, interrupted: bool):
        mode = "SIMULATION" if simulation else "REAL OPERATION"
        final_state = " (INTERRUPTED INCOMPLETE)" if interrupted else ""

        file_path = root_path / f"Log_Calypso_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        speed = log_data['pdfs_examined'] / exec_time if exec_time > 0 else 0

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("=" * 50 + "\n")
            f.write(f" CALYPSO RENAMING REPORT - {mode} MODE{final_state} \n")
            f.write("=" * 50 + "\n\n")
            f.write("--- ⏱️ PROCESS TELEMETRY ---\n")
            f.write(f"Execution time: {exec_time:.2f} seconds\n")
            f.write(f"Average speed:      {speed:.2f} PDF/second\n\n")
            f.write("--- 📊 GENERAL STATISTICS ---\n")
            f.write(f"Total PDFs Examined:  {log_data['pdfs_examined']}\n")
            f.write(f"PDFs Managed/Renamed: {log_data['pdfs_successful']}\n")
            f.write(f"PDFs Failed/Ignored:  {len(log_data['failed_files'])}\n\n")
            f.write("--- 🏷️ CODES AND BATCHES FOUND ---\n")
            if not log_data['found_pairs']:
                f.write("No valid batch/code identified.\n")
            else:
                for pair in sorted(log_data['found_pairs']):
                    f.write(f"- {pair}\n")
            f.write("\n--- ❌ UNRENAMABLE FILES DETAIL ---\n")
            if not log_data['failed_files']:
                f.write("Perfect! No files generated errors or missing batches.\n")
            else:
                for file in log_data['failed_files']:
                    f.write(f"- {file}\n")

        self.log(f"\n📝 Log file saved to: {file_path.name}")
        self.log(f"⏱️ Total time: {exec_time:.2f}s | 🚀 Final speed: {speed:.2f} PDF/s")

    def end_process(self, interrupted):
        self.btn_start.config(state="normal", text="▶ START PROCESS")
        self.btn_stop.config(state="disabled", text="⏹ STOP")

        if interrupted:
            self.lbl_status.config(text="Process stopped by user.", fg="#c0392b")
            messagebox.showinfo("Interrupted",
                                "Processing stopped safely.\nThe Log has been saved with partial results.", parent=self.root)
        else:
            self.update_dashboard(100, "Operation Completed Successfully!")
            self.lbl_status.config(fg="#27ae60")
            messagebox.showinfo("Done!", "Operation completed!\nCheck the Log for details.", parent=self.root)


if __name__ == "__main__":
    try:
        # Unique ID to maintain a separate icon on the Windows taskbar
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Calypso.Renamer.Pro")
    except Exception:
        pass

    root = tk.Tk()
    app = CalypsoRenamerApp(root)
    root.mainloop()
