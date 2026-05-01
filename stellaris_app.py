# stellaris_app.py
# Version 1.9 - Added table rendering, deep search for prerequisites
import tkinter as tk
from tkinter import ttk, messagebox
import json
import sys
import re
import requests
import threading
import os
import time
import hashlib
from difflib import get_close_matches
from PIL import Image, ImageTk
from datetime import datetime
from save_watcher import SaveWatcher
from save_parser import parse_save, save_valid
from data_extractor import extract_summary, get_empires, get_player_empire

# Handle paths for both script and compiled EXE
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = sys._MEIPASS
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

RESOURCE_DIR = os.path.join(SCRIPT_DIR, "resources")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "stellaris_config.json")
CACHE_FILE = os.path.join(SCRIPT_DIR, "response_cache.json")
DRAFT_FILE = os.path.join(SCRIPT_DIR, "draft.json")
DATA_FILE = os.path.join(SCRIPT_DIR, "source data", "stellaris_unified_fixed.json")
GAME_DATA_FILE = os.path.join(SCRIPT_DIR, "source data", "stellaris_game_data.json")

VERSION = "1.9"

DEFAULT_CONFIG = {
    "api_key": "",
    "api_url": "https://nano-gpt.com/api/v1/chat/completions",
    "model": "zai-org/glm-5:thinking",
    "conversation_mode": False,
    "cache_enabled": True,
    "rate_limit_seconds": 2,
    "temperature": 0.4,
    "max_tokens": 2500,
    "deep_search_mode": False,
    "live_data_mode": False
}

# Rate limiting
LAST_REQUEST_TIME = 0
MIN_REQUEST_INTERVAL = 2

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                return {**DEFAULT_CONFIG, **loaded}
        except Exception as e:
            print(f"Config load error: {e}")
    return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Config save error: {e}")

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except:
        pass

def load_draft():
    if os.path.exists(DRAFT_FILE):
        try:
            with open(DRAFT_FILE, "r", encoding="utf-8") as f:
                draft = json.load(f)
                if time.time() - draft.get("timestamp", 0) < 3600:
                    return draft.get("question", "")
        except:
            pass
    return ""

def save_draft(question):
    try:
        with open(DRAFT_FILE, "w", encoding="utf-8") as f:
            json.dump({"question": question, "timestamp": time.time()}, f)
    except:
        pass

def clear_draft():
    try:
        if os.path.exists(DRAFT_FILE):
            os.remove(DRAFT_FILE)
    except:
        pass

