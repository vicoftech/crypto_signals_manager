# CURSOR PROMPT — Fix crítico: gestión de capital en el simulador

## Contexto y urgencia

El simulador tiene 4 bugs críticos en la gestión de capital que están
produciendo resultados irreales. El sistema muestra -$1,300 sobre un
capital inicial de $1,183, lo que es imposible con riesgo del 5% por
operación correctamente implementado.

Estos bugs deben corregirse ANTES de continuar con cualquier otra funcionalidad.
Son bugs de lógica financiera, no de UI.

---

## ARQUITECTURA DEL CAPITAL SIMULADO

Antes de implementar los fixes, entender el modelo correcto:

```
Capital total simulado = capital inicial + P&L cerrado acumulado
Capital disponible     = capital total - capital bloqueado en posiciones abiertas
Capital bloqueado      = suma de position_size_usd de todas las posiciones OPEN

Riesgo por operación   = capital_disponible × RISK_PER_TRADE_PCT
Position size          = riesgo / sl_pct
SL en simulación       = precio de entrada - (riesgo / position_size × entrada)

Ejemplo correcto:
  Capital total:      $1,183
  Posición abierta:   $11,800 (position_size)
  Capital bloqueado:  $11,800
  Capital disponible: $1,183 - $11,800 → NEGATIVO → no abrir nueva posición

El modelo correcto es:
  Capital disponible = capital total - suma(risk_usd de posiciones OPEN)
  No se bloquea el position_size completo, se bloquea el riesgo máximo
  porque en spot el peor caso es perder el riesgo definido (si el SL funciona)
```

---

## FIX 1 — Capital dinámico: `/capital` muestra siempre el inicial

**Archivo:** `src/core/state.py` y `src/lambdas/webhook/handler.py`

**Problema:**
```python
# Actual — lee siempre el valor estático de ConfigTable
capital = config_table.get("capital")  # siempre $1,183
```

**Causa:** El capital no se actualiza en ConfigTable cuando se cierran trades.

**Fix — crear función `get_capital_actual()`:**

```python
# src/core/state.py

async def get_capital_actual() -> dict:
    """
    Calcula el capital real actual del simulador:
    capital_inicial + suma de P&L de todos los trades cerrados
    
    Retorna:
    {
        "capital_inicial":    1183.00,
        "pnl_cerrado":        +312.45,   # suma de net_pnl de trades CLOSED
        "capital_total":      1495.45,   # capital_inicial + pnl_cerrado
        "capital_bloqueado":   177.45,   # suma de risk_usd de trades OPEN
        "capital_disponible": 1318.00,   # capital_total - capital_bloqueado
        "posiciones_abiertas": 3,
        "drawdown_actual":    0.0,       # si capital_total < capital_inicial
    }
    """
    # 1. Leer capital inicial de ConfigTable (nunca cambia)
    capital_inicial = await get_config("capital_inicial")

    # 2. Sumar P&L neto de todos los trades cerrados (mode=SIM, status=CLOSED)
    trades_cerrados = await trades_manager.get_closed_sim_trades()
    pnl_cerrado = sum(t.net_pnl_usd for t in trades_cerrados)

    # 3. Capital total actual
    capital_total = capital_inicial + pnl_cerrado

    # 4. Capital bloqueado = suma de risk_usd de posiciones OPEN
    # (no el position_size completo — solo el riesgo máximo comprometido)
    trades_abiertos = await trades_manager.get_open_sim_trades()
    capital_bloqueado = sum(t.risk_usd for t in trades_abiertos)

    # 5. Capital disponible para nuevas operaciones
    capital_disponible = capital_total - capital_bloqueado

    # 6. Drawdown actual
    drawdown_pct = 0.0
    if capital_total < capital_inicial:
        drawdown_pct = (capital_inicial - capital_total) / capital_inicial

    return {
        "capital_inicial":     round(capital_inicial, 2),
        "pnl_cerrado":         round(pnl_cerrado, 2),
        "capital_total":       round(capital_total, 2),
        "capital_bloqueado":   round(capital_bloqueado, 2),
        "capital_disponible":  round(capital_disponible, 2),
        "posiciones_abiertas": len(trades_abiertos),
        "drawdown_actual":     round(drawdown_pct, 4),
    }
```

