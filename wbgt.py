import streamlit as st

st.set_page_config(layout="wide", page_title="WBGT Calculator")

import pandas as pd
from datetime import datetime, time, timedelta
import geopy.geocoders
from meteostat import Point, daily, hourly, stations
import thermofeel
import requests
import re

import time as pytime

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
        pytime.sleep(1.1)
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

def color_wbgt(val):
    try:
        val = float(val)
        if val > 32:
            return 'background-color: #ff4b4b; color: white' # Red
        elif val > 28:
            return 'background-color: #ffa421; color: white' # Orange
        elif val > 25:
            return 'background-color: #ffe83f; color: black' # Yellow
    except:
        pass
    return ''

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
                "Kickoff (UTC)": dt_utc.strftime("%Y-%m-%d %H:%M"),
                "Match": f"{team1} vs {team2}",
                "Stadium/City": ground,
                "Temperature (°C)": temp,
                "Relative Humidity (%)": rhum,
                "WBGT (°C)": round(float(wbgt_c), 2)
            })
            
    df_stations = pd.DataFrame(list(stations_used.values()))
    return pd.DataFrame(results), df_stations

@st.cache_data(ttl=3600)
def process_upcoming_world_cup_data(matches):
    results = []
    now = datetime.utcnow()
    five_days_from_now = now + timedelta(days=5)
    
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
                dt_local = datetime.strptime(f"{date_str} {time_full_str}", "%Y-%m-%d %H:%M")
                dt_utc = dt_local
            except:
                continue
                
        # Only process upcoming matches within 5 days
        if dt_utc <= now or dt_utc > five_days_from_now:
            continue
            
        lat, lon = get_location_coordinates(ground)
        if lat is None or lon is None:
            continue
            
        # Fetch forecast from Open-Meteo
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,relative_humidity_2m",
            "models": "best_match"
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                times = data.get("hourly", {}).get("time", [])
                temps = data.get("hourly", {}).get("temperature_2m", [])
                rhums = data.get("hourly", {}).get("relative_humidity_2m", [])
                
                target_time_str = dt_utc.strftime("%Y-%m-%dT%H:00")
                
                if target_time_str in times:
                    idx = times.index(target_time_str)
                    temp = temps[idx]
                    rhum = rhums[idx]
                    
                    if temp is not None and rhum is not None:
                        wbgt_c = calculate_wbgt_celsius(temp, rhum)
                        results.append({
                            "Kickoff (UTC)": dt_utc.strftime("%Y-%m-%d %H:%M"),
                            "Match": f"{team1} vs {team2}",
                            "Stadium/City": ground,
                            "Temperature (°C)": temp,
                            "Relative Humidity (%)": rhum,
                            "WBGT (°C)": round(float(wbgt_c), 2)
                        })
        except Exception as e:
            continue
            
    return pd.DataFrame(results)

st.title("WBGT Calculator")

st.info("**Disclaimer:** This tool uses the Australian Bureau of Meteorology's simplified empirical estimation for WBGT based only on 2m temperature and relative humidity. It is an empirical screening estimate (no radiation/wind term), intended for moderate-to-warm outdoor conditions; it is not a substitute for a physically-based calculation where definitive accuracy matters.")

tab1, tab2 = st.tabs(["Custom Location", "FIFA World Cup 2026"])

with tab1:
    st.write("Calculate the Wet Bulb Globe Temperature (WBGT) using weather data from Meteostat.")

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
                                df_display = df[[temp_col, rh_col, 'WBGT (°C)']].rename(columns={temp_col: 'Temperature (°C)', rh_col: 'Relative Humidity (%)'})
                                styled_df = df_display.style.format({
                                    "Temperature (°C)": "{:.1f}",
                                    "Relative Humidity (%)": "{:.0f}",
                                    "WBGT (°C)": "{:.1f}"
                                }).map(color_wbgt, subset=['WBGT (°C)'])
                                st.dataframe(styled_df, width='stretch', hide_index=True, height=600)
                                
                                st.line_chart(df['WBGT (°C)'])
                                
                                attribution = getattr(data, 'attribution', "Meteostat and its data providers")
                                st.caption(f"Source: {attribution}")

with tab2:
    st.write("Analyze the Wet Bulb Globe Temperature (WBGT) for the 2026 FIFA World Cup matches.")
    
    if st.button("Fetch Newest Data"):
        # Clear the cache to force a fresh fetch
        get_world_cup_matches.clear()
        process_world_cup_data.clear()
        
        with st.spinner("Fetching matches and calculating WBGT (this may take a minute or two)..."):
            matches = get_world_cup_matches()
            if not matches:
                st.error("Could not fetch the match schedule. Is the tournament URL correct?")
            else:
                df_wc, df_stations = process_world_cup_data(matches)
                df_forecast = process_upcoming_world_cup_data(matches)
                st.session_state['wc_data'] = df_wc
                st.session_state['wc_stations'] = df_stations
                st.session_state['wc_forecast'] = df_forecast

    if 'wc_data' in st.session_state and 'wc_stations' in st.session_state:
        df_wc = st.session_state['wc_data']
        df_stations = st.session_state['wc_stations']
        df_forecast = st.session_state.get('wc_forecast', pd.DataFrame())
        
        wc_tab1, wc_tab2 = st.tabs(["Played Matches", "Upcoming Matches"])
        
        with wc_tab1:
            if df_wc.empty:
                st.info("No matches have been played yet or no data could be fetched.")
            else:
                df_wc = df_wc.sort_values("Kickoff (UTC)", ascending=True).reset_index(drop=True)
                styled_wc = df_wc.style.format({
                    "Temperature (°C)": "{:.1f}",
                    "Relative Humidity (%)": "{:.0f}",
                    "WBGT (°C)": "{:.1f}"
                }).map(color_wbgt, subset=['WBGT (°C)'])
                st.dataframe(styled_wc, width='stretch', hide_index=True, height=800)
                st.caption("Source: Meteostat and its data providers. Match schedule from openfootball.")
                
            st.subheader("Weather Stations Used")
            st.write("For played matches, weather data is fetched from the nearest active weather station to the stadium at the time of the kickoff.")
            st.dataframe(df_stations, width='stretch', hide_index=True, height=600)
            
        with wc_tab2:
            if df_forecast.empty:
                st.info("No matches scheduled in the next 5 days, or forecast data unavailable.")
            else:
                df_forecast = df_forecast.sort_values("Kickoff (UTC)", ascending=True).reset_index(drop=True)
                styled_forecast = df_forecast.style.format({
                    "Temperature (°C)": "{:.1f}",
                    "Relative Humidity (%)": "{:.0f}",
                    "WBGT (°C)": "{:.1f}"
                }).map(color_wbgt, subset=['WBGT (°C)'])
                st.dataframe(styled_forecast, width='stretch', hide_index=True, height=800)
                st.caption("Source: Weather forecast data by [Open-Meteo.com](https://open-meteo.com/) (CC-BY 4.0). Match schedule from openfootball.")
