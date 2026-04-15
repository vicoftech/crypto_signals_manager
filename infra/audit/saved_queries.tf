resource "aws_athena_named_query" "embudo_scanner" {
  name        = "01_embudo_scanner_7dias"
  description = "Cuántos pares pasan cada etapa del embudo por día"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    SELECT
        year,
        month,
        day,
        session,
        COUNT(*) AS ciclos,
        ROUND(AVG(pares_evaluados), 1) AS avg_pares_evaluados,
        ROUND(AVG(pares_operables), 1) AS avg_pares_operables,
        ROUND(AVG(pares_operables * 100.0 / NULLIF(pares_evaluados, 0)), 1) AS pct_pasan_contexto,
        SUM(oportunidades_brutas) AS total_ops_brutas,
        SUM(enviadas_telegram) AS total_enviadas,
        ROUND(AVG(duracion_ms), 0) AS avg_duracion_ms
    FROM scan_cycles
    WHERE year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -7, CURRENT_DATE))
    GROUP BY year, month, day, session
    ORDER BY year DESC, month DESC, day DESC, total_enviadas DESC;
  SQL
}

resource "aws_athena_named_query" "razones_descarte_contexto" {
  name        = "02_razones_descarte_contexto"
  description = "Por qué se descartan los pares en el evaluador de contexto"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    SELECT
        CASE
            WHEN trend != 'BULLISH' THEN '1_trend_no_bullish'
            WHEN volume_state = 'QUIET' THEN '2_volumen_bajo'
            WHEN volatility = 'LOW' THEN '3_volatilidad_baja'
            WHEN NOT atr_viable THEN '4_atr_no_viable'
            WHEN bb_squeeze THEN '5_bb_squeeze'
            ELSE 'otro'
        END AS razon_descarte,
        COUNT(*) AS total_casos,
        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS porcentaje,
        COUNT(DISTINCT pair) AS pares_afectados,
        SUM(CASE WHEN session = 'ASIA' THEN 1 ELSE 0 END) AS en_asia,
        SUM(CASE WHEN session = 'LONDON' THEN 1 ELSE 0 END) AS en_london,
        SUM(CASE WHEN session = 'NEW_YORK' THEN 1 ELSE 0 END) AS en_new_york
    FROM market_context_log
    WHERE tradeable = false
        AND year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -7, CURRENT_DATE))
    GROUP BY 1
    ORDER BY total_casos DESC;
  SQL
}

resource "aws_athena_named_query" "fallas_por_estrategia" {
  name        = "03_fallas_por_estrategia"
  description = "Qué condición falla más frecuentemente en cada estrategia"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    SELECT
        strategy,
        condicion_falla,
        COUNT(*) AS total_fallos,
        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY strategy), 1) AS pct_dentro_estrategia,
        COUNT(DISTINCT pair) AS pares_donde_falla
    FROM strategy_executions
    WHERE resultado = 'FALLO'
        AND condicion_falla IS NOT NULL
        AND year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -7, CURRENT_DATE))
    GROUP BY strategy, condicion_falla
    ORDER BY strategy, total_fallos DESC;
  SQL
}

resource "aws_athena_named_query" "conversion_por_estrategia" {
  name        = "04_conversion_por_estrategia"
  description = "Qué porcentaje de ejecuciones genera una oportunidad"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    SELECT
        strategy,
        COUNT(*) AS total_ejecuciones,
        SUM(CASE WHEN resultado = 'OPORTUNIDAD' THEN 1 ELSE 0 END) AS oportunidades,
        SUM(CASE WHEN resultado = 'FALLO' THEN 1 ELSE 0 END) AS fallos,
        SUM(CASE WHEN resultado = 'ERROR' THEN 1 ELSE 0 END) AS errores,
        ROUND(SUM(CASE WHEN resultado = 'OPORTUNIDAD' THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0) * 100, 2) AS pct_conversion,
        COUNT(DISTINCT pair) AS pares_evaluados
    FROM strategy_executions
    WHERE year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -7, CURRENT_DATE))
    GROUP BY strategy
    ORDER BY pct_conversion DESC;
  SQL
}

resource "aws_athena_named_query" "oportunidades_por_sesion" {
  name        = "05_oportunidades_por_sesion_y_par"
  description = "En qué sesión y par se detectan más oportunidades"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    SELECT
        session,
        pair,
        strategy,
        COUNT(*) AS total_oportunidades,
        ROUND(AVG(rr_ratio), 2) AS rr_promedio,
        ROUND(AVG(sl_pct) * 100, 3) AS sl_pct_promedio,
        SUM(CASE WHEN confluence THEN 1 ELSE 0 END) AS con_confluencia
    FROM opportunities
    WHERE year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -30, CURRENT_DATE))
    GROUP BY session, pair, strategy
    ORDER BY total_oportunidades DESC
    LIMIT 30;
  SQL
}

