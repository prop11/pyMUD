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

    def connect_to_profile(self):
        selected_profile = self.profile_listbox.get(tk.ACTIVE)
        if selected_profile:
            profile = self.profile_manager.profiles[selected_profile]
            self.connect(profile['host'], profile['port'])

    def connect(self, host, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, f"Connected to {host}:{port}\n")
        self.output_text.config(state=tk.DISABLED)
        self.receive_thread = threading.Thread(target=self.receive_messages)
        self.receive_thread.start()

    def receive_messages(self):
        while True:
            try:
                message = self.sock.recv(1024).decode('utf-8')
                if message:
                    self.output_text.config(state=tk.NORMAL)
                    if self.is_gmcp_message(message):
                        self.handle_gmcp_message(message)
                    else:
                        self.output_text.insert(tk.END, message + "\n")
                    self.output_text.config(state=tk.DISABLED)
                    self.output_text.yview(tk.END)
            except:
                break

    def is_gmcp_message(self, message):
        return message.startswith("\xFF\xFA") and message.endswith("\xFF\xF0")

    def handle_gmcp_message(self, message):
        # Extract and parse the GMCP message
        match = re.match(r"\xFF\xFA[^\xFF]*?\xFF\xF0", message)
        if match:
            gmcp_message = match.group(0)[2:-2]  # Remove Telnet IAC bytes
            # Process the GMCP message here...
            self.output_text.insert(tk.END, f"GMCP Message: {gmcp_message}\n")

    def send_message(self, event):
        message = self.input_entry.get()
        self.sock.send(message.encode('utf-8'))
        self.input_entry.delete(0, tk.END)
