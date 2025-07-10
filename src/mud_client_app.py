import tkinter as tk
from tkinter import messagebox, simpledialog, scrolledtext, ttk
import socket
import threading
import re
import json
import logging
import os
import importlib.util
import sys
import time
import queue

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None
    logging.warning("pyttsx3 not found. Text-to-Speech features will be disabled.")

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

from .alias_manager import AliasManager
from .alias_manager_window import AliasManagerWindow
from .profile_selection_dialog import ProfileSelectionDialog
from .profile_manager_window import ProfileManagerWindow
from .profile_manager import ProfileManager

class ConfigManager:
    def __init__(self, config_file="config.json"):
        self.config_file = config_file
        self.config = self._load_config()

    def _load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logging.warning(f"Error decoding config file {self.config_file}. Using default config.")
            except Exception as e:
                logging.warning(f"Error loading config file {self.config_file}: {e}. Using default config.")
        return {}

    def save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving config file {self.config_file}: {e}")

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save_config()

class MUDClientApp:
    ANSI_COLOR_MAP = {
        30: 'black_fg', 31: 'red_fg', 32: 'green_fg', 33: 'yellow_fg',
        34: 'blue_fg', 35: 'magenta_fg', 36: 'cyan_fg', 37: 'white_fg',
        90: 'gray_fg', 91: 'bright_red_fg', 92: 'bright_green_fg', 93: 'bright_yellow_fg',
        94: 'bright_blue_fg', 95: 'bright_magenta_fg', 96: 'bright_cyan_fg', 97: 'bright_white_fg',

        40: 'black_bg', 41: 'red_bg', 42: 'green_bg', 43: 'yellow_bg',
        44: 'blue_bg', 45: 'magenta_bg', 46: 'cyan_bg', 47: 'white_bg',
        100: 'gray_bg', 101: 'bright_red_bg', 102: 'bright_green_bg', 103: 'bright_yellow_bg',
        104: 'bright_blue_bg', 105: 'bright_magenta_bg', 106: 'bright_cyan_bg', 107: 'bright_white_bg',
    }

    ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[([0-9;]*)m')

    IAC = b'\xff'
    DONT = b'\xfe'
    DO = b'\xfd'
    WONT = b'\xfc'
    WILL = b'\xfb'
    SB = b'\xfa'
    SE = b'\xf0'
    NOP = b'\xf9'
    GA = b'\xf9'

    ECHO = b'\x01'
    SUPPRESS_GO_AHEAD = b'\x03'
    NAWS = b'\x1f'
    GMCP = b'\xc9'
    GMCP_DATA_OPTIONS = (b'R', b'C', b'E')

    STATE_NORMAL = 0
    STATE_IAC = 1
    STATE_SB_READ_OPTION = 2
    STATE_GMCP_SUB = 3
    STATE_UNKNOWN_SB = 4

    def __init__(self, root):
        self.root = root
        self.root.title("PyMUD")

        self.profile_manager = ProfileManager()
        self.alias_manager = AliasManager(alias_file="aliases.json")

        self.alias_window = None
        self.profile_manager_window = None
        self._profile_select_dialog = None

        self.sock = None
        self.receive_thread = None
        self.connected = False
        self.current_profile = None

        self.loaded_mods = []
        self.gmcp_listeners = []

        self.telnet_buffer = b""
        self.telnet_parser_state = self.STATE_NORMAL
        self.telnet_sub_buffer = b""

        self.config_manager = ConfigManager()

        self.tts_engine = None
        self.tts_queue = queue.Queue()
        self.tts_thread = None

        self.tts_enabled = tk.BooleanVar(value=self.config_manager.get('tts_enabled', True))
        self.tts_read_mud_output = tk.BooleanVar(value=self.config_manager.get('tts_read_mud_output', True))
        self.tts_read_user_input = tk.BooleanVar(value=self.config_manager.get('tts_read_user_input', False))
        self.tts_read_system_messages = tk.BooleanVar(value=self.config_manager.get('tts_read_system_messages', False))

        if pyttsx3:
            try:
                self.tts_engine = pyttsx3.init()
                logging.info(f"TTS engine initialized successfully. TTS Enabled: {self.tts_enabled.get()}")
                
                self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
                self.tts_thread.start()
                logging.info("TTS worker thread started.")

            except RuntimeError as e:
                logging.error(f"Failed to initialize TTS engine: {e}. Speech features will be unavailable.")
                messagebox.showwarning("TTS Error", f"Text-to-Speech engine could not be initialized: {e}\nSpeech features will be disabled.")
        else:
            logging.warning("pyttsx3 not installed. TTS features are disabled.")
        
        self.current_font_size = tk.IntVar(value=self.config_manager.get('font_size', 10))

        self.tts_enabled.trace_add("write", lambda *args: self.config_manager.set('tts_enabled', self.tts_enabled.get()))
        self.tts_read_mud_output.trace_add("write", lambda *args: self.config_manager.set('tts_read_mud_output', self.tts_read_mud_output.get()))
        self.tts_read_user_input.trace_add("write", lambda *args: self.config_manager.set('tts_read_user_input', self.tts_read_user_input.get()))
        self.tts_read_system_messages.trace_add("write", lambda *args: self.config_manager.set('tts_read_system_messages', self.tts_read_system_messages.get()))
        self.current_font_size.trace_add("write", lambda *args: self.config_manager.set('font_size', self.current_font_size.get()))

        self.setup_gui()
        self.create_hud()
        self._apply_text_tags()
        self.load_mods()

        self.register_gmcp_listener(self._update_client_hud_from_gmcp)

        self.update_gui_state()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.load_profiles()

    def setup_gui(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        self.servers_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Servers", menu=self.servers_menu)
        self.servers_menu.add_command(label="Connect to Profile...", command=self.open_profile_selection_dialog)
        self.servers_menu.add_command(label="Disconnect", command=self.disconnect)
        self.servers_menu.add_separator()
        self.servers_menu.add_command(label="Manage Profiles...", command=self.open_profile_manager_window)

        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Alias Manager", command=self.open_alias_manager_window)

        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)

        tts_menu = tk.Menu(settings_menu, tearoff=0)
        settings_menu.add_cascade(label="Text-to-Speech", menu=tts_menu)
        tts_menu.add_checkbutton(label="Enable Text-to-Speech", variable=self.tts_enabled)
        tts_menu.add_checkbutton(label="Read MUD Output", variable=self.tts_read_mud_output)
        tts_menu.add_checkbutton(label="Read My Input", variable=self.tts_read_user_input)
        tts_menu.add_checkbutton(label="Read System Messages", variable=self.tts_read_system_messages)

        appearance_menu = tk.Menu(settings_menu, tearoff=0)
        settings_menu.add_cascade(label="Appearance", menu=appearance_menu)
        appearance_menu.add_command(label="Set Font Size...", command=self.set_font_size)

        main_content_frame = tk.Frame(self.root)
        main_content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.profile_frame = tk.LabelFrame(main_content_frame, text="Profile Selection", padx=10, pady=10)

        text_frame = tk.Frame(main_content_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.output_text = scrolledtext.ScrolledText(text_frame, state=tk.DISABLED, wrap=tk.WORD, bg="black", fg="white", font=("Courier New", self.current_font_size.get()))
        self.output_text.pack(fill=tk.BOTH, expand=True)

        self.input_entry = tk.Entry(main_content_frame, font=("Courier New", self.current_font_size.get()))
        self.input_entry.pack(fill=tk.X, expand=False, pady=(0,5))
        self.input_entry.bind("<Return>", self.send_message)

        self.mod_container_frame = tk.Frame(self.root, bd=2, relief=tk.GROOVE)
        self.mod_container_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5, expand=False)

        self.mod_label = tk.Label(self.mod_container_frame, text="Loaded Mods", font=("Arial", 10, "bold"), bg=self.mod_container_frame.cget('bg'))
        self.mod_label.pack(side=tk.TOP, pady=5)

    def _apply_text_tags(self):
        font_size = self.current_font_size.get()
        base_font_tuple = ("Courier New", font_size)

        self.output_text.tag_config("default_fg", foreground="white")
        self.output_text.tag_config("default_bg", background="black")

        self.output_text.tag_config("default", foreground="white", background="black", font=base_font_tuple)

        self.output_text.tag_config("bold_font", font=(base_font_tuple[0], base_font_tuple[1], "bold"))
        self.output_text.tag_config("underline_style", underline=1)

        self.output_text.tag_config("black_fg", foreground="black")
        self.output_text.tag_config("red_fg", foreground="red")
        self.output_text.tag_config("green_fg", foreground="green")
        self.output_text.tag_config("yellow_fg", foreground="yellow")
        self.output_text.tag_config("blue_fg", foreground="blue")
        self.output_text.tag_config("magenta_fg", foreground="magenta")
        self.output_text.tag_config("cyan_fg", foreground="cyan")
        self.output_text.tag_config("white_fg", foreground="white")
        self.output_text.tag_config("gray_fg", foreground="gray")
        self.output_text.tag_config("bright_red_fg", foreground="firebrick")
        self.output_text.tag_config("bright_green_fg", foreground="forestgreen")
        self.output_text.tag_config("bright_yellow_fg", foreground="gold")
        self.output_text.tag_config("bright_blue_fg", foreground="dodgerblue")
        self.output_text.tag_config("bright_magenta_fg", foreground="darkviolet")
        self.output_text.tag_config("bright_cyan_fg", foreground="lightskyblue")
        self.output_text.tag_config("bright_white_fg", foreground="white")

        self.output_text.tag_config("black_bg", background="black")
        self.output_text.tag_config("red_bg", background="red")
        self.output_text.tag_config("green_bg", background="green")
        self.output_text.tag_config("yellow_bg", background="yellow")
        self.output_text.tag_config("blue_bg", background="blue")
        self.output_text.tag_config("magenta_bg", background="magenta")
        self.output_text.tag_config("cyan_bg", background="cyan")
        self.output_text.tag_config("white_bg", background="white")
        self.output_text.tag_config("gray_bg", background="gray")
        self.output_text.tag_config("bright_red_bg", background="firebrick")
        self.output_text.tag_config("bright_green_bg", background="forestgreen")
        self.output_text.tag_config("bright_yellow_bg", background="gold")
        self.output_text.tag_config("bright_blue_bg", background="dodgerblue")
        self.output_text.tag_config("bright_magenta_bg", background="darkviolet")
        self.output_text.tag_config("bright_cyan_bg", background="lightskyblue")
        self.output_text.tag_config("bright_white_bg", background="white")

        self.output_text.tag_config("system_message", foreground="lightgray", font=("TkDefaultFont", font_size, "italic"))
        self.output_text.tag_config("user_input", foreground="lightblue", font=base_font_tuple)

        self.current_fg_tag = "default_fg"
        self.current_bg_tag = "default_bg"
        self.is_bold = False
        self.is_underline = False

    def set_font_size(self):
        new_size = simpledialog.askinteger("Set Font Size", "Enter new font size (e.g., 12):",
                                           initialvalue=self.current_font_size.get(),
                                           minvalue=6, maxvalue=24, parent=self.root)
        if new_size is not None and new_size != self.current_font_size.get():
            self.current_font_size.set(new_size)
            self.output_text.config(font=("Courier New", self.current_font_size.get()))
            self.input_entry.config(font=("Courier New", self.current_font_size.get()))
            self._apply_text_tags()
            self.speak_system_message(f"Font size set to {new_size}.")

    def load_profiles(self):
        pass

    def add_profile(self):
        pass

    def remove_profile(self):
        pass

    def create_hud(self):
        self.hud_frame = tk.Frame(self.root, bg="#333333")
        self.hud_frame.pack(side=tk.TOP, fill=tk.X, expand=False)

        info_frame = tk.Frame(self.hud_frame, bg="#333333")
        info_frame.pack(side=tk.LEFT, padx=10, pady=5)

        self.connection_label = tk.Label(info_frame, text="Disconnected", bg="#333333", fg="red", font=("Arial", 10, "bold"))
        self.connection_label.pack(side=tk.TOP, anchor="w")

        self.current_profile_label = tk.Label(info_frame, text="Profile: N/A", bg="#333333", fg="white", font=("Arial", 10))
        self.current_profile_label.pack(side=tk.TOP, anchor="w")

        vitals_frame = tk.Frame(self.hud_frame, bg="#333333")
        vitals_frame.pack(side=tk.LEFT, padx=10, pady=5)

        self.hp_label = tk.Label(vitals_frame, text="HP: N/A", bg="#333333", fg="white", font=("Arial", 10))
        self.hp_label.pack(side=tk.TOP, anchor="w")
        self.hp_bar_canvas = tk.Canvas(vitals_frame, width=150, height=12, bg="darkgrey", highlightthickness=0)
        self.hp_bar_canvas.pack(side=tk.TOP, pady=2, anchor="w")
        self.hp_bar_id = self.hp_bar_canvas.create_rectangle(0, 0, 0, 12, fill="green", outline="")

        self.sp_label = tk.Label(vitals_frame, text="SP: N/A", bg="#333333", fg="white", font=("Arial", 10))
        self.sp_label.pack(side=tk.TOP, anchor="w", pady=(5,0))
        self.sp_bar_canvas = tk.Canvas(vitals_frame, width=150, height=12, bg="darkgrey", highlightthickness=0)
        self.sp_bar_canvas.pack(side=tk.TOP, pady=2, anchor="w")
        self.sp_bar_id = self.sp_bar_canvas.create_rectangle(0, 0, 0, 12, fill="blue", outline="")

        equipment_frame = tk.Frame(self.hud_frame, bg="#333333")
        equipment_frame.pack(side=tk.LEFT, padx=10, pady=5)

        self.weapon_label = tk.Label(equipment_frame, text="Weapon: N/A", bg="#333333", fg="white", font=("Arial", 10))
        self.weapon_label.pack(side=tk.TOP, anchor="w")

        self.ammo_label = tk.Label(equipment_frame, text="Ammo: N/A", bg="#333333", fg="white", font=("Arial", 10))
        self.ammo_label.pack(side=tk.TOP, anchor="w", pady=(5,0))
        self.ammo_bar_canvas = tk.Canvas(equipment_frame, width=150, height=12, bg="darkgrey", highlightthickness=0)
        self.ammo_bar_canvas.pack(side=tk.TOP, pady=2, anchor="w")
        self.ammo_bar_id = self.ammo_bar_canvas.create_rectangle(0, 0, 0, 12, fill="orange", outline="")

        status_frame = tk.Frame(self.hud_frame, bg="#333333")
        status_frame.pack(side=tk.RIGHT, padx=10, pady=5, fill=tk.Y)

        self.status_message_label = tk.Label(status_frame, text="", bg="#333333", fg="lightblue", font=("Arial", 10))
        self.status_message_label.pack(side=tk.BOTTOM, anchor="e")

    def _update_client_hud_from_gmcp(self, package_name, data):
        # logging.debug(f"Client HUD Listener: Received GMCP - Package: {package_name}, Data: {data}") # Retaining for debugging GMCP if needed

        if package_name == "Char.Vitals" or package_name == "Char.Status":
            if 'hp' in data and 'maxhp' in data:
                self.update_hp(data['hp'], data['maxhp'])
            elif 'hp' in data:
                self.update_hp(data['hp'], None)

            if 'sp' in data and 'maxsp' in data:
                self.update_sp(data['sp'], data['maxsp'])
            elif 'sp' in data:
                self.update_sp(data['sp'], None)

            current_ammo = None
            max_ammo = None
            ammo_type = "N/A"

            if 'ammo_count' in data:
                current_ammo = data['ammo_count']
            if 'maxammo' in data:
                max_ammo = data['maxammo']
            if 'ammo_type' in data:
                ammo_type = data['ammo_type']
            elif 'ammo' in data:
                current_ammo = data['ammo']

            if current_ammo is not None:
                self.update_ammo(current_ammo, ammo_type, max_ammo)

            if 'name' in data:
                self.status_message_label.config(text=f"Name: {data['name']}")

        elif package_name == "Char.Items.Equip":
            equipped_weapon_name = "Nothing"
            if 'wield' in data and data['wield'] and 'name' in data['wield']:
                equipped_weapon_name = data['wield']['name']
            elif 'mainhand' in data and data['mainhand'] and 'name' in data['mainhand']:
                equipped_weapon_name = data['mainhand']['name']

            self.update_weapon(equipped_weapon_name)

    def update_connection_status(self, is_connected, profile_name=None):
        self.connected = is_connected
        self.current_profile = profile_name if is_connected else None
        self.update_gui_state()
        if not is_connected:
            self.update_hp("N/A", "N/A")
            self.update_sp("N/A", "N/A")
            self.update_ammo("N/A", "N/A")
            self.update_weapon("N/A")
            self.status_message_label.config(text="")
            self.speak_system_message("Disconnected.")
        else:
            self.speak_system_message(f"Connected to {profile_name}.")

    def update_gui_state(self):
        if self.connected:
            self.profile_frame.pack_forget()
            self.servers_menu.entryconfig("Connect to Profile...", state=tk.DISABLED)
            self.servers_menu.entryconfig("Disconnect", state=tk.NORMAL)
            self.servers_menu.entryconfig("Manage Profiles...", state=tk.DISABLED)
            self.input_entry.config(state=tk.NORMAL)
            self.connection_label.config(text="Connected", fg="green")
            self.current_profile_label.config(text=f"Profile: {self.current_profile}")
        else:
            self.profile_frame.pack(fill=tk.X, pady=5, expand=False)
            self.servers_menu.entryconfig("Connect to Profile...", state=tk.NORMAL)
            self.servers_menu.entryconfig("Disconnect", state=tk.DISABLED)
            self.servers_menu.entryconfig("Manage Profiles...", state=tk.NORMAL)
            self.input_entry.config(state=tk.DISABLED)
            self.connection_label.config(text="Not connected", fg="red")
            self.current_profile_label.config(text="Profile: N/A")
            self.status_message_label.config(text="Offline")

    def update_hp(self, current_hp, max_hp=None):
        self.root.after(0, lambda: self._update_bar(
            self.hp_label, self.hp_bar_canvas, self.hp_bar_id,
            "HP", current_hp, max_hp, "green", "red"
        ))

    def update_sp(self, current_sp, max_sp=None):
        self.root.after(0, lambda: self._update_bar(
            self.sp_label, self.sp_bar_canvas, self.sp_bar_id,
            "SP", current_sp, max_sp, "blue", "darkblue"
        ))

    def _update_bar(self, label_widget, canvas_widget, bar_item_id, stat_name, current_value, max_value, high_color, low_color):
        if current_value == "N/A":
            label_widget.config(text=f"{stat_name}: N/A")
            canvas_widget.coords(bar_item_id, 0, 0, 0, 0)
            canvas_widget.config(bg="darkgrey")
            return

        current_value_int = int(current_value) if isinstance(current_value, (int, str)) else 0
        max_value_int = int(max_value) if isinstance(max_value, (int, str)) and max_value is not None else current_value_int

        if stat_name == "Ammo":
            label_text = f"{stat_name}: {current_value}"
            if max_value is not None and max_value != "N/A":
                label_text += f"/{max_value}"
            label_widget.config(text=label_text)
        else:
            label_widget.config(text=f"{stat_name}: {current_value_int}/{max_value_int}")

        bar_width = canvas_widget.winfo_width()
        if bar_width <= 1:
             bar_width = 150

        if max_value_int > 0:
            fill_width = (current_value_int / max_value_int) * bar_width

            percentage = (current_value_int / max_value_int) * 100
            fill_color = high_color

            if stat_name == "HP":
                if percentage <= 20:
                    fill_color = low_color
                elif percentage <= 50:
                    fill_color = "orange"
            elif stat_name == "Ammo":
                 if percentage <= 20:
                    fill_color = "red"
                 elif percentage <= 50:
                    fill_color = "darkorange"
                 else:
                    fill_color = "gold"
        else:
            fill_width = 0
            fill_color = low_color if current_value_int > 0 else "grey"

        canvas_widget.coords(bar_item_id, 0, 0, fill_width, canvas_widget.winfo_height())
        canvas_widget.itemconfig(bar_item_id, fill=fill_color)
        canvas_widget.config(bg="black")

    def update_ammo(self, count, ammo_type="N/A", max_ammo=None):
        display_max_ammo = f"{max_ammo} {ammo_type}" if max_ammo is not None else ammo_type

        self.root.after(0, lambda: self._update_bar(
            self.ammo_label, self.ammo_bar_canvas, self.ammo_bar_id,
            "Ammo", count, display_max_ammo, "gold", "red"
        ))

    def update_weapon(self, weapon_name="N/A"):
        self.root.after(0, lambda: self.weapon_label.config(text=f"Weapon: {weapon_name}"))

    def display_message(self, message, tags=None):
        self.output_text.config(state=tk.NORMAL)

        clean_text_for_tts = []

        parts = self.ANSI_ESCAPE_PATTERN.split(message)

        for i in range(len(parts)):
            if i % 2 == 0:
                text_to_display = parts[i]
                if text_to_display:
                    clean_text_for_tts.append(text_to_display)
                    final_tags = [self.current_fg_tag, self.current_bg_tag]
                    if self.is_bold:
                        final_tags.append("bold_font")
                    if self.is_underline:
                        final_tags.append("underline_style")

                    if tags:
                        final_tags.extend(tags)

                    self.output_text.insert(tk.END, text_to_display, tuple(final_tags))
            else:
                codes_str = parts[i]
                if codes_str:
                    codes = [int(c) for c in codes_str.split(';') if c]

                    for code in codes:
                        if code == 0:
                            self.current_fg_tag = "default_fg"
                            self.current_bg_tag = "default_bg"
                            self.is_bold = False
                            self.is_underline = False
                        elif code == 1:
                            self.is_bold = True
                        elif code == 4:
                            self.is_underline = True
                        elif code == 22:
                            self.is_bold = False
                        elif code == 24:
                            self.is_underline = False
                        elif 30 <= code <= 37 or 90 <= code <= 97:
                            self.current_fg_tag = self.ANSI_COLOR_MAP.get(code, "default_fg")
                        elif code == 39:
                            self.current_fg_tag = "default_fg"
                        elif 40 <= code <= 47 or 100 <= code <= 107:
                            self.current_bg_tag = self.ANSI_COLOR_MAP.get(code, "default_bg")
                        elif code == 49:
                            self.current_bg_tag = "default_bg"

        self.output_text.config(state=tk.DISABLED)
        self.output_text.yview(tk.END)

        if self.tts_engine and self.tts_enabled.get() and self.tts_read_mud_output.get():
            text_to_speak = "".join(clean_text_for_tts).strip()
            text_to_speak = text_to_speak.replace('\n', ' ').replace('\r', ' ').strip()
            if text_to_speak:
                logging.debug(f"Queuing MUD output for TTS: '{text_to_speak[:50]}...'")
                self.tts_queue.put(text_to_speak)

    def speak_system_message(self, message):
        if self.tts_engine and self.tts_enabled.get() and self.tts_read_system_messages.get():
            logging.debug(f"Queuing system message for TTS: '{message}'")
            self.tts_queue.put(message)

    def _tts_worker(self):
        logging.info("TTS worker thread has started.")
        while True:
            text_to_speak = self.tts_queue.get()
            
            if text_to_speak is None:
                break
            
            if self.tts_engine and self.tts_enabled.get():
                logging.debug(f"TTS worker processing text. TTS Enabled: {self.tts_enabled.get()}")
                try:
                    cleaned_text = text_to_speak.replace('\n', ' ').replace('\r', ' ').strip()
                    if cleaned_text:
                        self.tts_engine.say(cleaned_text)
                        self.tts_engine.runAndWait()
                except Exception as e:
                    logging.error(f"Error in TTS worker thread speaking: '{cleaned_text[:100]}...': {e}", exc_info=True)
            else:
                logging.debug(f"TTS worker NOT speaking. Engine: {bool(self.tts_engine)}, TTS Enabled Flag: {self.tts_enabled.get()}")
            self.tts_queue.task_done()

        logging.info("TTS worker thread stopped.")

    def register_gmcp_listener(self, callback):
        if callable(callback):
            self.gmcp_listeners.append(callback)
            # logging.info(f"GMCP listener registered: {callback.__name__}") # Removed, less critical
        else:
            logging.warning(f"Attempted to register a non-callable GMCP listener: {callback}")

    def load_mods(self):
        mods_dir = "mods"
        if not os.path.exists(mods_dir):
            # logging.warning(f"Mods directory '{mods_dir}' not found. Creating it.") # Removed, less critical
            os.makedirs(mods_dir)
            return

        sys.path.insert(0, mods_dir)

        for filename in os.listdir(mods_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_name = filename[:-3]
                try:
                    spec = importlib.util.spec_from_file_location(module_name, os.path.join(mods_dir, filename))
                    if spec is None:
                        logging.error(f"Could not get spec for mod: {filename}")
                        continue

                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = mod
                    spec.loader.exec_module(mod)

                    if hasattr(mod, 'setup_mod_gui') and callable(mod.setup_mod_gui):
                        mod_frame = self.create_mod_frame(module_name)
                        mod.setup_mod_gui(mod_frame, self)
                        self.loaded_mods.append(mod)
                        # logging.info(f"Mod '{module_name}' loaded successfully.") # Removed, less critical
                    else:
                        logging.warning(f"Mod '{module_name}' does not have a callable 'setup_mod_gui' function.")

                except Exception as e:
                    logging.error(f"An error occurred loading mod '{module_name}': {e}")
                    logging.exception(f"Detailed error for mod '{module_name}'")

        sys.path.pop(0)

    def create_mod_frame(self, mod_name):
        display_name = mod_name.replace('_', ' ').title()
        frame = tk.LabelFrame(self.mod_container_frame, text=display_name, padx=5, pady=5)
        frame.pack(fill=tk.X, expand=False, padx=5, pady=5, anchor="n")
        return frame

    def open_profile_selection_dialog(self):
        if self.connected:
            messagebox.showwarning("Warning", "Already connected. Please disconnect first.")
            return

        if self._profile_select_dialog is not None and self._profile_select_dialog.winfo_exists():
            self._profile_select_dialog.focus_set()
            self._profile_select_dialog.lift()
            return

        self._profile_select_dialog = ProfileSelectionDialog(self.root, self.profile_manager, self.connect_to_profile_internal)

    def connect_to_profile_internal(self, profile_name):
        if self.connected:
            messagebox.showwarning("Warning", "Already connected.")
            return

        profile = self.profile_manager.profiles.get(profile_name)

        if profile:
            self.display_message(f"--- Attempting to connect to {profile['host']}:{profile['port']} ---\n", tags=("system_message",))
            self.status_message_label.config(text="Connecting...")
            self.speak_system_message(f"Attempting to connect to {profile_name} at {profile['host']}:{profile['port']}.")

            connection_thread = threading.Thread(target=self._initiate_connection, args=(profile['host'], profile['port'], profile_name))
            connection_thread.daemon = True
            connection_thread.start()
        else:
            messagebox.showerror("Error", "Selected profile not found. Please reload profiles.")
            self.speak_system_message("Selected profile not found.")
            self.load_profiles()

    def _initiate_connection(self, host, port, profile_name):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((host, port))
            self.sock.settimeout(None)

            self.telnet_buffer = b""
            self.telnet_parser_state = self.STATE_NORMAL
            self.telnet_sub_buffer = b""

            self.root.after(0, self.update_connection_status, True, profile_name)
            self.root.after(0, lambda: self.display_message("--- Connected to MUD ---\n", tags=("system_message", "ansi_32")))

            self.receive_thread = threading.Thread(target=self.receive_messages)
            self.receive_thread.daemon = True
            self.receive_thread.start()

            self.root.after(500, self.send_initial_gmcp_supports)

        except socket.timeout:
            self.root.after(0, lambda: self.display_message("Connection timed out.\n", tags=("system_message", "ansi_31")))
            self.speak_system_message("Connection timed out.")
            self.root.after(0, self.update_connection_status, False)
            logging.error(f"Connection timed out to {host}:{port}")
        except socket.error as e:
            self.root.after(0, lambda msg_text=f"Connection error: {e}\n": self.display_message(msg_text, tags=("system_message", "ansi_31")))
            self.speak_system_message(f"Connection error: {e}.")
            self.root.after(0, self.update_connection_status, False)
            logging.error(f"Socket error connecting to {host}:{port}: {e}")
        except Exception as e:
            self.root.after(0, lambda msg_text=f"An unexpected error occurred during connection: {e}\n": self.display_message(msg_text, tags=("system_message", "ansi_31")))
            self.speak_system_message(f"An unexpected error occurred during connection: {e}.")
            self.root.after(0, self.update_connection_status, False)
            logging.exception("An unexpected error occurred during connection")

    def disconnect(self):
        if not self.connected or not self.sock:
            # logging.info("Attempted to disconnect when not connected.") # Removed, less critical
            return

        try:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            # logging.info("Socket closed.") # Removed, less critical
        except socket.error as e:
            logging.warning(f"An error occurred during socket shutdown/close: {e}")
        except Exception as e:
            logging.warning(f"An unexpected error occurred during disconnect: {e}")
        finally:
            self.sock = None
            self.receive_thread = None
            self.root.after(0, self.update_connection_status, False)
            self.root.after(0, lambda: self.display_message("--- Disconnected from MUD ---\n", tags=("system_message", "ansi_31")))

    def receive_messages(self):
        line_buffer = ""
        self.sock.settimeout(0.1)

        while self.connected:
            try:
                received_bytes = self.sock.recv(4096)
                if not received_bytes:
                    # logging.info("Server disconnected gracefully.") # Removed, less critical
                    self.root.after(0, lambda: self.display_message("--- The server disconnected unexpectedly ---\n", tags=("system_message", "ansi_31")))
                    self.speak_system_message("The server disconnected unexpectedly.")
                    self.root.after(0, self.disconnect)
                    break

                self.telnet_buffer += received_bytes

                for text_chunk, is_prompt_signal in self._parse_telnet_stream_for_display_and_gmcp():
                    line_buffer += text_chunk

                    while "\n" in line_buffer:
                        newline_index = line_buffer.find("\n")
                        line_to_display = line_buffer[:newline_index + 1]
                        line_buffer = line_buffer[newline_index + 1:]

                        line_to_display = line_to_display.replace("\r", "")

                        self.root.after(0, self.display_message, line_to_display)

                    if is_prompt_signal or \
                       (not self.telnet_buffer and line_buffer and \
                        not (line_buffer.endswith('\n') or line_buffer.endswith('\r'))):

                        display_text = line_buffer.replace("\r", "")
                        if display_text:
                            self.root.after(0, self.display_message, display_text)
                        line_buffer = ""

            except socket.timeout:
                if line_buffer and not (line_buffer.endswith('\n') or line_buffer.endswith('\r')):
                    display_text = line_buffer.replace("\r", "")
                    if display_text:
                        self.root.after(0, self.display_message, display_text)
                    line_buffer = ""
                pass
            except socket.error as e:
                if self.connected:
                    logging.error(f"Socket error in receive_messages: {e}")
                    self.root.after(0, lambda msg_text=f"--- Network error: {e} ---\n": self.display_message(msg_text, tags=("system_message", "ansi_31")))
                    self.speak_system_message(f"Network error: {e}.")
                    self.root.after(0, self.disconnect)
                break
            except Exception as e:
                logging.exception(f"An unexpected error occurred in receive_messages: {e}")
                self.root.after(0, lambda msg_text=f"--- An unexpected error occurred: {e}\n": self.display_message(msg_text, tags=("system_message", "ansi_31")))
                self.speak_system_message(f"An unexpected error occurred: {e}.")
                self.root.after(0, self.disconnect)
                break

        if line_buffer:
            line_buffer = line_buffer.replace("\r", "")
            self.root.after(0, self.display_message, line_buffer + "\n")

    def _parse_telnet_stream_for_display_and_gmcp(self):
        i = 0
        display_buffer = b""

        while i < len(self.telnet_buffer):
            byte = self.telnet_buffer[i:i+1]

            is_prompt_signal = False

            if self.telnet_parser_state == self.STATE_NORMAL:
                if byte == self.IAC:
                    if display_buffer:
                        yield display_buffer.decode('utf-8', errors='replace'), False
                        display_buffer = b""
                    self.telnet_parser_state = self.STATE_IAC
                else:
                    display_buffer += byte

            elif self.telnet_parser_state == self.STATE_IAC:
                command = byte
                i += 1

                if command in (self.WILL, self.DO, self.WONT, self.DONT):
                    if i >= len(self.telnet_buffer):
                        i -= 1
                        break
                    
                    option = self.telnet_buffer[i:i+1]
                    # logging.debug(f"TELNET: Received IAC {command!r} option {option!r}") # Removed, often verbose

                    if command == self.WILL and option == self.GMCP:
                        # logging.info("TELNET: MUD WILL GMCP. Responding with DO GMCP.") # Removed, less critical
                        self.sock.sendall(self.IAC + self.DO + self.GMCP)
                    elif command == self.DO and option == self.SUPPRESS_GO_AHEAD:
                        # logging.info("TELNET: MUD DO SUPPRESS_GO_AHEAD. Responding with WILL SUPPRESS_GO_AHEAD.") # Removed, less critical
                        self.sock.sendall(self.IAC + self.WILL + self.SUPPRESS_GO_AHEAD)
                    elif command == self.DO and option == self.ECHO:
                        # logging.info("TELNET: MUD DO ECHO. Responding with WILL ECHO.") # Removed, less critical
                        self.sock.sendall(self.IAC + self.WILL + self.ECHO)

                    self.telnet_parser_state = self.STATE_NORMAL

                elif command == self.SB:
                    self.telnet_parser_state = self.STATE_SB_READ_OPTION
                    self.telnet_sub_buffer = b""

                elif command == self.IAC:
                    display_buffer += self.IAC
                    self.telnet_parser_state = self.STATE_NORMAL

                elif command == self.SE:
                    logging.warning("TELNET: Received an unexpected IAC SE in STATE_IAC. Resetting to NORMAL.")
                    self.telnet_parser_state = self.STATE_NORMAL

                elif command == self.NOP or command == self.GA:
                    # logging.debug(f"TELNET: Consumed a simple IAC command: {command!r}. Resetting to NORMAL.") # Removed, often verbose

                    if display_buffer:
                        decoded_text = display_buffer.decode('utf-8', errors='replace')
                        if command == self.GA and not (decoded_text.endswith('\n') or decoded_text.endswith('\r')):
                             is_prompt_signal = True
                        yield decoded_text, is_prompt_signal
                        display_buffer = b""
                    elif command == self.GA:
                        yield "", True

                    self.telnet_parser_state = self.STATE_NORMAL

            elif self.telnet_parser_state == self.STATE_SB_READ_OPTION:
                option_byte = byte
                # logging.debug(f"TELNET: In STATE_SB_READ_OPTION. Current byte (potential option): {option_byte!r}") # Removed, often verbose
                if option_byte == self.GMCP or option_byte in self.GMCP_DATA_OPTIONS:
                    self.telnet_parser_state = self.STATE_GMCP_SUB
                    self.telnet_sub_buffer = option_byte
                    # logging.debug(f"TELNET: Recognized a GMCP option (negotiation or data). Initializing sub buffer with: {option_byte!r}") # Removed, often verbose
                else:
                    # logging.debug(f"TELNET: Unknown SB option: {option_byte!r}. Transitioning to consume its payload.") # Removed, often verbose
                    self.telnet_parser_state = self.STATE_UNKNOWN_SB
                    self.telnet_sub_buffer = b""

            elif self.telnet_parser_state == self.STATE_GMCP_SUB:
                if byte == self.IAC:
                    if i + 1 < len(self.telnet_buffer) and self.telnet_buffer[i+1:i+2] == self.SE:
                        gmcp_raw_payload = self.telnet_sub_buffer
                        # logging.debug(f"TELNET: GMCP Subnegotiation ended. Raw payload accumulated: {gmcp_raw_payload!r}") # Removed, often verbose
                        try:
                            gmcp_string = gmcp_raw_payload.decode('latin-1', errors='replace')
                            # logging.debug(f"GMCP Dispatcher: Decoded GMCP string: '{gmcp_string}'") # Removed, often verbose
                            self.root.after(0, self._dispatch_gmcp_data, gmcp_string)
                        except Exception as e:
                            logging.error(f"Error decoding/dispatching GMCP payload: {e}. Raw: {gmcp_raw_payload!r}")
                            logging.exception("GMCP decode/dispatch details")

                        self.telnet_sub_buffer = b""
                        self.telnet_parser_state = self.STATE_NORMAL
                        i += 1
                    else:
                        self.telnet_sub_buffer += byte
                        # logging.debug(f"TELNET: Found IAC inside GMCP sub. Appending to payload. Current payload: {self.telnet_sub_buffer!r}") # Removed, often verbose
                else:
                    self.telnet_sub_buffer += byte
                    # logging.debug(f"TELNET: Appending to GMCP payload. Current byte: {byte!r}. Current payload: {self.telnet_sub_buffer!r}") # Removed, often verbose

            elif self.telnet_parser_state == self.STATE_UNKNOWN_SB:
                if byte == self.IAC:
                    if i + 1 < len(self.telnet_buffer) and self.telnet_buffer[i+1:i+2] == self.SE:
                        # logging.debug("TELNET: Unknown subnegotiation ended (IAC SE detected).") # Removed, often verbose
                        self.telnet_sub_buffer = b""
                        self.telnet_parser_state = self.STATE_NORMAL
                        i += 1
                    else:
                        pass
                else:
                    pass

            i += 1

        if display_buffer:
            yield display_buffer.decode('utf-8', errors='replace'), False

        self.telnet_buffer = self.telnet_buffer[i:]

    def _dispatch_gmcp_data(self, gmcp_string):
        # logging.debug(f"GMCP Dispatcher: Processing extracted GMCP. String: '{gmcp_string.strip()}'") # Removed, often verbose
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
                        logging.error(f"GMCP JSON decode error for package '{package_name}': {e}. JSON string: '{json_string}'")
                        json_data = {}

            for listener in self.gmcp_listeners:
                try:
                    listener(package_name, json_data)
                except Exception as e:
                    logging.error(f"An error occurred calling GMCP listener '{listener.__name__}': {e}")
                    logging.exception("GMCP listener callback details")

        except Exception as e:
            logging.error(f"Failed to parse GMCP message: {e}. Message: {gmcp_string!r}")
            logging.exception("GMCP parsing details")

    def send_gmcp(self, package_name, data=None):
        if not self.connected or not self.sock:
            # logging.warning("Attempted to send GMCP but not connected.") # Removed, less critical
            return

        payload_data = ""
        if data is not None:
            try:
                payload_data = json.dumps(data, separators=(',', ':'))
            except TypeError as e:
                logging.error(f"An error occurred JSON encoding GMCP data for {package_name}: {e}")
                return

        gmcp_content = f"{package_name} {payload_data}".encode('utf-8')

        full_packet = self.IAC + self.SB + self.GMCP + gmcp_content + self.IAC + self.SE

        try:
            self.sock.sendall(full_packet)
            # logging.debug(f"Sent GMCP: {package_name} {payload_data}") # Removed, often verbose
        except socket.error as e:
            logging.error(f"A socket error occurred sending GMCP: {e}")
            self.disconnect()
        except Exception as e:
            logging.exception(f"An unexpected error occurred sending GMCP {package_name}: {e}")

    def send_initial_gmcp_supports(self):
        supported_modules = {
            "Client.Core": ["1", "2"],
            "Room.Info": ["1"],
            "Char.Buffs": ["1"],
            "Char.Status": ["1"],
            "Char.Cooldowns": ["1"],
            "Char.Inventory": ["1"],
            "Char.Vitals": ["1"],
            "Char.Items.Inv": ["1"],
            "Char.Items.Equip": ["1"],
        }
        self.send_gmcp("Client.Core.Supports", supported_modules)
        # logging.info("Sent the Client.Core.Supports GMCP packet with specific modules.") # Removed, less critical

    def send_message(self, event=None):
        if not self.connected or not self.sock:
            self.display_message("Not connected to the MUD.\n", tags=("system_message", "ansi_31"))
            self.speak_system_message("Not connected to MUD.")
            return

        raw_message = self.input_entry.get()
        self.input_entry.delete(0, tk.END)

        if self.tts_engine and self.tts_enabled.get() and self.tts_read_user_input.get():
            self.tts_engine.stop()
            logging.debug(f"Queuing user input for TTS: 'You said: {raw_message}'")
            self.tts_queue.put(f"You said: {raw_message}")

        message_to_send = self.alias_manager.process_input(raw_message)

        self.display_message(f"> {raw_message}\n", tags=("user_input",))

        try:
            self.sock.sendall((message_to_send + "\n").encode('utf-8'))
            # logging.debug(f"Sent: {message_to_send!r} (originally: {raw_message!r})") # Removed, less critical
        except socket.error as e:
            self.display_message(f"An error occurred sending message: {e}\n", tags=("system_message", "ansi_31"))
            self.speak_system_message(f"Error sending message: {e}.")
            logging.error(f"Socket error sending message: {e}")
            self.disconnect()
        except Exception as e:
            self.display_message(f"An unexpected error occurred while sending: {e}\n", tags=("system_message", "ansi_31"))
            self.speak_system_message(f"An unexpected error occurred while sending: {e}.")
            logging.exception("An unexpected error occurred while sending message")

    def open_alias_manager_window(self):
        if self.alias_window is None or not self.alias_window.winfo_exists():
            self.alias_window = AliasManagerWindow(self.root, self.alias_manager)
        else:
            self.alias_window.focus_set()
            self.alias_window.lift()

    def open_profile_manager_window(self):
        if self.profile_manager_window is None or not self.profile_manager_window.winfo_exists():
            self.profile_manager_window = ProfileManagerWindow(self.root, self.profile_manager)
        else:
            self.profile_manager_window.focus_set()
            self.profile_manager_window.lift()

    def on_closing(self):
        if self.connected:
            if messagebox.askokcancel("Quit", "Connected. Disconnect and Quit?"):
                self.disconnect()
                if self.tts_thread and self.tts_thread.is_alive():
                    self.tts_queue.put(None)
                    self.tts_thread.join(timeout=1)
                if self.tts_engine:
                    self.tts_engine.stop()
                    self.tts_engine.runAndWait()
                self.root.destroy()
        else:
            if self.tts_thread and self.tts_thread.is_alive():
                self.tts_queue.put(None)
                self.tts_thread.join(timeout=1)
            if self.tts_engine:
                self.tts_engine.stop()
                self.tts_engine.runAndWait()
            self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = MUDClientApp(root)
    root.mainloop()
