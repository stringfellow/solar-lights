import unittest

from parameterized import parameterized

from power import get_production_percent_pixels

class TestPixels(unittest.TestCase):
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
        pixels = get_production_percent_pixels({
            'production': prod,
        }, multi=True)
        self.assertEqual(pixels, result)
