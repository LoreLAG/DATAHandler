import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import sqlite3
from pathlib import Path
import ctypes


class NavigatoreSQLiteApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Navigatore Database SQLite (Pro Edition)")
        self.root.geometry("1400x850")
        self.root.minsize(1200, 700)
        self.root.configure(bg="#ecf0f1")

        try:
            self.root.state('zoomed')  # Comando per Windows
        except tk.TclError:
            self.root.attributes('-zoomed', True)  # Alternativa per Linux/Mac

        # Motore Dati
        self.df_completo = pd.DataFrame()
        self.df_filtrato = pd.DataFrame()
        self.file_path_db = None

        # Gestione Pannello Misure Dinamico
        self.codice_corrente = None
        self.misure_visibili_vars = {}

        # ==========================================
        # DIZIONARIO TRADUTTORE: Nome DB -> Nome Visualizzato
        # ==========================================
        self.nomi_display = {
            'id': 'id',
            'file_pdf': 'File',
            'cartella_padre': 'Cartella',
            'codice_pezzo': 'Codice',
            'lotto': 'Lotto',
            'sezione': 'Sezione',
            'nome_misura': 'Misura',
            'misurato_mm': 'Misurato',
            'nominale_mm': 'Nominale',
            'tolleranza_piu': 'T+',
            'tolleranza_meno': 'T-',
            'deviazione': 'Scostamento',
            'extra_dev': 'Extra Dev.',
            'stato': 'Stato',
            'fase': 'Fase'
        }

        self.setup_ui()

    def get_nome_visivo(self, col_db):
        """Restituisce il nome formattato se esiste, altrimenti capitalizza quello del DB."""
        return self.nomi_display.get(col_db, col_db.replace("_", " ").title())

    # ==========================================
    # LOGICA: BLOCCO INTERFACCIA DURANTE IL LAVORO
    # ==========================================
    def imposta_caricamento(self, in_caricamento=True, messaggio="⏳ Elaborazione in corso..."):
        """Blocca l'UI e mostra il cursore di caricamento, o sblocca tutto a fine lavoro."""
        if in_caricamento:
            self.root.config(cursor="watch")
            self.lbl_file.config(text=messaggio, fg="#f1c40f")

            self.btn_carica.config(state="disabled")
            self.btn_esporta.config(state="disabled")
            self.btn_reset.config(state="disabled")
            self.btn_modifica.config(state="disabled")
            self.btn_rinomina_misura.config(state="disabled")
            self.btn_toggle_misure.config(state="disabled")

            self.root.update()
        else:
            self.root.config(cursor="")
            self.lbl_file.config(fg="white")

            self.btn_carica.config(state="normal")
            self.btn_esporta.config(state="normal")
            self.btn_reset.config(state="normal")
            self.btn_modifica.config(state="normal")

            if self.codice_corrente:
                self.btn_rinomina_misura.config(state="normal")
                self.btn_toggle_misure.config(state="normal")

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Treeview", rowheight=26, font=("Arial", 10))
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"), background="#d5d8dc")

        # ==========================================
        # 1. TOP BAR: CARICAMENTO FILE
        # ==========================================
        frame_top = tk.Frame(self.root, bg="#1c2833", pady=15, padx=20)
        frame_top.pack(fill="x", side="top")

        self.lbl_file = tk.Label(frame_top, text="Nessun Database caricato", bg="#1c2833", fg="white",
                                 font=("Arial", 12, "bold"))
        self.lbl_file.pack(side="left", padx=10)

        self.btn_carica = tk.Button(frame_top, text="📂 Carica Database SQLite (.db)", command=self.carica_db,
                                    bg="#3498db", fg="white", font=("Arial", 10, "bold"), bd=0, padx=15, pady=4)
        self.btn_carica.pack(side="right")

        self.btn_esporta = tk.Button(frame_top, text="💾 Esporta in Excel / CSV", command=self.esporta_dati,
                                     bg="#27ae60", fg="white", font=("Arial", 10, "bold"), bd=0, padx=15, pady=4)
        self.btn_esporta.pack(side="right", padx=10)

        # ==========================================
        # 2. LEFT BAR: SCORREVOLE GLOBALE
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

        # --- Sezione Filtri ---
        frame_filtri = tk.LabelFrame(self.frame_left, text="🔍 Filtri Dinamici", font=("Arial", 10, "bold"),
                                     bg="#ecf0f1", padx=10, pady=10)
        frame_filtri.pack(fill="x", pady=(0, 15))

        tk.Label(frame_filtri, text="Digita e premi INVIO\no seleziona dalla lista.", fg="#7f8c8d", bg="#ecf0f1",
                 font=("Arial", 9, "italic")).pack(pady=(0, 8))

        self.filtri_combo = {}
        self.frame_filtri_dinamici = tk.Frame(frame_filtri, bg="#ecf0f1")
        self.frame_filtri_dinamici.pack(fill="x")

        self.btn_reset = tk.Button(frame_filtri, text="🔄 Resetta Filtri", command=self.reset_filtri, bg="#e74c3c",
                                   fg="white", font=("Arial", 10, "bold"), bd=0, pady=4)
        self.btn_reset.pack(fill="x", pady=(15, 5))

        # --- Sezione Visibilità Colonne ---
        self.frame_visibilita = tk.LabelFrame(self.frame_left, text="👁️ Visibilità Colonne", font=("Arial", 10, "bold"),
                                              bg="#ecf0f1", padx=10, pady=10)
        self.frame_visibilita.pack(fill="x", pady=15)

        self.colonne_visibili_vars = {}
        self.inner_frame_visibilita = tk.Frame(self.frame_visibilita, bg="#ecf0f1")
        self.inner_frame_visibilita.pack(fill="x")

        # --- NUOVA SEZIONE: Visibilità e Gestione Misure ---
        self.frame_misure = tk.LabelFrame(self.frame_left, text="📏 Gestione Misure", font=("Arial", 10, "bold"),
                                          bg="#ecf0f1", padx=10, pady=10)
        self.frame_misure.pack(fill="x", pady=15)

        self.lbl_stato_misure = tk.Label(self.frame_misure, text="Seleziona un CODICE", fg="#7f8c8d", bg="#ecf0f1",
                                         font=("Arial", 9, "italic"))
        self.lbl_stato_misure.pack(pady=(0, 8))

        self.btn_toggle_misure = tk.Button(self.frame_misure, text="☑ Seleziona Tutto/Nessuno",
                                           command=self.toggle_misure, state="disabled", font=("Arial", 9), bd=0,
                                           bg="#bdc3c7", pady=2)
        self.btn_toggle_misure.pack(fill="x", pady=(0, 5))

        self.btn_rinomina_misura = tk.Button(self.frame_misure, text="✏️ Rinomina in Blocco",
                                             command=self.apri_rinomina_misura, state="disabled", bg="#f39c12",
                                             fg="white", font=("Arial", 9, "bold"), bd=0, pady=4)
        self.btn_rinomina_misura.pack(fill="x", pady=(0, 10))

        self.inner_frame_misure = tk.Frame(self.frame_misure, bg="#ecf0f1")
        self.inner_frame_misure.pack(fill="x")

        # ==========================================
        # 3. RIGHT BAR: STATISTICHE E AGGREGAZIONI
        # ==========================================
        frame_right = tk.LabelFrame(self.root, text="📊 Cruscotto Statistiche", font=("Arial", 10, "bold"), bg="#ecf0f1",
                                    padx=15, pady=15, width=280)
        frame_right.pack(side="right", fill="y", padx=15, pady=15)
        frame_right.pack_propagate(False)

        self.testo_statistiche = tk.Text(frame_right, state="disabled", wrap="word", bg="#ffffff", fg="#2c3e50",
                                         font=("Consolas", 10), bd=0, padx=5, pady=5)
        self.testo_statistiche.pack(fill="both", expand=True)

        # ==========================================
        # 4. CENTER: TABELLA DATI E ISTRUZIONI
        # ==========================================
        frame_center = tk.Frame(self.root, bg="#ecf0f1")
        frame_center.pack(side="left", fill="both", expand=True, pady=15)

        frame_comandi_tabella = tk.Frame(frame_center, bg="#ecf0f1")
        frame_comandi_tabella.pack(fill="x", pady=(0, 10))

        lbl_istruzioni = tk.Label(frame_comandi_tabella,
                                  text="💡 Per modificare una riga usa doppio click, invio o tasto destro. Multi-selezione supportata.",
                                  bg="#fff9c4", fg="#333", font=("Arial", 10), justify="left", padx=10, pady=4)
        lbl_istruzioni.pack(side="left")

        self.btn_modifica = tk.Button(frame_comandi_tabella, text="✏️ Modifica Selezionati", bg="#3498db", fg="white",
                                      font=("Arial", 10, "bold"), bd=0, padx=15, pady=4,
                                      command=lambda: self.apri_modifica_multipla())
        self.btn_modifica.pack(side="right")

        scroll_y = ttk.Scrollbar(frame_center, orient="vertical")
        scroll_x = ttk.Scrollbar(frame_center, orient="horizontal")

        self.tree = ttk.Treeview(frame_center, yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set,
                                 selectmode="extended")

        scroll_y.config(command=self.tree.yview)
        scroll_x.config(command=self.tree.xview)

        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<Return>", lambda e: self.apri_modifica_multipla())

        self.menu_destro = tk.Menu(self.root, tearoff=0)
        self.menu_destro.add_command(label="✏️ Modifica Selezionati", command=lambda: self.apri_modifica_multipla())
        self.tree.bind("<Button-3>", self.mostra_menu_destro)
        self.tree.bind("<Double-1>", self.apri_modifica_singola)

    # ==========================================
    # LOGICA: MENU TASTO DESTRO E PATH
    # ==========================================
    def mostra_menu_destro(self, event):
        if self.tree.selection():
            self.menu_destro.tk_popup(event.x_root, event.y_root)

    def tronca_percorso(self, path_str):
        if not path_str: return ""
        p_str = str(path_str).replace("/", "\\")
        parts = p_str.split("\\")
        if len(parts) > 4:
            return f"...\\{parts[-4]}\\{parts[-3]}\\{parts[-2]}\\{parts[-1]}"
        return p_str

    # ==========================================
    # LOGICA: CONNESSIONE AL DATABASE SQLITE
    # ==========================================
    def carica_db(self):
        # FIX: Aggiunto parent=self.root
        file_path = filedialog.askopenfilename(parent=self.root, filetypes=[("Database SQLite", "*.db")])
        if not file_path: return

        self.imposta_caricamento(True, "⏳ Caricamento Database in corso...")
        try:
            self.file_path_db = file_path
            conn = sqlite3.connect(file_path)
            self.df_completo = pd.read_sql_query("SELECT * FROM misurazioni", conn)
            conn.close()

            self.df_completo = self.df_completo.fillna("")
            for col in ['codice_pezzo', 'lotto', 'sezione', 'nome_misura', 'stato', 'fase']:
                if col in self.df_completo.columns:
                    self.df_completo[col] = self.df_completo[col].astype(str).str.strip()

            self.df_filtrato = self.df_completo.copy()
            self.codice_corrente = None  # Reset sicurezza

            self.inizializza_checkbox_colonne()
            self.costruisci_tabella()
            self.inizializza_filtri()
            self.applica_filtri()

        except Exception as e:
            # FIX: Aggiunto parent=self.root
            messagebox.showerror("Errore DB", f"Impossibile leggere il database:\n{str(e)}", parent=self.root)
        finally:
            self.imposta_caricamento(False)
            if not self.df_completo.empty:
                self.lbl_file.config(text=f"📂 {Path(file_path).name} ({len(self.df_completo)} misurazioni)")

    # ==========================================
    # LOGICA: VISIBILITÀ COLONNE E MISURE
    # ==========================================
    def inizializza_checkbox_colonne(self):
        for widget in self.inner_frame_visibilita.winfo_children():
            widget.destroy()
        self.colonne_visibili_vars.clear()

        for col in self.df_completo.columns:
            var = tk.BooleanVar(value=True)
            if col == 'id': var.set(False)

            testo_chk = self.get_nome_visivo(col)
            chk = tk.Checkbutton(self.inner_frame_visibilita, text=testo_chk, bg="#ecf0f1", activebackground="#ecf0f1",
                                 variable=var, command=self.aggiorna_colonne_visibili)
            chk.pack(anchor="w")
            self.colonne_visibili_vars[col] = var

        self.frame_left.update_idletasks()
        self.canvas_left.configure(scrollregion=self.canvas_left.bbox("all"))

    def aggiorna_colonne_visibili(self):
        colonne_attive = [col for col, var in self.colonne_visibili_vars.items() if var.get()]
        if not colonne_attive: colonne_attive = ['id']
        self.tree["displaycolumns"] = colonne_attive

    def costruisci_filtri_misure(self, codice):
        for widget in self.inner_frame_misure.winfo_children():
            widget.destroy()
        self.misure_visibili_vars.clear()

        misure_uniche = sorted(self.df_completo[self.df_completo['codice_pezzo'].astype(str).str.upper() == codice][
                                   'nome_misura'].unique())

        for mis in misure_uniche:
            var = tk.BooleanVar(value=True)
            chk = tk.Checkbutton(self.inner_frame_misure, text=mis, variable=var, bg="#ecf0f1",
                                 activebackground="#ecf0f1", command=self.applica_filtri)
            chk.pack(anchor="w")
            self.misure_visibili_vars[mis] = var

        self.lbl_stato_misure.config(text=f"Misure del codice:", fg="#2c3e50", font=("Arial", 9, "bold"))
        self.btn_rinomina_misura.config(state="normal")
        self.btn_toggle_misure.config(state="normal")

        self.frame_left.update_idletasks()
        self.canvas_left.configure(scrollregion=self.canvas_left.bbox("all"))
        self.canvas_left.yview_moveto(0)

    def svuota_filtri_misure(self):
        for widget in self.inner_frame_misure.winfo_children(): widget.destroy()
        self.misure_visibili_vars.clear()
        self.lbl_stato_misure.config(text="Seleziona un CODICE", fg="#7f8c8d", font=("Arial", 9, "italic"))
        self.btn_rinomina_misura.config(state="disabled")
        self.btn_toggle_misure.config(state="disabled")

        self.frame_left.update_idletasks()
        self.canvas_left.configure(scrollregion=self.canvas_left.bbox("all"))

    def toggle_misure(self):
        if not self.misure_visibili_vars: return
        attuali = [var.get() for var in self.misure_visibili_vars.values()]
        nuovo_stato = not all(attuali)
        for var in self.misure_visibili_vars.values():
            var.set(nuovo_stato)
        self.applica_filtri()

    # ==========================================
    # LOGICA: RINOMINA MISURA GLOBALE
    # ==========================================
    def apri_rinomina_misura(self):
        if not self.codice_corrente: return

        misure_attuali = list(self.misure_visibili_vars.keys())
        if not misure_attuali: return

        popup = tk.Toplevel(self.root)
        popup.title("Rinomina Misura (Azione Globale sul DB)")
        popup.geometry("450x300")
        popup.configure(bg="#ecf0f1")
        popup.transient(self.root)
        popup.grab_set()

        tk.Label(popup, text=f"Codice selezionato: {self.codice_corrente}", font=("Arial", 11, "bold"),
                 bg="#ecf0f1").pack(pady=15)

        tk.Label(popup, text="Scegli la misura da correggere:", bg="#ecf0f1", font=("Arial", 10)).pack(pady=(5, 0))
        combo_misure = ttk.Combobox(popup, values=misure_attuali, state="readonly", width=40, font=("Arial", 10))
        combo_misure.pack(pady=5)
        combo_misure.current(0)

        tk.Label(popup, text="Nuovo nome misura:", bg="#ecf0f1", font=("Arial", 10)).pack(pady=(15, 0))
        entry_nuovo = tk.Entry(popup, width=43, font=("Arial", 10))
        entry_nuovo.pack(pady=5)

        def salva_rinomina():
            vecchio_nome = combo_misure.get()
            nuovo_nome = entry_nuovo.get().strip()

            if not nuovo_nome or vecchio_nome == nuovo_nome: return

            self.imposta_caricamento(True, "⏳ Modifica in blocco nel Database...")
            popup.destroy()

            try:
                conn = sqlite3.connect(self.file_path_db)
                cur = conn.cursor()
                cur.execute("UPDATE misurazioni SET nome_misura = ? WHERE UPPER(codice_pezzo) = ? AND nome_misura = ?",
                            (nuovo_nome, self.codice_corrente, vecchio_nome))
                righe_coinvolte = cur.rowcount
                conn.commit()
                conn.close()

                mask = (self.df_completo['codice_pezzo'].astype(str).str.upper() == self.codice_corrente) & (
                            self.df_completo['nome_misura'] == vecchio_nome)
                self.df_completo.loc[mask, 'nome_misura'] = nuovo_nome

                self.codice_corrente = None
                self.applica_filtri()

                # FIX: Aggiunto parent=self.root dato che il popup è già distrutto
                messagebox.showinfo("Successo",
                                    f"✅ Misura rinominata con successo!\n\nDa: '{vecchio_nome}'\nA: '{nuovo_nome}'\nRighe modificate: {righe_coinvolte}",
                                    parent=self.root)

            except Exception as e:
                # FIX: Aggiunto parent=self.root
                messagebox.showerror("Errore Salvataggio", f"Errore durante l'aggiornamento del DB:\n{str(e)}",
                                     parent=self.root)
            finally:
                self.imposta_caricamento(False)

        tk.Button(popup, text="⚠️ Modifica su tutto il Database", command=salva_rinomina, bg="#c0392b", fg="white",
                  font=("Arial", 10, "bold"), bd=0, padx=15, pady=6).pack(pady=25)

    # ==========================================
    # LOGICA: MODIFICA SINGOLA E MULTIPLA A GRIGLIA
    # ==========================================
    def apri_modifica_singola(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell": return
        item_cliccato = self.tree.identify_row(event.y)
        if not item_cliccato: return
        self._esegui_modifica([item_cliccato])

    def apri_modifica_multipla(self, event=None):
        selezione = self.tree.selection()
        if not selezione: return
        self._esegui_modifica(selezione)

    def _esegui_modifica(self, lista_items):
        colonne = list(self.df_completo.columns)
        if 'id' not in colonne:
            messagebox.showerror("Errore", "La colonna 'id' (Primary Key) è mancante. Impossibile aggiornare il DB.",
                                 parent=self.root)
            return

        id_idx = colonne.index('id')
        ids_da_modificare = [str(self.tree.item(item, "values")[id_idx]) for item in lista_items]

        valori_prima_riga = self.tree.item(lista_items[0], "values")

        popup = tk.Toplevel(self.root)
        titolo_popup = f"Modifica Multipla ({len(lista_items)} righe selezionate)" if len(
            lista_items) > 1 else "Modifica Singola Riga"
        popup.title(titolo_popup)
        popup.geometry("600x480")
        popup.configure(bg="#ecf0f1")
        popup.transient(self.root)
        popup.grab_set()

        msg = "Sovrascrivi i campi che desideri aggiornare.\nI campi lasciati IN GRIGIO non verranno modificati."
        tk.Label(popup, text=msg, bg="#fff9c4", fg="#333", font=("Arial", 9), pady=10).pack(fill="x")

        frame_form = tk.Frame(popup, padx=20, pady=10, bg="#ecf0f1")
        frame_form.pack(fill="both", expand=True)

        campi_protetti = ['id', 'file_pdf', 'cartella_padre', 'misurato_mm', 'nominale_mm', 'tolleranza_piu',
                          'tolleranza_meno', 'deviazione']
        campi_modificabili = [c for c in colonne if c not in campi_protetti]

        entry_dict = {}

        def attiva_campo(event):
            widget = event.widget
            if widget.cget("fg") == "gray" and event.keysym not in ("Tab", "Shift_L", "Shift_R", "Return"):
                widget.config(fg="black")

        for riga_idx, col in enumerate(campi_modificabili):
            col_idx = colonne.index(col)
            val_originale = valori_prima_riga[col_idx]

            testo_label = self.get_nome_visivo(col).upper() + ":"
            tk.Label(frame_form, text=testo_label, font=("Arial", 10, "bold"), bg="#ecf0f1").grid(row=riga_idx,
                                                                                                  column=0, sticky="e",
                                                                                                  pady=8, padx=10)

            entry = tk.Entry(frame_form, width=40, font=("Arial", 10))
            entry.grid(row=riga_idx, column=1, sticky="w", pady=8)

            entry.insert(0, str(val_originale))
            entry.config(fg="gray")

            entry.bind("<Key>", attiva_campo)
            entry.bind("<<Paste>>", lambda e, w=entry: w.config(fg="black"))

            entry_dict[col] = entry

        def salva_modifiche():
            campi_da_aggiornare = {}
            for col, entry in entry_dict.items():
                if entry.cget("fg") == "black":
                    campi_da_aggiornare[col] = entry.get().strip()

            if not campi_da_aggiornare:
                popup.destroy()
                return

            self.imposta_caricamento(True, "⏳ Salvataggio modifiche nel Database...")
            popup.destroy()

            try:
                conn = sqlite3.connect(self.file_path_db)
                cur = conn.cursor()

                set_clause = ", ".join([f"{c} = ?" for c in campi_da_aggiornare.keys()])
                valori = list(campi_da_aggiornare.values())

                placeholders = ','.join('?' for _ in ids_da_modificare)
                query = f"UPDATE misurazioni SET {set_clause} WHERE id IN ({placeholders})"

                cur.execute(query, valori + ids_da_modificare)
                conn.commit()
                conn.close()

                for col, val in campi_da_aggiornare.items():
                    self.df_completo.loc[self.df_completo['id'].astype(str).isin(ids_da_modificare), col] = val

                self.applica_filtri()

                campi_modificati_belli = [self.get_nome_visivo(c) for c in campi_da_aggiornare.keys()]
                msg_finale = f"✅ {len(ids_da_modificare)} righe aggiornate con successo nei campi:\n{', '.join(campi_modificati_belli)}"
                if len(ids_da_modificare) == 1:
                    msg_finale = f"✅ Riga aggiornata con successo nei campi:\n{', '.join(campi_modificati_belli)}"

                # FIX: Aggiunto parent=self.root
                messagebox.showinfo("Fatto", msg_finale, parent=self.root)

            except Exception as e:
                # FIX: Aggiunto parent=self.root
                messagebox.showerror("Errore Salvataggio", f"Errore durante l'aggiornamento del database:\n{str(e)}",
                                     parent=self.root)
            finally:
                self.imposta_caricamento(False)

        tk.Button(popup, text="💾 Salva Modifiche", command=salva_modifiche, bg="#27ae60", fg="white",
                  font=("Arial", 11, "bold"), bd=0, padx=15, pady=6).pack(pady=20)

    # ==========================================
    # LOGICA: INTERFACCIA TABELLA E FILTRI A CASCATA
    # ==========================================
    def costruisci_tabella(self):
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = list(self.df_completo.columns)
        self.tree["show"] = "headings"

        for col in self.df_completo.columns:
            self.tree.heading(col, text=self.get_nome_visivo(col))

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

        self.aggiorna_colonne_visibili()

    def popola_tabella(self, df):
        self.tree.delete(*self.tree.get_children())
        df_display = df.head(1000)

        col_list = list(self.df_completo.columns)

        for _, row in df_display.iterrows():
            valori_riga = []
            for col in col_list:
                val = row[col]
                if col == 'file_pdf':
                    val = self.tronca_percorso(val)
                valori_riga.append(val)

            self.tree.insert("", "end", values=valori_riga)

    def inizializza_filtri(self):
        for widget in self.frame_filtri_dinamici.winfo_children(): widget.destroy()
        self.filtri_combo.clear()

        colonne_per_filtri = ['codice_pezzo', 'fase', 'lotto', 'sezione', 'stato', 'nome_misura']
        colonne_presenti = [col for col in colonne_per_filtri if col in self.df_completo.columns]

        for col in colonne_presenti:
            testo_label = self.get_nome_visivo(col).upper()
            tk.Label(self.frame_filtri_dinamici, text=testo_label, bg="#ecf0f1", font=("Arial", 9, "bold")).pack(
                anchor="w", pady=(5, 0))

            combo = ttk.Combobox(self.frame_filtri_dinamici, state="normal")
            combo.pack(fill="x")

            combo.bind("<<ComboboxSelected>>", lambda e: self.applica_filtri())
            combo.bind("<Return>", lambda e: self.applica_filtri())

            self.filtri_combo[col] = combo

    def reset_filtri(self):
        for combo in self.filtri_combo.values():
            combo.set("TUTTI")
        self.applica_filtri()

    def applica_filtri(self, event=None):
        if self.df_completo.empty: return

        self.imposta_caricamento(True, "⏳ Applicazione filtri in corso...")
        try:
            df = self.df_completo.copy()

            filtri_attivi = {}
            for col, combo in self.filtri_combo.items():
                val = combo.get().strip().upper()
                if val and val != "TUTTI":
                    filtri_attivi[col] = val
                    df = df[df[col].astype(str).str.upper() == val]

            cod_selezionato = "TUTTI"
            if 'codice_pezzo' in self.filtri_combo:
                cod_selezionato = self.filtri_combo['codice_pezzo'].get().strip().upper()

            if cod_selezionato and cod_selezionato != "TUTTI":
                if self.codice_corrente != cod_selezionato:
                    self.codice_corrente = cod_selezionato
                    self.costruisci_filtri_misure(cod_selezionato)

                misure_attive = [m for m, var in self.misure_visibili_vars.items() if var.get()]

                if len(misure_attive) < len(self.misure_visibili_vars):
                    df = df[df['nome_misura'].isin(misure_attive)]
            else:
                if self.codice_corrente is not None:
                    self.codice_corrente = None
                    self.svuota_filtri_misure()

            self.df_filtrato = df
            self.popola_tabella(self.df_filtrato)
            self.aggiorna_statistiche()

            for col, combo in self.filtri_combo.items():
                valore_attuale = combo.get().strip().upper()

                df_temp = self.df_completo.copy()
                for c_attivo, v_attivo in filtri_attivi.items():
                    if c_attivo != col:
                        df_temp = df_temp[df_temp[c_attivo].astype(str).str.upper() == v_attivo]

                nuove_opzioni = ["TUTTI"] + sorted([str(x) for x in df_temp[col].unique() if str(x) != ""])
                combo['values'] = nuove_opzioni

                if not valore_attuale or valore_attuale == "TUTTI":
                    combo.set("TUTTI")
                elif valore_attuale in [opt.upper() for opt in nuove_opzioni]:
                    combo.set(valore_attuale)
                else:
                    combo.set("TUTTI")

        finally:
            self.imposta_caricamento(False)
            avviso = f" (Mostrate prime 1000)" if len(self.df_filtrato) > 1000 else ""

            nome_file = Path(self.file_path_db).name if self.file_path_db else "Sconosciuto"
            self.lbl_file.config(text=f"📂 {nome_file} - Trovate: {len(self.df_filtrato)} righe{avviso}")

    # ==========================================
    # LOGICA: STATISTICHE AVANZATE SU MISURA
    # ==========================================
    def aggiorna_statistiche(self):
        self.testo_statistiche.config(state="normal")
        self.testo_statistiche.delete(1.0, tk.END)

        df = self.df_filtrato
        if df.empty:
            self.testo_statistiche.insert(tk.END, "Nessuna misurazione corrispondente ai filtri.")
            self.testo_statistiche.config(state="disabled")
            return

        statistiche = []
        statistiche.append(f"📌 TOTALE MISURAZIONI: {len(df)}\n")

        if 'file_pdf' in df.columns:
            totale_pezzi = df['file_pdf'].nunique()
            statistiche.append(f"📄 TOTALE PEZZI (PDF): {totale_pezzi}\n")
        else:
            statistiche.append("\n")

        statistiche.append("-" * 35 + "\n")

        if 'codice_pezzo' in df.columns:
            statistiche.append(f"📦 CODICI UNICI: {df['codice_pezzo'].nunique()}\n")
            if 'lotto' in df.columns:
                statistiche.append("🏷️ LOTTI PER CODICE PEZZO:")
                for cod, count in df.groupby('codice_pezzo')['lotto'].nunique().items():
                    statistiche.append(f"  • {cod if cod else '[Nessun Codice]'}: {count} lotti")
                statistiche.append("\n")

                if 'fase' in df.columns:
                    statistiche.append("⚙️ LOTTI PER CODICE E FASE:")
                    for (cod, fase), count in df.groupby(['codice_pezzo', 'fase'])['lotto'].nunique().items():
                        statistiche.append(
                            f"  • {cod if cod else '[No Cod]'} | {fase if fase else '[No Fase]'}: {count} lotti")
                    statistiche.append("\n")

        if 'file_pdf' in df.columns and 'stato' in df.columns:
            statistiche.append("-" * 35)
            statistiche.append("\n⚖️ QUALITÀ SUI PEZZI (PDF FISICI):")
            pdf_scartati = df[df['stato'].str.upper() == 'NON OK']['file_pdf'].nunique()
            pdf_ok = totale_pezzi - pdf_scartati

            perc_ok = (pdf_ok / totale_pezzi) * 100 if totale_pezzi > 0 else 0
            perc_ko = (pdf_scartati / totale_pezzi) * 100 if totale_pezzi > 0 else 0

            statistiche.append(f"  - Pezzi a posto: {pdf_ok} ({perc_ok:.1f}%)")
            statistiche.append(f"  - Pezzi da scartare: {pdf_scartati} ({perc_ko:.1f}%)\n")

        if 'stato' in df.columns:
            statistiche.append("-" * 35)
            statistiche.append("\n🔬 QUALITÀ SULLE SINGOLE MISURE:")
            for stato, count in df['stato'].value_counts().items():
                if stato.strip() == "": stato = "NON VALUTATO"
                statistiche.append(f"  - {stato}: {count} ({(count / len(df)) * 100:.1f}%)")

        self.testo_statistiche.insert(tk.END, "\n".join(statistiche))
        self.testo_statistiche.config(state="disabled")

    # ==========================================
    # LOGICA: ESPORTAZIONE
    # ==========================================
    def esporta_dati(self):
        if self.df_filtrato.empty:
            # FIX: Aggiunto parent=self.root
            return messagebox.showinfo("Vuoto", "Non ci sono dati da esportare.", parent=self.root)

        df_export = self.df_filtrato.drop(columns=['id'], errors='ignore')
        df_export = df_export.rename(columns=self.nomi_display)

        # FIX: Aggiunto parent=self.root
        file_path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".xlsx",
                                                 filetypes=[("Excel Files", "*.xlsx"), ("CSV Files", "*.csv")])

        if file_path:
            self.imposta_caricamento(True, "⏳ Generazione file in corso...")
            try:
                if file_path.endswith('.csv'):
                    df_export.to_csv(file_path, index=False, sep=";")
                else:
                    df_export.to_excel(file_path, index=False)
                # FIX: Aggiunto parent=self.root
                messagebox.showinfo("Successo", f"Dati esportati correttamente in:\n{Path(file_path).name}",
                                    parent=self.root)
            except Exception as e:
                # FIX: Aggiunto parent=self.root
                messagebox.showerror("Errore", f"Impossibile salvare il file:\n{str(e)}", parent=self.root)
            finally:
                self.imposta_caricamento(False)


if __name__ == "__main__":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Calypso.Navigator.Pro")
    except Exception:
        pass
    root = tk.Tk()
    app = NavigatoreSQLiteApp(root)
    root.mainloop()