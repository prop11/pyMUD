import tkinter as tk
from tkinter import messagebox
from .profile_manager import ProfileManager # Relative import

class ProfileSelectionDialog(tk.Toplevel):
    """
    A dialog window to select a MUD profile from a list for connection.
    """
    def __init__(self, master, profile_manager: ProfileManager, connect_callback):
        super().__init__(master)
        self.title("Select Profile to Connect")
        self.geometry("300x250") # Set a default size

        self.profile_manager = profile_manager
        self.connect_callback = connect_callback # Callback to MUDClientApp's connect_to_profile_internal

        self.transient(master) # Set to be a transient window of the master
        self.grab_set()        # Grab all input until this window is closed
        self.focus_set()       # Focus on this window

        self._setup_gui()
        self._load_profiles_to_gui()

        # Handle closing the window
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Make the master window wait until this one is closed
        master.wait_window(self)

    def _setup_gui(self):
        """Sets up the GUI elements for the profile selection dialog."""
        label = tk.Label(self, text="Choose a profile:")
        label.pack(pady=10)

        listbox_frame = tk.Frame(self)
        listbox_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.profile_listbox = tk.Listbox(listbox_frame)
        self.profile_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.profile_listbox.bind("<Double-Button-1>", lambda e: self._connect_selected())

        scrollbar = tk.Scrollbar(listbox_frame, orient="vertical", command=self.profile_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.profile_listbox.config(yscrollcommand=scrollbar.set)

        connect_button = tk.Button(self, text="Connect", command=self._connect_selected)
        connect_button.pack(pady=10)

    def _load_profiles_to_gui(self):
        """Populates the profile listbox with current profiles."""
        self.profile_listbox.delete(0, tk.END)
        profiles = list(self.profile_manager.profiles.keys())
        if not profiles:
            self.profile_listbox.insert(tk.END, "No profiles found. Add some via 'Manage Profiles'.")
            return

        for profile_name in profiles:
            self.profile_listbox.insert(tk.END, profile_name)
        
        # Select the first profile by default if any exist
        if profiles:
            self.profile_listbox.selection_set(0)
            self.profile_listbox.focus_set()


    def _connect_selected(self):
        """Handles connecting to the selected profile."""
        selected_index = self.profile_listbox.curselection()
        if not selected_index:
            messagebox.showwarning("Warning", "No profile selected.")
            return

        profile_name = self.profile_listbox.get(selected_index[0])
        
        # Call the callback function provided by MUDClientApp
        self.connect_callback(profile_name)
        self._on_close() # Close the dialog after attempting connection

    def _on_close(self):
        """Handles closing the dialog."""
        self.grab_release()
        self.destroy()