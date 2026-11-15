-- Run in Supabase SQL Editor. Keep RLS enabled; server uses the service_role key.
create extension if not exists pgcrypto;
create table if not exists public.employee_submissions (
  id uuid primary key default gen_random_uuid(),
  reference text not null unique,
  submitter_name text not null,
  submitter_department text not null,
  employee_name text not null,
  designation text not null,
  employee_department text not null,
  employee_id text,
  blood_group text not null default 'Not provided',
  work_email text,
  property text not null default 'Lakeshore Grand',
  card_request text not null check (card_request in ('id','business','both')),
  photo_path text not null,
  photo_mime text not null,
  status text not null default 'pending' check (status in ('pending','approved','rejected','generated')),
  hr_note text,
  submitted_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  audit_log jsonb not null default '[]'::jsonb
);
create index if not exists employee_submissions_status_idx on public.employee_submissions(status, submitted_at desc);
create index if not exists employee_submissions_employee_id_idx on public.employee_submissions(lower(employee_id)) where employee_id is not null;
alter table public.employee_submissions enable row level security;
-- Do not create anon/authenticated table policies. All reads/writes go through the server.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('employee-photos','employee-photos',false,8388608,array['image/jpeg','image/png','image/webp'])
on conflict (id) do update set public=false, file_size_limit=8388608, allowed_mime_types=array['image/jpeg','image/png','image/webp'];
-- No anon/authenticated storage policies: server service_role handles private uploads and signed photo URLs.
