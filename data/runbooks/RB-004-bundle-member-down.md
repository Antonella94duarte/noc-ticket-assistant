# RB-004 Bundle (LAG) member down

- Applies to alarms: `bundle_member_down`
- Default severity: major (lost redundancy) even when the bundle is still up
- Owner: NOC transport team

## Why it matters

A bundle with one member down still carries traffic, so customers usually notice nothing. But
capacity is halved and the next failure takes the bundle down: treat it as lost redundancy.

## Steps

1. **Check the bundle state.** `show bundle <bundle-name>` (IOS-XR) or
   `show etherchannel summary` (IOS-XE): how many members are active and the reason the member
   left (link down, LACP timeout, error-disabled).
2. **Check the remaining capacity.** If utilization on the active members is above 70% at peak,
   plan traffic engineering or a maintenance window: the bundle is close to congestion.
3. **Troubleshoot the member as a link.** Follow RB-001 for link down and RB-002 for optical
   readings on the failed member.
4. **LACP problems.** If the physical link is up but LACP does not bundle it, compare the LACP
   configuration (mode, rate, system priority) on both ends: a recent change is the usual cause
   (RB-007).

## Escalation

Restore within the same business day. If a second member fails or the bundle goes down, escalate
as a link down without backup.
