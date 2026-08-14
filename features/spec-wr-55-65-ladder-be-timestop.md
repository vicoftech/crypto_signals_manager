# SPEC — Mejoras de winrate (objetivo 55–65% WR) y PnL positivo

**Fecha:** 2026-08-14  
**Estado:** implementada (2026-08-14)  
**Cohorte de referencia:** últimas 95 ops `live_test` (2026-07-14 → 2026-08-14)  
**Baseline:** WR **37.9%**, PnL **−11.07 USD**, TP1+ **~27%**, TP3+ **4.2%**, avg progress a TP1 en SL **~40%**

---

## 1. Objetivo

Llevar el sistema live_test a:

| KPI | Baseline (95 ops) | Target (próximas ≥50 ops post-deploy) |
|-----|-------------------|--------------------------------------|
| Winrate | 37.9% | **55–65%** (máx. 35–45% perdedoras) |
| PnL neto cohorte | −11.07 | **> 0** |
| % que activan TP1+ | ~27% | **≥ 50%** |
| Avg loss / risk_usd | ~1.24× | **≤ 1.15×** |
| TP3+ | 4.2% | **≥ 8%** (secundario; no es el KPI principal) |

**Principio:** el WR no lo sube “forzar TP3”. Lo sube **activar la escalera antes** (TP1 más cerca + BE anticipado) y **abrir menos basura** (filtros / time-stop / cooldown).

---

## 2. Diagnóstico (por qué falla hoy)

1. TP1 está a **1.5R** (`TP_R_STEP=1.5` + hardcode en `simple_long_opportunity`).
2. En SL, el precio solo recorre ~**40%** del camino a TP1 → la escalera casi no se enciende.
3. Sin TP1, `active_stop` sigue en SL inicial → salida = perdedora plena (~−1.47 USD vs risk ~1.18).
4. Duraciones largas (avg **19.5 h**, max **~104 h**) dejan zombies que terminan en SL o MANUAL.
5. Payoff actual (~1.43) solo necesita ~41% WR para breakeven; el problema es WR, no payoff.

---

## 3. Alcance

### In scope (P0 + P1)

- A. Escalera: TP1 a **1.0R**, pasos de **1.0R** (TP2=2R, TP3=3R, …).
- B. Break-even anticipado a **0.7R** (antes de TP1).
- C. Time-stop si no hay progreso hacia TP1.
- D. Cooldown post-SL más largo.
- E. Env/Terraform + tests + reset contable post-deploy.
- F. Métricas de seguimiento en logs / resumen.

### Out of scope (esta spec)

- Reescribir estrategias ORB/RangeBreakout desde cero.
- Cambiar `risk_pct` / sizing de capital.
- Mainnet.
- Re-evaluación automática de pares (ya rechazada antes); pausas manuales/script OK.

### P2 (opcional, misma PR o follow-up)

- Endurecer filtros RangeBreakout (volumen / contexto).
- Script de pausa de pares con WR&lt;40% en cohorte actual.

---

## 4. CAMBIO A — Escalera TP a pasos de 1.0R

### Problema

`tp_price_for_level` usa `settings.tp_r_step` (hoy 1.5), pero `simple_long_opportunity` **hardcodea** 1.5 / 3.0 / 4.5 y no lee settings → inconsistencia y TP1 lejos.

### Diseño

| Nivel | Precio (nuevo) | Antes |
|-------|----------------|-------|
| TP1 | entry + **1.0R** | 1.5R |
| TP2 | entry + **2.0R** | 3.0R |
| TP3 | entry + **3.0R** | 4.5R |
| TPn | entry + **n × 1.0R** | n × 1.5R |

Comportamiento Caso 1 **sin cambios**: al tocar TPn, `active_stop_price = TPn`; salida única si precio ≤ active_stop → `SL_TPn`.

### Archivos

