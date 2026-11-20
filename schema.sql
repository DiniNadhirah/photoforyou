-- =====================================================================
-- PhotoForYou v2 - Supabase setup
-- Run once in Supabase -> SQL Editor -> New query -> Run.
-- Safe to run more than once. It does NOT delete your old `photos` table
-- or the old public `Photos` bucket; remove those yourself when ready.
-- =====================================================================

-- 1. Users (keeps your existing accounts and adds the vault columns) ----
create table if not exists public.users (
  id            bigint generated always as identity primary key,
  username      text not null unique,
  password_hash text not null,
  created_at    timestamptz not null default now()
);
alter table public.users add column if not exists vault_salt  text;
alter table public.users add column if not exists vault_check text;
alter table public.users add column if not exists created_at  timestamptz not null default now();

-- 2. Media: one row per encrypted photo/video ------------------------------
--    Only metadata lives here; the encrypted bytes live in Storage.
create table if not exists public.media (
  id           uuid primary key,
  user_id      text not null,              -- owner (users.id as text)
  folder       text not null,
  name_enc     text not null,              -- file name, encrypted in the browser
  mime_type    text not null,
  kind         text not null check (kind in ('image', 'video')),
  size_bytes   bigint not null,            -- original size (for the quota)
  stored_bytes bigint not null,            -- encrypted size actually stored
  object_path  text not null,              -- <user_id>/<id>.bin
  thumb_path   text,                       -- <user_id>/<id>.thumb.bin
  created_at   timestamptz not null default now()
);
create index if not exists media_user_created_idx on public.media (user_id, created_at desc);

-- 3. Row Level Security ---------------------------------------------------
--    RLS ON with NO policies = the public "anon" key can read nothing.
--    Only the server (service_role key, kept secret on Render) can access.
alter table public.users enable row level security;
alter table public.media enable row level security;

-- 4. Private storage bucket (50 MB per file) ------------------------------
insert into storage.buckets (id, name, public, file_size_limit)
values ('vault', 'vault', false, 52428800)
on conflict (id) do update set public = false, file_size_limit = 52428800;
