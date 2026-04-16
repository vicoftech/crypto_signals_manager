# CURSOR PROMPT — Auto-simulación automática configurable por par

---

## Contexto

El sistema ya tiene simulación manual funcionando donde el operador
decide si simular o ignorar cada señal con botones de Telegram.

El objetivo de este cambio es agregar un **modo de auto-simulación**
que entre automáticamente en TODAS las señales de un par sin intervención
humana, para acumular datos estadísticos representativos lo más rápido posible.

El modo es **configurable por par** porque algunos pares se operarán
manualmente y otros en auto-sim (o eventualmente auto-trade real).

---

## Cambios requeridos

### 1. PairsTable — nuevos campos

Agregar estos campos a cada ítem de la tabla `PairsTable` en DynamoDB:

```python
{
    "pair": "BTCUSDT",
    "tier": "1",
    "active": True,
    "strategies": ["EMAPullback", "MACDCross"],

    # ── NUEVO: configuración de modo por par ──────────────────
    "sim_mode": "manual",       # "manual" | "auto" | "disabled"
                                # manual:   operador decide señal por señal
                                # auto:     entra en todas las señales automáticamente
                                # disabled: no simula nada, solo notifica

    "auto_trade": False,        # True cuando Athena valide el par para real
    "auto_trade_strategies": [], # estrategias habilitadas para real (vacío = ninguna)

    "sim_auto_enabled_at": None,  # ISO timestamp de cuándo se activó auto-sim
    "sim_auto_reason": None,      # nota del operador al activarlo
    "sim_stats": {                # estadísticas acumuladas en tiempo real
        "total_sim": 0,
        "ganadoras": 0,
        "perdedoras": 0,
        "pnl_total_usd": 0.0,
        "r_multiple_avg": 0.0,
        "last_updated": None
    }
}
```

---

### 2. Nuevo flujo en el scanner — `src/lambdas/scanner/handler.py`

Cuando se detecta una oportunidad válida, antes de enviar a Telegram
consultar el `sim_mode` del par y actuar según corresponda:

```python
async def handle_opportunity(opportunity: Opportunity, pair_config: dict) -> None:
    sim_mode = pair_config.get("sim_mode", "manual")

    if sim_mode == "auto":
        # Entrar automáticamente en simulación SIN notificar al operador
        # Solo registrar el trade y enviar confirmación silenciosa
        trade = await trades_manager.open_sim_trade(opportunity)
        await telegram_client.send_auto_sim_opened(trade, opportunity)

    elif sim_mode == "manual":
        # Flujo actual — enviar señal con botones
        await telegram_client.send_opportunity(opportunity)

    elif sim_mode == "disabled":
        # Solo notificar la oportunidad sin botones de simulación
        await telegram_client.send_opportunity_notify_only(opportunity)
```

---

### 3. Mensajes de Telegram — `src/core/telegram_client.py`

#### Apertura de auto-sim

Cuando el modo es `auto`, enviar un mensaje compacto sin botones
que confirme que se entró automáticamente:

```
🤖 AUTO-SIM ABIERTA

📊 BTC/USDT  |  M30  |  EMAPullback
🎯 Entrada:  $74,200.00
🛑 SL:       $73,650.00  (-0.74%)
🏆 TP2:      $75,850.00  (+2.22%)
📐 R/R:      1 : 3.0

💰 Riesgo: $59.15 (5%)
⏰ 14:32 UTC
```

#### Actualizaciones periódicas — con P&L circunstancial

El monitor envía actualizaciones cada 60s mientras la posición está abierta.
Cada actualización debe mostrar el **P&L circunstancial** calculado en tiempo real
en base al precio actual de Binance vs el precio de entrada real:

```python
def calcular_pnl_circunstancial(
    entry_price: float,
    current_price: float,
    position_size_usd: float,
    commission_usd: float
) -> tuple[float, float]:
    """
    Calcula el P&L circunstancial de la posición en este momento.
    Incluye las comisiones de entrada ya pagadas.
    No incluye la comisión de salida (se pagaría si cerrara ahora).

    Retorna (pnl_usd, pnl_pct)
    """
    pnl_bruto = (current_price - entry_price) / entry_price * position_size_usd
    # Comisión de entrada ya pagada + estimación de comisión de salida
    comision_salida_estimada = position_size_usd * 0.001  # 0.1%
    pnl_neto = pnl_bruto - commission_usd - comision_salida_estimada
    pnl_pct  = pnl_neto / position_size_usd * 100
    return round(pnl_neto, 2), round(pnl_pct, 3)
```

