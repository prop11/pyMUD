import json
import os
from pathlib import Path

class ProfileManager:
    def __init__(self, filename="profiles.json"):
        # Save the profiles file in the user's home directory
        self.filename = os.path.join(Path.home(), filename)
        self.profiles = self.load_profiles()

    def load_profiles(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as file:
                    return json.load(file)
            except Exception as e:
                print(f"Error loading profiles: {e}")
        return {}

    def save_profiles(self):
        try:
            with open(self.filename, 'w') as file:
                json.dump(self.profiles, file, indent=4)
        except Exception as e:
            print(f"Error saving profiles: {e}")

    def add_profile(self, name, host, port):
        self.profiles[name] = {'host': host, 'port': port}
        self.save_profiles()

    def remove_profile(self, name):
        if name in self.profiles:
            del self.profiles[name]
            self.save_profiles()
