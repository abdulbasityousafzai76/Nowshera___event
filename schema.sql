begin;
create schema if not exists nec_private;
revoke all on schema nec_private from public;
create table public.nec_admins (
 user_id uuid primary key references auth.users(id) on delete cascade,
 created_at timestamptz not null default now()
);
create table public.nec_events (
 id uuid primary key default gen_random_uuid(),
 title text not null check(length(trim(title)) between 3 and 160),
 description text not null check(length(trim(description)) between 10 and 10000),
 venue text not null check(length(trim(venue)) between 3 and 240),
 category text not null default 'Workshop' check(category in ('Workshop','Seminar','Community')),
 starts_at timestamptz not null,
 capacity integer not null check(capacity between 1 and 100000),
 status text not null default 'draft' check(status in ('draft','published','cancelled','completed')),
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.nec_registrations (
 id uuid primary key default gen_random_uuid(),
 event_id uuid not null references public.nec_events(id) on delete restrict,
 user_id uuid not null references auth.users(id) on delete cascade,
 status text not null default 'active' check(status in ('active','cancelled')),
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create unique index nec_one_active on public.nec_registrations(event_id,user_id) where status='active';
create index nec_reg_user on public.nec_registrations(user_id);
create index nec_event_schedule on public.nec_events(status,starts_at);
alter table public.nec_events enable row level security;
alter table public.nec_registrations enable row level security;
alter table public.nec_admins enable row level security;
revoke all on public.nec_events,public.nec_registrations,public.nec_admins from anon,authenticated;
-- Only this private, explicitly authorized API can mutate records. There are
-- deliberately no direct table grants; the Data API cannot bypass the rules.
create function nec_private.api(operation text, payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 uid uuid := auth.uid(); admin boolean; ev public.nec_events; reg public.nec_registrations;
 n integer; eid uuid; result jsonb; new_status text;
begin
 select uid is not null and exists(select 1 from public.nec_admins where user_id=uid) into admin;
 if operation='list' then
  select coalesce(jsonb_agg(to_jsonb(t) order by t.starts_at),'[]'::jsonb) into result from (
   select e.*, (select count(*) from public.nec_registrations r where r.event_id=e.id and r.status='active') as registered
   from public.nec_events e where e.status='published' and e.starts_at>now()
  ) t; return result;
 end if;
 if operation='detail' then
  select to_jsonb(e) || jsonb_build_object('registered',(select count(*) from public.nec_registrations r where r.event_id=e.id and r.status='active')) into result
  from public.nec_events e where e.id=(payload->>'id')::uuid and (e.status<>'draft' or admin or exists(select 1 from public.nec_registrations r where r.event_id=e.id and r.user_id=uid));
  if result is null then raise exception 'Event not found'; end if; return result;
 end if;
 if uid is null then raise exception 'Please sign in to continue'; end if;
 if operation='me' then return jsonb_build_object('id',uid,'is_admin',admin); end if;
 if operation='my' then
  select coalesce(jsonb_agg(to_jsonb(r)||jsonb_build_object('event',to_jsonb(e)) order by r.created_at desc),'[]'::jsonb) into result
  from public.nec_registrations r join public.nec_events e on e.id=r.event_id where r.user_id=uid; return result;
 end if;
 if operation='register' then
  select * into ev from public.nec_events where id=(payload->>'id')::uuid for update;
  if not found then raise exception 'Event not found'; end if;
  if ev.status<>'published' or ev.starts_at<=now() then raise exception 'This event is no longer accepting registrations'; end if;
  if exists(select 1 from public.nec_registrations where event_id=ev.id and user_id=uid and status='active') then raise exception 'You already have a place at this event'; end if;
  select count(*) into n from public.nec_registrations where event_id=ev.id and status='active';
  if n>=ev.capacity then raise exception 'This event is full'; end if;
  insert into public.nec_registrations(event_id,user_id) values(ev.id,uid) returning * into reg;
  return to_jsonb(reg);
 end if;
 if operation='cancel' then
  select event_id into eid from public.nec_registrations where id=(payload->>'id')::uuid and user_id=uid;
  if eid is null then raise exception 'Registration not found'; end if;
  select * into ev from public.nec_events where id=eid for update;
  if ev.starts_at<=now() or ev.status in ('cancelled','completed') then raise exception 'Cancellation is closed for this event'; end if;
  update public.nec_registrations set status='cancelled',updated_at=now() where id=(payload->>'id')::uuid and user_id=uid and status='active' returning * into reg;
  if not found then raise exception 'Registration is already cancelled'; end if; return to_jsonb(reg);
 end if;
 if not admin then raise exception 'Administrator access required'; end if;
 if operation='admin_list' then
  select coalesce(jsonb_agg(to_jsonb(t) order by t.starts_at desc),'[]'::jsonb) into result from (
   select e.*,(select count(*) from public.nec_registrations r where r.event_id=e.id and r.status='active') as registered from public.nec_events e
  ) t; return result;
 elsif operation='save' then
  eid:=nullif(payload->>'id','')::uuid; new_status:=payload->>'status';
  if eid is not null then
   select * into ev from public.nec_events where id=eid for update;
   if not found then raise exception 'Event not found'; end if;
   if ev.status in ('cancelled','completed') and new_status<>ev.status then raise exception 'Closed events cannot be reopened'; end if;
   if ev.status='published' and new_status='draft' then raise exception 'Published events cannot return to draft'; end if;
   select count(*) into n from public.nec_registrations where event_id=eid and status='active';
   if (payload->>'capacity')::integer<n then raise exception 'Capacity cannot be below active registrations'; end if;
  end if;
  if new_status='published' and (payload->>'starts_at')::timestamptz<=now() then raise exception 'Published events must have a future date'; end if;
  if new_status='completed' and (payload->>'starts_at')::timestamptz>now() then raise exception 'An event can only be completed after its start'; end if;
  if eid is null then
   insert into public.nec_events(title,description,venue,category,starts_at,capacity,status)
   values(payload->>'title',payload->>'description',payload->>'venue',payload->>'category',(payload->>'starts_at')::timestamptz,(payload->>'capacity')::integer,new_status) returning * into ev;
  else
   update public.nec_events set title=payload->>'title',description=payload->>'description',venue=payload->>'venue',category=payload->>'category',starts_at=(payload->>'starts_at')::timestamptz,capacity=(payload->>'capacity')::integer,status=new_status,updated_at=now() where id=eid returning * into ev;
  end if; return to_jsonb(ev);
 elsif operation='delete' then
  select * into ev from public.nec_events where id=(payload->>'id')::uuid for update;
  if not found then raise exception 'Event not found'; end if;
  if exists(select 1 from public.nec_registrations where event_id=ev.id) then raise exception 'This event has registration history. Cancel the event to preserve records'; end if;
  delete from public.nec_events where id=ev.id; return '{"deleted":true}'::jsonb;
 elsif operation='attendees' then
  select coalesce(jsonb_agg(jsonb_build_object('id',r.id,'name',coalesce(u.raw_user_meta_data->>'name','Attendee'),'email',u.email,'status',r.status,'created_at',r.created_at) order by r.created_at),'[]'::jsonb) into result
  from public.nec_registrations r join auth.users u on u.id=r.user_id where r.event_id=(payload->>'id')::uuid; return result;
 elsif operation='stats' then
  return jsonb_build_object('total_events',(select count(*) from public.nec_events),'upcoming_events',(select count(*) from public.nec_events where status='published' and starts_at>now()),'registrations',(select count(*) from public.nec_registrations where status='active'),'available_places',(select coalesce(sum(e.capacity-(select count(*) from public.nec_registrations r where r.event_id=e.id and r.status='active')),0) from public.nec_events e where e.status='published' and e.starts_at>now()));
 end if;
 raise exception 'Unknown operation';
end $$;
revoke all on function nec_private.api(text,jsonb) from public;
grant usage on schema nec_private to anon,authenticated;
grant execute on function nec_private.api(text,jsonb) to anon,authenticated;
create function public.nec_api(operation text,payload jsonb default '{}'::jsonb)
returns jsonb language sql security invoker set search_path='' as $$ select nec_private.api(operation,payload); $$;
revoke all on function public.nec_api(text,jsonb) from public;
grant execute on function public.nec_api(text,jsonb) to anon,authenticated;
commit;
