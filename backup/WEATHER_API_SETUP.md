# Weather API Setup

## OpenWeatherMap API Key

To get weather data for multiple stations, you need a free OpenWeatherMap API key.

### Steps:

1. Go to https://openweathermap.org/api
2. Click "Sign Up" (top right)
3. Create a free account
4. Once logged in, go to "API keys" section
5. Copy your API key

### Set the API Key:

**Option 1: Environment Variable (Recommended)**
Create a `.env` file in the project root:
```
OPENWEATHERMAP_API_KEY=your_api_key_here
```

**Option 2: Direct in config.py**
Edit `config.py` and set:
```python
WEATHER_CONFIG = {
    "openweathermap_api_key": "your_api_key_here",
}
```

### Free Tier Limits:
- 1000 calls/day
- 60 calls/minute
- More than enough for 4 stations updating every 5-10 minutes

### Testing:
Once the API key is set, the weather stations will automatically fetch data from OpenWeatherMap API using the coordinates for each station location.

