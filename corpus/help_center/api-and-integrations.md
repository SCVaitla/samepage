<!-- FICTIONAL: Juniper Desk is an invented company for the SamePage demo. Not real product information. -->
# API and integrations

Connect Juniper Desk to the tools your team already uses, or build your own integration with
the REST API.

## Built-in integrations

All plans include Google Drive (attach files from Drive to tasks), Slack (post task updates to
a channel and create tasks from messages), and email forwarding (forward an email to your
workspace address to create a task). Admins turn integrations on under Settings, Integrations.

## The REST API

The REST API is available on the Pro and Enterprise plans. Create a personal access token
under Settings, Developer, or register an OAuth app that a workspace admin approves. The API
covers projects, tasks, comments, members and custom fields.

## Rate limits

Each workspace has a rate limit on API calls. Pro workspaces can make 1,000 requests per
minute, and Enterprise workspaces 5,000 requests per minute. If you go over the limit, the
API answers with HTTP 429 and a Retry-After header telling you how many seconds to wait.

## Webhooks

Webhooks notify your service when tasks are created, updated or completed. Deliveries are
signed with your webhook secret. If your endpoint does not answer with a 2xx status, we retry
with backoff for up to 24 hours.