**Formato del mensaje de actualización:**

```
📊 [SIM] BTC/USDT — en curso

💵 Precio actual:  $74,580
📈 P&L ahora:      +$22.14  (+0.30%)  ← P&L circunstancial
─────────────────────────────────
🎯 Entrada:  $74,200  |  SL: $73,650
✅ TP1:      $75,025  (falta +$445)
🏆 TP2:      $75,850  (falta +$1,270)
⏱ Abierta:  47 min
```

Después de tocar TP1 y con trailing activo:

```
📊 [SIM] BTC/USDT — trailing activo

💵 Precio actual:  $75,280
📈 P&L ahora:      +$141.20  (+1.90%)  ← P&L circunstancial
🔒 P&L asegurado:  +$89.40   (+1.20%)  ← si cierra en trailing SL ahora
─────────────────────────────────
✅ TP1 alcanzado — SL movido a entrada
🔄 Trailing SL:  $74,902  (step 0.5%)
🏆 TP2:          $75,850  (falta +$570)
⏱ Abierta:  1h 23min
```

**Reglas del P&L circunstancial:**
- Calcularlo en CADA actualización del monitor (cada 15s internamente, notificar cada 60s)
- Siempre mostrar P&L **neto** (descontando comisiones de entrada ya pagadas
  más estimación de comisión de salida si cerrara ahora)
- Mostrar también el **P&L asegurado** cuando el trailing está activo
  (lo que ganaría si el trailing SL se ejecutara al precio actual)
- El color del emoji cambia según el estado:
  - `📈` si P&L > 0
  - `📉` si P&L < 0
  - `➡️` si P&L ≈ 0 (dentro de ±0.05%)

#### Cierre — con P&L circunstancial final

```
🤖 AUTO-SIM CERRADA  ✅ GANADORA

📊 BTC/USDT  |  EMAPullback
📈 Entrada:   $74,200  →  Salida: $75,420
💰 P&L neto:  +$177.45  (+2.39%)
📐 R múltiple: +2.9
🔒 Cierre:    TRAILING_SL
⏱ Duración:  1h 47min

📊 Stats BTC/USDT auto-sim:
   Trades: 12 | Win: 10 (83%) | R avg: +2.1
```

#### Comando `/simular` — estado de posiciones abiertas con P&L circunstancial

El comando `/simular` debe listar todas las posiciones abiertas (auto y manual)
mostrando el **P&L circunstancial en tiempo real** de cada una:

```python
async def handle_simular_command() -> str:
    """
    Al ejecutar /simular, consultar precio actual de Binance
    para cada posición abierta y calcular el P&L circunstancial.
    """
    open_trades = await trades_manager.get_all_open_trades()

    if not open_trades:
        return "No hay posiciones abiertas en este momento."

    # Para cada trade abierto, consultar precio actual
    for trade in open_trades:
        current_price = await binance_client.get_price(trade.pair)
        trade.pnl_circunstancial, trade.pnl_pct = calcular_pnl_circunstancial(
            trade.entry_price,
            current_price,
            trade.position_size_usd,
            trade.commission_usd
        )
        trade.current_price = current_price
```

**Formato de respuesta del comando `/simular`:**

```
📊 POSICIONES ABIERTAS  (3)

① BTC/USDT  🤖 AUTO  |  EMAPullback
   Entrada: $74,200  |  Ahora: $74,850
   📈 P&L:  +$38.20  (+0.51%)
   ✅ TP1 alcanzado | 🔄 Trailing: $74,478
   ⏱ 1h 23min abierta

② ETH/USDT  🤖 AUTO  |  MACDCross
   Entrada: $2,315  |  Ahora: $2,298
   📉 P&L:  -$12.40  (-0.17%)
   SL: $2,280  (falta -$18 / -0.78%)
   ⏱ 28min abierta

③ SOL/USDT  👤 MANUAL  |  Momentum
   Entrada: $84.20  |  Ahora: $85.10
   📈 P&L:  +$31.80  (+0.38%)
   TP1: $85.45  (falta +$0.35 / +0.41%)
   ⏱ 52min abierta

──────────────────────────────
💼 P&L total abierto:  +$57.60  (+0.69%)
   Riesgo expuesto:    $177.45  (3 × 5%)
```

