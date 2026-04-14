# 🤖 CURSOR PROMPT — Trading Opportunity Bot (Telegram + AWS Lambda + Webhook)

---

## CONTEXTO DEL PROYECTO

Construí un **buscador de oportunidades de trading** semi-automático para operar en **Binance Spot**.

El sistema NO es un generador de señales por cuota. Es un evaluador de contexto de mercado
que actúa **solo cuando las condiciones son genuinamente favorables**. Si el mercado no da
oportunidades reales, el bot no genera nada — ese silencio es la respuesta correcta, no un fallo.

**Filosofía central:**
- Calidad sobre volumen — una buena oportunidad vale más que diez señales forzadas
- El mercado manda — si está lateral o sin volumen, se descarta el par sin forzar nada
- El operador decide — recibe la oportunidad y elige: entrar real, simular o ignorar
- En modo REAL: el operador ejecuta en Binance y Binance gestiona SL/TP/Trailing
- En modo SIM: el bot simula todo en tiempo real con precios reales de Binance

**El sistema tiene dos modos operativos que comparten el mismo scanner:**
- `REAL`: el operador abre la orden en Binance manualmente. Binance gestiona la ejecución.
  El bot recibe el cierre vía WebSocket (User Data Stream) y registra la metadata completa.
- `SIM`: el bot simula la operación completa internamente. El monitor de 60s
  con loop interno de 15s evalúa niveles y gestiona el trailing virtualmente.

---

## ARQUITECTURA COMPLETA

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 FASE 1 — DETECCIÓN DE OPORTUNIDADES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Binance REST API (OHLCV + ticker 24h)
        ↓
ScannerLambda — EventBridge rate(5 minutes)
        ↓
[A] MarketContextEvaluator por par
    ¿Tendencia? ¿Volumen? ¿ATR viable? ¿BB squeeze?
        ↓ si tradeable=True
[B] Estrategias de entrada (solo si contexto OK)
    6 estrategias independientes por par
        ↓ si hay oportunidad válida
[C] Calculadora SL estructural / TP1 / TP2 / Trailing
    Validación R/R mínimo 2.5 / SL% máximo 2%
    Validación drift de entrada (precio se movió < 0.3%)
        ↓
Telegram → mensaje con botones inline
[ 📈 ENTRAR ]  [ 🎮 SIMULAR ]  [ ❌ IGNORAR ]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 FASE 2A — MODO REAL (gestión delegada a Binance)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Operador presiona ENTRAR
        ↓
Bot registra trade en TradesTable (mode=REAL, status=OPEN)
Bot envía niveles exactos para configurar en Binance
        ↓
Operador configura en Binance:
  orden límite + OCO (SL + TP) + trailing stop
Operador confirma con [ ✅ ORDEN PUESTA ]
        ↓
Binance gestiona SL / TP / Trailing en microsegundos
(completamente independiente del bot)
        ↓
Binance User Data Stream emite ORDER_TRADE_UPDATE
        ↓
API Gateway WebSocket → BinanceEventsLambda
        ↓
Registra metadata completa en TradesTable
Notifica resultado a Telegram
        ↓
KeepAliveLambda (rate 30 min) renueva listenKey Binance

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 FASE 2B — MODO SIMULACIÓN (gestión interna del bot)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Operador presiona SIMULAR
        ↓
Bot registra trade en TradesTable (mode=SIM, status=OPEN)
entry_price = precio actual de Binance en ese instante
        ↓
PositionMonitorLambda — EventBridge rate(1 minute)
  Loop interno: 4 checks × sleep(15s) = resolución real 15s
  Consulta precio actual Binance REST cada 15s
  Evalúa SL / TP1 / TP2 / Trailing virtualmente
  Actualiza MFE y MAE continuamente
  Alerta zona de peligro si precio < 0.3% del SL
        ↓
