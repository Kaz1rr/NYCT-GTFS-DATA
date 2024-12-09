import csv
import time
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_session import Session
from datetime import datetime
from collections import defaultdict
from dateutil import parser

app = Flask(__name__, template_folder="templates")
app.secret_key = 'your-secret-key-here'
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Default settings
DEFAULT_SETTINGS = {
    'text_color': '#00ffff',
    'glow_strength': '15'
}

TRANSITER_BASE_URL = "https://demo.transiter.dev"

def get_line_name(stop_id):
    route_id = stop_id[0]
    base_url = f"{TRANSITER_BASE_URL}/systems/us-ny-subway/routes/{route_id}"

    try:
        response = requests.get(base_url)
        response.raise_for_status()
        route_data = response.json()
        train_name = route_data.get("shortName", "Unknown Train")
        
        # Special handling for shuttles
        if train_name == "S":
            if route_id == "GS":
                return "42nd Street Shuttle"
            elif route_id == "FS":
                return "Franklin Avenue Shuttle"
            elif route_id == "H":
                return "Rockaway Shuttle"
            else:
                return "Shuttle"
        return train_name
    except requests.exceptions.RequestException as e:
        print(f"Error fetching route info for {route_id}: {e}")
        return "Unknown Train"

def parse_stops(file_path, specific_line_stops=None):
    lines_stations = {}
    
    with open(file_path, newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            stop_id = row["stop_id"]
            stop_name = row["stop_name"]
            
            # Skip if it's a child station (ends with N or S)
            if stop_id[-1] in ['N', 'S']:
                continue
            
            # If specific stops are provided, only include those
            if specific_line_stops:
                for line, stops in specific_line_stops.items():
                    if stop_id in stops:
                        if stop_id not in lines_stations:
                            lines_stations[stop_id] = {
                                "stop_id": stop_id,
                                "stop_name": stop_name,
                                "stop_lat": float(row["stop_lat"]),
                                "stop_lon": float(row["stop_lon"])
                            }
            
    return lines_stations

def get_upcoming_trains_for_stop(stop_id, lines_stations):
    """Get upcoming train arrivals for a specific stop."""
    stop_ids = [stop_id]
    
    if stop_id[-1] not in ['N', 'S']:
        stop_ids.extend([f"{stop_id}N", f"{stop_id}S"])
    
    all_train_info = []
    seen_trains = set()
    
    for current_stop_id in stop_ids:
        url = f"{TRANSITER_BASE_URL}/systems/us-ny-subway/stops/{current_stop_id}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Error fetching data for stop {current_stop_id}: {e}")
            continue

        now = time.time()
        upcoming_trains = [stop_time for stop_time in data.get("stopTimes", []) 
                         if float(stop_time["departure"].get("time", 0)) > (now - 60)][:5]  # Allow slightly past trains and show more per direction

        for stop_time in upcoming_trains:
            departure_time = stop_time.get("departure", {}).get("time", None)

            if departure_time is None:
                continue

            seconds_to_leave = float(departure_time) - now
            minutes = int(seconds_to_leave / 60)

            trip_info = stop_time.get("trip", {})
            route_id = trip_info.get("route", {}).get("id", "Unknown")
            route_name = get_line_name(route_id)
            destination = trip_info.get("destination", {}).get("name", "Unknown")
            headsign = stop_time.get("headsign", "Unknown")
            trip_id = trip_info.get("id", "Unknown")

            # Only skip if we really have no useful information
            if destination == "Unknown" and headsign == "Unknown":
                continue
            if route_name == "Unknown Line":
                continue

            train_key = f"{route_name}-{destination}-{departure_time}"
            if train_key not in seen_trains:
                seen_trains.add(train_key)
                train_info = {
                    "route_name": route_name,
                    "destination": destination or headsign,
                    "headsign": headsign,
                    "departure_in_minutes": max(0, minutes)
                }
                all_train_info.append(train_info)
    
    # Sort by departure time and show more trains
    return sorted(all_train_info, key=lambda x: x["departure_in_minutes"])[:5]

def get_stop_name(stop_id):
    url = f"{TRANSITER_BASE_URL}/systems/us-ny-subway/stops/{stop_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data["name"]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching station name for {stop_id}: {e}")
        return "Unknown Station"

