import time
import logging
from datetime import datetime, timedelta

import requests
from astral import LocationInfo
from astral.sun import sun
from blinkt import set_pixel, clear, show

from config import API_KEY, SITE_ID

LOG = logging.getLogger('solar-lights')
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO
)

RENDER_MODE = 'blinkt'


IMPORT_COLOUR = [255, 0, 0]  # Bright RED  (worst is import!)
EXPORT_COLOUR = [0, 0, 255]  # Bright BLUE
NEUTRAL_COLOUR = [0, 255, 0]  # Bright GREEN  (best is self-consumption)

# Get the following from the API?
CAPACITY = 2.97  # kWp - capacity of the PV system installed
MAX_IDEAL_POWER = 2.  # kW - daily usage at SITE_ID

SOLAREDGE_SITE_API = f"https://monitoringapi.solaredge.com/site/{SITE_ID}/"
API_QUERY_LIMIT = 250  # 300


def get_live_power_with_status():
    """Get live power values from SolarEdge API.

    Response might look like:

    {
        'siteCurrentPowerFlow': {
            'updateRefreshRate': 3,
            'unit': 'kW',
            'connections': [
                # IMPORTING
                {'from': 'PV', 'to': 'Load'},
                {'from': 'GRID', 'to': 'Load'}
                # EXPORTING (?)
                {'from': 'PV', 'to': 'Load'},
                {'from': 'Load', 'to': 'GRID'}
            ],
            'GRID': {'status': 'Active', 'currentPower': 2.22},
            'LOAD': {'status': 'Active', 'currentPower': 3.23},
            'PV': {'status': 'Active', 'currentPower': 1.01}
        }
    }
    """
    url = f"{SOLAREDGE_SITE_API}currentPowerFlow.json?api_key={API_KEY}"
    response = requests.get(url)
    result = {
        'production': None,
        'consumption': None,
        'import': None,
        'export': None,
    }
    if response.status_code == 200:
        packet = response.json()['siteCurrentPowerFlow']
        production = packet['PV']['currentPower']
        consumption = packet['LOAD']['currentPower']
        grid = packet['GRID']['currentPower']

        result['production'] = production
        result['consumption'] = consumption

        direction = 'neutral'
        if production > consumption:
            direction = 'export'
        elif production < consumption:
            direction = 'import'
        result['direction'] = direction
        result['grid'] = grid
        result[direction] = grid
        return result


def get_day_hourly_summary():
    """Get the summary of the day (up to now) per-hour."""
    url = f"{SOLAREDGE_SITE_API}energyDetails.json"
    params = {
        'api_key': API_KEY,
        'startTime': datetime.now().strftime('%Y-%m-%d%%2000:00:00'),
        'endTime': (
            datetime.now() + timedelta(hours=1)
        ).strftime('%Y-%m-%d%%20%H:00:00'),
        'timeUnit': 'HOUR',
    }
    response = requests.get(url, params=params)
    import ipdb; ipdb.set_trace()
    print(response)


def render_with_html(pixels: dict):
    """Use HTML to render the lights."""
    pixel_markup = ""
    prop = int(100. / len(pixels)) - 2
    for ix in range(len(pixels)):
        pixel_markup += (
            '<div style="background-color: rgb(' +
            ', '.join([str(col) for col in pixels[ix]]) +
            '); display: inline-block; ' +
            f'width: {prop}%; height: {prop}%; ' +
            'border: solid #333 1px;"></div>'
        )

    with open('lights.html', 'w') as fp:
        fp.write("""
        <html><head></head>
        <body style="background-color: black;">
        <script>
        window.setTimeout(function(){window.location=location.href}, 10000);
        </script>
        """ + pixel_markup + "</body></html>")


def render_with_blinkt(pixels: dict):
    """Use the blink API to render the lights."""
    clear()
    for ix in range(len(pixels)):
        set_pixel(ix, *pixels[ix])
    show()
    render_with_html(pixels)