**Actualizar el comando `/capital`:**

```python
# src/lambdas/webhook/handler.py

async def handle_capital_command() -> str:
    cap = await get_capital_actual()

    pnl_emoji = "📈" if cap["pnl_cerrado"] >= 0 else "📉"
    dd_texto = f"⚠️ Drawdown: {cap['drawdown_actual']:.1%}" if cap["drawdown_actual"] > 0 else "✅ Sin drawdown"

    return f"""
💼 ESTADO DEL CAPITAL SIMULADO

💰 Capital inicial:    ${cap['capital_inicial']:,.2f}
{pnl_emoji} P&L cerrado:       ${cap['pnl_cerrado']:+,.2f}
━━━━━━━━━━━━━━━━━━━━━━━
📊 Capital total:      ${cap['capital_total']:,.2f}

🔒 Bloqueado ({cap['posiciones_abiertas']} ops): -${cap['capital_bloqueado']:,.2f}
✅ Disponible:         ${cap['capital_disponible']:,.2f}

{dd_texto}
Riesgo próxima op:    ${cap['capital_total'] * 0.05:,.2f}  (5%)
"""
```

---

## FIX 2 — Riesgo dinámico: siempre usa el mismo monto

**Archivo:** `src/core/calculator.py` y `src/lambdas/scanner/handler.py`

**Problema:**
```python
# Actual — usa capital estático de config
capital = settings.capital_total  # siempre $1,183
risk_usd = capital * RISK_PER_TRADE_PCT  # siempre $59.15
```

**Fix — calcular riesgo sobre capital actual:**

```python
# src/core/calculator.py

async def calculate_position_with_current_capital(
    opportunity: Opportunity,
    risk_pct: float = 0.05
) -> Opportunity:
    """
    Recalcula el riesgo y tamaño de posición usando el capital actual,
    no el capital inicial estático.
    """
    # Obtener capital actual en tiempo real
    cap = await get_capital_actual()
    capital_total = cap["capital_total"]
    capital_disponible = cap["capital_disponible"]

    # Verificar que hay capital disponible
    if capital_disponible <= 0:
        raise InsufficientCapitalError(
            f"Capital disponible: ${capital_disponible:.2f}. "
            f"No se puede abrir nueva posición."
        )

    # Riesgo sobre capital TOTAL actual (no disponible)
    # El % de riesgo siempre se calcula sobre el total, no sobre el disponible
    risk_usd = capital_total * risk_pct

    # Verificar que el riesgo no supera el capital disponible
    if risk_usd > capital_disponible:
        # Ajustar riesgo al capital disponible
        risk_usd = capital_disponible
        logger.warning(
            f"[CAPITAL] Riesgo ajustado a capital disponible: "
            f"${risk_usd:.2f} (original: ${capital_total * risk_pct:.2f})"
        )

    # Recalcular position_size con el riesgo actual
    sl_pct = (opportunity.entry_price - opportunity.sl_price) / opportunity.entry_price
    if sl_pct <= 0:
        raise ValueError(f"SL inválido: sl_pct={sl_pct}")

    position_size_usd = risk_usd / sl_pct

    # Actualizar la oportunidad con los valores correctos
    opportunity.risk_usd          = round(risk_usd, 2)
    opportunity.position_size_usd = round(position_size_usd, 2)
    opportunity.capital_at_open   = round(capital_total, 2)

    # Recalcular TPs con el nuevo entry (por si el drift cambió el entry)
    risk_price = opportunity.entry_price - opportunity.sl_price
    opportunity.tp1_price = round(opportunity.entry_price + risk_price * 1.5, 8)
    opportunity.tp2_price = round(opportunity.entry_price + risk_price * 3.0, 8)

    return opportunity
```

