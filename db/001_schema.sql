CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS papers (
    arxiv_id text PRIMARY KEY,
    title text NOT NULL,
    authors text NOT NULL,
    abstract text NOT NULL,
    categories text[] NOT NULL,
    embedding vector(384) NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id uuid PRIMARY KEY,
    kind text NOT NULL DEFAULT 'query' CHECK (kind IN ('query', 'index')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    object_key text NOT NULL,
    cache_key text,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    result jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    published_at timestamptz
);

CREATE INDEX IF NOT EXISTS jobs_outbox_idx ON jobs (created_at, id) WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS corpus_snapshot (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    digest text NOT NULL,
    model_mode text NOT NULL,
    paper_count integer NOT NULL,
    batch_size integer NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'completed'))
);
