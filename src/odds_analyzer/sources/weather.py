from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from odds_analyzer.sources.football_data import FootballDataFixture


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
COMPETITION_COUNTRIES = {"PL": "GB", "PD": "ES", "SA": "IT", "BL1": "DE", "FL1": "FR"}

TEAM_CITY_OVERRIDES = {
    "arsenal": "London",
    "aston villa": "Birmingham",
    "athletic club": "Bilbao",
    "atletico madrid": "Madrid",
    "atalanta": "Bergamo",
    "chelsea": "London",
    "crystal palace": "London",
    "everton": "Liverpool",
    "espanyol": "Barcelona",
    "rcd espanyol de barcelona": "Barcelona",
    "fiorentina": "Florence",
    "fulham": "London",
    "internazionale milano": "Milan",
    "inter milan": "Milan",
    "juventus": "Turin",
    "lazio": "Rome",
    "nottingham forest": "Nottingham",
    "olympique de marseille": "Marseille",
    "olympique lyonnais": "Lyon",
    "paris saint germain": "Paris",
    "racing club de lens": "Lens",
    "rc lens": "Lens",
    "real betis": "Seville",
    "real sociedad": "San Sebastian",
    "stade brestois 29": "Brest",
    "udinese": "Udine",
    "tottenham hotspur": "London",
    "west ham united": "London",
    "wolverhampton wanderers": "Wolverhampton",
}


@dataclass(frozen=True)
class WeatherLocation:
    name: str
    latitude: float
    longitude: float
    country_code: str


@dataclass(frozen=True)
class WeatherSnapshot:
    match_id: int
    location: str
    latitude: float
    longitude: float
    forecast_time: str
    temperature_c: float | None
    precipitation_probability: float | None
    weather_code: int | None
    wind_speed_kmh: float | None
    wind_gusts_kmh: float | None
    source: str = "Open-Meteo"


@dataclass(frozen=True)
class WeatherBatch:
    forecasts: dict[int, WeatherSnapshot]
    errors: tuple[str, ...] = ()
    source: str = "Open-Meteo"


def fetch_fixture_weather(
    fixtures: tuple[FootballDataFixture, ...], timeout: float = 20
) -> WeatherBatch:
    requests: list[tuple[FootballDataFixture, str, str]] = []
    errors: list[str] = []
    for fixture in fixtures:
        country_code = COMPETITION_COUNTRIES.get(fixture.competition_code)
        if not country_code:
            errors.append(f"match {fixture.match_id}: country unavailable for weather lookup")
            continue
        requests.append((fixture, team_city_query(fixture.home_team), country_code))

    locations: dict[tuple[str, str], WeatherLocation] = {}
    for _, city, country_code in requests:
        key = (city.casefold(), country_code)
        if key in locations:
            continue
        try:
            location = _geocode(city, country_code, timeout)
        except Exception as exc:
            errors.append(f"{city}: {type(exc).__name__}")
            continue
        if location is None:
            errors.append(f"{city}: location not found")
            continue
        locations[key] = location

    resolved = [
        (fixture, locations[(city.casefold(), country_code)])
        for fixture, city, country_code in requests
        if (city.casefold(), country_code) in locations
    ]
    if not resolved:
        return WeatherBatch(forecasts={}, errors=tuple(errors))

    try:
        payload = _forecast([location for _, location in resolved], timeout)
    except Exception as exc:
        errors.append(f"forecast: {type(exc).__name__}")
        return WeatherBatch(forecasts={}, errors=tuple(errors))

    responses = payload if isinstance(payload, list) else [payload]
    forecasts: dict[int, WeatherSnapshot] = {}
    for (fixture, location), response in zip(resolved, responses):
        snapshot = parse_hourly_weather(fixture, location, response)
        if snapshot is None:
            errors.append(f"match {fixture.match_id}: kickoff hour unavailable")
            continue
        forecasts[fixture.match_id] = snapshot
    return WeatherBatch(forecasts=forecasts, errors=tuple(errors))


