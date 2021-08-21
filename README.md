# Solar lights

This small script is intended for use with a Pimoroni + Blinkt! header to show
domestic PV Production / Consumption / Grid usage data as indicator lights,
using the SolarEdge monitoring API.

It does not intend to replicate the functionality of the SolarEdge monitoring
portal, but to give a physical indicator in-place of the 'feeling' of how the
home system is performing.

## Features
- Shows:
    - Production
    - If overall system is currently importing, exporting or neutral
    - The 'tilt' away from neutral if importing/exporting
    - Consumption
    - End-of-day retrospective of export to self-consumption
- Use of sunrise/sunset to increase/decrease refresh rate (API is limited!)
- Has settable dim and off times
- Web UI explaining current visuals, and current production/consumption values
- Web UI to modify config (times, colours, etc) and restart

## Ideas
- Flashing to indicate to reduce or increase self-consumption of energy (e.g. after a long period of high import or export respectively)
- Use of time-of-year to limit max expected production capacity

## Security
**The web ui (flask app) is really really insecure!**

It re-writes a python config file via a web form and issues a reboot command.
Do not expose it to the Internet! In the example crontab below, it also uses the
Flask dev server -- this is not advised.

## Running on a Pi
There's no install script yet, so you just have to bodge it together with a git checkout and a crontab...

### Example crontab
```
@reboot cd /home/pi/Code/solar-lights/ && /home/pi/Envs/solar-lights/bin/python /home/pi/Code/solar-lights/power.py -w 60 > /home/pi/logs/power.log 2>&1 &
@reboot cd /home/pi/Code/solar-lights/ && FLASK_APP=configurator /home/pi/Envs/solar-lights/bin/flask run --host=0.0.0.0 --port=8080 > /home/pi/logs/configurator.log 2>&1 &
```
