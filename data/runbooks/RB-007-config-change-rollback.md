# RB-007 Service affected after a configuration change

- Applies to alarms: `config_change`, and any service issue that starts right after a change
- Default severity: major when a customer service is down
- Owner: NOC operations with the change owner

## Steps

1. **Find the change.** Compare the start of the problem with recent configuration changes:
   - `show configuration commit list` (IOS-XR) or the archive log (IOS-XE): who changed what and
     when.
   - Check the change management calendar for an approved change on the device.
2. **Compare the configuration.** `show configuration commit changes <commit-id>` (IOS-XR) or
   `show archive config differences`: look for removed VLANs, ACL entries, route policies or
   interface settings related to the affected service.
3. **Decide: fix forward or roll back.**
   - If the change was not approved, or its owner can't be reached in 15 minutes and a customer
     service is down, roll back: `rollback configuration to <commit-id>` (IOS-XR) or reapply the
     removed lines.
   - If the change was approved and only one detail is wrong (for example a VLAN missing from a
     trunk), apply the minimal fix and record it in the change ticket.
4. **Verify the service.** Confirm with the customer or with a remote test that the service works.
5. **Close the loop.** Inform the change owner and add the incident to the change review.

## Common cases

- VLAN removed from a trunk's allowed list: the customer behind that VLAN loses service while the
  port stays up.
- ACL entry removed or reordered: one protocol or destination stops working (for example SSH to a
  hosted server) while the rest works.
