import tkinter as tk
from tkinter import messagebox, simpledialog, scrolledtext # Import scrolledtext for auto-scrollbar
from src.profile_manager import ProfileManager # Assuming this exists and works
import socket
import threading
import re
import json # For GMCP parsing
import logging # For better error/info logging

# Configure logging for better error visibility
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- MOCK ProfileManager for standalone testing ---
# If src.profile_manager.py exists and works, you can remove or comment out this mock.
# This mock allows you to run the MUDClientApp.py file directly for testing.
class ProfileManager:
    def __init__(self):
        self.profiles = {
            "Example MUD 1": {"host": "mud.example.com", "port": 4000}, # Replace with a real MUD host/port
            "Local Test": {"host": "127.0.0.1", "port": 5000} # Use this with a simple local server (e.g., netcat, or a simple Python socket server)
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
    # --- Fix 5 & 8: Define mappings for ANSI colors and styles to Tkinter tags ---
    # These will be used to configure Tkinter text tags.
    ANSI_COLOR_MAP = {
        0: 'white',  # Reset color to default (often white on black for MUDs)
        30: 'black', 31: 'red', 32: 'green', 33: 'yellow',
        34: 'blue', 35: 'magenta', 36: 'cyan', 37: 'white',
        # Bright colors (often codes 90-97)
        90: 'gray', 91: 'firebrick', 92: 'forestgreen', 93: 'gold',
        94: 'dodgerblue', 95: 'violet', 96: 'lightskyblue', 97: 'white'
    }
    # Add support for background colors if your MUD uses them
    # ANSI_BG_COLOR_MAP = {40: 'black', 41: 'red', ...}

    # Regex to find ANSI escape sequences: captures codes like "0", "31", "1;32"
    ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[([0-9;]*)m')
    
    # --- Fix 6: Regex to find common Telnet IAC (Interpret As Command) sequences ---
    # This is a simplification; a full Telnet protocol parser is complex.
    # It attempts to catch common patterns like IAC WILL/DO/WONT/DONT OPTION, IAC SB ... IAC SE
    TELNET_IAC_PATTERN = re.compile(rb'\xff[\xfb-\xfe][\x01-\xff]|\xff\xf0|\xff\xfa[\x01-\xff]*?\xff\xf0')


    def __init__(self, root):
        self.root = root
        self.root.title("MUD Client")
        self.profile_manager = ProfileManager()

        # --- Fix 1: Initialize socket and connection state ---
        self.sock = None
        self.receive_thread = None
        self.connected = False # Keep track of connection status

        self.setup_gui()
        self.create_hud()
        self.define_text_tags() # Define Tkinter text tags after output_text is created

        self.update_gui_state() # --- Fix 7: Set initial GUI state correctly ---

        # Handle window close event gracefully
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_gui(self):
        # Frame for profile management
        profile_frame = tk.Frame(self.root)
        profile_frame.pack(fill=tk.X, pady=5, padx=5, expand=False) # expand=False for frames that contain fixed-height elements

        self.profile_listbox = tk.Listbox(profile_frame, height=5) # --- Fix 7: Fixed height for listbox ---
        self.profile_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True) # --- Fix 7: Fill and expand ---

        profile_btn_frame = tk.Frame(profile_frame) # Buttons for profile manager
        profile_btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5)

        self.add_btn = tk.Button(profile_btn_frame, text="Add Profile", command=self.add_profile)
        self.add_btn.pack(fill=tk.X, pady=2)

        self.remove_btn = tk.Button(profile_btn_frame, text="Remove Profile", command=self.remove_profile)
        self.remove_btn.pack(fill=tk.X, pady=2)
        
        self.load_profiles() # Load profiles on startup

        # Connect/Disconnect buttons frame
        connect_disconnect_frame = tk.Frame(self.root)
        connect_disconnect_frame.pack(fill=tk.X, pady=2, padx=5, expand=False)

        self.connect_btn = tk.Button(connect_disconnect_frame, text="Connect", command=self.connect_to_profile)
        self.connect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # --- Fix 2: Add Disconnect Button ---
        self.disconnect_btn = tk.Button(connect_disconnect_frame, text="Disconnect", command=self.disconnect)
        self.disconnect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)


        # Main output text area with scrollbar
        # --- Fix 7: Use ScrolledText for output_text for automatic scrollbar ---
        text_frame = tk.Frame(self.root)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=5, padx=5)

        self.output_text = scrolledtext.ScrolledText(text_frame, state=tk.DISABLED, wrap=tk.WORD, bg="black", fg="white", font=("Courier New", 10))
        self.output_text.pack(fill=tk.BOTH, expand=True)

        # Input entry
        self.input_entry = tk.Entry(self.root)
        self.input_entry.pack(fill=tk.X, expand=False, pady=(0,5), padx=5) # Keep expand=False for entry
        self.input_entry.bind("<Return>", self.send_message)

    # --- Fix 8: Define tags for the Text widget ---
    def define_text_tags(self):
        """Define tags for ANSI colors and common styles in the output_text widget."""
        self.output_text.tag_config("default", foreground="white", background="black") # Default color

        # Foreground colors (e.g., ansi_31 for red foreground)
        for code, color_name in self.ANSI_COLOR_MAP.items():
            self.output_text.tag_config(f"ansi_{code}", foreground=color_name)
        
        # System messages (e.g., connect/disconnect info)
        self.output_text.tag_config("system_message", foreground="lightgray", font=("TkDefaultFont", 10, "italic"))
        # Add styles (e.g., bold, underline if needed) - for simplicity, not fully implemented here
        # self.output_text.tag_config("bold", font=("TkDefaultFont", 10, "bold"))


    def load_profiles(self):
        self.profile_listbox.delete(0, tk.END)
        for profile_name in self.profile_manager.profiles:
            self.profile_listbox.insert(tk.END, profile_name)
        if self.profile_manager.profiles:
            self.profile_listbox.selection_set(0) # Select first profile by default


    def add_profile(self):
        name = simpledialog.askstring("Profile Name", "Enter profile name:")
        if not name: return # User cancelled
        if name in self.profile_manager.profiles:
            messagebox.showerror("Error", "Profile with this name already exists.")
            return
        host = simpledialog.askstring("Host", "Enter host address:")
        if not host: return # User cancelled
        try:
            port = simpledialog.askinteger("Port", "Enter port number:")
            if port is None: return # User cancelled
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
        self.hud_frame = tk.Frame(self.root, bg="#333333") # Darker gray
        self.hud_frame.pack(side=tk.TOP, fill=tk.X, expand=False)

        self.connection_label = tk.Label(self.hud_frame, text="Disconnected", bg="#333333", fg="red", font=("Arial", 10, "bold"))
        self.connection_label.pack(side=tk.LEFT, padx=10, pady=5)

        self.health_label = tk.Label(self.hud_frame, text="Health: N/A", bg="#333333", fg="white", font=("Arial", 10))
        self.health_label.pack(side=tk.LEFT, padx=10, pady=5)

        self.status_message_label = tk.Label(self.hud_frame, text="", bg="#333333", fg="lightblue", font=("Arial", 10))
        self.status_message_label.pack(side=tk.RIGHT, padx=10, pady=5)

    # --- Fix 7: Update GUI state based on connection status ---
    def update_gui_state(self):
        if self.connected:
            self.connect_btn.config(state=tk.DISABLED)
            self.disconnect_btn.config(state=tk.NORMAL)
            self.input_entry.config(state=tk.NORMAL)
            self.profile_listbox.config(state=tk.DISABLED) # Disable profile management while connected
            self.add_btn.config(state=tk.DISABLED)
            self.remove_btn.config(state=tk.DISABLED)
            self.connection_label.config(text="Connected", fg="green")
            self.status_message_label.config(text="Online")
        else:
            self.connect_btn.config(state=tk.NORMAL)
            self.disconnect_btn.config(state=tk.DISABLED)
            self.input_entry.config(state=tk.DISABLED)
            self.profile_listbox.config(state=tk.NORMAL) # Enable profile management when disconnected
            self.add_btn.config(state=tk.NORMAL)
            self.remove_btn.config(state=tk.NORMAL)
            self.connection_label.config(text="Not connected", fg="red")
            self.status_message_label.config(text="Offline")


    def update_connection_status(self, connected):
        self.connected = connected
        self.update_gui_state()


    # --- Fix 3: Ensure GUI updates are thread-safe ---
    def update_health(self, health):
        self.root.after(0, lambda: self.health_label.config(text=f"Health: {health}"))


    def display_message(self, message, tags=None): # Changed color to tags
        """Displays a message in the output text widget with specified tags."""
        self.output_text.config(state=tk.NORMAL)
        # --- Fix 8: Apply tags correctly ---
        # If tags is None, use "default" tag
        self.output_text.insert(tk.END, message, tags if tags is not None else "default")
        self.output_text.insert(tk.END, "\n")
        self.output_text.config(state=tk.DISABLED)
        self.output_text.yview(tk.END) # Auto-scroll to bottom


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
            self.display_message(f"--- Attempting to connect to {profile['host']}:{profile['port']} ---", tags=("system_message",))
            self.status_message_label.config(text="Connecting...")
            
            # --- Fix 1: Use a thread for connection to prevent GUI freeze ---
            connection_thread = threading.Thread(target=self._initiate_connection, args=(profile['host'], profile['port']))
            connection_thread.daemon = True # Allows thread to exit with main program if main thread exits
            connection_thread.start()
        else:
            messagebox.showerror("Error", "Selected profile not found. Please reload profiles.")
            self.load_profiles()


    # --- Fix 1: New method for thread-safe connection handling ---
    def _initiate_connection(self, host, port):
        """Internal method to handle socket connection in a separate thread."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5) # Set a timeout for connection attempt
            self.sock.connect((host, port))
            self.sock.settimeout(None) # Remove timeout after connection for blocking recv

            # All GUI updates must be called via root.after from this thread
            self.root.after(0, self.update_connection_status, True)
            self.root.after(0, self.display_message, "--- Connected to MUD ---", tags=("system_message", "ansi_32")) # Green for connected

            self.receive_thread = threading.Thread(target=self.receive_messages)
            self.receive_thread.daemon = True
            self.receive_thread.start()
            
        except socket.timeout:
            self.root.after(0, self.display_message, "Connection timed out.", tags=("system_message", "ansi_31")) # Red for error
            self.root.after(0, self.update_connection_status, False)
            logging.error(f"Connection timed out to {host}:{port}")
        except socket.error as e: # --- Fix 4: More specific exception handling ---
            self.root.after(0, self.display_message, f"Connection error: {e}", tags=("system_message", "ansi_31"))
            self.root.after(0, self.update_connection_status, False)
            logging.error(f"Socket error connecting to {host}:{port}: {e}")
        except Exception as e:
            self.root.after(0, self.display_message, f"An unexpected error occurred during connection: {e}", tags=("system_message", "ansi_31"))
            self.root.after(0, self.update_connection_status, False)
            logging.exception("Unexpected error during connection")


    # --- Fix 2: Disconnect method for graceful shutdown ---
    def disconnect(self):
        if not self.connected or not self.sock:
            # messagebox.showwarning("Warning", "Not connected to disconnect.") # Can be noisy
            logging.info("Attempted to disconnect when not connected.")
            return
        
        try:
            # Shutdown both send and receive to properly close the connection
            # This will cause the recv() in the receive_messages thread to error out (socket.error),
            # allowing the thread to terminate.
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            logging.info("Socket closed.")
        except socket.error as e:
            logging.warning(f"Error during socket shutdown/close: {e}")
        except Exception as e:
            logging.warning(f"Unexpected error during disconnect: {e}")
        finally:
            self.sock = None
            self.receive_thread = None # The thread should naturally terminate due to socket closure
            self.root.after(0, self.update_connection_status, False)
            self.root.after(0, self.display_message, "--- Disconnected from MUD ---", tags=("system_message", "ansi_31"))


    def receive_messages(self):
        # Using a buffer to handle partial messages and Telnet IACs
        buffer = b""
        while self.connected: # --- Fix 2: Use self.connected to control the loop ---
            try:
                message_bytes = self.sock.recv(4096) # Receive a larger chunk of data

                # --- Fix 4: Handle server disconnect (recv returns empty bytes) ---
                if not message_bytes: # Server closed connection
                    logging.info("Server disconnected gracefully.")
                    self.root.after(0, self.display_message, "--- Server disconnected unexpectedly ---", tags=("system_message", "ansi_31"))
                    self.root.after(0, self.disconnect) # Initiate clean disconnect sequence
                    break # Exit the thread loop
                
                buffer += message_bytes
                
                # --- Fix 6: Basic Telnet IAC stripping ---
                # This is a very simplistic IAC stripper. A full implementation is complex.
                # It tries to remove common IAC patterns that appear as garbage.
                processed_buffer = self.TELNET_IAC_PATTERN.sub(b'', buffer)

                try:
                    # Attempt to decode the entire buffer as UTF-8
                    message = processed_buffer.decode('utf-8')
                    buffer = b"" # Clear buffer if successfully decoded
                except UnicodeDecodeError:
                    # If UTF-8 fails, try a more lenient decoding and log it.
                    # A more advanced buffer management would try to identify where the decode failed
                    # and keep the undecodable bytes in the buffer for the next recv.
                    # For simplicity, we'll decode what we can and clear the buffer here.
                    message = processed_buffer.decode('latin-1', errors='replace') # Replace invalid chars
                    buffer = b"" # Clear buffer for this example
                    logging.warning("UnicodeDecodeError encountered, falling back to latin-1 for display.")


                if message:
                    # --- Fix 3: All GUI updates must be called via root.after ---
                    self.root.after(0, self.parse_and_display_message, message)
                    # GMCP parsing also needs to be on the main thread for HUD updates
                    self.root.after(0, self.parse_gmcp_and_hud, message)
            
            # --- Fix 4: More specific exception handling ---
            except socket.timeout:
                # Should not happen with self.sock.settimeout(None) after connect,
                # but good to have if timeouts are used elsewhere.
                pass 
            except socket.error as e:
                # This exception occurs if the socket is closed (e.g., by disconnect()) or network issues
                if self.connected: # Only log error if we thought we were still connected
                    logging.error(f"Socket error in receive_messages: {e}")
                    self.root.after(0, self.display_message, f"--- Network error: {e} ---", tags=("system_message", "ansi_31"))
                    self.root.after(0, self.disconnect) # Initiate clean disconnect
                break # Exit the thread loop
            except Exception as e:
                logging.exception(f"An unexpected error occurred in receive_messages: {e}")
                self.root.after(0, self.display_message, f"--- An unexpected error occurred: {e} ---", tags=("system_message", "ansi_31"))
                self.root.after(0, self.disconnect) # Initiate clean disconnect
                break # Exit the thread loop


    def parse_and_display_message(self, message):
        """
        --- Fix 5 & 8: Parses ANSI escape codes and displays text with appropriate Tkinter tags. ---
        This runs on the main Tkinter thread.
        """
        self.output_text.config(state=tk.NORMAL)
        
        # Keep track of current active foreground color
        current_fg_tag = "default" # Start with default tag

        parts = self.ANSI_ESCAPE_PATTERN.split(message)
        
        # Iterate through the split parts: [text_before_ansi, codes, text_after_ansi, codes, ...]
        for i in range(len(parts)):
            if i % 2 == 0: # This is a text part
                text_to_display = parts[i]
                if text_to_display:
                    # Insert text with the current foreground tag
                    self.output_text.insert(tk.END, text_to_display, current_fg_tag)
            else: # This is the part containing the ANSI codes (e.g., "0" or "31" or "1;32")
                codes_str = parts[i]
                if codes_str: # Check if codes_str is not empty (e.g., from \x1b[m)
                    # Handle multiple codes like "1;31"
                    codes = [int(c) for c in codes_str.split(';') if c] # Filter empty strings from split

                    for code in codes:
                        if code == 0: # Reset all attributes
                            current_fg_tag = "default"
                            # If handling bold/underline/background, reset them here too
                        elif code in self.ANSI_COLOR_MAP: # Foreground color
                            current_fg_tag = f"ansi_{code}"
                        # Add logic for bold, underline, background colors here if defined in tags
        
        self.output_text.insert(tk.END, "\n") # Always add a newline after processing a full line of MUD output
        self.output_text.config(state=tk.DISABLED)
        self.output_text.yview(tk.END) # Auto-scroll to bottom


    def parse_gmcp_and_hud(self, message):
        """
        Simplified GMCP parsing and HUD update.
        This function runs on the main Tkinter thread.
        """
        # This is a very basic simulation. Real GMCP parsing is more involved
        # and usually involves listening for specific Telnet subnegotiation (IAC SB GMCP ...)
        # For this simplified example, we're just looking for "GMCP " in the decoded text.
        
        if "GMCP" in message:
            try:
                # Find the GMCP payload. This needs to be robust for real MUDs.
                gmcp_start_index = message.find("GMCP ")
                if gmcp_start_index != -1:
                    gmcp_payload = message[gmcp_start_index + len("GMCP "):].strip()
                    
                    # GMCP is often in the format "Package.Subpackage JSON_DATA"
                    parts = gmcp_payload.split(" ", 1)
                    if len(parts) == 2:
                        package_name = parts[0]
                        json_str = parts[1]
                        
                        if package_name == "Char.Vitals":
                            data = json.loads(json_str)
                            if 'hp' in data and 'maxhp' in data:
                                self.update_health(f"{data['hp']}/{data['maxhp']}")
                            elif 'hp' in data: # sometimes just HP is sent
                                self.update_health(f"{data['hp']}")
                            # You can extend this for 'mana', 'endurance', etc.
                        elif package_name == "Char.Status":
                            data = json.loads(json_str)
                            if 'status' in data:
                                self.status_message_label.config(text=f"Status: {data['status']}")
                            # Add more GMCP package handling as needed

            except (IndexError, json.JSONDecodeError, ValueError) as e:
                logging.error(f"Error parsing GMCP message: {e} - Raw: {message}")
            except Exception as e:
                logging.exception(f"Unexpected error in GMCP parsing: {e} - Raw: {message}")


    def send_message(self, event=None): # Added event=None for direct calls if needed
        # --- Fix 1: Check if connected before sending ---
        if not self.connected or not self.sock:
            self.display_message("--- Not connected. Cannot send message. ---", tags=("system_message", "ansi_31"))
            return

        message = self.input_entry.get()
        if not message.strip(): # Don't send empty messages
            return

        try:
            self.sock.sendall((message + "\n").encode('utf-8')) # Send newline for MUD commands
            self.input_entry.delete(0, tk.END)
        except socket.error as e: # --- Fix 4: Error handling for sending ---
            self.display_message(f"--- Failed to send message: {e} ---", tags=("system_message", "ansi_31"))
            logging.error(f"Failed to send message: {e}")
            self.disconnect() # Assume connection issue and disconnect
        except Exception as e:
            self.display_message(f"--- Unexpected error sending message: {e} ---", tags=("system_message", "ansi_31"))
            logging.exception(f"Unexpected error sending message: {e}")


    def on_closing(self):
        """Handles closing the application window gracefully."""
        if self.connected:
            if messagebox.askokcancel("Quit", "You are connected. Disconnect and quit?"):
                self.disconnect() # Disconnect first
                self.root.destroy()
            # If user cancels, keep window open
        else:
            self.root.destroy()


# Main application execution
if __name__ == "__main__":
    root = tk.Tk()
    app = MUDClientApp(root)
    root.mainloop()
