# Lakeshore Grand — Public Employee Submission Portal (starter)

This is the first deployable implementation module for the agreed workflow:

- Department heads use one public link; no department-head account or login.
- Form captures submitter name/department, employee name, designation, employee department, optional employee ID, blood group, optional work email, requested card(s), and employee photo.
- Each successful submission receives a reference number and confirmation.
- Photos are stored in a **private** Supabase Storage bucket. Database and photo access are performed by the server only.
- HR dashboard is private and requires an HR bearer token (this is separate from the public submission form).
- HR can review requests and change status to pending, approved, rejected, or generated, with optional notes and audit entries.
- A laptop sync script downloads submissions and photos into a local SQLite database and local photo folder.

## Project files

- `app.py` — Flask API and hosted web application.
- `templates/submit.html` — public mobile-friendly form.
- `templates/hr.html` — private HR inbox.
- `sql/schema.sql` — Supabase database table and private photo bucket setup.
- `local_sync/sync_client.py` — laptop-side pull/sync utility.
- `render.yaml` — Render deployment blueprint.
- `.env.example` — required server environment variables.

## Deployment setup (not yet deployed)

1. Create a Supabase project.
2. In Supabase SQL Editor, run `sql/schema.sql`.
3. In Supabase Project Settings → API, copy the Project URL and **service_role** key. The service-role key must stay on the server; never paste it into browser code, WhatsApp, or the local HTML.
4. Create a strong random HR token (at least 32 random bytes). Keep it private.
5. Deploy this folder to a Python web host such as Render. Set these environment variables on the host:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `HR_API_TOKEN`
   - `SUPABASE_STORAGE_BUCKET=employee-photos`
   - `MAX_UPLOAD_MB=8`
   - `RATELIMIT_STORAGE_URI` (for production, use a managed Redis URL; memory rate limiting is only a single-instance fallback)
6. After deployment, check `/health`, then test one submission and the `/hr` page.
7. Share the deployed root URL (`https://your-host/...`) with department heads through WhatsApp or email. HR opens `/hr` and enters the HR token.

## Laptop sync

Install Python 3.10+ on the HR laptop, then:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install requests
$env:PORTAL_URL="https://YOUR-DEPLOYED-HOST"
$env:HR_API_TOKEN="YOUR_HR_TOKEN"
py .\local_sync\sync_client.py
```

By default, records and photos are saved under `%USERPROFILE%\LakeshoreGrandHR\`. Re-run the command whenever you want to sync. This initial utility is a manual pull; it does not yet run as a background Windows service or automatically start the card generator.

## Security and production notes

- Public form is intentionally no-login. Anyone with the link can submit; do not treat the URL as proof of identity.
- HR routes require a separate secret token. Protect the token and restrict access to authorized HR staff. A future release should replace the shared token with named HR accounts / MFA if needed.
- The service-role key bypasses Supabase RLS, so it exists only in server environment variables.
- Supabase bucket is private; photos are exposed to HR only through short-lived signed URLs.
- The code validates image signatures and MIME type, limits upload size, applies a per-IP submission rate limit, uses a hidden honeypot field, checks duplicate active employee IDs, and records status changes.
- Configure Redis-backed rate limiting before scaling to multiple server instances. Consider adding CAPTCHA, email notifications, backups, retention rules, malware scanning, and audit-log immutability before production use.
- This starter is not deployed and does not yet issue a live public URL. It has not been penetration-tested. Verify local legal/privacy requirements for employee photographs and blood-group data before collecting them.

## Illustrator card design integration

The earlier Illustrator-matched portal remains a separate local card-preview artifact. This module stores the approved card-request details and employee photo securely. The next integration step is to connect approved records from the local sync database to the fixed Lakeshore Grand ID/business-card renderer and its original Illustrator assets. Do not use the public form to redesign card artwork.
