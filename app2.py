import csv
import time
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_session import Session
from datetime import datetime

app = Flask(__name__, template_folder="templates")
app.secret_key = 'your-secret-key-here'
# Default settings
DEFAULT_SETTINGS = {
    'text_color': '#00ffff',
    'glow_strength': '15'
}

def get_line_name(stop_id):
    route_id = stop_id[0]
    base_url = f"https://demo.transiter.dev/systems/us-ny-subway/routes/{route_id}"

    try:
        response = requests.get(base_url)
        response.raise_for_status()
        route_data = response.json()
        train_name = route_data.get("shortName", "Unknown Train")
        return train_name
    except requests.exceptions.RequestException as e:
        print(f"Error fetching route info for {route_id}: {e}")
        return "Unknown Train"

def parse_stops(file_path, specific_line_stops=None):
    lines_stations = {}
    valid_lines = ['1', '2', '3', '4', '5', '6', '7', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'J', 'L', 'M', 'N', 'Q', 'R', 'S', 'T', "H", "W", "9"]

    with open(file_path, newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            stop_id = row["stop_id"]
            stop_name = row["stop_name"]
            
            # Skip if it's a child station (ends with N or S)
            if stop_id[-1] in ['N', 'S']:
                continue
            
            # Determine line using custom mapping
            line = next(
                (l for l, stops in line_mapping.items() if stop_id in stops), 
                stop_id[0]  # Fallback to original first-character method
            )
            
            if line in valid_lines:
                # If specific stops are provided for a line, only include those
                if specific_line_stops and line in specific_line_stops:
                    if stop_id in specific_line_stops[line]:
                        if line not in lines_stations:
                            lines_stations[line] = []
                        
                        station = {
                            "stop_id": stop_id,
                            "stop_name": stop_name,
                            "stop_lat": float(row["stop_lat"]),
                            "stop_lon": float(row["stop_lon"])
                        }
                        lines_stations[line].append(station)
                
                # If no specific stops, use the original logic
                elif not specific_line_stops:
                    if line not in lines_stations:
                        lines_stations[line] = []
                    
                    # Only add parent stations or unique stops
                    if not any(s["stop_name"] == stop_name for s in lines_stations[line]):
                        station = {
                            "stop_id": stop_id,
                            "stop_name": stop_name,
                            "stop_lat": float(row["stop_lat"]),
                            "stop_lon": float(row["stop_lon"])
                        }
                        lines_stations[line].append(station)
    
    return lines_stations

def get_upcoming_trains_for_stop(stop_id, lines_stations):
    # For a given stop_id, we'll check both N and S directions
    stop_ids = [stop_id]
    
    if stop_id[-1] not in ['N', 'S']:
        stop_ids.extend([f"{stop_id}N", f"{stop_id}S"])

    all_train_info = []
    seen_trains = set()
    
    for current_stop_id in stop_ids:
        url = f"https://demo.transiter.dev/systems/us-ny-subway/stops/{current_stop_id}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, KeyError, IndexError) as e:
            print(f"Error fetching data for stop {current_stop_id}: {e}")
            continue

        now = time.time()
        upcoming_trains = [stop_time for stop_time in data.get("stopTimes", []) if int(stop_time["departure"].get("time", 0)) > now]

        for stop_time in upcoming_trains[:2]:  # Limit to the next 2 trains
            departure_time = stop_time.get("departure", {}).get("time", None)

            if departure_time is None:
                print(f"Skipping train info due to missing departure time for stop {current_stop_id}")
                continue

            seconds_to_leave = int(departure_time) - now
            minutes, _ = divmod(seconds_to_leave, 60)

            trip_info = stop_time.get("trip", {})
            route_id = trip_info.get("route", {}).get("id", "Unknown")
            route_name = get_line_name(route_id)
            destination = trip_info.get("destination", {}).get("name", "Unknown")
            headsign = stop_time.get("headsign", "Unknown")
            trip_id = trip_info.get("id", "Unknown")
            
            # Fetch the next stop after the current one for this trip
            next_stop_url = f"https://demo.transiter.dev/systems/us-ny-subway/trips/{trip_id}/stop_times"
            try:
                next_stop_response = requests.get(next_stop_url)
                next_stop_response.raise_for_status()
                next_stop_data = next_stop_response.json()
                next_stop = next_stop_data[1]["stop"]["name"] if len(next_stop_data) > 1 else None
            except requests.exceptions.RequestException as e:
                print(f"Error fetching next stop data for trip {trip_id}: {e}")
                next_stop = None

            if destination == "Unknown":
                destination = "No destination available"
            if route_name == "Unknown Line":
                route_name = "No route available"

            train_details = f"to {destination} [{headsign}] leaves in {int(minutes)} min"

            if train_details not in seen_trains:
                seen_trains.add(train_details)
                train_info = {
                    "train_details": train_details,
                    "trip_id": trip_id,
                    "destination": destination,
                    "headsign": headsign,
                    "departure_time": departure_time,
                    "departure_in_minutes": int(minutes),
                    "route_name": route_name,
                    "next_stop": next_stop
                }
                all_train_info.append(train_info)
    
    return all_train_info

def get_stop_name(stop_id):
    url = f"https://demo.transiter.dev/systems/us-ny-subway/stops/{stop_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data["name"]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching station name for {stop_id}: {e}")
        return "Unknown Station"

