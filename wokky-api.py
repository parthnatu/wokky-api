from flask import Flask
from flask import request
import openmeteo_requests
import requests_cache
from retry_requests import retry
from flask_cors import CORS
from geopy.geocoders import Nominatim
import pandas as pd
from timezonefinder import TimezoneFinder
from pywebpush import webpush
import os
from apscheduler.schedulers.background import BackgroundScheduler
import json
from pymongo import MongoClient
from pywebpush import WebPushException
import atexit
import time
import logging
import base64
import hashlib
notification_ignore_weather_flag = False
client = MongoClient(
    os.environ["MONGO_DB_HOST"],
    username=os.environ["MONGO_DB_USER"],
    password=os.environ["MONGO_DB_PASSWD"],
    authMechanism="SCRAM-SHA-256",
)

db = client["wokky"]
priv_key = db["keys"].find_one({"name": "wokky-api-keys"})["private"]

# Setup the Open-Meteo API client with cache and retry on error
geolocator = Nominatim(user_agent="wokkyApi")
cache_session = requests_cache.CachedSession(".cache", expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)
app = Flask(__name__)
CORS(app, support_credentials=True)

notification_data = {"title": "Go for a walk!", "options": {"body": "The weather is looking good :)"}}


def send_notifs():
    for x in db["subscriptions"].find():
        try:
            lat = x["latitude"]
            lon = x["longitude"]
            hasher = hashlib.sha1(str(x["_id"]).encode('utf-8'))
            base64_id = base64.urlsafe_b64encode(hasher.digest()[:10])
            app.logger.debug(f"checking if {base64_id} need to be sent a notification")
            if not should_sent_notification(lat, lon) and not notification_ignore_weather_flag:
                app.logger.debug(
                    f"{base64_id} does not need to be sent a notification because the weather is not optimal"
                )
                continue
            if x["last_sent"] != None and (int(time.time()) - x["last_sent"]) >= 5:
                app.logger.debug(
                    f"{base64_id} does not need to be sent a notification because last_sent is not within the threshold"
                )
                continue
            app.logger.info(
                    f"{base64_id} sending notification"
                )
            
            webpush(
                x["_id"],
                json.dumps(notification_data),
                vapid_private_key=priv_key,
                vapid_claims={"sub": "mailto:parth.natu@gmail.com"},
            )
            update_operation = {"$set": {"last_sent": int(time.time())}}
            db["subscriptions"].update_one({"_id": x["_id"]}, update_operation)
        except WebPushException as e:
            if e.response.status_code == 410:  # subscription has gone
                print("subscription gone! deleting")
                db["subscriptions"].delete_one({"_id": x["_id"]})


def get_weather_data(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    openmeteo_params = {
        "latitude": lat,
        "longitude": lon,
        "current": ["temperature_2m", "relative_humidity_2m", "wind_speed_10m"],
        "forecast_days": 1,
        "minutely_15": ["temperature_2m", "relative_humidity_2m", "wind_speed_10m"],
        "timezone": "auto",
    }

    return openmeteo.weather_api(url, params=openmeteo_params)[0]


def check_weather_data(weather_data):
    current = weather_data.Current()
    current_temperature_2m = current.Variables(0).Value()
    current_relative_humidity_2m = current.Variables(1).Value()
    current_wind_speed_10m = current.Variables(2).Value()
    return is_it_wokable(
        int(current_temperature_2m),
        int(current_relative_humidity_2m),
        int(current_wind_speed_10m),
    )


def should_sent_notification(lat, lon):
    (_, is_wokky) = check_weather_data(get_weather_data(lat, lon))
    return is_wokky


@app.route("/subscribe", methods=["POST"])
def subscribe():
    json_request = request.get_json()

    susbcription = json_request["subscription"]
    if json_request["latitude"] != 0 and json_request["longitude"] != 0:
        db["subscriptions"].replace_one(
            {"_id": susbcription},
            {
                "_id": susbcription,
                "latitude": json_request["latitude"],
                "longitude": json_request["longitude"],
                "last_sent": None,
            },
            upsert=True,
        )
        return {"message": "subscribed"}
    return {"message": "not subscribed because lat and lon are both 0"}


@app.route("/wokky_time_now", methods=["POST"])
def wokky_time_now():
    json_request = request.get_json()

    # get the timezone
    obj = TimezoneFinder()
    timezone_str = obj.timezone_at(
        lat=json_request["latitude"], lng=json_request["longitude"]
    )

    # this should return just one location's results, get them
    response = get_weather_data(json_request["latitude"], json_request["longitude"])

    # extract values into JSON
    json_response = dict()
    (measures, is_wokky) = check_weather_data(response)
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
            start=pd.to_datetime(minutely_data.Time(), unit="s", utc=True),
            end=pd.to_datetime(minutely_data.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=minutely_data.Interval()),
            inclusive="left",
        )
    }
    minutely_15_data["date"] = minutely_15_data["date"].tz_convert(tz)
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
        .strftime("%d %b %Y %I:%M %p")
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
    scheduler = BackgroundScheduler()
    scheduler.configure(timezone="utc")
    scheduler.add_job(send_notifs, "interval", seconds=10)
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    app.logger.setLevel(logging.DEBUG)
    app.run(host="0.0.0.0", threaded=True, debug=False)

if __name__ != "__main__":
    scheduler = BackgroundScheduler()
    scheduler.configure(timezone="utc")
    scheduler.add_job(send_notifs, "interval", seconds=30)
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
