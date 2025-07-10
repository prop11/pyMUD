import tkinter as tk
from tkinter import messagebox
from .alias_manager import AliasManager # Import the AliasManager class

class AliasManagerWindow(tk.Toplevel):
    """
    A separate Tkinter window for managing MUD client aliases.
    """
    def __init__(self, master, alias_manager: AliasManager):
        # Call the constructor of Toplevel
        super().__init__(master)
        self.title("Alias Manager")
        self.geometry("600x400") # Set a default size for the window

        self.alias_manager = alias_manager # Reference to the AliasManager instance
        self.master = master # Reference to the main MUDClientApp root window

        # Ensure the window is destroyed properly when closed
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._setup_gui()
        self._load_aliases_to_gui() # Populate the listbox on startup

        # Make sure the window is modal or stays on top if needed, or simply focuses
        self.transient(master) # Set to be a transient window of the master
        self.grab_set()        # Grab all input until this window is closed
        self.focus_set()       # Focus on this window
        master.wait_window(self) # Make the master window wait until this one is closed

    def _setup_gui(self):
        """Sets up the GUI elements for the alias manager window."""
        # Frame for adding/editing aliases
        input_frame = tk.LabelFrame(self, text="Add/Edit Alias", padx=10, pady=10)
        input_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(input_frame, text="Command:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.alias_cmd_entry = tk.Entry(input_frame, width=25)
        self.alias_cmd_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

        tk.Label(input_frame, text="Replacement:").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.alias_replace_entry = tk.Entry(input_frame, width=40)
        self.alias_replace_entry.grid(row=1, column=1, padx=5, pady=2, sticky="ew")

        # Configure column weights for resizing
        input_frame.grid_columnconfigure(1, weight=1)

        button_frame = tk.Frame(input_frame)
        button_frame.grid(row=2, column=0, columnspan=2, pady=5)

        tk.Button(button_frame, text="Add/Update Alias", command=self.add_alias_gui).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Remove Selected Alias", command=self.remove_alias_gui).pack(side=tk.LEFT, padx=5)

        # Frame for alias list
        list_frame = tk.LabelFrame(self, text="Current Aliases", padx=10, pady=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.alias_listbox = tk.Listbox(list_frame)
        self.alias_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.alias_listbox.bind("<<ListboxSelect>>", self._load_alias_into_entries)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.alias_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.alias_listbox.config(yscrollcommand=scrollbar.set)

    def _load_aliases_to_gui(self):
        """Populates the alias listbox with current aliases."""
        self.alias_listbox.delete(0, tk.END)
        aliases = self.alias_manager.get_aliases()
        if not aliases:
            self.alias_listbox.insert(tk.END, "No aliases configured yet.")
            return

        for cmd, repl in aliases.items():
            self.alias_listbox.insert(tk.END, f"{cmd} -> {repl}")

    def add_alias_gui(self):
        """Handles adding/updating an alias from the GUI."""
        cmd = self.alias_cmd_entry.get().strip()
        repl = self.alias_replace_entry.get().strip()
        if self.alias_manager.add_alias(cmd, repl):
            messagebox.showinfo("Success", f"Alias '{cmd}' set to '{repl}'")
            self._load_aliases_to_gui()
            self.alias_cmd_entry.delete(0, tk.END)
            self.alias_replace_entry.delete(0, tk.END)
        else:
            messagebox.showerror("Error", "Command and replacement cannot be empty.")

    def remove_alias_gui(self):
        """Handles removing an alias from the GUI."""
        selected_index = self.alias_listbox.curselection()
        if not selected_index:
            messagebox.showwarning("Warning", "No alias selected to remove.")
            return
        
        # Extract the command from the listbox string "cmd -> repl"
        selected_alias_str = self.alias_listbox.get(selected_index[0])
        cmd = selected_alias_str.split(' -> ')[0] # Assumes format "cmd -> repl"

        if messagebox.askyesno("Confirm Removal", f"Are you sure you want to remove alias '{cmd}'?"):
            if self.alias_manager.remove_alias(cmd):
                messagebox.showinfo("Success", f"Alias '{cmd}' removed.")
                self._load_aliases_to_gui()
            else:
                messagebox.showerror("Error", f"Failed to remove alias '{cmd}'.")

    def _load_alias_into_entries(self, event):
        """Loads selected alias from listbox into entry fields for editing."""
        selected_index = self.alias_listbox.curselection()
        if not selected_index:
            return
        selected_alias_str = self.alias_listbox.get(selected_index[0])
        try:
            cmd, repl = selected_alias_str.split(' -> ', 1)
            self.alias_cmd_entry.delete(0, tk.END)
            self.alias_cmd_entry.insert(0, cmd)
            self.alias_replace_entry.delete(0, tk.END)
            self.alias_replace_entry.insert(0, repl)
        except ValueError:
            # This can happen if the placeholder "No aliases configured yet." is selected
            self.alias_cmd_entry.delete(0, tk.END)
            self.alias_replace_entry.delete(0, tk.END)
            pass

    def on_close(self):
        """Handles the window closing event."""
        self.grab_release() # Release the input grab
        self.destroy()      # Destroy the window