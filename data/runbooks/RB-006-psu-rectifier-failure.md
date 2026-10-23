# RB-006 Power supply or rectifier failure

- Applies to alarms: `psu_failure`, `rectifier_failure`
- Default severity: major (lost redundancy)
- Owner: NOC operations with the field team

## Why it matters

Devices and sites have redundant power supplies or rectifiers. When one fails the equipment keeps
running on the other, so there is no service impact yet, but a second failure means an outage.

## Steps

1. **Confirm the remaining unit is healthy.** `show environment power` (IOS-XE) or
   `show environment` (IOS-XR): the other power supply must be OK and below its rated load.
   For rectifiers, check the load on the remaining units on the power system controller.
2. **Rule out an upstream cause.** If both feeds of the device come from the same power
   distribution and other devices on the site show power alarms, investigate the site power first
   (RB-005).
3. **Request the replacement.** Open an RMA for the failed unit with the hardware vendor and
   schedule the replacement within 24 hours. Power supplies are hot-swappable: no maintenance
   window is needed unless the device has a single feed.
4. **Watch the device until it is replaced.** Raise the priority of any further power alarm on the
   same device.
