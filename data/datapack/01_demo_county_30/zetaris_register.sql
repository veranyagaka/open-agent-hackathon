-- Run these in the Zetaris SQL Editor, ONE statement at a time. Creating a datasource needs administrator rights.
-- Replace the placeholders. Do not commit this file with a real password.

CREATE DATASOURCE stockwhy_pg DESCRIBE BY "StockWhy synthetic data" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://YOUR_HOST:5432/YOUR_DATABASE?sslmode=require",
  username "YOUR_USER",
  password "YOUR_PASSWORD",
  fetchsize "1000"
);

REGISTER DATASOURCE TABLES FROM stockwhy_pg;

-- Check it worked:
SHOW DATASOURCE TABLES stockwhy_pg;
SELECT * FROM stockwhy_pg.stock LIMIT 5;

-- Then set ZETARIS_SCHEMA=stockwhy_pg in .env