def get_transfers_for_stop(stop_id):
    # Clean the stop_id by removing any /realtime suffix
    if '/realtime' in stop_id:
        stop_id = stop_id.replace('/realtime', '')
    
    url = f"{TRANSITER_BASE_URL}/systems/us-ny-subway/stops/{stop_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        transfers = data.get('transfers', [])
        processed_transfers = []
        for transfer in transfers:
            from_route = transfer['fromStop']['id'][0]
            to_route = transfer['toStop']['id'][0]
            
            # Handle special cases for shuttles
            if from_route in ['H', 'S', 'FS']:
                if from_route == 'H':
                    from_route = 'h'  # Rockaway
                elif from_route == 'FS':
                    from_route = 'fs'  # Franklin
                else:
                    from_route = 's'  # 42nd St
                    
            if to_route in ['H', 'S', 'FS']:
                if to_route == 'H':
                    to_route = 'h'  # Rockaway
                elif to_route == 'FS':
                    to_route = 'fs'  # Franklin
                else:
                    to_route = 's'  # 42nd St
            
            # Clean the stop IDs by removing any /realtime suffix
            from_stop_id = transfer['fromStop']['id']
            to_stop_id = transfer['toStop']['id']
            if '/realtime' in from_stop_id:
                from_stop_id = from_stop_id.replace('/realtime', '')
            if '/realtime' in to_stop_id:
                to_stop_id = to_stop_id.replace('/realtime', '')
            
            transfer_info = {
                'from_stop': transfer['fromStop']['name'],
                'to_stop': transfer['toStop']['name'],
                'from_route': from_route.lower(),
                'to_route': to_route.lower(),
                'from_stop_id': from_stop_id,
                'to_stop_id': to_stop_id
            }
            processed_transfers.append(transfer_info)
        return processed_transfers
    except requests.exceptions.RequestException as e:
        print(f"Error fetching transfers for {stop_id}: {e}")
        return []

def get_route_for_stop(stop_id):
    url = f"{TRANSITER_BASE_URL}/systems/us-ny-subway/stops/{stop_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        route_id = data.get("route", {}).get("id", "Unknown")
        return get_line_name(route_id)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching route for {stop_id}: {e}")
        return "Unknown Route"

def get_headways_for_stop(stop_id):
    # Clean the stop_id by removing any /realtime suffix if present
    if '/realtime' in stop_id:
        stop_id = stop_id.replace('/realtime', '')
        
    url = f"{TRANSITER_BASE_URL}/systems/us-ny-subway/stops/{stop_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        headways = []
        if 'data' in data:
            for route in data['data']:
                route_id = route['route']['id']
                if 'headways' in route:
                    headway_info = {
                        'route_id': route_id,
                        'scheduled': route['headways'].get('scheduled'),
                        'observed': route['headways'].get('observed')
                    }
                    headways.append(headway_info)
        return headways
    except requests.exceptions.RequestException as e:
        print(f"Error fetching headways for {stop_id}: {e}")
        return []

