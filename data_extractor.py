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
    if 'country' not in state:
        return None

    empire = state['country'].get(empire_id)
    if not isinstance(empire, dict):
        return None

    # Military power is stored at country level
    # Note: This may include power from allies/subjects in some cases
    military_power = empire.get('military_power', 0)

    return {
        'total': 1 if military_power > 0 else 0,
        'total_power': round(military_power, 1),
        'fleets': {}
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

        # Completed techs
        completed = tech_status.get('technology', {})
        if isinstance(completed, list):
            completed_count = len(completed)
        elif isinstance(completed, dict):
            completed_count = len(completed)
        else:
            completed_count = 0

        # Current research queues
        current_research = {}

        for queue_name, queue_key in [
            ('physics', 'physics_queue'),
            ('society', 'society_queue'),
            ('engineering', 'engineering_queue')
        ]:
            queue = tech_status.get(queue_key, [])
            if queue and isinstance(queue, list) and len(queue) > 0:
                first_item = queue[0]
                if isinstance(first_item, dict):
                    tech_name = first_item.get('technology', 'Unknown')
                    progress = first_item.get('progress', 0)
                    # Check if it's a special project
                    is_project = 'special_project' in first_item
                    current_research[queue_name] = {
                        'tech': tech_name,
                        'progress': progress,
                        'is_project': is_project
                    }

        # Research output from budget
        budget = empire.get('budget', {}).get('current_month', {}).get('income', {})
        physics = 0
        society = 0
        engineering = 0

        for source, values in budget.items():
            if isinstance(values, dict):
                physics += float(values.get('physics_research', 0))
                society += float(values.get('society_research', 0))
                engineering += float(values.get('engineering_research', 0))

        return {
            'completed_count': completed_count,
            'current_research': current_research,
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
    planets = []
    total_pops = 0

    planet_dict = state.get('planets', {}).get('planet', {})

    for pid, planet in planet_dict.items():
        if not isinstance(planet, dict):
            continue
        if planet.get('owner') != empire_id:
            continue

        # Count pops from pop_groups (not 'pop' field)
        planet_pops = 0
        pop_groups = planet.get('pop_groups', {})
        if isinstance(pop_groups, dict):
            for group_id, group_data in pop_groups.items():
                if isinstance(group_data, dict) and 'pops' in group_data:
                    pops = group_data['pops']
                    if isinstance(pops, list):
                        planet_pops += len(pops)
                    elif isinstance(pops, dict):
                        planet_pops += len(pops)

        # Also check num_sapient_pops field
        if planet_pops == 0 and 'num_sapient_pops' in planet:
            planet_pops = planet.get('num_sapient_pops', 0)

        total_pops += planet_pops

        planets.append({
            'name': planet.get('name', 'Unknown'),
            'pops': planet_pops,
            'districts': len(planet.get('districts', {})) if isinstance(planet.get('districts'), dict) else 0,
            'buildings': len(planet.get('buildings_cache', {})) if isinstance(planet.get('buildings_cache'), dict) else 0,
            'stability': planet.get('stability', 0),
            'crime': planet.get('crime', 0)
        })

    return {
        'total': len(planets),
        'total_pops': total_pops,
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

def debug_save_structure(state, empire_id=0):
    """Print detailed structure of save data for debugging."""
    print("\n" + "="*60)
    print("SAVE DATA STRUCTURE DEBUG")
    print("="*60)

    # 1. POP DATA
    print("\n--- POP DATA ---")
    if 'pop' in state:
        pop_data = state['pop']
        print(f"state['pop'] exists: {type(pop_data)}")
        if isinstance(pop_data, dict):
            print(f"  Total pops: {len(pop_data)}")
            # Show first pop structure
            if pop_data:
                first_pop_key = list(pop_data.keys())[0]
                first_pop = pop_data[first_pop_key]
                print(f"  First pop key: {first_pop_key}")
                print(f"  First pop fields: {list(first_pop.keys()) if isinstance(first_pop, dict) else type(first_pop)}")
        elif isinstance(pop_data, list):
            print(f"  Total pops: {len(pop_data)}")
    else:
        print("state['pop'] NOT FOUND")

    # 2. FLEET DATA
    print("\n--- FLEET DATA ---")
    if 'fleet' in state:
        fleet_data = state['fleet']
        print(f"state['fleet'] exists: {type(fleet_data)}")
        if isinstance(fleet_data, dict):
            print(f"  Total fleets: {len(fleet_data)}")
            # Find player fleets
            player_fleets = []
            for fid, fleet in fleet_data.items():
                if isinstance(fleet, dict) and fleet.get('owner') == empire_id:
                    player_fleets.append((fid, fleet))
            print(f"  Player fleets (owner={empire_id}): {len(player_fleets)}")

            if player_fleets:
                fid, first_fleet = player_fleets[0]
                print(f"  First fleet fields: {list(first_fleet.keys())}")
                print(f"  military_power: {first_fleet.get('military_power', 'N/A')}")
                print(f"  ships: {first_fleet.get('ships', 'N/A')}")
    else:
        print("state['fleet'] NOT FOUND")

    # 3. SHIP DATA (separate from fleet)
    print("\n--- SHIP DATA ---")
    if 'ships' in state:
        ships_data = state['ships']
        print(f"state['ships'] exists: {type(ships_data)}")
        if isinstance(ships_data, dict):
            print(f"  Total ships: {len(ships_data)}")
    else:
        print("state['ships'] NOT FOUND")

    # FLEET DEBUG - Find why owner matching fails
    print("\n--- FLEET OWNER DEBUG ---")
    if 'fleet' in state:
        for fid, fleet in list(state['fleet'].items())[:5]:
            print(f"  Fleet {fid}: owner={fleet.get('owner')}, type={type(fleet.get('owner'))}")

    print("\n--- SHIP OWNER DEBUG ---")
    if 'ships' in state:
        for sid, ship in list(state['ships'].items())[:5]:
            print(f"  Ship {sid}: owner={ship.get('owner')}, type={type(ship.get('owner'))}")

    # 4. TECH DATA
    print("\n--- TECH DATA ---")
    countries = state.get('country', {})
    empire = countries.get(empire_id, {})

    if 'tech_status' in empire:
        tech_status = empire['tech_status']
        print(f"tech_status exists: {type(tech_status)}")
        if isinstance(tech_status, dict):
            print(f"  tech_status fields: {list(tech_status.keys())}")

            # Look for completed techs
            if 'technology' in tech_status:
                techs = tech_status['technology']
                print(f"  technology type: {type(techs)}")
                if isinstance(techs, dict):
                    print(f"  Completed techs count: {len(techs)}")
                    # Show first few
                    for i, (tech_id, tech_data) in enumerate(techs.items()):
                        if i >= 3:
                            break
                        print(f"    {tech_id}: {type(tech_data)}")
                        if isinstance(tech_data, dict):
                            print(f"      fields: {list(tech_data.keys())[:5]}")

            # Alternative locations
            for key in tech_status.keys():
                if 'progress' in key.lower() or 'research' in key.lower() or 'complete' in key.lower():
                    print(f"  Found '{key}': {tech_status[key]}")
    else:
        print("tech_status NOT FOUND in empire")

    # 5. ECONOMY/RESOURCE DATA
    print("\n--- RESOURCE DATA ---")
    if 'modules' in empire:
        modules = empire['modules']
        print(f"modules exists: {type(modules)}")
        if isinstance(modules, dict):
            print(f"  module keys: {list(modules.keys())[:10]}")

            # Look for economy module
            for mod_name in ['standard_economy_module', 'economy', 'resources']:
                if mod_name in modules:
                    mod = modules[mod_name]
                    print(f"\n  {mod_name}:")
                    if isinstance(mod, dict):
                        print(f"    fields: {list(mod.keys())}")
                        if 'resources' in mod:
                            print(f"    resources: {mod['resources']}")
    else:
        print("modules NOT FOUND in empire")

    # Budget data
    if 'budget' in empire:
        budget = empire['budget']
        print(f"\nbudget exists: {type(budget)}")
        if isinstance(budget, dict):
            print(f"  budget fields: {list(budget.keys())}")
            if 'current_month' in budget:
                cm = budget['current_month']
                print(f"  current_month fields: {list(cm.keys()) if isinstance(cm, dict) else cm}")
    else:
        print("budget NOT FOUND in empire")

    # 6. PLANET DATA
    print("\n--- PLANET DATA ---")
    if 'planets' in state:
        planets_data = state['planets']
        print(f"state['planets'] exists: {type(planets_data)}")
        if isinstance(planets_data, dict):
            if 'planet' in planets_data:
                planets = planets_data['planet']
                print(f"  Total planets: {len(planets) if isinstance(planets, dict) else 'N/A'}")
            else:
                print(f"  planets_data keys: {list(planets_data.keys())[:5]}")
    else:
        print("state['planets'] NOT FOUND")

    # Look for planets owned by player
    print(f"\n  Looking for planets owned by empire {empire_id}...")
    planet_count = 0
    if 'planets' in state and isinstance(state['planets'], dict):
        planet_dict = state['planets'].get('planet', state['planets'])
        for pid, planet in (planet_dict.items() if isinstance(planet_dict, dict) else []):
            if isinstance(planet, dict) and planet.get('owner') == empire_id:
                planet_count += 1
                if planet_count == 1:  # Show first planet structure
                    print(f"  First planet fields: {list(planet.keys())}")
                    if 'pop' in planet:
                        print(f"    planet['pop']: {planet['pop']}")
                    if 'pop_charts' in planet:
                        print(f"    planet['pop_charts']: {type(planet['pop_charts'])}")
    print(f"  Planets owned by player: {planet_count}")

    print("\n" + "="*60)
    print("END DEBUG")
    print("="*60 + "\n")