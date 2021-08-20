import argparse
import logging
import time
import random
import signal
import sys
from datetime import datetime, timedelta
from functools import partial

import requests
from astral import LocationInfo
from astral.sun import sun

from config import (
    API_KEY, SITE_ID,
    IMPORT_COLOUR, EXPORT_COLOUR, NEUTRAL_COLOUR, PRODUCTION_COLOUR,
    REFRESH_RATE_SECS,
    CAPACITY, MAX_IDEAL_POWER, MAX_IDEAL_CONSUMPTION,
    DIM_DOWN_TIME_NIGHT, BRIGHTEN_UP_TIME_MORNING,
    OFF_TIMES, OFF_TIME_NIGHT, ON_TIME_MORNING
)

LOG = logging.getLogger('solar-lights')
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO
)

SOLAREDGE_SITE_API = f"https://monitoringapi.solaredge.com/site/{SITE_ID}/"
API_QUERY_LIMIT = 300


class DataMethodNotAvailable(Exception):
    """Raised when data access failed."""


class RenderMethodFailed(Exception):
    """Raised when render fails for some reason."""


class SolarLights:
    """Manage the lights output depending on production/consumption."""

    PIXELS_AVAILABLE = 8
    DARK_PIXEL = [0, 0, 0]

    def __init__(self, with_blinkt=True, with_pygame=False):
        """Set up."""
        self._data = None
        self._summary = None
        self._pixels = {}
        self._city = None
        self._sun_params = None
        self._next_update = None
        self._with_blink = with_blinkt
        self._with_pygame = with_pygame
        self._render_count = 0
        self._running = True

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
        methods = []
        if self.is_daylight:
            methods = [
                partial(self.get_production_percent_pixels, multi=3),
                self.get_indicator_pixels,
                self.get_tilt_pixels,
                partial(self.get_consumption_percent_pixels, multi=3),
            ]
        else:
            methods = [
                partial(self.get_day_summary_pixels, multi=7),
                self.get_consumption_percent_pixels,
            ]
        for method in methods:
            pixels.extend(method())
        return pixels

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
        get_new_params = (
            self._sun_params is None or
            self._sun_params['sunset'].day < datetime.now().day
        )
        if get_new_params:
            self._sun_params = sun(self.city.observer, datetime.now())
        return self._sun_params

    def get_daylight_seconds(self):
        """Return number of seconds of daylight."""
        return (
            self.sun_params['sunset'] - self.sun_params['sunrise']
        ).total_seconds()

    def get_on_seconds(self):
        """Return number of seconds we are actually displaying for."""
        off_parts = [int(part) for part in OFF_TIME_NIGHT.split(':')]
        on_parts = [int(part) for part in ON_TIME_MORNING.split(':')]

        return (
            ((off_parts[0] - on_parts[0]) % 24 * 60 * 60) +  # hours
            ((off_parts[1] - on_parts[1]) % 60 * 60) +  # mins
            ((off_parts[2] - on_parts[2]) % 60)  # secs
        )

    @property
    def should_off(self):
        """Return trun within, if we have an off period set."""
        now_time = datetime.now().time().strftime("%H:%M:%S")
        off_down_night = OFF_TIMES and OFF_TIME_NIGHT <= now_time
        off_down_morn = OFF_TIMES and now_time <= ON_TIME_MORNING
        return off_down_night or off_down_morn

    @property
    def should_dim(self):
        """Return if it is in the dim-down time range."""
        now_time = datetime.now().time().strftime("%H:%M:%S")
        dim_down_night = DIM_DOWN_TIME_NIGHT <= now_time
        dim_down_morn = now_time <= BRIGHTEN_UP_TIME_MORNING
        return dim_down_night or dim_down_morn

    @property
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

    def get_solaredge_day_summary(self):
        """Get the summary of the day (up to now) from SolarEdge API."""
        try:
            url = f"{SOLAREDGE_SITE_API}energyDetails.json"
            params = {
                'api_key': API_KEY,
                'startTime': datetime.now().strftime('%Y-%m-%d 00:00:00'),
                'endTime': (
                    datetime.now() + timedelta(hours=1)
                ).strftime('%Y-%m-%d %H:00:00'),
                'timeUnit': 'HOUR',
            }
            response = requests.get(url, params=params)
            result = {}
            if response.status_code == 200:
                data = response.json()
                meters = {
                    meter['type']: meter['values']
                    for meter in data['energyDetails']['meters']
                }
                for meter, values in meters.items():
                    result[meter] = sum([
                        hour.get('value', 0)
                        for hour in values
                    ])
                return result
            else:
                raise DataMethodNotAvailable(
                    f"SolarEdge API returned {response.status_code} status."
                )
        except requests.exceptions.ConnectionError:
            raise DataMethodNotAvailable("SolarEdge API not reachable.")
        except KeyError:
            raise DataMethodNotAvailable("Unexpected response data.")

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
        try:
            with open('data.csv', 'r') as fp:
                lines = fp.readlines()
                keys = lines[0].strip().split(',')
                vals = [float(val.strip()) for val in lines[1].split(',')]
                data = dict(zip(keys, vals))
                return self.get_mock_power_with_status(**data)
        except (FileNotFoundError, KeyError, IndexError):
            raise DataMethodNotAvailable("Data file is not present or correct.")

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
        on_time_secs = self.get_on_seconds()
        dark_secs = on_time_secs - light_secs
        day_portion = int(API_QUERY_LIMIT * 0.95)
        # Night portion is -2: one for Summary request, and one for safety...
        night_portion = API_QUERY_LIMIT - day_portion - 2
        refresh_day = int(light_secs / day_portion)
        refresh_night = int(dark_secs / night_portion)

        if self.is_daylight:
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

            if self.is_daylight:
                self._summary = None
            elif self._summary is None:
                LOG.info("Getting summary data...")
                # Only do this once so API request limit not reached...
                self._summary = self.get_solaredge_day_summary()
                LOG.info(f"Data: {self._summary}")

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
            str(REFRESH_RATE_SECS * 15000) + """);
            </script>
            """ + pixel_markup +
            f"<p>Date: {datetime.utcnow().isoformat()}</p>" +
            f"<p>Data: {self._data}</p>" +
            f"<p>Summary: {self._summary}</p>" +
            f"<p>Pixels: {self.pixels}</p>"
            "</body></html>")

    def render_with_blinkt(self):
        """Use the blink API to render the lights."""
        if not self._with_blink:
            return

        try:
            from blinkt import clear, set_pixel, show, set_brightness
            clear()
            set_brightness(0.5 if self.is_daylight else 0.05)

            dim = 0.01 if self.should_dim else 1
            off = 0 if self.should_off else 1
            for ix in range(len(self.pixels)):
                set_pixel(
                    ix,
                    *[int(val * dim * off) for val in self.pixels[ix]]
                )
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
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    self.cleanup()
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
        pct = self.flash_percent if self.is_daylight else 1
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

        c1 = all_cons

        pct = grid / cons
        c2 = all_imp
        if prod > cons:
            pct = grid / prod
            c2 = all_exp

        pixel = self.blend_pixel(c1, c2, pct)
        return [pixel]

    def blend_pixel(self, c1, c2, pct):
        """Simple blend from c1 to c2 by pct."""
        colour = [
            round((1 - pct) * c1[0] + pct * c2[0]),
            round((1 - pct) * c1[1] + pct * c2[1]),
            round((1 - pct) * c1[2] + pct * c2[2])
        ]
        return colour

    def spread_pixels(self, n_pixels: int, full_pixel: list, pct: float):
        """Spread the full_pixel over n_pixels."""
        result = []
        pix_pct = max([0.001, 1. / float(n_pixels)])

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
        pct = prod / CAPACITY
        result = []

        pct = pct * self.pulse_percent
        if multi:
            result = self.spread_pixels(multi, PRODUCTION_COLOUR, pct)
        else:
            result.append([val * pct for val in PRODUCTION_COLOUR])
        return result

    def get_consumption_percent_pixels(self, multi: float=0) -> list:
        """Return colour for how 'bad' consumption is relative to... avg?..."""
        cons = self._data['consumption']
        pct = min([cons / MAX_IDEAL_POWER, 1.])
        result = []
        pct = pct * self.pulse_percent
        if multi:
            result = self.spread_pixels(multi, [128, 0, 0], pct)
        else:
            result.append([round(255. * pct), 0, 0])
        return reversed(result)

    def get_day_summary_pixels(self, multi=3):
        """Summarise the day - more export or more self consumption?."""
        if self._summary is None:
            return [self.DARK_PIXEL] * multi

        total_prod = self._summary['FeedIn'] + self._summary['SelfConsumption']
        try:
            pct_self = self._summary['SelfConsumption'] / total_prod
            pct_export = self._summary['FeedIn'] / total_prod
        except ZeroDivisionError:
            # No production at all... return red?
            day_cons = self._summary['Consumption']
            day_goodness = min([
                day_cons / 1000. / float(MAX_IDEAL_CONSUMPTION),
                1.
            ]) * self.pulse_percent
            return self.spread_pixels(multi, IMPORT_COLOUR, day_goodness)

        result = []
        pct_per_pix = 1.0 / float(multi)
        calcd = 0
        while (calcd + pct_per_pix) <= pct_self:
            result.append(NEUTRAL_COLOUR)
            calcd += pct_per_pix

        result.append(
            self.blend_pixel(EXPORT_COLOUR, NEUTRAL_COLOUR, pct_self)
        )
        calcd += pct_per_pix

        while (calcd + pct_per_pix) <= 1:
            result.append(EXPORT_COLOUR)
            calcd += pct_per_pix

        return result

    def run(self):
        """Start the process."""
        self.set_next_update()
        while self._running:
            self.update_data()
            self.set_next_update()
            pixels = self.get_pixels()
            self.set_pixels(pixels, 0, clear=True)
            self.render()
            time.sleep(REFRESH_RATE_SECS)
        return self._running

    def cleanup(self):
        """Clear any states..."""
        self._running = False
        if self._with_blink:
            try:
                from blinkt import clear, show
                clear()
                show()
            except:
                LOG.exception("Failed to cleanup Blinkt.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p", "--with-pygame", action="store_true",
        default=False,
        help="Do a render with Pygame"
    )
    parser.add_argument(
        "-B", "--no-blinkt", action="store_true",
        default=False,
        help="Don't do a render with Blinkt"
    )
    parser.add_argument(
        '-w', '--wait', action="store", type=int,
        help="Wait n seconds before starting ("
        "helps with clock/connection issues)"
    )
    args = parser.parse_args()
    if args.wait:
        LOG.info(f'Waiting {args.wait} seconds before starting...')
        time.sleep(int(args.wait))

    controller = SolarLights(
        with_blinkt=not args.no_blinkt,
        with_pygame=args.with_pygame
    )

    def signal_term_handler(signal, frame):
        """Handle exit gracefully..."""
        LOG.info(f"Got signal {signal}, aborting...")
        sys.exit(0)
    signal.signal(signal.SIGTERM, signal_term_handler)

    interrupted = False
    while not interrupted:
        try:
            interrupted = not controller.run()
        except (KeyboardInterrupt, SystemExit):
            interrupted = True
        except:
            LOG.exception("Exception occurred, retrying run loop.")
        finally:
            controller.cleanup()
            LOG.info("..cleanup on abort done.")
