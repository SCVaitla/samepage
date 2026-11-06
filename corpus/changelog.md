<!-- FICTIONAL: Juniper Desk is an invented company for the SamePage demo. Not real product information. -->
# Changelog

Notable changes to Juniper Desk, newest first.

## 2026-10-14

- New: workload view now shows hours as well as task counts.
- Improved: the iOS app opens recently viewed projects offline.
- Fixed: comments with long links no longer overflow on Android.

## 2026-09-02

- API: raised the Pro rate limit to 1k rpm per workspace (was 600). Enterprise stays at 5k rpm.
- New: webhook deliveries are now signed with a per-workspace secret.
- Fixed: CSV export kept the wrong time zone for due dates.

## 2026-07-21

- New: Enterprise workspaces can choose data residency in the European Union.
- New: SCIM provisioning for Enterprise, with Okta and Microsoft Entra ID.
- Improved: board columns load twice as fast on large projects.

## 2026-05-30

- New: timeline dependencies on Pro and Enterprise.
- New: Slack integration can create tasks from message shortcuts.
- Removed: the legacy XML export. Use CSV or the API instead.

## 2026-03-12

- New: two-factor authentication can be required for all members on every plan.
- Improved: the trash now keeps deleted items for 30 days instead of 14.
