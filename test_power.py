from unittest import TestCase
from unittest.mock import patch, PropertyMock


from parameterized import parameterized

from power import SolarLights

class TestPixels(TestCase):
    """Test pixel production."""

    @parameterized.expand([
        (0, [[0, 0, 0], [0, 0, 0], [0, 0, 0]]),
        (2.97 * 5. / 6., [[255, 255, 255], [255, 255, 255], [127, 127, 127]]),
        (2.97, [[255, 255, 255], [255, 255, 255], [255, 255, 255]]),
        (.99, [[255, 255, 255], [0, 0, 0], [0, 0, 0]]),
        (1.98, [[255, 255, 255], [255, 255, 255], [0, 0, 0]]),
        (1, [[255, 255, 255], [2, 2, 2], [0, 0, 0]]),
    ])
    def test_multi_pixel_split(self, prod, result):
        """Should split into multi pixels."""
        pulse = PropertyMock(return_value=1)
        with patch(
            'power.PRODUCTION_COLOUR', [255, 255, 255]
        ):
            sl = SolarLights()
            type(sl).pulse_percent = pulse
            sl._data = {
                'production': prod
            }
            pixels = sl.get_production_percent_pixels(multi=3)
            self.assertEqual(pixels, result)
