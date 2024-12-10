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
    'glow_strength': '15',
    'font_link': 'https://fonts.googleapis.com/css2?family=Jersey+25+Charted&display=swap',
    'font_size': '16'
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
                         if float(stop_time["departure"].get("time", 0)) > (now - 0.5)]  # Allow slightly past trains and show more per direction

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
    return sorted(all_train_info, key=lambda x: x["departure_in_minutes"])[:4]

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
        '42nd Street Shuttle': ['GS'],
        'Franklin Avenue Shuttle': ['FS'],
        'Rockaway Park Shuttle': ['H'],
        'Staten Island Railway': ['SIR'],
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
        '42nd Street Shuttle': '#808183',     # Dark slate gray
        'Franklin Avenue Shuttle': '#808183', # Dark slate gray
        'Rockaway Park Shuttle': '#808183',   # Dark slate gray
        'Shuttles': '#808183',                # Dark slate gray
        'Staten Island Railway': '##0078C6', 
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

def get_stops_for_trunk_line(trunk_line, service):
    """Map trunk lines and services to their specific stop IDs."""
    trunk_line_stops = {
        # Done
        'Eighth Avenue Line': {
            'A': ["A02", "A03", "A05", "A06", "A07", "A09", "A10", "A11", "A12", "A14", "A15", "A16", "A17", "A18", "A19", "A20", "A21", "A22", "A24", "A25", "A27", "A28", "A30", "A31", "A32", "A33", "A34", "A36", "A38", "A40", "A41", "A42", "A43", "A44", "A45", "A46", "A47", "A48", "A49", "A50", "A51", "A52", "A53", "A54", "A55", "A57", "A59", "A60", "A61", "A63", "A64", "A65", "H01", "H02", "H03", "H04", "H06", "H07", "H08", "H09", "H10", "H11", "H12"],
            'C': ['A09', "A10", "A11", "A12", "A14", "A15", "A16", "A17", "A18", "A19", "A20", "A21", "A22", "A24", "A25", "A27", "A28", "A30", "A31", "A32", "A33", "A34", "A36", "A38", "A40", "A41", "A42", "A43", "A44", "A45", "A46", "A47", "A48", "A49", "A50", "A51", "A52", "A53", "A54", "A55", "A57", "A59", "A60", "A61", "A63", "A64", "A65", "H01", "H02", "H03", "H04", "H06", "H07", "H08", "H09", "H10", "H11", "H12"],
            'E': ["G05", "G06", "G07", "F05", "F06", "F07", "G08", "G09", "G10", "G11", "G12", "G13", "G14", "G15", "G16", "G18", "G19", "G20", "G21", "F09", "F11", "F12", "D14", "A25", "A27", "A28", "A30", "A31", "A32", "A33", "A34", "E01",]
        },
        # Done 
        'Sixth Avenue Line': {
            'B': ["D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10", "D11", "D12", "D13", "A14", "A15", "A16", "A17", "A18", "A19", "A20", "A21", "A22", "A24", "D14", "D15", "D16", "D17", "D20", "D21", "D22", "R30", "D24", "D25", "D26", "D27", "D28", "D29", "D30", "D31", "D32", "D33", "D34", "D35", "D39", "D40",],
            'D': ['D01', "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10", "D11", "D12", "D13", "A15", "A24", "D14", "D15", "D16", "D17", "D20", "D21", "D22", "R30", "R31", "R32", "R33", "R34", "R35", "R36", "B12", "B13", "B14", "B15", "B16", "B17", "B18", "B19", "B20", "B21", "B22", "B23", "D43"],
            'F': ['F01', 'F02', 'F03', "F04", "F05", "F06", "F07", "G08", "G09", "G10", "G11", "G12", "G13", "G14", "G15", "G16", "G18", "G19", "G20", "B04", "B06", "B08", "B10", "D15", "D16", "D17", "D18", "D19", "D20", "D21", "D22", "F14", "F15", "F16", "F18", "A41", "F20", "F21", "F22", "F23", "F24", "F25", "F26", "F27", "F29", "F30", "F31", "F32", "F33", "F34", "F35", "F36", "F38", 'F39', "D42", "D43",  ],
            'M': ["G08", "G09", "G10", "G11", "G12", "G13", "G14", "G15", "G16", "G18", "G19", "G20", "G21", "F09", "F11", "F12", "D15", "D16", "D17", "D18", "D19", "D20", "D21", "M18", "M16", "M14", "M13", "M12", "M11", "M10", "M09", "M08", "M06", "M05", "M04", "M01"]
        },
        # Done 
        'Crosstown Line': {
            'G': ["G22", "G24", "G26", "G28", "G29", "G30", "G31", "G32", "G33", "G34", "G35", "G36", "A42", "F20", "F21", "F22", "F23", "F24", "F25", "F26", "F27", "F28"]
        },
        # Done
        'Canarsie Line': {
            'L': ["L01", "L02", "L03", "L05", "L06", "L08", "L10", "L11", "L12", "L13", "L14", "L15", "L16", "L17", "L19", "L20", "L21", "L22", "L24", "L25", "L26", "L27", "L28", "L29", "L30"]
        },
        # Done
        'Nassau Street Line': {
            'J': ["G05", "G06", "J12", "J13", "J14", "J15", "J16", "J17", "J19", "J20", "J21", "J22", "J23", "J24", "J27", "J28", "J29", "J30", "J31", "M11", "M12", "M14", "M16", "M18", "M19", "M20", "M21", "M22", "M23"],
            'Z': ["G05", "G06", "J12", "J13", "J14", "J15", "J16", "J17", "J19", "J20", "J21", "J23", "J24", "J27", "J28", "J30", "M11", "M12", "M13", "M14", "M16", "M18", "M19", "M20", "M21", "M22", "M23"]
        },
        'Broadway Line': {
            'N': ['N01', 'N02', 'N03'],
            'Q': ['Q01', 'Q02', 'Q03'],
            'R': ['R01', 'R02', 'R03'],
            'W': ['W01', 'W02', 'W03']
        },
        'Broadway–Seventh Avenue Line': {
            '1': ['101', '102', '103'],
            '2': ['201', '204', '247'],
            '3': ['301', '302', '303']
        },
        'Lexington Avenue Line': {
            '4': ['401', '402', '403'],
            '5': ['501', '502', '247'],
            '6': ['601', '602', '603']
        },
        # Done  
        'Flushing Line': {
            '7': ['701', '702', '705', "706", "707", "708", "709", "710", "711", "712", "713", "714", "715", "716", "718", "719", "720", "721", "723", "724", "725", "726", ""]
        },
        # Done
        '42nd Street Shuttle': {
            'GS': ['901', '902']
        },
        # Done
        'Franklin Avenue Shuttle': {
            'FS': ['D26', 'S01', 'S03', 'S04']
        },
        # Done
        'Rockaway Park Shuttle': {
            'H': ['H01', 'H02', 'H03', 'H04', 'H06', 'H07', 'H08', 'H09', 'H10', 'H11', 'H12', 'H13', 'H14', 'H15']
        },
        # Done
        'Staten Island Railway': {
            'SIR': ['S09', 'S11', 'S13', 'S14', 'S15', 'S16', 'S17', 'S18', 'S19', 'S20', 'S21', 'S22', 'S23', 'S24', 'S25', 'S26', 'S27', 'S28', 'S29', 'S30', 'S31']
        }
    }
    return trunk_line_stops.get(trunk_line, {}).get(service, [])

