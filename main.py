from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv
import httpx
import os
import polyline
import asyncio


load_dotenv()

app = FastAPI(
    title="Route Risk Operational Intelligence API",
    version="5.0.0",
    description="Corridor-level logistics operational intelligence API"
)

# =========================================================
# RESPONSE MODELS
# =========================================================

class RouteSummary(BaseModel):

    route_distance_km: float

    baseline_travel_time_hours: float

    predicted_operational_travel_time_hours: float

    checkpoints_analyzed: int


class TrafficSummary(BaseModel):

    congestion_level: str

    average_corridor_speed_kmph: float

    operational_traffic_impact: str


class WeatherSummary(BaseModel):

    dominant_weather_condition: str

    temperature_celsius: float

    weather_instability_detected: bool

    weather_risk_factors: List[str]


class OperationalAssessment(BaseModel):

    overall_risk_score: int

    overall_risk_level: str

    estimated_operational_delay_hours: float

    corridor_stability: str

    dispatch_feasibility: str


class RouteRiskResponse(BaseModel):

    success: bool

    source: str

    destination: str

    route_summary: RouteSummary

    traffic_summary: TrafficSummary

    weather_summary: WeatherSummary

    operational_assessment: OperationalAssessment

    recommendation: str

# =========================================================
# ENV VARIABLES
# =========================================================

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

OPENROUTE_API_KEY = os.getenv("OPENROUTE_API_KEY")

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY")

# =========================================================
# BASE URLS
# =========================================================

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

# =========================================================
# GEO HELPERS
# =========================================================

async def get_coordinates(city: str):

    url = (
        "http://api.openweathermap.org/geo/1.0/direct"
        f"?q={city}"
        f"&limit=1"
        f"&appid={OPENWEATHER_API_KEY}"
    )

    timeout = httpx.Timeout(20.0)

    async with httpx.AsyncClient(timeout=timeout) as client:

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

# =========================================================
# ROUTE FETCH
# =========================================================

async def get_route(source_coords, destination_coords):

    headers = {
        "Authorization": OPENROUTE_API_KEY
    }

    body = {
        "coordinates": [
            [
                source_coords["lon"],
                source_coords["lat"]
            ],
            [
                destination_coords["lon"],
                destination_coords["lat"]
            ]
        ],
        "instructions": False
    }

    timeout = httpx.Timeout(30.0)

    try:

        async with httpx.AsyncClient(timeout=timeout) as client:

            response = await client.post(
                ROUTE_BASE_URL,
                headers=headers,
                json=body
            )

        if response.status_code != 200:

            print("ROUTE API ERROR:", response.text)

            return None

        data = response.json()

        if "routes" not in data:
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

    except Exception as e:

        print("ROUTE FETCH ERROR:", str(e))

        return None

# =========================================================
# WAYPOINT SAMPLING
# =========================================================

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

# =========================================================
# WEATHER FETCH
# =========================================================

async def get_forecast(lat, lon):

    url = (
        f"{WEATHER_BASE_URL}"
        f"?lat={lat}"
        f"&lon={lon}"
        f"&appid={OPENWEATHER_API_KEY}"
        f"&units=metric"
    )

    timeout = httpx.Timeout(20.0)

    async with httpx.AsyncClient(timeout=timeout) as client:

        response = await client.get(url)

    if response.status_code != 200:
        return None

    return response.json()

# =========================================================
# TRAFFIC FETCH
# =========================================================

async def get_traffic(lat, lon):

    url = (
        f"{TOMTOM_TRAFFIC_URL}"
        f"?point={lat},{lon}"
        f"&key={TOMTOM_API_KEY}"
    )

    timeout = httpx.Timeout(20.0)

    async with httpx.AsyncClient(timeout=timeout) as client:

        response = await client.get(url)

    if response.status_code != 200:
        return None

    return response.json()

# =========================================================
# WEATHER ANALYSIS
# =========================================================

def calculate_weather_risk(forecast_data):

    risk_score = 0

    risk_factors = set()

    dominant_condition = "Clear"

    max_temperature = 0

    instability_detected = False

    for item in forecast_data["list"][:8]:

        weather_condition = (
            item["weather"][0]["main"]
        )

        weather_lower = weather_condition.lower()

        temperature = item["main"]["temp"]

        max_temperature = max(
            max_temperature,
            temperature
        )

        dominant_condition = weather_condition

        wind_speed = item.get(
            "wind",
            {}
        ).get("speed", 0)

        visibility = item.get(
            "visibility",
            10000
        )

        rain_volume = item.get(
            "rain",
            {}
        ).get("3h", 0)

        if "thunderstorm" in weather_lower:

            risk_score += 45

            instability_detected = True

            risk_factors.add(
                "Thunderstorm conditions"
            )

        elif "rain" in weather_lower:

            risk_score += 25

            instability_detected = True

            risk_factors.add(
                "Heavy rainfall"
            )

        elif "snow" in weather_lower:

            risk_score += 35

            instability_detected = True

            risk_factors.add(
                "Snow conditions"
            )

        if rain_volume > 5:

            risk_score += 20

            instability_detected = True

            risk_factors.add(
                "Intense rainfall"
            )

        if wind_speed > 15:

            risk_score += 25

            instability_detected = True

            risk_factors.add(
                "Strong winds"
            )

        if visibility < 2000:

            risk_score += 25

            instability_detected = True

            risk_factors.add(
                "Low visibility"
            )

        if temperature > 42:

            risk_score += 15

            risk_factors.add(
                "Extreme heat"
            )

        if temperature < 2:

            risk_score += 15

            risk_factors.add(
                "Extreme cold"
            )

    return {
        "weather_score": round(risk_score / 8),
        "risk_factors": list(risk_factors),
        "dominant_condition": dominant_condition,
        "max_temperature": round(max_temperature, 2),
        "instability_detected": instability_detected
    }

