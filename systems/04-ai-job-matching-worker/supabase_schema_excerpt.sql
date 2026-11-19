-- =============================================================================
-- Supabase (PostgreSQL) Core Queue, Platform Policy & Audit Schema
-- Decoupled Next.js UI <-> Docker Playwright Worker State Machine
-- =============================================================================

create table public.users (
    id                uuid primary key references auth.users(id) on delete cascade,
    email             text not null,
    full_name         text,
    phone             text,
    cv_storage_path   text,
    cv_uploaded_at    timestamptz,
    credits_available int not null default 0,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

create type task_status as enum (
    'pending',
    'scraping',
    'analyzing',
    'applying',
    'completed',
    'failed'
);

create table public.job_tasks (
    id               uuid primary key default gen_random_uuid(),
    user_id          uuid not null references public.users(id) on delete cascade,
    status           task_status not null default 'pending',
    search_role      text not null,
    search_location  text,
    search_platform  text not null,
    cv_storage_path  text not null,
    max_applications int not null default 10,
    jobs_scraped     int not null default 0,
    jobs_matched     int not null default 0,
    jobs_applied     int not null default 0,
    error_message    text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    completed_at     timestamptz
);

create index idx_job_tasks_status on public.job_tasks(status);
create index idx_job_tasks_user   on public.job_tasks(user_id);

-- Platform Governance: Tiers 1-2 support API/form prep; Tiers 3-4 generate search links only.
create type application_mode as enum ('auto_apply', 'manual_suggested');

create table public.job_platforms (
    id                   text primary key,
    display_name         text not null,
    risk_tier            int not null,
    application_mode     application_mode not null,
    search_url_template  text,
    created_at           timestamptz not null default now()
);

alter table public.job_platforms enable row level security;
create policy "select_all_platforms" on public.job_platforms
    for select using (true);

insert into public.job_platforms (id, display_name, risk_tier, application_mode, search_url_template) values
    ('remoteok',        'RemoteOK',          1, 'auto_apply', null),
    ('arbeitnow',       'Arbeitnow',         1, 'auto_apply', null),
    ('jobicy',          'Jobicy',            1, 'auto_apply', null),
    ('himalayas',       'Himalayas',         1, 'auto_apply', null),
    ('greenhouse',      'Greenhouse (ATS)',  2, 'auto_apply', null),
    ('lever',           'Lever (ATS)',       2, 'auto_apply', null),
    ('workable',        'Workable (ATS)',    2, 'auto_apply', null),
    ('ashby',           'Ashby (ATS)',       2, 'auto_apply', null),
    ('linkedin',        'LinkedIn',          4, 'manual_suggested',
        'https://www.linkedin.com/jobs/search/?keywords={role}&location={location}'),
    ('indeed',          'Indeed',            4, 'manual_suggested',
        'https://www.indeed.com/jobs?q={role}&l={location}')
on conflict (id) do nothing;

-- Audit & Human-in-the-Loop Execution Gate
-- ready_for_review -> user RPC confirm_application() -> confirmed -> submitting -> submitted
create table public.applications_log (
    id                          uuid primary key default gen_random_uuid(),
    job_task_id                 uuid not null references public.job_tasks(id) on delete cascade,
    user_id                     uuid not null references public.users(id) on delete cascade,
    platform_id                 text references public.job_platforms(id),
    job_external_id             text,
    job_title                   text,
    job_company                 text,
    job_url                     text not null,
    match_score                 int,
    match_reason                text,
    cover_letter                text,
    application_status          text not null default 'pending',
    preview_screenshot_path     text,
    post_submit_screenshot_path text,
    submitted_at                timestamptz,
    error_message               text,
    created_at                  timestamptz not null default now()
);

create index idx_applications_log_task     on public.applications_log(job_task_id);
create index idx_applications_log_user     on public.applications_log(user_id);
create index idx_applications_log_platform on public.applications_log(platform_id);

alter table public.users            enable row level security;
alter table public.job_tasks        enable row level security;
alter table public.applications_log enable row level security;
