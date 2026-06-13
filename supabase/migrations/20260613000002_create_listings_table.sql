-- ============================================================
-- Migration: Create listings table, indexes, and claiming function
-- Purpose:   Support a multi-tenant task queue for AutoBVB
--            using PostgreSQL and concurrency-safe queues.
-- ============================================================

-- 1. Create listings table
CREATE TABLE listings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id TEXT NOT NULL,
    original_assets TEXT[] NOT NULL DEFAULT '{}',
    generated_captions JSONB,
    final_approved_text TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'processing', 'completed', 'failed')),
    claimed_by TEXT,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Create performance index for approved listings
CREATE INDEX idx_listings_approved_status
ON listings (created_at ASC)
WHERE status = 'approved';

-- 3. Automatic updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 4. Create trigger to auto-update updated_at
CREATE TRIGGER update_listings_updated_at
BEFORE UPDATE ON listings
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- 5. Atomic queue claiming function utilizing SELECT ... FOR UPDATE SKIP LOCKED
CREATE OR REPLACE FUNCTION claim_next_approved_listing(worker_id TEXT)
RETURNS SETOF listings AS $$
DECLARE
    claimed_listing listings;
BEGIN
    -- Select the oldest approved task, locking it and skipping any already locked by other transactions
    SELECT * INTO claimed_listing
    FROM listings
    WHERE status = 'approved'
    ORDER BY created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    -- If a listing was successfully locked, transition it to 'processing' and assign the worker
    IF claimed_listing.id IS NOT NULL THEN
        UPDATE listings
        SET status = 'processing',
            claimed_by = worker_id
        WHERE id = claimed_listing.id
        RETURNING * INTO claimed_listing;

        RETURN NEXT claimed_listing;
    END IF;

    RETURN;
END;
$$ LANGUAGE plpgsql;
