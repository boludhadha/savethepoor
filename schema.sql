-- Create table for registered users.
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    display_name TEXT NOT NULL
);

-- Create table for transactions (each expense recorded).
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    spender BIGINT NOT NULL REFERENCES users(user_id),
    amount NUMERIC NOT NULL,
    description TEXT NOT NULL,
    share NUMERIC NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create table for debts (each debtor’s status per transaction).
CREATE TABLE IF NOT EXISTS debts (
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    debtor_id BIGINT NOT NULL REFERENCES users(user_id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'marked', 'confirmed')),
    PRIMARY KEY (transaction_id, debtor_id)
);
