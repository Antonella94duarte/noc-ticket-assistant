# RB-002 Low optical receive power or loss of signal

- Applies to alarms: `optical_rx_los`, `optical_rx_low`, `onu_los`
- Default severity: major when the link carries traffic; minor while receive power is still above
  the alarm threshold
- Owner: NOC transport team

## Reference values

| Optic | Normal Rx | Low warning | Low alarm |
|---|---|---|---|
| 10G LR | -1 to -10 dBm | -12 dBm | -14 dBm |
| 100G LR4 (per lane) | 0 to -8 dBm | -11 dBm | -14 dBm |
| GPON ONU | -8 to -25 dBm | -27 dBm | -28 dBm |

A reading of -28 dBm or lower on a 10G/100G link, or "LOS", means practically no light.

## Steps

1. **Read both ends.** `show controllers optics <interface>` (IOS-XR) or
   `show interfaces <interface> transceiver detail` (IOS-XE): Tx power on the far end and Rx power
   on the near end.
   - Far-end Tx normal, near-end Rx very low: the problem is in the fiber path or connectors.
   - Far-end Tx low or zero: the far-end optic or device is the suspect.
2. **Check recent work.** Any maintenance on the patch panels or the fiber route in the last
   24 hours is the most likely cause.
3. **Clean and reseat.** With a field technician: clean the connectors at both ends and reseat
   the optic. Re-check Rx power.
4. **Swap the optic.** If cleaning does not help, replace the optic on the side with abnormal
   readings using a spare of the same type.
5. **Test the fiber.** If both optics read normal with a loopback, request an OTDR test of the
   route to locate a break or a bad splice.

## GPON (ONU LOS)

An ONU in LOS with other ONUs on the same PON port working points to the customer drop, the
splitter port or the ONU power (ask the customer whether the ONU has power). Several ONUs in LOS
on the same PON port point to the feeder fiber or the splitter.

## Escalation

If the link has no redundant path, escalate immediately and dispatch the field team in parallel
with the remote checks.
