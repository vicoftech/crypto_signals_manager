# CURSOR PROMPT — Diagnóstico y corrección del modelo de capital del simulador

---

## Objetivo

Antes de aplicar cualquier fix, hacer un diagnóstico completo del estado actual
del simulador para entender exactamente cómo está calculando el capital,
el position size, el P&L y el SL.

El sistema reportó -$1,300 sobre un capital inicial de $1,183 lo cual es
matemáticamente imposible con el modelo correcto.

---

## PASO 1 — DIAGNÓSTICO: leer el código actual y reportar

Leer los siguientes archivos y para cada uno responder las preguntas específicas.
NO modificar nada todavía. Solo leer y reportar.

### 1A. Leer `src/core/calculator.py`

Responder:
```
¿Cómo calcula position_size_usd?
  a) position_size = capital × risk_pct  (compra el % directamente)
  b) position_size = risk_usd / sl_pct   (position sizing con SL)
  c) otro — describir

¿Cómo calcula risk_usd?
  a) risk_usd = capital_inicial × risk_pct  (capital fijo)
  b) risk_usd = capital_actual × risk_pct   (capital dinámico)
  c) otro — describir

¿Usa capital_inicial hardcodeado o lo lee de algún lado?
¿Recalcula el riesgo cuando hay posiciones abiertas?
```

### 1B. Leer `src/core/simulator.py`

Responder:
```
¿Cómo calcula la pérdida cuando ejecuta el SL?
  a) pérdida = position_size × sl_pct  (sobre lo invertido)
  b) pérdida = position_size - (position_size × (1 - sl_pct))
  c) pérdida = entry_price - current_price × cantidad_comprada
  d) otro — describir

¿A qué precio registra el cierre cuando el SL se ejecuta?
  a) al precio del SL definido (correcto)
  b) al precio actual del check (puede ser peor que el SL)
  c) otro — describir

¿El trailing SL puede bajar una vez activado?
¿Hay algún hardcap que limite la pérdida máxima a risk_usd?
```

### 1C. Leer `src/core/trades_manager.py` o `src/core/state.py`

Responder:
```
¿Verifica capital disponible antes de abrir una posición?
  a) sí — ¿cómo lo calcula?
  b) no — abre sin verificar

¿Bloquea capital cuando hay posiciones abiertas?
  a) sí — ¿cuánto bloquea? ¿el risk_usd o el position_size_usd?
  b) no

¿Cuántas posiciones simultáneas permite?
¿Hay algún límite de max_concurrent_open implementado?
```

### 1D. Leer `src/lambdas/webhook/handler.py` — comando `/capital`

Responder:
```
¿De dónde lee el capital para mostrar?
  a) de ConfigTable key="capital" (valor estático)
  b) calcula dinámicamente sumando P&L de trades cerrados
  c) otro — describir

¿Actualiza el capital después de cada trade cerrado?
```

### 1E. Consultar DynamoDB — TradesTable

Ejecutar estas consultas y mostrar los resultados:

