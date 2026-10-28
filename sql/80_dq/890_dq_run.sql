-- object : гейт сборки по DQ
-- grain  : -
-- source : mart.dq_result
-- cc     : -
-- why    : в режиме strict упавшая проверка откатывает всю сборку (она идёт одной транзакцией);
--          режим задаётся SET capibara.dq_mode = 'strict' | 'report', по умолчанию strict

DO $$
DECLARE
    failed text;
BEGIN
    SELECT string_agg(check_id, ', ' ORDER BY check_id) INTO failed
    FROM mart.dq_result
    WHERE NOT passed;

    IF failed IS NOT NULL THEN
        IF COALESCE(NULLIF(current_setting('capibara.dq_mode', true), ''), 'strict') = 'strict' THEN
            RAISE EXCEPTION 'DQ failed: %', failed;
        END IF;
        RAISE WARNING 'DQ failed (report mode): %', failed;
    END IF;
END $$;
