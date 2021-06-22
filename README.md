# Solar lights

This small script is intended for use with a Pimoroni + Blinkt! header to show
domestic PV Production / Consumption / Grid usage data as indicator lights,
using the SolarEdge monitoring API.

It does not intend to replicate the functionality of the SolarEdge monitoring
portal, but to give a physical indicator in-place of the 'feeling' of how the
home system is performing.

## Ideas
- Showing the 'lean' toward import/export or neutral (balanced) production & consumption
- Showing the production strength (as a luminous-proportion of capacity)
- Flashing to indicate to reduce or increase self-consumption of energy (e.g. after a long period of high import or export respectively)
- ...