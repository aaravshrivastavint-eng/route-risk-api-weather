from fastapi import FastAPI
from dotenv import load_dotenv
import httpx
import os
import polyline
import asyncio

load_dotenv()

app = FastAPI(
    title="Route Risk Weather API",
    version="2.0.0",
    description="Shipment route weather and traffic intelligence API"
)

# ENV VARIABLES

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

OPENROUTE_API_KEY = os.getenv("OPENROUTE_API_KEY")

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY")

# BASE URLS

WEATHER_BASE_URL = (
    "https://api.openweathermap.org/data/2.5/forecast"
)

ROUTE_BASE_URL = (
    "https://api.openrouteservice.org/v2/directions/driving-car"
)

TOMTOM_TRAFFIC_URL = (
    "https://api.tomtom.com/traffic/services/4/"
    "flowSegmentData/absolute/10/json"
)

# GEO HELPERS

async def get_coordinates(city: str):

    url = (
        f"http://api.openweathermap.org/geo/1.0/direct"
        f"?q={city}"
        f"&limit=1"
        f"&appid={OPENWEATHER_API_KEY}"
    )
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(
        timeout=timeout
    ) as client:

        response = await client.get(url)

    if response.status_code != 200:
        return None

    data = response.json()

    if not data:
        return None

    return {
        "lat": data[0]["lat"],
        "lon": data[0]["lon"]
    }

# ROUTE FETCH

async def get_route(source_coords, destination_coords):

    headers = {
        "Authorization": OPENROUTE_API_KEY
    }

    body = {
        "coordinates": [
            [source_coords["lon"], source_coords["lat"]],
            [destination_coords["lon"], destination_coords["lat"]]
        ]
    }
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(
        timeout=timeout
    ) as client:

        response = await client.post(
            ROUTE_BASE_URL,
            headers=headers,
            json=body
        )

    if response.status_code != 200:
        print(response.text)
        return None

    data = response.json()

    if "routes" not in data:
        print(data)
        return None

    route = data["routes"][0]

    geometry = route["geometry"]

    summary = route["summary"]

    distance_km = round(
        summary["distance"] / 1000,
        2
    )

    duration_hours = round(
        summary["duration"] / 3600,
        2
    )

    return {
        "geometry": geometry,
        "distance_km": distance_km,
        "duration_hours": duration_hours
    }

# CHECKPOINT SAMPLING

def sample_waypoints(route_coordinates):

    total_points = len(route_coordinates)

    if total_points <= 5:

        indices = range(total_points)

    else:

        indices = [
            0,
            total_points // 4,
            total_points // 2,
            (3 * total_points) // 4,
            total_points - 1
        ]

    checkpoints = []

    for idx in indices:

        lon, lat = route_coordinates[idx]

        checkpoints.append({
            "lat": lat,
            "lon": lon
        })

    return checkpoints

# WEATHER FETCH

async def get_forecast(lat, lon):

    url = (
        f"{WEATHER_BASE_URL}"
        f"?lat={lat}"
        f"&lon={lon}"
        f"&appid={OPENWEATHER_API_KEY}"
        f"&units=metric"
    )
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(
        timeout=timeout
    ) as client:

        response = await client.get(url)

    if response.status_code != 200:
        return None

    return response.json()

# TRAFFIC FETCH

async def get_traffic(lat, lon):

    url = (
        f"{TOMTOM_TRAFFIC_URL}"
        f"?point={lat},{lon}"
        f"&key={TOMTOM_API_KEY}"
    )
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(
        timeout=timeout
    ) as client:

        response = await client.get(url)

    if response.status_code != 200:
        return None

    return response.json()

# WEATHER RISK ENGINE

def calculate_weather_risk(forecast_data):

    max_score = 0

    risk_factors = set()

    for item in forecast_data["list"][:8]:

        score = 0

        weather_condition = (
            item["weather"][0]["main"].lower()
        )

        temperature = item["main"]["temp"]

        wind_speed = item.get(
            "wind", {}
        ).get("speed", 0)

        visibility = item.get(
            "visibility",
            10000
        )

        rain_volume = item.get(
            "rain", {}
        ).get("3h", 0)

        # WEATHER CONDITIONS

        if "thunderstorm" in weather_condition:

            score += 50

            risk_factors.add(
                "Thunderstorm conditions"
            )

        elif "rain" in weather_condition:

            score += 30

            risk_factors.add(
                "Heavy rainfall"
            )

        elif "snow" in weather_condition:

            score += 40

            risk_factors.add(
                "Snow conditions"
            )

        # RAIN VOLUME

        score += min(rain_volume * 2, 25)

        if rain_volume > 5:

            risk_factors.add(
                "Intense rainfall"
            )

        # WIND

        if wind_speed > 15:

            score += 30

            risk_factors.add(
                "Strong winds"
            )

        elif wind_speed > 8:

            score += 15

        # VISIBILITY

        if visibility < 2000:

            score += 30

            risk_factors.add(
                "Low visibility"
            )

        elif visibility < 5000:

            score += 15

        # TEMPERATURE

        if temperature > 42:

            score += 20

            risk_factors.add(
                "Extreme heat"
            )

        elif temperature < 2:

            score += 20

            risk_factors.add(
                "Extreme cold"
            )

        max_score = max(max_score, score)

    return {
        "risk_score": round(max_score),
        "risk_factors": list(risk_factors)
    }