resource "aws_athena_named_query" "performance_trades" {
  name        = "06_performance_trades_por_estrategia"
  description = "Winrate, R múltiple promedio y P&L por estrategia"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    SELECT
        strategy,
        mode,
        COUNT(*) AS total_trades,
        SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) AS ganadoras,
        ROUND(AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) AS winrate_pct,
        ROUND(AVG(r_multiple), 2) AS r_multiple_promedio,
        ROUND(SUM(net_pnl), 2) AS pnl_total_usd,
        ROUND(AVG(mae) * 100, 3) AS mae_promedio_pct,
        ROUND(AVG(mfe) * 100, 3) AS mfe_promedio_pct,
        ROUND(AVG(duration_minutes), 0) AS duracion_promedio_min
    FROM trades
    GROUP BY strategy, mode
    ORDER BY mode, r_multiple_promedio DESC;
  SQL
}

resource "aws_athena_named_query" "analisis_mae_mfe" {
  name        = "07_analisis_mae_mfe_optimizacion_sl"
  description = "Compara MAE de ganadoras vs SL actual"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    SELECT
        strategy,
        close_reason,
        COUNT(*) AS trades,
        ROUND(AVG(sl_pct) * 100, 3) AS sl_pct_promedio,
        ROUND(AVG(mae) * 100, 3) AS mae_promedio_pct,
        ROUND(AVG(mae) / NULLIF(AVG(sl_pct), 0) * 100, 1) AS mae_como_pct_del_sl,
        ROUND(AVG(mfe) * 100, 3) AS mfe_promedio_pct,
        ROUND(AVG(rr_actual), 2) AS rr_actual_promedio,
        ROUND(AVG(rr_planned), 2) AS rr_planeado_promedio
    FROM trades
    WHERE net_pnl > 0
        AND year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -30, CURRENT_DATE))
    GROUP BY strategy, close_reason
    ORDER BY strategy, mae_como_pct_del_sl ASC;
  SQL
}

resource "aws_athena_named_query" "confluencia_vs_winrate" {
  name        = "08_confluencia_vs_winrate"
  description = "Las señales con confluencia tienen mejor winrate?"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    SELECT
        confluence,
        mode,
        COUNT(*) AS total_trades,
        ROUND(AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) AS winrate_pct,
        ROUND(AVG(r_multiple), 2) AS r_multiple_promedio,
        ROUND(SUM(net_pnl), 2) AS pnl_total_usd
    FROM trades
    GROUP BY confluence, mode
    ORDER BY mode, confluence DESC;
  SQL
}

resource "aws_athena_named_query" "resumen_diario" {
  name        = "09_resumen_diario_ejecutivo"
  description = "Vista rápida del día: oportunidades, trades, P&L"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    WITH contexto AS (
        SELECT
            COUNT(DISTINCT pair) AS pares_evaluados,
            SUM(CASE WHEN tradeable THEN 1 ELSE 0 END) AS pares_operables,
            ROUND(AVG(CASE WHEN tradeable THEN 1.0 ELSE 0.0 END) * 100, 1) AS pct_operables
        FROM market_context_log
        WHERE year = YEAR(CURRENT_DATE)
          AND month = MONTH(CURRENT_DATE)
          AND day = DAY(CURRENT_DATE)
    ),
    ops AS (
        SELECT
            COUNT(*) AS total_oportunidades,
            COUNT(DISTINCT strategy) AS estrategias_activas,
            COUNT(DISTINCT pair) AS pares_con_oportunidad,
            SUM(CASE WHEN confluence THEN 1 ELSE 0 END) AS con_confluencia
        FROM opportunities
        WHERE year = YEAR(CURRENT_DATE)
          AND month = MONTH(CURRENT_DATE)
          AND day = DAY(CURRENT_DATE)
    ),
    resultado AS (
        SELECT
            COUNT(*) AS trades_totales,
            SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) AS ganadoras,
            ROUND(SUM(net_pnl), 2) AS pnl_neto_usd,
            ROUND(AVG(r_multiple), 2) AS r_multiple_avg
        FROM trades
        WHERE year = YEAR(CURRENT_DATE)
          AND month = MONTH(CURRENT_DATE)
          AND day = DAY(CURRENT_DATE)
    )
    SELECT
        c.pares_evaluados,
        c.pares_operables,
        c.pct_operables AS pct_pasan_contexto,
        o.total_oportunidades,
        o.estrategias_activas,
        o.pares_con_oportunidad,
        o.con_confluencia,
        r.trades_totales,
        r.ganadoras,
        r.pnl_neto_usd,
        r.r_multiple_avg
    FROM contexto c, ops o, resultado r;
  SQL
}

resource "aws_athena_named_query" "estrategias_degradadas" {
  name        = "10_deteccion_estrategias_degradadas"
  description = "Alerta si alguna estrategia tiene winrate bajo o R múltiple negativo (14d)"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    SELECT
        strategy,
        COUNT(*) AS trades,
        ROUND(AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) AS winrate_pct,
        ROUND(AVG(r_multiple), 2) AS r_multiple_promedio,
        ROUND(SUM(net_pnl), 2) AS pnl_total,
        CASE
            WHEN AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END) < 0.30 THEN 'WINRATE_BAJO'
            WHEN AVG(r_multiple) < 1.0 THEN 'R_NEGATIVO'
            ELSE 'OK'
        END AS estado
    FROM trades
    WHERE year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -14, CURRENT_DATE))
    GROUP BY strategy
    HAVING COUNT(*) >= 5
    ORDER BY r_multiple_promedio ASC;
  SQL
}