**En el scanner, antes de abrir cualquier posición:**

```python
# src/lambdas/scanner/handler.py

try:
    opportunity = await calculate_position_with_current_capital(
        opportunity, risk_pct=settings.risk_per_trade_pct
    )
except InsufficientCapitalError as e:
    logger.warning(f"[CAPITAL] {pair} — {e}")
    await telegram_client.send_capital_insuficiente(pair, opportunity)
    continue  # no abrir la posición
```

---

## FIX 3 — Bloqueo de capital: no verifica capital disponible

**Archivo:** `src/core/trades_manager.py` y `src/lambdas/scanner/handler.py`

**Problema:**
```python
# Actual — abre posiciones sin verificar capital disponible
# Resultado: puede tener 10 posiciones abiertas simultáneamente
# con capital total de $1,183 y riesgo acumulado de $590
trade = await open_sim_trade(opportunity)  # sin verificar capital
```

**Fix — verificación de capital antes de abrir:**

```python
# src/core/trades_manager.py

class InsufficientCapitalError(Exception):
    pass

async def can_open_trade(risk_usd: float) -> tuple[bool, str]:
    """
    Verifica si hay capital disponible para abrir una nueva posición.
    
    Retorna (puede_abrir: bool, razon: str)
    """
    cap = await get_capital_actual()

    # 1. Capital disponible suficiente
    if cap["capital_disponible"] < risk_usd:
        return False, (
            f"Capital insuficiente. "
            f"Disponible: ${cap['capital_disponible']:.2f} | "
            f"Requerido: ${risk_usd:.2f}"
        )

    # 2. No superar el máximo de posiciones concurrentes
    if cap["posiciones_abiertas"] >= settings.max_concurrent_open:
        return False, (
            f"Máximo de posiciones alcanzado: "
            f"{cap['posiciones_abiertas']}/{settings.max_concurrent_open}"
        )

    # 3. El capital total no está en drawdown extremo
    if cap["drawdown_actual"] >= 0.25:
        return False, (
            f"Drawdown de seguridad alcanzado: "
            f"{cap['drawdown_actual']:.1%}. "
            f"Pausar operaciones y revisar en Athena."
        )

    return True, "OK"


async def open_sim_trade(opportunity: Opportunity) -> Trade:
    """
    Abre una posición simulada verificando capital disponible primero.
    """
    puede, razon = await can_open_trade(opportunity.risk_usd)

    if not puede:
        raise InsufficientCapitalError(razon)

    # Registrar el trade con capital_at_open correcto
    trade = Trade(
        trade_id          = str(uuid.uuid4()),
        mode              = "SIM",
        status            = "OPEN",
        pair              = opportunity.pair,
        strategy          = opportunity.strategy,
        entry_price       = opportunity.entry_price,
        sl_initial        = opportunity.sl_price,
        sl_final          = opportunity.sl_price,
        risk_usd          = opportunity.risk_usd,
        position_size_usd = opportunity.position_size_usd,
        capital_at_open   = opportunity.capital_at_open,  # capital TOTAL al abrir
        # ... resto de campos
    )

    await dynamodb.put_item(TableName="TradesTable", Item=trade.to_dynamo())
    return trade
```

**Mensaje cuando no hay capital disponible:**

```
⚠️ SIN CAPITAL DISPONIBLE

📊 BTC/USDT  |  EMAPullback
Capital total:      $1,247.50
Capital bloqueado:  $1,195.00  (3 posiciones abiertas)
Capital disponible: $52.50
Riesgo requerido:   $62.38

→ Señal registrada pero no simulada.
  Esperá que cierren posiciones abiertas.
```

---

## FIX 4 — Pérdidas mayores al riesgo definido

**Archivo:** `src/core/simulator.py`

**Problema — 3 causas posibles que hay que corregir todas:**

### Causa A: El simulador no respeta el precio del SL (usa precio del check)

