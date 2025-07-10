import tkinter as tk
from tkinter import messagebox, simpledialog
from .profile_manager import ProfileManager # Relative import

class ProfileManagerWindow(tk.Toplevel):
    """
    A separate Tkinter window for managing MUD client profiles (add/remove).
    """
    def __init__(self, master, profile_manager: ProfileManager):
        super().__init__(master)
        self.title("Profile Manager")
        self.geometry("450x300") # Set a default size

        self.profile_manager = profile_manager
        self.master = master

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._setup_gui()
        self._load_profiles_to_gui()

        self.transient(master)
        self.grab_set()
        self.focus_set()
        master.wait_window(self)

    def _setup_gui(self):
        """Sets up the GUI elements for the profile manager window."""
        # Frame for adding profiles
        add_frame = tk.LabelFrame(self, text="Add New Profile", padx=10, pady=10)
        add_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(add_frame, text="Name:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.name_entry = tk.Entry(add_frame, width=20)
        self.name_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

        tk.Label(add_frame, text="Host:").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.host_entry = tk.Entry(add_frame, width=30)
        self.host_entry.grid(row=1, column=1, padx=5, pady=2, sticky="ew")

        tk.Label(add_frame, text="Port:").grid(row=2, column=0, padx=5, pady=2, sticky="w")
        self.port_entry = tk.Entry(add_frame, width=10)
        self.port_entry.grid(row=2, column=1, padx=5, pady=2, sticky="ew")

        add_frame.grid_columnconfigure(1, weight=1)

        tk.Button(add_frame, text="Add Profile", command=self.add_profile_gui).grid(row=3, column=0, columnspan=2, pady=5)

        # Frame for listing and removing profiles
        list_frame = tk.LabelFrame(self, text="Current Profiles", padx=10, pady=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.profile_listbox = tk.Listbox(list_frame)
        self.profile_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.profile_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.profile_listbox.config(yscrollcommand=scrollbar.set)

        tk.Button(self, text="Remove Selected Profile", command=self.remove_profile_gui).pack(pady=5)

    def _load_profiles_to_gui(self):
        """Populates the profile listbox with current profiles."""
        self.profile_listbox.delete(0, tk.END)
        profiles = list(self.profile_manager.profiles.keys())
        if not profiles:
            self.profile_listbox.insert(tk.END, "No profiles configured yet.")
            return

        for profile_name in profiles:
            self.profile_listbox.insert(tk.END, profile_name)

    def add_profile_gui(self):
        """Handles adding a profile from the GUI entries."""
        name = self.name_entry.get().strip()
        host = self.host_entry.get().strip()
        port_str = self.port_entry.get().strip()

        if not name or not host or not port_str:
            messagebox.showerror("Error", "All fields are required.")
            return
        
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                messagebox.showerror("Error", "Port must be between 1 and 65535.")
                return
        except ValueError:
            messagebox.showerror("Error", "Invalid port number. Please enter an integer.")
            return

        if name in self.profile_manager.profiles:
            messagebox.showerror("Error", f"Profile '{name}' already exists.")
            return

        self.profile_manager.add_profile(name, host, port)
        messagebox.showinfo("Success", f"Profile '{name}' added.")
        self._load_profiles_to_gui()
        self.name_entry.delete(0, tk.END)
        self.host_entry.delete(0, tk.END)
        self.port_entry.delete(0, tk.END)

    def remove_profile_gui(self):
        """Handles removing the selected profile from the GUI."""
        selected_index = self.profile_listbox.curselection()
        if not selected_index:
            messagebox.showwarning("Warning", "No profile selected to remove.")
            return
        
        profile_name = self.profile_listbox.get(selected_index[0])

        if messagebox.askyesno("Confirm Removal", f"Are you sure you want to remove profile '{profile_name}'?"):
            self.profile_manager.remove_profile(profile_name)
            messagebox.showinfo("Success", f"Profile '{profile_name}' removed.")
            self._load_profiles_to_gui()

    def _on_close(self):
        """Handles closing the window."""
        self.grab_release()
        self.destroy()