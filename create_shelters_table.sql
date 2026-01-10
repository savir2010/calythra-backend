-- SQL script to create the shelters table in Supabase
-- Run this in your Supabase SQL Editor

CREATE TABLE IF NOT EXISTS shelters (
    id BIGSERIAL PRIMARY KEY,
    call_sid TEXT NOT NULL,
    rank INTEGER NOT NULL,
    shelter_name TEXT NOT NULL,
    address TEXT,
    phone TEXT,
    description TEXT,
    user_status TEXT,
    user_location TEXT,
    user_needs TEXT,
    shelter_type TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create an index on call_sid for faster queries
CREATE INDEX IF NOT EXISTS idx_shelters_call_sid ON shelters(call_sid);

-- Create an index on created_at for time-based queries
CREATE INDEX IF NOT EXISTS idx_shelters_created_at ON shelters(created_at);