```python
import boto3

dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
table = dynamodb.Table("TradesTable")  # ajustar nombre si es diferente

# Consulta 1: últimos 5 trades cerrados
response = table.scan(
    FilterExpression="#s = :closed AND #m = :sim",
    ExpressionAttributeNames={"#s": "status", "#m": "mode"},
    ExpressionAttributeValues={":closed": "CLOSED", ":sim": "SIM"},
    Limit=10
)

for trade in response["Items"]:
    print(f"""
    trade_id:          {trade.get('trade_id')}
    pair:              {trade.get('pair')}
    strategy:          {trade.get('strategy')}
    entry_price:       {trade.get('entry_price')}
    exit_price:        {trade.get('exit_price')}
    position_size_usd: {trade.get('position_size_usd')}
    risk_usd:          {trade.get('risk_usd')}
    sl_initial:        {trade.get('sl_initial')}
    sl_pct:            {trade.get('sl_pct')}
    net_pnl_usd:       {trade.get('net_pnl_usd')}
    close_reason:      {trade.get('close_reason')}
    capital_at_open:   {trade.get('capital_at_open')}
    """)

# Consulta 2: trades abiertos ahora mismo
response2 = table.scan(
    FilterExpression="#s = :open AND #m = :sim",
    ExpressionAttributeNames={"#s": "status", "#m": "mode"},
    ExpressionAttributeValues={":open": "OPEN", ":sim": "SIM"},
)
print(f"\nPosiciones abiertas: {len(response2['Items'])}")
for t in response2["Items"]:
    print(f"  {t.get('pair')} | position_size: {t.get('position_size_usd')} | risk: {t.get('risk_usd')}")

# Consulta 3: P&L total acumulado
total_pnl = sum(
    float(t.get("net_pnl_usd", 0))
    for t in table.scan(
        FilterExpression="#s = :closed AND #m = :sim",
        ExpressionAttributeNames={"#s": "status", "#m": "mode"},
        ExpressionAttributeValues={":closed": "CLOSED", ":sim": "SIM"},
    )["Items"]
)
print(f"\nP&L total acumulado (trades cerrados): ${total_pnl:.2f}")

# Consulta 4: máximo de posiciones abiertas simultáneamente
# (aproximado — buscar el momento con más trades abiertos)
all_trades = table.scan()["Items"]
print(f"\nTotal trades en tabla: {len(all_trades)}")
print(f"Cerrados: {sum(1 for t in all_trades if t.get('status') == 'CLOSED')}")
print(f"Abiertos: {sum(1 for t in all_trades if t.get('status') == 'OPEN')}")
```

---

## PASO 2 — DIAGNÓSTICO: identificar el modelo actual

Basándote en lo que encontraste en el Paso 1, identificar cuál de estos
modelos está implementado actualmente:

```
MODELO A — Correcto (invertir el % directamente):
  position_size_usd = capital × risk_pct  (ej: $118.30)
  Pérdida si SL:     position_size × sl_pct  (ej: $1.30)
  Ganancia si TP2:   position_size × tp2_pct (ej: $3.90)

MODELO B — Incorrecto para spot con capital pequeño:
  risk_usd          = capital × risk_pct     (ej: $118.30)
  position_size_usd = risk_usd / sl_pct      (ej: $10,754)
  Pérdida si SL:     risk_usd                (ej: $118.30)
  Ganancia si TP2:   risk_usd × 3            (ej: $354.90)

MODELO C — Mezclado o inconsistente:
  Calcula position_size de una forma pero el P&L de otra
  → genera resultados incorrectos
```

Reportar cuál modelo está implementado con evidencia del código.

---

## PASO 3 — CORRECCIÓN según el diagnóstico

Según el modelo encontrado, aplicar la corrección correspondiente.

### Si encontraste MODELO B o MODELO C → aplicar este fix

El modelo correcto para spot con capital pequeño es el MODELO A:

```
Comprás exactamente el % del capital.
La ganancia y pérdida son el % de movimiento del precio
aplicado sobre lo que compraste.
```

#### Fix en `src/core/calculator.py`