def team_city_query(team_name: str) -> str:
    normalized = _normalize_team(team_name)
    if normalized in TEAM_CITY_OVERRIDES:
        return TEAM_CITY_OVERRIDES[normalized]
    words = re.sub(
        r"\b(fc|afc|cf|cfc|ac|ssc|rcd|rc|ogc|es|aj|as|calcio)\b|\b(19|20)\d{2}\b",
        " ",
        team_name,
        flags=re.IGNORECASE,
    )
    words = re.sub(
        r"^(real|borussia|bayer|eintracht|olympique|stade|rb)\s+|\s+(united|city|town|albion)$",
        "",
        words.strip(),
        flags=re.IGNORECASE,
    )
    words = re.sub(r"\s+", " ", words).strip(" -")
    return words or team_name


def parse_hourly_weather(
    fixture: FootballDataFixture,
    location: WeatherLocation,
    payload: dict[str, Any],
) -> WeatherSnapshot | None:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None
    kickoff = _parse_time(fixture.utc_date)
    parsed_times = [_parse_time(value) for value in times]
    index = min(range(len(parsed_times)), key=lambda item: abs(parsed_times[item] - kickoff))
    if abs((parsed_times[index] - kickoff).total_seconds()) > 5400:
        return None
    return WeatherSnapshot(
        match_id=fixture.match_id,
        location=location.name,
        latitude=location.latitude,
        longitude=location.longitude,
        forecast_time=times[index],
        temperature_c=_number_at(hourly, "temperature_2m", index),
        precipitation_probability=_number_at(hourly, "precipitation_probability", index),
        weather_code=_integer_at(hourly, "weather_code", index),
        wind_speed_kmh=_number_at(hourly, "wind_speed_10m", index),
        wind_gusts_kmh=_number_at(hourly, "wind_gusts_10m", index),
    )


def weather_description(code: int | None, language: str = "zh") -> str:
    group = "unknown"
    if code == 0:
        group = "clear"
    elif code in {1, 2, 3}:
        group = "cloudy"
    elif code in {45, 48}:
        group = "fog"
    elif code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        group = "rain"
    elif code in {71, 73, 75, 77, 85, 86}:
        group = "snow"
    elif code in {95, 96, 99}:
        group = "storm"
    labels = {
        "zh": {"clear": "晴", "cloudy": "多云", "fog": "有雾", "rain": "有雨", "snow": "有雪", "storm": "雷暴", "unknown": "天气状况未分类"},
        "en": {"clear": "Clear", "cloudy": "Cloudy", "fog": "Fog", "rain": "Rain", "snow": "Snow", "storm": "Thunderstorm", "unknown": "Unclassified conditions"},
    }
    return labels[language][group]


def _geocode(city: str, country_code: str, timeout: float) -> WeatherLocation | None:
    payload = _get_json(
        GEOCODING_URL,
        {"name": city, "count": 1, "language": "en", "format": "json", "countryCode": country_code},
        timeout,
    )
    results = payload.get("results") or []
    if not results:
        return None
    result = results[0]
    return WeatherLocation(
        name=str(result.get("name") or city),
        latitude=float(result["latitude"]),
        longitude=float(result["longitude"]),
        country_code=str(result.get("country_code") or country_code),
    )


def _forecast(locations: list[WeatherLocation], timeout: float) -> Any:
    return _get_json(
        FORECAST_URL,
        {
            "latitude": ",".join(str(location.latitude) for location in locations),
            "longitude": ",".join(str(location.longitude) for location in locations),
            "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m,wind_gusts_10m",
            "timezone": "GMT",
            "forecast_days": 2,
        },
        timeout,
    )


def _get_json(url: str, params: dict[str, Any], timeout: float) -> Any:
    request = Request(f"{url}?{urlencode(params)}", headers={"User-Agent": "odds-analyzer/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_team(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    value = re.sub(r"\b(fc|afc|cf|cfc|ac|ssc|calcio)\b", " ", value)
    return " ".join(value.split())


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number_at(hourly: dict[str, Any], key: str, index: int) -> float | None:
    values = hourly.get(key) or []
    if index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def _integer_at(hourly: dict[str, Any], key: str, index: int) -> int | None:
    value = _number_at(hourly, key, index)
    return int(value) if value is not None else None
