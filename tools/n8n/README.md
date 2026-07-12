# n8n Google Drive mirror (customer files)

Optional, off-the-hot-path glue that mirrors every newly registered customer file
into a per-customer Google Drive folder. It is **off by default** and lives entirely
outside the chat request cycle — if n8n is down, file registration still succeeds and
the customer's local-disk folder is unaffected.

```
Django (crm.storage.register_file)
  └─ crm.file_sink.mirror_customer_file  ── signed POST ──▶  n8n Webhook
                                                              ├─ Search customer folder (Drive)
                                                              ├─ Create it if missing (search-then-create)
                                                              ├─ Download file_url
                                                              ├─ Upload into the folder
                                                              └─ Respond { "drive_url": ... }
Django stores drive_url back on CustomerFile.
```

## Payload Django sends

`POST <n8n webhook URL>` with header `X-Nordland-Signature: sha256=<hmac>` (when a
shared secret is configured) and JSON body:

```json
{
  "customer_id": 42,
  "customer_name": "Erik Svensson",
  "file_url": "https://nordland.example.com/uploads/customers/42/invoices/quote.pdf",
  "filename": "quote.pdf",
  "folder": "invoices"
}
```

The response is parsed for a Drive link under any of: `drive_url`, `link`,
`webViewLink`, `webContentLink`, `url`. The first non-empty match is saved to
`CustomerFile.drive_url` and shown as a `↗ Drive` link in the dashboard.

## Setup

1. **Dashboard → Settings → n8n → Google Drive mirror**: paste the n8n webhook URL,
   set a shared secret (`openssl rand -hex 32`), tick *Enable mirror*, Save.
2. In n8n: **Import from File** → `drive_mirror.workflow.json`.
3. Open each **Google Drive** node and select your Google Drive OAuth2 credential
   (the imported `id` is a placeholder — n8n will prompt).
4. **Verify the signature** (recommended): add a Function/Code node right after the
   Webhook that recomputes `HMAC_SHA256(shared_secret, raw_body)` and compares it to
   the `X-Nordland-Signature` header; reject on mismatch. (Django's signature is over
   the exact JSON bytes it sent.)
5. Ensure `file_url` is reachable from n8n. Set `PUBLIC_BASE_URL` in Django's env to a
   host n8n can fetch, or run n8n where it can reach the media path. If the media route
   is auth-gated, add the appropriate auth on the **Download file** HTTP Request node.
6. Activate the workflow and upload a test file to a customer to confirm a Drive folder
   is created and the `↗ Drive` link appears in the dashboard.

## Notes

- **Search-then-create** avoids duplicate folders: the `Search customer folder` node
  looks for `Customer <id> - <name>`; the `Folder exists?` IF branches to reuse or
  create. Folder naming keys on the immutable `customer_id` so a renamed customer still
  resolves to one folder (adjust the query to match on id only if you prefer).
- The workflow is a **starting point** — tune Drive `driveId`/shared-drive, folder
  naming, and add the signature-verification node before relying on it in production.
