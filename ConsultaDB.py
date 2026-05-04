import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import sqlite3
from pathlib import Path
import ctypes


class SQLiteNavigatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SQLite Database Navigator")
        self.root.geometry("1400x850")
        self.root.minsize(1200, 700)
        self.root.configure(bg="#ecf0f1")

        try:
            self.root.state('zoomed')  # Command for Windows
        except tk.TclError:
            self.root.attributes('-zoomed', True)  # Alternative for Linux/Mac

        # Data Engine
        self.df_complete = pd.DataFrame()
        self.df_filtered = pd.DataFrame()
        self.file_path_db = None

        # Dynamic Measure Panel Management
        self.current_code = None
        self.visible_measures_vars = {}

        # ==========================================
        # TRANSLATION DICTIONARY: DB Name -> Display Name
        # ==========================================
        self.display_names = {
            'id': 'id',
            'file_pdf': 'File',
            'cartella_padre': 'Folder',
            'codice_pezzo': 'Code',
            'lotto': 'Batch',
            'sezione': 'Section',
            'nome_misura': 'Measure',
            'misurato_mm': 'Measured',
            'nominale_mm': 'Nominal',
            'tolleranza_piu': 'T+',
            'tolleranza_meno': 'T-',
            'deviazione': 'Deviation',
            'extra_dev': 'Extra Dev.',
            'stato': 'Status',
            'fase': 'Phase'
        }

        self.setup_ui()

    def get_visual_name(self, db_col):
        """Returns the formatted name if it exists, otherwise capitalizes the DB one."""
        return self.display_names.get(db_col, db_col.replace("_", " ").title())

    # ==========================================
    # LOGIC: LOCK INTERFACE DURING WORK
    # ==========================================
    def set_loading(self, is_loading=True, message="⏳ Processing in progress..."):
        """Locks the UI and shows the loading cursor, or unlocks everything when done."""
        if is_loading:
            self.root.config(cursor="watch")
            self.lbl_file.config(text=message, fg="#f1c40f")

            self.btn_load.config(state="disabled")
            self.btn_export.config(state="disabled")
            self.btn_reset.config(state="disabled")
            self.btn_edit.config(state="disabled")
            self.btn_rename_measure.config(state="disabled")
            self.btn_toggle_measures.config(state="disabled")

            self.root.update()
        else:
            self.root.config(cursor="")
            self.lbl_file.config(fg="white")

            self.btn_load.config(state="normal")
            self.btn_export.config(state="normal")
            self.btn_reset.config(state="normal")
            self.btn_edit.config(state="normal")

            if self.current_code:
                self.btn_rename_measure.config(state="normal")
                self.btn_toggle_measures.config(state="normal")

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Treeview", rowheight=26, font=("Arial", 10))
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"), background="#d5d8dc")

        # ==========================================
        # 1. TOP BAR: FILE LOADING
        # ==========================================
        frame_top = tk.Frame(self.root, bg="#1c2833", pady=15, padx=20)
        frame_top.pack(fill="x", side="top")

        self.lbl_file = tk.Label(frame_top, text="No Database loaded", bg="#1c2833", fg="white",
                                 font=("Arial", 12, "bold"))
        self.lbl_file.pack(side="left", padx=10)

        self.btn_load = tk.Button(frame_top, text="📂 Load SQLite Database (.db)", command=self.load_db,
                                    bg="#3498db", fg="white", font=("Arial", 10, "bold"), bd=0, padx=15, pady=4)
        self.btn_load.pack(side="right")

        self.btn_export = tk.Button(frame_top, text="💾 Export to Excel / CSV", command=self.export_data,
                                     bg="#27ae60", fg="white", font=("Arial", 10, "bold"), bd=0, padx=15, pady=4)
        self.btn_export.pack(side="right", padx=10)

        # ==========================================
        # 2. LEFT BAR: GLOBAL SCROLL
        # ==========================================
        left_container = tk.Frame(self.root, width=240, bg="#ecf0f1")
        left_container.pack_propagate(False)
        left_container.pack(side="left", fill="y", padx=(15, 0), pady=15)

        self.canvas_left = tk.Canvas(left_container, bg="#ecf0f1", highlightthickness=0)
        self.scroll_left = ttk.Scrollbar(left_container, orient="vertical", command=self.canvas_left.yview)

        self.frame_left = tk.Frame(self.canvas_left, width=220, bg="#ecf0f1")

        self.canvas_left.create_window((0, 0), window=self.frame_left, anchor="nw", width=220)
        self.frame_left.bind("<Configure>",
                             lambda e: self.canvas_left.configure(scrollregion=self.canvas_left.bbox("all")))
        self.canvas_left.configure(yscrollcommand=self.scroll_left.set)

        self.canvas_left.pack(side="left", fill="both", expand=True)
        self.scroll_left.pack(side="right", fill="y")

        def _on_mousewheel(event):
            self.canvas_left.yview_scroll(int(-1 * (event.delta / 120)), "units")

        left_container.bind("<Enter>", lambda e: self.canvas_left.bind_all("<MouseWheel>", _on_mousewheel))
        left_container.bind("<Leave>", lambda e: self.canvas_left.unbind_all("<MouseWheel>"))

        # --- Filters Section ---
        frame_filters = tk.LabelFrame(self.frame_left, text="🔍 Dynamic Filters", font=("Arial", 10, "bold"),
                                      bg="#ecf0f1", padx=10, pady=10)
        frame_filters.pack(fill="x", pady=(0, 15))

        tk.Label(frame_filters, text="Type and press ENTER\nor select from the list.", fg="#7f8c8d", bg="#ecf0f1",
                 font=("Arial", 9, "italic")).pack(pady=(0, 8))

        self.combo_filters = {}
        self.frame_dynamic_filters = tk.Frame(frame_filters, bg="#ecf0f1")
        self.frame_dynamic_filters.pack(fill="x")

        self.btn_reset = tk.Button(frame_filters, text="🔄 Reset Filters", command=self.reset_filters, bg="#e74c3c",
                                   fg="white", font=("Arial", 10, "bold"), bd=0, pady=4)
        self.btn_reset.pack(fill="x", pady=(15, 5))

        # --- Column Visibility Section ---
        self.frame_visibility = tk.LabelFrame(self.frame_left, text="👁️ Column Visibility", font=("Arial", 10, "bold"),
                                              bg="#ecf0f1", padx=10, pady=10)
        self.frame_visibility.pack(fill="x", pady=15)

        self.visible_columns_vars = {}
        self.inner_frame_visibility = tk.Frame(self.frame_visibility, bg="#ecf0f1")
        self.inner_frame_visibility.pack(fill="x")

        # --- NEW SECTION: Measure Visibility and Management ---
        self.frame_measures = tk.LabelFrame(self.frame_left, text="📏 Measure Management", font=("Arial", 10, "bold"),
                                          bg="#ecf0f1", padx=10, pady=10)
        self.frame_measures.pack(fill="x", pady=15)

        self.lbl_measures_status = tk.Label(self.frame_measures, text="Select a CODE", fg="#7f8c8d", bg="#ecf0f1",
                                         font=("Arial", 9, "italic"))
        self.lbl_measures_status.pack(pady=(0, 8))

        self.btn_toggle_measures = tk.Button(self.frame_measures, text="☑ Select All/None",
                                           command=self.toggle_measures, state="disabled", font=("Arial", 9), bd=0,
                                           bg="#bdc3c7", pady=2)
        self.btn_toggle_measures.pack(fill="x", pady=(0, 5))

        self.btn_rename_measure = tk.Button(self.frame_measures, text="✏️ Batch Rename",
                                             command=self.open_rename_measure, state="disabled", bg="#f39c12",
                                             fg="white", font=("Arial", 9, "bold"), bd=0, pady=4)
        self.btn_rename_measure.pack(fill="x", pady=(0, 10))

        self.inner_frame_measures = tk.Frame(self.frame_measures, bg="#ecf0f1")
        self.inner_frame_measures.pack(fill="x")

        # ==========================================
        # 3. RIGHT BAR: STATISTICS AND AGGREGATIONS
        # ==========================================
        frame_right = tk.LabelFrame(self.root, text="📊 Statistics Dashboard", font=("Arial", 10, "bold"), bg="#ecf0f1",
                                    padx=15, pady=15, width=280)
        frame_right.pack(side="right", fill="y", padx=15, pady=15)
        frame_right.pack_propagate(False)

        self.text_statistics = tk.Text(frame_right, state="disabled", wrap="word", bg="#ffffff", fg="#2c3e50",
                                         font=("Consolas", 10), bd=0, padx=5, pady=5)
        self.text_statistics.pack(fill="both", expand=True)

        # ==========================================
        # 4. CENTER: DATA TABLE AND INSTRUCTIONS
        # ==========================================
        frame_center = tk.Frame(self.root, bg="#ecf0f1")
        frame_center.pack(side="left", fill="both", expand=True, pady=15)

        frame_table_commands = tk.Frame(frame_center, bg="#ecf0f1")
        frame_table_commands.pack(fill="x", pady=(0, 10))

        lbl_instructions = tk.Label(frame_table_commands,
                                  text="💡 Double-click, press Enter or right-click to edit a row. Multi-selection supported.",
                                  bg="#fff9c4", fg="#333", font=("Arial", 10), justify="left", padx=10, pady=4)
        lbl_instructions.pack(side="left")

        self.btn_edit = tk.Button(frame_table_commands, text="✏️ Edit Selected", bg="#3498db", fg="white",
                                      font=("Arial", 10, "bold"), bd=0, padx=15, pady=4,
                                      command=lambda: self.open_multiple_edit())
        self.btn_edit.pack(side="right")

        scroll_y = ttk.Scrollbar(frame_center, orient="vertical")
        scroll_x = ttk.Scrollbar(frame_center, orient="horizontal")

        self.tree = ttk.Treeview(frame_center, yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set,
                                 selectmode="extended")

        scroll_y.config(command=self.tree.yview)
        scroll_x.config(command=self.tree.xview)

        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<Return>", lambda e: self.open_multiple_edit())

        self.right_menu = tk.Menu(self.root, tearoff=0)
        self.right_menu.add_command(label="✏️ Edit Selected", command=lambda: self.open_multiple_edit())
        self.tree.bind("<Button-3>", self.show_right_menu)
        self.tree.bind("<Double-1>", self.open_single_edit)

    # ==========================================
    # LOGIC: RIGHT CLICK MENU AND PATH
    # ==========================================
    def show_right_menu(self, event):
        if self.tree.selection():
            self.right_menu.tk_popup(event.x_root, event.y_root)

    def truncate_path(self, path_str):
        if not path_str: return ""
        p_str = str(path_str).replace("/", "\\")
        parts = p_str.split("\\")
        if len(parts) > 4:
            return f"...\\{parts[-4]}\\{parts[-3]}\\{parts[-2]}\\{parts[-1]}"
        return p_str

    # ==========================================
    # LOGIC: SQLITE DATABASE CONNECTION
    # ==========================================
    def load_db(self):
        file_path = filedialog.askopenfilename(parent=self.root, filetypes=[("SQLite Database", "*.db")])
        if not file_path: return

        self.set_loading(True, "⏳ Loading Database...")
        try:
            self.file_path_db = file_path
            conn = sqlite3.connect(file_path)
            self.df_complete = pd.read_sql_query("SELECT * FROM misurazioni", conn)
            conn.close()

            self.df_complete = self.df_complete.fillna("")
            for col in ['codice_pezzo', 'lotto', 'sezione', 'nome_misura', 'stato', 'fase']:
                if col in self.df_complete.columns:
                    self.df_complete[col] = self.df_complete[col].astype(str).str.strip()

            self.df_filtered = self.df_complete.copy()
            self.current_code = None  # Security reset

            self.initialize_column_checkboxes()
            self.build_table()
            self.initialize_filters()
            self.apply_filters()

        except Exception as e:
            messagebox.showerror("DB Error", f"Unable to read the database:\n{str(e)}", parent=self.root)
        finally:
            self.set_loading(False)
            if not self.df_complete.empty:
                self.lbl_file.config(text=f"📂 {Path(file_path).name} ({len(self.df_complete)} measurements)")

    # ==========================================
    # LOGIC: COLUMNS AND MEASURES VISIBILITY
    # ==========================================
    def initialize_column_checkboxes(self):
        for widget in self.inner_frame_visibility.winfo_children():
            widget.destroy()
        self.visible_columns_vars.clear()

        for col in self.df_complete.columns:
            var = tk.BooleanVar(value=True)
            if col == 'id': var.set(False)

            check_text = self.get_visual_name(col)
            chk = tk.Checkbutton(self.inner_frame_visibility, text=check_text, bg="#ecf0f1", activebackground="#ecf0f1",
                                 variable=var, command=self.update_visible_columns)
            chk.pack(anchor="w")
            self.visible_columns_vars[col] = var

        self.frame_left.update_idletasks()
        self.canvas_left.configure(scrollregion=self.canvas_left.bbox("all"))

    def update_visible_columns(self):
        active_columns = [col for col, var in self.visible_columns_vars.items() if var.get()]
        if not active_columns: active_columns = ['id']
        self.tree["displaycolumns"] = active_columns

    def build_measure_filters(self, code):
        for widget in self.inner_frame_measures.winfo_children():
            widget.destroy()
        self.visible_measures_vars.clear()

        unique_measures = sorted(self.df_complete[self.df_complete['codice_pezzo'].astype(str).str.upper() == code][
                                   'nome_misura'].unique())

        for meas in unique_measures:
            var = tk.BooleanVar(value=True)
            chk = tk.Checkbutton(self.inner_frame_measures, text=meas, variable=var, bg="#ecf0f1",
                                 activebackground="#ecf0f1", command=self.apply_filters)
            chk.pack(anchor="w")
            self.visible_measures_vars[meas] = var

        self.lbl_measures_status.config(text=f"Measures for code:", fg="#2c3e50", font=("Arial", 9, "bold"))
        self.btn_rename_measure.config(state="normal")
        self.btn_toggle_measures.config(state="normal")

        self.frame_left.update_idletasks()
        self.canvas_left.configure(scrollregion=self.canvas_left.bbox("all"))
        self.canvas_left.yview_moveto(0)

    def clear_measure_filters(self):
        for widget in self.inner_frame_measures.winfo_children(): widget.destroy()
        self.visible_measures_vars.clear()
        self.lbl_measures_status.config(text="Select a CODE", fg="#7f8c8d", font=("Arial", 9, "italic"))
        self.btn_rename_measure.config(state="disabled")
        self.btn_toggle_measures.config(state="disabled")

        self.frame_left.update_idletasks()
        self.canvas_left.configure(scrollregion=self.canvas_left.bbox("all"))

    def toggle_measures(self):
        if not self.visible_measures_vars: return
        current_states = [var.get() for var in self.visible_measures_vars.values()]
        new_state = not all(current_states)
        for var in self.visible_measures_vars.values():
            var.set(new_state)
        self.apply_filters()

    # ==========================================
    # LOGIC: GLOBAL MEASURE RENAME
    # ==========================================
    def open_rename_measure(self):
        if not self.current_code: return

        current_measures = list(self.visible_measures_vars.keys())
        if not current_measures: return

        popup = tk.Toplevel(self.root)
        popup.title("Rename Measure (Global DB Action)")
        popup.geometry("450x300")
        popup.configure(bg="#ecf0f1")
        popup.transient(self.root)
        popup.grab_set()

        tk.Label(popup, text=f"Selected Code: {self.current_code}", font=("Arial", 11, "bold"),
                 bg="#ecf0f1").pack(pady=15)

        tk.Label(popup, text="Choose the measure to fix:", bg="#ecf0f1", font=("Arial", 10)).pack(pady=(5, 0))
        combo_measures = ttk.Combobox(popup, values=current_measures, state="readonly", width=40, font=("Arial", 10))
        combo_measures.pack(pady=5)
        combo_measures.current(0)

        tk.Label(popup, text="New measure name:", bg="#ecf0f1", font=("Arial", 10)).pack(pady=(15, 0))
        entry_new = tk.Entry(popup, width=43, font=("Arial", 10))
        entry_new.pack(pady=5)

        def save_rename():
            old_name = combo_measures.get()
            new_name = entry_new.get().strip()

            if not new_name or old_name == new_name: return

            self.set_loading(True, "⏳ Batch modifying Database...")
            popup.destroy()

            try:
                conn = sqlite3.connect(self.file_path_db)
                cur = conn.cursor()
                cur.execute("UPDATE misurazioni SET nome_misura = ? WHERE UPPER(codice_pezzo) = ? AND nome_misura = ?",
                            (new_name, self.current_code, old_name))
                rows_involved = cur.rowcount
                conn.commit()
                conn.close()

                mask = (self.df_complete['codice_pezzo'].astype(str).str.upper() == self.current_code) & (
                            self.df_complete['nome_misura'] == old_name)
                self.df_complete.loc[mask, 'nome_misura'] = new_name

                self.current_code = None
                self.apply_filters()

                messagebox.showinfo("Success",
                                    f"✅ Measure successfully renamed!\n\nFrom: '{old_name}'\nTo: '{new_name}'\nModified rows: {rows_involved}",
                                    parent=self.root)

            except Exception as e:
                messagebox.showerror("Save Error", f"Error while updating DB:\n{str(e)}",
                                     parent=self.root)
            finally:
                self.set_loading(False)

        tk.Button(popup, text="⚠️ Modify across whole Database", command=save_rename, bg="#c0392b", fg="white",
                  font=("Arial", 10, "bold"), bd=0, padx=15, pady=6).pack(pady=25)

    # ==========================================
    # LOGIC: SINGLE AND MULTIPLE GRID EDIT
    # ==========================================
    def open_single_edit(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell": return
        clicked_item = self.tree.identify_row(event.y)
        if not clicked_item: return
        self._execute_edit([clicked_item])

    def open_multiple_edit(self, event=None):
        selection = self.tree.selection()
        if not selection: return
        self._execute_edit(selection)

    def _execute_edit(self, items_list):
        columns = list(self.df_complete.columns)
        if 'id' not in columns:
            messagebox.showerror("Error", "The 'id' column (Primary Key) is missing. Unable to update DB.",
                                 parent=self.root)
            return

        id_idx = columns.index('id')
        ids_to_modify = [str(self.tree.item(item, "values")[id_idx]) for item in items_list]

        first_row_values = self.tree.item(items_list[0], "values")

        popup = tk.Toplevel(self.root)
        popup_title = f"Multiple Edit ({len(items_list)} selected rows)" if len(
            items_list) > 1 else "Single Row Edit"
        popup.title(popup_title)
        popup.geometry("600x480")
        popup.configure(bg="#ecf0f1")
        popup.transient(self.root)
        popup.grab_set()

        msg = "Overwrite the fields you wish to update.\nFields left IN GRAY will not be modified."
        tk.Label(popup, text=msg, bg="#fff9c4", fg="#333", font=("Arial", 9), pady=10).pack(fill="x")

        frame_form = tk.Frame(popup, padx=20, pady=10, bg="#ecf0f1")
        frame_form.pack(fill="both", expand=True)

        protected_fields = ['id', 'file_pdf', 'cartella_padre', 'misurato_mm', 'nominale_mm', 'tolleranza_piu',
                          'tolleranza_meno', 'deviazione']
        editable_fields = [c for c in columns if c not in protected_fields]

        entry_dict = {}

        def activate_field(event):
            widget = event.widget
            if widget.cget("fg") == "gray" and event.keysym not in ("Tab", "Shift_L", "Shift_R", "Return"):
                widget.config(fg="black")

        for row_idx, col in enumerate(editable_fields):
            col_idx = columns.index(col)
            original_val = first_row_values[col_idx]

            label_text = self.get_visual_name(col).upper() + ":"
            tk.Label(frame_form, text=label_text, font=("Arial", 10, "bold"), bg="#ecf0f1").grid(row=row_idx,
                                                                                                  column=0, sticky="e",
                                                                                                  pady=8, padx=10)

            entry = tk.Entry(frame_form, width=40, font=("Arial", 10))
            entry.grid(row=row_idx, column=1, sticky="w", pady=8)

            entry.insert(0, str(original_val))
            entry.config(fg="gray")

            entry.bind("<Key>", activate_field)
            entry.bind("<<Paste>>", lambda e, w=entry: w.config(fg="black"))

            entry_dict[col] = entry

        def save_changes():
            fields_to_update = {}
            for col, entry in entry_dict.items():
                if entry.cget("fg") == "black":
                    fields_to_update[col] = entry.get().strip()

            if not fields_to_update:
                popup.destroy()
                return

            self.set_loading(True, "⏳ Saving changes to Database...")
            popup.destroy()

            try:
                conn = sqlite3.connect(self.file_path_db)
                cur = conn.cursor()

                set_clause = ", ".join([f"{c} = ?" for c in fields_to_update.keys()])
                values = list(fields_to_update.values())

                placeholders = ','.join('?' for _ in ids_to_modify)
                query = f"UPDATE misurazioni SET {set_clause} WHERE id IN ({placeholders})"

                cur.execute(query, values + ids_to_modify)
                conn.commit()
                conn.close()

                for col, val in fields_to_update.items():
                    self.df_complete.loc[self.df_complete['id'].astype(str).isin(ids_to_modify), col] = val

                self.apply_filters()

                pretty_modified_fields = [self.get_visual_name(c) for c in fields_to_update.keys()]
                final_msg = f"✅ {len(ids_to_modify)} rows successfully updated in fields:\n{', '.join(pretty_modified_fields)}"
                if len(ids_to_modify) == 1:
                    final_msg = f"✅ Row successfully updated in fields:\n{', '.join(pretty_modified_fields)}"

                messagebox.showinfo("Done", final_msg, parent=self.root)

            except Exception as e:
                messagebox.showerror("Save Error", f"Error during database update:\n{str(e)}",
                                     parent=self.root)
            finally:
                self.set_loading(False)

        tk.Button(popup, text="💾 Save Changes", command=save_changes, bg="#27ae60", fg="white",
                  font=("Arial", 11, "bold"), bd=0, padx=15, pady=6).pack(pady=20)

    # ==========================================
    # LOGIC: TABLE INTERFACE AND CASCADING FILTERS
    # ==========================================
    def build_table(self):
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = list(self.df_complete.columns)
        self.tree["show"] = "headings"

        for col in self.df_complete.columns:
            self.tree.heading(col, text=self.get_visual_name(col))

            if col == 'id':
                self.tree.column(col, width=50, anchor="center")
            elif col == 'cartella_padre':
                self.tree.column(col, width=70, anchor="center")
            elif col == 'codice_pezzo':
                self.tree.column(col, width=65, anchor="center")
            elif col == 'lotto':
                self.tree.column(col, width=65, anchor="center")
            elif col == 'nome_misura':
                self.tree.column(col, width=180, anchor="center")
            elif col in ['stato', 'fase']:
                self.tree.column(col, width=60, anchor="center")
            elif col == 'sezione':
                self.tree.column(col, width=60, anchor="center")
            elif col in ['tolleranza_piu', 'tolleranza_meno']:
                self.tree.column(col, width=50, anchor="e")
            elif col in ['misurato_mm', 'deviazione', 'nominale_mm', 'extra_dev']:
                self.tree.column(col, width=90, anchor="e")
            elif col == 'file_pdf':
                self.tree.column(col, width=400, anchor="w")
            else:
                self.tree.column(col, width=110, anchor="w")

        self.update_visible_columns()

    def populate_table(self, df):
        self.tree.delete(*self.tree.get_children())
        df_display = df.head(1000)

        col_list = list(self.df_complete.columns)

        for _, row in df_display.iterrows():
            row_values = []
            for col in col_list:
                val = row[col]
                if col == 'file_pdf':
                    val = self.truncate_path(val)
                row_values.append(val)

            self.tree.insert("", "end", values=row_values)

    def initialize_filters(self):
        for widget in self.frame_dynamic_filters.winfo_children(): widget.destroy()
        self.combo_filters.clear()

        columns_for_filters = ['codice_pezzo', 'fase', 'lotto', 'sezione', 'stato', 'nome_misura']
        present_columns = [col for col in columns_for_filters if col in self.df_complete.columns]

        for col in present_columns:
            label_text = self.get_visual_name(col).upper()
            tk.Label(self.frame_dynamic_filters, text=label_text, bg="#ecf0f1", font=("Arial", 9, "bold")).pack(
                anchor="w", pady=(5, 0))

            combo = ttk.Combobox(self.frame_dynamic_filters, state="normal")
            combo.pack(fill="x")

            combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())
            combo.bind("<Return>", lambda e: self.apply_filters())

            self.combo_filters[col] = combo

    def reset_filters(self):
        for combo in self.combo_filters.values():
            combo.set("ALL")
        self.apply_filters()

    def apply_filters(self, event=None):
        if self.df_complete.empty: return

        self.set_loading(True, "⏳ Applying filters...")
        try:
            df = self.df_complete.copy()

            active_filters = {}
            for col, combo in self.combo_filters.items():
                val = combo.get().strip().upper()
                if val and val != "ALL":
                    active_filters[col] = val
                    df = df[df[col].astype(str).str.upper() == val]

            selected_code = "ALL"
            if 'codice_pezzo' in self.combo_filters:
                selected_code = self.combo_filters['codice_pezzo'].get().strip().upper()

            if selected_code and selected_code != "ALL":
                if self.current_code != selected_code:
                    self.current_code = selected_code
                    self.build_measure_filters(selected_code)

                active_measures = [m for m, var in self.visible_measures_vars.items() if var.get()]

                if len(active_measures) < len(self.visible_measures_vars):
                    df = df[df['nome_misura'].isin(active_measures)]
            else:
                if self.current_code is not None:
                    self.current_code = None
                    self.clear_measure_filters()

            self.df_filtered = df
            self.populate_table(self.df_filtered)
            self.update_statistics()

            for col, combo in self.combo_filters.items():
                current_value = combo.get().strip().upper()

                df_temp = self.df_complete.copy()
                for c_active, v_active in active_filters.items():
                    if c_active != col:
                        df_temp = df_temp[df_temp[c_active].astype(str).str.upper() == v_active]

                new_options = ["ALL"] + sorted([str(x) for x in df_temp[col].unique() if str(x) != ""])
                combo['values'] = new_options

                if not current_value or current_value == "ALL":
                    combo.set("ALL")
                elif current_value in [opt.upper() for opt in new_options]:
                    combo.set(current_value)
                else:
                    combo.set("ALL")

        finally:
            self.set_loading(False)
            warning = f" (Showing first 1000)" if len(self.df_filtered) > 1000 else ""

            file_name = Path(self.file_path_db).name if self.file_path_db else "Unknown"
            self.lbl_file.config(text=f"📂 {file_name} - Found: {len(self.df_filtered)} rows{warning}")

    # ==========================================
    # LOGIC: ADVANCED CUSTOM STATISTICS
    # ==========================================
    def update_statistics(self):
        self.text_statistics.config(state="normal")
        self.text_statistics.delete(1.0, tk.END)

        df = self.df_filtered
        if df.empty:
            self.text_statistics.insert(tk.END, "No measurements matching the filters.")
            self.text_statistics.config(state="disabled")
            return

        statistics = []
        statistics.append(f"📌 TOTAL MEASUREMENTS: {len(df)}\n")

        if 'file_pdf' in df.columns:
            total_parts = df['file_pdf'].nunique()
            statistics.append(f"📄 TOTAL PARTS (PDF): {total_parts}\n")
        else:
            statistics.append("\n")

        statistics.append("-" * 35 + "\n")

        if 'codice_pezzo' in df.columns:
            statistics.append(f"📦 UNIQUE CODES: {df['codice_pezzo'].nunique()}\n")
            if 'lotto' in df.columns:
                statistics.append("🏷️ BATCHES PER PART CODE:")
                for cod, count in df.groupby('codice_pezzo')['lotto'].nunique().items():
                    statistics.append(f"  • {cod if cod else '[No Code]'}: {count} batches")
                statistics.append("\n")

                if 'fase' in df.columns:
                    statistics.append("⚙️ BATCHES PER CODE AND PHASE:")
                    for (cod, phase), count in df.groupby(['codice_pezzo', 'fase'])['lotto'].nunique().items():
                        statistics.append(
                            f"  • {cod if cod else '[No Code]'} | {phase if phase else '[No Phase]'}: {count} batches")
                    statistics.append("\n")

        if 'file_pdf' in df.columns and 'stato' in df.columns:
            statistics.append("-" * 35)
            statistics.append("\n⚖️ QUALITY ON PARTS (PHYSICAL PDFs):")
            rejected_pdfs = df[df['stato'].str.upper() == 'NON OK']['file_pdf'].nunique()
            ok_pdfs = total_parts - rejected_pdfs

            perc_ok = (ok_pdfs / total_parts) * 100 if total_parts > 0 else 0
            perc_ko = (rejected_pdfs / total_parts) * 100 if total_parts > 0 else 0

            statistics.append(f"  - OK Parts: {ok_pdfs} ({perc_ok:.1f}%)")
            statistics.append(f"  - Scrap Parts: {rejected_pdfs} ({perc_ko:.1f}%)\n")

        if 'stato' in df.columns:
            statistics.append("-" * 35)
            statistics.append("\n🔬 QUALITY ON INDIVIDUAL MEASURES:")
            for status, count in df['stato'].value_counts().items():
                if status.strip() == "": status = "NOT EVALUATED"
                statistics.append(f"  - {status}: {count} ({(count / len(df)) * 100:.1f}%)")

        self.text_statistics.insert(tk.END, "\n".join(statistics))
        self.text_statistics.config(state="disabled")

    # ==========================================
    # LOGIC: EXPORT
    # ==========================================
    def export_data(self):
        if self.df_filtered.empty:
            return messagebox.showinfo("Empty", "No data to export.", parent=self.root)

        df_export = self.df_filtered.drop(columns=['id'], errors='ignore')
        df_export = df_export.rename(columns=self.display_names)

        file_path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".xlsx",
                                                 filetypes=[("Excel Files", "*.xlsx"), ("CSV Files", "*.csv")])

        if file_path:
            self.set_loading(True, "⏳ Generating file...")
            try:
                if file_path.endswith('.csv'):
                    df_export.to_csv(file_path, index=False, sep=";")
                else:
                    df_export.to_excel(file_path, index=False)
                messagebox.showinfo("Success", f"Data successfully exported to:\n{Path(file_path).name}",
                                    parent=self.root)
            except Exception as e:
                messagebox.showerror("Error", f"Unable to save the file:\n{str(e)}", parent=self.root)
            finally:
                self.set_loading(False)


if __name__ == "__main__":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Calypso.Navigator.Pro")
    except Exception:
        pass
    root = tk.Tk()
    app = SQLiteNavigatorApp(root)
    root.mainloop()