def get_indicator_pixel(power: dict):
    """Return pixel colour for "trinary" directional indicator."""
    return {
        'import': IMPORT_COLOUR,
        'export': EXPORT_COLOUR,
        'neutral': NEUTRAL_COLOUR,
    }[power['direction']]


def get_tilt_pixel(power: dict):
    """Return pixel colour for the "tilt" toward export/import/balance."""
    grid = power['grid']
    cons = power['consumption']
    prod = power['production']

    all_imp = IMPORT_COLOUR
    all_exp = EXPORT_COLOUR
    all_cons = NEUTRAL_COLOUR
    pct = grid / cons

    c1 = all_cons
    c2 = all_exp if prod > cons else all_imp

    # a simple blend either toward import or export from perfect pv consumption
    colour = [
        round((1 - pct) * c1[0] + pct * c2[0]),
        round((1 - pct) * c1[1] + pct * c2[1]),
        round((1 - pct) * c1[2] + pct * c2[2])
    ]
    return colour


def get_production_percent_pixels(power: dict, multi=False) -> list:
    """Return colour for how 'well' the system is doing relative to capacity."""
    prod = power['production']
    pct = prod / CAPACITY  # 0
    result = []
    if multi:
        pixel_n = 3.  # how many pixels to spread over
        pix_pct = 1 / pixel_n

        for _ in range(int(pixel_n)):
            if pct >= pix_pct:
                result.append([255, 255, 255])
                pct -= pix_pct
            elif pct > 0 and pct < pix_pct:
                result.append([int(255. * (pct / pix_pct))] * 3)
                pct -= pct
            else:
                result.append([0, 0, 0])
    else:
        result.append([round(255. * pct)] * 3)
    return result


def get_city():
    """Return the PV place."""
    return LocationInfo(
        "St. Helier", "Jersey", "Europe/London", 49.1811528, -2.1226525
    )


def get_sun_params():
    """Get sun params for location."""
    city = get_city()
    sun_params = sun(city.observer, datetime.now())
    return sun_params


def get_daylight_seconds():
    """Return number of seconds of daylight."""
    sun_params = get_sun_params()
    return (sun_params['sunset'] - sun_params['sunrise']).total_seconds()


def get_consumption_percent_pixel(power: dict) -> list:
    """Return colour for how 'bad' consumption is relative to... avg?..."""
    cons = power['consumption']
    pct = cons / MAX_IDEAL_POWER
    return [round(255. * pct), 0, 0]


def is_daylight():
    """Return true if it is daylight."""
    sun_params = get_sun_params()
    now = get_city().tzinfo.localize(datetime.now())
    return sun_params['sunset'] > now > sun_params['sunrise']


if __name__ == '__main__':
    if RENDER_MODE == 'blinkt':
        render_mode = render_with_blinkt
    else:
        render_mode = render_with_html

    while True:
        try:
            power = get_live_power_with_status()
            LOG.info(power)
            pixels = {}

            for pixel in get_production_percent_pixels(power, multi=True):
                pixels[len(pixels)] = pixel
            pixels[len(pixels)] = get_indicator_pixel(power)
            pixels[len(pixels)] = get_tilt_pixel(power)
            pixels[len(pixels)] = get_consumption_percent_pixel(power)

            render_mode(pixels)

            light_secs = get_daylight_seconds()
            dark_secs = 60 * 60 * 24 - light_secs
            day_portion = int(API_QUERY_LIMIT * 0.95)
            night_portion = API_QUERY_LIMIT - day_portion - 1  # -1 for safety!
            refresh_day = int(light_secs / day_portion)
            refresh_night = int(dark_secs / night_portion)

            if is_daylight():
                refresh = refresh_day
            else:
                refresh = refresh_night
            LOG.info(f'Refresh in {refresh} seconds...')
            time.sleep(refresh)
        except requests.exceptions.ConnectionError:
            LOG.exception('Retrying in 5s after connection exception...')
            time.sleep(5)