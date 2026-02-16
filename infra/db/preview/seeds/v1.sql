CREATE TABLE IF NOT EXISTS preview_seed_meta (
    id SERIAL PRIMARY KEY,
    seed_version TEXT NOT NULL,
    seeded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note TEXT
);

INSERT INTO preview_seed_meta (seed_version, note)
VALUES ('v1', 'Deterministic baseline preview seed')
ON CONFLICT DO NOTHING;