```python
# INCORRECTO — usa el precio actual aunque haya pasado el SL
if current_price <= trade.sl_initial:
    close_trade(trade, current_price, "SL")  # puede ser mucho menor que el SL
    # Si SL = $73,650 y current_price en el check = $73,100
    # La pérdida es sobre $73,100, no sobre $73,650
```

```python
# CORRECTO — siempre cerrar al precio del SL, no al precio del check
if current_price <= trade.sl_initial:
    # En simulación, la orden stop se ejecuta AL PRECIO DEL SL
    # (en realidad puede haber slippage, pero eso lo agregamos aparte)
    sl_execution_price = trade.sl_initial * (1 - SL_SLIPPAGE.get(trade.pair, 0.0002))
    close_trade(trade, sl_execution_price, "SL")
```

### Causa B: El trailing SL no se inicializa correctamente

```python
# INCORRECTO — trailing_sl_final puede quedar en 0 o en un valor incorrecto
if trade.tp1_hit:
    trade.trailing_sl_final = current_price * (1 - TRAILING_STEP_PCT)
    # Si esto se ejecuta múltiples veces en el mismo ciclo,
    # puede resetear el trailing SL a un valor menor que el de entrada
```

```python
# CORRECTO — el trailing SL solo sube, nunca baja
def update_trailing_sl(trade: Trade, current_price: float) -> bool:
    """
    Actualiza el trailing SL solo si el nuevo valor es MAYOR al actual.
    Retorna True si se actualizó.
    """
    nuevo_trailing_sl = current_price * (1 - TRAILING_STEP_PCT)
    
    # El trailing SL nunca puede ser menor al precio de entrada (breakeven)
    nuevo_trailing_sl = max(nuevo_trailing_sl, trade.entry_price)
    
    # Solo actualizar si el nuevo valor es mayor al actual
    if nuevo_trailing_sl > trade.trailing_sl_final:
        trade.trailing_sl_final = nuevo_trailing_sl
        return True
    return False
```

### Causa C: Múltiples posiciones con capital no bloqueado (la más probable)

```python
# Verificar en DynamoDB cuántos trades OPEN hay ahora mismo
# y cuánto capital está comprometido
# Si hay 5 posiciones abiertas con risk_usd = $59 cada una:
# capital_bloqueado = $295
# Si todas pierden → pérdida real = $295, no $59
# Eso no es un bug de pérdida excesiva POR operación
# Es un bug de múltiples operaciones simultáneas sin control
```

### Fix completo del simulador:

