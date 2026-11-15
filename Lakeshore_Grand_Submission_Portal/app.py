import os, re, uuid, secrets, mimetypes
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "8")) * 1024 * 1024
limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"))

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
HR_API_TOKEN = os.getenv("HR_API_TOKEN", "")
BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "employee-photos")
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
DEPARTMENTS = ["Front Office", "Food & Beverage", "Culinary & Kitchen", "Housekeeping", "Engineering & Maintenance", "Sales & Marketing", "Finance", "Human Resources", "Security", "IT", "Executive Management", "Other"]
BLOOD_GROUPS = ["A(+)" ,"A(-)","B(+)" ,"B(-)","AB(+)" ,"AB(-)","O(+)" ,"O(-)","Not provided"]


def configured():
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and HR_API_TOKEN)


def sb_headers(extra=None):
    h = {"apikey": SUPABASE_SERVICE_ROLE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"}
    if extra: h.update(extra)
    return h


def sb_request(method, path, **kwargs):
    if not configured():
        abort(503, description="Server setup is incomplete. Contact the HR administrator.")
    return requests.request(method, f"{SUPABASE_URL}{path}", headers=sb_headers(kwargs.pop("headers", None)), timeout=30, **kwargs)


def hr_only(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not HR_API_TOKEN or not secrets.compare_digest(token, HR_API_TOKEN):
            return jsonify({"error": "HR authorization required"}), 401
        return fn(*args, **kwargs)
    return wrapper


@app.get("/")
def public_form():
    return send_from_directory(os.path.join(BASE, "templates"), "submit.html")


@app.get("/hr")
def hr_dashboard():
    return send_from_directory(os.path.join(BASE, "templates"), "hr.html")


@app.get("/health")
def health():
    return jsonify({"ok": True, "configured": configured(), "service": "Lakeshore Grand Submission Portal"})


@app.post("/api/submissions")
@limiter.limit("8 per hour")
def create_submission():
    if not configured():
        return jsonify({"error": "Submission service is not configured yet."}), 503
    # Honeypot: humans should never fill this hidden field.
    if request.form.get("website", "").strip():
        return jsonify({"ok": True, "reference": "LG-" + secrets.token_hex(4).upper()}), 200

    required = ["submitter_name", "submitter_department", "employee_name", "designation", "employee_department", "card_request"]
    missing = [k for k in required if not request.form.get(k, "").strip()]
    if missing: return jsonify({"error": "Please complete all required fields.", "missing": missing}), 400

    fields = {k: request.form.get(k, "").strip() for k in required}
    fields["employee_id"] = request.form.get("employee_id", "").strip() or None
    fields["blood_group"] = request.form.get("blood_group", "Not provided").strip()
    fields["work_email"] = request.form.get("work_email", "").strip() or None
    fields["property"] = request.form.get("property", "Lakeshore Grand").strip()
    if fields["submitter_department"] not in DEPARTMENTS or fields["employee_department"] not in DEPARTMENTS:
        return jsonify({"error": "Please select a valid department."}), 400
    if fields["blood_group"] not in BLOOD_GROUPS:
        return jsonify({"error": "Please select a valid blood group."}), 400
    if fields["card_request"] not in {"id", "business", "both"}:
        return jsonify({"error": "Please select a valid card request."}), 400

    photo = request.files.get("photo")
    if not photo or not photo.filename:
        return jsonify({"error": "Please attach the employee photograph."}), 400
    if photo.mimetype not in ALLOWED_TYPES:
        return jsonify({"error": "Photo must be JPG, PNG or WEBP."}), 400
    data = photo.read()
    if not data or len(data) > app.config["MAX_CONTENT_LENGTH"]:
        return jsonify({"error": "Photo is empty or exceeds the upload limit."}), 400
    # Basic file signature validation; don't trust browser MIME alone.
    signatures = {"image/jpeg": data.startswith(b"\xff\xd8\xff"), "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"), "image/webp": data[:4] == b"RIFF" and data[8:12] == b"WEBP"}
    if not signatures.get(photo.mimetype, False):
        return jsonify({"error": "The uploaded file does not appear to be a valid image."}), 400

    # Duplicate check for a non-empty employee ID (case-insensitive).
    if fields["employee_id"]:
        dup = sb_request("GET", "/rest/v1/employee_submissions", params={"select":"id,reference,status", "employee_id":f"ilike.{fields['employee_id']}", "status":"not.eq.rejected", "limit":"1"})
        if not dup.ok: return jsonify({"error": "Could not verify duplicate employee ID. Please try again."}), 502
        if dup.json(): return jsonify({"error": "This employee ID already has an active submission.", "existing_reference": dup.json()[0]["reference"]}), 409

    submission_id = str(uuid.uuid4())
    reference = "LG-" + datetime.now(timezone.utc).strftime("%y%m%d") + "-" + secrets.token_hex(3).upper()
    ext = {"image/jpeg":"jpg", "image/png":"png", "image/webp":"webp"}[photo.mimetype]
    object_path = f"{submission_id}.{ext}"
    up = sb_request("POST", f"/storage/v1/object/{BUCKET}/{object_path}", data=data, headers={"Content-Type":photo.mimetype, "x-upsert":"false"})
    if not up.ok: return jsonify({"error": "Photo storage failed. Please try again later."}), 502

    record = {
        "id": submission_id, "reference": reference, **fields,
        "photo_path": object_path, "photo_mime": photo.mimetype,
        "status": "pending", "submitted_at": datetime.now(timezone.utc).isoformat(),
        "audit_log": [{"action":"submitted", "at":datetime.now(timezone.utc).isoformat(), "actor":"public_form"}]
    }
    ins = sb_request("POST", "/rest/v1/employee_submissions", json=record, headers={"Content-Type":"application/json", "Prefer":"return=representation"})
    if not ins.ok:
        sb_request("DELETE", f"/storage/v1/object/{BUCKET}", json={"prefixes":[object_path]})
        return jsonify({"error": "Could not save the submission. Please try again later."}), 502
    return jsonify({"ok":True, "reference":reference, "message":"Your employee request has been submitted to HR."}), 201


@app.get("/api/hr/submissions")
@hr_only
def list_submissions():
    status = request.args.get("status", "all")
    params = {"select":"*", "order":"submitted_at.desc", "limit":"250"}
    if status in {"pending", "approved", "rejected", "generated"}: params["status"] = f"eq.{status}"
    r = sb_request("GET", "/rest/v1/employee_submissions", params=params)
    if not r.ok: return jsonify({"error":"Could not load submissions"}), 502
    return jsonify(r.json())


@app.get("/api/hr/submissions/<submission_id>/photo")
@hr_only
def get_photo(submission_id):
    r = sb_request("GET", "/rest/v1/employee_submissions", params={"select":"photo_path", "id":f"eq.{submission_id}", "limit":"1"})
    if not r.ok or not r.json(): return jsonify({"error":"Submission not found"}), 404
    path = r.json()[0]["photo_path"]
    signed = sb_request("POST", f"/storage/v1/object/sign/{BUCKET}/{path}", json={"expiresIn":180})
    if not signed.ok: return jsonify({"error":"Could not create photo link"}), 502
    out = signed.json().get("signedURL") or signed.json().get("signedUrl")
    if not out: return jsonify({"error":"Photo link unavailable"}), 502
    if out.startswith("/"): out = SUPABASE_URL + out
    return jsonify({"url":out})


@app.patch("/api/hr/submissions/<submission_id>")
@hr_only
def update_submission(submission_id):
    body = request.get_json(silent=True) or {}
    allowed = {"pending", "approved", "rejected", "generated"}
    new_status = body.get("status")
    if new_status is not None and new_status not in allowed: return jsonify({"error":"Invalid status"}), 400
    note = str(body.get("note", ""))[:500]
    editable = {k: body[k] for k in ("employee_name", "designation", "employee_department", "employee_id", "blood_group", "work_email", "card_request") if k in body}
    if "card_request" in editable and editable["card_request"] not in {"id", "business", "both"}: return jsonify({"error":"Invalid card request"}), 400
    if "employee_name" in editable and not str(editable["employee_name"]).strip(): return jsonify({"error":"Employee name cannot be blank"}), 400
    old = sb_request("GET", "/rest/v1/employee_submissions", params={"select":"audit_log", "id":f"eq.{submission_id}", "limit":"1"})
    if not old.ok or not old.json(): return jsonify({"error":"Submission not found"}), 404
    log = old.json()[0].get("audit_log") or []
    if new_status is not None:
        log.append({"action":"status_changed", "status":new_status, "note":note, "at":datetime.now(timezone.utc).isoformat(), "actor":"hr"})
    if editable:
        log.append({"action":"details_edited", "fields":list(editable.keys()), "at":datetime.now(timezone.utc).isoformat(), "actor":"hr"})
    patch_data = {**editable, "audit_log":log, "updated_at":datetime.now(timezone.utc).isoformat()}
    if new_status is not None: patch_data["status"] = new_status
    if note: patch_data["hr_note"] = note
    patch = sb_request("PATCH", "/rest/v1/employee_submissions", params={"id":f"eq.{submission_id}"}, json=patch_data, headers={"Content-Type":"application/json", "Prefer":"return=representation"})
    if not patch.ok: return jsonify({"error":"Could not update submission"}), 502
    return jsonify(patch.json()[0] if patch.json() else {"ok":True})


@app.get("/api/hr/sync")
@hr_only
def sync_feed():
    since = request.args.get("since")
    params = {"select":"*", "order":"submitted_at.asc", "limit":"500"}
    if since: params["submitted_at"] = f"gt.{since}"
    r = sb_request("GET", "/rest/v1/employee_submissions", params=params)
    if not r.ok: return jsonify({"error":"Could not sync submissions"}), 502
    return jsonify({"items":r.json(), "server_time":datetime.now(timezone.utc).isoformat()})


@app.get("/api/hr/sync/<submission_id>/photo")
@hr_only
def sync_photo(submission_id):
    return get_photo(submission_id)


@app.errorhandler(413)
def too_large(_): return jsonify({"error":f"Photo exceeds {os.getenv('MAX_UPLOAD_MB','8')} MB limit."}), 413

@app.errorhandler(429)
def too_many(_): return jsonify({"error":"Too many submissions from this connection. Please try again later."}), 429

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
