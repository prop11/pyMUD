if __name__ == "__main__":
    import tkinter as tk
    from src.mud_client_app import MUDClientApp  # Updated import

    root = tk.Tk()
    app = MUDClientApp(root)
    root.mainloop()