def get_stop_info(stop_id):
    """Get stop name from stops.txt"""
    with open('stops.txt', 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row['stop_id'] == stop_id:
                return {
                    'stop_id': stop_id,
                    'stop_name': row['stop_name']
                }
    return None

def get_train_info(stop_id):
    """Fetch and display train information for a specific stop."""
    url = f"{TRANSITER_BASE_URL}/systems/us-ny-subway/stops/{stop_id}/trains"
    response = requests.get(url)
    data = response.json()
    
    now = time.time()
    upcoming_trains = [stop_time for stop_time in data.get("stopTimes", []) 
                       if float(stop_time["departure"].get("time", 0)) > (now - 0.5)]  # Allow slightly past trains

    all_train_info = []
    for stop_time in upcoming_trains:
        departure_time = stop_time.get("departure", {}).get("time", None)
        if departure_time:
            departure_in_minutes = (departure_time - now) / 60
            train_info = {
                "line": stop_time.get("line", {}).get("id", ""),
                "destination": stop_time.get("destination", {}).get("name", ""),
                "departure_in_minutes": int(departure_in_minutes)
            }
            all_train_info.append(train_info)
    
    # Sort by departure time and show all trains
    return sorted(all_train_info, key=lambda x: x["departure_in_minutes"])[:4]

@app.route('/')
def index():
    valid_lines = ['1', '2', '3', '4', '5', '6', '7', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'J', 'L', 'M', 'N', 'Q', 'R', 'S', 'T', "H", "W", "9", "FS", "GS", "SIR"]
    settings = session.get('settings', DEFAULT_SETTINGS)
    return render_template('index.html', services=valid_lines, settings=settings)

@app.route('/service/<service>')
def service(service):
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
        '42nd Street Shuttle': ['GS'],
        'Franklin Avenue Shuttle': ['FS'],
        'Rockaway Park Shuttle': ['H'],
        'Staten Island Railway': ['SIR']
    }
    
    trunk_line_colors = {
        'Eighth Avenue Line': '#0039a6',
        'Sixth Avenue Line': '#ff6319',
        'Crosstown Line': '#6cbe45',
        'Canarsie Line': '#a7a9ac',
        'Nassau Street Line': '#996633',
        'Broadway Line': '#fccc0a',
        'Broadway–Seventh Avenue Line': '#ee352e',
        'Lexington Avenue Line': '#00933c',
        'Flushing Line': '#b933ad',
        'Second Avenue Line': '#00add0'
    }
    
    current_trunk = None
    for trunk, services in trunk_lines.items():
        if service in services:
            current_trunk = trunk
            break
            
    if current_trunk is None:
        return "Invalid line"
        
    # Get stops for special trunk lines (shuttles and SIR)
    stops = get_stops_for_trunk_line(current_trunk, service)
    if stops:
        # Get stop names for each stop ID
        stop_info = []
        for stop_id in stops:
            info = get_stop_info(stop_id)
            if info:
                stop_info.append(info)
        
        return render_template('service.html', 
                             service=service,
                             trunk_line=current_trunk,
                             stops=stop_info,
                             trunk_color=trunk_line_colors.get(current_trunk, '#ffffff'))
                             
    # For regular trunk lines, continue with existing logic...
    # Get trunk line mappings
    stop_to_trunk, trunk_to_stops, _ = map_stops_to_trunk_lines()
    
    # Get all stops for this trunk line
    trunk_groups = {}
    if current_trunk in trunk_to_stops:
        trunk_groups[current_trunk] = trunk_to_stops[current_trunk]
    
    # Get settings
    settings = session.get('settings', DEFAULT_SETTINGS)
    
    return render_template('service.html', 
                         line=service,
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
        'glow_strength': '10',
        'font_link': 'https://fonts.googleapis.com/css2?family=Jersey+25+Charted&display=swap',
        'font_size': '16'
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
    
    train_info = get_train_info(stop_id)
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
            'glow_strength': request.form.get('glow_strength', DEFAULT_SETTINGS['glow_strength']),
            'font_link': request.form.get('font_link', DEFAULT_SETTINGS['font_link']),
            'font_size': request.form.get('font_size', DEFAULT_SETTINGS['font_size'])
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
        train_info = get_train_info(stop_id)
        
        # Calculate arrival times
        current_time = time.time()
        for info in train_info:
            if info['departure_in_minutes'] is not None:
                arrival_time_sec = info['departure_in_minutes'] * 60
                info['arrival_time'] = max(1, int(arrival_time_sec / 60)) if arrival_time_sec > 0 else None
            else:
                info['arrival_time'] = None
            
            # Extract just the route ID (number or letter)
            info['route_id'] = info['line'].split()[0]

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

@app.route('/update_font', methods=['POST'])
def update_font():
    font_link = request.form.get('font_link', '')
    session['settings']['font_link'] = font_link
    return redirect(url_for('settings'))

@app.route('/update_font_size', methods=['POST'])
def update_font_size():
    font_size = request.form.get('font_size', '16')
    session['settings']['font_size'] = font_size
    return redirect(url_for('settings'))

@app.route('/update_settings', methods=['POST'])
def update_settings():
    text_color = request.form.get('text_color', DEFAULT_SETTINGS['text_color'])
    glow_strength = request.form.get('glow_strength', DEFAULT_SETTINGS['glow_strength'])
    font_link = request.form.get('font_link', DEFAULT_SETTINGS['font_link'])
    font_size = request.form.get('font_size', DEFAULT_SETTINGS['font_size'])

    session['settings'] = {
        'text_color': text_color,
        'glow_strength': glow_strength,
        'font_link': font_link,
        'font_size': font_size
    }
    return redirect(url_for('index'))

@app.context_processor
def inject_settings():
    # Make sure 'font_link' and 'font_size' are set in the session
    settings = session.get('settings', DEFAULT_SETTINGS)
    settings.setdefault('font_link', DEFAULT_SETTINGS['font_link'])
    settings.setdefault('font_size', DEFAULT_SETTINGS['font_size'])
    return {
        'text_color': settings['text_color'],
        'glow_strength': settings['glow_strength'],
        'font_link': settings['font_link'],
        'font_size': settings['font_size']
    }

if __name__ == '__main__':
    app.run(debug=True, port=5002, host='0.0.0.0')
