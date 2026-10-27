-- StockWhy public notices (SYNTHETIC stand-ins for Bright Data results).
-- Load into a SEPARATE Postgres database (e.g. stockwhy_web), registered in Zetaris as its own datasource,
-- so investigators run a federated query across stockwhy_pg and stockwhy_web.
BEGIN;
DROP TABLE IF EXISTS public.web_notes;
CREATE TABLE public.web_notes (id INTEGER, month TEXT, commodity TEXT, source TEXT, title TEXT, url TEXT);
INSERT INTO public.web_notes VALUES
(1, '2025-06', 'ORS sachet', 'KEMSA notice (synthetic)', 'Routine delivery schedule update', 'https://example.org/synthetic/1'),
(2, '2025-11', 'zinc 20mg tab', 'Tender notice (synthetic)', 'Framework tender opened', 'https://example.org/synthetic/2');
COMMIT;
