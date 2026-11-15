"""Pull submitted employee requests and private photos into a local HR folder.
Run: set PORTAL_URL and HR_API_TOKEN, then python sync_client.py
"""
import os, json, sqlite3, pathlib, requests
from datetime import datetime, timezone

PORTAL_URL=os.getenv('PORTAL_URL','').rstrip('/')
TOKEN=os.getenv('HR_API_TOKEN','')
ROOT=pathlib.Path(os.getenv('LAKESHORE_LOCAL_DATA', pathlib.Path.home()/'LakeshoreGrandHR'))
DB=ROOT/'lakeshore_hr.sqlite3'; PHOTOS=ROOT/'photos'; PHOTOS.mkdir(parents=True,exist_ok=True); ROOT.mkdir(parents=True,exist_ok=True)
if not PORTAL_URL or not TOKEN: raise SystemExit('Set PORTAL_URL and HR_API_TOKEN first.')
headers={'Authorization':'Bearer '+TOKEN}
con=sqlite3.connect(DB);con.execute('''create table if not exists submissions (id text primary key, reference text unique, employee_name text, designation text, employee_department text, employee_id text, blood_group text, submitter_name text, submitter_department text, card_request text, status text, hr_note text, submitted_at text, photo_file text, raw_json text)''');con.commit()
r=requests.get(PORTAL_URL+'/api/hr/sync',headers=headers,timeout=60);r.raise_for_status();payload=r.json();count=0
for item in payload.get('items',[]):
    sid=item['id']; photo_path=''
    p=requests.get(PORTAL_URL+f'/api/hr/sync/{sid}/photo',headers=headers,timeout=30);p.raise_for_status(); signed=p.json()['url']; img=requests.get(signed,timeout=60);img.raise_for_status()
    suffix={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}.get(item.get('photo_mime'),'.img')
    local=PHOTOS/(sid+suffix);local.write_bytes(img.content);photo_path=str(local)
    con.execute('''insert into submissions values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict(id) do update set reference=excluded.reference, employee_name=excluded.employee_name, designation=excluded.designation, employee_department=excluded.employee_department, employee_id=excluded.employee_id, blood_group=excluded.blood_group, submitter_name=excluded.submitter_name, submitter_department=excluded.submitter_department, card_request=excluded.card_request, status=excluded.status, hr_note=excluded.hr_note, submitted_at=excluded.submitted_at, photo_file=excluded.photo_file, raw_json=excluded.raw_json''', (sid,item.get('reference'),item.get('employee_name'),item.get('designation'),item.get('employee_department'),item.get('employee_id'),item.get('blood_group'),item.get('submitter_name'),item.get('submitter_department'),item.get('card_request'),item.get('status'),item.get('hr_note'),item.get('submitted_at'),photo_path,json.dumps(item,ensure_ascii=False)))
    count+=1
con.commit();con.close();print(f'Synced {count} submission(s). Local database: {DB}');print(f'Photos: {PHOTOS}')
