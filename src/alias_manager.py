import json
import os
import logging

# Configure logging for the AliasManager
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class AliasManager:
    """
    Manages user-defined aliases for the MUD client.
    Aliases are stored in a JSON file.
    """
    def __init__(self, alias_file="aliases.json"):
        self.alias_file = alias_file
        self.aliases = self._load_aliases()
        logging.info(f"AliasManager initialized. Loaded {len(self.aliases)} aliases.")

    def _load_aliases(self):
        """Loads aliases from the JSON file."""
        if os.path.exists(self.alias_file):
            try:
                with open(self.alias_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                logging.error(f"Error decoding aliases.json: {e}. Starting with empty aliases.")
                return {}
            except Exception as e:
                logging.error(f"Error loading aliases.json: {e}. Starting with empty aliases.")
                return {}
        return {}

    def _save_aliases(self):
        """Saves current aliases to the JSON file."""
        try:
            with open(self.alias_file, 'w') as f:
                json.dump(self.aliases, f, indent=4)
            logging.info(f"Aliases saved to {self.alias_file}")
        except Exception as e:
            logging.error(f"Error saving aliases to {self.alias_file}: {e}")

    def add_alias(self, command: str, replacement: str) -> bool:
        """
        Adds a new alias or updates an existing one.
        Returns True if successful, False otherwise (e.g., invalid input).
        """
        if not command or not replacement:
            logging.warning("Cannot add empty alias command or replacement.")
            return False
        
        # We'll keep aliases case-sensitive as is common in MUDs.
        self.aliases[command] = replacement
        self._save_aliases()
        logging.info(f"Alias added/updated: '{command}' -> '{replacement}'")
        return True

    def remove_alias(self, command: str) -> bool:
        """
        Removes an alias.
        Returns True if the alias was found and removed, False otherwise.
        """
        if command in self.aliases:
            del self.aliases[command]
            self._save_aliases()
            logging.info(f"Alias removed: '{command}'")
            return True
        logging.warning(f"Attempted to remove non-existent alias: '{command}'")
        return False

    def get_aliases(self) -> dict:
        """Returns a copy of all current aliases."""
        return self.aliases.copy()

    def process_input(self, user_input: str) -> str:
        """
        Checks if the user_input matches an alias and returns the expanded command.
        If no alias matches, the original input is returned.
        Supports simple aliases (full match) and basic prefix aliases.
        """
        if not user_input:
            return ""

        # First, try exact match
        if user_input in self.aliases:
            logging.debug(f"Alias matched (exact): '{user_input}' -> '{self.aliases[user_input]}'")
            return self.aliases[user_input]

        # Then, try prefix match (e.g., 'k mob' matches 'k' -> 'kill')
        # This is a common MUD alias style.
        parts = user_input.split(' ', 1) # Split only on the first space
        command_part = parts[0]
        args_part = parts[1] if len(parts) > 1 else ''

        if command_part in self.aliases:
            expanded_command = self.aliases[command_part]
            # If the alias has arguments, append them.
            # E.g., if alias 'k' is 'kill', and user types 'k mob', becomes 'kill mob'.
            if args_part:
                logging.debug(f"Alias matched (prefix): '{command_part}' -> '{expanded_command}'. Appending args: '{args_part}'")
                return f"{expanded_command} {args_part}"
            else:
                logging.debug(f"Alias matched (prefix, no args): '{command_part}' -> '{expanded_command}'")
                return expanded_command

        logging.debug(f"No alias found for: '{user_input}'. Returning original input.")
        return user_input

# Example Usage (for testing AliasManager directly if needed)
if __name__ == "__main__":
    manager = AliasManager(alias_file="test_aliases.json")

    print("\nInitial aliases:", manager.get_aliases())

    manager.add_alias("l", "look")
    manager.add_alias("k", "kill")
    manager.add_alias("getall", "get all from corpse")
    manager.add_alias("inv", "inventory")
    manager.add_alias("north", "n") # Alias can map to shorter command

    print("\nAliases after adding:", manager.get_aliases())

    print("\nProcessing inputs:")
    print(f"Input 'l': {manager.process_input('l')}")
    print(f"Input 'k goblin': {manager.process_input('k goblin')}")
    print(f"Input 'getall': {manager.process_input('getall')}")
    print(f"Input 'inv': {manager.process_input('inv')}")
    print(f"Input 'score': {manager.process_input('score')}")
    print(f"Input 'look around': {manager.process_input('look around')}") # Should not expand 'look'
    print(f"Input 'north': {manager.process_input('north')}")


    manager.remove_alias("l")
    print("\nAliases after removing 'l':", manager.get_aliases())
    print(f"Input 'l': {manager.process_input('l')}") # Should now return 'l'

    # Clean up test file
    if os.path.exists("test_aliases.json"):
        os.remove("test_aliases.json")
        print("\nCleaned up test_aliases.json")