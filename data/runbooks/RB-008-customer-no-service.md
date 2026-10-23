# RB-008 Customer reports no service

- Applies to: customer tickets saying the service is down or nothing works
- Default severity: major for one customer; critical if several customers on the same site report
  it
- Owner: NOC service desk

## Steps

1. **Identify the circuit.** Find the customer's circuit by circuit ID or customer name: access
   device, access port and service type. If the ticket doesn't say which site or circuit, ask the
   customer before anything else.
2. **Check the access port.** Look for active alarms on the access device and port:
   - Port down with no light from the customer side: customer equipment without power, cable or
     drop problem.
   - Port up: the problem is beyond the port (configuration, routing) or on the customer LAN.
3. **Check for a wider problem.** Active alarms on the same site or on the uplinks of the access
   device mean the customer is affected by a larger incident: link the ticket to it instead of
   troubleshooting alone.
4. **Ask the customer the basics** when the network side looks fine:
   - Does the router or ONU have power, and which lights are on?
   - Did anything change on their side (power cut, moved equipment, new cabling)?
   - Since when, and does it affect all users and services?
5. **Dispatch** a technician if the access port shows no light and the customer confirms their
   equipment has power.

## Communication

Acknowledge the impact, say what we are checking, and ask only for the information we don't
already have from the network.