| Archivo | Cambio |
|---------|--------|
| `src/config.py` | Default `TP_R_STEP` **1.0** (env override). |
| `infra/terraform/app/main.tf` | `TP_R_STEP = "1.0"`. |
| `src/strategies/base.py` | `simple_long_opportunity`: TP1/2/3 vía `tp_price_for_level` / `settings.tp_r_step` (eliminar hardcode 1.5/3/4.5). |
| `src/core/tp_ladder.py` | Docstring actualizar (nivel 1 = 1.0R). Sin cambio de lógica si ya usa `tp_r_step`. |
| Tests que asuman 1.5R | Actualizar expectativas a 1.0R. |

### Pseudocódigo (`simple_long_opportunity`)

```python
from src.core.tp_ladder import tp_price_for_level

# ...
return Opportunity(
    ...
    tp1_price=tp_price_for_level(entry, sl, 1),
    tp2_price=tp_price_for_level(entry, sl, 2),
    tp3_price=tp_price_for_level(entry, sl, 3),
    ...
)
```

### Criterio de aceptación A

- [ ] Con `TP_R_STEP=1.0`, una entrada 100 / SL 99 → TP1=101, TP2=102, TP3=103.
- [ ] Trades nuevos en Dynamo persisten `tp1_price` coherente con 1.0R.
- [ ] Trades **ya abiertos** con TP a 1.5R: **no recalcular** precios históricos; solo nuevas entradas usan 1.0R (o documentar migración explícita si se decide backfill).
- [ ] Tests unitarios de ladder + `simple_long_opportunity` verdes.

---

## 5. CAMBIO B — Break-even anticipado a 0.7R

### Problema

Hoy el stop solo sube al tocar un TPn. Muchos trades llegan a ~0.5–0.8R y luego van a SL completo.

### Diseño

Mientras `ladder_level == 0` (aún no hubo TP1):

1. Calcular `R = entry - sl_price`.
2. Si `current_price >= entry + BE_R_THRESHOLD * R` (default **0.7**):
   - Set `active_stop_price = entry` (o `entry * (1 - BE_FEE_BUFFER_PCT)`, default **0.0005** = 0.05% para fees).
   - Set flag `breakeven_armed = True` (idempotente).
3. Si luego `current_price <= active_stop_price` y `breakeven_armed` y `ladder_level == 0`:
   - Cerrar con reason **`BE`** (o `SL_BE`) — cuenta como **no perdedora** si net_pnl ≥ 0; si net por fees &lt; 0, sigue siendo pérdida chica (mejor que −1R).

Tras TP1, la escalera normal manda (`active_stop` = TPn); BE no vuelve a bajar el stop.

### Live / exchange

En `position_monitor` / `live_exit`:

- Al armar BE, llamar `sync_ladder_stop_on_exchange` con el nuevo floor (igual que al subir escalera).
- Si el sync falla: persistir en Dynamo igual; el monitor cierra por precio (grace ya existente).

### Env

| Variable | Default | Descripción |
|----------|---------|-------------|
| `BE_R_THRESHOLD` | `0.7` | Múltiplo de R para armar BE |
| `BE_FEE_BUFFER_PCT` | `0.0005` | Stop ligeramente bajo entrada |
| `BE_ENABLED` | `true` | Feature flag |

### Archivos

| Archivo | Cambio |
|---------|--------|
| `src/config.py` | Nuevos settings. |
| `src/core/tp_ladder.py` | En `evaluate_ladder_trade`, rama BE antes del while de TPn. |
| `src/lambdas/position_monitor/handler.py` | Sync exchange al detectar `breakeven_armed` nuevo; mapear reason `BE` a notificaciones. |
| `infra/terraform/app/main.tf` | Env vars. |
| `tests/test_*.py` | Casos: arma BE a 0.7R; cierra BE; no baja stop tras TP1. |

### Pseudocódigo (ladder)

