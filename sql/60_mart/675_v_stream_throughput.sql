-- object : mart.v_stream_throughput
-- grain  : 1 строка = 1 минута (UTC, date_trunc по received_at) за последние 60 минут
-- source : landing.events
-- cc     : K0 §4.2 (received_at UTC, status), K4 §4 (источник D4 timeseries)
-- why    : пропускная способность потока по минутам для панели D4 Pipeline; VIEW — данные потока видны сразу, без REFRESH

CREATE VIEW mart.v_stream_throughput AS
SELECT
    date_trunc('minute', received_at) AS minute,
    COUNT(*) AS events,
    COUNT(*) FILTER (WHERE status = 'applied') AS applied,
    COUNT(*) FILTER (WHERE status = 'error') AS errors
FROM landing.events
WHERE received_at >= (now() AT TIME ZONE 'utc') - INTERVAL '60 minutes'
GROUP BY date_trunc('minute', received_at);