```python
async def calculate_position(
    opportunity: Opportunity,
    capital_total: float,
    risk_pct: float = 0.10,       # 10% del capital por operación
    commission_rate: float = 0.001  # 0.1% por lado Binance
) -> Opportunity:
    """
    MODELO CORRECTO PARA SPOT CON CAPITAL PEQUEÑO:

    Comprás exactamente (risk_pct × capital_total) en el activo.
    No hay position sizing con apalancamiento.
    La pérdida máxima es sl_pct × lo_que_compraste.
    La ganancia esperada es tp2_pct × lo_que_compraste.

    Ejemplo con capital $1,183, risk_pct 10%, SL 1.1%, TP 3.3%:
      Comprás:         $118.30 en BTC
      Pérdida si SL:   $118.30 × 1.1% = $1.30  (+ $0.24 comisión)
      Ganancia si TP2: $118.30 × 3.3% = $3.90  (- $0.24 comisión)
    """

    # Lo que comprás = % del capital total
    amount_to_invest = capital_total * risk_pct

    # SL y TP en % de movimiento del precio
    sl_pct  = (opportunity.entry_price - opportunity.sl_price) / opportunity.entry_price
    tp1_pct = (opportunity.tp1_price - opportunity.entry_price) / opportunity.entry_price
    tp2_pct = (opportunity.tp2_price - opportunity.entry_price) / opportunity.entry_price

    # Ganancia y pérdida en USD sobre lo invertido
    max_loss    = amount_to_invest * sl_pct
    tp1_gain    = amount_to_invest * tp1_pct
    tp2_gain    = amount_to_invest * tp2_pct

    # Comisión: 0.1% al comprar + 0.1% al vender = 0.2% del monto invertido
    commission  = amount_to_invest * commission_rate * 2

    # R/R real
    rr_ratio = tp2_gain / max_loss if max_loss > 0 else 0

    # Actualizar opportunity
    opportunity.position_size_usd = round(amount_to_invest, 2)
    opportunity.risk_usd          = round(max_loss, 4)        # pérdida máxima real
    opportunity.reward_usd        = round(tp2_gain, 4)        # ganancia esperada
    opportunity.commission_usd    = round(commission, 4)
    opportunity.rr_ratio          = round(rr_ratio, 2)
    opportunity.capital_at_open   = round(capital_total, 2)
    opportunity.risk_pct          = risk_pct
    opportunity.sl_pct            = round(sl_pct, 6)

    # Log para verificación
    logger.debug(f"""
    [CALC] {opportunity.pair} | {opportunity.strategy}
    Invertís:        ${amount_to_invest:.2f}  ({risk_pct:.0%} de ${capital_total:.2f})
    SL ({sl_pct:.2%}):  -${max_loss:.4f}
    TP2 ({tp2_pct:.2%}): +${tp2_gain:.4f}
    Comisión:        -${commission:.4f}
    R/R real:        1:{rr_ratio:.1f}
    Neto ganadora:   +${tp2_gain - commission:.4f}
    Neto perdedora:  -${max_loss + commission:.4f}
    """)

    return opportunity
```

#### Fix en `src/core/simulator.py` — `close_trade()`

```python
def close_trade(trade: Trade, exit_price: float, close_reason: str) -> None:
    """
    Calcula P&L neto correctamente en el modelo SPOT directo.

    P&L = (exit_price - entry_price) / entry_price × position_size_usd
    Comisión = position_size_usd × 0.2%
    """

    # Movimiento del precio
    price_change_pct = (exit_price - trade.entry_price) / trade.entry_price

    # P&L bruto = movimiento × lo que compraste
    gross_pnl = trade.position_size_usd * price_change_pct

    # Comisión sobre lo invertido (compra + venta)
    commission = trade.position_size_usd * 0.002  # 0.1% × 2

    # P&L neto
    net_pnl = gross_pnl - commission

    # VALIDACIÓN: verificar que los números son coherentes
    # Pérdida no puede ser mayor que lo invertido
    if net_pnl < -trade.position_size_usd:
        logger.error(
            f"[SIM] ⚠️ P&L imposible: {net_pnl:.4f} "
            f"sobre posición de {trade.position_size_usd:.2f}. "
            f"Limitando a pérdida total de la posición."
        )
        net_pnl = -trade.position_size_usd

    # R múltiple: cuántos "riesgos" ganó o perdió
    # Riesgo = lo que hubiera perdido si el SL original se ejecutaba
    riesgo_original = trade.position_size_usd * trade.sl_pct
    r_multiple = net_pnl / riesgo_original if riesgo_original > 0 else 0

    trade.exit_price      = round(exit_price, 8)
    trade.gross_pnl_usd   = round(gross_pnl, 4)
    trade.net_pnl_usd     = round(net_pnl, 4)
    trade.commission_usd  = round(commission, 4)
    trade.r_multiple      = round(r_multiple, 2)
    trade.close_reason    = close_reason
    trade.ended_at        = datetime.utcnow().isoformat()
    trade.duration_minutes = int(
        (datetime.utcnow() - datetime.fromisoformat(trade.started_at)).total_seconds() / 60
    )
    trade.status = "CLOSED"

    logger.info(json.dumps({
        "event_type":    "trade_closed",
        "trade_id":      trade.trade_id,
        "pair":          trade.pair,
        "strategy":      trade.strategy,
        "close_reason":  close_reason,
        "entry_price":   trade.entry_price,
        "exit_price":    exit_price,
        "price_chg_pct": round(price_change_pct * 100, 4),
        "position_size": trade.position_size_usd,
        "gross_pnl":     round(gross_pnl, 4),
        "commission":    round(commission, 4),
        "net_pnl":       round(net_pnl, 4),
        "r_multiple":    round(r_multiple, 2),
    }))
```

