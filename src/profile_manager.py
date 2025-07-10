import json
import os
from pathlib import Path
import logging # Import the logging module

class ProfileManager:
    def __init__(self, filename="profiles.json"):
        # Save the profiles file in the user's home directory
        self.filename = os.path.join(Path.home(), filename)
        self.profiles = self.load_profiles()
        logging.info(f"ProfileManager initialized. Profile file: {self.filename}. Loaded {len(self.profiles)} profiles.")


    def load_profiles(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as file:
                    loaded_data = json.load(file)
                    # Basic validation: ensure loaded data is a dictionary
                    if isinstance(loaded_data, dict):
                        logging.info(f"Profiles loaded successfully from {self.filename}")
                        return loaded_data
                    else:
                        logging.error(f"Profile file {self.filename} contains invalid data format. Expected dictionary, got {type(loaded_data).__name__}. Starting with empty profiles.")
                        return {}
            except json.JSONDecodeError as e:
                logging.error(f"Error decoding JSON from {self.filename}. File might be corrupted: {e}. Starting with empty profiles.")
            except Exception as e:
                logging.error(f"An unexpected error occurred while loading profiles from {self.filename}: {e}. Starting with empty profiles.")
        else:
            logging.info(f"Profile file {self.filename} not found. Starting with empty profiles.")
        return {} # Return empty dictionary if file doesn't exist or loading fails

    def save_profiles(self):
        try:
            with open(self.filename, 'w') as file:
                json.dump(self.profiles, file, indent=4)
            logging.info(f"Profiles saved successfully to {self.filename}")
        except Exception as e:
            logging.error(f"Error saving profiles to {self.filename}: {e}")

    def add_profile(self, name, host, port):
        self.profiles[name] = {'host': host, 'port': port}
        self.save_profiles()
        logging.info(f"Profile '{name}' added and saved.")


    def remove_profile(self, name):
        if name in self.profiles:
            del self.profiles[name]
            self.save_profiles()
            logging.info(f"Profile '{name}' removed and saved.")
        else:
            logging.warning(f"Attempted to remove non-existent profile: '{name}'.")