# Google Contacts Tools Reference

MCP tools for managing Google Contacts and contact groups. All tools require `user_google_email` (string, required).

## Contents
- Contacts: search_contacts, list_contacts, get_contact, manage_contact, manage_contacts_batch
- Contact Groups: list_contact_groups, get_contact_group, manage_contact_group
- Tips

---

## Contacts

### search_contacts
Search contacts by name, email, phone number, or other fields.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| query | string | yes | | Searches names, emails, phone numbers |
| user_google_email | string | yes | | |
| page_size | integer | no | 30 | Max 30 |

### list_contacts
List contacts for the authenticated user.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| page_size | integer | no | 100 | Max 1000 |
| page_token | any | no | | Pagination token |
| sort_order | string | no | | `LAST_MODIFIED_ASCENDING`, `LAST_MODIFIED_DESCENDING`, `FIRST_NAME_ASCENDING`, or `LAST_NAME_ASCENDING` |
| request_sync_token | boolean | no | false | Start a full sync and return a structured page; keep true when following its pages |
| sync_token | string | no | | Incremental sync from a previous `next_sync_token`; implies structured output |

Without sync options, the existing text listing is unchanged. For a full sync,
call `list_contacts` with `request_sync_token=true`, then follow
`next_page_token` with the same flag and effective `page_size`. Save
`next_sync_token` only after processing the final page. For later syncs, pass
that token as `sync_token`; on continuation pages, reuse the original
`sync_token` and `page_size`. `sort_order` is rejected in sync mode.

Sync responses contain `account`, `contacts`, `page_size`, `next_page_token`,
`next_sync_token`, and `reset_required`. Contacts are raw People API Person
objects, including email/phone arrays and `metadata.deleted` tombstones.
Empty pages still carry continuation tokens. Tokens are client-owned and are
never stored by the server. A People API HTTP 400 error with the structured
`ErrorInfo.reason` `EXPIRED_SYNC_TOKEN` (or the legacy HTTP 410 fallback) returns
`reset_required=true`, signaling that the client must start a new full sync.
Other HTTP 400 errors still propagate; no full sync is performed implicitly.
Sync tokens expire after seven days, and writes may take several minutes to
appear in sync results. See the [People API sync contract](https://developers.google.com/people/api/rest/v1/people.connections/list).

### get_contact
Get detailed information about a specific contact.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| contact_id | string | yes | | e.g. `c1234567890` or `people/c1234567890` |
| user_google_email | string | yes | | |

### manage_contact
Create, update, or delete a contact.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| action | string | yes | | `create`, `update`, or `delete` |
| user_google_email | string | yes | | |
| contact_id | string | conditional | | Required for `update` and `delete` |
| given_name | string | no | | First name (`create`, `update`) |
| family_name | string | no | | Last name (`create`, `update`) |
| email | string | no | | Email address (`create`, `update`) |
| phone | string | no | | Phone number (`create`, `update`) |
| organization | string | no | | Company/organization (`create`, `update`) |
| job_title | string | no | | Job title (`create`, `update`) |
| notes | string | no | | Additional notes (`create`, `update`) |

### manage_contacts_batch
Batch create, update, or delete contacts.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| action | string | yes | | `create`, `update`, or `delete` |
| user_google_email | string | yes | | |
| contacts | array | conditional | | For `create`: list of dicts with `given_name`, `family_name`, `email`, `phone`, `organization`, `job_title` |
| updates | array | conditional | | For `update`: list of dicts, each must include `contact_id` plus fields to update |
| contact_ids | array | conditional | | For `delete`: list of contact ID strings |

---

## Contact Groups

### list_contact_groups
List contact groups (labels).

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| page_size | integer | no | 100 | Max 1000 |
| page_token | any | no | | Pagination token |

### get_contact_group
Get details of a specific contact group including its members.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| group_id | string | yes | | |
| user_google_email | string | yes | | |
| max_members | integer | no | 100 | Max 1000 |

### manage_contact_group
Create, update, delete a contact group, or modify its members.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| action | string | yes | | `create`, `update`, `delete`, or `modify_members` |
| user_google_email | string | yes | | |
| group_id | string | conditional | | Required for `update`, `delete`, `modify_members` |
| name | string | conditional | | Group name; required for `create` and `update` |
| delete_contacts | boolean | no | false | If true and action is `delete`, also deletes contacts in the group |
| add_contact_ids | array | no | | Contact IDs to add (`modify_members`) |
| remove_contact_ids | array | no | | Contact IDs to remove (`modify_members`) |

---

## Tips

**Avoid duplicates**: Use `search_contacts` to check whether a contact already exists before creating a new one. Search matches on name, email, and phone number.

**Batch organisation**: Use contact groups to organise contacts into categories. Create a group with `manage_contact_group`, then add contacts to it with the `modify_members` action.

**Extra context**: The `notes` field on a contact is a free-text area useful for storing context that does not fit into structured fields (e.g. how you met, preferred contact method).