# TRAFFIC RISK ENGINE
def calculate_traffic_risk(traffic_data):

    if not traffic_data:

        return {
            "traffic_score": 0,
            "traffic_level": "LOW"
        }

    flow_data = traffic_data.get(
        "flowSegmentData",
        {}
    )

    current_speed = flow_data.get(
        "currentSpeed",
        0
    )

    free_flow_speed = max(
        flow_data.get("freeFlowSpeed", 1),
        1
    )

    confidence = flow_data.get(
        "confidence",
        0
    )

    congestion_ratio = (
        1 - (current_speed / free_flow_speed)
    )

    score = 0

    if congestion_ratio > 0.7:

        score += 50

    elif congestion_ratio > 0.5:

        score += 35

    elif congestion_ratio > 0.3:

        score += 20

    if confidence < 0.5:

        score += 10

    if score >= 50:

        level = "HIGH"

    elif score >= 25:

        level = "MEDIUM"

    else:

        level = "LOW"

    return {
        "traffic_score": round(score),
        "traffic_level": level,
        "current_speed": current_speed,
        "free_flow_speed": free_flow_speed,
        "congestion_ratio": round(
            congestion_ratio,
            2
        )
    }

# ROUTE ANALYSIS

async def analyze_route(waypoints):

    weather_tasks = [
        get_forecast(
            point["lat"],
            point["lon"]
        )
        for point in waypoints
    ]

    traffic_points = [
    waypoints[0],
    waypoints[len(waypoints) // 2],
    waypoints[-1]
    ]

    traffic_tasks = [
        get_traffic(
           point["lat"],
          point["lon"]
        )
        for point in traffic_points
    ]

    forecasts = await asyncio.gather(
        *weather_tasks
    )

    traffic_results = await asyncio.gather(
        *traffic_tasks
    )

    highest_score = 0

    final_level = "LOW"

    combined_factors = set()

    for idx, forecast in enumerate(forecasts):

        if not forecast:
            continue

        weather_risk = calculate_weather_risk(
            forecast
        )

        traffic_index = min(
            idx,
            len(traffic_results) - 1
        )

        traffic_data = traffic_results[
        traffic_index
        ]

        if isinstance(traffic_data, Exception):

            traffic_data = None

        traffic_risk = calculate_traffic_risk(
            traffic_data
        )

        combined_score = (
            weather_risk["risk_score"] * 0.7
            +
            traffic_risk["traffic_score"] * 0.3
        )

        combined_factors.update(
            weather_risk["risk_factors"]
        )

        if combined_score > highest_score:

            highest_score = combined_score

    # FINAL LEVEL

    if highest_score >= 80:

        final_level = "CRITICAL"

        delay_hours = 8

    elif highest_score >= 55:

        final_level = "HIGH"

        delay_hours = 5

    elif highest_score >= 30:

        final_level = "MEDIUM"

        delay_hours = 2

    else:

        final_level = "LOW"

        delay_hours = 0

    return {
        "overall_risk_score": round(highest_score),
        "overall_risk_level": final_level,
        "estimated_delay_hours": delay_hours,
        "risk_factors": list(combined_factors),
        "segments_analyzed": len(waypoints)
    }

# RECOMMENDATION ENGINE

def generate_recommendation(
    risk_level,
    distance_km
):

    if risk_level == "CRITICAL":

        return (
            "Avoid dispatch. Severe route "
            "disruptions expected."
        )

    elif risk_level == "HIGH":

        if distance_km > 800:

            return (
                "Consider alternate corridor "
                "routing or delayed dispatch."
            )

        return (
            "Delay non-critical dispatches "
            "and monitor traffic conditions."
        )

    elif risk_level == "MEDIUM":

        return (
            "Proceed with caution. Moderate "
            "delays possible."
        )

    return (
        "Route conditions acceptable "
        "for dispatch."
    )

# MAIN API

@app.get("/route-risk")

async def route_risk(
    source: str,
    destination: str
):

    # COORDINATES

    source_coords = await get_coordinates(
        source
    )

    destination_coords = await get_coordinates(
        destination
    )

    if not source_coords or not destination_coords:

        return {
            "success": False,
            "message": (
                "Invalid source or "
                "destination city"
            )
        }

    # ROUTE

    route_data = await get_route(
        source_coords,
        destination_coords
    )

    if not route_data:

        return {
            "success": False,
            "message": (
                "Unable to fetch route "
                "information"
            )
        }

    route_geometry = route_data["geometry"]

    distance_km = route_data["distance_km"]

    duration_hours = route_data[
        "duration_hours"
    ]

    # DECODE ROUTE

    decoded_coordinates = polyline.decode(
        route_geometry
    )

    formatted_coordinates = []

    for lat, lon in decoded_coordinates:

        formatted_coordinates.append(
            [lon, lat]
        )

    # CHECKPOINTS

    waypoints = sample_waypoints(
        formatted_coordinates
    )

    # ANALYSIS

    route_analysis = await analyze_route(
        waypoints
    )

    recommendation = generate_recommendation(
        route_analysis[
            "overall_risk_level"
        ],
        distance_km
    )

    # FINAL RESPONSE

    return {
        "success": True,

        "source": source,

        "destination": destination,

        "route_distance_km": distance_km,

        "estimated_travel_time_hours":
            duration_hours,

        "overall_risk_score":
            route_analysis[
                "overall_risk_score"
            ],

        "overall_risk_level":
            route_analysis[
                "overall_risk_level"
            ],

        "estimated_delay_hours":
            route_analysis[
                "estimated_delay_hours"
            ],

        "risk_factors":
            route_analysis[
                "risk_factors"
            ],

        "recommendation":
            recommendation,

        "checkpoints_analyzed":
            route_analysis[
                "segments_analyzed"
            ]
    }