#### Fix en `src/core/simulator.py` — precio de cierre del SL

```python
# En evaluate() — cuando el precio toca el SL
if current_price <= sl_activo:
    # IMPORTANTE: cerrar al precio del SL, no al precio del check
    # Esto simula que la orden stop estaba puesta en Binance
    # y se ejecutó exactamente en ese nivel
    # (con slippage mínimo del 0.02% para ser realista)
    slip = 0.0002
    precio_ejecucion = sl_activo * (1 - slip)

    razon = "TRAILING_SL" if trade.trailing_activated else "SL"
    await close_trade(trade, precio_ejecucion, razon)
    return
```

#### Fix en `src/core/state.py` — capital dinámico

```python
async def get_capital_actual(capital_inicial: float) -> dict:
    """
    Capital actual = capital inicial + suma de net_pnl de trades cerrados.
    Simple, sin complicaciones.
    """
    trades_cerrados = await trades_manager.get_closed_sim_trades()
    pnl_acumulado   = sum(float(t.net_pnl_usd) for t in trades_cerrados)
    capital_total   = capital_inicial + pnl_acumulado

    trades_abiertos   = await trades_manager.get_open_sim_trades()
    # Bloqueado = suma de lo invertido en posiciones abiertas
    capital_bloqueado = sum(float(t.position_size_usd) for t in trades_abiertos)
    capital_disponible = capital_total - capital_bloqueado

    return {
        "capital_inicial":    round(capital_inicial, 2),
        "pnl_acumulado":      round(pnl_acumulado, 2),
        "capital_total":      round(capital_total, 2),
        "capital_bloqueado":  round(capital_bloqueado, 2),
        "capital_disponible": round(capital_disponible, 2),
        "posiciones_abiertas": len(trades_abiertos),
    }
```

#### Fix en `src/lambdas/scanner/handler.py` — verificación antes de abrir

```python
async def can_open_new_position(capital_inicial: float, risk_pct: float) -> tuple[bool, str, float]:
    """
    Verifica si se puede abrir una nueva posición.
    Retorna (puede_abrir, razon, amount_to_invest)
    """
    cap = await get_capital_actual(capital_inicial)

    # Monto a invertir en la próxima operación
    amount = cap["capital_total"] * risk_pct

    # Verificar que hay capital disponible
    if cap["capital_disponible"] < amount:
        return False, (
            f"Capital insuficiente. "
            f"Disponible: ${cap['capital_disponible']:.2f} | "
            f"Requerido: ${amount:.2f}"
        ), 0

    # Verificar máximo de posiciones simultáneas
    max_ops = int(1 / risk_pct)  # con 10% → máximo 10 posiciones
    if cap["posiciones_abiertas"] >= max_ops:
        return False, (
            f"Máximo de posiciones: {cap['posiciones_abiertas']}/{max_ops}"
        ), 0

    return True, "OK", amount
```

---

## PASO 4 — VERIFICACIÓN post-fix

Después de aplicar los fixes, verificar con estos casos:

### Test manual A — operación ganadora

```python
# Simular manualmente:
capital    = 1183.0
risk_pct   = 0.10
invertido  = capital * risk_pct  # = $118.30

entry      = 74200.0
sl         = entry * (1 - 0.011)  # SL 1.1% = $73,384.20
tp2        = entry * (1 + 0.033)  # TP2 3.3% = $76,648.60

# Al cierre en TP2:
ganancia_bruta = invertido * 0.033           # = $3.9039
comision       = invertido * 0.002           # = $0.2366
ganancia_neta  = ganancia_bruta - comision   # = $3.6673

print(f"Invertido:      ${invertido:.2f}")
print(f"Ganancia bruta: ${ganancia_bruta:.4f}")
print(f"Comisión:       ${comision:.4f}")
print(f"Ganancia neta:  ${ganancia_neta:.4f}")

# Resultado esperado:
# Invertido:      $118.30
# Ganancia bruta: $3.9039
# Comisión:       $0.2366
# Ganancia neta:  $3.6673  ← esto debe aparecer en net_pnl_usd del trade
```

