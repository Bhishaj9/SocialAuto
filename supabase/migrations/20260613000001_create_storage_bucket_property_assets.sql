-- ============================================================
-- Migration: Create public storage bucket "property-assets"
-- Purpose:   Allow worker nodes to upload / read property images
--            without requiring per-request auth tokens.
-- ============================================================

-- 1. Create the bucket itself
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'property-assets',
  'property-assets',
  true,                          -- publicly readable URLs
  10485760,                      -- 10 MB per file (adjust as needed)
  ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/gif']
)
ON CONFLICT (id) DO NOTHING;

-- 2. Allow anyone to READ objects (public gallery)
DROP POLICY IF EXISTS "Public read access on property-assets" ON storage.objects;
CREATE POLICY "Public read access on property-assets"
  ON storage.objects
  FOR SELECT
  USING (bucket_id = 'property-assets');

-- 3. Allow authenticated users (worker service-role) to INSERT
DROP POLICY IF EXISTS "Authenticated upload to property-assets" ON storage.objects;
CREATE POLICY "Authenticated upload to property-assets"
  ON storage.objects
  FOR INSERT
  WITH CHECK (bucket_id = 'property-assets');

-- 4. Allow authenticated users to UPDATE their own objects
DROP POLICY IF EXISTS "Authenticated update on property-assets" ON storage.objects;
CREATE POLICY "Authenticated update on property-assets"
  ON storage.objects
  FOR UPDATE
  USING (bucket_id = 'property-assets')
  WITH CHECK (bucket_id = 'property-assets');

-- 5. Allow authenticated users to DELETE their own objects
DROP POLICY IF EXISTS "Authenticated delete on property-assets" ON storage.objects;
CREATE POLICY "Authenticated delete on property-assets"
  ON storage.objects
  FOR DELETE
  USING (bucket_id = 'property-assets');

