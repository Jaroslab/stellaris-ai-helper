# stellaris_game_extractor.py
"""
Proper Stellaris game data extractor.
Extracts game objects with their localization, organized by category.
"""

import os
import re
import json
from datetime import datetime
from collections import defaultdict

VERSION = "1.0"

# Whitespace for parser (same as save_parser)
WHITESPACE = '\n \t\r'

class InMemoryFile:
    """Same file interface as save_parser for consistency."""

    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.size = len(data)

    def read(self, n=1):
        if self.pos >= self.size:
            return ''
        self.pos = min(self.size, self.pos + n)
        return self.data[self.pos-n:self.pos]

    def peek(self, n=1):
        if self.pos >= self.size:
            return ''
        return self.data[self.pos:min(self.size, self.pos + n)]

    def eof(self):
        return self.pos >= self.size

    def peekto(self, delim):
        if self.pos >= self.size:
            return ''
        i = self.pos
        while i < self.size and self.data[i] not in delim:
            i += 1
        return self.data[self.pos:i]

    def readto(self, delim):
        if self.pos >= self.size:
            return ''
        i = self.pos
        while i < self.size and self.data[i] not in delim:
            i += 1
        result = self.data[self.pos:i]
        self.pos = i
        if self.pos < self.size:
            self.pos += 1
        return result

    def skip(self, skip_chars):
        while self.pos < self.size and self.data[self.pos] in skip_chars:
            self.pos += 1

def parse_paradox_file(filepath):
    """
    Parse a Paradox format file into Python dict.
    """
    print(f"  Parsing: {os.path.basename(filepath)}")

    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            content = f.read()
    except Exception as e:
        print(f"  ERROR reading file: {e}")
        return {}

    # Remove comments
    content = re.sub(r'#[^\n]*', '', content)

    file = InMemoryFile(content)

    PARSING_DICT = 0
    PARSING_LIST = 1
    PARSING_DICT_OR_LIST = 2
    PARSING_OBJECT = 3
    PARSING_VALUE = 4

    states = [PARSING_DICT]
    current_object = [{}]
    can_reduce = False
    iterations = 0
    max_iterations = 1000000

    def reduce_dict():
        if len(current_object) > 2 and isinstance(current_object[-3], dict):
            value = current_object.pop(-1)
            key = current_object.pop(-1)

            # FIX: Strip whitespace from key
            if isinstance(key, str):
                key = key.strip()

            if key in current_object[-1]:
                if isinstance(current_object[-1][key], list):
                    current_object[-1][key].append(value)
                else:
                    current_object[-1][key] = [current_object[-1][key], value]
            else:
                current_object[-1][key] = value

    while not file.eof():
        iterations += 1
        if iterations > max_iterations:
            print(f"  WARNING: Max iterations reached at {filepath}")
            break

        file.skip(WHITESPACE)
        if file.eof() or not states:
            break

        if PARSING_DICT == states[-1]:
            if can_reduce:
                reduce_dict()

            if file.peek() == '}':
                file.read()
                states.pop()
                continue

            can_reduce = True
            name = file.readto('=')
            if not name:
                continue

            # FIX: Strip whitespace from name (the key)
            name = name.strip()

            if name.isnumeric():
                name = int(name)
            current_object.append(name)
            states.append(PARSING_OBJECT)

        elif PARSING_LIST == states[-1]:
            if not isinstance(current_object[-1], list) or states[-2] == PARSING_LIST:
                value = current_object.pop(-1)
                current_object[-1].append(value)

            if file.peek() == '}':
                file.read()
                states.pop(-1)
                continue

            states.append(PARSING_OBJECT)

        elif PARSING_DICT_OR_LIST == states[-1]:
            saved_pos = file.pos
            file.skip(WHITESPACE)
            peek_content = file.peekto('=}{')
            delim_pos = file.pos + len(peek_content)

            if delim_pos < file.size:
                delim = file.data[delim_pos]
            else:
                delim = ''

            file.pos = saved_pos

            if delim == '=':
                can_reduce = False
                current_object.append({})
                states[-1] = PARSING_DICT
            else:
                current_object.append([])
                states[-1] = PARSING_LIST

        elif PARSING_OBJECT == states[-1]:
            if file.peek() == '{':
                file.read()
                states[-1] = PARSING_DICT_OR_LIST
            else:
                states[-1] = PARSING_VALUE

        elif PARSING_VALUE == states[-1]:
            if file.peek() == '"':
                file.read()
                result = []
                while not file.eof():
                    ch = file.read(1)
                    if not ch:
                        break
                    if ch == '"':
                        if result and result[-1] == '\\':
                            result[-1] = '"'
                        else:
                            break
                    else:
                        result.append(ch)
                value = ''.join(result)
            else:
                value_str = file.readto(WHITESPACE)
                if not value_str:
                    states.pop(-1)
                    continue
                # FIX: Strip whitespace from value
                value_str = value_str.strip()
                try:
                    if '.' in value_str:
                        value = float(value_str)
                    else:
                        value = int(value_str)
                except ValueError:
                    value = value_str

            current_object.append(value)
            states.pop(-1)

    reduce_dict()
    return current_object[0] if current_object else {}

