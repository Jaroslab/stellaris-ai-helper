# data_extractor.py
"""Extract structured data from parsed Stellaris saves."""

def parse_date(date_str):
    """Parse date string like '2240.06.15' into dict."""
    comps = str(date_str).split('.')
    if len(comps) != 3:
        return {'y': 0, 'm': 0, 'd': 0}
    return {
        'y': int(comps[0]),
        'm': int(comps[1]),
        'd': int(comps[2])
    }

def get_empires(state):
    """Get list of all empires in the save."""
    if 'country' not in state:
        return {}

    empires = {}
    for cid, empire in state['country'].items():
        if not isinstance(empire, dict):
            continue

        # Try to get name - it might be in different places
        name = None

        # Try name field first
        if 'name' in empire:
            name = empire['name']
            if isinstance(name, dict):
                # Handle localized name format
                name = name.get('key', name.get('name', 'Unknown'))
        elif 'key' in empire:
            name = empire['key']

        # Skip if no name found
        if not name:
            continue

        # Skip template/internal names
        if isinstance(name, str) and name.startswith('EMPIRE_DESIGN_'):
            # Try to get a cleaner name
            if 'name_data' in empire:
                name = empire['name_data']
            elif 'custom_name' in empire:
                name = empire['custom_name']

        empires[cid] = name

    return empires

def get_player_empire(state):
    """Find the player's empire ID."""
    print(f"\n=== get_player_empire called ===")
    print(f"  state is None? {state is None}")

    if state is None:
        print("  Returning None - state is None")
        return None

    if 'player' not in state:
        print("  'player' not in state, searching country...")
        # Try to find empire with player_name
        countries = state.get('country', {})
        print(f"  countries type: {type(countries)}")
        print(f"  countries count: {len(countries) if isinstance(countries, dict) else 'N/A'}")

        for cid, empire in countries.items():
            if isinstance(empire, dict):
                has_player_name = empire.get('player_name')
                print(f"    Country {cid}: player_name = {has_player_name}")
                if has_player_name:
                    print(f"  Found player empire: {cid}")
                    return cid
        print("  No player_name found in any country")
        return None

    players = state['player']
    print(f"  'player' found: {players}")
    print(f"  player type: {type(players)}")

    if isinstance(players, list) and len(players) > 0:
        first_player = players[0]
        print(f"  First player: {first_player}")
        if isinstance(first_player, dict):
            country = first_player.get('country')
            print(f"  Country from player: {country}")
            return country  # Can be 0, which is valid!
        print("  First player is not a dict")
        return None

    print("  Returning None - unexpected player format")
    return None

def get_economy(state, empire_id):
    """Extract economy data for an empire."""
    if 'country' not in state:
        return None

    empire = state['country'].get(empire_id)
    if not isinstance(empire, dict):
        return None

    try:
        resources = empire.get('modules', {}).get('standard_economy_module', {}).get('resources', {})
        budget = empire.get('budget', {}).get('current_month', {})

        return {
            'stockpile': resources,
            'income': budget.get('income', {}),
            'spending': budget.get('expenses', {})
        }
    except (KeyError, TypeError, AttributeError):
        return None

def get_fleets(state, empire_id):
    """Extract fleet data for an empire."""
    if 'fleet' not in state:
        return None

    empire_fleets = {}

    for fid, fleet in state['fleet'].items():
        if not isinstance(fleet, dict):
            continue
        if fleet.get('owner') != empire_id:
            continue
        if fleet.get('civilian') == 'yes' or fleet.get('station') == 'yes':
            continue

        empire_fleets[fid] = {
            'power': fleet.get('military_power', 0),
            'ships': len(fleet.get('ships', [])),
            'name': fleet.get('name', 'Unknown')
        }

    return {
        'total': len(empire_fleets),
        'total_power': sum(f['power'] for f in empire_fleets.values()),
        'fleets': empire_fleets
    }