# =========================================================
# TRAFFIC ANALYSIS
# =========================================================

def calculate_traffic_risk(traffic_data):

    if not traffic_data:

        return {
            "traffic_score": 0,
            "traffic_level": "LOW",
            "current_speed": 65,
            "free_flow_speed": 65,
            "congestion_ratio": 0
        }

    flow_data = traffic_data.get(
        "flowSegmentData",
        {}
    )

    current_speed = flow_data.get(
        "currentSpeed",
        65
    )

    free_flow_speed = max(
        flow_data.get(
            "freeFlowSpeed",
            65
        ),
        1
    )

    congestion_ratio = (
        1 - (
            current_speed /
            free_flow_speed
        )
    )

    score = round(congestion_ratio * 100)

    if score >= 70:

        level = "HIGH"

    elif score >= 40:

        level = "MEDIUM"

    else:

        level = "LOW"

    return {
        "traffic_score": score,
        "traffic_level": level,
        "current_speed": current_speed,
        "free_flow_speed": free_flow_speed,
        "congestion_ratio": round(
            congestion_ratio,
            2
        )
    }

# =========================================================
# ROUTE ANALYSIS ENGINE
# =========================================================

async def analyze_route(
    waypoints,
    distance_km,
    baseline_duration
):

    weather_tasks = [
        get_forecast(
            point["lat"],
            point["lon"]
        )
        for point in waypoints
    ]

    traffic_tasks = [
        get_traffic(
            point["lat"],
            point["lon"]
        )
        for point in waypoints
    ]

    forecasts = await asyncio.gather(
        *weather_tasks
    )

    traffic_results = await asyncio.gather(
        *traffic_tasks
    )

    all_speeds = []

    all_weather_scores = []

    all_traffic_scores = []

    risk_factors = set()

    dominant_weather = "Clear"

    max_temperature = 0

    instability_detected = False

    for idx in range(len(waypoints)):

        forecast = forecasts[idx]

        traffic = traffic_results[idx]

        if not forecast:
            continue

        weather_risk = calculate_weather_risk(
            forecast
        )

        traffic_risk = calculate_traffic_risk(
            traffic
        )

        all_weather_scores.append(
            weather_risk["weather_score"]
        )

        all_traffic_scores.append(
            traffic_risk["traffic_score"]
        )

        all_speeds.append(
            traffic_risk["current_speed"]
        )

        dominant_weather = (
            weather_risk[
                "dominant_condition"
            ]
        )

        max_temperature = max(
            max_temperature,
            weather_risk[
                "max_temperature"
            ]
        )

        if weather_risk[
            "instability_detected"
        ]:
            instability_detected = True

        risk_factors.update(
            weather_risk[
                "risk_factors"
            ]
        )

    if all_speeds:

        effective_speed = round(
            sum(all_speeds) /
            len(all_speeds),
            2
        )

    else:

        effective_speed = 65

    predicted_duration = round(
        distance_km / max(effective_speed, 1),
        2
    )

    estimated_delay = round(
        max(
            predicted_duration -
            baseline_duration,
            0
        ),
        2
    )

    avg_weather_score = (
        sum(all_weather_scores) /
        max(len(all_weather_scores), 1)
    )

    avg_traffic_score = (
        sum(all_traffic_scores) /
        max(len(all_traffic_scores), 1)
    )

    overall_score = round(
        (avg_weather_score * 0.4) +
        (avg_traffic_score * 0.6)
    )

    if overall_score >= 75:

        risk_level = "CRITICAL"

    elif overall_score >= 55:

        risk_level = "HIGH"

    elif overall_score >= 30:

        risk_level = "MEDIUM"

    else:

        risk_level = "LOW"

    if effective_speed < 35:

        corridor_stability = "Congested"

    elif effective_speed < 50:

        corridor_stability = "Moderate"

    else:

        corridor_stability = "Stable"

    if effective_speed >= 55:

        traffic_impact = (
            "Minimal congestion detected "
            "across analyzed checkpoints."
        )

        congestion_level = "LOW"

    elif effective_speed >= 40:

        traffic_impact = (
            "Moderate traffic congestion "
            "observed across route segments."
        )

        congestion_level = "MEDIUM"

    else:

        traffic_impact = (
            "Severe traffic slowdown detected "
            "across operational corridor."
        )

        congestion_level = "HIGH"

    if risk_level == "CRITICAL":

        dispatch_feasibility = (
            "Avoid non-essential dispatch operations."
        )

    elif risk_level == "HIGH":

        dispatch_feasibility = (
            "Dispatch only with active monitoring "
            "and rerouting readiness."
        )

    elif risk_level == "MEDIUM":

        dispatch_feasibility = (
            "Proceed with caution and "
            "continuous corridor monitoring."
        )

    else:

        dispatch_feasibility = (
            "Acceptable for standard shipment movement."
        )

    return {

        "overall_risk_score": overall_score,

        "overall_risk_level": risk_level,

        "predicted_operational_travel_time_hours":
            predicted_duration,

        "estimated_delay_hours":
            estimated_delay,

        "risk_factors":
            list(risk_factors),

        "dominant_weather":
            dominant_weather,

        "max_temperature":
            round(max_temperature, 2),

        "weather_instability":
            instability_detected,

        "average_speed":
            effective_speed,

        "traffic_level":
            congestion_level,

        "traffic_interpretation":
            traffic_impact,

        "corridor_stability":
            corridor_stability,

        "dispatch_feasibility":
            dispatch_feasibility,

        "segments_analyzed":
            len(waypoints)
    }

