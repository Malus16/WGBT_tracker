import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
import geopy.geocoders
from meteostat import Point, daily, hourly, stations
import thermofeel
import requests
import re

import time

WORLD_CUP_GROUNDS = {
    'Atlanta': (33.7554, -84.4006),
    'Boston (Foxborough)': (42.0909, -71.2643),
    'Dallas (Arlington)': (32.7473, -97.0945),
    'Guadalajara (Zapopan)': (20.6817, -103.4626),
    'Houston': (29.6847, -95.4107),
    'Kansas City': (39.0489, -94.4839),
    'Los Angeles (Inglewood)': (33.9534, -118.3387),
    'Mexico City': (19.3029, -99.1505),
    'Miami (Miami Gardens)': (25.9580, -80.2389),
    'Monterrey (Guadalupe)': (25.6644, -100.2443),
    'New York/New Jersey (East Rutherford)': (40.8128, -74.0745),
    'Philadelphia': (39.9012, -75.1675),
    'San Francisco Bay Area (Santa Clara)': (37.4032, -121.9698),
    'Seattle': (47.5952, -122.3316),
    'Toronto': (43.6332, -79.4186),
    'Vancouver': (49.2768, -123.1120)
}

@st.cache_data
def get_location_coordinates(location_name):
    if location_name in WORLD_CUP_GROUNDS:
        return WORLD_CUP_GROUNDS[location_name]
    try:
        time.sleep(1.1)
        geolocator = geopy.geocoders.Nominatim(user_agent="wbgt_app_mikke", timeout=10)
        location = geolocator.geocode(location_name)
        if location:
            return location.latitude, location.longitude
    except Exception as e:
        pass
    return None, None

def calculate_wbgt_celsius(temp_c, rh):
    temp_k = temp_c + 273.15
    # calculate_wbgt_simple expects numpy arrays or single floats, and returns the WBGT in Kelvin
    wbgt_k = thermofeel.calculate_wbgt_simple(temp_k, rh)
    return wbgt_k - 273.15

@st.cache_data
def get_world_cup_matches():
    url = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get("matches", [])
    return []

@st.cache_data
def process_world_cup_data(matches):
    results = []
    stations_used = {}
    # use today's date and a generous future limit for matches currently going on or finished
    now = datetime.utcnow()
    
    for match in matches:
        date_str = match.get("date")
        time_full_str = match.get("time") # e.g. "13:00 UTC-6"
        ground = match.get("ground")
        team1 = match.get("team1")
        team2 = match.get("team2")
        
        if not date_str or not time_full_str or not ground:
            continue
            
        # Parse time and convert to UTC
        match_re = re.match(r'(\d{2}:\d{2})\s*UTC([+-]\d+)', time_full_str)
        if match_re:
            time_str, offset = match_re.groups()
            dt_local = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            offset_hours = int(offset)
            dt_utc = dt_local - timedelta(hours=offset_hours)
        else:
            try:
                # Fallback if just time without offset
                dt_local = datetime.strptime(f"{date_str} {time_full_str}", "%Y-%m-%d %H:%M")
                dt_utc = dt_local
            except:
                continue
                
        # Only process past matches
        if dt_utc > now:
            continue
            
        lat, lon = get_location_coordinates(ground)
        if lat is None or lon is None:
            continue
            
        # Weather
        point = Point(lat, lon)
        closest_stations = stations.nearby(point)
        if closest_stations.empty:
            continue
            
        station_id = closest_stations.index[0]
        start_fetch = dt_utc.replace(minute=0, second=0, microsecond=0)
        end_fetch = start_fetch + timedelta(hours=1)
        
        data = hourly(station_id, start_fetch, end_fetch).fetch()
        
        if not data.empty and 'temp' in data.columns and 'rhum' in data.columns:
            row = data.iloc[0]
            temp = row['temp']
            rhum = row['rhum']
            if pd.isna(temp) or pd.isna(rhum):
                continue
            
            wbgt_c = calculate_wbgt_celsius(temp, rhum)
            
            if ground not in stations_used:
                station_row = closest_stations.iloc[0]
                stations_used[ground] = {
                    "Stadium/City": ground,
                    "Station ID": station_id,
                    "Station Name": station_row.get('name', 'Unknown'),
                    "Station Latitude": station_row.get('latitude', lat),
                    "Station Longitude": station_row.get('longitude', lon)
                }
            
            results.append({
                "Date": date_str,
                "Kickoff (UTC)": dt_utc.strftime("%Y-%m-%d %H:%M"),
                "Match": f"{team1} vs {team2}",
                "Stadium/City": ground,
                "Temperature (°C)": temp,
                "Relative Humidity (%)": rhum,
                "WBGT (°C)": round(float(wbgt_c), 2)
            })
            
    df_stations = pd.DataFrame(list(stations_used.values()))
    return pd.DataFrame(results), df_stations

