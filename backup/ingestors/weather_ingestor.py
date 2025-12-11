"""
Weather ingestion module for Fall River, MA
"""
import requests
import logging
from datetime import datetime
from typing import Dict, Optional, List
from config import LOCALE, WEATHER_CONFIG
from cache import get_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WeatherIngestor:
    """Fetch weather data for Fall River, MA"""
    
    def __init__(self):
        self.location = "Fall River, MA"
        self.api_key = WEATHER_CONFIG.get("openweathermap_api_key", "")
        if not self.api_key:
            logger.warning("OpenWeatherMap API key not set. Get a free key at https://openweathermap.org/api")
    
    def fetch_weather(self) -> Dict:
        """Fetch current weather and forecast"""
        cache = get_cache()
        cache_key = f"weather:{self.location}"
        
        # Check cache first
        cached_weather = cache.get("weather", cache_key)
        if cached_weather:
            logger.debug("Using cached weather data")
            return cached_weather
        
        try:
            # Try OpenWeatherMap API first (free tier available)
            weather = self._fetch_from_openweather()
            if weather:
                # Cache the result
                cache.set("weather", cache_key, weather)
                return weather
            
            # Fallback to basic data structure
            weather = self._get_fallback_weather()
            # Cache fallback too (shorter TTL)
            cache.set("weather", cache_key, weather, ttl=2 * 60)  # 2 minutes for fallback
            return weather
        
        except Exception as e:
            logger.error(f"Error fetching weather: {e}")
            weather = self._get_fallback_weather()
            cache.set("weather", cache_key, weather, ttl=2 * 60)
            return weather
    
    def _fetch_from_openweather(self) -> Optional[Dict]:
        """Fetch from OpenWeatherMap API"""
        if not self.api_key:
            logger.warning("OpenWeatherMap API key not set. Get a free key at https://openweathermap.org/api")
            return None
        
        try:
            # Fall River, MA coordinates
            lat, lon = 41.7015, -71.1550
            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": "imperial"  # Get temperature in Fahrenheit
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Map OpenWeatherMap response to our format
            weather_data = {
                "location": self.location,
                "current": {
                    "temperature": round(data.get("main", {}).get("temp", 0)),
                    "unit": "°F",
                    "condition": data.get("weather", [{}])[0].get("main", "Unknown"),
                    "description": data.get("weather", [{}])[0].get("description", ""),
                    "icon": self._get_weather_icon(data.get("weather", [{}])[0].get("main", "Clear")),
                    "feels_like": round(data.get("main", {}).get("feels_like", 0)),
                    "humidity": data.get("main", {}).get("humidity", 0),
                    "wind_speed": round(data.get("wind", {}).get("speed", 0)),
                    "wind_direction": self._get_wind_direction(data.get("wind", {}).get("deg"))
                },
                "forecast": []  # Can add forecast later if needed
            }
            
            logger.info(f"Successfully fetched weather from OpenWeatherMap: {weather_data['current']['temperature']}°F, {weather_data['current']['condition']}")
            return weather_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching from OpenWeatherMap API: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in OpenWeatherMap fetch: {e}")
            return None
    
    def _get_fallback_weather(self) -> Dict:
        """Fallback weather data structure"""
        # This can be enhanced with actual API calls
        # For now, return a structured format
        return {
            "location": self.location,
            "current": {
                "temperature": 36,
                "unit": "°F",
                "condition": "Clear",
                "icon": "☀️",
                "feels_like": 34,
                "humidity": 65,
                "wind_speed": 5,
                "wind_direction": "NW"
            },
            "forecast": [
                {
                    "day": "Today",
                    "high": 43,
                    "low": 30,
                    "condition": "Partly Cloudy",
                    "icon": "⛅"
                },
                {
                    "day": "Sun",
                    "high": 41,
                    "low": 26,
                    "condition": "Cloudy",
                    "icon": "☁️"
                },
                {
                    "day": "Mon",
                    "high": 29,
                    "low": 12,
                    "condition": "Sunny",
                    "icon": "☀️"
                },
                {
                    "day": "Tue",
                    "high": 35,
                    "low": 32,
                    "condition": "Cloudy",
                    "icon": "☁️"
                },
                {
                    "day": "Wed",
                    "high": 46,
                    "low": 36,
                    "condition": "Rain",
                    "icon": "🌧️"
                }
            ],
            "updated": datetime.now().isoformat()
        }
    
    def fetch_wattupa_weather(self) -> Optional[Dict]:
        """Fetch from Wattupa weather station if available"""
        # Wattupa weather station specific integration
        # This would need the actual API endpoint or data source
        try:
            # Placeholder for Wattupa weather station API
            # You would need to find the actual endpoint
            logger.info("Wattupa weather station integration - needs API endpoint")
            return None
        except Exception as e:
            logger.error(f"Error fetching Wattupa weather: {e}")
            return None
    
    def get_primary_weather_station_url(self) -> str:
        """Get the primary weather station URL for Fall River/Wattupa area
        
        Returns:
            URL to Weather Underground Fall River page
        """
        # Use Weather Underground for Fall River, MA
        return "https://www.wunderground.com/weather/us/ma/fall-river"
    
    # Weather Underground Personal Weather Station (PWS) configuration
    WEATHER_STATIONS = [
        {
            "station_id": "KMAFALLR62",
            "name": "Fall River",
            "location": {"lat": 41.70, "lon": -71.16, "elevation": 131},
            "url": "https://www.wunderground.com/dashboard/pws/KMAFALLR62"
        },
        {
            "station_id": "KMAFALLR41",
            "name": "Saint Anne's",
            "location": {"lat": 41.70, "lon": -71.16, "elevation": 135},  # Approximate city center
            "url": "https://www.wunderground.com/dashboard/pws/KMAFALLR41"
        },
        {
            "station_id": "KMAFALLR27",
            "name": "Highlands",
            "location": {"lat": 41.70, "lon": -71.16, "elevation": 197},  # Approximate city center
            "url": "https://www.wunderground.com/dashboard/pws/KMAFALLR27"
        },
        {
            "station_id": "KMAFALLR7",
            "name": "Fall River Station 7",
            "location": {"lat": 41.69, "lon": -71.17, "elevation": 200},
            "url": "https://www.wunderground.com/dashboard/pws/KMAFALLR7"
        }
    ]
    
    def _fetch_from_openweathermap(self, lat: float, lon: float) -> Optional[Dict]:
        """Fetch current weather data from OpenWeatherMap API by coordinates"""
        if not self.api_key:
            logger.error("OpenWeatherMap API key not configured")
            return None
        
        try:
            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": "imperial"  # Get temperature in Fahrenheit
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Map OpenWeatherMap response to our format
            weather_data = {
                "temperature": round(data.get("main", {}).get("temp", 0)),
                "unit": "°F",
                "feels_like": round(data.get("main", {}).get("feels_like", 0)),
                "humidity": data.get("main", {}).get("humidity"),
                "wind_speed": round(data.get("wind", {}).get("speed", 0)),
                "condition": data.get("weather", [{}])[0].get("main", "Unknown"),
                "description": data.get("weather", [{}])[0].get("description", ""),
                "icon_code": data.get("weather", [{}])[0].get("icon", ""),
                "updated": datetime.now().isoformat()
            }
            
            # Map condition to emoji icon
            weather_data["icon"] = self._get_weather_icon(weather_data["condition"])
            
            return weather_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching from OpenWeatherMap API: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error processing OpenWeatherMap data: {e}", exc_info=True)
            return None
    
    def fetch_wunderground_station(self, station_id: str) -> Optional[Dict]:
        """Fetch weather data for a station using OpenWeatherMap API by coordinates"""
        cache = get_cache()
        cache_key = f"weather_station:{station_id}"
        
        # Check cache first (5 minute TTL)
        cached_data = cache.get("weather", cache_key)
        if cached_data:
            logger.debug(f"Using cached data for station {station_id}")
            return cached_data
        
        # Find station config
        station_config = None
        for station in self.WEATHER_STATIONS:
            if station["station_id"] == station_id:
                station_config = station
                break
        
        if not station_config:
            logger.error(f"Station {station_id} not found in configuration")
            return None
        
        # Fetch weather data from OpenWeatherMap API using station coordinates
        lat = station_config["location"]["lat"]
        lon = station_config["location"]["lon"]
        
        weather_data = self._fetch_from_openweathermap(lat, lon)
        
        if not weather_data:
            logger.warning(f"Failed to fetch weather data for station {station_id}")
            return None
        
        # Build station data structure
        station_data = {
            "station_id": station_id,
            "name": station_config["name"],
            "location": station_config["location"],
            "current": weather_data
        }
        
        # Cache for 5 minutes
        cache.set("weather", cache_key, station_data, ttl=5 * 60)
        
        temp_display = f"{station_data['current'].get('temperature')}°F" if station_data['current'].get('temperature') is not None else "N/A"
        logger.info(f"Fetched data for station {station_id}: {temp_display}")
        return station_data
    
    def _get_weather_icon(self, condition: str) -> str:
        """Get emoji icon for weather condition"""
        condition_lower = condition.lower()
        if "rain" in condition_lower or "shower" in condition_lower:
            return "🌧️"
        elif "snow" in condition_lower:
            return "❄️"
        elif "storm" in condition_lower or "thunder" in condition_lower:
            return "⛈️"
        elif "cloud" in condition_lower or "overcast" in condition_lower:
            return "☁️"
        elif "sun" in condition_lower or "clear" in condition_lower:
            return "☀️"
        elif "fog" in condition_lower or "mist" in condition_lower:
            return "🌫️"
        else:
            return "⛅"
    
    def _get_wind_direction(self, degrees: Optional[float]) -> str:
        """Convert wind direction in degrees to cardinal direction"""
        if degrees is None:
            return ""
        # Map degrees to cardinal directions
        directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                     "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        index = int((degrees + 11.25) / 22.5) % 16
        return directions[index]
    
    def fetch_all_stations(self) -> List[Dict]:
        """Fetch weather data from all configured stations"""
        stations = []
        for station_config in self.WEATHER_STATIONS:
            station_data = self.fetch_wunderground_station(station_config["station_id"])
            if station_data:
                stations.append(station_data)
            else:
                # Return station config even if fetch fails, with placeholder data
                stations.append({
                    "station_id": station_config["station_id"],
                    "name": station_config["name"],
                    "location": station_config["location"],
                    "current": {
                        "temperature": None,
                        "unit": "°F",
                        "feels_like": None,
                        "humidity": None,
                        "wind_speed": None,
                        "condition": "Data unavailable",
                        "icon": "❓",
                        "updated": datetime.now().isoformat()
                    }
                })
        return stations