```python
be_thr = float(settings.be_r_threshold)  # 0.7
r = risk_amount(entry, sl)
if level <= 0 and r > 0 and not trade.get("breakeven_armed"):
    if current_price >= entry + be_thr * r:
        be_stop = entry * (1.0 - float(settings.be_fee_buffer_pct))
        updates["active_stop_price"] = be_stop
        updates["breakeven_armed"] = True
        # floor para cierre inmediato si ya está debajo (raro)
        active_stop = be_stop

# cierre: si level==0 y breakeven_armed y price <= active_stop → "BE"
```

### Criterio de aceptación B

- [ ] Precio sube a 0.7R → `breakeven_armed=True`, stop ≈ entry.
- [ ] Precio vuelve a entry → cierre `BE` con |net_pnl| << risk_usd.
- [ ] Precio toca TP1 sin haber armado BE → escalera normal, sin conflicto.
- [ ] Feature flag `BE_ENABLED=false` desactiva el comportamiento.

---

## 6. CAMBIO C — Time-stop sin progreso

### Problema

Trades abiertos muchas horas sin acercarse a TP1 terminan en SL o MANUAL.

### Diseño

En cada ciclo del monitor, para trades live/sim con `ladder_level == 0` y no `breakeven_armed`:

1. `age_hours = now - started_at`.
2. `progress = (MFE - entry) / R` (usar `max_favorable_excursion`).
3. Si `age_hours >= TIME_STOP_HOURS` (default **5**) **y** `progress < TIME_STOP_MIN_R` (default **0.3**):
   - Cerrar con reason **`TIME_STOP`**.
   - Live: intentar MARKET sell (mismos paths / fallos duros que hoy).

No aplicar time-stop si ya hubo TP1 o BE armado.

### Env

| Variable | Default |
|----------|---------|
| `TIME_STOP_HOURS` | `5` |
| `TIME_STOP_MIN_R` | `0.3` |
| `TIME_STOP_ENABLED` | `true` |

### Archivos

- `src/config.py`, Terraform env.
- `src/core/tp_ladder.py` **o** helper en `position_monitor` / `simulator` (preferible función pura `should_time_stop(trade, now) -> bool` en `src/core/exits.py` o `tp_ladder.py` para testear).
- Notificación Telegram: una línea en digest o update corto `⏱ TIME_STOP {pair}`.

### Criterio de aceptación C

- [ ] Trade 5h+, MFE &lt; 0.3R, level 0 → `TIME_STOP`.
- [ ] Trade 5h+, MFE ≥ 0.3R → no time-stop.
- [ ] Trade con TP1 hit → no time-stop.

---

## 7. CAMBIO D — Cooldown post-SL

### Diseño

- Subir `COOLDOWN_MINUTES` global de **45 → 90** (Terraform + default config), **o**
- Cooldown específico tras `close_reason in {SL, TIME_STOP}`: **120 min** solo para ese `(pair, strategy)`.

Preferencia: **90 global** + si es fácil, 120 tras SL (estado en cooldown table ya existente).

### Archivos

- `infra/terraform/app/main.tf` → `COOLDOWN_MINUTES = "90"`.
- Opcional: `src/lambdas/position_monitor` al cerrar SL marca cooldown extendido; `scanner` ya respeta `cooldown.in_cooldown`.

### Criterio de aceptación D

- [ ] Tras SL, el mismo par+estrategia no reabre antes del cooldown configurado.

---

## 8. CAMBIO E — Reset contable post-deploy

Tras merge + deploy exitoso:

1. Ejecutar reset de cohorte (mismo patrón que `apply_quality_matrix_20260713.py --no-reset` no; sí reset):
   - `accounting_epoch_started_at = now`
   - `capital_inicial_live_test = capital_total actual`
2. Confirmar **0** cierres en nueva cohorte y **0** (o solo nuevos) opens.
3. Documentar en nota de release / Telegram: “Cohorte WR-target desde &lt;ISO&gt;”.

No mezclar métricas pre/post en `/resumen`.

---

## 9. CAMBIO F — Observabilidad

### Logs (position_monitor)

Por trade cerrado, log estructurado (o campos ya existentes):

- `close_reason`, `ladder_level`, `breakeven_armed`, `mfe_r`, `duration_min`, `risk_usd`, `net_pnl_usd`.