st.title("WBGT Calculator")

tab1, tab2 = st.tabs(["Custom Location", "FIFA World Cup 2026"])

with tab1:
    st.write("Calculate the Wet Bulb Globe Temperature (WBGT) using Meteostat and Thermofeel.")

    location_input = st.text_input("Enter Location (e.g., London, UK):", "London, UK")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", datetime.today().date())
    with col2:
        end_date = st.date_input("End Date", datetime.today().date())

    frequency = st.selectbox("Frequency", ["Daily", "Hourly"])

    if st.button("Calculate WBGT"):
        with st.spinner("Fetching data..."):
            lat, lon = get_location_coordinates(location_input)
            if lat is None or lon is None:
                st.error("Could not find coordinates for the given location.")
            else:
                st.success(f"Location found: Latitude {lat}, Longitude {lon}")
                
                # Find closest weather station
                point = Point(lat, lon)
                closest_stations = stations.nearby(point)
                
                if closest_stations.empty:
                    st.error("No weather station found near this location.")
                else:
                    station_id = closest_stations.index[0]
                    st.write(f"Using Weather Station: {closest_stations.iloc[0]['name']}")
                    
                    start_dt = datetime.combine(start_date, time.min)
                    end_dt = datetime.combine(end_date, time.max)
                    
                    # Fetch data
                    if frequency == "Daily":
                        data = daily(station_id, start_dt, end_dt)
                    else:
                        data = hourly(station_id, start_dt, end_dt)
                        
                    df = data.fetch()
                    
                    if df.empty:
                        st.warning("No weather data available for the selected dates.")
                    else:
                        temp_col = 'tavg' if frequency == "Daily" else 'temp'
                        rh_col = 'rhum'
                        
                        if temp_col not in df.columns or rh_col not in df.columns:
                            st.error(f"Required data ({temp_col} or {rh_col}) is missing from the station's records.")
                        else:
                            df = df.dropna(subset=[temp_col, rh_col]).copy()
                            if df.empty:
                                st.warning("Data is missing temperature or humidity values for the selected dates.")
                            else:
                                # Calculate WBGT
                                df['WBGT (°C)'] = calculate_wbgt_celsius(df[temp_col], df[rh_col])
                                
                                st.subheader("Results")
                                st.dataframe(df[[temp_col, rh_col, 'WBGT (°C)']].rename(columns={temp_col: 'Temperature (°C)', rh_col: 'Relative Humidity (%)'}))
                                
                                st.line_chart(df['WBGT (°C)'])
                                
                                attribution = getattr(data, 'attribution', "Meteostat and its data providers")
                                st.caption(f"Source: {attribution}")

with tab2:
    st.write("Analyze the Wet Bulb Globe Temperature (WBGT) during kickoff times of the 2026 FIFA World Cup matches played so far.")
    
    if st.button("Fetch World Cup Data"):
        with st.spinner("Fetching matches and calculating WBGT (this may take a minute or two)..."):
            matches = get_world_cup_matches()
            if not matches:
                st.error("Could not fetch the match schedule. Is the tournament URL correct?")
            else:
                df_wc, df_stations = process_world_cup_data(matches)
                if df_wc.empty:
                    st.info("No matches have been played yet or no data could be fetched.")
                else:
                    st.dataframe(df_wc)
                    st.caption("Source: Meteostat and its data providers. Match schedule from openfootball.")
                    
                    st.subheader("Weather Stations Used")
                    st.write("Weather data is fetched from the nearest active weather station to the stadium at the time of the kickoff.")
                    st.dataframe(df_stations)
