import time
from functools import partial

import requests

from config import API_KEY, SITE_ID

RENDER_MODE = 'html'

# Get the following from the API?
CAPACITY = 2.97  # kWp - capacity of the PV system installed
MAX_IDEAL_POWER = 2.  # kW - daily usage at SITE_ID

SOLAREDGE_SITE_API = f"https://monitoringapi.solaredge.com/site/{SITE_ID}/"


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
    raise NotImplementedError("Use html.")


def get_indicator_pixel(power: dict):
    """Return pixel colour for "trinary" directional indicator."""
    return {
        'import': [255, 0, 0],
        'export': [0, 255, 0],
        'neutral': [0, 0, 255]
    }[power['direction']]


def get_tilt_pixel(power: dict):
    """Return pixel colour for the "tilt" toward export/import/balance."""
    grid = power['grid']
    cons = power['consumption']
    prod = power['production']

    all_imp = [255, 0, 0]
    all_exp = [0, 255, 0]
    all_cons = [0, 0, 255]
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


def get_consumption_percent_pixel(power: dict) -> list:
    """Return colour for how 'bad' consumption is relative to... avg?..."""
    cons = power['consumption']
    pct = cons / MAX_IDEAL_POWER
    return [round(255. * pct), 0, 0]


if __name__ == '__main__':
    if RENDER_MODE == 'blinkt':
        render_mode = render_with_blinkt
    else:
        render_mode = render_with_html

    while True:
        power = get_live_power_with_status()
        pixels = {}

        for pixel in get_production_percent_pixels(power, multi=True):
            pixels[len(pixels)] = pixel
        pixels[len(pixels)] = get_indicator_pixel(power)
        pixels[len(pixels)] = get_tilt_pixel(power)
        pixels[len(pixels)] = get_consumption_percent_pixel(power)

        render_mode(pixels)
        print(pixels)
        print(power)
        time.sleep(300)