-- db/create_multiplayer.sql

CREATE TABLE IF NOT EXISTS games (
  id SERIAL PRIMARY KEY,
  code CHAR(3) UNIQUE NOT NULL,
  host_name TEXT NOT NULL,
  city TEXT NOT NULL,
  rounds INTEGER NOT NULL DEFAULT 5,
  status TEXT NOT NULL DEFAULT 'lobby', -- lobby | active | finished | cancelled
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS game_players (
  id SERIAL PRIMARY KEY,
  game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  nickname TEXT NOT NULL,
  joined_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (game_id, nickname)
);

CREATE TABLE IF NOT EXISTS game_rounds (
  id SERIAL PRIMARY KEY,
  game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  round_no INTEGER NOT NULL,      -- 1..rounds
  place_id TEXT NOT NULL,
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  UNIQUE (game_id, round_no)
);

CREATE TABLE IF NOT EXISTS guesses (
  id SERIAL PRIMARY KEY,
  game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  round_id INTEGER NOT NULL REFERENCES game_rounds(id) ON DELETE CASCADE,
  player_id INTEGER NOT NULL REFERENCES game_players(id) ON DELETE CASCADE,
  guess_lat REAL NOT NULL,
  guess_lon REAL NOT NULL,
  distance_m REAL NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (round_id, player_id)
);