def map_stops_to_trunk_lines():
    # Define trunk lines and their associated services
    trunk_lines = {
        'Eighth Avenue Line': ['A', 'C', 'E'],
        'Sixth Avenue Line': ['B', 'D', 'F', 'M'],
        'Crosstown Line': ['G'],
        'Canarsie Line': ['L'],
        'Nassau Street Line': ['J', 'Z'],
        'Broadway Line': ['N', 'Q', 'R', 'W'],
        'Broadway–Seventh Avenue Line': ['1', '2', '3'],
        'Lexington Avenue Line': ['4', '5', '6'],
        'Flushing Line': ['7'],
        'Second Avenue Line': ['T'],
        'Shuttles': ['S'],
    }
    
    # Define trunk line colors
    trunk_line_colors = {
        'Eighth Avenue Line': '#0039e6',      # Blue
        'Sixth Avenue Line': '#ff6319',       # Orange
        'Crosstown Line': '#6cbe45',          # Lime
        'Canarsie Line': '#a7a9ac',          # Light slate gray
        'Nassau Street Line': '#996633',      # Brown
        'Broadway Line': '#fccc0a',           # Yellow
        'Broadway–Seventh Avenue Line': '#ee352e',  # Red
        'Lexington Avenue Line': '#00933c',   # Green
        'Flushing Line': '#b933ad',          # Purple
        'Second Avenue Line': '#00add0',      # Turquoise
        'Shuttles': '#808183'                 # Dark slate gray
    }
    
    # Create reverse mapping from service to trunk line
    service_to_trunk = {}
    for trunk, services in trunk_lines.items():
        for service in services:
            service_to_trunk[service] = trunk
    
    stop_to_trunk = {}
    trunk_to_stops = {}
    
    with open('stops.txt', 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            stop_id = row['stop_id']
            stop_name = row['stop_name']
            location_type = row.get('location_type', '')
            
            # Skip if it's a child station (ends with N or S)
            if stop_id[-1] in ['N', 'S']:
                continue
                
            # Get the service letter/number from stop_id
            service = stop_id[0]
            
            # If this service belongs to a trunk line
            if service in service_to_trunk:
                trunk = service_to_trunk[service]
                stop_to_trunk[stop_id] = trunk
                
                # Initialize trunk_to_stops[trunk] if not exists
                if trunk not in trunk_to_stops:
                    trunk_to_stops[trunk] = []
                    
                # Add stop info to trunk_to_stops
                trunk_to_stops[trunk].append({
                    'stop_id': stop_id,
                    'stop_name': stop_name,
                    'service': service
                })
    
    return stop_to_trunk, trunk_to_stops, trunk_line_colors

@app.route('/')
def index():
    valid_lines = ['1', '2', '3', '4', '5', '6', '7', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'J', 'L', 'M', 'N', 'Q', 'R', 'S', 'T', "H", "W", "9", "FS", "GS", "SIR"]
    settings = session.get('settings', DEFAULT_SETTINGS)
    return render_template('index.html', services=valid_lines, settings=settings)

@app.route('/service/<line>')
def service(line):
    # Get trunk line mappings
    stop_to_trunk, trunk_to_stops, trunk_line_colors = map_stops_to_trunk_lines()
    
    # Get the trunk line for this service
    trunk_lines = {
        'Eighth Avenue Line': ['A', 'C', 'E'],
        'Sixth Avenue Line': ['B', 'D', 'F', 'M'],
        'Crosstown Line': ['G'],
        'Canarsie Line': ['L'],
        'Nassau Street Line': ['J', 'Z'],
        'Broadway Line': ['N', 'Q', 'R', 'W'],
        'Broadway–Seventh Avenue Line': ['1', '2', '3'],
        'Lexington Avenue Line': ['4', '5', '6'],
        'Flushing Line': ['7'],
        'Second Avenue Line': ['T'],
        'Shuttles': ['S'],
        '42nd Street Shuttle': ['GS'],
        'Franklin Avenue Shuttle': ['FS'],
        'Rockaway Park Shuttle': ['H'],
    }
    
    current_trunk = None
    for trunk, services in trunk_lines.items():
        if line in services:
            current_trunk = trunk
            break
    
    if current_trunk is None:
        return "Invalid line", 404
        
    # Get all stops for this trunk line
    trunk_groups = {}
    if current_trunk in trunk_to_stops:
        trunk_groups[current_trunk] = trunk_to_stops[current_trunk]
    
    # Get settings
    settings = session.get('settings', DEFAULT_SETTINGS)
    
    return render_template('service.html', 
                         line=line,
                         trunk_groups=trunk_groups,
                         trunk_line_colors=trunk_line_colors,
                         settings=settings)

@app.route('/traininfo/<stop_id>')
def train_info(stop_id):
    stop_name = get_stop_name(stop_id)
    if not stop_name:
        return "Stop not found", 404

    lines_stations = parse_stops('stops.txt')
    train_info = get_upcoming_trains_for_stop(stop_id, lines_stations)
    transfers = get_transfers_for_stop(stop_id)
    
    # Get trunk line info for this stop
    stop_to_trunk, trunk_to_stops, trunk_line_colors = map_stops_to_trunk_lines()
    trunk_line = None
    if stop_id in stop_to_trunk:
        trunk_line = stop_to_trunk[stop_id]
    
    # Get the user's settings or use defaults
    settings = session.get('settings', {
        'text_color': '#39FF14',
        'glow_strength': '10'
    })

    return render_template('traininfo.html', 
                         stop_name=stop_name,
                         train_info=train_info,
                         transfers=transfers,
                         trunk_line=trunk_line,
                         trunk_line_colors=trunk_line_colors,
                         settings=settings)

@app.route('/get_stops/<service>', methods=['GET'])
def get_stops(service):
    lines_stations = parse_stops(r"stops.txt")
    stops = lines_stations.get(service, [])
    return jsonify(stops)

@app.route('/search', methods=['POST'])
def search():
    parent_station = request.form['parent_station']
    lines_stations = parse_stops(r"stops.txt")
    
    train_info = get_upcoming_trains_for_stop(parent_station, lines_stations)
    transfers = get_transfers_for_stop(parent_station)

    lines_info = set()
    for line, stations in lines_stations.items():
        for station in stations:
            if station["stop_id"] == parent_station:
                lines_info.add(line)

    stop_name = get_stop_name(parent_station)

    settings = session.get('settings', DEFAULT_SETTINGS)
    return render_template('index.html',
                         stop_name=stop_name,
                         train_info=train_info,
                         lines_info=lines_info,
                         transfers=transfers,
                         settings=settings)

@app.route('/get_train_info', methods=['GET'])
def get_train_info():
    stop_id = request.args.get('stop_id')
    lines_stations = parse_stops(r"stops.txt")
    
    train_info = get_upcoming_trains_for_stop(stop_id, lines_stations)
    stop_name = get_stop_name(stop_id)
    transfers = get_transfers_for_stop(stop_id)

    return jsonify({
        'stop_name': stop_name,
        'train_info': train_info,
        'transfers': transfers
    })

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        # Update settings
        new_settings = {
            'text_color': request.form.get('text_color', DEFAULT_SETTINGS['text_color']),
            'glow_strength': request.form.get('glow_strength', DEFAULT_SETTINGS['glow_strength'])
        }
        session['settings'] = new_settings
        return redirect(url_for('index'))
    
    # Get current settings from session or use defaults
    settings = session.get('settings', DEFAULT_SETTINGS)
    return render_template('settings.html', settings=settings)

@app.route('/stop/<stop_id>')
def stop(stop_id):
    # Clean the stop_id by removing any /realtime suffix
    if '/realtime' in stop_id:
        stop_id = stop_id.replace('/realtime', '')
        
    url = f"{TRANSITER_BASE_URL}/systems/us-ny-subway/stops/{stop_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        station_name = data.get('name', 'Unknown Station')
        
        # Get the lines_stations data
        lines_stations = parse_stops(r"stops.txt")
        
        # Get upcoming trains
        train_info = get_upcoming_trains_for_stop(stop_id, lines_stations)
        
        # Calculate arrival times
        current_time = time.time()
        for info in train_info:
            if info['departure_in_minutes'] is not None:
                arrival_time_sec = info['departure_in_minutes'] * 60
                info['arrival_time'] = max(1, int(arrival_time_sec / 60)) if arrival_time_sec > 0 else None
            else:
                info['arrival_time'] = None
            
            # Extract just the route ID (number or letter)
            info['route_id'] = info['route_name'].split()[0]

        # Sort by arrival time
        train_info.sort(key=lambda x: x['arrival_time'] if x['arrival_time'] is not None else float('inf'))
        
        # Get transfers and headways
        transfers = get_transfers_for_stop(stop_id)
        headways = get_headways_for_stop(stop_id)
        
        settings = session.get('settings', DEFAULT_SETTINGS)
        return render_template('traininfo.html', 
                            station_name=station_name,
                            trains=train_info,
                            transfers=transfers,
                            headways=headways,
                            settings=settings)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching stop info for {stop_id}: {e}")
        return "Station not found", 404

@app.context_processor
def inject_settings():
    # Make settings available to all templates
    settings = session.get('settings', DEFAULT_SETTINGS)
    return {
        'text_color': settings['text_color'],
        'glow_strength': settings['glow_strength']
    }

if __name__ == '__main__':
    app.run(debug=True, port=5002, host='0.0.0.0')
