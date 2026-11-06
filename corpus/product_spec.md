<!-- FICTIONAL: Juniper Desk is an invented company for the SamePage demo. Not real product information. -->
# Juniper Desk Product Specification

Status: Approved by Product, Legal and Finance. Version 4.2.
This document is the approved source of truth for what Juniper Desk offers. Customer-facing
material (website, help center, sales and support content) must agree with it. When it does
not, this document wins until Product approves a change.

## 1. Overview

Juniper Desk is a task and project management tool for small and mid-sized teams. Teams
organize work into projects, break projects into tasks, assign owners and due dates, and
track progress on boards, lists and timelines. Juniper Desk runs in the browser, on macOS
and Windows desktop apps, and on iOS and Android.

The product is sold as a monthly or annual subscription per workspace. A workspace is the
container for a team's projects, members, integrations and billing.

## 2. Plans

Juniper Desk is offered on three plans.

**Starter** is for small teams getting organized for the first time. It includes unlimited
projects and tasks, boards and lists, file attachments up to 100 MB per file, and the
standard integrations (Google Drive, Slack, email forwarding). Starter is billed at $8 per
seat per month on annual billing.

**Pro** is for growing teams that need planning and reporting. It adds timelines, task
dependencies, workload views, custom fields, guest access, and the full REST API. Pro is
billed at $15 per seat per month on annual billing.

**Enterprise** is for organizations with security, compliance and administration needs.
It adds identity and access controls, the admin audit log, data residency options, a
named customer success manager, and a 99.9% uptime commitment. Enterprise is priced by
quote.

Plan limits that apply to each workspace are listed in Appendix A.

## 3. Identity and access

All plans support email and password sign-in, Google sign-in, and two-factor
authentication with an authenticator app.

Single sign-on (SSO) through SAML 2.0 is an Enterprise plan feature. It is not available
on the Starter or Pro plans, including as a paid add-on. Enterprise workspaces can connect
Okta, Microsoft Entra ID, Google Workspace or any SAML 2.0 identity provider, and can
enforce SSO for all members. SCIM user provisioning is also Enterprise only.

Workspace admins on every plan can deactivate members, transfer project ownership, and
reset a member's two-factor authentication.

## 4. Billing and refunds

Subscriptions renew automatically at the end of each billing period. Workspaces can switch
between monthly and annual billing at renewal. Adding seats mid-period is billed pro rata;
removing seats takes effect at the next renewal.

Refund policy: a customer may request a full refund within 14 days of the initial purchase
or of an annual renewal. After 14 days, payments are non-refundable, and a cancelled
subscription stays active until the end of the paid period. Refunds are issued to the
original payment method. Monthly renewals are not eligible for refunds.

Invoices are available to workspace owners under Settings, Billing. Enterprise customers
can pay by bank transfer against a purchase order.

## 5. Support

Customer support is staffed 24/7, every day of the year, for all plans. Customers reach
support through the in-app chat or by email. Target first-response times are 24 hours on
Starter, 8 hours on Pro, and 1 hour on Enterprise for urgent issues. Enterprise customers
also have a named customer success manager who runs quarterly reviews.

Phone support is not offered on any plan.

## 6. API

The REST API is available on Pro and Enterprise. Requests are authenticated with personal
access tokens or OAuth 2.0 apps that a workspace admin approves.

API rate limits are applied per workspace:

- Pro: 1,000 requests per minute.
- Enterprise: 5,000 requests per minute, and higher on request.

Requests above the limit receive HTTP 429 with a Retry-After header. Webhooks are
delivered at least once and retried with backoff for up to 24 hours.

## 7. Data, security and compliance

Customer data is encrypted in transit with TLS 1.2 or later and at rest with AES-256.
Juniper Desk holds a SOC 2 Type II report, available under NDA, and is GDPR compliant.
Enterprise customers can choose data residency in the United States or the European Union.

Deleted tasks and projects stay in the workspace trash for 30 days and can be restored by
any admin during that time. After 30 days they are permanently deleted. When a workspace
is closed, its data is deleted within 60 days.

Availability target: 99.9% monthly uptime for Enterprise, measured as described in the
Enterprise agreement. Starter and Pro have no contractual uptime commitment.

## 8. Mobile and desktop apps

The iOS and Android apps support boards, lists, comments, notifications and offline
viewing of recently opened projects. The desktop apps add a global quick-add shortcut and
native notifications. Timelines and workload views are browser and desktop only.

## Appendix A. Workspace limits

These limits are enforced by the product. Sales may not promise exceptions without
written approval from Product.

| Limit | Starter | Pro | Enterprise |
|---|---|---|---|
| Seats per workspace | 5 | 250 | Unlimited |
| Guests per workspace | Not available | 50 | Unlimited |
| File size per attachment | 100 MB | 1 GB | 5 GB |
| Total storage | 10 GB | 1 TB | Unlimited |
| Automations per month | 100 | 5,000 | 50,000 |

Starter workspaces are limited to 5 seats. To add a sixth member, the workspace must
upgrade to Pro.
