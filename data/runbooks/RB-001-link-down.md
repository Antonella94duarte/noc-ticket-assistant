# RB-001 Link or interface down

- Applies to alarms: `link_down`, `interface_flap`
- Default severity: major (critical if it isolates a core or aggregation site)
- Owner: NOC transport team

## When to use

An interface between two of our devices, or toward a customer, has changed state to down, or
is flapping (going up and down repeatedly).

## Steps

1. **Find the far end.** Look up the link in the topology: which device and interface are on the
   other side, and whether the link is part of a redundant pair or a bundle.
2. **Check whether traffic was rerouted.** If the link has a redundant path, confirm the backup
   is up and not congested. A down link with a healthy backup means lost redundancy (major),
   not an outage.
3. **Check both ends.**
   - `show interfaces <interface>`: line protocol, last flap, input/output errors.
   - `show logging | include <interface>`: when it went down and any related events.
   - For optical interfaces, check light levels (see RB-002).
4. **Look for a common cause.** Several links down at the same time on one site usually point to
   power (RB-005) or a shared fiber route, not to each interface.
5. **Flapping links.** If the interface flapped more than 5 times in 10 minutes, dampen it or shut
   it administratively *only if* a backup path carries the traffic, and open a field ticket.
6. **Customer access ports.** If the port serves a customer circuit and shows no light from the
   customer side, follow RB-008 before dispatching.

## Escalation

- No backup path and more than 30 minutes down: escalate to the on-call transport engineer and
  dispatch the field team.
- Fiber cut confirmed: open a ticket with the fiber maintenance contractor and notify affected
  customers.