def get_transfers_for_stop(stop_id):
    url = f"https://demo.transiter.dev/systems/us-ny-subway/stops/{stop_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        transfers = data.get('transfers', [])
        processed_transfers = []
        for transfer in transfers:
            transfer_info = {
                'from_stop_name': transfer['fromStop']['name'],
                'to_stop_name': transfer['toStop']['name'],
                'from_stop_id': transfer['fromStop']['id'],
                'to_stop_id': transfer['toStop']['id'],
                'transfer_type': transfer['type'],
                'min_transfer_time': transfer.get('minTransferTime', 0)
            }
            processed_transfers.append(transfer_info)

        return processed_transfers
    except requests.exceptions.RequestException as e:
        print(f"Error fetching transfers for stop {stop_id}: {e}")
        return []

@app.route('/')
def index():
    valid_lines = ['1', '2', '3', '4', '5', '6', '7', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'J', 'L', 'M', 'N', 'Q', 'R', 'S', 'T', "H", "W", "9"]
    return render_template('index.html', services=valid_lines)

@app.route('/service/<line>')
def service(line):
    specific_line_stops = {
        '1': ['101', '103', '104', '106', '107', '108', '109', '110', '111', '112', '113', '114', '115', '116', '117', '118', '119', '120', '121', '122', '123', '124', '125', '126', '127', '128', '129', '130', '131', '132', '133', '134', '135', '136', '137', '138', '139', '142'],
        '2' : ['201', '204', '205','207', "208", "209", "210","211","212", "213", "214","215", "216", "217", "218", "219", "220", "221", "222", "224", "225", "226", "227", "120", "121", "122", "123", "124", "125", "126", "127" ,  "228", "229", "230", "231", "232", "233", "234", "235", "236", "237", "238", "239", "241", "242", "243", "244", "245", "246", "247" ],
        "3" : ["301", "302", "", "", "",]
    }
    
    lines_stations = parse_stops(r"stops.txt", specific_line_stops)
    stops = lines_stations.get(line, [])
    return render_template('service.html', line=line, stops=stops)


@app.route('/traininfo/<stop_id>')
def train_info(stop_id):
    lines_stations = parse_stops(r"stops.txt")
    stop_name = get_stop_name(stop_id)
    train_info = get_upcoming_trains_for_stop(stop_id, lines_stations)
    transfers = get_transfers_for_stop(stop_id)
    
    # Calculate arrival time in minutes
    current_time = time.time()
    for info in train_info:
        if info['departure_time'] is not None:
            arrival_time_sec = int(info['departure_time']) - current_time
            info['arrival_time'] = max(1, int(arrival_time_sec / 60)) if arrival_time_sec > 0 else None
        else:
            info['arrival_time'] = None

    # Sort by arrival time
    train_info.sort(key=lambda x: x['arrival_time'] if x['arrival_time'] is not None else float('inf'))

    # Get current time for display
    current_time = datetime.now().strftime("%I:%M %p")

    return render_template('traininfo.html', 
                         stop_name=stop_name,
                         stop_id=stop_id,
                         train_info=train_info,
                         transfers=transfers,
                         current_time=current_time)

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

    return render_template('index.html',
                         stop_name=stop_name,
                         train_info=train_info,
                         lines_info=lines_info,
                         transfers=transfers)

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
        # Update settings in session
        session['text_color'] = request.form.get('text_color', DEFAULT_SETTINGS['text_color'])
        session['glow_strength'] = request.form.get('glow_strength', DEFAULT_SETTINGS['glow_strength'])
        return redirect(url_for('index'))
    
    # Get current settings from session or use defaults
    current_settings = {
        'text_color': session.get('text_color', DEFAULT_SETTINGS['text_color']),
        'glow_strength': session.get('glow_strength', DEFAULT_SETTINGS['glow_strength'])
    }
    return render_template('settings.html', settings=current_settings)

@app.context_processor
def inject_settings():
    # Make settings available to all templates
    return {
        'text_color': session.get('text_color', DEFAULT_SETTINGS['text_color']),
        'glow_strength': session.get('glow_strength', DEFAULT_SETTINGS['glow_strength'])
    }

if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')