**Implementación — el comando `/simular` debe:**
1. Consultar `trades_manager.get_all_open_trades()` → todas las posiciones `status=OPEN`
2. Para cada trade, llamar `binance_client.get_price(pair)` en paralelo (asyncio.gather)
3. Calcular `pnl_circunstancial` para cada una con `calcular_pnl_circunstancial()`
4. Calcular P&L total sumando todos los circunstanciales
5. Calcular riesgo total expuesto (suma de `risk_usd` de todas las posiciones abiertas)
6. Formatear y enviar el mensaje

El P&L circunstancial también debe incluirse en el campo `pnl_usd` de
`TradesTable` para cada posición abierta — actualizar este campo en cada
ciclo del monitor para que `/simular` pueda leer el último valor sin
tener que recalcular (aunque siempre recalcula en el momento del comando
para máxima precisión).

---

### 4. Nuevos comandos Telegram — `src/lambdas/webhook/handler.py`

Implementar estos comandos para gestionar el modo por par:

```
/simconfig BTCUSDT auto
  → Activa auto-simulación para BTC
  → Respuesta: "✅ BTCUSDT en modo AUTO-SIM. Todas las señales se simularán automáticamente."

/simconfig ETHUSDT manual
  → Vuelve al modo manual para ETH
  → Respuesta: "✅ ETHUSDT en modo MANUAL. Recibirás señales con botones."

/simconfig SOLUSDT disabled
  → Desactiva simulación para SOL (solo notificaciones)
  → Respuesta: "✅ SOLUSDT en modo DISABLED. Solo recibirás notificaciones sin simulación."

/simstatus
  → Muestra el modo actual y estadísticas de todos los pares activos

/simstats BTCUSDT
  → Estadísticas detalladas de simulación para ese par
```

#### Respuesta de `/simstatus`

```
📊 ESTADO DE SIMULACIÓN

Par          Modo      Trades  Win%   R avg   P&L
──────────────────────────────────────────────────
BTC/USDT     🤖 AUTO   12      83%    +2.1    +$312
ETH/USDT     🤖 AUTO   8       75%    +1.8    +$198
SOL/USDT     👤 MANUAL 4       75%    +2.3    +$87
XRP/USDT     👤 MANUAL 2       50%    +1.1    +$12
BNB/USDT     ⛔ OFF    0       —      —       —

Total SIM:   26 trades | Win: 20 (77%) | P&L: +$609
Objetivo:    100 trades por par para habilitar automático
```

#### Respuesta de `/simstats BTCUSDT`

```
📈 ESTADÍSTICAS BTC/USDT — AUTO-SIM

Período:     15 días
Total trades: 34

RENDIMIENTO
  Ganadoras:    28  (82%)
  Perdedoras:   6   (18%)
  R múltiple:   +2.1 promedio
  P&L bruto:    +$1,247
  Comisiones:   -$89
  P&L neto:     +$1,158

POR ESTRATEGIA
  EMAPullback:  24 trades | 83% win | R: +2.3 ✅
  MACDCross:    10 trades | 80% win | R: +1.7 ✅

POR SESIÓN
  LONDON:       15 trades | 87% win ← mejor sesión
  NEW_YORK:     12 trades | 75% win
  ASIA:         7  trades | 71% win

CIERRE
  TRAILING_SL:  22 (79%)
  TP2:          6  (21%)
  SL:           6  (18%)

DURACIÓN
  Promedio:     1h 52min
  Mínima:       27min
  Máxima:       4h 18min

Estado para auto-trade: ⏳ 66/100 trades mínimos
```

---

### 5. Realismo del simulador — `src/core/simulator.py`

Al abrir una posición en modo auto-sim, aplicar slippage realista
para que los datos simulados sean lo más cercanos posible a la realidad:

