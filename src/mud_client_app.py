import tkinter as tk
from tkinter import messagebox, simpledialog, scrolledtext
from src.profile_manager import ProfileManager
import socket
import threading
import re
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- MOCK ProfileManager for standalone testing ---
class ProfileManager:
    def __init__(self):
        self.profiles = {
            "Example MUD 1": {"host": "mud.example.com", "port": 4000},
            "Local Test": {"host": "127.0.0.1", "port": 5000}
        }
        logging.info("ProfileManager initialized with mock profiles.")

    def add_profile(self, name, host, port):
        self.profiles[name] = {"host": host, "port": port}
        logging.info(f"Profile '{name}' added to mock manager.")

    def remove_profile(self, name):
        if name in self.profiles:
            del self.profiles[name]
            logging.info(f"Profile '{name}' removed from mock manager.")
# --- End MOCK ProfileManager ---


class MUDClientApp:
    ANSI_COLOR_MAP = {
        0: 'white',
        30: 'black', 31: 'red', 32: 'green', 33: 'yellow',
        34: 'blue', 35: 'magenta', 36: 'cyan', 37: 'white',
        90: 'gray', 91: 'firebrick', 92: 'forestgreen', 93: 'gold',
        94: 'dodgerblue', 95: 'violet', 96: 'lightskyblue', 97: 'white'
    }
    
    ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[([0-9;]*)m')
    
    TELNET_IAC_PATTERN = re.compile(rb'\xff[\xfb-\xfe][\x01-\xff]|\xff\xf0|\xff\xfa[\x01-\xff]*?\xff\xf0')


    def __init__(self, root):
        self.root = root
        self.root.title("MUD Client")
        self.profile_manager = ProfileManager()

        self.sock = None
        self.receive_thread = None
        self.connected = False

        self.setup_gui()
        self.create_hud()
        self.define_text_tags()

        self.update_gui_state()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_gui(self):
        profile_frame = tk.Frame(self.root)
        profile_frame.pack(fill=tk.X, pady=5, padx=5, expand=False)

        self.profile_listbox = tk.Listbox(profile_frame, height=5)
        self.profile_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        profile_btn_frame = tk.Frame(profile_frame)
        profile_btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5)

        self.add_btn = tk.Button(profile_btn_frame, text="Add Profile", command=self.add_profile)
        self.add_btn.pack(fill=tk.X, pady=2)

        self.remove_btn = tk.Button(profile_btn_frame, text="Remove Profile", command=self.remove_profile)
        self.remove_btn.pack(fill=tk.X, pady=2)
        
        self.load_profiles()

        connect_disconnect_frame = tk.Frame(self.root)
        connect_disconnect_frame.pack(fill=tk.X, pady=2, padx=5, expand=False)

        self.connect_btn = tk.Button(connect_disconnect_frame, text="Connect", command=self.connect_to_profile)
        self.connect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        self.disconnect_btn = tk.Button(connect_disconnect_frame, text="Disconnect", command=self.disconnect)
        self.disconnect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        text_frame = tk.Frame(self.root)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=5, padx=5)

        self.output_text = scrolledtext.ScrolledText(text_frame, state=tk.DISABLED, wrap=tk.WORD, bg="black", fg="white", font=("Courier New", 10))
        self.output_text.pack(fill=tk.BOTH, expand=True)

        self.input_entry = tk.Entry(self.root)
        self.input_entry.pack(fill=tk.X, expand=False, pady=(0,5), padx=5)
        self.input_entry.bind("<Return>", self.send_message)

    def define_text_tags(self):
        self.output_text.tag_config("default", foreground="white", background="black")

        for code, color_name in self.ANSI_COLOR_MAP.items():
            self.output_text.tag_config(f"ansi_{code}", foreground=color_name)
        
        self.output_text.tag_config("system_message", foreground="lightgray", font=("TkDefaultFont", 10, "italic"))


    def load_profiles(self):
        self.profile_listbox.delete(0, tk.END)
        for profile_name in self.profile_manager.profiles:
            self.profile_listbox.insert(tk.END, profile_name)
        if self.profile_manager.profiles:
            self.profile_listbox.selection_set(0)


    def add_profile(self):
        name = simpledialog.askstring("Profile Name", "Enter profile name:")
        if not name: return
        if name in self.profile_manager.profiles:
            messagebox.showerror("Error", "Profile with this name already exists.")
            return
        host = simpledialog.askstring("Host", "Enter host address:")
        if not host: return
        try:
            port = simpledialog.askinteger("Port", "Enter port number:")
            if port is None: return
            if not (1 <= port <= 65535):
                messagebox.showerror("Error", "Port must be between 1 and 65535.")
                return
        except ValueError:
            messagebox.showerror("Error", "Invalid port number. Please enter an integer.")
            return

        self.profile_manager.add_profile(name, host, port)
        self.load_profiles()
        messagebox.showinfo("Success", f"Profile '{name}' added.")


    def remove_profile(self):
        selected_index = self.profile_listbox.curselection()
        if not selected_index:
            messagebox.showwarning("Warning", "No profile selected to remove.")
            return
        selected_profile = self.profile_listbox.get(selected_index[0])
        if messagebox.askyesno("Confirm Remove", f"Are you sure you want to remove '{selected_profile}'?"):
            self.profile_manager.remove_profile(selected_profile)
            self.load_profiles()
            messagebox.showinfo("Success", f"Profile '{selected_profile}' removed.")


    def create_hud(self):
        self.hud_frame = tk.Frame(self.root, bg="#333333")
        self.hud_frame.pack(side=tk.TOP, fill=tk.X, expand=False)

        self.connection_label = tk.Label(self.hud_frame, text="Disconnected", bg="#333333", fg="red", font=("Arial", 10, "bold"))
        self.connection_label.pack(side=tk.LEFT, padx=10, pady=5)

        self.health_label = tk.Label(self.hud_frame, text="Health: N/A", bg="#333333", fg="white", font=("Arial", 10))
        self.health_label.pack(side=tk.LEFT, padx=10, pady=5)

        self.status_message_label = tk.Label(self.hud_frame, text="", bg="#333333", fg="lightblue", font=("Arial", 10))
        self.status_message_label.pack(side=tk.RIGHT, padx=10, pady=5)

    def update_gui_state(self):
        if self.connected:
            self.connect_btn.config(state=tk.DISABLED)
            self.disconnect_btn.config(state=tk.NORMAL)
            self.input_entry.config(state=tk.NORMAL)
            self.profile_listbox.config(state=tk.DISABLED)
            self.add_btn.config(state=tk.DISABLED)
            self.remove_btn.config(state=tk.DISABLED)
            self.connection_label.config(text="Connected", fg="green")
            self.status_message_label.config(text="Online")
        else:
            self.connect_btn.config(state=tk.NORMAL)
            self.disconnect_btn.config(state=tk.DISABLED)
            self.input_entry.config(state=tk.DISABLED)
            self.profile_listbox.config(state=tk.NORMAL)
            self.add_btn.config(state=tk.NORMAL)
            self.remove_btn.config(state=tk.NORMAL)
            self.connection_label.config(text="Not connected", fg="red")
            self.status_message_label.config(text="Offline")


    def update_connection_status(self, connected):
        self.connected = connected
        self.update_gui_state()


    def update_health(self, health):
        self.root.after(0, lambda: self.health_label.config(text=f"Health: {health}"))


    def display_message(self, message, tags=None):
        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, message, tags if tags is not None else "default")
        self.output_text.insert(tk.END, "\n")
        self.output_text.config(state=tk.DISABLED)
        self.output_text.yview(tk.END)


    def connect_to_profile(self):
        if self.connected:
            messagebox.showwarning("Warning", "Already connected. Please disconnect first.")
            return

        selected_index = self.profile_listbox.curselection()
        if not selected_index:
            messagebox.showwarning("Warning", "No profile selected. Please add or select a profile.")
            return
        
        selected_profile_name = self.profile_listbox.get(selected_index[0])
        profile = self.profile_manager.profiles.get(selected_profile_name)

        if profile:
            # FIX: Use lambda to pass tags keyword argument
            self.display_message(f"--- Attempting to connect to {profile['host']}:{profile['port']} ---", tags=("system_message",))
            self.status_message_label.config(text="Connecting...")
            
            connection_thread = threading.Thread(target=self._initiate_connection, args=(profile['host'], profile['port']))
            connection_thread.daemon = True
            connection_thread.start()
        else:
            messagebox.showerror("Error", "Selected profile not found. Please reload profiles.")
            self.load_profiles()


    def _initiate_connection(self, host, port):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((host, port))
            self.sock.settimeout(None)

            self.root.after(0, self.update_connection_status, True)
            # FIX: Use lambda to pass tags keyword argument to display_message
            self.root.after(0, lambda: self.display_message("--- Connected to MUD ---", tags=("system_message", "ansi_32")))

            self.receive_thread = threading.Thread(target=self.receive_messages)
            self.receive_thread.daemon = True
            self.receive_thread.start()
            
        except socket.timeout:
            # FIX: Use lambda to pass tags keyword argument to display_message
            self.root.after(0, lambda: self.display_message("Connection timed out.", tags=("system_message", "ansi_31")))
            self.root.after(0, self.update_connection_status, False)
            logging.error(f"Connection timed out to {host}:{port}")
        except socket.error as e:
            # FIX: Use lambda to pass tags keyword argument to display_message
            self.root.after(0, lambda msg_text=f"Connection error: {e}": self.display_message(msg_text, tags=("system_message", "ansi_31")))
            self.root.after(0, self.update_connection_status, False)
            logging.error(f"Socket error connecting to {host}:{port}: {e}")
        except Exception as e:
            # FIX: Use lambda to pass tags keyword argument to display_message
            self.root.after(0, lambda msg_text=f"An unexpected error occurred during connection: {e}": self.display_message(msg_text, tags=("system_message", "ansi_31")))
            self.root.after(0, self.update_connection_status, False)
            logging.exception("Unexpected error during connection")


    def disconnect(self):
        if not self.connected or not self.sock:
            logging.info("Attempted to disconnect when not connected.")
            return
        
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            logging.info("Socket closed.")
        except socket.error as e:
            logging.warning(f"Error during socket shutdown/close: {e}")
        except Exception as e:
            logging.warning(f"Unexpected error during disconnect: {e}")
        finally:
            self.sock = None
            self.receive_thread = None
            self.root.after(0, self.update_connection_status, False)
            # FIX: Use lambda to pass tags keyword argument to display_message
            self.root.after(0, lambda: self.display_message("--- Disconnected from MUD ---", tags=("system_message", "ansi_31")))


    def receive_messages(self):
        buffer = b""
        while self.connected:
            try:
                message_bytes = self.sock.recv(4096)

                if not message_bytes:
                    logging.info("Server disconnected gracefully.")
                    # FIX: Use lambda to pass tags keyword argument to display_message
                    self.root.after(0, lambda: self.display_message("--- Server disconnected unexpectedly ---", tags=("system_message", "ansi_31")))
                    self.root.after(0, self.disconnect)
                    break
                
                buffer += message_bytes
                
                processed_buffer = self.TELNET_IAC_PATTERN.sub(b'', buffer)

                try:
                    message = processed_buffer.decode('utf-8')
                    buffer = b""
                except UnicodeDecodeError:
                    message = processed_buffer.decode('latin-1', errors='replace')
                    buffer = b""
                    logging.warning("UnicodeDecodeError encountered, falling back to latin-1 for display.")

                if message:
                    self.root.after(0, self.parse_and_display_message, message)
                    self.root.after(0, self.parse_gmcp_and_hud, message)
            
            except socket.timeout:
                pass
            except socket.error as e:
                if self.connected:
                    logging.error(f"Socket error in receive_messages: {e}")
                    # FIX: Use lambda to pass tags keyword argument to display_message
                    self.root.after(0, lambda msg_text=f"--- Network error: {e} ---": self.display_message(msg_text, tags=("system_message", "ansi_31")))
                    self.root.after(0, self.disconnect)
                break
            except Exception as e:
                logging.exception(f"An unexpected error occurred in receive_messages: {e}")
                # FIX: Use lambda to pass tags keyword argument to display_message
                self.root.after(0, lambda msg_text=f"--- An unexpected error occurred: {e} ---": self.display_message(msg_text, tags=("system_message", "ansi_31")))
                self.root.after(0, self.disconnect)
                break


    def parse_and_display_message(self, message):
        self.output_text.config(state=tk.NORMAL)
        
        current_fg_tag = "default"

        parts = self.ANSI_ESCAPE_PATTERN.split(message)
        
        for i in range(len(parts)):
            if i % 2 == 0:
                text_to_display = parts[i]
                if text_to_display:
                    self.output_text.insert(tk.END, text_to_display, current_fg_tag)
            else:
                codes_str = parts[i]
                if codes_str:
                    codes = [int(c) for c in codes_str.split(';') if c]

                    for code in codes:
                        if code == 0:
                            current_fg_tag = "default"
                        elif code in self.ANSI_COLOR_MAP:
                            current_fg_tag = f"ansi_{code}"
        
        self.output_text.insert(tk.END, "\n")
        self.output_text.config(state=tk.DISABLED)
        self.output_text.yview(tk.END)


    def parse_gmcp_and_hud(self, message):
        if "GMCP" in message:
            try:
                gmcp_start_index = message.find("GMCP ")
                if gmcp_start_index != -1:
                    gmcp_payload = message[gmcp_start_index + len("GMCP "):].strip()
                    
                    parts = gmcp_payload.split(" ", 1)
                    if len(parts) == 2:
                        package_name = parts[0]
                        json_str = parts[1]
                        
                        if package_name == "Char.Vitals":
                            data = json.loads(json_str)
                            if 'hp' in data and 'maxhp' in data:
                                self.update_health(f"{data['hp']}/{data['maxhp']}")
                            elif 'hp' in data:
                                self.update_health(f"{data['hp']}")
                        elif package_name == "Char.Status":
                            data = json.loads(json_str)
                            if 'status' in data:
                                self.status_message_label.config(text=f"Status: {data['status']}")

            except (IndexError, json.JSONDecodeError, ValueError) as e:
                logging.error(f"Error parsing GMCP message: {e} - Raw: {message}")
            except Exception as e:
                logging.exception(f"Unexpected error in GMCP parsing: {e} - Raw: {message}")


    def send_message(self, event=None):
        if not self.connected or not self.sock:
            # FIX: Use lambda to pass tags keyword argument
            self.display_message("--- Not connected. Cannot send message. ---", tags=("system_message", "ansi_31"))
            return

        message = self.input_entry.get()
        if not message.strip():
            return

        try:
            self.sock.sendall((message + "\n").encode('utf-8'))
            self.input_entry.delete(0, tk.END)
        except socket.error as e:
            # FIX: Use lambda to pass tags keyword argument
            self.display_message(f"--- Failed to send message: {e} ---", tags=("system_message", "ansi_31"))
            logging.error(f"Failed to send message: {e}")
            self.disconnect()
        except Exception as e:
            # FIX: Use lambda to pass tags keyword argument
            self.display_message(f"--- Unexpected error sending message: {e} ---", tags=("system_message", "ansi_31"))
            logging.exception(f"Unexpected error sending message: {e}")


    def on_closing(self):
        if self.connected:
            if messagebox.askokcancel("Quit", "You are connected. Disconnect and quit?"):
                self.disconnect()
                self.root.destroy()
        else:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MUDClientApp(root)
    root.mainloop()
