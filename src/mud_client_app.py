import tkinter as tk
from tkinter import messagebox, simpledialog
from src.profile_manager import ProfileManager
import socket
import threading
import re

class MUDClientApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MUD Client")
        self.profile_manager = ProfileManager()

        self.setup_gui()

        # Initialize HUD elements
        self.create_hud()

    def setup_gui(self):
        self.profile_listbox = tk.Listbox(self.root)
        self.profile_listbox.pack(fill=tk.BOTH, expand=True)

        self.load_profiles()

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill=tk.X, expand=True)

        self.add_btn = tk.Button(btn_frame, text="Add Profile", command=self.add_profile)
        self.add_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.remove_btn = tk.Button(btn_frame, text="Remove Profile", command=self.remove_profile)
        self.remove_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.connect_btn = tk.Button(btn_frame, text="Connect", command=self.connect_to_profile)
        self.connect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.output_text = tk.Text(self.root, state=tk.DISABLED)
        self.output_text.pack(fill=tk.BOTH, expand=True)

        self.input_entry = tk.Entry(self.root)
        self.input_entry.pack(fill=tk.X, expand=True)
        self.input_entry.bind("<Return>", self.send_message)

    def load_profiles(self):
        self.profile_listbox.delete(0, tk.END)
        for profile_name in self.profile_manager.profiles:
            self.profile_listbox.insert(tk.END, profile_name)

    def add_profile(self):
        name = simpledialog.askstring("Profile Name", "Enter profile name:")
        host = simpledialog.askstring("Host", "Enter host address:")
        port = simpledialog.askinteger("Port", "Enter port number:")

        if name and host and port:
            self.profile_manager.add_profile(name, host, port)
            self.load_profiles()

    def remove_profile(self):
        selected_profile = self.profile_listbox.get(tk.ACTIVE)
        if selected_profile:
            self.profile_manager.remove_profile(selected_profile)
            self.load_profiles()

    def create_hud(self):
        self.hud_frame = tk.Frame(self.root, bg="gray")
        self.hud_frame.pack(side=tk.TOP, fill=tk.X)

        self.connection_label = tk.Label(self.hud_frame, text="Not connected", bg="gray", fg="white")
        self.connection_label.pack(side=tk.LEFT, padx=10)

        self.health_label = tk.Label(self.hud_frame, text="Health: N/A", bg="gray", fg="white")
        self.health_label.pack(side=tk.LEFT, padx=10)

    def update_connection_status(self, connected):
        if connected:
            self.connection_label.config(text="Connected", fg="green")
        else:
            self.connection_label.config(text="Not connected", fg="red")

    def update_health(self, health):
        self.health_label.config(text=f"Health: {health}")

    def display_message(self, message, color=None):
        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, message, color)
        self.output_text.insert(tk.END, "\n")
        self.output_text.config(state=tk.DISABLED)
        self.output_text.yview(tk.END)

    def connect_to_profile(self):
        selected_profile = self.profile_listbox.get(tk.ACTIVE)
        if selected_profile:
            profile = self.profile_manager.profiles[selected_profile]
            self.connect(profile['host'], profile['port'])

    def connect(self, host, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self.update_connection_status(True)
        self.receive_thread = threading.Thread(target=self.receive_messages)
        self.receive_thread.start()

    def receive_messages(self):
        while True:
            try:
                message = self.sock.recv(1024).decode('utf-8')
                if message:
                    self.parse_and_display_message(message)
                    # Example: Simulate GMCP health message
                    if "GMCP" in message:
                        gmcp_data = message.split("GMCP ")[1]
                        if "Char.Vitals" in gmcp_data:
                            health_data = gmcp_data.split("Char.Vitals ")[1]
                            health = health_data.split(",")[0]
                            self.update_health(health)
            except:
                break

    def parse_and_display_message(self, message):
        # Regular expression to match ANSI escape codes for text color
        color_pattern = re.compile(r'\x1b\[(\d+)(;\d+)?m')

        # Split the message based on ANSI escape codes
        parts = color_pattern.split(message)

        # Start with default color
        current_color = "black"

        # Iterate over message parts and display them with appropriate color
        for part in parts:
            if part.startswith("\x1b["):
                # This part contains color information
                color_code = int(part[2:-1])  # Extract color code
                if color_code == 0:  # Reset color
                    current_color = "black"
                elif color_code == 31:  # Red color
                    current_color = "red"
                elif color_code == 32:  # Green color
                    current_color = "green"
                # Add more color codes as needed
            else:
                # Regular text, display with current color
                self.display_message(part, color=current_color)

    def send_message(self, event):
        message = self.input_entry.get()
        self.sock.send(message.encode('utf-8'))
        self.input_entry.delete(0, tk.END)