```python
# Slippage de entrada por par (simulando orden limit en mercado real)
ENTRY_SLIPPAGE = {
    "BTCUSDT": (0.0001, 0.0003),   # 0.01% - 0.03%
    "ETHUSDT": (0.0001, 0.0004),   # 0.01% - 0.04%
    "BNBUSDT": (0.0002, 0.0005),
    "SOLUSDT": (0.0003, 0.0008),
    "XRPUSDT": (0.0002, 0.0006),
}

# Slippage de cierre por trailing (la orden de stop se ejecuta levemente peor)
TRAILING_CLOSE_SLIPPAGE = {
    "BTCUSDT": 0.0002,
    "ETHUSDT": 0.0002,
    "SOLUSDT": 0.0005,
    "XRPUSDT": 0.0004,
}

# Delay de entrada simulado (segundos entre señal y entrada real)
# En auto-sim es mínimo (~5s para Lambda) vs manual (minutos)
ENTRY_DELAY_SECONDS_AUTO   = 5
ENTRY_DELAY_SECONDS_MANUAL = 180   # 3 minutos promedio

def apply_realistic_entry(
    opportunity: Opportunity,
    mode: str = "auto"   # "auto" | "manual"
) -> tuple[float, float]:
    """
    Retorna (entry_price_real, slippage_pct)
    El precio de entrada real es peor que el close de la señal.
    """
    import random

    min_slip, max_slip = ENTRY_SLIPPAGE.get(
        opportunity.pair,
        (0.0005, 0.0015)
    )

    # En manual el slippage es mayor porque el precio se movió más
    if mode == "manual":
        min_slip *= 2
        max_slip *= 3

    slippage = random.uniform(min_slip, max_slip)
    entry_real = opportunity.entry_price * (1 + slippage)

    return entry_real, slippage


def apply_trailing_close_slippage(
    trailing_sl_price: float,
    pair: str
) -> float:
    """
    El cierre por trailing ejecuta levemente peor que el nivel del trailing SL.
    """
    slip = TRAILING_CLOSE_SLIPPAGE.get(pair, 0.0008)
    return trailing_sl_price * (1 - slip)


def is_signal_still_valid(
    signal_price: float,
    current_price: float,
    max_drift_pct: float = 0.003
) -> bool:
    """
    Verifica que el precio no se haya movido demasiado desde la señal.
    Si el drift supera el máximo, la señal ya no es ejecutable.
    """
    drift = abs(current_price - signal_price) / signal_price
    return drift <= max_drift_pct
```

---

### 6. Actualización de estadísticas en tiempo real — `src/core/trades_manager.py`

Cada vez que se cierra un trade de auto-sim, actualizar el campo
`sim_stats` del par en PairsTable atómicamente:

```python
async def update_pair_sim_stats(pair: str, trade: Trade) -> None:
    """
    Actualiza las estadísticas acumuladas del par en PairsTable
    usando una operación atómica de DynamoDB para evitar race conditions.
    """
    ganadora = 1 if trade.net_pnl_usd > 0 else 0

    dynamodb.update_item(
        TableName="PairsTable",
        Key={"pair": {"S": pair}},
        UpdateExpression="""
            SET sim_stats.total_sim = sim_stats.total_sim + :one,
                sim_stats.ganadoras = sim_stats.ganadoras + :ganadora,
                sim_stats.pnl_total_usd = sim_stats.pnl_total_usd + :pnl,
                sim_stats.last_updated = :ts
        """,
        ExpressionAttributeValues={
            ":one":      {"N": "1"},
            ":ganadora": {"N": str(ganadora)},
            ":pnl":      {"N": str(trade.net_pnl_usd)},
            ":ts":       {"S": datetime.utcnow().isoformat()},
        }
    )
```

---

### 7. Lógica de habilitación de auto-trade — `src/core/pairs_manager.py`

Cuando un par acumula suficientes trades simulados con métricas positivas,
el sistema puede sugerir automáticamente habilitarlo para trading real.
El operador siempre confirma manualmente.

