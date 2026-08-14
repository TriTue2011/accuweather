"""Constants for AccuWeather integration."""

DOMAIN = "accuweather"

# Shown on the device page. Keep VERSION in step with manifest.json — the device
# page used to advertise 2026.4.22 while the manifest had moved on.
MANUFACTURER = "TriTue2011"
VERSION = "2026.8.13"

# Config flow
CONF_LOCATION_KEY = "location_key"
CONF_LOCATION_NAME = "location_name"
CONF_UPDATE_INTERVAL = "update_interval"

# Language of the sensor names. "auto" leaves it to Home Assistant, which uses
# the language set in Settings; the other values pin the names to one language
# regardless of it, for people running an English UI who want Vietnamese
# sensors (or the reverse).
CONF_SENSOR_LANGUAGE = "sensor_language"
SENSOR_LANGUAGE_AUTO = "auto"
SENSOR_LANGUAGES: tuple[str, ...] = (SENSOR_LANGUAGE_AUTO, "vi", "en")

# Home Assistant builds entity ids from the local language only for languages it
# can slugify safely; Vietnamese is not one of them, so a Vietnamese install
# still gets English entity ids. Pinning the sensor language must not change
# that, so entity ids keep following this language.
LANGUAGE_FOR_ENTITY_IDS = "en"

# Update intervals. Every cycle reloads the two pages that actually change
# minute to minute (current conditions and MinuteCast) plus the storm feed;
# forecasts, air quality and health indices are reloaded every
# SLOW_REFRESH_EVERY cycles. At the 5-minute default that works out to fewer
# AccuWeather requests per hour than a 15-minute full reload, while current
# conditions and storms land three times sooner.
DEFAULT_UPDATE_INTERVAL = 300  # 5 minutes
MIN_UPDATE_INTERVAL = 180     # 3 minutes
MAX_UPDATE_INTERVAL = 3600    # 60 minutes

# How many cycles between full reloads of the slow-moving pages.
SLOW_REFRESH_EVERY = 4

# Hourly forecast days to fetch. AccuWeather serves day 1..3 (72 hours) without
# a Premium+ subscription; beyond that the pages are paywalled.
HOURLY_DAYS = 3

# API URLs
BASE_URL = "https://www.accuweather.com"
AUTOCOMPLETE_URL = f"{BASE_URL}/web-api/autocomplete"

# Windy.com — public endpoints, no API key required.
WINDY_NODE_URL = "https://node.windy.com"
WINDY_STORMS_URL = f"{WINDY_NODE_URL}/tc/v2/storms"
WINDY_ALERTS_URL = WINDY_NODE_URL + "/capalerts/{lat}/{lon}?source=hp&lang=vi&maxCount=6"

# A storm further away than this is listed but not tracked in detail.
STORM_NEARBY_RADIUS_KM = 2500

# How many individual storm sensors to create. The northwest Pacific rarely has
# more than three named systems at once; a fixed set of slots keeps the entity
# ids stable as storms come and go, and the count sensor always lists them all.
STORM_SLOTS = 3

# Track points kept in entity attributes. History can run to ~56 points per
# storm and attributes are written to the state machine on every update.
STORM_TRACK_POINTS = 12

# A forecast track point this close to the coast counts as reaching land.
LANDFALL_THRESHOLD_KM = 80

# Saying a storm has ALREADY come ashore is a stronger claim than saying one is
# heading for the coast, so an observed track point has to be closer than a
# forecast one before it counts. At 80 km a storm merely passing along the coast
# would read as having hit it.
LANDFALL_OBSERVED_KM = 45

# How far back an observed landfall still counts as news. Dolphin had crossed
# Japan five days before it reached inland China; reporting the Japanese
# crossing said nothing about where the storm actually was.
LANDFALL_RECENT_HOURS = 72

# Beyond this there is no land in the tracked basin, so no landfall is guessed.
# Naming a coast 3000 km away told people nothing except that the answer was
# forced: a storm off Tokyo was reported against the coast of Quảng Ninh.
COAST_LOOKUP_MAX_KM = 2000

