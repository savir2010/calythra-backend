-- SQL script to create the preferences table in Supabase
-- Run this in your Supabase SQL Editor

CREATE TABLE IF NOT EXISTS preferences (
    id BIGSERIAL PRIMARY KEY,
    call_sid TEXT NOT NULL,
    status TEXT,
    location TEXT,
    zipcode TEXT,
    needs TEXT,
    shelter_type TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create an index on call_sid for faster queries
CREATE INDEX IF NOT EXISTS idx_preferences_call_sid ON preferences(call_sid);

-- Create an index on created_at for time-based queries
CREATE INDEX IF NOT EXISTS idx_preferences_created_at ON preferences(created_at);