```python
# src/core/simulator.py

# Slippage al ejecutar SL (el stop ejecuta levemente peor que el nivel)
SL_EXECUTION_SLIPPAGE = {
    "BTCUSDT": 0.0002,   # 0.02% peor que el SL
    "ETHUSDT": 0.0002,
    "SOLUSDT": 0.0005,
    "XRPUSDT": 0.0004,
    "BNBUSDT": 0.0003,
}

def evaluate(trade: Trade, current_price: float) -> None:
    """
    Evalúa el estado de una posición abierta.
    Todas las pérdidas se calculan sobre el precio del SL, no sobre
    el precio del check — igual que funcionaría una orden stop real.
    """

    # ── 1. Actualizar MFE y MAE ──────────────────────────────────
    if current_price > trade.max_favorable_excursion:
        trade.max_favorable_excursion = current_price
        trade.max_favorable_excursion_at = datetime.utcnow().isoformat()

    if current_price < trade.max_adverse_excursion:
        trade.max_adverse_excursion = current_price
        trade.max_adverse_excursion_at = datetime.utcnow().isoformat()

    # ── 2. Calcular P&L circunstancial ──────────────────────────
    pnl_bruto = (current_price - trade.entry_price) / trade.entry_price * trade.position_size_usd
    comision_salida = trade.position_size_usd * 0.001
    trade.pnl_usd = round(pnl_bruto - trade.commission_usd - comision_salida, 2)

    # ── 3. Evaluar SL ────────────────────────────────────────────
    sl_activo = trade.trailing_sl_final if trade.trailing_activated else trade.sl_initial

    if current_price <= sl_activo:
        # SIEMPRE cerrar al precio del SL con slippage mínimo
        # NO al precio actual del check (que puede ser mucho peor)
        slip = SL_EXECUTION_SLIPPAGE.get(trade.pair, 0.0003)
        precio_ejecucion = sl_activo * (1 - slip)

        razon = "TRAILING_SL" if trade.trailing_activated else "SL"
        close_trade(trade, precio_ejecucion, razon)
        return

    # ── 4. Alerta zona de peligro (precio cerca del SL) ─────────
    distancia_sl = (current_price - sl_activo) / trade.entry_price
    if distancia_sl < 0.003 and not trade.danger_zone_notified:
        notify_danger_zone(trade, current_price, sl_activo)
        trade.danger_zone_notified = True

    # ── 5. Evaluar TP1 ───────────────────────────────────────────
    if not trade.tp1_hit and current_price >= trade.tp1_price:
        trade.tp1_hit = True
        trade.tp1_hit_at = datetime.utcnow().isoformat()
        trade.trailing_activated = True
        # Inicializar trailing SL en el precio de entrada (breakeven)
        trade.trailing_sl_final = trade.entry_price
        notify_tp1_reached(trade, current_price)

    # ── 6. Actualizar trailing (solo si está activo) ─────────────
    if trade.trailing_activated:
        updated = update_trailing_sl(trade, current_price)
        if updated:
            trade.trailing_updates_count += 1
            notify_trailing_update(trade, current_price)

    # ── 7. Evaluar TP2 ───────────────────────────────────────────
    if trade.tp1_hit and current_price >= trade.tp2_price:
        close_trade(trade, trade.tp2_price, "TP2")
        return

    # ── 8. Persistir estado actualizado ─────────────────────────
    await trades_manager.update_trade(trade)


def update_trailing_sl(trade: Trade, current_price: float) -> bool:
    """
    El trailing SL solo sube, nunca baja.
    Nunca puede ser menor al precio de entrada (breakeven garantizado).
    """
    nuevo_sl = current_price * (1 - TRAILING_STEP_PCT)

    # Piso: nunca por debajo de la entrada (protege el capital)
    nuevo_sl = max(nuevo_sl, trade.entry_price)

    if nuevo_sl > trade.trailing_sl_final:
        trade.trailing_sl_final = round(nuevo_sl, 8)
        return True
    return False


def close_trade(trade: Trade, exit_price: float, close_reason: str) -> None:
    """
    Cierra un trade calculando P&L neto correctamente.
    La pérdida máxima está limitada al risk_usd definido al abrir.
    """
    # P&L bruto basado en el precio de cierre real
    pnl_bruto = (exit_price - trade.entry_price) / trade.entry_price * trade.position_size_usd

    # Comisiones totales (entrada + salida)
    commission = trade.position_size_usd * 0.001 * 2  # 0.1% × 2
    pnl_neto = pnl_bruto - commission

    # VALIDACIÓN DE SEGURIDAD: la pérdida no puede superar el riesgo definido
    # Si por algún bug el precio de cierre es peor que el SL,
    # limitar la pérdida al risk_usd original
    if pnl_neto < -trade.risk_usd:
        logger.error(
            f"[CAPITAL] ⚠️ Pérdida {pnl_neto:.2f} supera riesgo {trade.risk_usd:.2f} "
            f"en {trade.pair}. Limitando al riesgo máximo."
        )
        pnl_neto = -trade.risk_usd

    trade.exit_price       = round(exit_price, 8)
    trade.close_reason     = close_reason
    trade.net_pnl_usd      = round(pnl_neto, 2)
    trade.gross_pnl_usd    = round(pnl_bruto, 2)
    trade.commission_usd   = round(commission, 2)
    trade.r_multiple       = round(pnl_neto / trade.risk_usd, 2)
    trade.rr_ratio_actual  = round(
        (exit_price - trade.entry_price) / (trade.entry_price - trade.sl_initial), 2
    ) if close_reason not in ("SL", "TRAILING_SL") else -1.0
    trade.ended_at         = datetime.utcnow().isoformat()
    trade.duration_minutes = int(
        (datetime.utcnow() - datetime.fromisoformat(trade.started_at)).total_seconds() / 60
    )
    trade.status = "CLOSED"

    # Actualizar estadísticas del par
    asyncio.create_task(trades_manager.update_pair_sim_stats(trade.pair, trade))
    asyncio.create_task(trades_manager.save_closed_trade(trade))
```

