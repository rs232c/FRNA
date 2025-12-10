/**
 * Weather Fetcher - Fetches weather data for zip code
 */

class WeatherFetcher {
    constructor() {
        this.apiKey = ''; // Will be set from config or env
        this.cache = new Map();
    }

    async fetchWeather(zipCode) {
        if (!zipCode) return null;

        // Check cache
        const cacheKey = `weather_${zipCode}`;
        const cached = this.cache.get(cacheKey);
        if (cached && Date.now() - cached.timestamp < 30 * 60 * 1000) { // 30 min cache
            return cached.data;
        }

        try {
            // Resolve zip to lat/lon
            const location = await this.resolveZipToCoords(zipCode);
            if (!location) return null;

            // Fetch from OpenWeatherMap (free tier)
            // Note: API key should be in config or passed from server
            const apiKey = this.getApiKey();
            if (!apiKey) {
                console.warn('OpenWeatherMap API key not configured');
                return this.getDefaultWeather();
            }

            const url = `https://api.openweathermap.org/data/2.5/weather?lat=${location.lat}&lon=${location.lon}&appid=${apiKey}&units=imperial`;
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`Weather API error: ${response.status}`);
            }

            const data = await response.json();
            
            // Fetch 7-day forecast
            const forecastUrl = `https://api.openweathermap.org/data/2.5/forecast?lat=${location.lat}&lon=${location.lon}&appid=${apiKey}&units=imperial`;
            const forecastResponse = await fetch(forecastUrl);
            const forecastData = forecastResponse.ok ? await forecastResponse.json() : null;

            const weather = this.formatWeatherData(data, forecastData);
            
            // Cache result
            this.cache.set(cacheKey, {
                data: weather,
                timestamp: Date.now()
            });

            return weather;
        } catch (error) {
            console.error('Error fetching weather:', error);
            return this.getDefaultWeather();
        }
    }

    async resolveZipToCoords(zipCode) {
        try {
            const response = await fetch(`https://api.zippopotam.us/us/${zipCode}`);
            if (response.ok) {
                const data = await response.json();
                if (data.places && data.places.length > 0) {
                    // Use a geocoding service to get lat/lon
                    // For now, return a default location (Fall River)
                    return { lat: 41.7015, lon: -71.1550 };
                }
            }
        } catch (error) {
            console.warn('Error resolving zip to coords:', error);
        }
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
                temperature: 65,
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