def get_tech(state, empire_id):
    """Extract technology data for an empire."""
    if 'country' not in state:
        return None

    empire = state['country'].get(empire_id)
    if not isinstance(empire, dict):
        return None

    try:
        tech_status = empire.get('tech_status', {})
        completed = tech_status.get('technology', {})

        # Get research output from budget
        budget = empire.get('budget', {}).get('current_month', {}).get('income', {})
        physics = sum(v.get('physics_research', 0) for v in budget.values() if isinstance(v, dict))
        society = sum(v.get('society_research', 0) for v in budget.values() if isinstance(v, dict))
        engineering = sum(v.get('engineering_research', 0) for v in budget.values() if isinstance(v, dict))

        return {
            'completed_count': len(completed) if isinstance(completed, dict) else 0,
            'research_output': {
                'physics': physics,
                'society': society,
                'engineering': engineering,
                'total': physics + society + engineering
            }
        }
    except (KeyError, TypeError, AttributeError):
        return None

def get_planets(state, empire_id):
    """Extract planet data for an empire."""
    if 'planets' not in state:
        return None

    planets = []

    for pid, planet in state['planets'].get('planet', {}).items():
        if not isinstance(planet, dict):
            continue
        if planet.get('owner') != empire_id:
            continue

        planets.append({
            'name': planet.get('name', 'Unknown'),
            'pops': len(planet.get('pop', [])),
            'districts': len(planet.get('district', {})),
            'buildings': len(planet.get('buildings', [])),
            'stability': planet.get('stability', 0),
            'crime': planet.get('crime', 0)
        })

    return {
        'total': len(planets),
        'total_pops': sum(p['pops'] for p in planets),
        'planets': planets
    }

def extract_summary(state, empire_id=None):
    """Extract a summary of the empire's current state."""
    print(f"\n=== extract_summary called ===")
    print(f"  empire_id: {empire_id}")

    if empire_id is None:
        empire_id = get_player_empire(state)
        print(f"  empire_id from get_player_empire: {empire_id}")

    if empire_id is None:
        print("  Returning None - no empire_id")
        return None

    countries = state.get('country', {})
    print(f"  countries keys (first 5): {list(countries.keys())[:5]}")

    empire = countries.get(empire_id)
    print(f"  empire for id {empire_id}: {type(empire)}")

    if not isinstance(empire, dict):
        print("  Returning None - empire is not a dict")
        return None

    # Get date
    date_str = state.get('date', '2200.1.1')
    date = parse_date(date_str)

    # Get empire name - check TOP LEVEL first!
    # For player empires (ID 0), the real name is at state["name"]
    name = None

    # If player empire (usually ID 0), use the top-level save name
    if empire_id == 0 or empire_id == '0':
        name = state.get('name') 
        print(f"  Got name from top-level state: {name}")

    # Fallback: check empire dict for name
    if not name:
        name = empire.get('name', 'Unknown')
        if isinstance(name, dict):
            name = name.get('key', 'Unknown')

        # Clean up internal names
        if isinstance(name, str) and name.startswith('EMPIRE_DESIGN_'):
            # Try custom_name or name_data
            if 'custom_name' in empire:
                name = empire['custom_name']
            elif 'name_data' in empire:
                name = empire['name_data']
            else:
                # Clean the internal name
                name = name.replace('EMPIRE_DESIGN_', '').replace('_', ' ').title()

    if not name:
        name = 'Unknown Empire'

    print(f"  Final empire name: {name}")

    economy = get_economy(state, empire_id)
    fleets = get_fleets(state, empire_id)
    tech = get_tech(state, empire_id)
    planets = get_planets(state, empire_id)

    summary = {
        'date': date_str,
        'date_components': date,
        'empire_id': empire_id,
        'empire_name': name,
    }

    if economy:
        summary['economy'] = economy
    if fleets:
        summary['fleets'] = fleets
    if tech:
        summary['tech'] = tech
    if planets:
        summary['planets'] = planets

    print(f"  Summary keys: {list(summary.keys())}")
    print("=== extract_summary done ===\n")

    return summary