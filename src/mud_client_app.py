import tkinter as tk
from tkinter import messagebox, simpledialog, scrolledtext
from .profile_manager import ProfileManager # Relative import
import socket
import threading
import re
import json
import logging
import os
import importlib.util
import sys
import time

# NEW IMPORTS: For Alias Management and new Profile Windows
from .alias_manager import AliasManager # Relative import
from .alias_manager_window import AliasManagerWindow # Relative import
from .profile_selection_dialog import ProfileSelectionDialog # NEW
from .profile_manager_window import ProfileManagerWindow # NEW

# I'm setting the logging level to DEBUG for thorough analysis.
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class MUDClientApp:
    """
    My Tkinter-based MUD client application, featuring profile management,
    mod loading, and robust Telnet/GMCP parsing.
    """

    # My mappings for ANSI color codes to Tkinter text tags.
    ANSI_COLOR_MAP = {
        0: 'white', # Reset/Default
        30: 'black', 31: 'red', 32: 'green', 33: 'yellow',
        34: 'blue', 35: 'magenta', 36: 'cyan', 37: 'white', # Standard ANSI colors
        90: 'gray', 91: 'firebrick', 92: 'forestgreen', 93: 'gold',
        94: 'dodgerblue', 95: 'dodgerblue', 96: 'lightskyblue', 97: 'white' # Bright ANSI colors
    }
    
    # My regular expression to find ANSI escape sequences.
    ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[([0-9;]*)m')
    
    # --- My Telnet Protocol Constants ---
    # IAC (Interpret As Command)
    IAC = b'\xff'
    # Telnet Commands
    DONT = b'\xfe'
    DO = b'\xfd'
    WONT = b'\xfc'
    WILL = b'\xfb'
    SB = b'\xfa' # Subnegotiation Begin
    SE = b'\xf0' # Subnegotiation End
    # Other common IAC bytes (often sent alone or in simple sequences)
    NOP = b'\xf9' # No Operation
    GA = b'\xf9' # Go Ahead (often the same byte as NOP)

    # My Telnet Options
    ECHO = b'\x01' # 1
    SUPPRESS_GO_AHEAD = b'\x03' # 3
    NAWS = b'\x1f' # 31 (Negotiate About Window Size)
    GMCP = b'\xc9' # 201 (Generic Mud Communication Protocol - Standard Negotiation Byte)
    # MY CRITICAL CHANGE: INCLUDING 'E' AND ENSURING THE OPTION BYTE IS KEPT FOR GMCP DATA
    GMCP_DATA_OPTIONS = (b'R', b'C', b'E') # 82, 67, 69 (MY SUSPECTED GMCP DATA BYTES FOR THIS MUD - FOR TESTING!) 
    
    # My states for the Telnet parser.
    STATE_NORMAL = 0           # Default state, processing normal text
    STATE_IAC = 1              # Received an IAC byte, expecting a command
    STATE_SB_READ_OPTION = 2   # Received IAC SB, waiting for the option byte
    STATE_GMCP_SUB = 3         # Inside a GMCP subnegotiation, accumulating GMCP payload
    STATE_UNKNOWN_SB = 4       # Inside an unknown subnegotiation, consuming bytes until IAC SE

    def __init__(self, root):
        """I'm initializing my MUD Client Application."""
        self.root = root
        self.root.title("Python MUD Client")

        self.profile_manager = ProfileManager()
        self.alias_manager = AliasManager(alias_file="aliases.json")
        
        self.alias_window = None # To hold the instance of the alias manager window
        self.profile_manager_window = None # To hold the instance of the profile manager window

        self.sock = None
        self.receive_thread = None
        self.connected = False 
        self.current_profile = None # Stores the name of the currently connected profile

        self.loaded_mods = [] 
        self.gmcp_listeners = [] 

        # --- My Telnet Parsing State Variables ---
        self.telnet_buffer = b"" 
        self.telnet_parser_state = self.STATE_NORMAL
        self.telnet_sub_buffer = b"" 

        self.setup_gui()
        self.create_hud()
        self.define_text_tags()
        self.load_mods() 

        # I'm registering my client's own HUD as a GMCP listener.
        self.register_gmcp_listener(self._update_client_hud_from_gmcp)

        self.update_gui_state() 
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Load profiles immediately, but the GUI elements are now managed by update_gui_state
        self.load_profiles()

    def setup_gui(self):
        """I'm setting up the main graphical user interface elements."""
        # Create a menu bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # Create a "Servers" menu
        self.servers_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Servers", menu=self.servers_menu)
        self.servers_menu.add_command(label="Connect to Profile...", command=self.open_profile_selection_dialog)
        self.servers_menu.add_command(label="Disconnect", command=self.disconnect)
        self.servers_menu.add_separator()
        self.servers_menu.add_command(label="Manage Profiles...", command=self.open_profile_manager_window)

        # Create a "Tools" menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Alias Manager", command=self.open_alias_manager_window)

        # Main content frame for output and input
        main_content_frame = tk.Frame(self.root)
        main_content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # This frame will hold the profile selection GUI.
        # Its visibility will be controlled by update_gui_state.
        self.profile_frame = tk.LabelFrame(main_content_frame, text="Profile Selection", padx=10, pady=10)
        # self.profile_frame.pack(fill=tk.X, pady=5, expand=False) # REMOVED: Managed by update_gui_state

        # NOTE: The listbox and buttons are now managed within ProfileManagerWindow
        # but for initial display if not connected, we keep a placeholder or just
        # let update_gui_state handle initial pack().
        # However, since we're moving the selection, these are technically gone from the main view.
        # They will be recreated in ProfileManagerWindow.

        # The profile_listbox, add_btn, remove_btn are now part of ProfileManagerWindow
        # and ProfileSelectionDialog, NOT directly in MUDClientApp's main frame.

        text_frame = tk.Frame(main_content_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.output_text = scrolledtext.ScrolledText(text_frame, state=tk.DISABLED, wrap=tk.WORD, bg="black", fg="white", font=("Courier New", 10))
        self.output_text.pack(fill=tk.BOTH, expand=True)

        self.input_entry = tk.Entry(main_content_frame)
        self.input_entry.pack(fill=tk.X, expand=False, pady=(0,5))
        self.input_entry.bind("<Return>", self.send_message)

        # Mod container frame on the right side
        self.mod_container_frame = tk.Frame(self.root, bd=2, relief=tk.GROOVE)
        self.mod_container_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5, expand=False) 

        self.mod_label = tk.Label(self.mod_container_frame, text="Loaded Mods", font=("Arial", 10, "bold"), bg=self.mod_container_frame.cget('bg'))
        self.mod_label.pack(side=tk.TOP, pady=5)

    def define_text_tags(self):
        """I'm defining custom text tags for the output text widget."""
        self.output_text.tag_config("default", foreground="white", background="black")

        for code, color_name in self.ANSI_COLOR_MAP.items():
            self.output_text.tag_config(f"ansi_{code}", foreground=color_name)
        
        self.output_text.tag_config("system_message", foreground="lightgray", font=("TkDefaultFont", 10, "italic"))
        self.output_text.tag_config("user_input", foreground="lightblue", font=("Courier New", 10))


    def load_profiles(self):
        """
        I'm loading profiles. This is primarily for the ProfileManagerWindow
        and ProfileSelectionDialog now. The main window no longer displays them
        directly on load.
        """
        # The listbox on the main window is gone.
        # The actual loading into a listbox happens in the dedicated windows.
        pass # No action needed on main GUI

    def add_profile(self):
        """
        This method will now only be called from ProfileManagerWindow.
        It handles adding a profile via ProfileManager and then
        requests the ProfileManagerWindow to refresh its display.
        """
        # This will be handled by the ProfileManagerWindow's own add_profile_gui method.
        # This method in MUDClientApp might still be used by external calls, but
        # the GUI interaction is now delegated.
        pass

    def remove_profile(self):
        """
        This method will now only be called from ProfileManagerWindow.
        It handles removing a profile via ProfileManager and then
        requests the ProfileManagerWindow to refresh its display.
        """
        # This will be handled by the ProfileManagerWindow's own remove_profile_gui method.
        pass

    def create_hud(self):
        """I'm creating the Heads-Up Display (HUD) elements."""
        self.hud_frame = tk.Frame(self.root, bg="#333333")
        self.hud_frame.pack(side=tk.TOP, fill=tk.X, expand=False) 

        self.connection_label = tk.Label(self.hud_frame, text="Disconnected", bg="#333333", fg="red", font=("Arial", 10, "bold"))
        self.connection_label.pack(side=tk.LEFT, padx=10, pady=5)

        self.current_profile_label = tk.Label(self.hud_frame, text="Profile: N/A", bg="#333333", fg="white", font=("Arial", 10))
        self.current_profile_label.pack(side=tk.LEFT, padx=10, pady=5)

        self.health_label = tk.Label(self.hud_frame, text="Health: N/A", bg="#333333", fg="white", font=("Arial", 10))
        self.health_label.pack(side=tk.LEFT, padx=10, pady=5)

        self.status_message_label = tk.Label(self.hud_frame, text="", bg="#333333", fg="lightblue", font=("Arial", 10))
        self.status_message_label.pack(side=tk.RIGHT, padx=10, pady=5)

    def _update_client_hud_from_gmcp(self, package_name, data):
        """I'm updating my client's built-in HUD labels based on GMCP data."""
        logging.debug(f"Client HUD Listener: Received GMCP - Package: {package_name}, Data: {data}")
        # Now expecting "Char.Vitals" or "Char.Status" correctly
        if package_name == "Char.Vitals":
            if 'hp' in data and 'maxhp' in data:
                self.update_health(f"{data['hp']}/{data['maxhp']}")
            elif 'hp' in data:
                self.update_health(f"{data['hp']}")
        elif package_name == "Char.Status":
            if 'hp' in data and 'maxhp' in data: # Most MUDs send vitals here too
                self.update_health(f"{data['hp']}/{data['maxhp']}")
            if 'name' in data: # Example: Display character name in status area
                self.status_message_label.config(text=f"Name: {data['name']}")


    def update_connection_status(self, is_connected, profile_name=None):
        """I'm updating the internal connection status and triggering GUI updates."""
        self.connected = is_connected
        self.current_profile = profile_name if is_connected else None
        self.update_gui_state()
        if not is_connected:
            self.update_health("N/A") 
            self.status_message_label.config(text="")

    def update_gui_state(self):
        """I'm updating GUI element states based on my connection status."""
        if self.connected:
            self.profile_frame.pack_forget() # Hide the profile selection frame
            self.servers_menu.entryconfig("Connect to Profile...", state=tk.DISABLED)
            self.servers_menu.entryconfig("Disconnect", state=tk.NORMAL)
            self.servers_menu.entryconfig("Manage Profiles...", state=tk.DISABLED) # Can't manage while connected
            self.input_entry.config(state=tk.NORMAL)
            self.connection_label.config(text="Connected", fg="green")
            self.current_profile_label.config(text=f"Profile: {self.current_profile}")
        else:
            self.profile_frame.pack(fill=tk.X, pady=5, expand=False) # Show the profile selection frame
            self.servers_menu.entryconfig("Connect to Profile...", state=tk.NORMAL)
            self.servers_menu.entryconfig("Disconnect", state=tk.DISABLED)
            self.servers_menu.entryconfig("Manage Profiles...", state=tk.NORMAL)
            self.input_entry.config(state=tk.DISABLED)
            self.connection_label.config(text="Not connected", fg="red")
            self.current_profile_label.config(text="Profile: N/A")
            self.status_message_label.config(text="Offline") 

    def update_health(self, health):
        """I'm updating the health label in the HUD."""
        self.root.after(0, lambda: self.health_label.config(text=f"Health: {health}"))


    def display_message(self, message, tags=None): 
        """
        I'm appending a message to the output text area, handling ANSI codes.
        This function does NOT automatically add newlines. Newlines must be
        part of the 'message' string if desired.
        """
        self.output_text.config(state=tk.NORMAL)
        
        current_fg_tag = "default"

        # I'm splitting the message by ANSI escape codes.
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
                        if code == 0: # Reset code
                            current_fg_tag = "default"
                        elif 30 <= code <= 37 or 90 <= code <= 97: # Standard and bright foregrounds
                            if code in self.ANSI_COLOR_MAP:
                                current_fg_tag = f"ansi_{code}"
                        # I'd extend this with background colors (40-47, 100-107), bold (1), etc. as needed.

        self.output_text.config(state=tk.DISABLED)
        self.output_text.yview(tk.END)

    def register_gmcp_listener(self, callback):
        """
        I'm registering a callback function to receive parsed GMCP data.
        The callback should accept two arguments: package_name (str) and data (dict).
        """
        if callable(callback):
            self.gmcp_listeners.append(callback)
            logging.info(f"GMCP listener registered: {callback.__name__}")
        else:
            logging.warning(f"I attempted to register a non-callable GMCP listener: {callback}")
            
    def load_mods(self):
        """I'm loading Python modules from the 'mods' directory."""
        mods_dir = "mods"
        if not os.path.exists(mods_dir):
            logging.warning(f"My mods directory '{mods_dir}' was not found. I'm creating it.")
            os.makedirs(mods_dir) # I'll create the directory if it doesn't exist.
            return

        # I'm adding the mods directory to the Python path temporarily for importlib.
        sys.path.insert(0, mods_dir) 

        for filename in os.listdir(mods_dir):
            if filename.endswith(".py") and not filename.startswith("__"): # I'm skipping __init__.py and other special files.
                module_name = filename[:-3] # I'm removing the .py extension.
                try:
                    spec = importlib.util.spec_from_file_location(module_name, os.path.join(mods_dir, filename))
                    if spec is None:
                        logging.error(f"I could not get the spec for mod: {filename}")
                        continue
                    
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = mod # I'm adding it to sys.modules to prevent re-import issues.
                    spec.loader.exec_module(mod) # I'm executing the module to define its contents.

                    # I'm checking if the mod has the required setup_mod_gui function.
                    if hasattr(mod, 'setup_mod_gui') and callable(mod.setup_mod_gui):
                        # I'm creating a dedicated frame for this mod's GUI.
                        mod_frame = self.create_mod_frame(module_name)
                        # I'm calling the mod's setup function, passing its frame and client app instance.
                        mod.setup_mod_gui(mod_frame, self) 
                        self.loaded_mods.append(mod) # I'm keeping a reference to the loaded mod module.
                        logging.info(f"My mod '{module_name}' loaded successfully.")
                    else:
                        logging.warning(f"My mod '{module_name}' does not have a callable 'setup_mod_gui' function.")

                except Exception as e:
                    logging.error(f"An error occurred loading my mod '{module_name}': {e}")
                    logging.exception(f"Detailed error for my mod '{module_name}'")
        
        # I'm removing the mods directory from the Python path after loading.
        sys.path.pop(0) 

    def create_mod_frame(self, mod_name):
        """I'm creating a labeled frame for a mod's GUI elements within the mod container."""
        # I'll clean up the mod name for display (e.g., "gmcp_hud_mod" -> "Gmcp Hud Mod").
        display_name = mod_name.replace('_', ' ').title()
        frame = tk.LabelFrame(self.mod_container_frame, text=display_name, padx=5, pady=5)
        # I'm packing frames vertically within the mod_container_frame.
        frame.pack(fill=tk.X, expand=False, padx=5, pady=5, anchor="n")
        return frame

    def open_profile_selection_dialog(self):
        """Opens a dialog to select and connect to a MUD profile."""
        if self.connected:
            messagebox.showwarning("Warning", "I'm already connected. Please disconnect first.")
            return

        # Ensure only one dialog instance is open (optional but good practice)
        if hasattr(self, '_profile_select_dialog') and self._profile_select_dialog.winfo_exists():
            self._profile_select_dialog.focus_set()
            self._profile_select_dialog.lift()
            return

        # Pass self (the MUDClientApp instance) so the dialog can call connect_to_profile_internal
        self._profile_select_dialog = ProfileSelectionDialog(self.root, self.profile_manager, self.connect_to_profile_internal)
    
    def connect_to_profile_internal(self, profile_name):
        """
        Internal method to initiate connection, called by ProfileSelectionDialog.
        """
        if self.connected: # Double-check in case user rapidly clicks
            messagebox.showwarning("Warning", "I'm already connected.")
            return

        profile = self.profile_manager.profiles.get(profile_name)

        if profile:
            self.display_message(f"--- I'm attempting to connect to {profile['host']}:{profile['port']} ---\n", tags=("system_message",))
            self.status_message_label.config(text="Connecting...")
            
            connection_thread = threading.Thread(target=self._initiate_connection, args=(profile['host'], profile['port'], profile_name))
            connection_thread.daemon = True
            connection_thread.start()
        else:
            messagebox.showerror("Error", "Selected profile not found. Please reload profiles.")
            self.load_profiles() # This would trigger the profile manager window to refresh if open

    def _initiate_connection(self, host, port, profile_name):
        """This is my internal method to handle the actual socket connection."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5) # I'm setting a timeout for initial connection.
            self.sock.connect((host, port))
            self.sock.settimeout(None) # I'll remove the timeout after connection (or set to a short timeout for the receive loop).
            
            # I'm resetting the Telnet parser state for a new connection.
            self.telnet_buffer = b""
            self.telnet_parser_state = self.STATE_NORMAL
            self.telnet_sub_buffer = b""

            # I'm using after(0, ...) to ensure GUI updates happen on the main thread.
            self.root.after(0, self.update_connection_status, True, profile_name) # Pass profile name
            self.root.after(0, lambda: self.display_message("--- Connected to MUD ---\n", tags=("system_message", "ansi_32")))

            self.receive_thread = threading.Thread(target=self.receive_messages)
            self.receive_thread.daemon = True
            self.receive_thread.start()

            # I'm using after to slightly delay sending the GMCP packet, giving the MUD a moment.
            self.root.after(500, self.send_initial_gmcp_supports)
            
        except socket.timeout:
            self.root.after(0, lambda: self.display_message("My connection timed out.\n", tags=("system_message", "ansi_31")))
            self.root.after(0, self.update_connection_status, False)
            logging.error(f"My connection timed out to {host}:{port}")
        except socket.error as e:
            self.root.after(0, lambda msg_text=f"My connection error: {e}\n": self.display_message(msg_text, tags=("system_message", "ansi_31")))
            self.root.after(0, self.update_connection_status, False)
            logging.error(f"My socket error connecting to {host}:{port}: {e}")
        except Exception as e:
            self.root.after(0, lambda msg_text=f"An unexpected error occurred during my connection: {e}\n": self.display_message(msg_text, tags=("system_message", "ansi_31")))
            self.root.after(0, self.update_connection_status, False)
            logging.exception("An unexpected error occurred during my connection")

    def disconnect(self):
        """I'm disconnecting from the MUD."""
        if not self.connected or not self.sock:
            logging.info("I attempted to disconnect when not connected.")
            return
        
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            logging.info("My socket closed.")
        except socket.error as e:
            logging.warning(f"An error occurred during my socket shutdown/close: {e}")
        except Exception as e:
            logging.warning(f"An unexpected error occurred during my disconnect: {e}")
        finally:
            self.sock = None
            self.receive_thread = None
            self.root.after(0, self.update_connection_status, False)
            self.root.after(0, lambda: self.display_message("--- Disconnected from MUD ---\n", tags=("system_message", "ansi_31")))

    def receive_messages(self):
        """
        I'm receiving raw byte messages from the MUD server, appending them to a buffer,
        and then processing the buffer using my Telnet parser.
        I'm accumulating processed text into line_buffer for display.
        """
        line_buffer = "" # I'll accumulate partial lines here for display.
        # I'm setting a short timeout for the socket's receive operation to allow periodic flushing.
        self.sock.settimeout(0.1) # 100 milliseconds timeout

        while self.connected:
            try:
                received_bytes = self.sock.recv(4096)
                if not received_bytes:
                    logging.info("The server disconnected gracefully.")
                    self.root.after(0, lambda: self.display_message("--- The server disconnected unexpectedly ---\n", tags=("system_message", "ansi_31")))
                    self.root.after(0, self.disconnect)
                    break
                
                self.telnet_buffer += received_bytes
                
                # I'm iterating through (text_chunk, is_prompt_signal) tuples.
                for text_chunk, is_prompt_signal in self._parse_telnet_stream_for_display_and_gmcp():
                    line_buffer += text_chunk
                    
                    # I'm processing full lines first (containing \n).
                    while "\n" in line_buffer:
                        # I'm finding the first newline, taking everything up to and including it.
                        newline_index = line_buffer.find("\n")
                        line_to_display = line_buffer[:newline_index + 1] # I'm including the newline character.
                        line_buffer = line_buffer[newline_index + 1:] # This is the remaining part.

                        # I'm removing carriage returns often paired with newlines in Telnet.
                        line_to_display = line_to_display.replace("\r", "")
                        
                        # I'm displaying the line. It includes the newline, display_message just inserts it.
                        self.root.after(0, self.display_message, line_to_display) 

                    # This is my crucial heuristic for non-newline-terminated prompts:
                    # If a prompt signal was explicitly received (from GA)
                    # OR if there's no more raw telnet buffer left to process (meaning _parse_telnet_stream...
                    # has processed all currently available bytes) AND
                    # line_buffer has content AND it doesn't end with a newline,
                    # then I'm assuming the current line_buffer is a prompt or final partial line
                    # and should be displayed immediately.
                    if is_prompt_signal or \
                       (not self.telnet_buffer and line_buffer and \
                        not (line_buffer.endswith('\n') or line_buffer.endswith('\r'))):
                        
                        display_text = line_buffer.replace("\r", "") 
                        if display_text: # I'm only displaying if there's actual text to prevent empty lines.
                            self.root.after(0, self.display_message, display_text) 
                        line_buffer = "" # I'm clearing the buffer as it's been displayed.

            except socket.timeout:
                # No data received within the timeout period.
                # If there's anything in line_buffer that hasn't been flushed by a newline,
                # I'm considering it a prompt and displaying it now.
                if line_buffer and not (line_buffer.endswith('\n') or line_buffer.endswith('\r')):
                    display_text = line_buffer.replace("\r", "")
                    if display_text:
                        self.root.after(0, self.display_message, display_text)
                    line_buffer = "" # I'm clearing the buffer after displaying this suspected prompt.
                pass # I'll just continue the loop, waiting for more data.
            except socket.error as e:
                if self.connected: 
                    logging.error(f"My socket error in receive_messages: {e}")
                    self.root.after(0, lambda msg_text=f"--- My network error: {e} ---\n": self.display_message(msg_text, tags=("system_message", "ansi_31")))
                    self.root.after(0, self.disconnect)
                break
            except Exception as e:
                logging.exception(f"An unexpected error occurred in my receive_messages: {e}")
                self.root.after(0, lambda msg_text=f"--- An unexpected error occurred: {e}\n": self.display_message(msg_text, tags=("system_message", "ansi_31")))
                self.root.after(0, self.disconnect)
                break
        
        # After the loop (connection ended), I'll display any remaining text in the buffer.
        if line_buffer:
            line_buffer = line_buffer.replace("\r", "")
            self.root.after(0, self.display_message, line_buffer + "\n")


    def _parse_telnet_stream_for_display_and_gmcp(self):
        """
        I'm processing my `self.telnet_buffer` byte by byte, handling Telnet protocol,
        extracting displayable text, and dispatching GMCP messages.
        I yield tuples: (displayable text segment, is_prompt_signal).
        `is_prompt_signal` is True if the segment was flushed by a GA and does not end with a newline.
        """
        i = 0
        display_buffer = b"" # I'm accumulating bytes that are meant for display.
        
        while i < len(self.telnet_buffer):
            byte = self.telnet_buffer[i:i+1] # This is the current byte being processed.
            
            is_prompt_signal = False # Default for each yielded chunk.

            if self.telnet_parser_state == self.STATE_NORMAL:
                if byte == self.IAC:
                    # If I accumulated displayable text, I'll yield it before processing IAC.
                    if display_buffer:
                        yield display_buffer.decode('utf-8', errors='replace'), False # Not a prompt signal.
                        display_buffer = b""
                    self.telnet_parser_state = self.STATE_IAC
                else:
                    display_buffer += byte # I'm accumulating normal characters.
            
            elif self.telnet_parser_state == self.STATE_IAC:
                command = byte
                i += 1 # I'm advancing to the potential option byte.
                
                if command in (self.WILL, self.DO, self.WONT, self.DONT):
                    if i >= len(self.telnet_buffer): # Not enough bytes for option, I'll wait for more.
                        i -= 1 # I'm rewinding to the IAC command.
                        break 
                    
                    option = self.telnet_buffer[i:i+1]
                    logging.debug(f"TELNET: I received IAC {command!r} option {option!r}")
                    
                    # I'm responding to common Telnet negotiations.
                    if command == self.WILL and option == self.GMCP:
                        logging.info("TELNET: MUD WILL GMCP. I'm responding with DO GMCP.")
                        self.sock.sendall(self.IAC + self.DO + self.GMCP)
                    elif command == self.DO and option == self.SUPPRESS_GO_AHEAD:
                        logging.info("TELNET: MUD DO SUPPRESS_GO_AHEAD. I'm responding with WILL SUPPRESS_GO_AHEAD.")
                        self.sock.sendall(self.IAC + self.WILL + self.SUPPRESS_GO_AHEAD)
                    elif command == self.DO and option == self.ECHO:
                        logging.info("TELNET: MUD DO ECHO. I'm responding with WILL ECHO.")
                        self.sock.sendall(self.IAC + self.WILL + self.ECHO)
                    
                    self.telnet_parser_state = self.STATE_NORMAL # Command + Option consumed.
                
                elif command == self.SB:
                    self.telnet_parser_state = self.STATE_SB_READ_OPTION # I'm moving to the state to read the option byte.
                    self.telnet_sub_buffer = b"" # I'm clearing the subnegotiation buffer.
                
                elif command == self.IAC: # Escaped IAC (IAC IAC means a literal 0xFF byte).
                    display_buffer += self.IAC # I'm adding the actual IAC byte to display.
                    self.telnet_parser_state = self.STATE_NORMAL
                
                elif command == self.SE: # Unexpected IAC SE (should only follow SB).
                    logging.warning("TELNET: I received an unexpected IAC SE in STATE_IAC. Resetting to NORMAL.")
                    self.telnet_parser_state = self.STATE_NORMAL
                
                elif command == self.NOP or command == self.GA: # Other single-byte IAC commands (e.g., NOP, GA).
                    logging.debug(f"TELNET: I consumed a simple IAC command: {command!r}. Resetting to NORMAL.")
                    
                    if display_buffer: 
                        decoded_text = display_buffer.decode('utf-8', errors='replace')
                        # IMPORTANT: I'm signaling as a prompt ONLY if it's a GA AND the text does NOT end with a line break.
                        if command == self.GA and not (decoded_text.endswith('\n') or decoded_text.endswith('\r')):
                             is_prompt_signal = True
                        yield decoded_text, is_prompt_signal 
                        display_buffer = b"" 
                    elif command == self.GA: # If GA comes without any preceding display_buffer.
                        # This means an explicit prompt flush signal, even if no text preceded it.
                        yield "", True # I'm signaling a prompt flush even if no text.
                    
                    self.telnet_parser_state = self.STATE_NORMAL # I'm consuming the command.
            
            # --- My Subnegotiation Handling ---
            elif self.telnet_parser_state == self.STATE_SB_READ_OPTION:
                option_byte = byte
                logging.debug(f"TELNET: I'm in STATE_SB_READ_OPTION. My current byte (potential option): {option_byte!r}")
                # I'm checking if the option is the standard GMCP byte OR one of my suspected GMCP data bytes.
                if option_byte == self.GMCP or option_byte in self.GMCP_DATA_OPTIONS:
                    self.telnet_parser_state = self.STATE_GMCP_SUB
                    # THIS IS THE CRITICAL CHANGE: I'm initializing the sub_buffer WITH the option byte.
                    self.telnet_sub_buffer = option_byte 
                    logging.debug(f"TELNET: I recognized a GMCP option (negotiation or data). Initializing sub buffer with: {option_byte!r}")
                else:
                    logging.debug(f"TELNET: My unknown SB option: {option_byte!r}. I'm transitioning to consume its payload.")
                    self.telnet_parser_state = self.STATE_UNKNOWN_SB
                    self.telnet_sub_buffer = b"" # Still clear for unknown, as we don't care about its content.
            
            elif self.telnet_parser_state == self.STATE_GMCP_SUB:
                # I'm inside GMCP subnegotiation.
                if byte == self.IAC:
                    # I'm checking if the next byte is SE (end of subnegotiation).
                    if i + 1 < len(self.telnet_buffer) and self.telnet_buffer[i+1:i+2] == self.SE:
                        # This is IAC SE, the end of GMCP subnegotiation.
                        gmcp_raw_payload = self.telnet_sub_buffer 
                        logging.debug(f"TELNET: GMCP Subnegotiation ended. My raw payload accumulated: {gmcp_raw_payload!r}")
                        try:
                            # I'm explicitly decoding from latin-1 because some MUDs might send raw bytes.
                            gmcp_string = gmcp_raw_payload.decode('latin-1', errors='replace') 
                            logging.debug(f"GMCP Dispatcher: My decoded GMCP string: '{gmcp_string}'")
                            self.root.after(0, self._dispatch_gmcp_data, gmcp_string) 
                        except Exception as e:
                            logging.error(f"An error occurred decoding/dispatching my GMCP payload: {e}. Raw: {gmcp_raw_payload!r}")
                            logging.exception("My GMCP decode/dispatch details")
                        
                        self.telnet_sub_buffer = b"" 
                        self.telnet_parser_state = self.STATE_NORMAL 
                        i += 1 # I'm consuming the SE byte as well.
                    else: 
                        # This is a literal IAC byte within GMCP payload, it should be escaped (IAC IAC).
                        # I should *not* consume the next byte here, just add the current IAC.
                        # This handles escaped IACs inside GMCP data.
                        self.telnet_sub_buffer += byte
                        logging.debug(f"TELNET: I found IAC inside GMCP sub. Appending to payload. My current payload: {self.telnet_sub_buffer!r}")
                else: 
                    # I'm accumulating actual GMCP payload bytes.
                    self.telnet_sub_buffer += byte
                    logging.debug(f"TELNET: Appending to GMCP payload. My current byte: {byte!r}. My current payload: {self.telnet_sub_buffer!r}")

            elif self.telnet_parser_state == self.STATE_UNKNOWN_SB:
                # I'm consuming bytes until IAC SE for unknown subnegotiations.
                if byte == self.IAC:
                    if i + 1 < len(self.telnet_buffer) and self.telnet_buffer[i+1:i+2] == self.SE:
                        logging.debug("TELNET: My unknown subnegotiation ended (IAC SE detected).")
                        self.telnet_sub_buffer = b"" 
                        self.telnet_parser_state = self.STATE_NORMAL 
                        i += 1 # I'm consuming the SE byte.
                    else: 
                        # This is a literal IAC byte within an unknown subnegotiation, I'll consume it.
                        # For unknown SB, I generally just discard the payload, so no action on self.telnet_sub_buffer.
                        pass 
                else: 
                    # I'm accumulating bytes of the unknown subnegotiation (or just discarding if not needed).
                    # For now, I'm just moving the pointer 'i', effectively discarding.
                    pass 

            i += 1 

        # This is my crucial part for handling partial lines/initial prompts that don't end in newline:
        # If there's any remaining display_buffer after parsing all currently available bytes,
        # I'll yield it. This forces receive_messages to process it.
        if display_buffer:
            yield display_buffer.decode('utf-8', errors='replace'), False # Not a prompt signal itself.

        self.telnet_buffer = self.telnet_buffer[i:]


    def _dispatch_gmcp_data(self, gmcp_string): 
        """
        I'm parsing raw messages for GMCP data and dispatching the parsed
        package name and data (dict) to all my registered GMCP listeners.
        """
        # I'm NO LONGER CHECKING FOR "GMCP " prefix, as it's already stripped.
        logging.debug(f"GMCP Dispatcher: I'm processing extracted GMCP. String: '{gmcp_string.strip()}'")
        try:
            payload = gmcp_string.strip() 
            first_space_idx = payload.find(' ')
            
            package_name = payload
            json_data = {}

            if first_space_idx != -1:
                package_name = payload[:first_space_idx]
                json_string = payload[first_space_idx:].strip()
                if json_string: 
                    try:
                        json_data = json.loads(json_string)
                    except json.JSONDecodeError as e:
                        logging.error(f"My GMCP JSON decode error for package '{package_name}': {e}. JSON string: '{json_string}'")
                        json_data = {} 
            
            for listener in self.gmcp_listeners:
                try:
                    listener(package_name, json_data)
                except Exception as e:
                    logging.error(f"An error occurred calling my GMCP listener '{listener.__name__}': {e}")
                    logging.exception("My GMCP listener callback details")

        except Exception as e:
            logging.error(f"I failed to parse my GMCP message: {e}. Message: {gmcp_string!r}") 
            logging.exception("My GMCP parsing details")

    def send_gmcp(self, package_name, data=None):
        """
        I'm sending a GMCP packet to the MUD.
        package_name: e.g., "Client.Core.Supports"
        data: dictionary to be JSON encoded, or None if no data.
        """
        if not self.connected or not self.sock:
            logging.warning("I attempted to send GMCP but I'm not connected.")
            return

        payload_data = ""
        if data is not None:
            try:
                # I'm ensuring compact JSON output for Telnet transmission.
                payload_data = json.dumps(data, separators=(',', ':'))
            except TypeError as e:
                logging.error(f"An error occurred JSON encoding my GMCP data for {package_name}: {e}")
                return

        # GMCP packet format: IAC SB GMCP <package.name> <json_data> IAC SE
        # \xff\xfa\xc9<package.name> <json_data>\xff\xf0
        
        # I'm building the full GMCP payload.
        # Note: Package name and JSON data are space-separated within the GMCP payload.
        gmcp_content = f"{package_name} {payload_data}".encode('utf-8')

        # I'm encapsulating it with Telnet IAC SB GMCP and IAC SE.
        # I'm using self.GMCP (b'\xc9') for sending, as the MUD negotiates with it.
        full_packet = self.IAC + self.SB + self.GMCP + gmcp_content + self.IAC + self.SE

        try:
            self.sock.sendall(full_packet)
            logging.debug(f"I sent GMCP: {package_name} {payload_data}")
        except socket.error as e:
            logging.error(f"A socket error occurred sending my GMCP: {e}")
            self.disconnect()
        except Exception as e:
            logging.exception(f"An unexpected error occurred sending my GMCP {package_name}: {e}")

    def send_initial_gmcp_supports(self):
        """
        I'm sending the Client.Core.Supports GMCP packet to the MUD,
        declaring supported GMCP modules and versions.
        """
        # This is a standard set. I might need to adjust this based on my specific MUD's docs.
        supported_modules = {
            "Client.Core": ["1", "2"], # I'm indicating support for Client.Core versions 1 and 2.
            "Room.Info": ["1"],        # I'm including Room.Info.
            "Char.Buffs": ["1"],       # I'm including Char.Buffs.
            "Char.Status": ["1"],      # I'm keeping Char.Status.
            "Char.Cooldowns": ["1"],   # I'm including Char.Cooldowns.
            "Char.Inventory": ["1"],   # I'm including Char.Inventory.
            "Char.Vitals": ["1"],      # I'm keeping Char.Vitals (most MUDs send this).
            # I might need to add other modules my MUD might support (e.g., "Comm.Channel", "IRE.Composer").
        }
        self.send_gmcp("Client.Core.Supports", supported_modules)
        logging.info("I sent the Client.Core.Supports GMCP packet with specific modules.")

    def send_message(self, event=None):
        """I'm sending the user's input to the MUD server."""
        if not self.connected or not self.sock:
            self.display_message("I'm not connected to the MUD.\n", tags=("system_message", "ansi_31"))
            return

        raw_message = self.input_entry.get() 
        self.input_entry.delete(0, tk.END) 

        message_to_send = self.alias_manager.process_input(raw_message)

        self.display_message(f"> {raw_message}\n", tags=("user_input",))

        try:
            self.sock.sendall((message_to_send + "\n").encode('utf-8')) 
            logging.debug(f"I sent: {message_to_send!r} (originally: {raw_message!r})") 
        except socket.error as e:
            self.display_message(f"An error occurred sending my message: {e}\n", tags=("system_message", "ansi_31"))
            logging.error(f"My socket error sending message: {e}")
            self.disconnect() 
        except Exception as e:
            self.display_message(f"An unexpected error occurred while I was sending: {e}\n", tags=("system_message", "ansi_31"))
            logging.exception("An unexpected error occurred while I was sending my message")

    def open_alias_manager_window(self):
        """Opens the Alias Manager window, or brings it to the front if already open."""
        if self.alias_window is None or not self.alias_window.winfo_exists():
            self.alias_window = AliasManagerWindow(self.root, self.alias_manager)
        else:
            self.alias_window.focus_set()
            self.alias_window.lift()

    def open_profile_manager_window(self):
        """Opens the Profile Manager window, or brings it to the front if already open."""
        # Ensure only one instance is open
        if self.profile_manager_window is None or not self.profile_manager_window.winfo_exists():
            self.profile_manager_window = ProfileManagerWindow(self.root, self.profile_manager)
        else:
            self.profile_manager_window.focus_set()
            self.profile_manager_window.lift()


    def on_closing(self):
        """I'm handling proper disconnection when the window is closed."""
        if self.connected:
            if messagebox.askokcancel("Quit", "I'm connected. Do I disconnect and Quit?"):
                self.disconnect()
                self.root.destroy()
        else:
            self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = MUDClientApp(root)
    root.mainloop()