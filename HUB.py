import tkinter as tk
from tkinter import messagebox
import multiprocessing
import sys
import os
import ctypes

# Import your scripts directly as modules!
try:
    import DaPDF
    import EstraiDati_LIGHT
    import EstraiDatiMACRO
    import ConsultaDB
    import CreaGRAPHS  # Module for graphs
except ImportError as e:
    messagebox.showerror("Startup Error", f"Unable to find one of the scripts:\n{e}")


def resource_path(relative_path):
    """ Gets the absolute path to resources, compatible with PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class CalypsoHubApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Calypso System Management - Control Panel")
        
        try:
            self.root.iconbitmap(resource_path("icon.ico"))
        except Exception:
            pass

        # --- AUTOMATIC SCREEN CENTERING ---
        window_width = 800
        window_height = 550

        # Get PC screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        # Calculate X and Y coordinates for the center
        x_coordinate = int((screen_width / 2) - (window_width / 2))
        y_coordinate = int((screen_height / 2) - (window_height / 2))

        # Apply dimensions and position
        self.root.geometry(f"{window_width}x{window_height}+{x_coordinate}+{y_coordinate}")

        self.root.resizable(False, False)
        self.root.configure(bg="#ecf0f1")

        self.opened_modules = {}

        self.setup_ui()

    def launch_module(self, module_name):
        """Opens the requested module or brings it to the foreground if already open."""

        if module_name in self.opened_modules:
            existing_window = self.opened_modules[module_name]
            if existing_window.winfo_exists():
                existing_window.lift()
                existing_window.focus_force()
                existing_window.bell()
                return
            else:
                del self.opened_modules[module_name]

        child_window = tk.Toplevel(self.root)

        try:
            child_window.iconbitmap(resource_path("icon.ico"))
        except Exception:
            pass

        self.opened_modules[module_name] = child_window

        try:
            if module_name == "DaPDF":
                app = DaPDF.CalypsoRenamerApp(child_window)
            elif module_name == "EstraiDati_LIGHT":
                app = EstraiDati_LIGHT.CalypsoLightApp(child_window)
            elif module_name == "EstraiDatiMACRO":
                app = EstraiDatiMACRO.UniversalExtractorApp(child_window)
            elif module_name == "ConsultaDB":
                app = ConsultaDB.SQLiteNavigatorApp(child_window)
            elif module_name == "CreaGRAPHS":
                app = CreaGRAPHS.DataAnalyzerApp(child_window)

            self.root.after(100, lambda: [child_window.lift(), child_window.focus_force()])

        except Exception as e:
            messagebox.showerror("Error", f"Unable to launch module {module_name}:\n{str(e)}")
            child_window.destroy()
            if module_name in self.opened_modules:
                del self.opened_modules[module_name]

    def create_card(self, container, row, column, title, description, bg_color, icon, module_id, colspan=1, internal_pad=12):
        """Creates a large button (Card) and places it in a grid."""
        cell_frame = tk.Frame(container, bg="#ecf0f1")
        cell_frame.grid(row=row, column=column, columnspan=colspan, sticky="nsew", padx=12, pady=6)

        frame = tk.Frame(cell_frame, bg=bg_color, bd=0, relief="flat", pady=internal_pad, padx=20)
        frame.pack(fill="both", expand=True)

        inner = tk.Frame(frame, bg=bg_color)
        inner.pack(fill="both", expand=True)

        # The icon is positioned on the left and centered vertically
        lbl_icon = tk.Label(inner, text=icon, font=("Segoe UI Emoji", 32), bg=bg_color, fg="white")
        lbl_icon.pack(side="left", padx=(0, 15), anchor="center")

        frame_texts = tk.Frame(inner, bg=bg_color)
        # Using fill="x" instead of fill="both" + anchor="center".
        # This aligns the text block perfectly with the icon height!
        frame_texts.pack(side="left", fill="x", expand=True, anchor="center")

        lbl_title = tk.Label(frame_texts, text=title, font=("Arial", 13, "bold"), bg=bg_color, fg="white", anchor="w")
        lbl_title.pack(fill="x")

        lbl_desc = tk.Label(frame_texts, text=description, font=("Arial", 9), bg=bg_color, fg="#ecf0f1", anchor="w", wraplength=700 if colspan==2 else 320, justify="left")
        lbl_desc.pack(fill="x", pady=(3, 0))

        for widget in [frame, inner, lbl_icon, frame_texts, lbl_title, lbl_desc]:
            widget.bind("<ButtonRelease-1>", lambda e, s=module_id: self.launch_module(s))
            widget.bind("<Enter>", lambda e, f=frame: f.configure(cursor="hand2"))

    def setup_ui(self):
        header = tk.Frame(self.root, bg="#2c3e50", pady=20)
        header.pack(fill="x")
        tk.Label(header, text="⚙️ CALYPSO CENTRAL SYSTEM", font=("Arial", 18, "bold"), bg="#2c3e50",
                 fg="white").pack()
        tk.Label(header, text="Select the module to launch", font=("Arial", 11, "italic"), bg="#2c3e50",
                 fg="#bdc3c7").pack()

        body = tk.Frame(self.root, bg="#ecf0f1", padx=20, pady=10)
        body.pack(fill="both", expand=True)

        body.rowconfigure(0, weight=0)  # Fixed banner
        body.rowconfigure(1, weight=1)  # Shared space
        body.rowconfigure(2, weight=1)  # Shared space
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        # ROW 0 - TOP BANNER (Flattened, two columns)
        self.create_card(body, row=0, column=0, colspan=2, internal_pad=8,
                         title="Rename PDF",
                         description="Recognizes batches in PDFs and correctly formats file names.",
                         bg_color="#e67e22", icon="📄", module_id="DaPDF")

        # ROW 1 - THE TWO EXTRACTIONS (Side by side)
        self.create_card(body, row=1, column=0, internal_pad=12,
                         title="LIGHT Extraction",
                         description="Targeted and selective extraction with fast export to CSV/Excel.",
                         bg_color="#16a085", icon="⚡", module_id="EstraiDati_LIGHT")

        self.create_card(body, row=1, column=1, internal_pad=12,
                         title="MACRO Extraction",
                         description="Extracts large volumes of PDFs and saves data to the SQLite Database.",
                         bg_color="#e74c3c", icon="⚙️", module_id="EstraiDatiMACRO")

        # ROW 2 - QUERY AND GRAPHS (Side by side)
        self.create_card(body, row=2, column=0, internal_pad=12,
                         title="Query Database",
                         description="Analyzes saved data, applies cross-filters, and exports reports.",
                         bg_color="#27ae60", icon="📊", module_id="ConsultaDB")

        self.create_card(body, row=2, column=1, internal_pad=12,
                         title="Generate Graphs",
                         description="Statistical analysis, density curves, and visual comparison between processes.",
                         bg_color="#8e44ad", icon="📈", module_id="CreaGRAPHS")

        footer = tk.Frame(self.root, bg="#ecf0f1")
        footer.pack(side="bottom", fill="x", pady=5)
        tk.Label(footer, text="Developed for process automation.", font=("Arial", 8), fg="gray",
                 bg="#ecf0f1").pack()


if __name__ == "__main__":
    multiprocessing.freeze_support()

    try:
        myappid = 'company.calypso.hub.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    root = tk.Tk()

    try:
        root.iconbitmap(resource_path("icon.ico"))
    except Exception:
        pass

    app = CalypsoHubApp(root)
    root.mainloop()
