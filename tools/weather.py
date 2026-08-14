import json
import urllib.error
import urllib.parse
import urllib.request

from config import settings
from tools.registry import BaseTool

WTTR_URL = "https://wttr.in/{location}?format=j1"


class WeatherTool(BaseTool):
    name = "weather"
    description = (
        "Météo actuelle et prévisions (source : wttr.in). Utilise-le quand l'utilisateur "
        "demande le temps qu'il fait, la température, s'il pleut, la météo du jour ou "
        "des prochains jours, ou pour décider quoi porter / faire dehors."
    )
    parameters = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "Ville (ex: 'Moscow', 'Paris'). Défaut : la ville configurée (WEATHER_LOCATION).",
            },
            "days": {"type": "integer", "description": "Nombre de jours de prévision (défaut 3)."},
        },
    }

    def run(self, args: dict, user_id: int) -> dict:
        location = (args.get("location") or settings.WEATHER_LOCATION or "Moscow").strip()
        days = max(1, min(int(args.get("days") or 3), 5))

        url = WTTR_URL.format(location=urllib.parse.quote(location))
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return self._err(f"wttr.in a répondu {exc.code} (ville introuvable ?).")
        except (urllib.error.URLError, TimeoutError) as exc:
            return self._err(f"Réseau : {exc.reason}")

        try:
            current = data["current_condition"][0]
            cur = {
                "temp_c": current.get("temp_C"),
                "feels_like_c": current.get("FeelsLikeC"),
                "humidity_pct": current.get("humidity"),
                "wind_kph": current.get("windspeedKmph"),
                "cloudcover_pct": current.get("cloudcover"),
                "description": current.get("weatherDesc", [{}])[0].get("value", ""),
            }
            forecast = []
            for day in data.get("weather", [])[:days]:
                forecast.append({
                    "date": day.get("date"),
                    "min_c": day.get("mintempC"),
                    "max_c": day.get("maxtempC"),
                    "description": day.get("hourly", [{}])[0].get("weatherDesc", [{}])[0].get("value", ""),
                })
            return {"location": location, "current": cur, "forecast": forecast}
        except (KeyError, IndexError, TypeError):
            return self._err("Réponse météo inattendue.")
