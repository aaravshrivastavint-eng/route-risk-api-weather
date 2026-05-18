from fastapi import FastAPI
from dotenv import load_dotenv
import requests
import os

load_dotenv()

app = FastAPI()

API_KEY = os.getenv("OPENWEATHER_API_KEY")


def get_weather(city: str):

    url = (
        f"https://api.openweathermap.org/data/2.5/weather"
        f"?q={city}&appid={API_KEY}&units=metric"
    )

    response = requests.get(url)

    if response.status_code != 200:
        return None

    return response.json()


def calculate_risk(weather_data):

    score = 0
    risk_factors = []

    weather_condition = weather_data["weather"][0]["main"].lower()

    if "thunderstorm" in weather_condition:
        score += 50
        risk_factors.append("Thunderstorm conditions")

    elif "rain" in weather_condition:
        score += 30
        risk_factors.append("Heavy rainfall")

    wind_speed = weather_data.get("wind", {}).get("speed", 0)

    if wind_speed > 15:
        score += 30
        risk_factors.append("Strong winds")

    visibility = weather_data.get("visibility", 10000)

    if visibility < 2000:
        score += 30
        risk_factors.append("Low visibility")

    if score >= 80:
        risk_level = "CRITICAL"
        delay = 8

    elif score >= 50:
        risk_level = "HIGH"
        delay = 5

    elif score >= 25:
        risk_level = "MEDIUM"
        delay = 2

    else:
        risk_level = "LOW"
        delay = 0

    return {
        "risk_score": score,
        "risk_level": risk_level,
        "estimated_delay_hours": delay,
        "risk_factors": risk_factors
    }


@app.get("/route-risk")
def route_risk(source: str, destination: str):

    weather_data = get_weather(destination)

    if not weather_data:
        return {
            "success": False,
            "message": "Failed to fetch weather data"
        }

    risk = calculate_risk(weather_data)

    return {
        "success": True,
        "source": source,
        "destination": destination,
        "weather_condition": weather_data["weather"][0]["main"],
        "temperature": weather_data["main"]["temp"],
        "risk_analysis": risk
    }
