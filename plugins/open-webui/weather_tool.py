"""
title: Weather Lookup Tool
author: airpods
author_url: https://github.com/radicazz/airpods
version: 0.1.0
description: Allows LLMs to fetch real-time weather data for any location using wttr.in API.
required_open_webui_version: 0.3.0
"""

import json
import requests
from typing import Optional
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Priority level for the tool operations."
        )
        timeout_seconds: int = Field(
            default=10, description="HTTP request timeout in seconds."
        )

    def __init__(self):
        self.valves = self.Valves()

    def get_weather(self, location: str, units: str = "metric") -> str:
        """
        Fetch current weather information for a specified location.

        :param location: City name, airport code, or coordinates (e.g., "London", "LAX", "48.8566,2.3522")
        :param units: Temperature units - "metric" for Celsius or "imperial" for Fahrenheit
        :return: Weather data as a formatted string
        """
        try:
            # Use wttr.in API which is free and requires no API key
            # Format: wttr.in/{location}?format=j1 for JSON output
            url = f"https://wttr.in/{location}?format=j1"

            if units == "imperial":
                url += "&u"  # Add imperial units flag

            response = requests.get(url, timeout=self.valves.timeout_seconds)
            response.raise_for_status()

            data = response.json()

            # Extract relevant current weather data
            current = data.get("current_condition", [{}])[0]
            location_info = data.get("nearest_area", [{}])[0]

            location_name = location_info.get("areaName", [{}])[0].get(
                "value", location
            )
            country = location_info.get("country", [{}])[0].get("value", "Unknown")

            temp_unit = "°F" if units == "imperial" else "°C"

            weather_info = {
                "location": f"{location_name}, {country}",
                "temperature": f"{current.get('temp_C', 'N/A')}°C ({current.get('temp_F', 'N/A')}°F)",
                "feels_like": f"{current.get('FeelsLikeC', 'N/A')}°C ({current.get('FeelsLikeF', 'N/A')}°F)",
                "condition": current.get("weatherDesc", [{}])[0].get("value", "N/A"),
                "humidity": f"{current.get('humidity', 'N/A')}%",
                "wind": f"{current.get('windspeedKmph', 'N/A')} km/h {current.get('winddir16Point', '')}",
                "precipitation": f"{current.get('precipMM', 'N/A')} mm",
                "pressure": f"{current.get('pressure', 'N/A')} mb",
                "visibility": f"{current.get('visibility', 'N/A')} km",
                "uv_index": current.get("uvIndex", "N/A"),
            }

            # Format as readable string
            result = f"**Weather for {weather_info['location']}:**\n\n"
            result += f"🌡️ Temperature: {weather_info['temperature']}\n"
            result += f"🤔 Feels like: {weather_info['feels_like']}\n"
            result += f"☁️ Condition: {weather_info['condition']}\n"
            result += f"💧 Humidity: {weather_info['humidity']}\n"
            result += f"💨 Wind: {weather_info['wind']}\n"
            result += f"🌧️ Precipitation: {weather_info['precipitation']}\n"
            result += f"📊 Pressure: {weather_info['pressure']}\n"
            result += f"👁️ Visibility: {weather_info['visibility']}\n"
            result += f"☀️ UV Index: {weather_info['uv_index']}\n"

            return result

        except requests.RequestException as e:
            return f"Error fetching weather data: {str(e)}"
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return f"Error parsing weather data: {str(e)}"
        except Exception as e:
            return f"Unexpected error: {str(e)}"