class StellarisGameExtractor:
    """
    Extracts game data from Stellaris installation.
    Produces clean, categorized JSON with attached localization.
    """

    # What we extract and where to find it
    CATEGORIES = {
        'technologies': {
            'path': 'common/technology',
            'key_field': None,  # Keys ARE the tech IDs
            'fields': ['tier', 'cost', 'area', 'category', 'prerequisites', 
                      'weight', 'potential', 'feature', 'is_rare', 'is_dangerous'],
        },
        'buildings': {
            'path': 'common/buildings',
            'key_field': None,
            'fields': ['buildtime', 'resources', 'upgrades', 'potential',
                      'planet_modifier', 'country_modifier', 'produces'],
        },
        'ship_sizes': {
            'path': 'common/ship_sizes',
            'key_field': None,
            'fields': ['slot_size', 'max_components', 'resources', 'build_time'],
        },
        'starbase_modules': {
            'path': 'common/starbase_modules',
            'key_field': None,
            'fields': ['resources', 'potential', 'build_time', 'modifier'],
        },
        'starbase_buildings': {
            'path': 'common/starbase_buildings',
            'key_field': None,
            'fields': ['resources', 'potential', 'build_time', 'modifier'],
        },
        'resources': {
            'path': 'common/strategic_resources',
            'key_field': None,
            'fields': ['type', 'is_rare', 'is_collectable', 'max', 'modifier'],
        },
        'traits': {
            'path': 'common/traits',
            'key_field': None,
            'fields': ['cost', 'modifier', 'initial', 'ruler', 'leader',
                      'species', 'pop', 'ethos'],
        },
        'ethics': {
            'path': 'common/ethics',
            'key_field': None,
            'fields': ['icon', 'allowed_civics', 'conflicting_ethics'],
        },
        'civics': {
            'path': 'common/government_civics',
            'key_field': None,
            'fields': ['cost', 'potential', 'possible', 'modifier'],
        },
        'traditions': {
            'path': 'common/traditions',
            'key_field': None,
            'fields': ['cost', 'potential', 'prerequisites', 'modifier'],
        },
        'ascension_perks': {
            'path': 'common/ascension_perks',
            'key_field': None,
            'fields': ['potential', 'possible', 'modifier', 'on_enabled'],
        },
        'planet_classes': {
            'path': 'common/planet_classes',
            'key_field': None,
            'fields': ['habitable', 'habitat', 'colonizable', 'districts'],
        },
        'deposits': {
            'path': 'common/deposits',
            'key_field': None,
            'fields': ['resources', 'potential', 'planet_modifier'],
        },
        'policies': {
            'path': 'common/policies',
            'key_field': None,
            'fields': ['potential', 'options'],
        },
        'edicts': {
            'path': 'common/edicts',
            'key_field': None,
            'fields': ['resources', 'potential', 'modifier', 'duration'],
        },
        'armies': {
            'path': 'common/armies',
            'key_field': None,
            'fields': ['resources', 'build_time', 'damage', 'health', 'morale'],
        },
        'ship_components': {
            'path': 'common/component_templates',
            'key_field': None,
            'fields': ['key', 'size', 'prerequisites', 'component_set', 'tags', 'modifier', 'ship_modifier', 'resources'],
        },
        'government_types': {
            'path': 'common/governments',
            'key_field': None,
            'fields': ['potential', 'civics'],
        },
        'species_rights': {
            'path': 'common/species_rights',
            'key_field': None,
            'fields': ['potential', 'modifier', 'pop_modifier'],
        },
        'terraform': {
            'path': 'common/terraform',
            'key_field': None,
            'fields': ['cost', 'time', 'from', 'to'],
        },
    }

    def __init__(self, stellaris_path):
        self.stellaris_path = stellaris_path
        self.localization = {}
        self.game_version = None
        self.data = {}
        self.stats = defaultdict(int)
        self.errors = []
        self.debug = True
        self.defines = {}

    def dprint(self, msg):
        """Debug print."""
        if self.debug:
            print(f"  {msg}")

    def load_game_version(self):
        """Extract game version from launcher-settings.json."""
        launcher_path = os.path.join(self.stellaris_path, 'launcher-settings.json')

        if os.path.exists(launcher_path):
            try:
                with open(launcher_path, 'r', encoding='utf-8') as f:
                    launcher_data = json.load(f)
                    self.game_version = launcher_data.get('version', 'unknown')
                    print(f"Game version: {self.game_version}")
                    return
            except:
                pass

        # Fallback: try version.txt
        version_path = os.path.join(self.stellaris_path, 'version.txt')
        if os.path.exists(version_path):
            try:
                with open(version_path, 'r', encoding='utf-8') as f:
                    self.game_version = f.read().strip()
                    print(f"Game version: {self.game_version}")
                    return
            except:
                pass

        self.game_version = 'unknown'
        print("Could not determine game version")

    def load_localization(self):
        """
        Load ALL localization into memory.
        We'll look up what we need - don't dump everything.
        """
        print("\n=== LOADING LOCALIZATION ===")

        loc_folders = [
            os.path.join(self.stellaris_path, 'localisation', 'english'),
            os.path.join(self.stellaris_path, 'localisation', 'l_english'),
            os.path.join(self.stellaris_path, 'localisation'),
        ]

        loc_path = None
        for p in loc_folders:
            if os.path.exists(p):
                loc_path = p
                print(f"Found localization: {p}")
                break

        if not loc_path:
            self.errors.append("Localization folder not found")
            return

        # Load all .yml files
        file_count = 0
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

                            # Format: KEY:0 "Value" or KEY: "Value"
                            match = re.match(r'([\w.-]+):\d*\s+"(.*)"', line)
                            if match:
                                key, val = match.groups()
                                # Clean up escape sequences
                                val = val.replace('\\"', '"')
                                val = val.replace('\\n', '\n')
                                self.localization[key] = val
                    file_count += 1

                except Exception as e:
                    self.errors.append(f"Loc error {filename}: {e}")

        print(f"Loaded {len(self.localization)} localization strings from {file_count} files")


    def load_weapon_stats(self):
        """Load weapon component stats from CSV files."""
        print("\n=== LOADING WEAPON STATS ===")

        self.weapon_stats = {}

        csv_files = [
            'weapon_components.csv',
            'mutation_weapon_components.csv',
        ]

        component_path = os.path.join(self.stellaris_path, 'common', 'component_templates')

        for csv_file in csv_files:
            filepath = os.path.join(component_path, csv_file)
            if not os.path.exists(filepath):
                continue

            try:
                with open(filepath, 'r', encoding='utf-8-sig') as f:
                    lines = f.readlines()

                # Find header line
                header = None
                for line in lines:
                    if line.startswith('key;'):
                        header = line.strip().split(';')
                        break

                if not header:
                    continue

                # Parse data lines
                for line in lines:
                    if line.startswith('#') or line.startswith('key;'):
                        continue
                    if not line.strip():
                        continue

                    values = line.strip().split(';')
                    if len(values) < 14:
                        continue

                    key = values[0]

                    # Parse numeric values
                    try:
                        self.weapon_stats[key] = {
                            'cost': float(values[1]) if values[1] else 0,
                            'power': float(values[2]) if values[2] else 0,
                            'min_damage': float(values[3]) if values[3] else 0,
                            'max_damage': float(values[4]) if values[4] else 0,
                            'hull_damage_mult': float(values[5]) if values[5] else 1,
                            'shield_damage_mult': float(values[6]) if values[6] else 1,
                            'shield_penetration': float(values[7]) if values[7] else 0,
                            'armor_damage_mult': float(values[8]) if values[8] else 1,
                            'armor_penetration': float(values[9]) if values[9] else 0,
                            'cooldown': float(values[12]) if len(values) > 12 and values[12] else 0,
                            'range': float(values[13]) if len(values) > 13 and values[13] else 0,
                            'accuracy': float(values[14]) if len(values) > 14 and values[14] else 0,
                            'tracking': float(values[15]) if len(values) > 15 and values[15] else 0,
                        }
                    except (ValueError, IndexError):
                        pass

                print(f"  Loaded {len(self.weapon_stats)} weapon stats from {csv_file}")

            except Exception as e:
                print(f"  Error loading {csv_file}: {e}")        

    def loc(self, key, fallback=None):
        """Get localization for a key, resolving $variable$ references."""
        if not key:
            return fallback or ""

        # Try exact match
        if key in self.localization:
            value = self.localization[key]
            return self._resolve_loc_variables(value)

        # Try common suffixes
        for suffix in ['', '_name', '_desc', '_title']:
            test_key = f"{key}{suffix}"
            if test_key in self.localization:
                value = self.localization[test_key]
                return self._resolve_loc_variables(value)

        return fallback or str(key).replace('_', ' ').title()

    def _resolve_loc_variables(self, text):
        """Resolve $variable$ references in localization text."""
        if not text or not isinstance(text, str):
            return text

        # Use [$] to match literal $ character (avoids escape issues)
        pattern = r'[$]([a-zA-Z_][a-zA-Z0-9_]*)[$]'

        max_iterations = 5
        for _ in range(max_iterations):
            matches = re.findall(pattern, text)
            if not matches:
                break
            for var_name in matches:
                if var_name in self.localization:
                    text = text.replace(f"${var_name}$", self.localization[var_name])

        return text

    def clean_loc_text(self, text):
        """
        Clean localization text of game formatting codes.
        Stellaris uses codes like §H (highlight), §R (red), etc.
        """
        if not text:
            return ""

        # Remove color codes: §H, §R, §G, §Y, §B, §L, §S, §!, §W, §-
        text = re.sub(r'§[a-zA-Z!-]', '', text)

        # Remove $variable$ references, keep the content if it's just text
        text = re.sub(r'$([a-zA-Z_]+)$', r'[\1]', text)

        # Clean up extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text
    

    
    def load_scripted_variables(self):
        """Load @variable definitions from scripted_variables folder."""
        print("\n=== LOADING SCRIPTED VARIABLES ===")

        var_path = os.path.join(self.stellaris_path, 'common', 'scripted_variables')

        if not os.path.exists(var_path):
            print("  Scripted variables folder not found!")
            return

        count = 0
        # Scan ALL files in the folder, not just one
        for filename in sorted(os.listdir(var_path)):
            if not filename.endswith('.txt'):
                continue

            filepath = os.path.join(var_path, filename)
            try:
                with open(filepath, 'r', encoding='utf-8-sig') as f:
                    content = f.read()

                # Match @variable = number
                for match in re.finditer(r'@(\w+)\s*=\s*(-?\d+\.?\d*)', content):
                    var_name = match.group(1)
                    var_value = match.group(2)

                    try:
                        if '.' in var_value:
                            self.defines[var_name] = float(var_value)
                        else:
                            self.defines[var_name] = int(var_value)
                        count += 1
                    except:
                        pass

            except Exception as e:
                print(f"  Error reading {filename}: {e}")

        print(f"  Loaded {count} scripted variables")

        # Show key variables we care about
        key_vars = ['citadel_cost', 'halved_alloy_to_food_cost_ratio']
        for var in key_vars:
            if var in self.defines:
                print(f"  @{var} = {self.defines[var]}")

    def find_unlock_info(self, item_id):
        """
        Find what this item unlocks based on TECHUNLOCK_ or similar keys.
        Returns list of unlock descriptions.
        """
        unlocks = []

        # Check for TECHUNLOCK_ keys
        unlock_prefix = f"TECHUNLOCK_{item_id.upper()}"

        for key in self.localization:
            if key.upper().startswith("TECHUNLOCK_"):
                # Check if this unlock relates to our item
                key_lower = key.lower()
                if item_id.lower() in key_lower or key_lower in item_id.lower():
                    title = self.localization.get(f"{key}_TITLE", "")
                    desc = self.localization.get(f"{key}_DESC", "")
                    if title or desc:
                        unlocks.append({
                            'title': self.clean_loc_text(title),
                            'description': self.clean_loc_text(desc),
                        })

        return unlocks

    def extract_technology(self, tech_id, tech_data):
        """Extract a single technology with resolved costs."""
        tech_id = tech_id.strip() if isinstance(tech_id, str) else tech_id

        tech = {
            'id': tech_id,
            'name': self.loc(tech_id),
            'description': self.clean_loc_text(self.loc(f"{tech_id}_desc")),
        }

        # Tier
        tier = tech_data.get('tier', 0)
        if isinstance(tier, str):
            try:
                tier = int(tier)
            except:
                tier = 0
        tech['tier'] = tier

        # Cost - RESOLVE @variables
        raw_cost = tech_data.get('cost', 0)
        tech['cost'] = self.resolve_cost(raw_cost)

        # Area
        area = tech_data.get('area', 'unknown')
        tech['area'] = area.lower() if isinstance(area, str) else 'unknown'

        # Categories
        categories = tech_data.get('category', [])
        if isinstance(categories, str):
            categories = [categories]
        elif isinstance(categories, dict):
            categories = categories.get('__values__', [])
        tech['categories'] = categories

        # Prerequisites
        prereq_data = tech_data.get('prerequisites', {})
        prereqs = self._extract_prerequisites(prereq_data)

        # Simplify if no complex logic
        if isinstance(prereqs, dict):
            if not prereqs.get('any_of'):
                prereqs = prereqs['required']

        # Resolve names for LLM readability
        tech['prerequisites'] = self._resolve_prerequisite_names(prereqs)

        # Weight
        weight_raw = tech_data.get('weight', 0)
        tech['weight'] = self.resolve_cost(weight_raw)

        # Flags
        tech['is_rare'] = self._to_bool(tech_data.get('is_rare'))
        tech['is_dangerous'] = self._to_bool(tech_data.get('is_dangerous'))
        tech['is_start_tech'] = self._to_bool(tech_data.get('start_tech'))

        # Extract unlock info from prereqfor_desc
        unlocks = self._extract_unlocks(tech_data)
        if unlocks:
            tech['unlocks'] = unlocks

        # Feature flags
        if 'feature_flags' in tech_data:
            tech['feature_flags'] = tech_data['feature_flags']

        # Modifier
        if 'modifier' in tech_data:
            tech['modifier'] = tech_data['modifier']

        # Print for debug
        print(f"  {tech_id}: Tier {tier}, Cost {tech['cost']}, Area {area}")
        if tech['prerequisites']:
            print(f"    Prerequisites: {tech['prerequisites']}")
        if unlocks:
            print(f"    Unlocks: {[u.get('title', '?') for u in unlocks]}")

        return tech

    def _extract_unlocks(self, tech_data):
        """Extract unlock information from prereqfor_desc."""
        unlocks = []

        prereqfor = tech_data.get('prereqfor_desc', {})

        if isinstance(prereqfor, dict):
            for unlock_type, info in prereqfor.items():
                if isinstance(info, dict):
                    title_key = info.get('title', '')
                    desc_key = info.get('desc', '')

                    title = self.loc(title_key, title_key)
                    desc = self.clean_loc_text(self.loc(desc_key, ''))

                    if title or desc:
                        unlocks.append({
                            'type': unlock_type,
                            'title': title,
                            'description': desc,
                        })

        return unlocks
    
    def _extract_prerequisites(self, data):
        """
        Extract prerequisites from parsed data.
        Handles the parser bug that concatenates values into garbage strings.
        """
        if not data:
            return {"required": []}

        result = {"required": [], "any_of": []}

        # Case 1: String
        if isinstance(data, str):
            if '\n' in data or '\t' in data:
                tokens = data.split()
                for token in tokens:
                    token = token.strip()
                    if token and token.startswith('tech_'):
                        result["required"].append(token)
            elif data.startswith('tech_'):
                result["required"].append(data.strip())
            return result

        # Case 2: List
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    if '\n' in item or '\t' in item:
                        for token in item.split():
                            if token.startswith('tech_'):
                                result["required"].append(token.strip())
                    elif item.startswith('tech_'):
                        result["required"].append(item.strip())
                elif isinstance(item, dict):
                    nested = self._extract_prerequisites(item)
                    result["required"].extend(nested.get("required", []))
                    result["any_of"].extend(nested.get("any_of", []))
            return result

        # Case 3: Dict - THIS IS WHERE THE PARSER BUG SURFACES
        if isinstance(data, dict):
            for key, value in data.items():
                key_str = str(key).strip() if key else ''

                # PARSER BUG: key is a garbage string like 
                # "tech_starbase_5\n\t\ttech_zero_point_power\n\t\tOR"
                # Split it to find real tech IDs and keywords
                if '\n' in key_str or '\t' in key_str:
                    tokens = key_str.split()
                    for i, token in enumerate(tokens):
                        token = token.strip()
                        if token.startswith('tech_'):
                            result["required"].append(token)
                        elif token.upper() == 'OR':
                            # Found OR - value contains the OR options
                            or_techs = self._extract_tech_ids_from_block(value)
                            if or_techs:
                                result["any_of"].append(or_techs)
                elif key_str.upper() == 'OR':
                    or_techs = self._extract_tech_ids_from_block(value)
                    if or_techs:
                        result["any_of"].append(or_techs)
                elif key_str.upper() == 'AND':
                    and_techs = self._extract_tech_ids_from_block(value)
                    if and_techs:
                        result["required"].extend(and_techs)
                elif key_str.upper() == 'NOT':
                    pass
                elif key_str.startswith('tech_'):
                    result["required"].append(key_str)
                elif isinstance(value, str) and str(value).startswith('tech_'):
                    result["required"].append(str(value).strip())
                elif isinstance(value, dict):
                    nested = self._extract_prerequisites(value)
                    result["required"].extend(nested.get("required", []))
                    result["any_of"].extend(nested.get("any_of", []))

            return result

        return result

    def _extract_tech_ids_from_block(self, block):
        """Extract all tech IDs from an OR/AND/NOT block."""
        techs = []

        if isinstance(block, str):
            if block.startswith('tech_'):
                techs.append(block.strip())
            elif '\n' in block or '\t' in block:
                # Garbage string - split and clean
                for token in block.split():
                    token = token.strip()
                    if token.startswith('tech_'):
                        techs.append(token)

        elif isinstance(block, list):
            for item in block:
                if isinstance(item, str) and item.strip().startswith('tech_'):
                    techs.append(item.strip())

        elif isinstance(block, dict):
            # Check for __values__ (list-style dict)
            if '__values__' in block:
                for item in block['__values__']:
                    if isinstance(item, str) and item.strip().startswith('tech_'):
                        techs.append(item.strip())

            # Check keys
            for key in block.keys():
                key_str = str(key).strip()
                if key_str.startswith('tech_') and key_str.upper() not in ('OR', 'AND', 'NOT'):
                    techs.append(key_str)

        return techs
    
    def _resolve_prerequisite_names(self, prereqs):
        """Convert prerequisite IDs to human-readable names."""
        if isinstance(prereqs, list):
            return [self.loc(tid) for tid in prereqs]

        if isinstance(prereqs, dict):
            result = {}

            if prereqs.get("required"):
                result["required"] = [self.loc(tid) for tid in prereqs["required"]]

            if prereqs.get("any_of"):
                result["any_of"] = [
                    [self.loc(tid) for tid in group]
                    for group in prereqs["any_of"]
                ]

            return result

        return prereqs


    def _to_bool(self, value):
        """Convert various formats to boolean."""
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('yes', 'true', '1')
        return bool(value)

    def extract_building(self, building_id, building_data):
        """Extract a single building with all relevant info."""

        building = {
            'id': building_id,
            'name': self.loc(building_id),
            'description': self.clean_loc_text(self.loc(f"{building_id}_desc")),
        }

        # Build time and cost
        building['build_time'] = building_data.get('buildtime', 0)

        # Resources (cost to build)
        resources = building_data.get('resources', {})
        if isinstance(resources, dict):
            building['cost'] = resources

        # What it produces/upgrades to
        building['upgrades'] = self._get_list(building_data, 'upgrades')

        # Modifiers
        if 'planet_modifier' in building_data:
            building['planet_modifier'] = building_data['planet_modifier']
        if 'country_modifier' in building_data:
            building['country_modifier'] = building_data['country_modifier']

        # Potential/requirements
        if 'potential' in building_data:
            building['potential'] = building_data['potential']

        return building

    def _get_list(self, data, key):
        """Extract a list value from data, handling various formats."""
        val = data.get(key, [])

        if isinstance(val, list):
            return val
        if isinstance(val, str):
            return [val] if val else []
        if isinstance(val, dict) and '__values__' in val:
            return val['__values__']
        return []

    def extract_category(self, category_name, category_info):
        """
        Extract all items from a category folder.
        """
        folder_path = os.path.join(self.stellaris_path, category_info['path'])

        if not os.path.exists(folder_path):
            self.dprint(f"Folder not found: {folder_path}")
            return {}

        print(f"\n=== EXTRACTING {category_name.upper()} ===")
        print(f"Path: {folder_path}")

        category_data = {}
        file_count = 0

        for filename in os.listdir(folder_path):
            if not filename.endswith('.txt'):
                continue

            filepath = os.path.join(folder_path, filename)
            file_data = parse_paradox_file(filepath)
            file_count += 1

            if not isinstance(file_data, dict):
                continue

            # THIS LOOP MUST BE INSIDE THE FILE LOOP
            for entry_id, entry_data in file_data.items():
                # Skip metadata keys
                if entry_id.lower() in ('category', 'categories', 'area', 'tier',
                                        'table', 'type', 'types', 'groups', 
                                        '__values__', 'default'):
                    continue

                # Handle list case (multiple entries with same key)
                if isinstance(entry_data, list):
                    for item_data in entry_data:
                        if not isinstance(item_data, dict):
                            continue
                        actual_key = item_data.get('key', entry_id)
                        item = self._extract_item(category_name, actual_key, item_data)
                        if item:
                            item = self.finalize_item(item)
                            category_data[actual_key] = item
                            self.stats[category_name] += 1
                    continue

                # Normal single entry
                if not isinstance(entry_data, dict):
                    continue

                item = self._extract_item(category_name, entry_id, entry_data)
                if item:
                    item = self.finalize_item(item)
                    category_data[entry_id] = item
                    self.stats[category_name] += 1

        print(f"Extracted {len(category_data)} {category_name} from {file_count} files")
        return category_data

    def extract_starbase_module(self, module_id, module_data):
        """Extract starbase module info."""
        module = {
            'id': module_id,
            'name': self.loc(module_id),
            'description': self.clean_loc_text(self.loc(f"{module_id}_desc")),
        }

        module['build_time'] = module_data.get('buildtime', 0)
        module['cost'] = module_data.get('resources', {})

        if 'modifier' in module_data:
            module['modifier'] = module_data['modifier']

        return module

    def extract_starbase_building(self, building_id, building_data):
        """Extract starbase building info."""
        building = {
            'id': building_id,
            'name': self.loc(building_id),
            'description': self.clean_loc_text(self.loc(f"{building_id}_desc")),
        }

        building['build_time'] = building_data.get('buildtime', 0)
        resources = building_data.get('resources', {})
        building['cost'] = self.resolve_all_variables(resources)
        building['cost'] = building_data.get('resources', {})

        if 'modifier' in building_data:
            building['modifier'] = building_data['modifier']

        return building
    
    def finalize_item(self, item):
        """
        Finalize extracted item:
        - Resolve all @variable references
        - Clean up any remaining issues
        """
        return self.resolve_all_variables(item)

    def extract_ship_size(self, ship_id, ship_data):
        """Extract ship size (class) info with full stats."""
        ship = {
            'id': ship_id,
            'name': self.loc(ship_id),
            'description': self.clean_loc_text(self.loc(f"{ship_id}_desc")),
        }

        # Movement stats
        ship['max_speed'] = ship_data.get('max_speed', 0)
        ship['acceleration'] = ship_data.get('acceleration', 0)
        ship['rotation_speed'] = ship_data.get('rotation_speed', 0)

        # Combat stats
        ship['max_hitpoints'] = self.resolve_cost(ship_data.get('max_hitpoints', 0))
        ship['combat_size_multiplier'] = ship_data.get('combat_size_multiplier', 1)

        # Build time
        ship['build_time'] = ship_data.get('base_buildtime', ship_data.get('build_time', 0))

        # Cost
        resources = ship_data.get('resources', {})
        ship['cost'] = self.resolve_all_variables(resources)

        # Modifiers
        if 'modifier' in ship_data:
            ship['modifier'] = self.resolve_all_variables(ship_data['modifier'])
        if 'ship_modifier' in ship_data:
            ship['ship_modifier'] = self.resolve_all_variables(ship_data['ship_modifier'])

        # Section slots (where modules/weapons go)
        if 'section_slots' in ship_data:
            ship['section_slots'] = list(ship_data['section_slots'].keys())

        # Prerequisites
        if 'prerequisites' in ship_data:
            prereqs = ship_data['prerequisites']
            if isinstance(prereqs, dict):
                prereqs = list(prereqs.keys())
            elif isinstance(prereqs, str):
                prereqs = [prereqs]
            ship['prerequisites'] = [self.loc(p) for p in prereqs]

        # Required components
        if 'required_component_set' in ship_data:
            reqs = ship_data['required_component_set']
            if isinstance(reqs, dict):
                reqs = list(reqs.keys())
            elif isinstance(reqs, str):
                reqs = [reqs]
            ship['required_components'] = reqs

        return ship

    def extract_resource(self, resource_id, resource_data):
        """Extract strategic resource info."""
        resource = {
            'id': resource_id,
            'name': self.loc(resource_id),
            'description': self.clean_loc_text(self.loc(f"{resource_id}_desc")),
        }

        resource['type'] = resource_data.get('type', 'basic')
        resource['is_rare'] = resource_data.get('is_rare', False)
        resource['is_collectable'] = resource_data.get('is_collectable', False)

        if 'modifier' in resource_data:
            resource['modifier'] = resource_data['modifier']

        return resource

    def extract_trait(self, trait_id, trait_data):
        """Extract trait info (species, leader, ruler)."""
        trait = {
            'id': trait_id,
            'name': self.loc(trait_id),
            'description': self.clean_loc_text(self.loc(f"{trait_id}_desc")),
        }

        trait['cost'] = trait_data.get('cost', 0)

        # Determine trait type
        if trait_data.get('ruler'):
            trait['type'] = 'ruler'
        elif trait_data.get('leader'):
            trait['type'] = 'leader'
        elif trait_data.get('species'):
            trait['type'] = 'species'
        elif trait_data.get('pop'):
            trait['type'] = 'pop'
        else:
            trait['type'] = 'unknown'

        if 'modifier' in trait_data:
            trait['modifier'] = trait_data['modifier']

        return trait

    def extract_ethic(self, ethic_id, ethic_data):
        """Extract ethic info."""
        ethic = {
            'id': ethic_id,
            'name': self.loc(ethic_id),
            'description': self.clean_loc_text(self.loc(f"{ethic_id}_desc")),
        }

        # Ethics have pairs like ethic_fanatic_xenophile vs ethic_xenophile
        ethic['fanatic'] = 'fanatic' in ethic_id.lower()

        if 'allowed_civics' in ethic_data:
            ethic['allowed_civics'] = ethic_data['allowed_civics']

        return ethic

    def extract_civic(self, civic_id, civic_data):
        """Extract civic info."""
        civic = {
            'id': civic_id,
            'name': self.loc(civic_id),
            'description': self.clean_loc_text(self.loc(f"{civic_id}_desc")),
        }

        civic['cost'] = civic_data.get('cost', 0)

        if 'possible' in civic_data:
            civic['requirements'] = civic_data['possible']
        if 'modifier' in civic_data:
            civic['modifier'] = civic_data['modifier']

        return civic

    def extract_tradition(self, tradition_id, tradition_data):
        """Extract tradition info."""
        tradition = {
            'id': tradition_id,
            'name': self.loc(tradition_id),
            'description': self.clean_loc_text(self.loc(f"{tradition_id}_desc")),
        }

        tradition['cost'] = tradition_data.get('cost', 0)
        tradition['prerequisites'] = self._extract_prerequisites(tradition_data)

        if 'modifier' in tradition_data:
            tradition['modifier'] = tradition_data['modifier']

        return tradition

    def extract_ascension_perk(self, perk_id, perk_data):
        """Extract ascension perk info."""
        perk = {
            'id': perk_id,
            'name': self.loc(perk_id),
            'description': self.clean_loc_text(self.loc(f"{perk_id}_desc")),
        }

        if 'possible' in perk_data:
            perk['requirements'] = perk_data['possible']
        if 'modifier' in perk_data:
            perk['modifier'] = perk_data['modifier']
        if 'on_enabled' in perk_data:
            perk['on_enabled'] = perk_data['on_enabled']

        return perk

    def extract_planet_class(self, pc_id, pc_data):
        """Extract planet class info."""
        planet = {
            'id': pc_id,
            'name': self.loc(pc_id),
            'description': self.clean_loc_text(self.loc(f"{pc_id}_desc")),
        }

        planet['habitable'] = pc_data.get('habitable', False)
        planet['colonizable'] = pc_data.get('colonizable', False)

        if 'districts' in pc_data:
            planet['districts'] = pc_data['districts']

        return planet

    def extract_deposit(self, deposit_id, deposit_data):
        """Extract deposit (resource on planet) info."""
        deposit = {
            'id': deposit_id,
            'name': self.loc(deposit_id),
            'description': self.clean_loc_text(self.loc(f"{deposit_id}_desc")),
        }

        if 'resources' in deposit_data:
            deposit['resources'] = deposit_data['resources']
        if 'planet_modifier' in deposit_data:
            deposit['modifier'] = deposit_data['planet_modifier']

        return deposit

    def extract_army(self, army_id, army_data):
        """Extract army info."""
        army = {
            'id': army_id,
            'name': self.loc(army_id),
            'description': self.clean_loc_text(self.loc(f"{army_id}_desc")),
        }

        army['build_time'] = army_data.get('build_time', 0)
        army['cost'] = army_data.get('resources', {})
        army['damage'] = army_data.get('damage', 0)
        army['health'] = army_data.get('max_health', 0)
        army['morale'] = army_data.get('max_morale', 0)

        return army
    
    def extract_ship_component(self, comp_id, comp_data):
        """Extract ship component (weapon, utility, etc.)."""
        # Get the actual key from the component data
        actual_key = comp_data.get('key', comp_id)

        component = {
            'id': actual_key,
            'name': self.loc(actual_key),
            'type': None,  # Will be determined by template type
        }

        # Component size
        component['size'] = comp_data.get('size', 'unknown')

        # Prerequisites
        if 'prerequisites' in comp_data:
            prereqs = comp_data['prerequisites']
            if isinstance(prereqs, dict):
                prereqs = list(prereqs.keys())
            elif isinstance(prereqs, str):
                prereqs = [prereqs]
            component['prerequisites'] = [self.loc(p) for p in prereqs if p]

        # Component set (grouping)
        component['component_set'] = comp_data.get('component_set', '')

        # Tags
        if 'tags' in comp_data:
            tags = comp_data['tags']
            if isinstance(tags, dict):
                tags = list(tags.keys())
            component['tags'] = tags

        # Modifiers (for non-weapons like shields, armor, thrusters)
        if 'modifier' in comp_data:
            component['modifier'] = self.resolve_all_variables(comp_data['modifier'])
        if 'ship_modifier' in comp_data:
            component['ship_modifier'] = self.resolve_all_variables(comp_data['ship_modifier'])

        # Cost/upkeep
        if 'resources' in comp_data:
            component['resources'] = self.resolve_all_variables(comp_data['resources'])

        # Power usage
        if 'power' in comp_data:
            component['power'] = comp_data['power']

        # Weapon stats from CSV (if weapon)
        if actual_key in self.weapon_stats:
            stats = self.weapon_stats[actual_key]
            component['weapon_stats'] = stats

        return component
    
    def _extract_item(self, category_name, entry_id, entry_data):
        """Route to the appropriate extraction method."""
        if category_name == 'technologies':
            return self.extract_technology(entry_id, entry_data)
        elif category_name == 'buildings':
            return self.extract_building(entry_id, entry_data)
        elif category_name == 'starbase_modules':
            return self.extract_starbase_module(entry_id, entry_data)
        elif category_name == 'starbase_buildings':
            return self.extract_starbase_building(entry_id, entry_data)
        elif category_name == 'ship_sizes':
            return self.extract_ship_size(entry_id, entry_data)
        elif category_name == 'ship_components':
            return self.extract_ship_component(entry_id, entry_data)
        elif category_name == 'resources':
            return self.extract_resource(entry_id, entry_data)
        elif category_name == 'traits':
            return self.extract_trait(entry_id, entry_data)
        elif category_name == 'ethics':
            return self.extract_ethic(entry_id, entry_data)
        elif category_name == 'civics':
            return self.extract_civic(entry_id, entry_data)
        elif category_name == 'traditions':
            return self.extract_tradition(entry_id, entry_data)
        elif category_name == 'ascension_perks':
            return self.extract_ascension_perk(entry_id, entry_data)
        elif category_name == 'planet_classes':
            return self.extract_planet_class(entry_id, entry_data)
        elif category_name == 'deposits':
            return self.extract_deposit(entry_id, entry_data)
        elif category_name == 'armies':
            return self.extract_army(entry_id, entry_data)
        else:
            return self.extract_generic(entry_id, entry_data, category_name)

    def extract_generic(self, item_id, item_data, category):
        """Generic extraction for unknown categories."""
        item = {
            'id': item_id,
            'name': self.loc(item_id),
            'description': self.clean_loc_text(self.loc(f"{item_id}_desc")),
            'category': category,
        }

        # Copy all fields from data
        for key, val in item_data.items():
            if key not in item:
                item[key] = val

        return item

    def extract_all(self, progress_callback=None):
        """
        Extract all game data.
        Returns clean, structured dictionary.
        """
        print("\n" + "=" * 60)
        print("STELLARIS GAME DATA EXTRACTION")
        print("=" * 60)
        print(f"Source: {self.stellaris_path}")

        # Load version
        self.load_game_version()

        # Load localization
        self.load_localization()
        self.load_defines()
        self.load_scripted_variables()
        self.load_weapon_stats()

        # Extract each category
        for category_name, category_info in self.CATEGORIES.items():
            if progress_callback:
                progress_callback(f"Extracting {category_name}...")

            category_data = self.extract_category(category_name, category_info)

            if category_data:
                self.data[category_name] = category_data

        self.debug_tech_file_detail()  # <-- ADD THIS
        print("\nPress Enter to continue or Ctrl+C to abort...")
        input()
        

        # Build final output
        output = {
            'metadata': {
                'version': VERSION,
                'game_version': self.game_version,
                'extraction_date': datetime.now().isoformat(),
                'source_path': self.stellaris_path,
                'total_entries': sum(self.stats.values()),
                'stats': dict(self.stats),
            }
        }
        output.update(self.data)

        print("\n" + "=" * 60)
        print("EXTRACTION COMPLETE")
        print("=" * 60)
        for cat, count in self.stats.items():
            print(f"  {cat}: {count}")
        print(f"  TOTAL: {sum(self.stats.values())}")

        if self.errors:
            print(f"\nErrors: {len(self.errors)}")
            for err in self.errors[:10]:
                print(f"  - {err}")

        return output

    def debug_file_structure(self, filepath):
        """Debug: Show the raw structure of a parsed file."""
        print(f"\n--- {os.path.basename(filepath)} ---")

        data = parse_paradox_file(filepath)

        if not data:
            print("  (empty or failed)")
            return

        def show_item(key, value, indent=0):
            prefix = "  " * indent

            if isinstance(value, dict):
                print(f"{prefix}{key}:")
                for k, v in list(value.items())[:8]:
                    show_item(k, v, indent + 1)
                if len(value) > 8:
                    print(f"{prefix}  ... ({len(value) - 8} more)")
            elif isinstance(value, list):
                print(f"{prefix}{key}: [{len(value)} items]")
                for i, item in enumerate(value[:3]):
                    if isinstance(item, (str, int, float, bool)):
                        print(f"{prefix}  [{i}]: {item}")
                    else:
                        print(f"{prefix}  [{i}]: {type(item).__name__}")
                if len(value) > 3:
                    print(f"{prefix}  ... ({len(value) - 3} more)")
            else:
                val_str = str(value)
                if len(val_str) > 60:
                    val_str = val_str[:60] + "..."
                print(f"{prefix}{key}: {val_str}")

        for key, value in list(data.items())[:15]:
            show_item(key, value)
        if len(data) > 15:
            print(f"  ... ({len(data) - 15} more entries)")

    def debug_technology_folder(self):
        """Debug: Show structure of technology files."""
        tech_path = os.path.join(self.stellaris_path, 'common', 'technology')

        if not os.path.exists(tech_path):
            print(f"Technology folder not found: {tech_path}")
            return

        for filename in sorted(os.listdir(tech_path)):
            if filename.endswith('.txt'):
                filepath = os.path.join(tech_path, filename)
                self.debug_file_structure(filepath)

    def debug_localization_keys(self, search_term):
        """
        Debug: Find localization keys matching a search term.
        """
        print(f"\n=== LOCALIZATION KEYS matching '{search_term}' ===")

        matches = []
        for key in self.localization:
            if search_term.lower() in key.lower():
                matches.append(key)

        matches.sort()

        if not matches:
            print("  No matches found")
            return

        print(f"  Found {len(matches)} matches:")
        for key in matches[:20]:  # Show first 20
            val = self.localization[key]
            if len(val) > 80:
                val = val[:80] + "..."
            print(f"    {key}: {val}")

        if len(matches) > 20:
            print(f"  ... ({len(matches) - 20} more)")

    # Add this method to StellarisGameExtractor class

    def debug_tech_file_detail(self):
        """
        Deep debug: Show the ACTUAL parsed structure of a tech file.
        """
        tech_path = os.path.join(self.stellaris_path, 'common', 'technology')

        # Find a file that should have citadel
        for filename in os.listdir(tech_path):
            if filename.endswith('.txt') and 'eng' in filename.lower():
                filepath = os.path.join(tech_path, filename)
                print(f"\n{'='*60}")
                print(f"FILE: {filename}")
                print('='*60)

                # Show raw content (first 2000 chars)
                try:
                    with open(filepath, 'r', encoding='utf-8-sig') as f:
                        raw = f.read()
                        print(f"\n--- RAW CONTENT (first 2000 chars) ---")
                        print(raw[:2000])
                        print("...")
                except Exception as e:
                    print(f"Error reading: {e}")
                    continue

                # Parse and show structure
                data = parse_paradox_file(filepath)
                print(f"\n--- PARSED STRUCTURE ---")
                print(f"Type: {type(data)}")
                print(f"Keys: {list(data.keys())[:20] if isinstance(data, dict) else 'N/A'}")

                if isinstance(data, dict):
                    # Show first few items in detail
                    for i, (key, value) in enumerate(data.items()):
                        if i >= 3:
                            print(f"... ({len(data) - 3} more items)")
                            break

                        print(f"\n  KEY: {key}")
                        print(f"  VALUE TYPE: {type(value)}")

                        if isinstance(value, dict):
                            print(f"  VALUE KEYS: {list(value.keys())[:15]}")
                            # Show the actual values
                            for k, v in list(value.items())[:10]:
                                print(f"    {k}: {v}")
                        elif isinstance(value, list):
                            print(f"  VALUE: {value[:5]}...")
                        else:
                            print(f"  VALUE: {value}")

                break

    def load_defines(self):
        """Load defines to resolve @variable references."""
        print("\n=== LOADING DEFINES ===")

        defines_path = os.path.join(self.stellaris_path, 'common', 'defines')

        if not os.path.exists(defines_path):
            print("  Defines folder not found!")
            self.defines = {}
            return

        self.defines = {}

        for filename in sorted(os.listdir(defines_path)):
            if not filename.endswith('.txt'):
                continue

            filepath = os.path.join(defines_path, filename)

            try:
                with open(filepath, 'r', encoding='utf-8-sig') as f:
                    content = f.read()

                # DEBUG: Look for tier cost patterns in ALL files
                if '@tier' in content.lower() or 'tier0cost' in content.lower() or 'tier1cost' in content.lower():
                    print(f"\n  === {filename} contains tier cost patterns! ===")
                    # Find and print those lines
                    for line in content.split('\n'):
                        line_lower = line.lower()
                        if 'tier' in line_lower and 'cost' in line_lower:
                            print(f"    {line.strip()}")

                # Remove comments
                content = re.sub(r'#[^\n]*', '', content)

                # Find ALL word = number patterns anywhere
                for match in re.finditer(r'(\w+)\s*=\s*(-?\d+\.?\d*)', content):
                    key = match.group(1)
                    val = match.group(2)

                    try:
                        if '.' in val:
                            self.defines[key] = float(val)
                        else:
                            self.defines[key] = int(val)
                    except:
                        self.defines[key] = val

            except Exception as e:
                print(f"  Error reading {filename}: {e}")

        print(f"\n  Loaded {len(self.defines)} define values")

        # Show tier costs specifically
        print("\n  === Tier cost defines found ===")
        tier_costs = {k: v for k, v in self.defines.items() 
                    if 'tier' in k.lower() and ('cost' in k.lower() or 'weight' in k.lower())}
        if tier_costs:
            for k in sorted(tier_costs.keys()):
                print(f"    {k} = {tier_costs[k]}")
        else:
            print("    NONE FOUND - tier costs might be in a different file format")

    def _parse_defines_file(self, filepath):
        """
        Parse defines file - extracts all key=value pairs.
        """
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                content = f.read()
        except Exception as e:
            print(f"    Read error: {e}")
            return

        content = re.sub(r'#[^\n]*', '', content)

        # Find all key = number patterns (including inside braces)
        # This pattern matches: word = number
        for match in re.finditer(r'(\w+)\s*=\s*(-?\d+\.?\d*)', content):
            key = match.group(1)
            value_str = match.group(2)

            try:
                if '.' in value_str:
                    value = float(value_str)
                else:
                    value = int(value_str)
                self.defines[key] = value
            except:
                self.defines[key] = value_str

    def _extract_defines(self, data, prefix=''):
        """Recursively extract defines from nested structure."""
        if isinstance(data, dict):
            for key, value in data.items():
                full_key = f"{prefix}_{key}" if prefix else key

                if isinstance(value, (int, float, str)):
                    # Store with and without prefix
                    self.defines[key] = value
                    if prefix:
                        self.defines[full_key] = value
                elif isinstance(value, dict):
                    # Skip nested structures that aren't values
                    if '__values__' in value:
                        # It's a list-like dict
                        for i, v in enumerate(value['__values__']):
                            if isinstance(v, (int, float, str)):
                                self.defines[f"{full_key}_{i}"] = v
                    else:
                        self._extract_defines(value, full_key)

    def resolve_all_variables(self, data):
        """
        Recursively resolve all @variable references in a data structure.
        Works on dicts, lists, and strings.
        """
        if isinstance(data, dict):
            return {k: self.resolve_all_variables(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.resolve_all_variables(item) for item in data]
        elif isinstance(data, str):
            return self._resolve_variable_in_string(data)
        else:
            return data

    def _resolve_variable_in_string(self, text):
        """Resolve @variable in a string value."""
        if not isinstance(text, str):
            return text

        # Check if it's a single @variable
        if text.startswith('@'):
            var_name = text[1:]
            if var_name in self.defines:
                return self.defines[var_name]

        # Check for @variable anywhere in string
        pattern = r'@(\w+)'
        for match in re.finditer(pattern, text):
            var_name = match.group(1)
            if var_name in self.defines:
                text = text.replace(f"@{var_name}", str(self.defines[var_name]))

        return text
    
    def resolve_cost(self, value):
        """Resolve a cost value like @tier4cost2 to actual number."""
        if value is None:
            return 0

        if isinstance(value, (int, float)):
            return int(value)

        if isinstance(value, str):
            value = value.strip()

            if value.startswith('@'):
                var_name = value[1:]  # Remove @

                if var_name in self.defines:
                    resolved = self.defines[var_name]
                    if isinstance(resolved, (int, float)):
                        return int(resolved)
                    return self.resolve_cost(resolved)

            try:
                return int(float(value))
            except:
                pass

        return 0


            

# ============================================================================
# GUI APPLICATION
# ============================================================================

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading

class ExtractorApp:
    """GUI for the game data extractor."""

    def __init__(self, root):
        self.root = root
        self.root.title("Stellaris Game Data Extractor")
        self.root.geometry("700x550")
        self.root.configure(bg="#1a1a2e")

        self.stellaris_path = tk.StringVar()
        self.output_path = tk.StringVar(value="stellaris_game_data.json")
        self.status = tk.StringVar(value="Ready")
        self.debug_mode = tk.BooleanVar(value=True)

        self._setup_ui()
        self._auto_detect_path()

    def _setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background="#1a1a2e")
        style.configure("TLabel", background="#1a1a2e", foreground="#e0e0e0")
        style.configure("Header.TLabel", background="#1a1a2e", foreground="#00d4ff",
                        font=("Segoe UI", 14, "bold"))

        main = ttk.Frame(self.root, padding=20)
        main.pack(fill="both", expand=True)

        # Header
        ttk.Label(main, text="Stellaris Game Data Extractor", 
                  style="Header.TLabel").pack(pady=(0, 5))
        ttk.Label(main, text="Extracts clean, structured data from game files.",
                  foreground="#888888").pack(pady=(0, 15))

        # Stellaris path
        path_frame = ttk.Frame(main)
        path_frame.pack(fill="x", pady=5)
        ttk.Label(path_frame, text="Stellaris Installation:").pack(anchor="w")

        path_row = ttk.Frame(path_frame)
        path_row.pack(fill="x", pady=2)
        tk.Entry(path_row, textvariable=self.stellaris_path, 
                 bg="#16213e", fg="#e0e0e0",
                 font=("Consolas", 10)).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Button(path_row, text="Browse", 
                   command=self._browse_stellaris).pack(side="right")

        # Output path
        out_frame = ttk.Frame(main)
        out_frame.pack(fill="x", pady=10)
        ttk.Label(out_frame, text="Output File:").pack(anchor="w")

        out_row = ttk.Frame(out_frame)
        out_row.pack(fill="x", pady=2)
        tk.Entry(out_row, textvariable=self.output_path, 
                 bg="#16213e", fg="#e0e0e0",
                 font=("Consolas", 10)).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Button(out_row, text="Save As", 
                   command=self._browse_output).pack(side="right")

        # Options
        opt_frame = ttk.Frame(main)
        opt_frame.pack(fill="x", pady=10)
        ttk.Checkbutton(opt_frame, text="Debug output (verbose)", 
                        variable=self.debug_mode).pack(anchor="w")

        # Log area
        ttk.Label(main, text="Progress:", foreground="#888888").pack(anchor="w", pady=(10, 2))

        log_frame = tk.Frame(main, bg="#16213e")
        log_frame.pack(fill="both", expand=True, pady=5)

        self.log_text = tk.Text(log_frame, bg="#16213e", fg="#00ff88",
                                font=("Consolas", 9), wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", 
                                  command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=15)
        ttk.Button(btn_frame, text="Extract All Data", 
                   command=self._start_extraction).pack(side="left")
        ttk.Button(btn_frame, text="Quit", 
                   command=self.root.destroy).pack(side="right")

        # Status
        ttk.Label(main, textvariable=self.status, 
                  foreground="#888888").pack(pady=5)

    def _auto_detect_path(self):
        """Try to auto-detect Stellaris installation."""
        paths = [
            r"C:\Program Files (x86)\Steam\steamapps\common\Stellaris",
            r"C:\Program Files\Steam\steamapps\common\Stellaris",
            r"D:\SteamLibrary\steamapps\common\Stellaris",
            r"E:\SteamLibrary\steamapps\common\Stellaris",
            os.path.expanduser("~/.steam/steam/steamapps/common/Stellaris"),
            "/opt/steam/steamapps/common/Stellaris",
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
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")]
        )
        if path:
            self.output_path.set(path)

    def _log(self, msg):
        self.log_text.insert("end", f"{msg}\n")
        self.log_text.see("end")
        self.log_text.update()

    def _start_extraction(self):
        stellaris_path = self.stellaris_path.get()
        output_path = self.output_path.get()

        if not stellaris_path:
            messagebox.showerror("Error", "Please select Stellaris installation folder")
            return

        if not os.path.exists(os.path.join(stellaris_path, 'common')):
            messagebox.showerror("Error", "Invalid Stellaris folder (no 'common' directory)")
            return

        self.log_text.delete("1.0", "end")
        self.status.set("Extracting...")

        # Run in thread
        threading.Thread(
            target=self._extract_thread,
            args=(stellaris_path, output_path),
            daemon=True
        ).start()

    def _extract_thread(self, stellaris_path, output_path):
        try:
            extractor = StellarisGameExtractor(stellaris_path)
            extractor.debug = self.debug_mode.get()

            # Load localization first (for debug)
            self.root.after(0, lambda: self._log("Loading localization..."))
            extractor.load_localization()

            # === DEBUG MODE: Show file structure ===
            if extractor.debug:
                self.root.after(0, lambda: self._log("\n=== DEBUG: Citadel localization ==="))
                for key in sorted(extractor.localization.keys()):
                    if 'citadel' in key.lower():
                        val = extractor.localization[key][:80]
                        self.root.after(0, lambda k=key, v=val: self._log(f"  {k}: {v}"))

                self.root.after(0, lambda: self._log("\n=== DEBUG: Technology files ==="))
                tech_path = os.path.join(stellaris_path, 'common', 'technology')
                if os.path.exists(tech_path):
                    for filename in os.listdir(tech_path)[:2]:
                        if filename.endswith('.txt'):
                            filepath = os.path.join(tech_path, filename)
                            self.root.after(0, lambda f=filepath: self._log(f"\n--- {os.path.basename(f)} ---"))
                            extractor.debug_file_structure(filepath)

            # Now extract with progress callback
            def progress(msg):
                self.root.after(0, lambda m=msg: self._log(m))

            data = extractor.extract_all(progress_callback=progress)

            # Save
            self.root.after(0, lambda: self._log("\nSaving to JSON..."))

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Show results
            total = data['metadata']['total_entries']

            self.root.after(0, lambda: self._log(f"\nDone! {total} entries extracted"))
            self.root.after(0, lambda: self._log(f"Saved to: {output_path}"))
            self.root.after(0, lambda: self.status.set("Complete!"))

            messagebox.showinfo(
                "Success",
                f"Extracted {total} entries!\n\nSaved to:\n{output_path}"
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            err_msg = str(e)
            self.root.after(0, lambda: messagebox.showerror("Error", err_msg))
            self.root.after(0, lambda: self.status.set("Failed"))

    def _debug_loc(self, extractor, term):
        """Helper to show localization matches."""
        print(f"\n=== LOCALIZATION for '{term}' ===")
        count = 0
        for key in sorted(extractor.localization.keys()):
            if term.lower() in key.lower():
                val = extractor.localization[key]
                print(f"  {key}: {val[:100]}{'...' if len(val) > 100 else ''}")
                count += 1
                if count >= 30:
                    print(f"  ... (more matches)")
                    break            

if __name__ == "__main__":
    root = tk.Tk()
    app = ExtractorApp(root)
    root.mainloop()