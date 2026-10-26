-- Registers the two StockWhy sources in Zetaris. `python scripts/setup_live.py` runs these for you, filling the
-- placeholders from .env (one statement per call, as Zetaris requires). Creating a datasource needs admin rights.
-- Never commit this file with real values.

CREATE DATASOURCE stockwhy_pg DESCRIBE BY "StockWhy facility stock orders and payments" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://{PG_HOST}:{PG_PORT}/{PG_DATABASE}{PG_JDBC_PARAMS}",
  username "{PG_USER}",
  password "{PG_PASSWORD}",
  fetchsize "1000"
);

REGISTER DATASOURCE TABLES FROM stockwhy_pg;

CREATE DATASOURCE stockwhy_web DESCRIBE BY "StockWhy public notices" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://{PG_HOST}:{PG_PORT}/{PG_WEB_DATABASE}{PG_JDBC_PARAMS}",
  username "{PG_USER}",
  password "{PG_PASSWORD}",
  fetchsize "1000"
);

REGISTER DATASOURCE TABLES FROM stockwhy_web;