---

## FIX adicional — Drawdown de seguridad automático

Si el capital cae más del 25% del inicial, pausar automáticamente
todas las operaciones y notificar:

```python
# src/core/state.py

DRAWDOWN_LIMIT = 0.25  # 25% — pausa automática

async def check_drawdown_limit() -> bool:
    """
    Verifica si el drawdown superó el límite de seguridad.
    Si sí, pausa el sistema automáticamente.
    Retorna True si el sistema está pausado por drawdown.
    """
    cap = await get_capital_actual()

    if cap["drawdown_actual"] >= DRAWDOWN_LIMIT:
        # Pausar el sistema
        await set_config("paused", "true")
        await set_config("paused_reason", "drawdown_limit")

        await telegram_client.send_message(f"""
🚨 SISTEMA PAUSADO AUTOMÁTICAMENTE

⚠️ Drawdown límite alcanzado: {cap['drawdown_actual']:.1%}
Capital inicial: ${cap['capital_inicial']:,.2f}
Capital actual:  ${cap['capital_total']:,.2f}
Pérdida:         ${cap['capital_inicial'] - cap['capital_total']:,.2f}

El sistema no generará nuevas simulaciones.
Revisá los datos en Athena antes de reanudar.

Comandos:
/capital       → ver estado del capital
/historial     → ver últimas operaciones
/reanudar      → reanudar manualmente (con precaución)
""")
        return True
    return False
```

Llamar `check_drawdown_limit()` en el scanner antes de procesar cualquier señal:

```python
# src/lambdas/scanner/handler.py — al inicio del handler

if await check_drawdown_limit():
    logger.warning("[SCANNER] Sistema pausado por drawdown. Saltando ciclo.")
    return
```

---

## ConfigTable — nuevas claves requeridas

```python
# Agregar estas claves en ConfigTable si no existen
{
    "key": "capital_inicial",
    "value": "1183.0"   # NUNCA se modifica — es el baseline
}

{
    "key": "capital_total",
    "value": "1183.0"   # se actualiza con cada trade cerrado
    # DEPRECAR este campo — calcularlo dinámicamente desde los trades
}

# El /capital comando que el operador usa para actualizar el capital
# ahora actualiza "capital_inicial" SOLO si no hay trades registrados
# Si ya hay trades, rechaza el cambio con un mensaje explicativo
```

---

## Comando `/reset_capital` — para empezar de cero

```python
# Cuando el operador quiere resetear la simulación completamente

async def handle_reset_capital_command(nuevo_capital: float) -> str:
    """
    Cierra todas las posiciones abiertas al precio actual,
    limpia el historial de simulación y reinicia el capital.
    Solo disponible si NO hay posiciones abiertas.
    """
    trades_abiertos = await trades_manager.get_open_sim_trades()

    if trades_abiertos:
        return (
            f"❌ No se puede resetear con posiciones abiertas. "
            f"Hay {len(trades_abiertos)} posiciones abiertas. "
            f"Esperá que cierren o cerralas manualmente."
        )

    await set_config("capital_inicial", str(nuevo_capital))
    # No borrar el historial — marcarlo como "sesión anterior"
    await set_config("sim_session", str(int(datetime.utcnow().timestamp())))

    return f"✅ Capital reiniciado a ${nuevo_capital:,.2f}. Nueva sesión iniciada."
```

---

## Tests requeridos — `tests/test_capital_management.py`

