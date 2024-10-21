from flask import Flask
from flask import request
import openmeteo_requests
import requests_cache
from retry_requests import retry
from flask_cors import CORS
from geopy.geocoders import Nominatim

# Setup the Open-Meteo API client with cache and retry on error
geolocator = Nominatim(user_agent="wokkyApi")
cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)
app = Flask(__name__)
CORS(app, support_credentials=True)
context = ('certs/server.crt', 'certs/server.key')


@app.route("/wokky_time_now", methods=["POST"])
def wokky_time_now():
    json_request = request.get_json()
    url = "https://api.open-meteo.com/v1/forecast"
    openmeteo_params = {
        "latitude": json_request['latitude'],
        "longitude": json_request['longitude'],
	    "current": ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "wind_gusts_10m"]
    }

    # this should return just one location's results, get them
    response = openmeteo.weather_api(url, params=openmeteo_params)[0]
    
        
    # Current values. The order of variables needs to be the same as requested.
    current = response.Current()
    current_temperature_2m = current.Variables(0).Value()
    current_relative_humidity_2m = current.Variables(1).Value()
    current_wind_speed_10m = current.Variables(2).Value()
    current_wind_gusts_10m = current.Variables(3).Value()



    # extract values into JSON
    json_response = dict()
    json_response["current_temperature_2m"] = current_temperature_2m
    json_response["current_relative_humidity_2m"] = current_relative_humidity_2m
    json_response["current_wind_gusts_10m"] = current_wind_gusts_10m
    json_response["current_wind_speed_10m"] = current_wind_speed_10m
    wokky_reasons = is_it_wokable(int(current_temperature_2m), int(current_relative_humidity_2m), int(current_wind_speed_10m))
    json_response["is_wokky"] = len(wokky_reasons) == 0
    json_response["reasons"] = wokky_reasons

    #reverse geocoding using latitude and longitude
    location = geolocator.reverse(str(json_request['latitude'])+","+str(json_request['longitude']), language='en')
    json_response["location"] = location.raw["address"]
    return json_response

"""
this function assumes the following units: temp: Celsius
wind_speed : km/h
"""
def is_it_wokable(temperature, humidity, wind_speed):
    reasons = list()
    if(temperature < 13 or temperature > 24): 
        reasons.append(f"{temperature}°C temperature too high" if temperature > 24 else f"{temperature}°C temperature too low")
    if(humidity < 30 or humidity > 60):
        reasons.append(f"{humidity} % humidity too high" if humidity > 60 else f"{humidity} % humidity too low")
    if(wind_speed < 5 or wind_speed > 15): 
        reasons.append(f"{wind_speed} km/h wind speed too high" if wind_speed > 15 else f"{wind_speed} km/h wind speed too low")
    
    return reasons

if __name__ == "__main__":
  app.run(host='0.0.0.0', ssl_context=context, threaded=True, debug=True)