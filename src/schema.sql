CREATE TABLE IF NOT EXISTS users (
  id          TEXT PRIMARY KEY,
  telegram_id INTEGER UNIQUE NOT NULL,
  name        TEXT NOT NULL,
  created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
  id           TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount       INTEGER NOT NULL CHECK (amount > 0),
  category     TEXT NOT NULL,
  description  TEXT,
  date         TEXT NOT NULL,
  input_type   TEXT CHECK (input_type IN ('text', 'image', 'pdf', 'agent')),
  raw_input    TEXT,
  confidence   TEXT CHECK (confidence IN ('high', 'medium', 'low')),
  created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS budgets (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category   TEXT NOT NULL,
  amount     INTEGER NOT NULL CHECK (amount > 0),
  month      INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  year       INTEGER NOT NULL,
  UNIQUE (user_id, category, month, year)
);

CREATE TABLE IF NOT EXISTS total_budgets (
  id       TEXT PRIMARY KEY,
  user_id  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount   INTEGER NOT NULL CHECK (amount > 0),
  month    INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  year     INTEGER NOT NULL,
  UNIQUE (user_id, month, year)
);

CREATE INDEX IF NOT EXISTS idx_transactions_user_date
  ON transactions(user_id, date);

CREATE INDEX IF NOT EXISTS idx_budgets_user_month
  ON budgets(user_id, month, year);