# Vietnamese coastal reference points, named by province because that is the
# useful answer here. Everywhere else in the basin comes from coastline.py,
# named by country. Ordered north to south.
VIETNAM_COAST: tuple[tuple[str, float, float], ...] = (
    ("Quảng Ninh", 21.05, 107.35),
    ("Hải Phòng", 20.75, 106.75),
    ("Thái Bình", 20.45, 106.55),
    ("Nam Định", 20.15, 106.35),
    ("Ninh Bình", 20.05, 106.10),
    ("Thanh Hóa", 19.70, 105.95),
    ("Nghệ An", 18.80, 105.80),
    ("Hà Tĩnh", 18.30, 106.05),
    ("Quảng Bình", 17.50, 106.65),
    ("Quảng Trị", 16.85, 107.15),
    ("Huế", 16.50, 107.65),
    ("Đà Nẵng", 16.05, 108.25),
    ("Quảng Nam", 15.60, 108.55),
    ("Quảng Ngãi", 15.10, 108.90),
    ("Bình Định", 14.00, 109.25),
    ("Phú Yên", 13.15, 109.30),
    ("Khánh Hòa", 12.25, 109.20),
    ("Ninh Thuận", 11.60, 109.00),
    ("Bình Thuận", 10.90, 108.10),
    ("Bà Rịa - Vũng Tàu", 10.35, 107.10),
    ("TP. Hồ Chí Minh", 10.40, 106.90),
    ("Tiền Giang", 10.30, 106.70),
    ("Bến Tre", 9.90, 106.60),
    ("Trà Vinh", 9.70, 106.50),
    ("Sóc Trăng", 9.40, 106.10),
    ("Bạc Liêu", 9.10, 105.70),
    ("Cà Mau", 8.70, 105.10),
    ("Kiên Giang", 10.00, 104.80),
)

# Forecast models in the order they are trusted for a landfall estimate: JMA is
# the WMO-designated centre for this basin, then ECMWF, then the rest.
LANDFALL_MODEL_PRIORITY: tuple[str, ...] = (
    "jma", "ecmwf", "ukm", "noaa-at", "imd", "detected(ecmwf-hres)", "detected(gfs)",
)


# Vietnamese compass points -> (English cardinal, degrees).
# B=Bắc(N), N=Nam(S), Đ=Đông(E), T=Tây(W) — "N" means SOUTH in Vietnamese, so
# it must never be handed to Home Assistant unconverted.
WIND_DIRECTION_VI: dict[str, tuple[str, float]] = {
    "B": ("N", 0.0),
    "BĐB": ("NNE", 22.5),
    "ĐB": ("NE", 45.0),
    "ĐĐB": ("ENE", 67.5),
    "Đ": ("E", 90.0),
    "ĐĐN": ("ESE", 112.5),
    "ĐN": ("SE", 135.0),
    "NĐN": ("SSE", 157.5),
    "N": ("S", 180.0),
    "NTN": ("SSW", 202.5),
    "TN": ("SW", 225.0),
    "TTN": ("WSW", 247.5),
    "T": ("W", 270.0),
    "TTB": ("WNW", 292.5),
    "TB": ("NW", 315.0),
    "BTB": ("NNW", 337.5),
}

# English cardinals -> full Vietnamese names, for describing which way a storm
# is heading in plain words.
CARDINAL_VI: dict[str, str] = {
    "N": "Bắc",
    "NNE": "Bắc Đông Bắc",
    "NE": "Đông Bắc",
    "ENE": "Đông Đông Bắc",
    "E": "Đông",
    "ESE": "Đông Đông Nam",
    "SE": "Đông Nam",
    "SSE": "Nam Đông Nam",
    "S": "Nam",
    "SSW": "Nam Tây Nam",
    "SW": "Tây Nam",
    "WSW": "Tây Tây Nam",
    "W": "Tây",
    "WNW": "Tây Tây Bắc",
    "NW": "Tây Bắc",
    "NNW": "Bắc Tây Bắc",
}

# English cardinals -> degrees, in case a page is served in English.
WIND_DIRECTION_EN: dict[str, float] = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5,
    "E": 90.0, "ESE": 112.5, "SE": 135.0, "SSE": 157.5,
    "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5,
}