```python
# test_capital_inicial_no_cambia
# Verificar que capital_inicial en ConfigTable nunca se modifica por trades

# test_capital_total_suma_pnl_cerrado
# Verificar que capital_total = capital_inicial + sum(net_pnl trades cerrados)

# test_capital_bloqueado_suma_risk_usd_abiertos
# Verificar que capital_bloqueado = sum(risk_usd de trades OPEN)

# test_capital_disponible_positivo
# Verificar que capital_disponible = capital_total - capital_bloqueado

# test_no_abre_sin_capital_disponible
# Verificar que si capital_disponible < risk_usd la posición no se abre

# test_no_supera_max_concurrent
# Verificar que con 3 posiciones abiertas y max=3 no abre una cuarta

# test_riesgo_calculado_sobre_capital_actual
# Abrir 3 trades, cerrar 2 con ganancia, verificar que el 4to
# calcula el riesgo sobre el capital actualizado (mayor al inicial)

# test_riesgo_calculado_sobre_capital_actual_con_perdidas
# Abrir 3 trades, cerrar 2 con pérdida, verificar que el 4to
# calcula el riesgo sobre el capital reducido (menor al inicial)

# test_sl_ejecuta_al_precio_del_sl_no_del_check
# Simular precio cayendo de $74,200 a $72,000 en un check
# Verificar que el cierre se registra a $73,650 (SL) + slippage mínimo
# NO a $72,000 (precio del check)

# test_trailing_sl_solo_sube
# Verificar que trailing_sl_final nunca baja aunque el precio baje

# test_trailing_sl_minimo_es_entrada
# Verificar que trailing_sl nunca es menor al precio de entrada

# test_perdida_maxima_limitada_a_risk_usd
# Verificar que close_trade nunca registra pérdida > risk_usd original

# test_drawdown_pausa_sistema
# Verificar que con drawdown >= 25% el sistema se pausa automáticamente
# y no genera nuevas simulaciones

# test_capital_command_muestra_capital_actual
# Verificar que /capital muestra capital_total actual, no el inicial
```

---

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `src/core/state.py` | `get_capital_actual()`, `check_drawdown_limit()` |
| `src/core/calculator.py` | `calculate_position_with_current_capital()` |
| `src/core/trades_manager.py` | `can_open_trade()`, `open_sim_trade()` con verificación |
| `src/core/simulator.py` | `evaluate()`, `update_trailing_sl()`, `close_trade()` con hardcap |
| `src/lambdas/scanner/handler.py` | Verificar drawdown al inicio, usar capital dinámico |
| `src/lambdas/webhook/handler.py` | `/capital` dinámico, `/reset_capital` |
| `src/core/telegram_client.py` | Mensaje de capital insuficiente |
| `tests/test_capital_management.py` | Crear archivo con todos los tests |

## Archivos a NO modificar
- `src/strategies/` — las estrategias no cambian
- `src/core/market_context.py` — el evaluador no cambia
- `infra/` — no hay cambios de infraestructura

---

## Orden de implementación

1. `state.py` → `get_capital_actual()` primero — todo depende de esto
2. `trades_manager.py` → `can_open_trade()` y `open_sim_trade()` con verificación
3. `simulator.py` → `close_trade()` con hardcap y `update_trailing_sl()` corregido
4. `calculator.py` → `calculate_position_with_current_capital()`
5. `scanner/handler.py` → integrar verificaciones al flujo
6. `webhook/handler.py` → comandos `/capital` y `/reset_capital`
7. Tests → verificar que todo funciona correctamente

---

## Resultado esperado

```
ANTES de los fixes:
  Capital inicial: $1,183
  Capital actual:  -$117  (imposible — drawdown > 100%)
  Pérdidas por op: hasta $160 (debería ser máx $59)

DESPUÉS de los fixes:
  Capital inicial: $1,183  (inmutable)
  Capital actual:  calculado dinámicamente desde trades cerrados
  Riesgo por op:   5% del capital actual (varía con el P&L)
  Pérdida máx:     risk_usd hardcapeado — imposible perder más
  Sin capital:     el scanner no abre nuevas posiciones
  Drawdown 25%:    pausa automática y notificación
```