Telegram: actualizaciones de estado + alertas de niveles
Al cierre: metadata completa en TradesTable

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 COMANDOS — WebhookLambda (API Gateway HTTP)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WebhookLambda — recibe updates de Telegram
Comandos de texto + callbacks de inline buttons
```

---

## STACK TECNOLÓGICO

- **Runtime:** Python 3.12
- **Infraestructura:** AWS Lambda + API Gateway (HTTP + WebSocket) + EventBridge
- **Región:** `ap-northeast-1` Tokyo — mínima latencia a servidores Binance (~3-8ms)
- **Dependencias:** `python-telegram-bot`, `python-binance`, `pandas`, `pandas-ta`, `numpy`
- **Secretos:** AWS SSM Parameter Store (gratuito)
- **Deploy:** AWS SAM
- **Logs:** CloudWatch — retención 7 días, nivel INFO en prod, DEBUG para condiciones de estrategias

---

## PARES A MONITOREAR — DynamoDB `PairsTable`

Los pares **no están hardcodeados**. Se leen dinámicamente en cada ciclo del scanner.

### Estructura

| Atributo | Tipo | Descripción |
|---|---|---|
| `pair` (PK) | String | Ej: `"BTCUSDT"` |
| `active` | Boolean | `true` = monitorear, `false` = pausar sin borrar |
| `tier` | String | `"1"` o `"2"` — prioridad de la oportunidad |
| `strategies` | List | Estrategias habilitadas. Ej: `["EMAPullback", "ORB"]` |
| `notes` | String | Comentario del operador (opcional) |
| `added_at` | String | ISO timestamp |

### Seed inicial — `scripts/seed_pairs.py`

```python
INITIAL_PAIRS = [
    {"pair": "BTCUSDT", "tier": "1", "active": True,
     "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "MACDCross", "ORB", "Momentum"]},
    {"pair": "ETHUSDT", "tier": "1", "active": True,
     "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "MACDCross", "ORB", "Momentum"]},
    {"pair": "SOLUSDT", "tier": "1", "active": True,
     "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "Momentum"]},
    {"pair": "XRPUSDT", "tier": "1", "active": True,
     "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "MACDCross"]},
    {"pair": "BNBUSDT", "tier": "1", "active": True,
     "strategies": ["EMAPullback", "SupportBounce", "MACDCross", "Momentum"]},
]
```

**No hay cuota diaria.** 0 oportunidades en un día es tan válido como 8.

---

## CONFIGURACIÓN DE CAPITAL Y RIESGO

```python
CAPITAL_TOTAL       = 1183.0   # USD — actualizable vía /capital
RISK_PER_TRADE_PCT  = 0.05     # 5% inicial → 10% cuando sistema validado
MIN_RR_RATIO        = 2.5      # R/R mínimo aceptado
MAX_SL_PCT          = 0.02     # SL máximo 2% desde entrada
TRAILING_ACTIVATION = 1.0      # Activar trailing cuando llega a TP1 (ratio 1:1)
TRAILING_STEP_PCT   = 0.005    # Step del trailing: 0.5%
ENTRY_DRIFT_MAX_PCT = 0.003    # Si precio se movió > 0.3% desde señal → recalcular R/R

# Timeframes recomendados por compatibilidad con scanner de 5 min:
# M30 → ventana perdida máxima 17% de la vela ✅ recomendado
# H1  → ventana perdida máxima  8% de la vela ✅ ideal
# M15 → ventana perdida máxima 33% de la vela ⚠️ aceptable, SL estructural absorbe drift
# El SL estructural con margen suficiente absorbe imperfección de entrada de ±0.2-0.3%
# sin invalidar el setup — el problema es cuando el setup es tan frágil que no aguanta
```

---

## MOTOR DE EJECUCIÓN — Flujo del Scanner (cada 5 min)

```
1. Leer pares activos de PairsTable
2. Para cada par:

   ── FASE 1: CONTEXTO ──────────────────────────────────────
   a. Pedir OHLCV a Binance (últimas 100 velas, todos los TF necesarios)
   b. enrich_dataframe() — calcular TODOS los indicadores una sola vez
   c. MarketContextEvaluator.evaluate() → MarketContext
   d. Si tradeable=False → skip silencioso, loguear razón

   ── FASE 2: ESTRATEGIAS (solo si contexto OK) ──────────────
   e. Para cada estrategia habilitada en el par:
      - try/except independiente (fallo de una no afecta las otras)
      - Evaluar condiciones booleanas en secuencia con nombre
      - Loguear qué condición falló (para debugging y optimización)
      - Si todas pasan → construir Opportunity con SL/TP calculados
   f. Descartar si R/R < MIN_RR_RATIO
   g. Descartar si sl_pct > MAX_SL_PCT
   h. Verificar cooldown en SignalsTable (45 min por par+estrategia)
   i. Detectar confluencias (2+ estrategias mismo par)

   ── FASE 3: VALIDACIÓN DE DRIFT DE ENTRADA ────────────────
   j. Comparar precio de señal vs precio actual de Binance
   k. Si diferencia <= 0.3% → notificar normalmente
   l. Si diferencia > 0.3% → recalcular R/R con precio actual
      - Si R/R nuevo >= MIN_RR_RATIO → notificar con precio actualizado y nota
      - Si R/R nuevo < MIN_RR_RATIO → descartar silenciosamente (el momento pasó)

   ── FASE 4: NOTIFICACIÓN ──────────────────────────────────
   m. Enviar oportunidades válidas a Telegram con inline buttons
   n. Silencio en cualquier otro caso
```

**Regla de oro: el bot solo habla cuando tiene algo genuinamente útil que decir.**

---

## EVALUADOR DE CONTEXTO — `core/market_context.py`

```python
@dataclass
class MarketContext:
    pair: str
    trend: str          # "BULLISH" | "BEARISH" | "SIDEWAYS"
    volatility: str     # "HIGH" | "MEDIUM" | "LOW"
    volume_state: str   # "ACTIVE" | "QUIET"
    atr_viable: bool    # ATR suficiente para ratio 3:1 dentro de MAX_SL_PCT
    bb_squeeze: bool    # True = Bollinger Bands apretadas (rango muerto)
    tradeable: bool     # True solo si TODAS las condiciones son favorables
    reason: str         # Descripción legible para logs y /contexto


class MarketContextEvaluator:
    @staticmethod
    def evaluate(df: pd.DataFrame, pair: str) -> MarketContext:

        # 1. TENDENCIA
        ema21  = df["EMA_21"].iloc[-1]
        ema50  = df["EMA_50"].iloc[-1]
        close  = df["close"].iloc[-1]
        if ema21 > ema50 and close > ema21:    trend = "BULLISH"
        elif ema21 < ema50 and close < ema21:  trend = "BEARISH"
        else:                                   trend = "SIDEWAYS"

        # 2. VOLATILIDAD — ATR actual vs promedio 20 períodos
        atr_current = df["ATRr_14"].iloc[-1]
        atr_avg     = df["ATRr_14"].rolling(20).mean().iloc[-1]
        ratio = atr_current / atr_avg
        if ratio > 1.3:    volatility = "HIGH"
        elif ratio > 0.7:  volatility = "MEDIUM"
        else:              volatility = "LOW"

        # 3. VOLUMEN
        vol_avg      = df["volume"].rolling(20).mean().iloc[-1]
        volume_state = "ACTIVE" if df["volume"].iloc[-1] > vol_avg * 1.1 else "QUIET"

        # 4. ATR VIABLE para ratio 3:1 sin superar MAX_SL_PCT
        atr_viable = (atr_current * 0.5) <= MAX_SL_PCT

        # 5. BOLLINGER BANDS SQUEEZE
        bb_width   = (df["BBU_20_2.0"] - df["BBL_20_2.0"]) / df["BBM_20_2.0"]
        bb_squeeze = bb_width.iloc[-1] < bb_width.rolling(20).mean().iloc[-1] * 0.7

        # Solo operar LONG en spot → solo BULLISH habilita operaciones
        tradeable = (
            trend == "BULLISH" and
            volatility in ("MEDIUM", "HIGH") and
            volume_state == "ACTIVE" and
            atr_viable and
            not bb_squeeze
        )

        return MarketContext(pair=pair, trend=trend, volatility=volatility,
            volume_state=volume_state, atr_viable=atr_viable,
            bb_squeeze=bb_squeeze, tradeable=tradeable,
            reason=_build_reason(trend, volatility, volume_state, atr_viable, bb_squeeze))
```

---

## INDICADORES — `core/indicators.py`

Calculados **una sola vez** por DataFrame antes de correr cualquier estrategia:

```python
def enrich_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df.ta.ema(length=21, append=True)    # EMA_21
    df.ta.ema(length=50, append=True)    # EMA_50
    df.ta.rsi(length=14, append=True)    # RSI_14
    df.ta.macd(append=True)              # MACD_12_26_9, MACDs_12_26_9, MACDh_12_26_9
    df.ta.atr(length=14, append=True)    # ATRr_14
    df.ta.bbands(append=True)            # BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
    return df
```

---

## ESTRATEGIAS A IMPLEMENTAR

```python
class BaseStrategy(ABC):
    name: str
    timeframes: list[str]

    @abstractmethod
    def analyze(self, df: pd.DataFrame, pair: str) -> "Opportunity | None": ...

    def _check_conditions(self, conditions: list[tuple[str, bool]]) -> bool:
        for name, result in conditions:
            if not result:
                logger.debug(f"[{self.name}] Falló: {name}")
                return False
        return True

STRATEGY_REGISTRY = {
    "EMAPullback":   EMAPullbackStrategy(),
    "RangeBreakout": RangeBreakoutStrategy(),
    "SupportBounce": SupportBounceStrategy(),
    "MACDCross":     MACDCrossStrategy(),
    "ORB":           ORBStrategy(),
    "Momentum":      MomentumContinuationStrategy(),
}
```

### Estrategia 1 — Pullback a EMA (`EMAPullbackStrategy`)
**TF:** M15, M30
1. EMA21 > EMA50 y precio > EMA21 (tendencia alcista confirmada)
2. Precio retrocede y toca la EMA21
3. Vela de confirmación cierra por encima de EMA21 con cuerpo alcista
4. Entrada: close de la vela de confirmación
5. SL: mínimo de las últimas 3 velas (estructural)
6. TP1: entrada + riesgo × 1.5 | TP2: entrada + riesgo × 3.0

### Estrategia 2 — Ruptura de rango (`RangeBreakoutStrategy`)
**TF:** M15, H1
1. Últimas 10 velas con ATR bajo (rango lateral detectado)
2. Precio cierra por encima de la resistencia del rango
3. Volumen > 1.5× promedio 20 velas
4. Entrada: close de la vela de ruptura
5. SL: mínimo del rango (acepta 1.3-1.5% si es estructural)
6. TP1/TP2: proyección de altura del rango × 1.5 y × 3.0

### Estrategia 3 — Rebote en soporte (`SupportBounceStrategy`)
**TF:** M15, M30
1. Soporte horizontal con ≥ 2 toques en últimas 50 velas
2. RSI(14) < 35 cuando toca el soporte
3. Vela de confirmación alcista con mecha inferior ≥ 60% del rango
4. Entrada: close de la vela de confirmación
5. SL: 0.2% por debajo del soporte identificado
6. TP1/TP2: siguiente resistencia relevante y proyección 3:1

### Estrategia 4 — Cruce MACD (`MACDCrossStrategy`)
**TF:** M30, H1
1. Cruce alcista MACD sobre señal por debajo de la línea cero
2. Precio > EMA50 (tendencia de fondo alcista)
3. Entrada: apertura de la vela siguiente al cruce
4. SL: mínimo de las últimas 5 velas
5. TP: ratio 3:1 desde el SL

### Estrategia 5 — Opening Range Breakout (`ORBStrategy`)
**TF:** M15 | **Válida solo:** 00:00-06:00 UTC
1. Rango de las primeras 4 velas del día (00:00-01:00 UTC)
2. Ruptura del máximo con volumen > 1.3× promedio
3. Entrada: close de la vela de ruptura
4. SL: mínimo del rango de apertura
5. TP: altura del rango × 2.0 y × 3.0

### Estrategia 6 — Continuación de impulso (`MomentumContinuationStrategy`)
**TF:** M15, M30
1. 3 velas alcistas consecutivas con cuerpo > 60% del rango
2. Pullback de 1-2 velas corrigiendo máximo 38.2%
3. Vela de reanudación cierra sobre el máximo del pullback
4. RSI(14) entre 50-70 (momentum sin sobrecompra)
5. SL: mínimo del pullback
6. TP: extensiones Fibonacci 1.5 y 2.618 del impulso

---

## CALCULADORA DE SETUP

```python
@dataclass
class Opportunity:
    pair: str
    strategy: str
    timeframe: str
    direction: str               # "LONG"
    entry_price: float           # precio de la señal
    entry_actual_price: float    # precio actual al momento de notificar (puede diferir)
    sl_price: float
    sl_pct: float
    sl_type: str                 # "bajo soporte $82,650" | "bajo EMA21" | etc.
    tp1_price: float
    tp2_price: float
    trailing_activation: float
    trailing_step_pct: float
    position_size_usd: float
    risk_usd: float
    reward_usd: float
    rr_ratio: float              # calculado con entry_actual_price
    market_context: MarketContext
    confluence: bool
    timestamp: datetime

# Cálculos:
# risk_usd        = CAPITAL_TOTAL × RISK_PER_TRADE_PCT
# position_size   = risk_usd / sl_pct
# rr_ratio        = (tp2 - entry_actual) / (entry_actual - sl)
# Descartar si rr_ratio < MIN_RR_RATIO
# Descartar si sl_pct > MAX_SL_PCT
# Si |entry_actual - entry_signal| / entry_signal > ENTRY_DRIFT_MAX_PCT → recalcular
```

---

## FILTROS DE CALIDAD

```python
FILTERS = {
    "min_volume_ratio":    1.2,   # volumen actual vs promedio 20 velas
    "min_body_ratio":      0.4,   # cuerpo de vela vs rango total
    "cooldown_minutes":    45,    # no repetir par+estrategia antes de N min
    "max_concurrent_open": 3,     # máximo 3 posiciones abiertas simultáneas
    "entry_drift_max_pct": 0.003, # recalcular R/R si precio se movió > 0.3%
}
```

---

## SCHEMA COMPLETO — `TradesTable` (análisis post mortem)

```python
@dataclass
class Trade:
    # ── IDENTIFICACIÓN ──────────────────────────────────────────
    trade_id: str              # UUID
    mode: str                  # "REAL" | "SIM"
    status: str                # "OPEN" | "CLOSED"

    # ── PAR Y ESTRATEGIA ────────────────────────────────────────
    pair: str                  # "BTCUSDT"
    timeframe: str             # "15m" | "30m" | "1h"
    strategy: str              # "EMAPullback"
    tier: str                  # "1" | "2"

    # ── CONTEXTO DE MERCADO AL ENTRAR ───────────────────────────
    market_trend: str          # "BULLISH" | "SIDEWAYS" | "BEARISH"
    market_volatility: str     # "HIGH" | "MEDIUM" | "LOW"
    volume_state: str          # "ACTIVE" | "QUIET"
    atr_at_entry: float        # valor ATR exacto al abrir
    btc_trend_at_entry: str    # tendencia BTC si el par no es BTC
    session: str               # "ASIA" | "LONDON" | "NEW_YORK" | "OVERLAP"
    confluence: bool           # True si 2+ estrategias coincidieron

    # ── SETUP TÉCNICO ────────────────────────────────────────────
    entry_signal_price: float  # precio cuando se detectó la oportunidad
    entry_price: float         # precio real de entrada (puede diferir de la señal)
    sl_initial: float          # SL original al abrir (nunca cambia — para calcular R/R real)
    sl_final: float            # SL al cierre (puede haber sido movido por trailing)
    sl_type: str               # "bajo soporte" | "bajo EMA21" | "bajo mínimo rango"
    sl_pct: float              # % de distancia SL desde entrada real
    tp1_price: float
    tp2_price: float
    rr_ratio_planned: float    # R/R calculado al abrir

    # ── CAPITAL ──────────────────────────────────────────────────
    capital_at_open: float     # capital total al momento de abrir
    risk_pct: float            # 0.05 o 0.10
    risk_usd: float            # capital en riesgo
    position_size_usd: float   # tamaño total de la posición
    amount_invested: float     # igual que position_size_usd

    # ── EJECUCIÓN ─────────────────────────────────────────────────
    signal_sent_at: str        # ISO — cuándo se detectó y notificó la oportunidad
    entry_confirmed_at: str    # ISO — cuándo el operador confirmó entrada
    slippage_pct: float        # diferencia señal vs entrada real (0.0 en SIM)

    # ── RESULTADO ─────────────────────────────────────────────────
    exit_price: float          # precio de salida
    amount_final: float        # capital recuperado al cerrar
    gross_pnl_usd: float       # P&L bruto
    commission_usd: float      # comisión Binance: 0.1% entrada + 0.1% salida
    net_pnl_usd: float         # P&L neto después de comisiones
    r_multiple: float          # +3.0 ganadora | -1.0 perdedora | +1.5 trailing
    rr_ratio_actual: float     # R/R real logrado vs el planeado

    # ── ANÁLISIS DE RECORRIDO — MFE y MAE ─────────────────────────
    # MFE (Maximum Favorable Excursion): precio máximo favorable alcanzado
    # Si MFE promedio supera TP2 → TP2 puede ser más agresivo
    max_favorable_excursion: float
    max_favorable_excursion_at: str    # ISO timestamp del MFE

    # MAE (Maximum Adverse Excursion): precio más adverso antes de recuperar
    # Si MAE promedio de ganadoras es 0.3% → SL puede ajustarse más cerca
    max_adverse_excursion: float
    max_adverse_excursion_at: str      # ISO timestamp del MAE

    # ── TRAILING STOP ─────────────────────────────────────────────
    tp1_hit: bool                      # ¿llegó a TP1?
    tp1_hit_at: str                    # ISO timestamp exacto
    trailing_activated: bool           # ¿se activó el trailing?
    trailing_activation_price: float   # precio donde se activó
    trailing_sl_final: float           # último nivel del trailing SL al cierre
    trailing_updates_count: int        # cuántas veces se actualizó el trailing

    # ── CIERRE ────────────────────────────────────────────────────
    close_reason: str          # "TP2" | "TP1_TRAILING" | "SL" | "MANUAL" | "TRAILING_SL"
    started_at: str            # ISO apertura
    ended_at: str              # ISO cierre
    duration_minutes: int      # duración total de la operación

    # ── VOLUMEN DEL PAR ───────────────────────────────────────────
    pair_volume_24h: float     # volumen 24h del par al momento de entrada
    pair_volume_at_entry: float # volumen de la vela de entrada específica

    # ── METADATA TÉCNICA ──────────────────────────────────────────
    telegram_message_id: int   # para editar el mensaje original
    binance_order_id: str      # ID de la orden en Binance (solo mode=REAL)
    ttl: int                   # expiración DynamoDB: 90 días (7776000 segundos)
```

### Preguntas que habilita este schema (con 3 meses de datos)

- ¿Qué estrategia tiene mejor winrate? ¿Y mejor R múltiple promedio?
- ¿En qué sesión (Asia/London/NY) el sistema rinde mejor?
- ¿Las confluencias son estadísticamente mejores que las señales únicas?
- ¿Cuándo BTC está lateral, las altcoins pierden más?
- ¿El MAE promedio de las ganadoras justifica ajustar el SL más cerca?
- ¿Cuánto cuesta el slippage en modo real vs la simulación?
- ¿Qué timeframe da mejor R múltiple por estrategia?
- ¿El trailing captura más ganancia que cerrar en TP2 fijo?
- ¿En qué condición de volatilidad (HIGH/MEDIUM) rinde mejor cada estrategia?

---

## SISTEMA DE SIMULACIÓN EN TIEMPO REAL

### PositionMonitorLambda — lógica completa

```python
def handler(event, context):
    # EventBridge dispara cada 60 segundos
    # Loop interno para resolución real de 15 segundos:
    for check in range(4):
        open_sims = trades_manager.get_open_sims()
        for trade in open_sims:
            current_price = binance_client.get_price(trade.pair)
            simulator.evaluate(trade, current_price)
        time.sleep(15)
    # Timeout del Lambda: 58s (el loop 4×15s cabe con margen)
    # Costo adicional vs 60s simple: ~$0.40/mes


def evaluate(trade: Trade, current_price: float) -> None:

    # 1. Actualizar MFE y MAE continuamente
    if current_price > trade.max_favorable_excursion:
        update_mfe(trade, current_price)
    if current_price < trade.max_adverse_excursion:
        update_mae(trade, current_price)

    # 2. Alerta zona de peligro antes de tocar SL
    sl_active = trade.trailing_sl_final if trade.trailing_activated else trade.sl_initial
    distance_to_sl_pct = (current_price - sl_active) / trade.entry_price
    if distance_to_sl_pct < 0.003 and not trade.danger_zone_notified:
        notify_danger_zone(trade, current_price, sl_active)

    # 3. Trailing activo
    if trade.trailing_activated:
        new_trailing_sl = current_price * (1 - TRAILING_STEP_PCT)
        if new_trailing_sl > trade.trailing_sl_final:
            update_trailing_sl(trade, new_trailing_sl)
            notify_trailing_update(trade, new_trailing_sl, current_price)
        if current_price <= trade.trailing_sl_final:
            close_trade(trade, current_price, "TRAILING_SL")
            return

    # 4. Evaluar niveles en orden
    if not trade.trailing_activated and current_price <= trade.sl_initial:
        close_trade(trade, current_price, "SL")
    elif not trade.tp1_hit and current_price >= trade.tp1_price:
        hit_tp1(trade, current_price)      # SL → entrada, trailing ON
    elif trade.tp1_hit and current_price >= trade.tp2_price:
        close_trade(trade, current_price, "TP2")
```

### Mensajes Telegram durante simulación

```
── apertura ──────────────────────────────
🎮 [SIM] BTC/USDT ABIERTO
Entrada: $83,200 | SL: $82,650 | TP1: $84,025 | TP2: $85,850
P&L: $0.00 (0.00%)

── zona de peligro ───────────────────────
⚠️ [SIM] BTC/USDT — CERCA DEL SL
Precio: $82,680 | SL: $82,650 (a $30 / 0.04%)

── actualización cada 60s ────────────────
📊 [SIM] BTC/USDT
Precio: $83,580 | P&L: +$2.56 (+0.46%)
SL: $82,650 | TP1: $84,025 (falta $445)

── TP1 alcanzado ─────────────────────────
✅ [SIM] TP1 — BTC/USDT
Precio: $84,028 | P&L parcial: +$4.90
SL movido a entrada: $83,200 (breakeven)
🔄 Trailing activado | step 0.5%

── trailing actualizado ──────────────────
🔄 [SIM] TRAILING — BTC/USDT
Nuevo SL: $84,920 | Precio: $85,350
P&L asegurado: +$102.00

── TP2 ───────────────────────────────────
🏆 [SIM] TP2 ALCANZADO — BTC/USDT
Precio: $85,872 | P&L neto: +$177.45 (+3.18%)
R múltiple: +3.0 | Duración: 2h 14min
Capital simulado: $1,360.45 ✅ GANADORA

── SL ────────────────────────────────────
🛑 [SIM] SL EJECUTADO — BTC/USDT
Precio: $82,648 | P&L neto: -$59.15 (-5.0%)
R múltiple: -1.0 | Duración: 47min
Capital simulado: $1,123.85 ❌ PÉRDIDA
```

Botones activos durante la simulación:
```
[ 🔴 CERRAR AHORA ]   [ 📊 RESUMEN ]
```

---

## MODO REAL — Integración Binance User Data Stream

```
1. Operador presiona ENTRAR
2. Bot registra trade (mode=REAL, status=OPEN)
3. Bot envía mensaje con niveles para configurar en Binance:
   ┌────────────────────────────────────────┐
   │ Configurá en Binance:                  │
   │ Entrada límite:  $83,200.00            │
   │ OCO Stop Loss:   $82,650.00            │
   │ OCO Take Profit: $84,025.00 (TP1)      │
   │ Trailing stop:   0.5% desde TP1        │
   └────────────────────────────────────────┘
   [ ✅ ORDEN PUESTA ]

4. Operador configura en Binance y presiona [ ✅ ORDEN PUESTA ]
5. Bot registra entry_confirmed_at y espera eventos de Binance

── Binance ejecuta todo en tiempo real ──────

6. Binance User Data Stream → ORDER_TRADE_UPDATE
7. API Gateway WebSocket → BinanceEventsLambda
8. BinanceEventsLambda:
   - Parsea el evento de Binance
   - Determina close_reason desde el tipo de orden ejecutada
   - Registra metadata completa en TradesTable
   - Calcula comisiones reales (del evento de Binance)
   - Notifica resultado a Telegram
```

### KeepAliveLambda

```python
# EventBridge rate(30 minutes)
# El listenKey de Binance expira cada 60 min → renovar cada 30
def handler(event, context):
    listen_key = ssm.get_parameter("/trading-bot/BINANCE_LISTEN_KEY")
    binance_client.keepalive_user_data_stream(listen_key)
    logger.info("listenKey renovado")
```

---

## FORMATO DEL MENSAJE DE OPORTUNIDAD

```
🎯 OPORTUNIDAD DETECTADA  🔥 CONFLUENCIA

📊 BTC/USDT  |  M30
📈 Estrategia: Pullback EMA + MACD Cross
🌡 Contexto: Alcista | Vol. Media | Volumen activo

──────────────────────────────────
🎯 Entrada:    $83,200.00
🛑 SL:         $82,650.00  (-0.66%)  ← bajo soporte
✅ TP1:        $84,025.00  (+0.99%)  → mover SL a entrada
🏆 TP2:        $85,850.00  (+3.18%)
📐 R/R:        1 : 3.2
🔄 Trailing:   desde TP1 | step 0.5%

──────────────────────────────────
💰 Capital:    5%  →  $59.15
📦 Posición:   $8,962 en BTC
⚠️  Riesgo máx: $59.15

⏰ 14:32 UTC  |  Sesión: LONDON
──────────────────────────────────

   [ 📈 ENTRAR ]   [ 🎮 SIMULAR ]   [ ❌ IGNORAR ]
```

---

## COMANDOS DE TELEGRAM

| Comando | Función |
|---|---|
| `/capital 1350` | Actualizar capital total |
| `/riesgo 10` | Cambiar % de riesgo (5 o 10) |
| `/contexto` | Estado del mercado por par en tiempo real |
| `/status` | Config actual + posiciones abiertas + P&L del día |
| `/resumen` | Oportunidades del día: entradas real/sim/ignoradas |
| `/historial` | Últimas 20 operaciones cerradas con resultado |
| `/rendimiento` | Winrate y R múltiple por estrategia, sesión y modo |
| `/pausar` | Pausar detección de oportunidades |
| `/reanudar` | Reanudar |
| `/calcular BTCUSDT 83200 82650` | Calcular setup manual |
| `/pares` | Listar pares activos con estrategias |
| `/agregar SOLUSDT` | Agregar par nuevo |
| `/pausarpar BNBUSDT` | Pausar par |
| `/activarpar BNBUSDT` | Reactivar par |
| `/estrategias BTCUSDT` | Ver estrategias activas de un par |
| `/simular` | Ver simulaciones abiertas |
| `/confirmado BTCUSDT` | Confirmar que orden real fue puesta en Binance |

### `/contexto`
```
📊 CONTEXTO DE MERCADO ACTUAL
──────────────────────────────────────
BTC/USDT  ✅ OPERABLE   Alcista | Vol.Media | Activo
ETH/USDT  ✅ OPERABLE   Alcista | Vol.Alta  | Activo
SOL/USDT  ⏸ EN ESPERA  Lateral | Vol.Baja  | BB squeeze
XRP/USDT  ⏸ EN ESPERA  Lateral | Vol.Media | Volumen bajo
BNB/USDT  ✅ OPERABLE   Alcista | Vol.Media | Activo

Próxima evaluación: 3 min
```

### `/rendimiento`
```
📈 RENDIMIENTO ACUMULADO
──────────────────────────────────────
Capital inicial:  $1,183.00
Capital actual:   $1,847.50  (+56.2%)

REAL  Win: 8/14 (57%) | R prom: +1.8 | P&L: +$312.40
SIM   Win: 22/38 (58%) | R prom: +1.9 | P&L: +$352.10

Por estrategia:
  EMAPullback    62% | R: +2.1  ✅
  SupportBounce  58% | R: +1.8  ✅
  MACDCross      51% | R: +1.4
  RangeBreakout  47% | R: +1.2  ⚠️

Por sesión:
  LONDON      65% ← mejor sesión
  NEW_YORK    58%
  ASIA        44% ← considerar pausar
```

---

## ESTRUCTURA DE ARCHIVOS

```
trading-bot/
├── template.yaml                      # AWS SAM — 5 Lambdas + 5 tablas + 2 API Gateways
├── requirements.txt
├── src/
│   ├── lambdas/
│   │   ├── scanner/
│   │   │   └── handler.py             # Cron 5 min — contexto + oportunidades
│   │   ├── webhook/
│   │   │   └── handler.py             # Webhook Telegram — comandos y callbacks
│   │   ├── position_monitor/
│   │   │   └── handler.py             # Cron 60s + loop 4×15s — solo modo SIM
│   │   ├── binance_events/
│   │   │   └── handler.py             # WebSocket Binance — solo modo REAL
│   │   └── keepalive/
│   │       └── handler.py             # Cron 30 min — renueva listenKey Binance
│   ├── strategies/
│   │   ├── base.py                    # BaseStrategy + Opportunity + STRATEGY_REGISTRY
│   │   ├── ema_pullback.py
│   │   ├── range_breakout.py
│   │   ├── support_bounce.py
│   │   ├── macd_cross.py
│   │   ├── orb.py
│   │   └── momentum.py
│   ├── core/
│   │   ├── binance_client.py          # REST API — OHLCV + precio actual
│   │   ├── binance_stream.py          # User Data Stream — parsing de eventos
│   │   ├── indicators.py              # enrich_dataframe()
│   │   ├── market_context.py          # MarketContextEvaluator
│   │   ├── calculator.py              # Calculadora SL/TP/Trailing/Posición + drift
│   │   ├── filters.py                 # Filtros de calidad + drift de entrada
│   │   ├── simulator.py               # MFE/MAE/trailing/niveles/zona de peligro
│   │   ├── state.py                   # DynamoDB — cooldowns, config
│   │   ├── pairs_manager.py           # CRUD PairsTable
│   │   ├── trades_manager.py          # CRUD TradesTable — schema completo
│   │   └── telegram_client.py         # Mensajes, inline buttons, editar mensajes
│   └── config.py
├── tests/
│   ├── test_strategies.py
│   ├── test_market_context.py         # fixtures: bullish, sideways, bb_squeeze
│   ├── test_calculator.py             # incluye test de drift de entrada
│   ├── test_simulator.py              # ganadora completa, perdedora, trailing, zona peligro
│   ├── test_filters.py
│   └── fixtures/
│       ├── ohlcv_bullish.json
│       ├── ohlcv_sideways.json
│       └── ohlcv_bearish.json
└── scripts/
    ├── seed_pairs.py
    └── deploy.sh
```

---

## INFRAESTRUCTURA AWS SAM (template.yaml)

```
ScannerFunction:         256MB | 60s  | EventBridge rate(5 minutes)
WebhookFunction:         128MB | 15s  | API Gateway HTTP POST /webhook
PositionMonitorFunction: 128MB | 58s  | EventBridge rate(1 minute) — solo SIM
BinanceEventsFunction:   128MB | 15s  | API Gateway WebSocket $default — solo REAL
KeepAliveFunction:       128MB | 10s  | EventBridge rate(30 minutes)

PairsTable:    PK: pair | Sin TTL | PAY_PER_REQUEST
SignalsTable:  PK: pair#strategy | SK: timestamp | TTL: 86400
TradesTable:   PK: trade_id | GSI: status-index | TTL: 7776000 (90 días)
ConfigTable:   PK: key
StreamTable:   PK: connection_id  # estado del WebSocket Binance

SSM Parameter Store (gratuito):
  /trading-bot/BINANCE_API_KEY
  /trading-bot/BINANCE_SECRET
  /trading-bot/TELEGRAM_BOT_TOKEN
  /trading-bot/TELEGRAM_CHAT_ID
  /trading-bot/BINANCE_LISTEN_KEY
```

---

## COSTO ESTIMADO MENSUAL

```
ScannerFunction       8,640 inv × 15s × 256MB   → $0.18
PositionMonitor      43,200 inv × 58s × 128MB   → $0.55
WebhookFunction         ~500 inv                 → $0.00
BinanceEventsFunction   ~500 inv                 → $0.00
KeepAliveFunction      1,440 inv × 1s            → $0.00
API Gateway HTTP                                  → $0.00
API Gateway WebSocket  720hs conexión             → $0.18
DynamoDB               5 tablas                  → $0.15
SSM Parameter Store                               → $0.00
CloudWatch Logs        7 días retención           → $0.20
────────────────────────────────────────────────────────
TOTAL:                                           ~$1.26/mes
```

---

## REGLAS DE IMPLEMENTACIÓN

1. Cada estrategia es completamente independiente — fallo en una no afecta las otras
2. Sin estado en Lambda — todo el estado vive en DynamoDB
3. Logs estructurados: INFO para oportunidades, ERROR para fallos, DEBUG para condiciones de estrategias
4. SL siempre estructural — la calculadora ajusta el tamaño de posición según el SL, nunca al revés
5. Retry con backoff exponencial (3 intentos) si Binance REST API falla
6. Solo operaciones LARGO — spot puro
7. Hardcap de 10% de capital por operación — no superable aunque el usuario configure más
8. Validar drift de entrada ANTES de notificar — recalcular R/R con precio actual
9. MFE y MAE se actualizan en cada check del monitor, no solo al cierre
10. `binance_order_id` se registra en REAL para poder reconciliar si hay discrepancia
11. Typing y dataclasses en todo el proyecto
12. Cada Lambda tiene su propio `requirements.txt` con dependencias mínimas

---

## ENTREGABLES ESPERADOS

- [ ] `sam deploy` en región `ap-northeast-1` Tokyo
- [ ] `scripts/seed_pairs.py` pobla `PairsTable` post-deploy
- [ ] Webhook Telegram registrado automáticamente al deploy
- [ ] Scanner: contexto primero, estrategias solo si tradeable=True
- [ ] Validación de drift de entrada antes de notificar
- [ ] Modo SIM: loop 4×15s, MFE/MAE, trailing, alertas zona de peligro, cierre con metadata completa
- [ ] Modo REAL: User Data Stream, cierre registrado desde evento Binance, comisiones reales
- [ ] KeepAlive renueva listenKey cada 30 minutos
- [ ] `/rendimiento` muestra winrate y R múltiple por estrategia, sesión y modo
- [ ] `/contexto` muestra estado de mercado en tiempo real
- [ ] Tests con fixtures bullish/sideways/bearish y simulaciones completas
- [ ] `README.md` con configuración, deploy, seed y uso

---

*Capital inicial: $1,183 USDT en Binance Spot.*
*No es un generador de señales — es un detector de oportunidades reales.*
*El silencio del bot es tan válido como una oportunidad. El mercado manda.*
*El historial de trades con metadata completa es el activo más valioso del sistema.*
