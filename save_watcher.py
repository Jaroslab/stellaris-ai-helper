# save_watcher.py
import os
import sys
import time
import threading
from pathlib import Path

class SaveWatcher:
    """Watches Stellaris save directory for new saves."""

    def __init__(self, save_dir=None, callback=None):
        self.save_dir = save_dir or self._find_save_dir()
        self.callback = callback
        self.running = False
        self.thread = None
        self.last_mtime = 0
        self.last_file = None

    def _find_save_dir(self):
        """Find Stellaris save directory based on OS."""
        print("\n=== SAVE DIR DEBUG ===")

        if os.name == 'nt':  # Windows
            import ctypes
            from ctypes import wintypes

            # Get Documents folder
            docs = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, docs)
            base = str(docs.value)
            print(f"Documents folder: {base}")

            paths = [
                os.path.join(base, "Paradox Interactive", "Stellaris", "save games"),
                os.path.join(base, "Paradox Interactive", "Stellaris Plaza", "save games"),
                os.path.join(base, "Paradox Interactive", "Stellaris GamePass", "save games"),
            ]

            for p in paths:
                print(f"Checking: {p}")
                print(f"  Exists: {os.path.isdir(p)}")
                if os.path.isdir(p):
                    print(f"=== FOUND SAVE DIR ===\n")
                    return p

        elif os.name == 'posix':  # Linux/Mac
            home = str(Path.home())
            print(f"Home folder: {home}")

            if sys.platform == 'darwin':  # Mac
                paths = [
                    os.path.join(home, "Documents", "Paradox Interactive", "Stellaris", "save games"),
                ]
            else:  # Linux
                paths = [
                    os.path.join(home, ".local", "share", "Paradox Interactive", "Stellaris", "save games"),
                    os.path.join(home, ".steam", "steam", "steamapps", "compatdata", "281990", "pfx", "drive_c", "users", "steamuser", "Documents", "Paradox Interactive", "Stellaris", "save games"),
                ]

            for p in paths:
                print(f"Checking: {p}")
                print(f"  Exists: {os.path.isdir(p)}")
                if os.path.isdir(p):
                    print(f"=== FOUND SAVE DIR ===\n")
                    return p

        print("=== NO SAVE DIR FOUND ===\n")
        return None

    def get_latest_save(self, quiet=True):
        """Find the most recent .sav file."""
        if not quiet:
            print("\n=== LATEST SAVE DEBUG ===")

        if not self.save_dir or not os.path.isdir(self.save_dir):
            return None

        latest = None
        latest_mtime = 0

        for root, dirs, files in os.walk(self.save_dir):
            for f in files:
                if f.endswith('.sav'):
                    path = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(path)
                        if not quiet:
                            print(f"  Found: {f}")
                        if mtime > latest_mtime:
                            latest_mtime = mtime
                            latest = path
                    except:
                        pass

        if not quiet:
            print(f"Latest: {latest}")
            print("========================\n")

        return latest

    def _watch_loop(self):
        """Background thread that checks for new saves."""
        while self.running:
            try:
                latest = self.get_latest_save()
                if latest:
                    mtime = os.path.getmtime(latest)
                    # Only print when something NEW happens
                    if mtime > self.last_mtime and latest != self.last_file:
                        size1 = os.path.getsize(latest)
                        time.sleep(0.5)
                        size2 = os.path.getsize(latest)

                        if size1 == size2:
                            print(f"\n>>> NEW SAVE DETECTED: {os.path.basename(latest)}")
                            self.last_mtime = mtime
                            self.last_file = latest
                            if self.callback:
                                self.callback(latest)

            except Exception as e:
                print(f"Watch error: {e}")

            time.sleep(2)

    def start(self):
        """Start watching for changes."""
        if self.running:
            return

        # Get initial save
        latest = self.get_latest_save()
        if latest:
            self.last_file = latest
            self.last_mtime = os.path.getmtime(latest)

            # NEW: Load the initial save immediately
            print(f"Loading initial save: {latest}")
            if self.callback:
                self.callback(latest)

        self.running = True
        self.thread = threading.Thread(target=self._watch_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop watching."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)