# =========================================================
# RECOMMENDATION ENGINE
# =========================================================

def generate_recommendation(analysis):

    level = analysis[
        "overall_risk_level"
    ]

    if level == "CRITICAL":

        return (
            "Severe operational instability detected "
            "across the shipment corridor. Dispatch "
            "operations should be avoided until "
            "route conditions stabilize."
        )

    elif level == "HIGH":

        return (
            "Operational degradation detected across "
            "multiple route segments. Prepare rerouting "
            "contingencies and monitor movement continuously."
        )

    elif level == "MEDIUM":

        return (
            "Moderate operational disruption detected. "
            "Shipment movement may continue with active "
            "monitoring and ETA buffer adjustments."
        )

    return (
        "Corridor conditions are currently stable "
        "for shipment movement. No major operational "
        "disruption detected across analyzed checkpoints."
    )

# =========================================================
# MAIN API
# =========================================================

@app.get(
    "/route-risk",
    response_model=RouteRiskResponse
)

async def route_risk(
    source: str,
    destination: str
):

    source_coords = await get_coordinates(source)

    destination_coords = await get_coordinates(destination)

    if not source_coords or not destination_coords:

        raise HTTPException(
            status_code=400,
            detail="Invalid source or destination city."
    )

    route_data = await get_route(
        source_coords,
        destination_coords
    )

    if not route_data:

        raise HTTPException(
            status_code=500,
            detail="Unable to fetch route information."
        )

    route_geometry = route_data["geometry"]

    distance_km = route_data["distance_km"]

    baseline_duration = route_data["duration_hours"]

    decoded_coordinates = polyline.decode(
        route_geometry
    )

    formatted_coordinates = []

    for lat, lon in decoded_coordinates:

        formatted_coordinates.append(
            [lon, lat]
        )

    waypoints = sample_waypoints(
        formatted_coordinates
    )

    route_analysis = await analyze_route(
        waypoints,
        distance_km,
        baseline_duration
    )

    recommendation = generate_recommendation(
        route_analysis
    )

    return {

        "success": True,

        "source": source,

        "destination": destination,

        "route_summary": {

            "route_distance_km":
                distance_km,

            "baseline_travel_time_hours":
                baseline_duration,

            "predicted_operational_travel_time_hours":
                route_analysis[
                    "predicted_operational_travel_time_hours"
                ],

            "checkpoints_analyzed":
                route_analysis[
                    "segments_analyzed"
                ]
        },

        "traffic_summary": {

            "congestion_level":
                route_analysis[
                    "traffic_level"
                ],

            "average_corridor_speed_kmph":
                route_analysis[
                    "average_speed"
                ],

            "operational_traffic_impact":
                route_analysis[
                    "traffic_interpretation"
                ]
        },

        "weather_summary": {

            "dominant_weather_condition":
                route_analysis[
                    "dominant_weather"
                ],

            "temperature_celsius":
                route_analysis[
                    "max_temperature"
                ],

            "weather_instability_detected":
                route_analysis[
                    "weather_instability"
                ],

            "weather_risk_factors":
                route_analysis[
                    "risk_factors"
                ]
        },

        "operational_assessment": {

            "overall_risk_score":
                route_analysis[
                    "overall_risk_score"
                ],

            "overall_risk_level":
                route_analysis[
                    "overall_risk_level"
                ],

            "estimated_operational_delay_hours":
                route_analysis[
                    "estimated_delay_hours"
                ],

            "corridor_stability":
                route_analysis[
                    "corridor_stability"
                ],

            "dispatch_feasibility":
                route_analysis[
                    "dispatch_feasibility"
                ]
        },

        "recommendation":
            recommendation
    }
