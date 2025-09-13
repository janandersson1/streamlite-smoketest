-- db/create_multiplayer.sqlite.sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS games (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  code       TEXT NOT NULL UNIQUE CHECK (length(code) = 3),
  host_name  TEXT NOT NULL,
  city       TEXT NOT NULL,
  rounds     INTEGER NOT NULL DEFAULT 5,
  status     TEXT NOT NULL DEFAULT 'lobby', -- lobby | active | finished | cancelled
  created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS game_players (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id    INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  nickname   TEXT NOT NULL,
  joined_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  UNIQUE (game_id, nickname)
);

CREATE TABLE IF NOT EXISTS game_rounds (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  round_no    INTEGER NOT NULL,      -- 1..rounds
  place_id    TEXT NOT NULL,
  lat         REAL NOT NULL,
  lon         REAL NOT NULL,
  started_at  TEXT,
  finished_at TEXT,
  UNIQUE (game_id, round_no)
);

CREATE TABLE IF NOT EXISTS guesses (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  round_id    INTEGER NOT NULL REFERENCES game_rounds(id) ON DELETE CASCADE,
  player_id   INTEGER NOT NULL REFERENCES game_players(id) ON DELETE CASCADE,
  guess_lat   REAL NOT NULL,
  guess_lon   REAL NOT NULL,
  distance_m  REAL NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  UNIQUE (round_id, player_id)
);

-- Rekommenderade index
CREATE INDEX IF NOT EXISTS idx_game_players_game     ON game_players(game_id);
CREATE INDEX IF NOT EXISTS idx_rounds_game_roundno   ON game_rounds(game_id, round_no);
CREATE INDEX IF NOT EXISTS idx_guesses_round         ON guesses(round_id);
CREATE INDEX IF NOT EXISTS idx_guesses_game          ON guesses(game_id);
