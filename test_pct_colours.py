"""Script to spit out a table of colours to show the "tilt" light."""
from power import SolarLights


if __name__ == '__main__':
    sl = SolarLights()
    data = {
       'production': 0.00,
       'consumption': 0.00,
       'import': 0.00,
       'export': None,
       'direction': 'import',
       'grid': 0.00
    }
    with open('pct_test.html', 'w') as fp:
        fp.write('<html><head></head><body>\n')
        fp.write('<table>\n')

        for i in range(1, 300, 10):
            fp.write('<tr>')

            data['production'] = i / 100.
            for j in range(1, 300, 10):
                data['consumption'] = j / 100.
                if data['production'] > data['consumption']:
                    data['export'] = data['production'] - data['consumption']
                    data['import'] = 0
                    data['grid'] = data['export']
                    data['direction'] = 'export'
                    pct = data['grid'] / data['production']
                else:
                    data['import'] = data['consumption'] - data['production']
                    data['export'] = 0
                    data['grid'] = data['import']
                    data['direction'] = 'import'
                    pct = data['grid'] / data['consumption']
                sl._data = data
                pixel = sl.get_tilt_pixels()[0]
                fp.write(
                    f'<td style="background-color: '
                    f'rgb({pixel[0]}, {pixel[1]}, {pixel[2]});"'
                    f' title="{data}">\n'
                )
                fp.write(f'    {round(pct, 2)}%\n')
                fp.write('</td>\n')

            fp.write('</tr>\n')
        fp.write('</table>')
        fp.write('</body></html>')
