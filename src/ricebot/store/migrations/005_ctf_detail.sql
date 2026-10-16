-- What the announcement and the channel's first message say about a contest.
-- All of it is CTFtime's, so ensure() overwrites it on every pass.
ALTER TABLE ctf_events ADD COLUMN restrictions TEXT NOT NULL DEFAULT '';
ALTER TABLE ctf_events ADD COLUMN onsite INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ctf_events ADD COLUMN location TEXT NOT NULL DEFAULT '';
ALTER TABLE ctf_events ADD COLUMN organizers TEXT NOT NULL DEFAULT '';
ALTER TABLE ctf_events ADD COLUMN participants INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ctf_events ADD COLUMN description TEXT NOT NULL DEFAULT '';
