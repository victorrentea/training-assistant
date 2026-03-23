-- Initial schema: participants, scores, app settings, and activity state
-- All participant tables are keyed by UUID (TEXT)

CREATE TABLE participants (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    avatar TEXT NOT NULL DEFAULT ''
);

CREATE TABLE scores (
    uuid TEXT PRIMARY KEY,
    score INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO app_settings (key, value) VALUES ('mode', 'workshop');

-- Activity state stored as JSON blobs (poll, Q&A, wordcloud, codereview, debate)
CREATE TABLE activity_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