def load_theme():
    theme_path = os.path.join(RESOURCE_DIR, "theme.json")
    default_theme = {
        "colors": {
            "background": "#0f172a",
            "surface": "#16213e",
            "surface_light": "#1e3a5f",
            "accent": "#00d4ff",
            "accent_hover": "#00ffff",
            "accent_secondary": "#f39c12",
            "text": "#e0e0e0",
            "text_dim": "#888888",
            "error": "#e94560",
            "success": "#27ae60",
            "warning": "#f39c12",
            "button_blue": "#1e40af",
            "button_blue_hover": "#2563eb",
            "button_blue_active": "#1d4ed8"
        },
        "fonts": {
            "title": {"family": "Segoe UI", "size": 18, "weight": "bold"},
            "section": {"family": "Segoe UI", "size": 10, "weight": "bold"},
            "normal": {"family": "Segoe UI", "size": 10},
            "entry": {"family": "Segoe UI", "size": 11}
        },
        "window": {"width": 950, "height": 850, "title": "Stellaris AI Helper v1.7"}
    }

    if os.path.exists(theme_path):
        try:
            with open(theme_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                for key in default_theme:
                    if key not in loaded:
                        loaded[key] = default_theme[key]
                    elif isinstance(default_theme[key], dict):
                        for subkey in default_theme[key]:
                            if subkey not in loaded[key]:
                                loaded[key][subkey] = default_theme[key][subkey]
                return loaded
        except:
            pass
    return default_theme

def load_image(filename, size=None, folder=""):
    if folder:
        path = os.path.join(RESOURCE_DIR, folder, filename)
    else:
        path = os.path.join(RESOURCE_DIR, filename)

    if not os.path.exists(path):
        if not filename.endswith(".png"):
            path = os.path.join(RESOURCE_DIR, folder, filename + ".png") if folder \
                else os.path.join(RESOURCE_DIR, filename + ".png")

    if not os.path.exists(path):
        return None

    try:
        img = Image.open(path)
        if img.mode == "RGBA":
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)
        if size:
            img = img.resize(size, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception as e:
        print(f"Could not load image {filename}: {e}")
        return None

def estimate_tokens(text):
    return max(1, len(text) // 4)

def validate_data(data):
    issues = []
    if not data:
        issues.append("No data loaded")
        return issues

    empty_sections = []
    for key, value in data.items():
        if not value:
            empty_sections.append(key)
    if empty_sections:
        issues.append(f"Empty sections: {', '.join(empty_sections[:5])}")
    return issues

# Load configuration and theme
CONFIG = load_config()
THEME = load_theme()
RESPONSE_CACHE = load_cache()
MIN_REQUEST_INTERVAL = CONFIG.get("rate_limit_seconds", 2)

# Load game data
try:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        DATA = json.load(f)
    DATA_LOADED = True
    DATA_ISSUES = validate_data(DATA)
except FileNotFoundError:
    DATA = {}
    DATA_LOADED = False
    DATA_ISSUES = ["Data file not found"]
except json.JSONDecodeError as e:
    DATA = {}
    DATA_LOADED = False
    DATA_ISSUES = [f"Invalid JSON: {e}"]
except Exception as e:
    DATA = {}
    DATA_LOADED = False
    DATA_ISSUES = [f"Load error: {e}"]

try:
    with open(GAME_DATA_FILE, "r", encoding="utf-8") as f:
        GAME_DATA = json.load(f)
    GAME_DATA_LOADED = True
    GAME_DATA_ISSUES = validate_data(GAME_DATA)
except FileNotFoundError:
    GAME_DATA = {}
    GAME_DATA_LOADED = False
    GAME_DATA_ISSUES = ["Game data file not found"]
except json.JSONDecodeError as e:
    GAME_DATA = {}
    GAME_DATA_LOADED = False
    GAME_DATA_ISSUES = [f"Game data invalid JSON: {e}"]
except Exception as e:
    GAME_DATA = {}
    GAME_DATA_LOADED = False
    GAME_DATA_ISSUES = [f"Game data load error: {e}"]

def search(query, max_results=5):
    """Search for matching data with complete recursive search."""
    if not DATA_LOADED or not query:
        return []

    query_lower = query.lower()
    query_norm = query_lower.replace("-", "").replace("_", "").replace(" ", "")
    query_words = [w for w in re.findall(r'\b\w+\b', query_lower) if len(w) > 2]

    found_items = []
    seen_keys = set()

    def get_item_key(item):
        """Get unique key for deduplication."""
        item_id = str(item.get("id", "")).lower()
        item_name = str(item.get("name", "")).lower()
        if not item_id and not item_name:
            return json.dumps(item, sort_keys=True, default=str)
        return (item_id, item_name)

    def score_item(item):
        """Score how well an item matches the query."""
        item_name = str(item.get("name", "")).lower()
        item_id = str(item.get("id", "")).lower()
        item_name_norm = item_name.replace("-", "").replace("_", "").replace(" ", "")
        item_id_norm = item_id.replace("-", "").replace("_", "").replace(" ", "")

        # 1. Exact normalized match
        if query_norm == item_name_norm or query_norm == item_id_norm:
            return 500

        # 2. Item name is INSIDE the query
        #    IMPORTANT: Require minimum length to avoid matching "i" or "a"
        if len(item_name_norm) >= 3 and item_name_norm in query_norm:
            return 300
        if len(item_id_norm) >= 3 and item_id_norm in query_norm:
            return 280

        # 3. Query is inside the item name
        if len(query_norm) >= 3 and (item_name_norm and query_norm in item_name_norm):
            return 250
        if len(query_norm) >= 3 and (item_id_norm and query_norm in item_id_norm):
            return 240

        score = 0

        # 4. Word matching
        for qw in query_words:
            if qw in item_name or qw in item_id:
                score += 30

        # 5. Prerequisites matching for tech questions
        prereq_str = ""
        for field in ["prerequisites", "prereq", "requires"]:
            val = item.get(field)
            if val:
                if isinstance(val, dict):
                    prereq_str += json.dumps(val).lower()
                elif isinstance(val, list):
                    prereq_str += " ".join(str(v) for v in val).lower()
                else:
                    prereq_str += str(val).lower()

        tech_keywords = [
            'prerequisite', 'need', 'require', 'unlock', 'tree', 'research',
            'path', 'way', 'route', 'get', 'before', 'after', 'lead'
        ]
        is_tech_query = any(kw in query_lower for kw in tech_keywords)
        if is_tech_query and prereq_str:
            score += 50

        for qw in query_words:
            if qw in prereq_str:
                score += 20

        return score

    def recursive_search(data, path=""):
        """Recursively search through ALL nested structures."""
        if isinstance(data, dict):
            # Check if this dict is an item
            if "name" in data or "id" in data or "tier" in data:
                key = get_item_key(data)
                if key not in seen_keys:
                    score = score_item(data)
                    if score > 0:
                        seen_keys.add(key)
                        found_items.append((path, data, score))

            # Recurse into children (skip long text fields)
            for key, value in data.items():
                if key in ["description", "sources", "image", "icon"]:
                    continue
                child_path = f"{path}/{key}" if path else key
                recursive_search(value, child_path)

        elif isinstance(data, list):
            for i, item in enumerate(data):
                child_path = f"{path}[{i}]"
                if isinstance(item, dict):
                    if "name" in item or "id" in item or "tier" in item:
                        key = get_item_key(item)
                        if key not in seen_keys:
                            score = score_item(item)
                            if score > 0:
                                seen_keys.add(key)
                                found_items.append((child_path, item, score))
                    recursive_search(item, child_path)

    # Run recursive search
    recursive_search(DATA)

    # Section key fallback (lower priority)
    for key in DATA.keys():
        key_lower = key.lower()
        key_score = 0

        if query_lower == key_lower:
            key_score = 100
        elif query_lower in key_lower:
            key_score = 50
        elif key_lower in query_lower:
            key_score = 30
        else:
            for qw in query_words:
                if qw in key_lower:
                    key_score += 10

        if key_score > 0 and (key_score >= 80 or not found_items):
            found_items.append((key, DATA[key], key_score))

    # Sort and return top results
    found_items.sort(key=lambda x: (-x[2], x[0]))
    return found_items[:max_results]

def search_game(query, max_results=5):
    """Search game extracted data. Same logic as search(), different source."""
    if not GAME_DATA_LOADED or not query:
        return []

    query_lower = query.lower()
    query_norm = query_lower.replace("-", "").replace("_", "").replace(" ", "")
    query_words = [w for w in re.findall(r'\b\w+\b', query_lower) if len(w) > 2]

    found_items = []
    seen_keys = set()

    def get_item_key(item):
        """Get unique key for deduplication."""
        item_id = str(item.get("id", "")).lower()
        item_name = str(item.get("name", "")).lower()
        if not item_id and not item_name:
            return json.dumps(item, sort_keys=True, default=str)
        return (item_id, item_name)

    def score_item(item):
        """Score how well an item matches the query."""
        item_name = str(item.get("name", "")).lower()
        item_id = str(item.get("id", "")).lower()
        item_name_norm = item_name.replace("-", "").replace("_", "").replace(" ", "")
        item_id_norm = item_id.replace("-", "").replace("_", "").replace(" ", "")

        # 1. Exact normalized match
        if query_norm == item_name_norm or query_norm == item_id_norm:
            return 500

        # 2. Item name is INSIDE the query
        if len(item_name_norm) >= 3 and item_name_norm in query_norm:
            return 300
        if len(item_id_norm) >= 3 and item_id_norm in query_norm:
            return 280

        # 3. Query is inside the item name
        if len(query_norm) >= 3 and (item_name_norm and query_norm in item_name_norm):
            return 250
        if len(query_norm) >= 3 and (item_id_norm and query_norm in item_id_norm):
            return 240

        score = 0

        # 4. Word matching
        for qw in query_words:
            if qw in item_name or qw in item_id:
                score += 30

        # 5. Prerequisites matching for tech questions
        prereq_str = ""
        for field in ["prerequisites", "prereq", "requires"]:
            val = item.get(field)
            if val:
                if isinstance(val, dict):
                    prereq_str += json.dumps(val).lower()
                elif isinstance(val, list):
                    prereq_str += " ".join(str(v) for v in val).lower()
                else:
                    prereq_str += str(val).lower()

        tech_keywords = [
            'prerequisite', 'need', 'require', 'unlock', 'tree', 'research',
            'path', 'way', 'route', 'get', 'before', 'after', 'lead'
        ]
        is_tech_query = any(kw in query_lower for kw in tech_keywords)
        if is_tech_query and prereq_str:
            score += 50

        for qw in query_words:
            if qw in prereq_str:
                score += 20

        return score

    def recursive_search(data, path=""):
        """Recursively search through ALL nested structures."""
        if isinstance(data, dict):
            # Check if this dict is an item
            if "name" in data or "id" in data or "tier" in data:
                key = get_item_key(data)
                if key not in seen_keys:
                    score = score_item(data)
                    if score > 0:
                        seen_keys.add(key)
                        found_items.append((path, data, score))

            # Recurse into children (skip long text fields)
            for key, value in data.items():
                if key in ["description", "sources", "image", "icon"]:
                    continue
                child_path = f"{path}/{key}" if path else key
                recursive_search(value, child_path)

        elif isinstance(data, list):
            for i, item in enumerate(data):
                child_path = f"{path}[{i}]"
                if isinstance(item, dict):
                    if "name" in item or "id" in item or "tier" in item:
                        key = get_item_key(item)
                        if key not in seen_keys:
                            score = score_item(item)
                            if score > 0:
                                seen_keys.add(key)
                                found_items.append((child_path, item, score))
                    recursive_search(item, child_path)

    # Run recursive search - USE GAME_DATA HERE
    recursive_search(GAME_DATA)

    # Section key fallback (lower priority) - USE GAME_DATA HERE
    for key in GAME_DATA.keys():
        key_lower = key.lower()
        key_score = 0

        if query_lower == key_lower:
            key_score = 100
        elif query_lower in key_lower:
            key_score = 50
        elif key_lower in query_lower:
            key_score = 30
        else:
            for qw in query_words:
                if qw in key_lower:
                    key_score += 10

        if key_score > 0 and (key_score >= 80 or not found_items):
            found_items.append((key, GAME_DATA[key], key_score))

    # Sort and return top results
    found_items.sort(key=lambda x: (-x[2], x[0]))
    return found_items[:max_results]


    

def extract_references(item_data):
    """Extract all IDs referenced in prerequisites, requires, unlocks, etc."""
    refs = set()

    ref_fields = ["prerequisites", "prereq", "requires", "unlocks", 
                  "blocked_by", "allows", "leads_to"]

    for field in ref_fields:
        val = item_data.get(field)
        if not val:
            continue

        if isinstance(val, list):
            refs.update(str(v) for v in val)
        elif isinstance(val, dict):
            for sub_val in val.values():
                if isinstance(sub_val, list):
                    refs.update(str(v) for v in sub_val)
                else:
                    refs.add(str(sub_val))
        else:
            refs.add(str(val))

    refs = {r for r in refs if len(r) < 50 and not r.startswith('{')}
    return refs

def find_prerequisite_chain(start_item, max_depth=10, max_items=50):
    """
    Recursively find items that this item depends on.
    Returns list of (key, item_data) tuples.
    """
    if not DATA_LOADED:
        return []

    visited = set()
    found_items = []

    def is_valid_item(item):
        """Check if result is a proper item (not a section description)."""
        return "id" in item or "name" in item

    def get_refs(item):
        """Extract prerequisite IDs from item."""
        refs = set()
        for field in ["prerequisites", "prereq", "requires", "unlocks"]:
            val = item.get(field)
            if not val:
                continue
            if isinstance(val, list):
                refs.update(str(v) for v in val if len(str(v)) < 50)
            elif isinstance(val, dict):
                for sub_val in val.values():
                    if isinstance(sub_val, list):
                        refs.update(str(v) for v in sub_val if len(str(v)) < 50)
            else:
                if len(str(val)) < 50:
                    refs.add(str(val))
        return refs

    def matches_ref(ref_id, item, search_score):
        """Check if an item matches a prerequisite reference ID."""
        ref_norm = ref_id.lower().replace("_", "").replace("-", "").replace(" ", "")

        item_name = str(item.get("name", "")).lower()
        item_id = str(item.get("id", "")).lower()
        item_name_norm = item_name.replace("_", "").replace("-", "").replace(" ", "")
        item_id_norm = item_id.replace("_", "").replace("-", "").replace(" ", "")

        # 1. Perfect match (ID or Name normalized equals ref)
        if ref_norm == item_name_norm or ref_norm == item_id_norm:
            return True

        # 2. Substring match (ref inside name/id OR name/id inside ref)
        if ref_norm in item_name_norm or item_name_norm in ref_norm:
            return True
        if ref_norm in item_id_norm or item_id_norm in ref_norm:
            return True

        # 3. Word overlap (e.g., "antimatter_power" vs "Antimatter Reactors")
        #    Extract words from ref_id (handling snake_case)
        ref_words = set(re.findall(r'\w+', ref_id.lower()))
        item_words = set(re.findall(r'\w+', item_name)) | set(re.findall(r'\w+', item_id))

        # If they share a significant word (len > 3), it's likely a match
        common = ref_words & item_words
        if any(len(w) > 3 for w in common):
            return True

        # 4. High search score (trust the search engine)
        if search_score >= 100:
            return True

        return False

    def recurse(item, depth):
        if depth > max_depth or len(found_items) >= max_items:
            return

        refs = get_refs(item)

        for ref_id in refs:
            if ref_id in visited:
                continue
            visited.add(ref_id)

            ref_results = search(ref_id, max_results=3)

            for key, ref_item, score in ref_results:
                if not is_valid_item(ref_item):
                    continue

                if matches_ref(ref_id, ref_item, score):
                    found_items.append((f"prereq: {key}", ref_item))
                    recurse(ref_item, depth + 1)
                    break  # Found valid match, move to next ref

    recurse(start_item, 0)
    return found_items[:max_items]

def clean_output(text):
    return re.sub(r'<[a-z]+>.*?<[a-z]+>', '', text, flags=re.DOTALL).strip()

class MarkdownRenderer:
    """Renders markdown to tkinter Text widget with formatting"""

    def __init__(self, text_widget, colors, fonts):
        self.text = text_widget
        self.colors = colors
        self.fonts = fonts
        self._setup_tags()

    def _setup_tags(self):
        self.text.tag_configure("bold",
            font=(self.fonts["normal"]["family"], self.fonts["normal"]["size"], "bold"))

        self.text.tag_configure("italic",
            font=(self.fonts["normal"]["family"], self.fonts["normal"]["size"], "italic"))

        self.text.tag_configure("h1",
            font=(self.fonts["normal"]["family"], self.fonts["normal"]["size"] + 4, "bold"),
            foreground=self.colors["accent"])
        self.text.tag_configure("h2",
            font=(self.fonts["normal"]["family"], self.fonts["normal"]["size"] + 2, "bold"),
            foreground=self.colors["accent"])
        self.text.tag_configure("h3",
            font=(self.fonts["normal"]["family"], self.fonts["normal"]["size"], "bold"),
            foreground=self.colors["accent_secondary"])

        self.text.tag_configure("bullet", lmargin1=20, lmargin2=30)

        self.text.tag_configure("code",
            font=("Consolas", self.fonts["normal"]["size"]),
            background=self.colors["background"],
            foreground=self.colors["accent"])

        self.text.tag_configure("code_block",
            font=("Consolas", self.fonts["normal"]["size"]),
            background=self.colors["background"],
            foreground=self.colors["text"])

        self.text.tag_configure("cached", foreground=self.colors["text_dim"])

    def render(self, text, cache_hint=False):
        self.text.delete("1.0", "end")

        if cache_hint:
            self.text.insert("end", "[From cache]\n\n", "cached")

        lines = text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]

            if line.strip().startswith('```'):
                i = self._insert_code_block(lines, i)
                continue

            if line.startswith('### '):
                self._insert_header(line[4:], "h3")
                i += 1
                continue
            elif line.startswith('## '):
                self._insert_header(line[3:], "h2")
                i += 1
                continue
            elif line.startswith('# '):
                self._insert_header(line[2:], "h1")
                i += 1
                continue

            if '|' in line and i + 1 < len(lines) and '|' in lines[i + 1]:
                i = self._insert_table(lines, i)
                continue

            if line.startswith('* ') or line.startswith('- '):
                self._insert_bullet(line[2:])
                i += 1
                continue

            if re.match(r'^\d+\.\s', line):
                match = re.match(r'^(\d+)\.\s(.*)$', line)
                if match:
                    num, content = match.groups()
                    self._insert_numbered(num, content)
                    i += 1
                    continue

            self._insert_paragraph(line)
            i += 1

    def _insert_code_block(self, lines, start_idx):
        i = start_idx + 1
        code_lines = []

        while i < len(lines):
            line = lines[i]
            if line.strip() == '```' or line.strip().startswith('```'):
                break
            code_lines.append(line)
            i += 1

        if code_lines:
            self.text.insert("end", '\n')
            for code_line in code_lines:
                self.text.insert("end", code_line + '\n', "code_block")
            self.text.insert("end", '\n')

        return i + 1

    def _insert_table(self, lines, start_idx):
        rows = []
        i = start_idx

        while i < len(lines):
            line = lines[i].strip()
            if not line or '|' not in line:
                break
            if re.match(r'^[\|\-\s:]+$', line):
                i += 1
                continue

            cells = [c.strip() for c in line.split('|')]
            cells = [c for c in cells if c]

            if cells:
                rows.append(cells)
            i += 1

        if not rows:
            return start_idx + 1

        self.text.insert("end", '\n')

        num_cols = max(len(row) for row in rows)
        col_widths = [0] * num_cols
        for row in rows:
            for j, cell in enumerate(row):
                if j < len(col_widths):
                    col_widths[j] = max(col_widths[j], len(cell))

        col_widths = [max(w, 5) for w in col_widths]

        if rows:
            header = rows[0]
            for j, cell in enumerate(header):
                if j < len(col_widths):
                    padded = cell.ljust(col_widths[j])
                    self.text.insert("end", f" {padded} ", "bold")
                    if j < len(header) - 1:
                        self.text.insert("end", "│")
            self.text.insert("end", '\n')

            for j in range(len(header)):
                if j < len(col_widths):
                    self.text.insert("end", "─" * (col_widths[j] + 2))
                    if j < len(header) - 1:
                        self.text.insert("end", "┼")
            self.text.insert("end", '\n')

            for row in rows[1:]:
                for j, cell in enumerate(row):
                    if j < len(col_widths):
                        padded = cell.ljust(col_widths[j])
                        self.text.insert("end", f" {padded} ")
                        if j < len(row) - 1:
                            self.text.insert("end", "│")
                self.text.insert("end", '\n')

        self.text.insert("end", '\n')
        return i

    def _insert_header(self, text, level):
        self._insert_formatted(text + '\n', level)
        self.text.insert("end", '\n')

    def _insert_bullet(self, text):
        self.text.insert("end", '  • ', "bold")
        self._insert_formatted(text + '\n', "bullet")

    def _insert_numbered(self, num, text):
        self.text.insert("end", f'  {num}. ', "bold")
        self._insert_formatted(text + '\n', "bullet")

    def _insert_paragraph(self, text):
        if text.strip():
            self._insert_formatted(text + '\n')
        else:
            self.text.insert("end", '\n')

    def _insert_formatted(self, text, extra_tag=None):
        parts = self._parse_inline(text)

        for content, tag in parts:
            if tag:
                self.text.insert("end", content, tag)
            else:
                self.text.insert("end", content)

    def _parse_inline(self, text):
        result = []
        i = 0
        current = ""

        while i < len(text):
            if text[i:i+2] == '**':
                if current:
                    result.append((current, None))
                    current = ""

                end = text.find('**', i + 2)
                if end != -1:
                    bold_text = text[i+2:end]
                    result.append((bold_text, "bold"))
                    i = end + 2
                    continue

            elif text[i] == '*' and (i == 0 or text[i-1] != '*'):
                j = i + 1
                while j < len(text):
                    if text[j] == '*' and (j + 1 >= len(text) or text[j+1] != '*'):
                        break
                    j += 1

                if j < len(text) and text[j] == '*':
                    if current:
                        result.append((current, None))
                        current = ""
                    italic_text = text[i+1:j]
                    result.append((italic_text, "italic"))
                    i = j + 1
                    continue

            elif text[i] == '`':
                if current:
                    result.append((current, None))
                    current = ""

                end = text.find('`', i + 1)
                if end != -1:
                    code_text = text[i+1:end]
                    result.append((code_text, "code"))
                    i = end + 1
                    continue

            current += text[i]
            i += 1

        if current:
            result.append((current, None))

        return result

class StellarisApp:
    def __init__(self, root):
        self.root = root
        self.colors = THEME["colors"]
        fonts = THEME["fonts"]
        window = THEME.get("window", {})

        self.conversation_history = []
        self.last_question = ""
        self.last_matches = []
        self.has_error = False
        self.is_loading = False
        self.loading_job = None

        self.root.title(window.get("title", f"Stellaris AI Helper v{VERSION}"))
        self.root.geometry(f"{window.get('width', 950)}x{window.get('height', 850)}")
        self.root.minsize(800, 600)
        self.root.configure(bg=self.colors["background"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        icon_path = os.path.join(RESOURCE_DIR, "logo.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except:
                pass

        self.images = {}
        self.images["logo"] = load_image("logo.png", size=(120, 115))
        self.images["header"] = load_image("header.png", folder="panels")
        self.images["ask_normal"] = load_image("ask_normal", size=(50, 20), folder="buttons")
        self.images["ask_hover"] = load_image("ask_hover", size=(50, 20), folder="buttons")
        self.images["clear"] = load_image("clear", size=(25, 15), folder="buttons")

        # Save indicator state
        self.save_status_var = tk.StringVar(value="No save loaded")
        self.save_loaded = False
        self.save_loading = False
        self.pulse_job = None

        self.setup_styles(fonts)
        self.build_ui()
        self.setup_keyboard_shortcuts()
        self.restore_draft()

        self.markdown = MarkdownRenderer(self.answer_text, self.colors, fonts)
        
        # Live data manager
        self.live_data = LiveDataManager(
            status_callback=self.status_var.set,
            save_status_callback=self.update_save_status
        )

        save_dir = self.live_data.start_watching()
        if save_dir:
            self.status_var.set(f"Watching: {save_dir}")
        else:
            self.status_var.set("Ready - no save directory found")

        if not DATA_LOADED:
            messagebox.showwarning("Warning",
                "Could not find stellaris_unified_fixed.json\n\n"
                "The app will still work, but won't have game data to reference.")
        elif DATA_ISSUES:
            messagebox.showwarning("Data Warning", f"Data loaded with issues:\n{DATA_ISSUES[0]}")
    def convert_tables_to_lists(self, text):
        """Convert markdown tables to formatted bullet lists."""
        lines = text.split('\n')
        result = []
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # Detect table start
            if '|' in line and i + 1 < len(lines) and '|' in lines[i + 1]:
                table_lines = []
                while i < len(lines) and '|' in lines[i]:
                    table_lines.append(lines[i])
                    i += 1

                # Parse and convert table
                converted = self._table_to_list(table_lines)
                result.extend(converted)
            else:
                result.append(lines[i])
                i += 1

        return '\n'.join(result)

    def _table_to_list(self, table_lines):
        """Convert a markdown table to bullet list format."""
        if len(table_lines) < 2:
            return table_lines

        rows = []
        for line in table_lines:
            # Skip separator lines (|---|---|)
            if re.match(r'^[\|\-\s:]+$', line.strip()):
                continue

            cells = [c.strip() for c in line.split('|')]
            cells = [c for c in cells if c]
            if cells:
                rows.append(cells)

        if len(rows) < 1:
            return table_lines

        result = []

        # First row is header
        if len(rows) >= 1:
            header = rows[0]
            if len(header) >= 2:
                result.append(f"**{header[0]}** → **{header[1]}**" if len(header) > 1 else f"**{header[0]}**")
                result.append("")

        # Data rows as bullets
        for row in rows[1:]:
            if len(row) >= 2:
                result.append(f"  • **{row[0]}**: {row[1]}")
            elif len(row) == 1:
                result.append(f"  • {row[0]}")

        result.append("")
        return result
    
    def setup_keyboard_shortcuts(self):
        self.root.bind("<Control-Return>", lambda e: self.ask())
        self.root.bind("<Control-l>", lambda e: self.clear_all())
        self.root.bind("<Control-Shift-c>", lambda e: self.copy_answer())
        self.root.bind("<Control-h>", lambda e: self.toggle_history())
        self.root.bind("<Escape>", lambda e: self.focus_question())
        self.root.bind("<F5>", lambda e: self.retry_last())
        self.root.bind("<Control-r>", lambda e: self.retry_last())

    def focus_question(self):
        self.question_entry.delete(0, "end")
        self.question_entry.focus_set()

    def start_loading_animation(self):
        self.loading_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.loading_index = 0
        self.is_loading = True
        self.animate_loading()

    def animate_loading(self):
        if not self.is_loading:
            return
        frame = self.loading_frames[self.loading_index]
        self.answer_text.delete("1.0", "end")
        self.answer_text.insert("1.0", f"\n\n\n        {frame} Querying AI...\n\n")
        self.loading_index = (self.loading_index + 1) % len(self.loading_frames)
        self.loading_job = self.root.after(100, self.animate_loading)

    def stop_loading_animation(self):
        self.is_loading = False
        if self.loading_job:
            self.root.after_cancel(self.loading_job)
            self.loading_job = None

    def style_scrollbars(self):
        c = self.colors

        def configure_scrollbar(widget):
            try:
                widget.configure(
                    background=c["surface_light"],
                    troughcolor=c["surface"],
                    activebackground=c["accent"],
                    highlightthickness=0,
                    relief="flat"
                )
            except:
                pass
            for child in widget.winfo_children():
                configure_scrollbar(child)

        configure_scrollbar(self.root)

    def setup_styles(self, fonts):
        style = ttk.Style()
        style.theme_use('clam')
        c = self.colors

        style.configure("Main.TFrame", background=c["background"])
        style.configure("Surface.TFrame", background=c["surface"])
        style.configure("Title.TLabel",
            background=c["background"],
            foreground=c["accent"],
            font=(fonts["title"]["family"], fonts["title"]["size"],
                  fonts["title"].get("weight", "bold")))
        style.configure("Section.TLabel",
            background=c["background"],
            foreground=c["accent"],
            font=(fonts["section"]["family"], fonts["section"]["size"],
                  fonts["section"].get("weight", "bold")))
        style.configure("TLabel",
            background=c["background"],
            foreground=c["text"],
            font=(fonts["normal"]["family"], fonts["normal"]["size"]))
        style.configure("Subtle.TLabel",
            background=c["background"],
            foreground=c["text_dim"],
            font=(fonts["normal"]["family"], fonts["normal"]["size"]))

        button_blue = c.get("button_blue", "#1e40af")
        button_blue_hover = c.get("button_blue_hover", "#2563eb")
        button_blue_active = c.get("button_blue_active", "#1d4ed8")

        style.configure("Blue.TButton",
            font=(fonts["normal"]["family"], fonts["normal"]["size"]),
            padding=(12, 6),
            background=button_blue,
            foreground="white",
            borderwidth=0,
            focuscolor="none")
        style.map("Blue.TButton",
            background=[("active", button_blue_active), 
                       ("!active", button_blue),
                       ("hover", button_blue_hover)],
            foreground=[("active", "white"), ("!active", "white")])

        style.configure("Flat.TButton",
            font=(fonts["normal"]["family"], fonts["normal"]["size"]),
            padding=(8, 4),
            background=c["background"],
            foreground=c["accent"],
            borderwidth=0,
            focuscolor="none")
        style.map("Flat.TButton",
            background=[("active", c["surface"]), ("!active", c["background"])],
            foreground=[("active", c["accent_hover"]), ("!active", c["accent"])])

        style.configure("TButton",
            font=(fonts["normal"]["family"], fonts["normal"]["size"]), padding=8)
        style.configure("Accent.TButton",
            background=c["accent"],
            foreground=c["background"])
        style.map("Accent.TButton",
            background=[("active", c["accent_hover"]), ("!active", c["accent"])])
        style.configure("TEntry",
            fieldbackground=c["surface"],
            foreground=c["text"])
        style.configure("TCheckbutton",
            background=c["background"],
            foreground=c["text"])

        style.configure("Card.TLabelframe",
            background=c["surface"],
            bordercolor=c["surface_light"],
            relief="flat",
            borderwidth=1)
        style.configure("Card.TLabelframe.Label",
            background=c["surface"],
            foreground=c["accent"],
            font=(fonts["section"]["family"], fonts["section"]["size"],
                  fonts["section"].get("weight", "bold")))

        style.configure("Error.TLabel",
            background=c["background"],
            foreground=c["error"],
            font=(fonts["normal"]["family"], fonts["normal"]["size"]))

    def build_ui(self):
        main = ttk.Frame(self.root, style="Main.TFrame")
        main.pack(fill="both", expand=True, padx=5, pady=15)

        self.build_header(main)
        self.build_settings(main)
        self.build_question_area(main)
        self.build_answer_area(main)
        self.build_history_panel(main)
        self.build_status_bar(main)
        self.style_scrollbars()

    def build_header(self, parent):
        c = self.colors
        header = ttk.Frame(parent, style="Main.TFrame")
        header.pack(fill="x", pady=(0, 10))

        if self.images.get("logo"):
            logo_label = tk.Label(header, image=self.images["logo"],
                bg=c["background"], borderwidth=0)
            logo_label.pack(side="left", padx=0)
        elif self.images.get("header"):
            header_label = tk.Label(header, image=self.images["header"],
                bg=c["background"], borderwidth=0)
            header_label.pack(side="left")
        else:
            ttk.Label(header, text=f"Stellaris AI Helper v{VERSION}",
                style="Title.TLabel").pack(side="left")

        # Right side info frame
        info_frame = ttk.Frame(header, style="Main.TFrame")
        info_frame.pack(side="right")

        # Data sections info
        info_text = f"{len(DATA)} sections loaded" if DATA_LOADED else "No data"
        ttk.Label(info_frame, text=info_text, style="Subtle.TLabel").pack(side="left")

        if DATA_LOADED and CONFIG.get("cache_enabled", True):
            cache_count = len(RESPONSE_CACHE)
            if cache_count > 0:
                ttk.Label(info_frame, text=f" | {cache_count} cached",
                    style="Subtle.TLabel").pack(side="left", padx=(5, 0))

        # Save indicator (new line below data info)
        save_frame = ttk.Frame(info_frame, style="Main.TFrame")
        save_frame.pack(side="left", padx=(15, 0))

        # Status dot canvas
        self.save_dot = tk.Canvas(save_frame, width=12, height=12,
            bg=c["background"], highlightthickness=0)
        self.save_dot.pack(side="left", padx=(0, 5))
        self.update_save_dot("inactive")

        # Save status label
        self.save_label = ttk.Label(save_frame, textvariable=self.save_status_var,
            style="Subtle.TLabel")
        self.save_label.pack(side="left")

        # Manual scan button 
        scan_btn = ttk.Button(save_frame, text="🔄", width=3,
            command=self.manual_scan, style="Flat.TButton")
        scan_btn.pack(side="left", padx=(5, 0))

    def build_settings(self, parent):
        c = self.colors

        toggle_frame = ttk.Frame(parent, style="Main.TFrame")
        toggle_frame.pack(fill="x", pady=(0, 5))

        self.settings_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(toggle_frame, text="⚙ Settings",
            variable=self.settings_visible,
            command=self.toggle_settings,
            style="Section.TLabel").pack(side="left")

        self.settings_frame = ttk.LabelFrame(parent, text="API Configuration",
            style="Card.TLabelframe", padding=10)

        entry_font = (THEME["fonts"]["entry"]["family"], THEME["fonts"]["entry"]["size"])

        row1 = ttk.Frame(self.settings_frame, style="Surface.TFrame")
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="API Key:", width=12, style="TLabel").pack(side="left")
        self.api_key_var = tk.StringVar(value=CONFIG.get("api_key", ""))
        self.api_key_entry = tk.Entry(row1,
            textvariable=self.api_key_var,
            show="*",
            font=entry_font,
            bg=c["surface"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=c["surface_light"],
            highlightcolor=c["accent"])
        self.api_key_entry.pack(side="left", padx=(5, 0), fill="x", expand=True, ipady=4)

        self.show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="Show", variable=self.show_key,
            command=self.toggle_key_visibility).pack(side="left", padx=(10, 0))

        row2 = ttk.Frame(self.settings_frame, style="Surface.TFrame")
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="API URL:", width=12, style="TLabel").pack(side="left")
        self.api_url_var = tk.StringVar(value=CONFIG.get("api_url", ""))
        tk.Entry(row2,
            textvariable=self.api_url_var,
            font=entry_font,
            bg=c["surface"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=c["surface_light"],
            highlightcolor=c["accent"]).pack(side="left", padx=(5, 0), fill="x", expand=True, ipady=4)

        row3 = ttk.Frame(self.settings_frame, style="Surface.TFrame")
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="Model:", width=12, style="TLabel").pack(side="left")
        self.model_var = tk.StringVar(value=CONFIG.get("model", ""))
        tk.Entry(row3,
            textvariable=self.model_var,
            font=entry_font,
            bg=c["surface"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=c["surface_light"],
            highlightcolor=c["accent"]).pack(side="left", padx=(5, 0), fill="x", expand=True, ipady=4)

        row_temp = ttk.Frame(self.settings_frame, style="Surface.TFrame")
        row_temp.pack(fill="x", pady=2)
        ttk.Label(row_temp, text="Temperature:", width=12, style="TLabel").pack(side="left")
        self.temperature_var = tk.StringVar(value=str(CONFIG.get("temperature", 0.4)))
        tk.Entry(row_temp,
            textvariable=self.temperature_var,
            width=8,
            font=entry_font,
            bg=c["surface"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=c["surface_light"],
            highlightcolor=c["accent"]).pack(side="left", padx=(5, 10), ipady=4)
        ttk.Label(row_temp, text="(0.0-2.0, lower = more focused)",
            style="Subtle.TLabel").pack(side="left")

        row_tokens = ttk.Frame(self.settings_frame, style="Surface.TFrame")
        row_tokens.pack(fill="x", pady=2)
        ttk.Label(row_tokens, text="Max Tokens:", width=12, style="TLabel").pack(side="left")
        self.max_tokens_var = tk.StringVar(value=str(CONFIG.get("max_tokens", 2500)))
        tk.Entry(row_tokens,
            textvariable=self.max_tokens_var,
            width=8,
            font=entry_font,
            bg=c["surface"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=c["surface_light"],
            highlightcolor=c["accent"]).pack(side="left", padx=(5, 10), ipady=4)
        ttk.Label(row_tokens, text="(1-8000, response length limit)",
            style="Subtle.TLabel").pack(side="left")

        row4 = ttk.Frame(self.settings_frame, style="Surface.TFrame")
        row4.pack(fill="x", pady=(10, 0))
        ttk.Label(row4, text="Options:", width=12, style="TLabel").pack(side="left")

        self.cache_enabled = tk.BooleanVar(value=CONFIG.get("cache_enabled", True))
        ttk.Checkbutton(row4, text="Enable caching",
            variable=self.cache_enabled).pack(side="left", padx=(0, 15))

        ttk.Label(row4, text="Rate limit (sec):", style="TLabel").pack(side="left", padx=(15, 0))
        self.rate_limit_var = tk.StringVar(value=str(CONFIG.get("rate_limit_seconds", 2)))
        tk.Entry(row4,
            textvariable=self.rate_limit_var,
            width=5,
            font=entry_font,
            bg=c["surface"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=c["surface_light"],
            highlightcolor=c["accent"]).pack(side="left", padx=(5, 0), ipady=4)

        row5 = ttk.Frame(self.settings_frame, style="Surface.TFrame")
        row5.pack(fill="x", pady=(10, 0))
        ttk.Label(row5, text="Presets:", width=12, style="TLabel").pack(side="left")

        ttk.Button(row5, text="Nano-GPT",
            command=lambda: self.apply_preset("nano"),
            style="Flat.TButton").pack(side="left", padx=2)
        ttk.Button(row5, text="OpenAI",
            command=lambda: self.apply_preset("openai"),
            style="Flat.TButton").pack(side="left", padx=2)
        ttk.Button(row5, text="Custom",
            command=lambda: self.apply_preset("custom"),
            style="Flat.TButton").pack(side="left", padx=2)

        ttk.Button(row5, text="Clear Cache",
            command=self.clear_cache,
            style="Blue.TButton").pack(side="left", padx=(20, 2))
        ttk.Button(row5, text="Save",
            command=self.save_settings,
            style="Blue.TButton").pack(side="right", padx=2)

    def build_question_area(self, parent):
        c = self.colors
        q_frame = ttk.Frame(parent, style="Main.TFrame")
        q_frame.pack(fill="x", pady=(10, 5))

        label_row = ttk.Frame(q_frame, style="Main.TFrame")
        label_row.pack(fill="x")
        ttk.Label(label_row, text="Question:", style="Section.TLabel").pack(side="left")

        self.token_label = ttk.Label(label_row, text="", style="Subtle.TLabel")
        self.token_label.pack(side="right")

        self.question_entry = tk.Entry(q_frame,
            font=(THEME["fonts"]["entry"]["family"], THEME["fonts"]["entry"]["size"]),
            bg=c["surface"], fg=c["text"], insertbackground=c["text"],
            relief="flat", highlightthickness=1,
            highlightbackground=c["surface_light"],
            highlightcolor=c["accent"])
        self.question_entry.pack(fill="x", pady=(5, 0), ipady=8)
        self.question_entry.bind("<Return>", lambda e: self.ask())
        self.question_entry.bind("<KeyRelease>", self.update_token_estimate)

        conv_row = ttk.Frame(q_frame, style="Main.TFrame")
        conv_row.pack(fill="x", pady=(5, 0))

        self.conversation_mode = tk.BooleanVar(
            value=CONFIG.get("conversation_mode", False))
        ttk.Checkbutton(conv_row,
            text="Conversation mode (AI remembers context)",
            variable=self.conversation_mode,
            style="TCheckbutton").pack(side="left")

        self.deep_search_mode = tk.BooleanVar(
            value=CONFIG.get("deep_search_mode", False))
        ttk.Checkbutton(conv_row,
            text="Include prerequisites (finds related tech tree)",
            variable=self.deep_search_mode,
            style="TCheckbutton").pack(side="left", padx=(20, 0))
        
        # NEW: Live game data toggle
        self.live_data_mode = tk.BooleanVar(
            value=CONFIG.get("live_data_mode", False))
        ttk.Checkbutton(conv_row,
            text="Live game data (from saves)",
            variable=self.live_data_mode,
            style="TCheckbutton").pack(side="left", padx=(20, 0))
        
        self.game_data_mode = tk.BooleanVar(
            value=CONFIG.get("game_data_mode", True))
        ttk.Checkbutton(conv_row,
            text="Game extracted data",
            variable=self.game_data_mode,
            style="TCheckbutton").pack(side="left", padx=(20, 0))

        self.context_label = ttk.Label(conv_row, text="", style="Subtle.TLabel")
        self.context_label.pack(side="right")

        btn_row = ttk.Frame(q_frame, style="Main.TFrame")
        btn_row.pack(fill="x", pady=(10, 0))

        ask_container = ttk.Frame(btn_row, style="Main.TFrame")
        ask_container.pack(side="left", anchor="w")

        if self.images.get("ask_normal"):
            self.ask_btn = tk.Button(ask_container,
                image=self.images["ask_normal"],
                borderwidth=0,
                bg=c["background"],
                activebackground=c["background"],
                command=self.ask)
            self.ask_btn.pack(side="left", padx=(0, 5), anchor="center")

            if self.images.get("ask_hover"):
                self.ask_btn.bind("<Enter>",
                    lambda e: self.ask_btn.configure(image=self.images["ask_hover"]))
                self.ask_btn.bind("<Leave>",
                    lambda e: self.ask_btn.configure(image=self.images["ask_normal"]))
        else:
            self.ask_btn = ttk.Button(ask_container, text="Ask",
                command=self.ask, style="Accent.TButton")
            self.ask_btn.pack(side="left", padx=(0, 8))

        self.retry_btn = ttk.Button(ask_container, text="Retry",
            command=self.retry_last, style="Flat.TButton")

        ttk.Label(ask_container, text="Enter to submit | Ctrl+Enter to force",
            style="Subtle.TLabel").pack(side="left", padx=(10, 0), anchor="center")

    def build_answer_area(self, parent):
        c = self.colors

        label_row = ttk.Frame(parent, style="Main.TFrame")
        label_row.pack(fill="x", pady=(15, 5))
        ttk.Label(label_row, text="Response:", style="Section.TLabel").pack(side="left")

        clear_container = ttk.Frame(label_row, style="Main.TFrame")
        clear_container.pack(side="right", anchor="e")

        ttk.Label(clear_container, text="Clear:",
            style="Subtle.TLabel").pack(side="left", padx=(0, 3), anchor="center")

        if self.images.get("clear"):
            clear_btn = tk.Button(clear_container,
                image=self.images["clear"],
                borderwidth=0,
                bg=c["background"],
                activebackground=c["background"],
                command=self.clear_answer)
            clear_btn.pack(side="left", anchor="center")
        else:
            ttk.Button(clear_container, text="Clear",
                command=self.clear_answer).pack(side="left")

        text_frame = tk.Frame(parent, bg=c["surface"],
            highlightthickness=1,
            highlightbackground=c["surface_light"])
        text_frame.pack(fill="both", expand=True, pady=(5, 0))

        style = ttk.Style()
        style.configure("Custom.Vertical.TScrollbar",
            background=c["surface_light"],
            troughcolor=c["surface"],
            arrowcolor=c["text"],
            gripcount=0,
            borderwidth=0,
            relief="flat")
        style.map("Custom.Vertical.TScrollbar",
            background=[("active", c["accent"])],
            arrowcolor=[("active", c["accent"])])

        scrollbar = ttk.Scrollbar(text_frame, orient="vertical",
            style="Custom.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")

        self.answer_text = tk.Text(text_frame,
            wrap="word",
            bg=c["surface"],
            fg=c["text"],
            insertbackground=c["text"],
            font=(THEME["fonts"]["normal"]["family"], THEME["fonts"]["normal"]["size"]),
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=10,
            yscrollcommand=scrollbar.set,
            selectbackground=c["accent"],
            inactiveselectbackground=c["surface_light"],
            height=8)
        self.answer_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.answer_text.yview)

        btn_row = ttk.Frame(parent, style="Main.TFrame")
        btn_row.pack(fill="x", pady=(10, 0))

        ttk.Button(btn_row, text="Copy Answer",
            command=self.copy_answer,
            style="Blue.TButton").pack(side="left")
        ttk.Button(btn_row, text="Clear All",
            command=self.clear_all,
            style="Blue.TButton").pack(side="left", padx=(5, 0))

    def build_history_panel(self, parent):
        c = self.colors

        toggle_frame = ttk.Frame(parent, style="Main.TFrame")
        toggle_frame.pack(fill="x", pady=(10, 5))

        self.history_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(toggle_frame, text="📜 History (click to expand)",
            variable=self.history_visible,
            command=self.toggle_history,
            style="Section.TLabel").pack(side="left")

        self.history_frame = ttk.LabelFrame(parent, text="Conversation History",
            style="Card.TLabelframe", padding=10)

        history_container = tk.Frame(self.history_frame, bg=c["surface"],
            highlightthickness=1,
            highlightbackground=c["surface_light"])
        history_container.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(history_container, orient="vertical",
            style="Custom.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")

        self.history_text = tk.Text(history_container,
            wrap="word",
            bg=c["surface"],
            fg=c["text"],
            insertbackground=c["text"],
            font=(THEME["fonts"]["normal"]["family"], THEME["fonts"]["normal"]["size"]),
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=10,
            yscrollcommand=scrollbar.set,
            selectbackground=c["accent"],
            inactiveselectbackground=c["surface_light"],
            state="disabled")
        self.history_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.history_text.yview)

        btn_row = ttk.Frame(self.history_frame, style="Main.TFrame")
        btn_row.pack(fill="x", pady=(10, 0))

        ttk.Button(btn_row, text="Copy History",
            command=self.copy_history,
            style="Blue.TButton").pack(side="left")
        ttk.Button(btn_row, text="Clear History",
            command=self.clear_history,
            style="Blue.TButton").pack(side="left", padx=(5, 0))

        self.history_info_label = ttk.Label(btn_row, text="", style="Subtle.TLabel")
        self.history_info_label.pack(side="right")

    def build_status_bar(self, parent):
        status_frame = ttk.Frame(parent, style="Main.TFrame")
        status_frame.pack(fill="x", pady=(15, 0))

        self.status_var = tk.StringVar(value="Ready - ask a question about Stellaris")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var,
            style="Subtle.TLabel")
        self.status_label.pack(side="left")

        ttk.Button(status_frame, text="About",
            command=self.show_about,
            style="Flat.TButton").pack(side="right")
        
    def update_save_dot(self, status):
        """Update the save indicator dot color. status: 'inactive' (gray), 'loading' (orange pulse), 'active' (green)"""
        c = self.colors
        self.save_dot.delete("all")

        if status == "inactive":
            # Gray dot - no save
            self.save_dot.create_oval(2, 2, 10, 10, fill="#666666", outline="#555555")
            self.save_dot.tooltip_text = "No save loaded"
        elif status == "loading":
            # Orange dot - loading
            self.save_dot.create_oval(2, 2, 10, 10, fill="#f39c12", outline="#e67e22")
            self.save_dot.tooltip_text = "Loading save..."
        elif status == "active":
            # Green dot - save loaded
            self.save_dot.create_oval(2, 2, 10, 10, fill="#27ae60", outline="#1e8449")
            self.save_dot.tooltip_text = "Save loaded"
        elif status == "error":
            # Red dot - error
            self.save_dot.create_oval(2, 2, 10, 10, fill="#e94560", outline="#c0392b")
            self.save_dot.tooltip_text = "Error loading save"

    def start_save_pulse(self):
        """Start pulsing animation for loading state."""
        self.stop_save_pulse()
        self.save_loading = True
        self.pulse_frame = 0
        self.pulse_colors = ["#f39c12", "#e67e22", "#d68910", "#e67e22"]  # Orange pulse
        self._animate_pulse()

    def _animate_pulse(self):
        """Internal pulse animation loop."""
        if not self.save_loading:
            return

        color = self.pulse_colors[self.pulse_frame]
        self.save_dot.delete("all")
        self.save_dot.create_oval(2, 2, 10, 10, fill=color, outline=color)

        self.pulse_frame = (self.pulse_frame + 1) % len(self.pulse_colors)
        self.pulse_job = self.root.after(300, self._animate_pulse)

    def stop_save_pulse(self):
        """Stop pulsing animation."""
        self.save_loading = False
        if self.pulse_job:
            self.root.after_cancel(self.pulse_job)
            self.pulse_job = None

    def update_save_status(self, status, save_name=None, timestamp=None):
        """Update save indicator status.

        status: 'none', 'loading', 'loaded', 'error'
        """
        self.stop_save_pulse()

        if status == "none":
            self.save_loaded = False
            self.update_save_dot("inactive")
            self.save_status_var.set("No save loaded")
        elif status == "loading":
            self.update_save_dot("loading")
            self.start_save_pulse()
            self.save_status_var.set("Loading save...")
        elif status == "loaded":
            self.save_loaded = True
            self.update_save_dot("active")
            if save_name and timestamp:
                self.save_status_var.set(f"{save_name} ({timestamp})")
            elif save_name:
                self.save_status_var.set(save_name)
            else:
                self.save_status_var.set("Save loaded")
        elif status == "error":
            self.save_loaded = False
            self.update_save_dot("error")
            self.save_status_var.set("Save error")

    def manual_scan(self):
        """Manually trigger a save scan and load latest."""
        print("\n=== MANUAL SCAN TRIGGERED ===")

        if not self.live_data.watcher:
            print("No watcher instance!")
            self.status_var.set("No watcher initialized")
            return

        save_dir = self.live_data.watcher.save_dir
        print(f"Save directory: {save_dir}")

        if not save_dir:
            print("Save directory not found!")
            self.status_var.set("Save directory not found - check console")
            messagebox.showwarning("Save Directory", 
                "Could not find Stellaris save directory.\n\n"
                "Expected location:\n"
                "Documents/Paradox Interactive/Stellaris/save games")
            return

        # List all saves in directory
        print(f"\nListing all .sav files in: {save_dir}")
        save_count = 0
        ironman_count = 0
        saves_list = []

        for root, dirs, files in os.walk(save_dir):
            empire_name = os.path.basename(root) if root != save_dir else "Root"

            for f in files:
                if f.endswith('.sav'):
                    save_count += 1
                    path = os.path.join(root, f)
                    size = os.path.getsize(path)
                    mtime = os.path.getmtime(path)
                    mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', 
                                              time.localtime(mtime))

                    is_ironman = self.is_ironman_save(path)
                    if is_ironman:
                        ironman_count += 1

                    saves_list.append({
                        'name': f,
                        'path': path,
                        'empire': empire_name,
                        'size': size,
                        'mtime': mtime,
                        'mtime_str': mtime_str,
                        'ironman': is_ironman
                    })

                    print(f"  [{empire_name}] {f}")
                    print(f"    Size: {size:,} bytes")
                    print(f"    Modified: {mtime_str}")
                    print(f"    Ironman: {is_ironman}")

        print(f"\nTotal saves found: {save_count}")
        print(f"  Ironman: {ironman_count}")
        print(f"  Normal: {save_count - ironman_count}")

        if save_count == 0:
            self.status_var.set("No .sav files found")
            messagebox.showinfo("No Saves", 
                "No save files found.\n\n"
                "Make sure you have saved a game in Stellaris.")
            return

        # Find latest NON-IRONMAN save
        normal_saves = [s for s in saves_list if not s['ironman']]

        if not normal_saves:
            self.status_var.set("Only Ironman saves found (encrypted)")
            messagebox.showwarning("Ironman Saves", 
                f"Found {save_count} saves, but all are Ironman.\n\n"
                "Ironman saves are encrypted and cannot be read.\n"
                "Please create a non-Ironman save to use live data.")
            return

        # Sort by mtime, get latest
        latest = max(normal_saves, key=lambda s: s['mtime'])
        print(f"\nLatest normal save: {latest['name']}")
        print(f"  Empire: {latest['empire']}")
        print(f"  Path: {latest['path']}")

        # Update watcher state
        self.live_data.watcher.last_mtime = latest['mtime']
        self.live_data.watcher.last_file = latest['path']

        # Load it!
        print(f"\n>>> LOADING SAVE <<<")
        self.live_data.on_save_detected(latest['path'])

        self.status_var.set(f"Loaded: {latest['name']}")

    def is_ironman_save(self, file_path):
        """Check if save is Ironman (encrypted)."""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(4)
                return header[:2] != b'PK'
        except:
            return True    

    # --- UI Actions ---

    def toggle_history(self):
        if self.history_visible.get():
            self.history_frame.pack(fill="both", expand=True, pady=(0, 10))
            self.update_history_info()
        else:
            self.history_frame.pack_forget()

    def toggle_settings(self):
        if self.settings_visible.get():
            self.settings_frame.pack(fill="x", pady=(0, 10),
                before=self.question_entry.master)
        else:
            self.settings_frame.pack_forget()

    def toggle_key_visibility(self):
        if self.show_key.get():
            self.api_key_entry.configure(show="")
        else:
            self.api_key_entry.configure(show="*")

    def apply_preset(self, preset):
        presets = {
            "nano": {
                "api_url": "https://nano-gpt.com/api/v1/chat/completions",
                "model": "zai-org/glm-5:thinking",
                "temperature": 0.4,
                "max_tokens": 2500
            },
            "openai": {
                "api_url": "https://api.openai.com/v1/chat/completions",
                "model": "gpt-4",
                "temperature": 0.7,
                "max_tokens": 3000
            },
            "custom": {
                "api_url": self.api_url_var.get(),
                "model": self.model_var.get(),
                "temperature": float(self.temperature_var.get() or 0.4),
                "max_tokens": int(self.max_tokens_var.get() or 2500)
            }
        }
        if preset in presets and preset != "custom":
            p = presets[preset]
            self.api_url_var.set(p["api_url"])
            self.model_var.set(p["model"])
            self.temperature_var.set(str(p["temperature"]))
            self.max_tokens_var.set(str(p["max_tokens"]))
            self.status_var.set(f"Applied {preset} preset")
        elif preset == "custom":
            self.status_var.set("Custom preset uses current values")

    def save_settings(self):
        try:
            rate_limit = int(self.rate_limit_var.get())
            if rate_limit < 0:
                rate_limit = 0
        except ValueError:
            rate_limit = 2

        try:
            temperature = float(self.temperature_var.get())
            temperature = max(0.0, min(2.0, temperature))
        except ValueError:
            temperature = 0.4

        try:
            max_tokens = int(self.max_tokens_var.get())
            max_tokens = max(1, min(8000, max_tokens))
        except ValueError:
            max_tokens = 2500

        config = {
            "api_key": self.api_key_var.get(),
            "api_url": self.api_url_var.get(),
            "model": self.model_var.get(),
            "conversation_mode": self.conversation_mode.get(),
            "cache_enabled": self.cache_enabled.get(),
            "rate_limit_seconds": rate_limit,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "deep_search_mode": self.deep_search_mode.get(),
            "live_data_mode": self.live_data_mode.get()
        }
        save_config(config)

        global MIN_REQUEST_INTERVAL
        MIN_REQUEST_INTERVAL = rate_limit

        self.status_var.set(f"Settings saved! (temp={temperature}, tokens={max_tokens})")

    def clear_cache(self):
        global RESPONSE_CACHE
        RESPONSE_CACHE = {}
        try:
            if os.path.exists(CACHE_FILE):
                os.remove(CACHE_FILE)
        except:
            pass
        self.status_var.set("Cache cleared")

    def update_token_estimate(self, event=None):
        question = self.question_entry.get()
        if question:
            tokens = estimate_tokens(question)
            self.token_label.config(text=f"~{tokens} tokens")
        else:
            self.token_label.config(text="")

    def restore_draft(self):
        draft = load_draft()
        if draft:
            self.question_entry.insert(0, draft)
            self.update_token_estimate()

    def clear_answer(self):
        self.answer_text.delete("1.0", "end")
        self.has_error = False
        self.hide_retry_button()

    def clear_history(self):
        self.history_text.config(state="normal")
        self.history_text.delete("1.0", "end")
        self.history_text.config(state="disabled")
        self.conversation_history = []
        self.update_context_label()
        self.update_history_info()
        self.status_var.set("History cleared")

    def clear_all(self):
        self.question_entry.delete(0, "end")
        self.answer_text.delete("1.0", "end")
        self.clear_history()
        self.has_error = False
        self.hide_retry_button()
        clear_draft()
        self.status_var.set("Ready - all cleared")
        self.token_label.config(text="")

    def copy_answer(self):
        text = self.answer_text.get("1.0", "end").strip()
        if text.startswith("[From cache]"):
            text = text.replace("[From cache]\n\n", "", 1)
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("Copied to clipboard")
        else:
            self.status_var.set("Nothing to copy")

    def copy_history(self):
        text = self.history_text.get("1.0", "end").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("History copied to clipboard")
        else:
            self.status_var.set("No history to copy")

    def show_about(self):
        about_text = f"""Stellaris AI Helper v{VERSION}

A tool to query Stellaris game data with AI assistance.

Features:
• AI-powered Q&A about Stellaris
• Markdown formatting in responses
• Table rendering
• Conversation mode for context
• Deep search for prerequisite chains
• Response caching
• Works even without data match

Data file: stellaris_unified_fixed.json
Loaded: {len(DATA)} sections
Cache: {len(RESPONSE_CACHE)} responses

Keyboard shortcuts:
• Enter: Submit question
• Ctrl+Enter: Force submit
• F5 or Ctrl+R: Retry last question
• Ctrl+L: Clear all
• Ctrl+Shift+C: Copy answer
• Ctrl+H: Toggle history
• Escape: Clear question"""
        messagebox.showinfo("About", about_text)

    def show_retry_button(self):
        self.retry_btn.pack(side="left", padx=(10, 0))

    def hide_retry_button(self):
        self.retry_btn.pack_forget()

    def update_context_label(self):
        if self.conversation_mode.get():
            msg_count = len(self.conversation_history) // 2
            if msg_count > 0:
                self.context_label.config(text=f"Context: {msg_count} exchange(s)")
            else:
                self.context_label.config(text="Context: New conversation")
        else:
            self.context_label.config(text="")

    def update_history_info(self):
        if self.history_visible.get():
            count = len(self.conversation_history) // 2
            self.history_info_label.config(text=f"{count} Q&A pair(s)")

    def add_to_history(self, question, answer, matches, has_data):
        timestamp = datetime.now().strftime("%H:%M:%S")

        entry = f"\n{'─' * 50}\n[{timestamp}]"
        if not has_data:
            entry += " (no game data)"
        entry += f"\nQ: {question}\n\n"
        entry += f"A: {answer}\n"
        if matches:
            # matches is a list of (key, data, score) tuples
            match_names = []
            for m in matches:
                if isinstance(m, tuple) and len(m) >= 2:
                    item = m[1]
                    name = item.get("name", item.get("id", m[0]))
                    match_names.append(str(name))
                else:
                    match_names.append(str(m))
            entry += f"\n(Sections: {', '.join(match_names)})\n"
        entry += f"{'─' * 50}\n"

        self.history_text.config(state="normal")
        self.history_text.insert("end", entry)
        self.history_text.see("end")
        self.history_text.config(state="disabled")

        self.update_history_info()

    # --- Main Actions ---

    def ask(self):
        global LAST_REQUEST_TIME

        question = self.question_entry.get().strip()
        if not question:
            self.status_var.set("Please enter a question")
            return

        elapsed = time.time() - LAST_REQUEST_TIME
        if elapsed < MIN_REQUEST_INTERVAL:
            wait_time = int(MIN_REQUEST_INTERVAL - elapsed) + 1
            self.status_var.set(f"Rate limit - wait {wait_time}s...")
            self.root.after(wait_time * 1000, self.ask)
            return

        LAST_REQUEST_TIME = time.time()

        CONFIG["api_key"] = self.api_key_var.get()
        CONFIG["api_url"] = self.api_url_var.get()
        CONFIG["model"] = self.model_var.get()
        CONFIG["cache_enabled"] = self.cache_enabled.get()
        CONFIG["deep_search_mode"] = self.deep_search_mode.get()

        try:
            CONFIG["temperature"] = float(self.temperature_var.get())
            CONFIG["temperature"] = max(0.0, min(2.0, CONFIG["temperature"]))
        except ValueError:
            CONFIG["temperature"] = 0.4

        try:
            CONFIG["max_tokens"] = int(self.max_tokens_var.get())
            CONFIG["max_tokens"] = max(1, min(8000, CONFIG["max_tokens"]))
        except ValueError:
            CONFIG["max_tokens"] = 2500

        if not CONFIG["api_key"]:
            messagebox.showwarning("Missing API Key",
                "Please enter your API key in Settings.")
            return

        save_draft(question)

        self.answer_text.delete("1.0", "end")
        self.has_error = False
        self.hide_retry_button()

        self.status_var.set("Querying API...")
        self.start_loading_animation()

        try:
            self.ask_btn.configure(state="disabled")
        except:
            pass

        self.last_question = question

        threading.Thread(target=self._ask_thread, args=(question,),
            daemon=True).start()

    def _ask_thread(self, question):
        try:
            matches = []
            has_game_data = False

            # Search wiki data (existing)
            if DATA_LOADED:
                wiki_matches = search(question)
                for m in wiki_matches:
                    # Add source tag to each match
                    matches.append((m[0], m[1], m[2], "wiki"))
                if wiki_matches:
                    has_game_data = True

            # Search game data (new, if enabled)
            if GAME_DATA_LOADED and self.game_data_mode.get():
                game_matches = search_game(question)  # Same logic, different data
                for m in game_matches:
                    matches.append((m[0], m[1], m[2], "game"))
                if game_matches:
                    has_game_data = True

            print(f"\n=== SEARCH DEBUG ===")
            print(f"Query: {question}")
            print(f"Found {len(matches)} matches:")
            for key, data, score, source in matches:
                name = data.get("name", data.get("id", "???"))
                has_id = "id" in data
                print(f"  - {name} (score: {score}, has id: {has_id})")
            print("===================\n")

            context = ""
            total_tokens = 0
            all_items = []

            if has_game_data:
                for key, value, score, source in matches:
                    all_items.append((key, value, False, source))

                # Deep search: Find prerequisite chain
                if self.deep_search_mode.get() and matches:
                    # Find the BEST starting point for the tree
                    # Usually the item with the highest Tier or Cost (the final goal)
                    best_item = None
                    best_item_name = None
                    best_priority = -1

                    for key, data, score, source in matches:
                        if not isinstance(data, dict):
                            continue

                        # Must be a real game item
                        is_game_item = (
                            "tier" in data or 
                            "cost" in data or 
                            "prerequisites" in data or 
                            "id" in data
                        )

                        if not is_game_item:
                            continue

                        name = data.get("name", data.get("id", key))
                        if len(str(name)) <= 2:
                            continue

                        # Calculate priority: Higher tier/cost = better starting point
                        try:
                            tier = int(data.get("tier", 0))
                        except:
                            tier = 0
                        try:
                            cost = int(data.get("cost", 0))
                        except:
                            cost = 0

                        priority = tier * 10000 + cost

                        if priority > best_priority:
                            best_priority = priority
                            best_item = data
                            best_item_name = name

                    if best_item:
                        print(f"\n=== DEEP SEARCH DEBUG ===")
                        print(f"Starting from: {best_item_name} (priority: {best_priority})")

                        prereq_items = find_prerequisite_chain(best_item)

                        print(f"Found {len(prereq_items)} prerequisite items:")
                        for key, item in prereq_items:
                            name = item.get("name", item.get("id", "???"))
                            prereq = item.get("prerequisites", item.get("prereq", []))
                            print(f"  - {name} (prereqs: {prereq})")
                        print("========================\n")

                        for key, item in prereq_items:
                            if not any(ai[0] == key for ai in all_items):
                                all_items.append((key, item, True, "game"))
                    else:
                        print("Deep search: No valid item found to start from!")

                parts = []
                for key, value, is_prereq, source in all_items:
                    text = json.dumps(value, indent=2, ensure_ascii=False)
                    if len(text) > 2500:
                        text = text[:2500] + "\n...[truncated]"

                    source_label = "WIKI" if source == "wiki" else "GAME"
                    prereq_label = "PREREQUISITE: " if is_prereq else ""
                    parts.append(f"=== [{source_label}] {prereq_label}{key.upper()} ===\n{text}")

                context = "\n\n".join(parts)

            # Add live game state to context (only if enabled)
            print(f"\n=== PREPARING AI CONTEXT ===")
            print(f"Live data mode: {self.live_data_mode.get()}")
            print(f"Current summary: {self.live_data.current_summary is not None}")

            if self.live_data_mode.get():
                live_context = self.live_data.get_live_context()
                print(f"Live context result: {live_context[:200] if live_context else 'None'}...")

                if live_context:
                    live_context = (
                        "=== YOUR CURRENT GAME (from save file) ===\n"
                        "This is your ACTUAL game state right now.\n"
                        "Use this for questions about YOUR empire.\n\n"
                    ) + live_context

                    if context:
                        context = live_context + "\n\n" + (
                            "=== GAME REFERENCE DATA (general info) ===\n"
                            "This is general game information, NOT your save.\n"
                            "Use this for questions about game mechanics.\n\n"
                        ) + context
                    else:
                        context = live_context
                    print(f"Live context added ({len(live_context)} chars)")
                else:
                    print("WARNING: Live mode on but no live context!")
            else:
                print("Live data mode is OFF")         

            cache_key = self.get_cache_key(question, matches)
            if CONFIG.get("cache_enabled", True) and cache_key in RESPONSE_CACHE:
                cached = RESPONSE_CACHE[cache_key]
                self.root.after(0, lambda: self.show_result(
                    cached["answer"], matches, question,
                    from_cache=True, tokens=total_tokens, has_data=has_game_data))
                return

            # Build messages based on data availability
            if has_game_data:
                # We have game data (static and/or live)
                has_live_data = (
                    self.live_data_mode.get() and 
                    self.live_data.current_summary is not None
                )

                if has_live_data:
                    system_prompt = (
                        "You are a Stellaris game expert helping a player with their CURRENT save file.\n\n"
                        "CRITICAL: You MUST use the EXACT numbers from 'YOUR CURRENT GAME' section.\n"
                        "- Do NOT round or approximate numbers\n"
                        "- Do NOT make up or estimate any values\n"
                        "- If the save shows 'energy: 2082.49', report EXACTLY '2,082.49'\n\n"
                        "You have TWO data sources:\n\n"
                        "1. YOUR CURRENT GAME - This is their ACTUAL save file with:\n"
                        "   - Exact resource amounts (energy, minerals, alloys, etc.)\n"
                        "   - Fleet power and ship counts\n"
                        "   - Planet and pop counts\n"
                        "   - Research output\n\n"
                        "2. GAME REFERENCE DATA - General info about technologies, buildings, etc.\n\n"
                        "Data sections are labeled [WIKI] or [GAME]:\n"
                        "- [WIKI] data = human descriptions, may be outdated\n"
                        "- [GAME] data = accurate stats from current game version\n\n"
                        "When numbers conflict, use [GAME] data for stats.\n\n"
                        "When asked about resources, ships, or anything from the save:\n"
                        "- Quote the EXACT numbers from YOUR CURRENT GAME\n"
                        "- Include decimal places if present in the data\n"
                        "- Never invent or round numbers\n\n"
                        "FORMATTING:\n"
                        "- Use **bold** for key numbers\n"
                        "- Use bullet points for lists\n"
                        "- No markdown tables"
                    )
                else:
                    system_prompt = (
                        "You are a Stellaris game expert. Use ONLY the provided game data. "
                        "Be concise and accurate.\n\n"
                        "Data sections are labeled [WIKI] or [GAME]:\n"
                        "- [WIKI] data = human descriptions, may be outdated\n"
                        "- [GAME] data = accurate stats from current game version\n\n"
                        "When numbers conflict, use [GAME] data for stats.\n\n"
                        "FORMATTING RULES:\n"
                        "- Use **bold** for important terms\n"
                        "- Use bullet points for lists\n"
                        "- Use `code blocks` for ASCII diagrams\n"
                        "- NEVER use markdown tables\n"
                        "- If data doesn't contain the answer, say so clearly."
                    )

                # CRITICAL: Set user_content with context!
                user_content = f"GAME DATA:\n{context}\n\nQUESTION: {question}"

            else:
                # No game data found
                system_prompt = (
                    "You are a helpful assistant for a Stellaris game helper application. "
                    "The user's question did not match any game data in the database, "
                    "but you can still help with general questions about Stellaris or "
                    "provide general assistance. Be concise and friendly. "
                    "Format your response clearly using:\n"
                    "- **bold** for important terms\n"
                    "- *italics* for emphasis\n"
                    "- Bullet points with * or - for lists\n"
                    "- Headers with ## or ### for sections\n"
                    "- Simple tables with | col1 | col2 | format"
                )
                user_content = question
                # DEBUG: Show what we're sending
                print(f"\n=== API REQUEST DEBUG ===")
                print(f"has_game_data: {has_game_data}")
                print(f"context length: {len(context) if context else 0}")
                print(f"context preview: {context[:300] if context else 'None'}...")
                print(f"user_content length: {len(user_content)}")
                print(f"user_content preview: {user_content[:500]}...")
                print("=========================\n")

            messages = [{"role": "system", "content": system_prompt}]

            if self.conversation_mode.get():
                for msg in self.conversation_history[-20:]:
                    messages.append(msg)

            messages.append({"role": "user", "content": user_content})

            temperature = CONFIG.get("temperature", 0.4)
            max_tokens = CONFIG.get("max_tokens", 2500)

            # Build messages array
            messages = [{"role": "system", "content": system_prompt}]

            if self.conversation_mode.get():
                for msg in self.conversation_history[-20:]:
                    messages.append(msg)

            messages.append({"role": "user", "content": user_content})

            # DEBUG: Show messages
            print(f"\n=== MESSAGES DEBUG ===")
            print(f"Total messages: {len(messages)}")
            for i, msg in enumerate(messages):
                print(f"  Message {i}: {msg['role']} - {len(msg['content'])} chars")
                if i < 2:  # Show first 2 messages
                    print(f"    Preview: {msg['content'][:200]}...")
            print("=====================\n")

            try:
                resp = requests.post(
                    CONFIG["api_url"],
                    headers={"Authorization": f"Bearer {CONFIG['api_key']}"},
                    json={
                        "model": CONFIG["model"],
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    },
                    timeout=120
                )

                if resp.status_code != 200:
                    error_msg = self.parse_api_error(resp)
                    self.root.after(0, lambda: self.show_result(
                        f"API Error ({resp.status_code}):\n{error_msg}",
                        [], question, is_error=True, has_data=False))
                    return

                data = resp.json()

                if "choices" not in data or not data["choices"]:
                    self.root.after(0, lambda: self.show_result(
                        "Invalid API response: no choices returned",
                        [], question, is_error=True, has_data=False))
                    return

                answer = data["choices"][0]["message"]["content"]
                answer = clean_output(answer)

                if CONFIG.get("cache_enabled", True):
                    RESPONSE_CACHE[cache_key] = {"answer": answer}
                    save_cache(RESPONSE_CACHE)

                if self.conversation_mode.get():
                    self.conversation_history.append(
                        {"role": "user", "content": question})
                    self.conversation_history.append(
                        {"role": "assistant", "content": answer})

                self.root.after(0, lambda: self.show_result(
                    answer, matches, question,
                    from_cache=False, tokens=total_tokens, has_data=has_game_data))

            except requests.exceptions.Timeout:
                self.root.after(0, lambda: self.show_result(
                    "Request timed out after 120 seconds.\n\n"
                    "The AI service may be busy. Try:\n"
                    "• Waiting a moment and retrying (F5)\n"
                    "• Using a different model",
                    [], question, is_error=True, has_data=False))

            except requests.exceptions.ConnectionError:
                self.root.after(0, lambda: self.show_result(
                    "Cannot connect to the API.\n\n"
                    "Check:\n"
                    "• Your internet connection\n"
                    "• The API URL in settings",
                    [], question, is_error=True, has_data=False))

            except requests.exceptions.RequestException as e:
                self.root.after(0, lambda: self.show_result(
                    f"Network error:\n{str(e)}",
                    [], question, is_error=True, has_data=False))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.root.after(0, lambda: self.show_result(
                f"Unexpected error:\n{str(e)}",
                [], question, is_error=True, has_data=False))   

    def parse_api_error(self, response):
        try:
            data = response.json()
            if "error" in data:
                return data["error"].get("message", str(data["error"]))
            return response.text[:200]
        except:
            return response.text[:200] if response.text else "Unknown error"

    def get_cache_key(self, question, matches):
        conv_mode = "conv" if self.conversation_mode.get() else "single"
        deep_mode = "deep" if self.deep_search_mode.get() else "normal"
        temp = CONFIG.get("temperature", 0.4)
        max_tok = CONFIG.get("max_tokens", 2500)
        if matches:
            match_keys = "|".join([m[0] for m in matches])
            content = f"{question}|{match_keys}|{CONFIG.get('model', '')}|{conv_mode}|{deep_mode}|{temp}|{max_tok}"
        else:
            content = f"{question}|nodata|{CONFIG.get('model', '')}|{conv_mode}|{deep_mode}|{temp}|{max_tok}"
        return hashlib.md5(content.encode()).hexdigest()

    def show_result(self, answer, matches, question, is_error=False,
                    from_cache=False, tokens=0, has_data=True):
        """Display result in UI with markdown formatting"""
        self.stop_loading_animation()

        self.last_matches = matches

        if hasattr(self, 'markdown'):
            # Pre-process: convert any markdown tables to bullet lists
            answer = self.convert_tables_to_lists(answer)
            self.markdown.render(answer, cache_hint=from_cache)
        else:
            self.answer_text.delete("1.0", "end")
            if from_cache:
                self.answer_text.insert("end", "[From cache]\n\n")
            self.answer_text.insert("end", answer)

        self.has_error = is_error
        if is_error:
            self.show_retry_button()
        else:
            self.hide_retry_button()
            clear_draft()

        self.add_to_history(question, answer, matches, has_data)
        self.update_context_label()

        if is_error:
            self.status_var.set("Error occurred")
        else:
            status_parts = []
            if matches:
                # Extract names from (key, data, score) tuples
                match_names = []
                for m in matches:
                    if isinstance(m, tuple) and len(m) >= 2:
                        item = m[1]
                        name = item.get("name", item.get("id", m[0]))
                        match_names.append(str(name))
                    else:
                        match_names.append(str(m))
                status_parts.append(f"Sections: {', '.join(match_names)}")
            elif not has_data:
                status_parts.append("No game data (general response)")
            if tokens > 0:
                status_parts.append(f"~{tokens} context tokens")
            if from_cache:
                status_parts.append("(cached)")
            if self.deep_search_mode.get() and has_data:
                status_parts.append("deep search")
            self.status_var.set(" | ".join(status_parts) if status_parts else "Done")

        try:
            self.ask_btn.configure(state="normal")
        except:
            pass

    def retry_last(self):
        if self.last_question:
            self.question_entry.delete(0, "end")
            self.question_entry.insert(0, self.last_question)
            self.ask()
        else:
            self.status_var.set("No previous question to retry")

    def on_close(self):
        try:
            rate_limit = int(self.rate_limit_var.get())
            if rate_limit < 0:
                rate_limit = 0
        except ValueError:
            rate_limit = 2

        try:
            temperature = float(self.temperature_var.get())
            temperature = max(0.0, min(2.0, temperature))
        except ValueError:
            temperature = 0.4

        try:
            max_tokens = int(self.max_tokens_var.get())
            max_tokens = max(1, min(8000, max_tokens))
        except ValueError:
            max_tokens = 2500

        config = {
            "api_key": self.api_key_var.get(),
            "api_url": self.api_url_var.get(),
            "model": self.model_var.get(),
            "conversation_mode": self.conversation_mode.get(),
            "cache_enabled": self.cache_enabled.get(),
            "rate_limit_seconds": rate_limit,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "deep_search_mode": self.deep_search_mode.get(),
            "live_data_mode": self.live_data_mode.get()
        }
        save_config(config)
        save_cache(RESPONSE_CACHE)

        question = self.question_entry.get().strip()
        if question:
            save_draft(question)
            
        self.live_data.stop_watching()
        self.root.destroy()

class LiveDataManager:
    """Manages live game data from save files."""

    def __init__(self, status_callback=None, save_status_callback=None):
        self.status_callback = status_callback
        self.save_status_callback = save_status_callback  # NEW
        self.watcher = None
        self.current_state = None
        self.current_summary = None
        self.save_path = None

    def on_save_detected(self, save_path):
        """Called when a new save is detected."""
        print(f"\n=== on_save_detected called ===")
        print(f"Save path: {save_path}")

        self.save_path = save_path
        save_name = os.path.basename(save_path)

        # Notify UI that loading started
        if self.save_status_callback:
            self.save_status_callback('loading')

        try:
            if self.status_callback:
                self.status_callback(f"Parsing save: {save_name}")

            print("  Calling parse_save...")
            meta, state = parse_save(save_path)
            print(f"  parse_save returned!")
            print(f"  state is None? {state is None}")
            print(f"  state type: {type(state)}")
            if state:
                print(f"  state keys: {list(state.keys())[:10]}")

            self.current_state = state
            print(f"  current_state set: {self.current_state is not None}")

            # Get player empire
            print("  Getting player empire...")
            empire_id = get_player_empire(state)
            print(f"  Empire ID: {empire_id}")

            # DEBUG: Show save structure
            from data_extractor import debug_save_structure
            debug_save_structure(state, empire_id)

            if empire_id is not None:
                print(f"  Calling extract_summary for empire {empire_id}...")
                self.current_summary = extract_summary(state, empire_id)
                print(f"  extract_summary returned: {self.current_summary is not None}")
            else:
                print("  No empire_id, trying get_empires...")
                empires = get_empires(state)
                print(f"  Empires found: {empires}")
                if empires:
                    first_empire = list(empires.keys())[0]
                    print(f"  Using first empire: {first_empire}")
                    self.current_summary = extract_summary(state, first_empire)
                    print(f"  extract_summary returned: {self.current_summary is not None}")

            print(f"  FINAL current_summary: {self.current_summary is not None}")
            if self.current_summary:
                print(f"  Summary keys: {list(self.current_summary.keys())}")
                print(f"  Summary content: {self.current_summary}")

            # Get timestamp from save
            timestamp = None
            if self.current_summary:
                date_str = self.current_summary.get('date', '')
                if date_str:
                    timestamp = date_str.replace('.', '/')

            # Notify UI that loading completed
            if self.save_status_callback:
                if self.current_summary:
                    self.save_status_callback('loaded', save_name, timestamp)
                else:
                    self.save_status_callback('error')

            if self.status_callback:
                if self.current_summary:
                    empire = self.current_summary.get('empire_name', 'Unknown')
                    self.status_callback(f"Live data loaded: {empire}")
                else:
                    self.status_callback("Save parsed, but no empire found")

            print("=== on_save_detected complete ===\n")

        except Exception as e:
            import traceback
            print(f"Error parsing save: {e}")
            traceback.print_exc()

            if self.save_status_callback:
                self.save_status_callback('error')

            if self.status_callback:
                self.status_callback(f"Error parsing save: {str(e)[:50]}")

    def start_watching(self, save_dir=None):
        """Start watching for save file changes."""
        self.watcher = SaveWatcher(
            save_dir=save_dir,
            callback=self.on_save_detected
        )
        self.watcher.start()

        return self.watcher.save_dir

    def stop_watching(self):
        """Stop watching."""
        if self.watcher:
            self.watcher.stop()

    def get_live_context(self):
        """Get formatted context string for AI queries."""
        if not self.current_summary:
            return None

        s = self.current_summary
        lines = [f"=== CURRENT GAME STATE ==="]
        lines.append(f"Date: {s.get('date', 'Unknown')}")
        lines.append(f"Empire: {s.get('empire_name', 'Unknown')}")

        if 'economy' in s:
            eco = s['economy']
            stock = eco.get('stockpile', {})
            income = eco.get('income', {})
            spending = eco.get('spending', {})

            lines.append(f"\nResources:")
            for res in ['energy', 'minerals', 'food', 'alloys', 'consumer_goods']:
                if res not in stock:
                    continue

                amount = stock[res]

                # Calculate totals
                total_income = 0
                total_spending = 0
                top_expenses = []

                if isinstance(income, dict):
                    for source, values in income.items():
                        if isinstance(values, dict) and res in values:
                            total_income += float(values[res])

                if isinstance(spending, dict):
                    for category, values in spending.items():
                        if isinstance(values, dict) and res in values:
                            val = float(values[res])
                            total_spending += val
                            top_expenses.append((category, val))

                # Sort expenses by amount (highest first)
                top_expenses.sort(key=lambda x: -x[1])
                net = total_income - total_spending

                # Format net
                sign = "+" if net >= 0 else ""
                net_str = f"{sign}{net:.1f}/month"

                # Build line
                if total_spending > 0:
                    # Show top 3 expenses
                    expense_str = ", ".join([f"{cat}({v:.1f})" for cat, v in top_expenses[:3]])
                    lines.append(f"  • {res}: {amount:,.2f} ({net_str})")
                    lines.append(f"      Expenses: {expense_str}")
                else:
                    lines.append(f"  • {res}: {amount:,.2f} ({net_str})")

        if 'fleets' in s:
            fl = s['fleets']
            lines.append(f"\nMilitary:")
            lines.append(f"  • Fleet Power: {fl.get('total_power', 0):,.0f}")

        if 'planets' in s:
            pl = s['planets']
            lines.append(f"\nPlanets:")
            lines.append(f"  • Count: {pl.get('total', 0)}")
            lines.append(f"  • Pops: {pl.get('total_pops', 0):,}")

        if 'tech' in s:
            t = s['tech']
            out = t.get('research_output', {})
            lines.append(f"\nResearch:")
            lines.append(f"  • Output: Physics({out.get('physics', 0):.1f}), "
                       f"Society({out.get('society', 0):.1f}), "
                       f"Engineering({out.get('engineering', 0):.1f})")
            lines.append(f"  • Techs Researched: {t.get('completed_count', 0)}")

            current = t.get('current_research', {})
            if current:
                lines.append(f"  • Currently Researching:")
                for field in ['physics', 'society', 'engineering']:
                    if field in current:
                        data = current[field]
                        tech = data.get('tech', 'Unknown')
                        # Clean up tech name
                        tech = tech.replace('tech_', '').replace('_', ' ').title()
                        progress = data.get('progress', 0)
                        status = "Project" if data.get('is_project') else f"{progress:.0f} progress"
                        lines.append(f"      {field.capitalize()}: {tech} ({status})")

        return '\n'.join(lines)

if __name__ == "__main__":
    root = tk.Tk()
    app = StellarisApp(root)
    root.mainloop()