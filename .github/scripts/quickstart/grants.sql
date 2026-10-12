-- The quick-start source's logins (CI job `quickstart`, spec 021). The reader follows
-- docs/guides/read-only-login.md; the writer additionally may INSERT into orders.
CREATE ROLE sahifa_reader LOGIN PASSWORD :'reader_password';
GRANT CONNECT ON DATABASE shop TO sahifa_reader;
GRANT USAGE ON SCHEMA public TO sahifa_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO sahifa_reader;

CREATE ROLE writer LOGIN PASSWORD :'writer_password';
GRANT CONNECT ON DATABASE shop TO writer;
GRANT USAGE ON SCHEMA public TO writer;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO writer;
GRANT INSERT ON public.orders TO writer;