```python
MINIMUM_TRADES_FOR_AUTO = 100       # mínimo de trades simulados
MINIMUM_WINRATE_FOR_AUTO = 0.45     # winrate mínimo 45%
MINIMUM_R_MULTIPLE_FOR_AUTO = 1.5   # R múltiple promedio mínimo

async def check_auto_trade_eligibility(pair: str) -> dict:
    """
    Evalúa si un par está listo para habilitar auto-trade real.
    Se llama automáticamente cuando se cierra cada trade simulado.
    Notifica por Telegram si se alcanza el umbral.
    """
    stats = await get_pair_sim_stats(pair)

    total     = stats["total_sim"]
    winrate   = stats["ganadoras"] / total if total > 0 else 0
    r_avg     = stats.get("r_multiple_avg", 0)

    resultado = {
        "pair":           pair,
        "total_trades":   total,
        "winrate":        winrate,
        "r_multiple_avg": r_avg,
        "eligible":       False,
        "reason":         ""
    }

    if total < MINIMUM_TRADES_FOR_AUTO:
        resultado["reason"] = f"Faltan {MINIMUM_TRADES_FOR_AUTO - total} trades"
        return resultado

    if winrate < MINIMUM_WINRATE_FOR_AUTO:
        resultado["reason"] = f"Winrate {winrate:.0%} < mínimo {MINIMUM_WINRATE_FOR_AUTO:.0%}"
        return resultado

    if r_avg < MINIMUM_R_MULTIPLE_FOR_AUTO:
        resultado["reason"] = f"R múltiple {r_avg:.2f} < mínimo {MINIMUM_R_MULTIPLE_FOR_AUTO}"
        return resultado

    resultado["eligible"] = True
    resultado["reason"] = "Cumple todos los criterios"

    # Notificar al operador que el par está listo
    await notify_auto_trade_eligible(pair, resultado)

    return resultado


async def notify_auto_trade_eligible(pair: str, stats: dict) -> None:
    """
    Envía notificación a Telegram cuando un par alcanza los criterios
    para habilitar auto-trade. El operador decide si activarlo.
    """
    mensaje = f"""
🎯 PAR LISTO PARA AUTO-TRADE

📊 {pair}
✅ Trades simulados: {stats['total_trades']}
✅ Winrate: {stats['winrate']:.0%}
✅ R múltiple: {stats['r_multiple_avg']:.2f}

¿Habilitás auto-trade para este par?
"""
    # Botones inline para confirmar o rechazar
    # [ ✅ HABILITAR AUTO-TRADE ]  [ ❌ SEGUIR EN SIMULACIÓN ]
    await telegram_client.send_auto_trade_proposal(pair, mensaje, stats)
```

---

### 8. Seed actualizado — `scripts/seed_pairs.py`

Actualizar el seed para incluir los nuevos campos,
con BTC y ETH en auto-sim desde el inicio:

```python
INITIAL_PAIRS = [
    {
        "pair": "BTCUSDT", "tier": "1", "active": True,
        "sim_mode": "auto",      # ← auto-sim desde el inicio
        "auto_trade": False,
        "auto_trade_strategies": [],
        "sim_auto_enabled_at": datetime.utcnow().isoformat(),
        "sim_auto_reason": "Validación inicial del sistema",
        "sim_stats": {
            "total_sim": 0, "ganadoras": 0, "perdedoras": 0,
            "pnl_total_usd": 0.0, "r_multiple_avg": 0.0, "last_updated": None
        },
        "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce",
                       "MACDCross", "ORB", "Momentum"],
    },
    {
        "pair": "ETHUSDT", "tier": "1", "active": True,
        "sim_mode": "auto",      # ← auto-sim desde el inicio
        "auto_trade": False,
        "auto_trade_strategies": [],
        "sim_auto_enabled_at": datetime.utcnow().isoformat(),
        "sim_auto_reason": "Validación inicial del sistema",
        "sim_stats": {
            "total_sim": 0, "ganadoras": 0, "perdedoras": 0,
            "pnl_total_usd": 0.0, "r_multiple_avg": 0.0, "last_updated": None
        },
        "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce",
                       "MACDCross", "ORB", "Momentum"],
    },
    {
        "pair": "SOLUSDT", "tier": "1", "active": True,
        "sim_mode": "manual",    # ← manual — patrón menos conocido
        "auto_trade": False,
        "auto_trade_strategies": [],
        "sim_stats": {
            "total_sim": 0, "ganadoras": 0, "perdedoras": 0,
            "pnl_total_usd": 0.0, "r_multiple_avg": 0.0, "last_updated": None
        },
        "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "Momentum"],
    },
    {
        "pair": "XRPUSDT", "tier": "1", "active": True,
        "sim_mode": "manual",
        "auto_trade": False,
        "auto_trade_strategies": [],
        "sim_stats": {
            "total_sim": 0, "ganadoras": 0, "perdedoras": 0,
            "pnl_total_usd": 0.0, "r_multiple_avg": 0.0, "last_updated": None
        },
        "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "MACDCross"],
    },
    {
        "pair": "BNBUSDT", "tier": "1", "active": True,
        "sim_mode": "manual",
        "auto_trade": False,
        "auto_trade_strategies": [],
        "sim_stats": {
            "total_sim": 0, "ganadoras": 0, "perdedoras": 0,
            "pnl_total_usd": 0.0, "r_multiple_avg": 0.0, "last_updated": None
        },
        "strategies": ["EMAPullback", "SupportBounce", "MACDCross", "Momentum"],
    },
]
```

---

### 9. Tests requeridos — `tests/test_auto_sim.py`

