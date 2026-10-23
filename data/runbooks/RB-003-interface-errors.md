# RB-003 CRC and input errors on an interface

- Applies to alarms: `interface_errors`
- Default severity: minor (major if the interface carries a backbone or uplink without backup)
- Owner: NOC operations

## Symptoms

Customers report slowness, intermittent drops or frozen video calls while the interface stays up.
Counters show CRC, frame or input errors growing.

## Steps

1. **Confirm the errors are still growing.** Errors accumulate since the last counter clear, so a
   single reading means little.
   - `show interfaces <interface>` and note CRC and input errors.
   - Wait 5 minutes and read again. Do not clear the counters before the second reading.
2. **Read what kind of errors they are.**
   - CRC and frame errors: physical layer (cable, connector, optic) or a duplex/speed mismatch.
   - Overruns and input drops without CRC: congestion or the device not keeping up, see RB-009.
3. **Check speed and duplex on both ends.** A mismatch (one side forced, the other on auto)
   produces CRC errors under load. Both sides must match.
4. **Check the optic or cable.** For optical ports, check light levels (RB-002). For copper, ask
   the site or the customer to replace the patch cord.
5. **Move the circuit if needed.** If errors keep growing after replacing the cable or optic and
   the customer is affected, move the circuit to a spare port.

## Communication

Errors that only affect one customer port are usually fixed by replacing a cable or an optic.
Tell the customer we are checking the connection and may need someone on site to replace a cable.
