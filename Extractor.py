# stellaris_extractor_v2_fixed.py
# Comprehensive data extractor for Stellaris (Fixed version)

import os
import re
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
from collections import defaultdict

VERSION = "2.1"

class StellarisDataExtractor:
    """Extracts comprehensive data from Stellaris game files."""

    DATA_CATEGORIES = {
        'technologies': 'technology',
        'buildings': 'buildings',
        'ship_sizes': 'ship_sizes',
        'resources': 'strategic_resources',
        'traits': 'traits',
        'species_traits': 'species_traits',
        'leader_traits': 'leader_traits',
        'ruler_traits': 'ruler_traits',
        'ethics': 'ethics',
        'civics': 'civics',
        'governments': 'government_types',
        'policies': 'policies',
        'edicts': 'edicts',
        'traditions': 'traditions',
        'ascension_perks': 'ascension_perks',
        'planet_classes': 'planet_classes',
        'deposits': 'deposits',
        'tile_blockers': 'tile_blockers',
        'starbase_buildings': 'starbase_buildings',
        'starbase_modules': 'starbase_modules',
        'armies': 'armies',
    }

    def __init__(self):
        self.all_data = {}
        self.localization = {}
        self.errors = []
        self.stats = defaultdict(int)

    def parse_paradox_file(self, filepath):
        """Parse Paradox format file."""
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                content = f.read()
        except Exception as e:
            self.errors.append(f"Read error {filepath}: {e}")
            return {}

        content = re.sub(r'#[^\n]*', '', content)
        result, _ = self._parse_block(content, 0)
        return result

    def _parse_block(self, content, pos=0):
        result = {}
        list_values = []
        i = pos
        length = len(content)

        while i < length:
            while i < length and content[i] in ' \t\n\r':
                i += 1

            if i >= length:
                break

            if content[i] == '}':
                if list_values and not result:
                    return list_values, i + 1
                if list_values:
                    result["__values__"] = list_values
                return result, i + 1

            token, i = self._read_token(content, i)
            if not token:
                i += 1
                continue

            while i < length and content[i] in ' \t\n\r':
                i += 1

            if i >= length:
                list_values.append(self._convert(token))
                break

            if content[i] == '=':
                i += 1
                while i < length and content[i] in ' \t\n\r':
                    i += 1

                if i >= length:
                    result[token] = None
                    break

                if content[i] == '{':
                    i += 1
                    value, i = self._parse_block(content, i)
                    result[token] = value
                elif content[i] == '"':
                    value, i = self._read_string(content, i)
                    result[token] = value
                else:
                    val, i = self._read_token(content, i)
                    result[token] = self._convert(val)

            elif content[i] == '{':
                i += 1
                value, i = self._parse_block(content, i)
                result[token] = value
            else:
                list_values.append(self._convert(token))

        if list_values and not result:
            return list_values, i
        if list_values:
            result["__values__"] = list_values
        return result, i

    def _read_token(self, content, pos):
        i = pos
        length = len(content)
        if i < length and content[i] in '{}=:\n\r\t "':
            return "", i
        start = i
        while i < length and content[i] not in ' \t\n\r{}="':
            i += 1
        return content[start:i], i

    def _read_string(self, content, pos):
        if content[pos] != '"':
            return "", pos
        i = pos + 1
        length = len(content)
        chars = []
        while i < length:
            if content[i] == '\\' and i + 1 < length:
                chars.append(content[i + 1])
                i += 2
            elif content[i] == '"':
                return ''.join(chars), i + 1
            else:
                chars.append(content[i])
                i += 1
        return ''.join(chars), i

    def _convert(self, val):
        if not val:
            return ""
        if val.lower() == 'yes':
            return True
        if val.lower() == 'no':
            return False
        try:
            return int(val)
        except:
            pass
        try:
            return float(val)
        except:
            pass
        return val

    def load_localization(self, stellaris_path):
        self.localization = {}

        loc_paths = [
            os.path.join(stellaris_path, 'localisation', 'english'),
            os.path.join(stellaris_path, 'localisation', 'l_english'),
            os.path.join(stellaris_path, 'localisation'),
        ]

        loc_path = None
        for p in loc_paths:
            if os.path.exists(p):
                loc_path = p
                break

        if not loc_path:
            self.errors.append("Localization folder not found")
            return

        for root, dirs, files in os.walk(loc_path):
            for filename in files:
                if not filename.endswith('.yml'):
                    continue

                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8-sig') as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith('#'):
                                continue
                            match = re.match(r'([\w.-]+):\d*\s+"(.*)"', line)
                            if match:
                                key, val = match.groups()
                                self.localization[key] = val.replace('\\"', '"')
                except Exception as e:
                    self.errors.append(f"Loc error {filename}: {e}")

    def loc(self, key, fallback=None):
        if key in self.localization:
            return self.localization[key]
        for suffix in ['', '_name', '_desc', '_title']:
            if f"{key}{suffix}" in self.localization:
                return self.localization[f"{key}{suffix}"]
        if fallback:
            return fallback
        return key.replace('_', ' ').title()

    def extract_category(self, common_path, folder_name):
        """Extract a single category of data."""
        folder_path = os.path.join(common_path, folder_name)

        if not os.path.exists(folder_path):
            return {}

        category_data = {}

        for filename in os.listdir(folder_path):
            if not filename.endswith('.txt'):
                continue

            filepath = os.path.join(folder_path, filename)
            data = self.parse_paradox_file(filepath)

            # FIX: Handle cases where data is not a dict
            if not isinstance(data, dict):
                if isinstance(data, list):
                    self.errors.append(f"Skipped list-format file: {filename}")
                continue

            for entry_id, entry_data in data.items():
                if not isinstance(entry_data, dict):
                    continue

                if entry_id in ('category', 'categories', 'area', 'tier', 
                               'table', 'type', 'types', 'groups', '__values__'):
                    continue

                processed = self._process_entry(entry_id, entry_data, folder_name)
                if processed:
                    category_data[entry_id] = processed

        return category_data

    def _process_entry(self, entry_id, entry_data, category):
        processed = {
            'id': entry_id,
            'name': self.loc(entry_id, entry_id),
            'description': self.loc(f"{entry_id}_desc", ""),
            'category': category,
        }

        if category == 'technology':
            processed.update({
                'tier': entry_data.get('tier', 0),
                'cost': entry_data.get('cost', 0),
                'area': entry_data.get('area', 'unknown'),
                'prerequisites': self._get_list(entry_data, 'prerequisites'),
                'weight': entry_data.get('weight', 0),
                'category_tags': self._get_list(entry_data, 'category'),
            })

        elif category in ('buildings', 'starbase_buildings'):
            processed.update({
                'buildtime': entry_data.get('buildtime', 0),
                'resources': entry_data.get('resources', {}),
                'upgrades': self._get_list(entry_data, 'upgrades'),
            })

        elif category in ('traits', 'species_traits', 'leader_traits'):
            processed.update({
                'cost': entry_data.get('cost', 0),
                'modifier': entry_data.get('modifier', {}),
            })

        elif category == 'ethics':
            processed.update({
                'icon': entry_data.get('icon', ''),
            })

        elif category == 'civics':
            processed.update({
                'cost': entry_data.get('cost', 0),
                'possible': entry_data.get('possible', {}),
            })

        elif category == 'traditions':
            processed.update({
                'cost': entry_data.get('cost', 0),
                'prerequisites': self._get_list(entry_data, 'prerequisites'),
            })

        elif category == 'strategic_resources':
            processed.update({
                'type': entry_data.get('type', 'basic'),
                'rare': entry_data.get('is_rare', False),
            })

        return processed

    def _get_list(self, data, key):
        val = data.get(key, [])
        if isinstance(val, list):
            if val and isinstance(val[0], dict):
                return []
            return val
        if isinstance(val, str):
            return [val] if val else []
        if isinstance(val, dict) and '__values__' in val:
            return val['__values__']
        return []

    def extract_all(self, stellaris_path, progress_callback=None):
        common_path = os.path.join(stellaris_path, 'common')

        if not os.path.exists(common_path):
            self.errors.append("Common folder not found")
            return {}

        if progress_callback:
            progress_callback("Loading localization...")
        self.load_localization(stellaris_path)

        for data_key, folder_name in self.DATA_CATEGORIES.items():
            if progress_callback:
                progress_callback(f"Extracting {folder_name}...")

            category_data = self.extract_category(common_path, folder_name)
            if category_data:
                self.all_data[data_key] = category_data
                self.stats[data_key] = len(category_data)

        output = {
            'metadata': {
                'source': stellaris_path,
                'version': VERSION,
                'extraction_stats': dict(self.stats),
                'total_entries': sum(self.stats.values()),
                'localization_count': len(self.localization),
            },
            'localization': self.localization,
        }

        output.update(self.all_data)
        return output

class ExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Stellaris Data Extractor v{VERSION}")
        self.root.geometry("650x600")
        self.root.configure(bg="#1a1a2e")

        self.extractor = StellarisDataExtractor()
        self.stellaris_path = tk.StringVar()
        self.output_path = tk.StringVar(value="stellaris_game_data.json")
        self.status = tk.StringVar(value="Ready")

        self._setup_ui()
        self._auto_detect()

    def _setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background="#1a1a2e")
        style.configure("TLabel", background="#1a1a2e", foreground="#e0e0e0")
        style.configure("Header.TLabel", background="#1a1a2e", foreground="#00d4ff",
                        font=("Segoe UI", 16, "bold"))
        style.configure("Subtle.TLabel", background="#1a1a2e", foreground="#888888")

        main = ttk.Frame(self.root, padding=20)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Stellaris Data Extractor", style="Header.TLabel").pack(pady=(0, 5))
        ttk.Label(main, text="Extracts tech, buildings, traits, ethics, civics, traditions, and more.",
                  style="Subtle.TLabel", wraplength=600).pack(pady=(0, 20))

        input_frame = ttk.Frame(main)
        input_frame.pack(fill="x", pady=5)
        ttk.Label(input_frame, text="Stellaris Installation:").pack(anchor="w")

        path_row = ttk.Frame(input_frame)
        path_row.pack(fill="x", pady=2)
        tk.Entry(path_row, textvariable=self.stellaris_path, bg="#16213e", fg="#e0e0e0",
                 font=("Consolas", 10)).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Button(path_row, text="Browse", command=self._browse_stellaris).pack(side="right")

        out_frame = ttk.Frame(main)
        out_frame.pack(fill="x", pady=10)
        ttk.Label(out_frame, text="Output File:").pack(anchor="w")

        out_row = ttk.Frame(out_frame)
        out_row.pack(fill="x", pady=2)
        tk.Entry(out_row, textvariable=self.output_path, bg="#16213e", fg="#e0e0e0",
                 font=("Consolas", 10)).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Button(out_row, text="Save As", command=self._browse_output).pack(side="right")

        ttk.Label(main, text="Progress:", style="Subtle.TLabel").pack(anchor="w", pady=(10, 2))

        log_frame = tk.Frame(main, bg="#16213e")
        log_frame.pack(fill="both", expand=True, pady=5)

        self.log_text = tk.Text(log_frame, bg="#16213e", fg="#00ff88",
                                font=("Consolas", 9), wrap="word", height=8)
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=15)
        ttk.Button(btn_frame, text="Extract All Data", command=self._extract).pack(side="left", padx=5)

        ttk.Label(main, textvariable=self.status, style="Subtle.TLabel").pack(pady=5)

    def _auto_detect(self):
        paths = [
            r"C:\Program Files (x86)\Steam\steamapps\common\Stellaris",
            r"C:\Program Files\Steam\steamapps\common\Stellaris",
            r"D:\SteamLibrary\steamapps\common\Stellaris",
            os.path.expanduser("~/.steam/steam/steamapps/common/Stellaris"),
        ]
        for path in paths:
            if os.path.exists(path):
                self.stellaris_path.set(path)
                self._log(f"Auto-detected: {path}")
                return
        self._log("Please browse to your Stellaris installation folder.")

    def _browse_stellaris(self):
        path = filedialog.askdirectory(title="Select Stellaris Folder")
        if path:
            self.stellaris_path.set(path)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            self.output_path.set(path)

    def _log(self, msg):
        self.log_text.insert("end", f"{msg}\n")
        self.log_text.see("end")
        self.log_text.update()

    def _extract(self):
        stellaris_path = self.stellaris_path.get()
        output_path = self.output_path.get()

        if not stellaris_path or not output_path:
            messagebox.showerror("Error", "Please fill in all fields")
            return

        if not os.path.exists(os.path.join(stellaris_path, 'common')):
            messagebox.showerror("Error", "Invalid Stellaris folder (no 'common' directory)")
            return

        self.log_text.delete("1.0", "end")
        self.status.set("Extracting...")
        threading.Thread(target=self._extract_thread, args=(stellaris_path, output_path), daemon=True).start()

    def _extract_thread(self, stellaris_path, output_path):
        try:
            def progress(msg):
                self.root.after(0, lambda m=msg: self._log(m))

            data = self.extractor.extract_all(stellaris_path, progress)

            if not data:
                self.root.after(0, lambda: messagebox.showerror("Error", "No data extracted."))
                return

            for key, count in self.extractor.stats.items():
                self.root.after(0, lambda k=key, c=count: self._log(f"  {k}: {c} entries"))

            for err in self.extractor.errors[:10]:
                self.root.after(0, lambda e=err: self._log(f"Note: {e}"))

            self.root.after(0, lambda: self._log("Saving to JSON..."))

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            total = data['metadata']['total_entries']
            loc_count = data['metadata']['localization_count']

            self.root.after(0, lambda: self._log(f"\nDone! {total} entries, {loc_count} loc strings"))
            self.root.after(0, lambda: self._log(f"Saved to: {output_path}"))

            msg = f"Success!\n\nTotal: {total} entries\nLocalization: {loc_count}\n\nSaved to:\n{output_path}"
            self.root.after(0, lambda: messagebox.showinfo("Done", msg))
            self.root.after(0, lambda: self.status.set("Done!"))

        except Exception as e:
            import traceback
            traceback.print_exc()
            err_msg = str(e)
            self.root.after(0, lambda: messagebox.showerror("Error", err_msg))
            self.root.after(0, lambda: self.status.set("Failed"))

if __name__ == "__main__":
    root = tk.Tk()
    app = ExtractorApp(root)
    root.mainloop()