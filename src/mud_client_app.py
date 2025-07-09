# src/mud_client_app.py

import tkinter as tk
from tkinter import messagebox, simpledialog, scrolledtext
from src.profile_manager import ProfileManager # Correct import for src.profile_manager
import socket
import threading
import re
import json
import logging
import os # For path manipulation and directory checks
import importlib.util # For dynamic module loading
import sys # For managing sys.path

# Configure basic logging for the entire application
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MUDClientApp:
    """
    A basic Tkinter-based MUD client application with profile management and mod loading.
    """

    # ANSI color codes to Tkinter tag mapping for text output
    ANSI_COLOR_MAP = {
        0: 'white', # Reset/Default
        30: 'black', 31: 'red', 32: 'green', 33: 'yellow',
        34: 'blue', 35: 'magenta', 36: 'cyan', 37: 'white', # Standard ANSI colors
        90: 'gray', 91: 'firebrick', 92: 'forestgreen', 93: 'gold',
        94: 'dodgerblue', 95: 'violet', 96: 'lightskyblue', 97: 'white' # Bright ANSI colors
    }
    
    # Regular expression to find ANSI escape sequences
    ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[([0-9;]*)m')
    
    # Regular expression to remove Telnet IAC (Interpret As Command) sequences
    # This prevents control characters from showing up in the output
    TELNET_IAC_PATTERN = re.compile(rb'\xff[\xfb-\xfe][\x01-\xff]|\xff\xf0|\xff\xfa[\x01-\xff]*?\xff\xf0')


    def __init__(self, root):
        """Initializes the MUD Client Application."""
        self.root = root
        self.root.title("Python MUD Client") # Set window title

        # Initialize profile manager
        self.profile_manager = ProfileManager() 

        # Connection state variables
        self.sock = None
        self.receive_thread = None
        self.connected = False
        self.loaded_mods = [] # List to store references to successfully loaded mod modules

        # Setup GUI elements
        self.setup_gui()
        self.create_hud() # Heads-Up Display
        self.define_text_tags() # Define special text tags for coloring

        # Load user mods
        self.load_mods() # Call load_mods here after GUI is set up to integrate mod UIs

        # Update initial GUI state based on connection status
        self.update_gui_state()

        # Handle window closing event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_gui(self):
        """Sets up the main graphical user interface elements."""
        # Main content frame to hold everything except potential right-side mods
        # This frame takes up the left and center part of the window
        main_content_frame = tk.Frame(self.root)
        main_content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Profile management frame (top-left)
        profile_frame = tk.Frame(main_content_frame)
        profile_frame.pack(fill=tk.X, pady=5, expand=False)

        self.profile_listbox = tk.Listbox(profile_frame, height=5)
        self.profile_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        profile_btn_frame = tk.Frame(profile_frame)
        profile_btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5)

        self.add_btn = tk.Button(profile_btn_frame, text="Add Profile", command=self.add_profile)
        self.add_btn.pack(fill=tk.X, pady=2)

        self.remove_btn = tk.Button(profile_btn_frame, text="Remove Profile", command=self.remove_profile)
        self.remove_btn.pack(fill=tk.X, pady=2)
        
        self.load_profiles() # Populate the listbox with saved profiles

        # Connect/Disconnect buttons frame (below profiles)
        connect_disconnect_frame = tk.Frame(main_content_frame)
        connect_disconnect_frame.pack(fill=tk.X, pady=2, expand=False)

        self.connect_btn = tk.Button(connect_disconnect_frame, text="Connect", command=self.connect_to_profile)
        self.connect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        self.disconnect_btn = tk.Button(connect_disconnect_frame, text="Disconnect", command=self.disconnect)
        self.disconnect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Main output text area with scrollbar (center)
        text_frame = tk.Frame(main_content_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.output_text = scrolledtext.ScrolledText(text_frame, state=tk.DISABLED, wrap=tk.WORD, bg="black", fg="white", font=("Courier New", 10))
        self.output_text.pack(fill=tk.BOTH, expand=True)

        # Input entry field (bottom-left)
        self.input_entry = tk.Entry(main_content_frame)
        self.input_entry.pack(fill=tk.X, expand=False, pady=(0,5))
        self.input_entry.bind("<Return>", self.send_message) # Send message on Enter key press

        # NEW: Frame for mods on the right side of the main window
        self.mod_container_frame = tk.Frame(self.root, bd=2, relief=tk.GROOVE) # Border and relief for visual separation
        self.mod_container_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5, expand=False) 

        self.mod_label = tk.Label(self.mod_container_frame, text="Loaded Mods", font=("Arial", 10, "bold"), bg=self.mod_container_frame.cget('bg'))
        self.mod_label.pack(side=tk.TOP, pady=5)

    def define_text_tags(self):
        """Defines custom text tags for the output text widget."""
        self.output_text.tag_config("default", foreground="white", background="black")

        # Configure tags for ANSI colors
        for code, color_name in self.ANSI_COLOR_MAP.items():
            self.output_text.tag_config(f"ansi_{code}", foreground=color_name)
        
        # Tag for system messages (e.g., connection status)
        self.output_text.tag_config("system_message", foreground="lightgray", font=("TkDefaultFont", 10, "italic"))

    def load_profiles(self):
        """Loads profiles from ProfileManager into the listbox."""
        self.profile_listbox.delete(0, tk.END) # Clear existing items
        for profile_name in self.profile_manager.profiles:
            self.profile_listbox.insert(tk.END, profile_name) # Insert each profile name
        if self.profile_manager.profiles:
            self.profile_listbox.selection_set(0) # Select the first profile by default if any exist

    def add_profile(self):
        """Prompts user for new profile details and adds it via ProfileManager."""
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
        self.load_profiles() # Refresh listbox to show the new profile
        messagebox.showinfo("Success", f"Profile '{name}' added.")

    def remove_profile(self):
        """Removes the selected profile via ProfileManager."""
        selected_index = self.profile_listbox.curselection()
        if not selected_index:
            messagebox.showwarning("Warning", "No profile selected to remove.")
            return
        selected_profile = self.profile_listbox.get(selected_index[0])
        if messagebox.askyesno("Confirm Remove", f"Are you sure you want to remove '{selected_profile}'?"):
            self.profile_manager.remove_profile(selected_profile)
            self.load_profiles() # Refresh listbox
            messagebox.showinfo("Success", f"Profile '{selected_profile}' removed.")

    def create_hud(self):
        """Creates the Heads-Up Display (HUD) elements."""
        self.hud_frame = tk.Frame(self.root, bg="#333333") # Dark background for the HUD
        self.hud_frame.pack(side=tk.TOP, fill=tk.X, expand=False) 

        self.connection_label = tk.Label(self.hud_frame, text="Disconnected", bg="#333333", fg="red", font=("Arial", 10, "bold"))
        self.connection_label.pack(side=tk.LEFT, padx=10, pady=5)

        self.health_label = tk.Label(self.hud_frame, text="Health: N/A", bg="#333333", fg="white", font=("Arial", 10))
        self.health_label.pack(side=tk.LEFT, padx=10, pady=5)

        self.status_message_label = tk.Label(self.hud_frame, text="", bg="#333333", fg="lightblue", font=("Arial", 10))
        self.status_message_label.pack(side=tk.RIGHT, padx=10, pady=5)

    def update_gui_state(self):
        """Updates GUI element states based on connection status."""
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
        """Updates the internal connection status and triggers GUI update."""
        self.connected = connected
        self.update_gui_state()

    def update_health(self, health):
        """Updates the health label in the HUD."""
        self.root.after(0, lambda: self.health_label.config(text=f"Health: {health}"))

    def display_message(self, message, tags=None):
        """Appends a message to the output text area."""
        self.output_text.config(state=tk.NORMAL) # Enable editing temporarily
        self.output_text.insert(tk.END, message, tags if tags is not None else "default")
        self.output_text.insert(tk.END, "\n") # Add newline after message
        self.output_text.config(state=tk.DISABLED) # Disable editing
        self.output_text.yview(tk.END) # Scroll to the end

    def connect_to_profile(self):
        """Initiates connection to the selected MUD profile."""
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
            
            # Start connection in a separate thread to keep GUI responsive
            connection_thread = threading.Thread(target=self._initiate_connection, args=(profile['host'], profile['port']))
            connection_thread.daemon = True # Allow app to exit even if thread is running
            connection_thread.start()
        else:
            messagebox.showerror("Error", "Selected profile not found. Please reload profiles.")
            self.load_profiles() # Reload profiles in case file changed

    def _initiate_connection(self, host, port):
        """Internal method to handle the actual socket connection."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5) # Short timeout for initial connection
            self.sock.connect((host, port))
            self.sock.settimeout(None) # Remove timeout after connection for blocking recv

            # Update GUI on main thread
            self.root.after(0, self.update_connection_status, True)
            self.root.after(0, lambda: self.display_message("--- Connected to MUD ---", tags=("system_message", "ansi_32")))

            # Start receiving messages in a separate thread
            self.receive_thread = threading.Thread(target=self.receive_messages)
            self.receive_thread.daemon = True
            self.receive_thread.start()
            
        except socket.timeout:
            self.root.after(0, lambda: self.display_message("Connection timed out.", tags=("system_message", "ansi_31")))
            self.root.after(0, self.update_connection_status, False)
            logging.error(f"Connection timed out to {host}:{port}")
        except socket.error as e:
            self.root.after(0, lambda msg_text=f"Connection error: {e}": self.display_message(msg_text, tags=("system_message", "ansi_31")))
            self.root.after(0, self.update_connection_status, False)
            logging.error(f"Socket error connecting to {host}:{port}: {e}")
        except Exception as e:
            self.root.after(0, lambda msg_text=f"An unexpected error occurred during connection: {e}": self.display_message(msg_text, tags=("system_message", "ansi_31")))
            self.root.after(0, self.update_connection_status, False)
            logging.exception("Unexpected error during connection")

    def disconnect(self):
        """Disconnects from the MUD."""
        if not self.connected or not self.sock:
            logging.info("Attempted to disconnect when not connected.")
            return
        
        try:
            # Attempt to gracefully shut down the socket
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            logging.info("Socket closed.")
        except socket.error as e:
            logging.warning(f"Error during socket shutdown/close: {e}")
        except Exception as e:
            logging.warning(f"Unexpected error during disconnect: {e}")
        finally:
            self.sock = None
            self.receive_thread = None # Clear thread reference
            self.root.after(0, self.update_connection_status, False) # Update GUI
            self.root.after(0, lambda: self.display_message("--- Disconnected from MUD ---", tags=("system_message", "ansi_31")))

    def receive_messages(self):
        """Receives and processes messages from the MUD server."""
        buffer = b"" # Buffer to hold incomplete messages
        while self.connected:
            try:
                # Receive data in chunks
                message_bytes = self.sock.recv(4096)

                if not message_bytes:
                    # Server closed the connection
                    logging.info("Server disconnected gracefully.")
                    self.root.after(0, lambda: self.display_message("--- Server disconnected unexpectedly ---", tags=("system_message", "ansi_31")))
                    self.root.after(0, self.disconnect)
                    break # Exit receive loop
                
                buffer += message_bytes # Add received bytes to buffer
                
                # Remove Telnet IAC sequences before decoding
                processed_buffer = self.TELNET_IAC_PATTERN.sub(b'', buffer)

                try:
                    # Attempt to decode as UTF-8 (common for modern MUDs)
                    message = processed_buffer.decode('utf-8')
                    buffer = b"" # Clear buffer if successful
                except UnicodeDecodeError:
                    # Fallback to Latin-1 if UTF-8 fails (common for older MUDs/special chars)
                    message = processed_buffer.decode('latin-1', errors='replace')
                    buffer = b"" # Clear buffer if successful
                    logging.warning("UnicodeDecodeError encountered, falling back to latin-1 for display.")

                if message:
                    # Process and display message on main thread
                    self.root.after(0, self.parse_and_display_message, message)
                    # Attempt to parse GMCP for HUD updates
                    self.root.after(0, self.parse_gmcp_and_hud, message)
            
            except socket.timeout:
                # This should ideally not happen if timeout is None, but good to handle
                pass
            except socket.error as e:
                # Handle socket errors (e.g., connection reset by peer)
                if self.connected: # Only log/disconnect if we were actively connected
                    logging.error(f"Socket error in receive_messages: {e}")
                    self.root.after(0, lambda msg_text=f"--- Network error: {e} ---": self.display_message(msg_text, tags=("system_message", "ansi_31")))
                    self.root.after(0, self.disconnect)
                break # Exit receive loop
            except Exception as e:
                # Catch any other unexpected errors
                logging.exception(f"An unexpected error occurred in receive_messages: {e}")
                self.root.after(0, lambda msg_text=f"--- An unexpected error occurred: {e} ---": self.display_message(msg_text, tags=("system_message", "ansi_31")))
                self.root.after(0, self.disconnect)
                break # Exit receive loop

    def parse_and_display_message(self, message):
        """Parses ANSI escape codes and displays colored text in the output area."""
        self.output_text.config(state=tk.NORMAL)
        
        current_fg_tag = "default" # Start with default color

        # Split message by ANSI escape sequences
        parts = self.ANSI_ESCAPE_PATTERN.split(message)
        
        for i in range(len(parts)):
            if i % 2 == 0:
                # This is plain text
                text_to_display = parts[i]
                if text_to_display:
                    self.output_text.insert(tk.END, text_to_display, current_fg_tag)
            else:
                # This is an ANSI code string (e.g., "31;1" or "0")
                codes_str = parts[i]
                if codes_str:
                    codes = [int(c) for c in codes_str.split(';') if c]

                    for code in codes:
                        if code == 0: # Reset code
                            current_fg_tag = "default"
                        elif code in self.ANSI_COLOR_MAP:
                            current_fg_tag = f"ansi_{code}" # Apply specific color tag
        
        self.output_text.insert(tk.END, "\n") # Always add a newline at the end of each message
        self.output_text.config(state=tk.DISABLED)
        self.output_text.yview(tk.END) # Scroll to the bottom

    def parse_gmcp_and_hud(self, message):
        """
        Attempts to parse GMCP (Generic MUD Communication Protocol) messages
        to update HUD elements. This is a very basic example.
        """
        if "GMCP" in message:
            try:
                gmcp_start_index = message.find("GMCP ")
                if gmcp_start_index != -1:
                    # Extract the GMCP payload (e.g., "Char.Vitals {"hp": 100}")
                    gmcp_payload = message[gmcp_start_index + len("GMCP "):].strip()
                    
                    # Split into package name and JSON string
                    parts = gmcp_payload.split(" ", 1)
                    if len(parts) == 2:
                        package_name = parts[0]
                        json_str = parts[1]
                        
                        if package_name == "Char.Vitals":
                            data = json.loads(json_str)
                            if 'hp' in data and 'maxhp' in data:
                                self.update_health(f"{data['hp']}/{data['maxhp']}")
                            elif 'hp' in data: # Handle cases where maxhp might not be present
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
        """Sends the text from the input entry to the MUD."""
        if not self.connected or not self.sock:
            self.display_message("--- Not connected. Cannot send message. ---", tags=("system_message", "ansi_31"))
            return

        message = self.input_entry.get()
        if not message.strip(): # Don't send empty messages
            return

        try:
            self.sock.sendall((message + "\n").encode('utf-8')) # Encode and add newline
            self.input_entry.delete(0, tk.END) # Clear input field
        except socket.error as e:
            self.display_message(f"--- Failed to send message: {e} ---", tags=("system_message", "ansi_31"))
            logging.error(f"Failed to send message: {e}")
            self.disconnect() # Disconnect on send error
        except Exception as e:
            self.display_message(f"--- Unexpected error sending message: {e} ---", tags=("system_message", "ansi_31"))
            logging.exception(f"Unexpected error sending message: {e}")

    # Mod loading functionality
    def load_mods(self):
        """
        Discovers and loads Python modules from the 'mods' directory
        located in the project's root folder.
        """
        # Determine the directory of the current script (src/mud_client_app.py)
        current_script_dir = os.path.dirname(__file__)
        # Go up one level from 'src' to 'your_project_root'
        parent_dir = os.path.abspath(os.path.join(current_script_dir, os.pardir))
        # Construct the full path to the 'mods' directory
        mods_dir = os.path.join(parent_dir, "mods")

        # Ensure the mods directory exists
        if not os.path.exists(mods_dir):
            os.makedirs(mods_dir)
            self.display_message(f"--- Created '{mods_dir}' directory for mods. ---", tags=("system_message",))
            return

        # Add the mods directory to Python's path so modules can be imported dynamically
        if mods_dir not in sys.path:
            sys.path.insert(0, mods_dir)
            logging.info(f"Added '{mods_dir}' to sys.path.")

        self.display_message(f"--- Loading mods from '{mods_dir}' ---", tags=("system_message",))
        
        # Clear previously loaded mods and their GUI elements
        for mod_instance in self.loaded_mods:
            if hasattr(mod_instance, '_mod_frame') and mod_instance._mod_frame.winfo_exists():
                mod_instance._mod_frame.destroy() # Destroy the mod's specific GUI frame
            # If mod had any cleanup logic, you'd call it here
        self.loaded_mods = [] # Reset the list of loaded mods

        # Iterate through files in the mods directory
        for filename in os.listdir(mods_dir):
            if filename.endswith(".py") and filename != "__init__.py": # Process Python files, ignore __init__.py
                module_name = filename[:-3] # Get module name by removing .py extension
                file_path = os.path.join(mods_dir, filename)
                
                try:
                    # Create a module specification from the file path
                    spec = importlib.util.spec_from_file_location(module_name, file_path)
                    if spec is None:
                        logging.error(f"Could not load module spec for {filename}")
                        self.root.after(0, lambda fn=filename: self.display_message(f"--- Failed to load mod '{fn}': Invalid module spec. ---", tags=("system_message", "ansi_31")))
                        continue

                    # Create a new module object and execute its code
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = mod # Add to sys.modules to prevent re-imports/resolve internal dependencies
                    spec.loader.exec_module(mod) # Run the module's code

                    # Check if the mod has the expected 'setup_mod_gui' function
                    if hasattr(mod, 'setup_mod_gui') and callable(mod.setup_mod_gui):
                        # Create a dedicated Tkinter LabelFrame for this mod's GUI
                        mod_frame = tk.LabelFrame(self.mod_container_frame, text=module_name.replace('_', ' ').title(), padx=5, pady=5)
                        mod_frame.pack(fill=tk.X, pady=5, padx=5, expand=False) # Each mod frame fills horizontally within its container
                        
                        # Store a reference to this frame on the mod object itself
                        # This allows the client to clean up the mod's GUI if mods are reloaded
                        mod._mod_frame = mod_frame 

                        # Call the mod's setup function, passing its designated frame and the client instance
                        # This allows the mod to build its GUI and interact with the client
                        mod.setup_mod_gui(mod_frame, self)
                        self.loaded_mods.append(mod) # Store reference to the loaded module
                        self.root.after(0, lambda mn=module_name: self.display_message(f"--- Mod '{mn}' loaded successfully. ---", tags=("system_message", "ansi_32")))
                    else:
                        self.root.after(0, lambda fn=filename: self.display_message(f"--- Mod '{fn}' skipped: 'setup_mod_gui' function not found or not callable. ---", tags=("system_message", "ansi_33")))
                        logging.warning(f"Mod '{filename}' skipped: 'setup_mod_gui' function not found or not callable.")

                except Exception as e:
                    # Log and display any errors during mod loading
                    self.root.after(0, lambda fn=filename, err=e: self.display_message(f"--- Error loading mod '{fn}': {err} ---", tags=("system_message", "ansi_31")))
                    logging.exception(f"Error loading mod '{filename}'")
        self.root.after(0, lambda: self.display_message(f"--- Finished loading mods. Loaded {len(self.loaded_mods)} mods. ---", tags=("system_message",)))

    def on_closing(self):
        """Handles closing the application window gracefully, prompting to disconnect if connected."""
        if self.connected:
            if messagebox.askokcancel("Quit", "You are connected. Disconnect and quit?"):
                self.disconnect() # Disconnect first
                self.root.destroy() # Close the window
            # If user cancels, keep window open
        else:
            self.root.destroy() # If not connected, just close the window