```python
# test_scanner_auto_sim_mode
# Verificar que cuando sim_mode="auto" el scanner abre el trade
# sin enviar botones de Telegram

# test_scanner_manual_mode
# Verificar que cuando sim_mode="manual" el scanner envía botones

# test_scanner_disabled_mode
# Verificar que cuando sim_mode="disabled" solo envía notificación

# test_slippage_aplicado_en_auto_sim
# Verificar que entry_price real > signal_price en auto-sim

# test_slippage_mayor_en_manual
# Verificar que el slippage manual es mayor que el automático

# test_trailing_close_slippage
# Verificar que el cierre por trailing es levemente peor que el nivel del SL

# test_signal_drift_invalida_entrada
# Verificar que si precio se movió > 0.3% la señal se descarta

# test_update_pair_sim_stats_atomico
# Verificar que las estadísticas se actualizan correctamente en DynamoDB

# test_eligibility_check_insuficientes_trades
# Verificar que con < 100 trades no se sugiere auto-trade

# test_eligibility_check_winrate_bajo
# Verificar que con winrate < 45% no se sugiere auto-trade

# test_eligibility_check_criterios_cumplidos
# Verificar que con 100+ trades, 45%+ winrate y R 1.5+ se notifica

# test_simconfig_comando_auto
# Verificar que /simconfig BTCUSDT auto actualiza PairsTable correctamente

# test_simstatus_formato_correcto
# Verificar que /simstatus genera el mensaje con todos los pares

# test_pnl_circunstancial_positivo
# Verificar cálculo correcto cuando current_price > entry_price

# test_pnl_circunstancial_negativo
# Verificar cálculo correcto cuando current_price < entry_price

# test_pnl_circunstancial_incluye_comisiones
# Verificar que descuenta comisión de entrada pagada + estimación de salida

# test_pnl_asegurado_con_trailing
# Verificar que cuando trailing activo muestra P&L si cierra en trailing SL ahora

# test_simular_comando_sin_posiciones
# Verificar mensaje cuando no hay posiciones abiertas

# test_simular_comando_con_posiciones
# Verificar que consulta precio actual y calcula P&L circunstancial por posición

# test_simular_pnl_total
# Verificar que el P&L total es la suma de los circunstanciales individuales

# test_emoji_pnl_positivo
# Verificar que usa 📈 cuando P&L > 0

# test_emoji_pnl_negativo
# Verificar que usa 📉 cuando P&L < 0

# test_emoji_pnl_neutro
# Verificar que usa ➡️ cuando P&L está dentro de ±0.05%
```

---

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `src/lambdas/scanner/handler.py` | Leer `sim_mode` y bifurcar flujo |
| `src/lambdas/webhook/handler.py` | Nuevos comandos `/simconfig`, `/simstatus` y `/simular` con P&L circunstancial |
| `src/core/telegram_client.py` | Mensajes de auto-sim abierta/cerrada/actualización con P&L circunstancial |
| `src/core/simulator.py` | Slippage realista, trailing slippage, drift check, `calcular_pnl_circunstancial()` |
| `src/core/trades_manager.py` | `update_pair_sim_stats()` atómico, `get_all_open_trades()` |
| `src/core/pairs_manager.py` | `check_auto_trade_eligibility()` y notificación |
| `src/core/binance_client.py` | Verificar que `get_price()` soporta llamadas en paralelo con asyncio |
| `scripts/seed_pairs.py` | Campos nuevos con BTC/ETH en auto-sim |
| `tests/test_auto_sim.py` | Tests nuevos (crear archivo) |

## Archivos a NO modificar

- `src/strategies/` — las estrategias no cambian
- `src/core/market_context.py` — el evaluador de contexto no cambia
- `src/core/calculator.py` — la calculadora no cambia
- `infra/` — no hay cambios de infraestructura

---

## Comportamiento esperado después del cambio

```
ANTES:
  60+ señales detectadas → Telegram con botones → operador elige 11
  Datos recopilados: 11 trades/día (sesgados)

DESPUÉS con BTC y ETH en auto-sim:
  60+ señales detectadas
  BTC + ETH en auto-sim → todas se simulan automáticamente (~20-30/día)
  SOL + XRP + BNB en manual → operador elige cuáles simular

  Datos recopilados: ~25-35 trades/día sin sesgo
  Trades para decisión estadística: ~4-5 días en lugar de semanas
```

---

*El objetivo es llegar a 100 trades por par lo más rápido posible.*
*Con auto-sim en BTC y ETH: ~50 trades en 2-3 días.*
*Con eso tenés base estadística real para decidir si habilitar auto-trade.*
