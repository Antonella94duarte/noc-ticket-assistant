# RB-009 High utilization on an uplink

- Applies to alarms: `high_utilization`, and customer reports of slowness at peak hours
- Default severity: warning while there is no packet loss; minor with drops; major if the uplink
  is the only path left because its redundant pair is down
- Owner: NOC capacity team

## Steps

1. **Check why it is high.** Look at the redundant uplinks of the same device: if one is down,
   all traffic moved to this one and the real problem is the failed link (RB-001), not capacity.
2. **Check for drops.** `show interfaces <interface>`: output drops and queue drops. Utilization
   without drops is a warning; drops mean customers already feel it.
3. **Find the top talkers.** Use flow data to see whether one customer or one service explains the
   increase (for example a backup job or an attack).
4. **Short term.** If drops are growing and a redundant link is down, prioritize restoring that
   link. Otherwise move traffic to an alternative path if one exists.
5. **Long term.** Utilization above 70% at peak for more than a week: open a capacity upgrade
   request.

## Relation with other symptoms

Congestion causes latency, jitter and frozen video calls for customers on that device, while
links and ports stay up.
