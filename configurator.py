import os
from importlib import reload

from flask import Flask, render_template, request, redirect, jsonify

import config as power_config
from power import SolarLights

app = Flask(__name__)


def _rewrite_config_file():
    """Update config.py."""
    exceptions = ('SITE_ID',)
    temp_arrays = {}

    with open('config.py', 'w') as fp:
        for key, val in request.form.items():
            if key not in exceptions and '-' not in key:
                try:
                    val = float(val)
                    fp.write(f"{key} = {val}\n")
                except ValueError:
                    fp.write(f"{key} = '{val}'\n")
            elif '-' in key:
                prefix, suffix = key.split('-')
                temp_arrays[prefix] = temp_arrays.get(prefix, {})
                temp_arrays[prefix][suffix] = int(val)
            else:
                fp.write(f"{key} = '{val}'\n")

        for key, vals in temp_arrays.items():
            fp.write(f"{key} = [{vals['R']}, {vals['G']}, {vals['B']}]\n")

    return redirect("/?updated=1", code=302)


@app.route("/", methods=['GET', 'POST'])
def update_config():
    """Show form and update config."""
    reload(power_config)
    if request.method == 'POST':
        return _rewrite_config_file()

    context = {
        key: val
        for key, val
        in power_config.__dict__.items()
        if not key.startswith('_')
    }
    context.update(request.args)

    return render_template('home.jinja2', **context)


@app.route('/reboot', methods=['POST'])
def reboot():
    """Restart the service."""
    os.system('sudo reboot')
    return render_template('rebooting.jinja2')


@app.route('/lights', methods=['GET'])
def get_lights():
    """Get current display and explanation."""
    sol = SolarLights(
        with_pygame=False, with_blinkt=False,
        with_csv=True, with_solaredge=False
    )
    sol._pulse_max_renders = 1
    sol._flash_max_renders = 1
    sol._render_count = 1
    sol.set_next_update()
    sol.update_data()
    pixels = sol.get_pixels()
    help = sol.help
    refresh = sol.get_refresh_interval()
    context = {
        'pixels': pixels,
        'help': help,
        'refresh': refresh,
        'data': sol._data,
    }
    return jsonify(context)