# Weather conditions mapping to Home Assistant
CONDITION_MAP = {
    "sunny": "sunny",
    "clear": "sunny", 
    "mostly sunny": "sunny",
    "partly sunny": "partlycloudy",
    "intermittent clouds": "partlycloudy",
    "hazy sunshine": "partlycloudy",
    "mostly cloudy": "cloudy",
    "cloudy": "cloudy",
    "overcast": "cloudy",
    "fog": "fog",
    "showers": "rainy",
    "mostly cloudy w/ showers": "rainy", 
    "partly sunny w/ showers": "rainy",
    "t-storms": "lightning-rainy",
    # The English pages spell it out in full as well as abbreviated.
    "thunderstorm": "lightning-rainy",
    "mostly cloudy w/ t-storms": "lightning-rainy",
    "partly sunny w/ t-storms": "lightning-rainy",
    "rain": "rainy",
    "flurries": "snowy",
    "mostly cloudy w/ flurries": "snowy",
    "partly sunny w/ flurries": "snowy",
    "snow": "snowy",
    "mostly cloudy w/ snow": "snowy",
    "ice": "snowy",
    "sleet": "snowy",
    "freezing rain": "snowy",
    "rain and snow": "snowy-rainy",
    "hot": "sunny",
    "cold": "sunny",
    "windy": "windy",
    "clear night": "clear-night",
    "mostly clear": "clear-night",
    "partly cloudy": "partlycloudy",
    "intermittent clouds night": "partlycloudy",
    "hazy moonlight": "partlycloudy",
    "mostly cloudy night": "cloudy",
    "partly cloudy w/ showers": "rainy",
    "mostly cloudy w/ showers night": "rainy",
    "partly cloudy w/ t-storms": "lightning-rainy",
    "mostly cloudy w/ t-storms night": "lightning-rainy",
    "partly cloudy w/ flurries": "snowy",
    "mostly cloudy w/ flurries night": "snowy",
    "rain and snow mixed": "snowy-rainy"
}

# Vietnamese condition mapping (updated based on real data)
CONDITION_MAP_VI = {
    "nắng": "sunny",
    "quang đãng": "sunny",
    "nắng nhiều": "sunny",
    "nhiều nắng": "sunny",
    "nắng nhẹ": "sunny", 
    "ít mây": "partlycloudy",
    "có mây": "partlycloudy",
    "mây từng đợt": "partlycloudy",
    "mây rải rác": "partlycloudy",
    "mây và nắng": "partlycloudy",
    "nắng sau đó có ít mây": "partlycloudy",
    "mây ngày càng nhiều": "cloudy",
    "nhiều mây": "cloudy",
    "u ám": "cloudy",
    "âm u": "cloudy",
    "sương mù": "fog",
    "mưa rào": "rainy",
    "mưa": "rainy",
    "mưa nhẹ": "rainy",
    "mưa vừa": "rainy", 
    "mưa to": "pouring",
    "đôi lúc có mưa": "rainy",
    "khả năng có mưa": "rainy",
    "một vài cơn mưa rào": "rainy",
    "một chút mưa": "rainy",
    "cơn mưa rào hoặc mưa dông": "lightning-rainy",
    "dông": "lightning",
    "sấm sét": "lightning-rainy",
    "mưa dông": "lightning-rainy",
    "một vài cơn mưa rão và mưa dông": "lightning-rainy",
    "mưa dông ở một số phần trong khu vực": "lightning-rainy",
    "một vài cơn mưa dông": "lightning-rainy",
    "có thể có mưa rào hoặc mưa dông": "lightning-rainy",
    "tuyết": "snowy",
    "mưa tuyết": "snowy-rainy",
    "gió": "windy",
    "đêm quang đãng": "clear-night",
    "trời quang": "sunny",
    "quang mây": "sunny",
    "trăng mờ": "partlycloudy",
    "mát hơn": "cloudy",
    "ấm hơn": "sunny",
    "lạnh hơn": "cloudy",
}
