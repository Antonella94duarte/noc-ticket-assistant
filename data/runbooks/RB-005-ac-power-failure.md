# RB-005 Commercial power failure (site on batteries)

- Applies to alarms: `ac_input_failure`, `battery_discharge`, `generator_failure`
- Default severity: major; critical when the remaining battery autonomy is under 1 hour or the
  site is a core site
- Owner: NOC operations with the facilities team

## Steps

1. **Confirm the power loss.** Check whether the alarm affects only our site or the whole area:
   call the power utility and check their outage map.
2. **Estimate the time left.** Use the battery remaining percentage and the site's rated
   autonomy (site inventory: backup power hours). Recheck every 30 minutes.
3. **Generator.** If the site has a generator, confirm it started. If it failed to start, dispatch
   facilities immediately.
4. **Plan for the worst case.** With less than 2 hours of autonomy and no restoration time from
   the utility:
   - Dispatch a portable generator.
   - Identify which customers and links depend on the site and whether traffic can be rerouted.
   - Prepare a notice for affected enterprise customers.
5. **Load shedding.** Below 20% battery, shut down non-essential equipment (lab, test devices)
   following the site's load shedding list to extend autonomy.

## Communication

Do not announce an outage before it happens: tell enterprise customers served by the site that
there is a power event under control and that we will update them if service could be affected.