### Test manual B — operación perdedora

```python
# Al cierre en SL:
perdida_bruta = invertido * 0.011           # = $1.3013
comision      = invertido * 0.002           # = $0.2366
perdida_neta  = perdida_bruta + comision    # = $1.5379

print(f"Pérdida bruta:  ${perdida_bruta:.4f}")
print(f"Comisión:       ${comision:.4f}")
print(f"Pérdida neta:   ${perdida_neta:.4f}")

# Resultado esperado:
# Pérdida bruta:  $1.3013
# Comisión:       $0.2366
# Pérdida neta:   $1.5379  ← esto debe aparecer en net_pnl_usd del trade
```

### Test manual C — 10 operaciones, 4 ganadoras, 6 perdedoras

```python
ganadoras  = 4 * 3.6673   # = $14.67
perdedoras = 6 * 1.5379   # = $9.23
resultado  = ganadoras - perdedoras  # = +$5.44

capital_final = 1183.0 + resultado  # = $1,188.44

# Con winrate 40% el sistema es levemente positivo
# Con winrate 45% es claramente positivo
# NUNCA puede dar -$1,300 con este modelo
```

---

## PASO 5 — REPORTE FINAL

Al terminar el diagnóstico y los fixes, generar un reporte con:

```
DIAGNÓSTICO:
  Modelo encontrado:          [A / B / C / otro]
  Bug principal:              [descripción]
  Causa del -$1,300:          [explicación]

FIXES APLICADOS:
  calculator.py:              [sí/no — qué cambió]
  simulator.py close_trade(): [sí/no — qué cambió]
  simulator.py precio SL:     [sí/no — qué cambió]
  state.py capital dinámico:  [sí/no — qué cambió]
  scanner.py verificación:    [sí/no — qué cambió]

VERIFICACIÓN:
  Test A (ganadora):     net_pnl esperado $3.67  → real: [valor]
  Test B (perdedora):    net_pnl esperado -$1.54 → real: [valor]
  Test C (4G/6P):        resultado esperado +$5.44 → real: [valor]

ESTADO:
  ¿El sistema opera correctamente ahora?  [sí/no]
  ¿Quedan bugs conocidos?                 [descripción o ninguno]
```

---

## Archivos a leer (diagnóstico)
- `src/core/calculator.py`
- `src/core/simulator.py`
- `src/core/trades_manager.py`
- `src/core/state.py`
- `src/lambdas/scanner/handler.py`
- `src/lambdas/webhook/handler.py`

## Archivos a modificar (solo si el diagnóstico confirma bugs)
- `src/core/calculator.py`
- `src/core/simulator.py`
- `src/core/state.py`
- `src/lambdas/scanner/handler.py`

## Archivos a NO modificar
- `src/strategies/` — las estrategias no cambian
- `src/core/market_context.py` — el evaluador no cambia
- `src/core/indicators.py` — los indicadores no cambian
- `infra/` — no hay cambios de infraestructura

---

## Modelo de negocio correcto para referencia de Cursor

```
SISTEMA: Spot Binance sin apalancamiento
CAPITAL: $1,183 inicial

POR OPERACIÓN (10%):
  Invertís:          $118.30  (comprás BTC por ese monto)
  SL 1.1%:           perdés $1.30 + $0.24 comisión = $1.54 total
  TP2 3.3%:          ganás  $3.90 - $0.24 comisión = $3.66 total
  R/R real:          1:2.38

CON 10 OPERACIONES PARALELAS:
  Capital comprometido: $1,183 (100% trabajando)
  Si todas pierden:     -$15.40 máximo en una semana
  Si 4/10 ganan:        +$5.44 semanal

COMPUESTO:
  Cada ganancia reinvierte → el 10% siguiente es levemente mayor
  Con EV positivo y tiempo → crecimiento exponencial inevitable
```
