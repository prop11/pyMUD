import tkinter as tk
from src.mud_client_app import MUDClientApp # Import MUDClientApp from the src package

if __name__ == "__main__":
    root = tk.Tk()
    app = MUDClientApp(root)
    root.mainloop()
