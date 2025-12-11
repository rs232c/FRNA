/**
 * Weather Fetcher - Fetches weather data for zip code
 */

class WeatherFetcher {
    constructor() {
        this.apiKey = ''; // Will be set from config or env
        // NO CACHING - Always fetch fresh data on every page load
    }

    async fetchWeather(zipCode) {
        if (!zipCode) return null;

        // NO CACHING - Always fetch fresh data on every page load
        try {
            // Use OpenWeatherMap's zip code endpoint directly (no need to convert to lat/lon)
            const apiKey = this.getApiKey();
            if (!apiKey) {
                console.warn('OpenWeatherMap API key not configured');
                return this.getDefaultWeather();
            }

            // Debug: Log zip code being used
            console.log(`[Weather] Fetching weather for zip code: ${zipCode}`);

            // For zip 02720 (Fall River), use coordinates for more accuracy
            // Fall River, MA coordinates: lat 41.7015, lon -71.1550
            let url;
            const timestamp = Date.now();
            
            if (zipCode === '02720') {
                // Use coordinates for Fall River to ensure accurate location
                url = `https://api.openweathermap.org/data/2.5/weather?lat=41.7015&lon=-71.1550&appid=${apiKey}&units=imperial&_t=${timestamp}`;
                console.log(`[Weather] Using coordinates for Fall River: lat=41.7015, lon=-71.1550`);
            } else {
                // Use zip code for other locations
                url = `https://api.openweathermap.org/data/2.5/weather?zip=${zipCode},us&appid=${apiKey}&units=imperial&_t=${timestamp}`;
            }
            const response = await fetch(url, {
                cache: 'no-cache'
                // Removed headers to avoid CORS preflight
            });
            
            if (!response.ok) {
                throw new Error(`Weather API error: ${response.status}`);
            }

            const data = await response.json();
            
            // Debug: Log API response location data
            console.log(`[Weather] API Response - Location: ${data.name}, ${data.sys?.country || 'US'}, Temp: ${data.main?.temp}°F`);
            console.log(`[Weather] API Response - Coordinates: lat=${data.coord?.lat}, lon=${data.coord?.lon}`);
            
            // Verify location matches Fall River (zip 02720)
            const locationName = data.name?.toLowerCase() || '';
            const isFallRiver = locationName.includes('fall river') || 
                               locationName.includes('fallriver') ||
                               (data.coord?.lat && Math.abs(data.coord.lat - 41.7015) < 0.1 && 
                                data.coord?.lon && Math.abs(data.coord.lon - (-71.1550)) < 0.1);
            
            if (!isFallRiver && zipCode === '02720') {
                console.warn(`[Weather] WARNING: API returned location "${data.name}" but expected Fall River, MA. Coordinates: ${data.coord?.lat}, ${data.coord?.lon}`);
            }
            
            // Fetch 7-day forecast (use same method as current weather)
            let forecastUrl;
            if (zipCode === '02720') {
                forecastUrl = `https://api.openweathermap.org/data/2.5/forecast?lat=41.7015&lon=-71.1550&appid=${apiKey}&units=imperial&_t=${timestamp}`;
            } else {
                forecastUrl = `https://api.openweathermap.org/data/2.5/forecast?zip=${zipCode},us&appid=${apiKey}&units=imperial&_t=${timestamp}`;
            }
            const forecastResponse = await fetch(forecastUrl, {
                cache: 'no-cache'
                // Removed headers to avoid CORS preflight
            });
            const forecastData = forecastResponse.ok ? await forecastResponse.json() : null;

            const weather = this.formatWeatherData(data, forecastData);
            
            // NO CACHING - Return fresh data immediately

            return weather;
        } catch (error) {
            console.error('[Weather] Error fetching weather:', error);
            return this.getDefaultWeather();
        }
    }

    async resolveZipToCoords(zipCode) {
        // No longer needed - OpenWeatherMap accepts zip codes directly
        // But keep for backwards compatibility if needed elsewhere
        return { lat: 41.7015, lon: -71.1550 }; // Fall River default
    }

    formatWeatherData(current, forecast) {
        return {
            current: {
                temperature: Math.round(current.main.temp),
                unit: '°F',
                condition: current.weather[0].main,
                icon: this.getWeatherIcon(current.weather[0].main),
                feels_like: Math.round(current.main.feels_like),
                humidity: current.main.humidity,
                wind_speed: Math.round(current.wind.speed)
            },
            forecast: this.formatForecast(forecast)
        };
    }

    formatForecast(forecastData) {
        if (!forecastData || !forecastData.list) {
            return this.getDefaultForecast();
        }

        // Group by day and get high/low
        const daily = {};
        forecastData.list.forEach(item => {
            const date = new Date(item.dt * 1000);
            const dayKey = date.toDateString();
            
            if (!daily[dayKey]) {
                daily[dayKey] = {
                    day: date.toLocaleDateString('en-US', { weekday: 'short' }),
                    date: date,
                    temps: [],
                    conditions: []
                };
            }
            
            daily[dayKey].temps.push(item.main.temp);
            daily[dayKey].conditions.push(item.weather[0].main);
        });

        // Format for display
        const forecast = [];
        const sortedDays = Object.values(daily).sort((a, b) => a.date - b.date);
        
        sortedDays.slice(0, 7).forEach(day => {
            const high = Math.round(Math.max(...day.temps));
            const low = Math.round(Math.min(...day.temps));
            const condition = day.conditions[Math.floor(day.conditions.length / 2)]; // Most common
            
            forecast.push({
                day: day.day,
                high: high,
                low: low,
                condition: condition,
                icon: this.getWeatherIcon(condition)
            });
        });

        return forecast.length > 0 ? forecast : this.getDefaultForecast();
    }

    getWeatherIcon(condition) {
        const icons = {
            'Clear': '☀️',
            'Clouds': '☁️',
            'Rain': '🌧️',
            'Drizzle': '🌦️',
            'Thunderstorm': '⛈️',
            'Snow': '❄️',
            'Mist': '🌫️',
            'Fog': '🌫️'
        };
        return icons[condition] || '☀️';
    }

    getDefaultWeather() {
        return {
            current: {
                temperature: 0,  // Changed to 0 so it shows "0°F" when API fails
                unit: '°F',
                condition: 'Clear',
                icon: '☀️'
            },
            forecast: this.getDefaultForecast()
        };
    }

    getDefaultForecast() {
        const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        return days.map((day, i) => ({
            day: day,
            high: 65 + (i * 2),
            low: 45 + (i * 2),
            condition: 'Clear',
            icon: '☀️'
        }));
    }

    getApiKey() {
        // Try to get from window config or use empty (will use default)
        return window.WEATHER_API_KEY || '';
    }
}

// Initialize weather fetcher
let weatherFetcher;
if (typeof window !== 'undefined') {
    weatherFetcher = new WeatherFetcher();
    window.weatherFetcher = weatherFetcher;
}

