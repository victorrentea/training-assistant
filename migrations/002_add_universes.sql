-- Add universe column for conference mode character assignments
ALTER TABLE participants ADD COLUMN universe TEXT NOT NULL DEFAULT '';
