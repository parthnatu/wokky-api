from flask import Flask
from flask import request
import openmeteo_requests
import requests_cache
from retry_requests import retry
from flask_cors import CORS
from geopy.geocoders import Nominatim
import pandas as pd
from timezonefinder import TimezoneFinder

# Setup the Open-Meteo API client with cache and retry on error
geolocator = Nominatim(user_agent="wokkyApi")
cache_session = requests_cache.CachedSession(".cache", expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)
app = Flask(__name__)
CORS(app, support_credentials=True)

@app.route("/wokky_time_now", methods=["POST"])
def wokky_time_now():
    json_request = request.get_json()

    # get the timezone
    obj = TimezoneFinder()
    timezone_str = obj.timezone_at(
        lat=json_request["latitude"], lng=json_request["longitude"]
    )

    url = "https://api.open-meteo.com/v1/forecast"
    openmeteo_params = {
        "latitude": json_request["latitude"],
        "longitude": json_request["longitude"],
        "current": ["temperature_2m", "relative_humidity_2m", "wind_speed_10m"],
        "forecast_days": 1,
        "minutely_15": ["temperature_2m", "relative_humidity_2m", "wind_speed_10m"],
        "timezone": "auto",
    }

    # this should return just one location's results, get them
    response = openmeteo.weather_api(url, params=openmeteo_params)[0]

    # Current values. The order of variables needs to be the same as requested.
    current = response.Current()
    current_temperature_2m = current.Variables(0).Value()
    current_relative_humidity_2m = current.Variables(1).Value()
    current_wind_speed_10m = current.Variables(2).Value()

    # extract values into JSON
    json_response = dict()
    (measures, is_wokky) = is_it_wokable(
        int(current_temperature_2m),
        int(current_relative_humidity_2m),
        int(current_wind_speed_10m),
    )
    json_response["is_wokky"] = is_wokky
    json_response["measures"] = measures

    if is_wokky is False:
        # find the next best time to walk
        next_wokable_time = find_next_wokable(response.Minutely15(), timezone_str)
        json_response["next_wokable_time"] = (
            next_wokable_time if next_wokable_time is not None else {}
        )

    # reverse geocoding using latitude and longitude
    location = geolocator.reverse(
        str(json_request["latitude"]) + "," + str(json_request["longitude"]),
        language="en",
    )
    json_response["location"] = location.raw["address"]
    return json_response


def find_next_wokable(minutely_data, tz):
    minutely_15_temperature_2m = minutely_data.Variables(0).ValuesAsNumpy()
    minutely_15_relative_humidity_2m = minutely_data.Variables(1).ValuesAsNumpy()
    minutely_15_wind_speed_10m = minutely_data.Variables(2).ValuesAsNumpy()

    minutely_15_data = {
        "date": pd.date_range(
            start=pd.to_datetime(minutely_data.Time(), unit="s", utc=False),
            end=pd.to_datetime(minutely_data.TimeEnd(), unit="s", utc=False),
            freq=pd.Timedelta(seconds=minutely_data.Interval()),
            inclusive="left",
        )
    }
    minutely_15_data["date"] = minutely_15_data["date"].tz_localize(tz)
    minutely_15_data["temp"] = minutely_15_temperature_2m
    minutely_15_data["humid"] = minutely_15_relative_humidity_2m
    minutely_15_data["wspeed"] = minutely_15_wind_speed_10m

    minutely_15_dataframe = pd.DataFrame(data=minutely_15_data).sort_values(by=["date"])
    minutely_15_dataframe_filtered = minutely_15_dataframe.query(
        "temp >= 13 and temp <= 24 and humid >= 30 and humid <= 60 and wspeed >=5 and wspeed <= 15"
    )
    minutely_15_dataframe_filtered = minutely_15_dataframe_filtered[
        minutely_15_dataframe_filtered["date"] > pd.Timestamp.now(tz)
    ]
    if minutely_15_dataframe_filtered.empty:
        return None
    return {
        "date": minutely_15_dataframe_filtered.iloc[0]["date"]
        .to_pydatetime()
        .strftime("%I:%M %p %Z")
    }


"""
this function assumes the following units: temp: Celsius
wind_speed : km/h
"""


def is_it_wokable(temperature, humidity, wind_speed):
    measures = list()
    is_wokky = True
    if temperature < 13 or temperature > 24:
        is_wokky = False
        if temperature < 13:
            measures.append(
                {
                    "name": "Temperature",
                    "value": temperature,
                    "unit": "°C",
                    "reason": "low",
                }
            )
        else:
            measures.append(
                {
                    "name": "Temperature",
                    "value": temperature,
                    "unit": "°C",
                    "reason": "high",
                }
            )
    else:
        measures.append(
            {"name": "Temperature", "value": temperature, "unit": "°C", "reason": ""}
        )

    if humidity < 30 or humidity > 60:
        is_wokky = False
        if humidity < 30:
            measures.append(
                {"name": "Humidity", "value": humidity, "unit": "%", "reason": "low"}
            )
        else:
            measures.append(
                {"name": "Humidity", "value": humidity, "unit": "%", "reason": "high"}
            )
    else:
        measures.append(
            {"name": "Humidity", "value": humidity, "unit": "%", "reason": ""}
        )

    if wind_speed < 5 or wind_speed > 15:
        is_wokky = False
        if wind_speed < 5:
            measures.append(
                {
                    "name": "Wind Speed",
                    "value": wind_speed,
                    "unit": "km/h",
                    "reason": "low",
                }
            )
        else:
            measures.append(
                {
                    "name": "Wind Speed",
                    "value": wind_speed,
                    "unit": "km/h",
                    "reason": "high",
                }
            )
    else:
        measures.append(
            {"name": "Wind Speed", "value": wind_speed, "unit": "km/h", "reason": ""}
        )

    return (measures, is_wokky)


if __name__ == "__main__":
    app.run(host="0.0.0.0", threaded=True, debug=True)