### Telegram `/rendimiento` o `/resumen` (mínimo)

Línea agregada en cohorte:

```
WR=xx% | TP1+=yy% | BE=n | TIME_STOP=n | SL=n | expectancy=$z
```

Si el cambio de webhook es grande, deferir a P2 y usar script offline `scripts/analyze_cohort_wr.py` (opcional en esta spec).

---

## 10. Orden de implementación

1. **A** — TP_R_STEP 1.0 + unificar `simple_long_opportunity` (fundación).
2. **B** — BE 0.7R + sync exchange.
3. **C** — Time-stop.
4. **D** — Cooldown 90.
5. Tests + deploy Terraform/Lambda.
6. **E** — Reset contable.
7. Medir ≥50 trades o 14 días.

No implementar P2 hasta validar A–D en cohorte nueva.

---

## 11. Tests requeridos

| Test | Qué valida |
|------|------------|
| `test_tp_step_one_r` | TP niveles con step 1.0 |
| `test_opportunity_uses_settings_tp_step` | No hardcode 1.5 |
| `test_breakeven_arms_at_0_7r` | Flag + stop |
| `test_breakeven_exit_reason` | Cierre `BE` |
| `test_breakeven_does_not_lower_after_tp1` | Monotonicidad del stop |
| `test_time_stop_triggers` | Edad + progress |
| `test_time_stop_skipped_if_progress` | No falso positivo |
| Regresión ladder Caso 1 | SL_TP1/TP2 como hoy |

---

## 12. Plan de medición (éxito / rollback)

### Éxito (tras ≥50 cierres en cohorte nueva)

- WR ∈ **[55%, 65%]** **o** al menos WR ≥ **50%** y PnL &gt; 0 con TP1+ ≥ 45%.
- Avg loss / risk ≤ 1.15.
- Sin regresión de spam Telegram (digests de exit-fail intactos).

### Rollback parcial

| Síntoma | Acción |
|---------|--------|
| WR sube pero avg win colapsa y PnL &lt; 0 | Subir TP1 a **1.2R** (`TP_R_STEP=1.2`) sin quitar BE |
| Demasiados TIME_STOP | Subir `TIME_STOP_HOURS` a 8 o `TIME_STOP_MIN_R` a 0.2 |
| BE demasiado temprano (ruido) | `BE_R_THRESHOLD=0.85` |
| Falla sync exchange en BE | `BE_ENABLED=false` temporal; Dynamo-only stop |

### Rollback total

Revertir commit(s) de esta spec y `TP_R_STEP=1.5`; nuevo accounting epoch para no contaminar.

---

## 13. Riesgos

| Riesgo | Mitigación |
|--------|------------|
| Más wins chicos, menos “home runs” | Aceptable; KPI es WR + PnL, no TP3 |
| BE en testnet con slippage negativo | `BE_FEE_BUFFER_PCT` |
| Time-stop cierra trades que habrían ido a TP3 | Threshold 0.3R / 5h; tunear con datos |
| Trades viejos con TP 1.5R mezclados | Solo nuevas entradas; reset epoch |

---

## 14. Checklist de PR

- [ ] Código A–D + tests verdes
- [ ] Terraform env actualizado
- [ ] Sin hardcode 1.5/3.0/4.5 en `base.py`
- [ ] Docstring ladder actualizado
- [ ] Nota de deploy: reset contable post-CI
- [ ] No incluir `infra/audit/tfplan`

---

## 15. Resumen ejecutivo

Para WR 55–65% y PnL positivo:

1. **TP1 a 1.0R** (más trades encienden escalera).  
2. **BE a 0.7R** (salvar almost-winners).  
3. **Time-stop 5h / 0.3R** (matar zombies).  
4. **Cooldown 90m** (menos revenge trading).  
5. **Nueva cohorte** y medir ≥50 ops.

TP3 sigue siendo bonus; el interruptor del WR es **activar protección antes**.
