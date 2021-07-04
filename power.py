import logging
import time
import random
from datetime import datetime, timedelta
from functools import partial

import requests
from astral import LocationInfo
from astral.sun import sun

from config import API_KEY, SITE_ID

LOG = logging.getLogger('solar-lights')
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO
)


IMPORT_COLOUR = [255, 0, 0]  # Bright RED  (worst is import!)
EXPORT_COLOUR = [0, 0, 255]  # Bright BLUE
NEUTRAL_COLOUR = [0, 255, 0]  # Bright GREEN  (best is self-consumption)

# Get the following from the API?
CAPACITY = 2.97  # kWp - capacity of the PV system installed
MAX_IDEAL_POWER = 3.  # kW - daily usage at SITE_ID

SOLAREDGE_SITE_API = f"https://monitoringapi.solaredge.com/site/{SITE_ID}/"
API_QUERY_LIMIT = 300

REFRESH_RATE_SECS = 0.1


class DataMethodNotAvailable(Exception):
    """Raised when data access failed."""


class RenderMethodFailed(Exception):
    """Raised when render fails for some reason."""


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



class SolarLights:
    """Manage the lights output depending on production/consumption."""

    PIXELS_AVAILABLE = 8
    DARK_PIXEL = [0, 0, 0]
    DEFAULT_BRIGHTNESS = 0.2

    def __init__(self, with_blinkt=True, with_pygame=False):
        """Set up."""
        self._pixels = {}
        self._brightness = self.DEFAULT_BRIGHTNESS
        self._city = None
        self._sun_params = None
        self._next_update = None
        self._with_blink = with_blinkt
        self._with_pygame = with_pygame
        self._render_count = 0

        self._pygame_display = None

    @property
    def pixels(self):
        """Return pixel array."""
        return [
            self._pixels[ix]
            if ix in self._pixels
            else self.DARK_PIXEL
            for ix in range(8)
        ]

    def set_pixels(self, pixels, first_index, clear=False):
        """Add pixels to the pixel array starting at first_index."""
        if clear:
            self._pixels = {}

        pixels.reverse()
        if len(pixels) + len(self._pixels) <= self.PIXELS_AVAILABLE:
            for ix in range(first_index, len(pixels)):
                self._pixels[ix] = pixels.pop()

    def get_pixels(self):
        """Return a load of pixels to render."""
        pixels = []
        for method in [
            partial(self.get_production_percent_pixels, multi=3),
            self.get_indicator_pixels,
            self.get_tilt_pixels,
            partial(self.get_consumption_percent_pixels, multi=3),
        ]:
            pixels.extend(method())
        return pixels

    @property
    def brightness(self):
        """Get brightness."""
        return self._brightness

    @property
    def city(self):
        """Return the PV place."""
        if self._city is None:
            self._city = LocationInfo(
                "St. Helier", "Jersey", "Europe/London", 49.1811528, -2.1226525
            )
        return self._city

    @property
    def sun_params(self):
        """Return sun params for this place."""
        if self._sun_params is None:
            self._sun_params = sun(self.city.observer, datetime.now())
        return self._sun_params

    def get_daylight_seconds(self):
        """Return number of seconds of daylight."""
        return (
            self.sun_params['sunset'] - self.sun_params['sunrise']
        ).total_seconds()

    def is_daylight(self):
        """Return true if it is daylight."""
        now = self.city.tzinfo.localize(datetime.now())
        return self.sun_params['sunset'] > now > self.sun_params['sunrise']

    def update_power_with_status(self, power_dict):
        """Add status to the power_dict."""
        direction = 'neutral'
        if power_dict['production'] > power_dict['consumption']:
            direction = 'export'
        elif power_dict['production'] < power_dict['consumption']:
            direction = 'import'
        power_dict['direction'] = direction

    def get_modbus_power_with_status(self):
        """Get data from inverter...?."""
        raise DataMethodNotAvailable("How can we modbus?")

    def get_solaredge_power_with_status(self):
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
        try:
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

                self.update_power_with_status(result)

                result['grid'] = grid
                result[result['direction']] = grid

                return result
            else:
                raise DataMethodNotAvailable(
                    f"SolarEdge API returned {response.status_code} status."
                )
        except requests.exceptions.ConnectionError:
            raise DataMethodNotAvailable("SolarEdge API not reachable.")

    def get_static_power_from_csv(self):
        """Get power from CSV file."""
        with open('data.csv', 'r') as fp:
            lines = fp.readlines()
            keys = lines[0].strip().split(',')
            vals = [float(val.strip()) for val in lines[1].split(',')]
            data = dict(zip(keys, vals))
            return self.get_mock_power_with_status(**data)

    def get_mock_power_with_status(self, prod=None, cons=None):
        """Just make something up."""
        prod = prod or random.randint(0, int(10 * CAPACITY)) / 10.
        cons = cons or (random.randint(0, 10 * 5) / 10.) + 0.1
        result = {
            'production': prod,
            'consumption': cons,
            'import': None if prod > cons else cons - prod,
            'export': None if prod < cons else prod - cons,
        }
        grid = result['import'] or result['export']

        self.update_power_with_status(result)

        result['grid'] = grid
        result[result['direction']] = grid
        return result

    def get_live_power_with_status(self):
        """Get power/status dict."""
        result = None
        methods = [
            self.get_modbus_power_with_status,
            self.get_solaredge_power_with_status,
            self.get_static_power_from_csv,
            self.get_mock_power_with_status,
        ]
        methods.reverse()
        while result is None and len(methods):
            method = methods.pop()
            try:
                result = method()
            except DataMethodNotAvailable:
                continue
        LOG.debug("Data updated!")
        return result

    def set_next_update(self):
        """Figure out when we can next update, set it."""
        if self._next_update and self._next_update > datetime.utcnow():
            return

        if self._next_update is None:
            self._next_update = datetime.utcnow().replace(microsecond=0)
            return

        light_secs = self.get_daylight_seconds()
        dark_secs = 60 * 60 * 24 - light_secs
        day_portion = int(API_QUERY_LIMIT * 0.95)
        night_portion = API_QUERY_LIMIT - day_portion - 1  # -1 for safety!
        refresh_day = int(light_secs / day_portion)
        refresh_night = int(dark_secs / night_portion)

        if self.is_daylight():
            refresh = refresh_day
        else:
            refresh = refresh_night
        self._next_update = (
            datetime.utcnow() + timedelta(seconds=refresh)
        ).replace(microsecond=0)
        LOG.info(f'Refresh in {refresh} seconds at {self._next_update}...')

    def update_data(self):
        """If the time is right, update the data."""
        if self._next_update is None:
            return

        if self._next_update <= datetime.utcnow():
            LOG.debug("Updating data...")
            self._data = self.get_live_power_with_status()
            LOG.debug(f"Data: {self._data}")

    def render_with_html(self):
        """Use HTML to render the lights."""
        pixel_markup = ""
        prop = int(100. / len(self.pixels)) - 2
        for ix in range(len(self.pixels)):
            pixel_markup += (
                '<div style="background-color: rgb(' +
                ', '.join([str(col) for col in self.pixels[ix]]) +
                '); display: inline-block; ' +
                f'width: {prop}%; height: {prop}%; ' +
                'border: solid #333 1px;"></div>'
            )

        with open('lights.html', 'w') as fp:
            fp.write("""
            <html><head></head>
            <body style="background-color: black; color: white;">
            <script>
            window.setTimeout(function(){window.location=location.href}, """ +
            str(REFRESH_RATE_SECS * 5000) + """);
            </script>
            """ + pixel_markup +
            f"<p>Date: {datetime.utcnow().isoformat()}</p>" +
            f"<p>Data: {self._data}</p>" +
            f"<p>Pixels: {self.pixels}</p>"
            "</body></html>")

    def render_with_blinkt(self):
        """Use the blink API to render the lights."""
        if not self._with_blink:
            return

        try:
            from blinkt import clear, set_pixel, show, set_brightness
            set_brightness(0.5)
            clear()
            for ix in range(len(self.pixels)):
                set_pixel(ix, *self.pixels[ix])
            show()
        except ImportError:
            raise RenderMethodFailed("No blinkt!")

    def render_with_pygame(self):
        """Use pygame to simulate hardware."""
        if not self._with_pygame:
            return

        try:
            import pygame
            if self._pygame_display is None:
                pygame.init()
                self._pygame_display = pygame.display.set_mode(
                    (500, 400), 0, 32
                )
            for ix, pixel in enumerate(self.pixels):
                pygame.draw.rect(
                    self._pygame_display,
                    pixel,
                    (ix * 50, 0, 50, 50)
                )
            pygame.display.update()
        except Exception as ex:
            raise RenderMethodFailed(f"Pygame render failed... {ex}")

    @property
    def flash_percent(self):
        """Return percent of flash depending on render count."""
        max_ = 15.
        return (self._render_count % max_) / max_

    @property
    def pulse_percent(self):
        """Return percent of pulse depending on render count."""
        max_ = 127.
        return (self._render_count % max_) / max_

    def render(self):
        """Render somehow (HTML, Blinkt, etc.)."""
        for method in [
            self.render_with_html,
            self.render_with_blinkt,
            self.render_with_pygame,
        ]:
            try:
                method()
            except RenderMethodFailed:
                LOG.error(f"Method {method.__name__} failed.")
        self._render_count += 1
        LOG.debug("Rendered!")

    def get_indicator_pixels(self):
        """Return pixel colour for "trinary" directional indicator."""
        pct = self.flash_percent
        return [
            [
                int(val * pct) for val in {
                    'import': IMPORT_COLOUR,
                    'export': EXPORT_COLOUR,
                    'neutral': NEUTRAL_COLOUR,
                }[self._data['direction']]
            ]
        ]

    def get_tilt_pixels(self):
        """Return pixel colour for the "tilt" toward export/import/balance."""
        grid = self._data['grid']
        cons = self._data['consumption']
        prod = self._data['production']

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
        return [colour]

    def spread_pixels(self, n_pixels: int, full_pixel: list, pct: float):
        """Spread the full_pixel over n_pixels."""
        result = []
        pix_pct = 1 / n_pixels

        for _ in range(int(n_pixels)):
            if pct >= pix_pct:
                result.append(full_pixel)
                pct -= pix_pct
            elif pct > 0 and pct < pix_pct:
                result.append([
                    int(float(full_pixel[ix]) * (pct / pix_pct))
                    for ix in range(3)
                ])
                pct -= pct
            else:
                result.append([0, 0, 0])
        return result

    def get_production_percent_pixels(self, multi: float=0) -> list:
        """Return colour for how 'well' the system is doing relative to capacity."""
        prod = self._data['production']
        pct = prod / CAPACITY  # 0
        result = []

        pct = pct * self.pulse_percent
        if multi:
            result = self.spread_pixels(multi, [128, 128, 128], pct)
        else:
            result.append([round(255. * pct)] * 3)
        return result

    def get_consumption_percent_pixels(self, multi: float=0) -> list:
        """Return colour for how 'bad' consumption is relative to... avg?..."""
        cons = self._data['consumption']
        pct = cons / MAX_IDEAL_POWER
        result = []
        pct = pct * self.pulse_percent
        if multi:
            result = self.spread_pixels(multi, [128, 0, 0], pct)
        else:
            result.append([round(255. * pct), 0, 0])
        return reversed(result)

    def run(self):
        """Start the process."""
        try:
            self.set_next_update()
            while True:
                self.update_data()
                self.set_next_update()
                self.set_pixels(self.get_pixels(), 0, clear=True)
                self.render()
                time.sleep(REFRESH_RATE_SECS)
        except KeyboardInterrupt:
            LOG.info("Keyboard interrupt, aborting.")


if __name__ == '__main__':
    controller = SolarLights()
    controller.run()
