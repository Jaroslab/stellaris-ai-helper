# save_parser.py
from zipfile import ZipFile

WHITESPACE = '\n \t'

class InMemoryFile:
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
            self.pos += 1  # Skip the delimiter
        return result

    def skip(self, skip_chars):
        while self.pos < self.size and self.data[self.pos] in skip_chars:
            self.pos += 1

def open_save(file):
    """Open a .sav file and return meta and gamestate."""
    print(f"\n=== open_save debug ===")

    with ZipFile(file) as zipped:
        print(f"  Files in zip: {zipped.namelist()}")

        for name in zipped.namelist():
            info = zipped.getinfo(name)
            print(f"    {name}: {info.file_size:,} bytes (compressed: {info.compress_size:,})")

        # Read meta
        meta_data = zipped.read('meta').decode('utf-8')
        print(f"\n  meta content length: {len(meta_data):,} chars")

        # Read gamestate
        gamestate_data = zipped.read('gamestate').decode('utf-8')
        print(f"\n  gamestate content length: {len(gamestate_data):,} chars")

        # Show where state={ starts
        state_pos = gamestate_data.find('state={')
        print(f"  'state={{' found at position: {state_pos}")

        if state_pos > 0:
            print(f"  Content before state={{:\n{gamestate_data[:state_pos]}")
            print(f"  Content at state={{:\n{gamestate_data[state_pos:state_pos+200]}")

        meta = InMemoryFile(meta_data)
        gamestate = InMemoryFile(gamestate_data)

        print("=== end open_save debug ===\n")
        return meta, gamestate

def save_valid(file):
    """Check if file is a valid Stellaris save."""
    try:
        with ZipFile(file) as zipped:
            return 'meta' in zipped.namelist() and 'gamestate' in zipped.namelist()
    except:
        return False

def parse_data(file):
    """Parse clausewitz format into Python dict."""
    print("  parse_data: Starting parse...")

    PARSING_DICT = 0
    PARSING_LIST = 1
    PARSING_DICT_OR_LIST = 2
    PARSING_OBJECT = 3
    PARSING_VALUE = 4

    states = [PARSING_DICT]
    current_object = [{}]
    can_reduce = False
    iterations = 0
    max_iterations = 10000000  # Safety limit

    def reduce_dict():
        if len(current_object) > 2 and isinstance(current_object[-3], dict):
            value = current_object.pop(-1)
            key = current_object.pop(-1)
            if key in current_object[-1]:
                if isinstance(current_object[-1][key], list):
                    current_object[-1][key].append(value)
                else:
                    current_object[-1][key] = [current_object[-1][key], value]
            else:
                current_object[-1][key] = value

    while not file.eof():
        iterations += 1
        if iterations % 100000 == 0:
            print(f"    Iteration {iterations}...")
        if iterations > max_iterations:
            print(f"  WARNING: Max iterations reached ({max_iterations}), returning partial data")
            # Don't break - try to reduce and return what we have
            break

        file.skip(WHITESPACE)
        if file.eof():
            print(f"  EOF reached at iteration {iterations}")
            break
        if not states:
            print(f"  States empty at iteration {iterations}")
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
            if not name:  # Safety check
                print(f"  WARNING: Empty name at pos {file.pos}")
                continue
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
            # Determine if this is a dict (has key=value) or list (just values)
            # Skip any whitespace first
            saved_pos = file.pos
            file.skip(WHITESPACE)

            # Peek ahead to find what comes next
            peek_content = file.peekto('=}{')

            # Calculate position of actual delimiter
            delim_pos = file.pos + len(peek_content)

            # Get the actual delimiter character
            if delim_pos < file.size:
                delim = file.data[delim_pos]
            else:
                delim = ''

            # Restore position (we'll re-skip in the dict/list parsing)
            file.pos = saved_pos

            if delim == '=':
                # It's a dict: key=value pairs inside
                can_reduce = False
                current_object.append({})
                states[-1] = PARSING_DICT
            else:
                # It's a list: just values inside
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
                current_object.append(''.join(result))
            else:
                value_str = file.readto(WHITESPACE)
                if not value_str:
                    states.pop(-1)
                    continue
                try:
                    if '.' in value_str:
                        current_object.append(float(value_str))
                    else:
                        current_object.append(int(value_str))
                except ValueError:
                    current_object.append(value_str)
            states.pop(-1)

    reduce_dict()
    print(f"  parse_data: Done ({iterations} iterations)")
    return current_object[0] if current_object else {}

def parse_save(file):
    """Parse a Stellaris save file and return (meta, state) tuple."""
    print(f"Parsing save file: {file}")
    meta_file, state_file = open_save(file)

    print("  Parsing meta...")
    meta = parse_data(meta_file)
    print(f"  Meta parsed: {len(str(meta))} chars")

    print("  Parsing gamestate...")
    gamestate = parse_data(state_file)
    print(f"  Gamestate parsed: {len(str(gamestate))} chars")
    print(f"  Gamestate keys: {list(gamestate.keys())}")

    # NEW: Handle new format where gamestate has header + state={}
    if 'state' in gamestate:
        print("  Found 'state' key in gamestate - extracting actual state")
        state = gamestate['state']
        print(f"  Extracted state keys: {list(state.keys())[:10]}")
    else:
        # Old format - gamestate IS the state
        state = gamestate

    return meta, state