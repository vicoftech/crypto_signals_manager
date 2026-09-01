# SPEC — Protección de escalera verificada en Binance (SL / BE / TP1…TPn)

**Fecha:** 2026-09-01  
**Estado:** implementado (2026-09-01)  
**Prioridad:** P0 — incidente RUNE/SNX cohorte 56 (−$42 en 2 trades con `SL_TP1`/`SL_TP3` y fill ~−3R)  
**Relacionado:** `spec-wr-55-65-ladder-be-timestop.md`, cohorte 60 RangeBreakout-only

---

## 1. Problema

Hoy la escalera **existe en Dynamo** (`active_stop_price`, `ladder_level`) pero la protección en Binance es **best-effort**:

| Síntoma | Evidencia cohorte 56 |
|--------|----------------------|
| Cierre etiquetado `SL_TP1` / `SL_TP3` con PnL de **−3R** | RUNE, SNX 2026-08-22 |
| `binance_stop_order_id` **vacío** al cierre | Sin STOP activo en exchange |
| Cierre vía `binance_exit_order_id` (MARKET) | Fill lejos del piso teórico |
| Sync fallido → fallback MARKET silencioso | `position_monitor` L318–337 |

**Conclusión:** no es un bug genérico de Binance; es **desalineación libro ↔ exchange** + fallback MARKET agresivo.

---

## 2. Principio rector — paridad Dynamo ↔ Binance

**Espíritu de esta spec:** el trade OPEN debe tener **el mismo estado de protección** en DynamoDB y en Binance. No son dos verdades independientes.

| Regime | Dynamo | Binance | ¿Válido? |
|--------|--------|---------|----------|
| **Steady state** | `protection_level=TP2`, `active_stop=0.289` | 1× STOP SELL @ 0.289, qty = base | **Sí — objetivo normal** |
| **Transición** | ya actualizado a TP2 | cancel SL/TP1 en vuelo; STOP TP2 aún no verificado | **Sí — breve** (`pending`, segundos–1 ciclo) |
| **Roto** | Dynamo dice TP3 @ 0.292 | open orders vacío o STOP @ 0.279 | **No — bug / incidente** |
| **Roto** | `ladder_level=3` | sin orden protectora | **No — causó RUNE/SNX** |

### 2.1 Invariante de paridad (steady state)

Para cada trade `OPEN` con `protection_sync_status=synced`:

```text
Dynamo.active_stop_price     ≈ Binance.openOrder.stopPrice   (±1 tick)
Dynamo.protection_level      ↔  tipo de piso (SL/BE/TPn)
Dynamo.base_qty              ≈ Binance.openOrder.origQty     (±1 step)
Dynamo.protection_order_id   =  Binance.openOrder.orderId
```

Solo puede existir **una** orden protectora SELL (STOP u OCO stop leg) por trade en Binance.

### 2.2 Divergencia temporal permitida

Durante **cancel → place → verify** (transición):

- Dynamo puede pasar a `protection_sync_status=pending` **antes** de confirmar Binance.
- Ventana esperada: **< 30 s** (mismo ciclo monitor) o **≤ 1 ciclo** (~5 min) con reintentos.
- Mientras `pending`: no se asume paridad; no se cierra por MARKET en escalera.
- Al terminar verify OK → `synced` (paridad restaurada).

Si `pending` o `failed` persiste **> 15 min** en trade OPEN → alerta admin (paridad rota demasiado tiempo).

### 2.3 Fuente de verdad

| Fase | Fuente de verdad para **precio de salida** | Fuente de verdad para **estado** |
|------|-------------------------------------------|----------------------------------|
| Steady state | Binance (orden activa) | **Ambos iguales** — Dynamo es caché verificada |
| Transición | — | Binance manda al confirmar verify |
| Cierre | Fill real (`binance_events`) | Dynamo actualizado post-fill |

Dynamo **no** avanza `ladder_level` / `active_stop_price` sin encolar reconcile hacia ese target (o marcar `pending` explícitamente).

### 2.4 Reconciliación continua

Cada ciclo del `position_monitor` (trade OPEN):

1. Leer Dynamo (target: level + stop price).
2. Leer Binance (`openOrders` + `get_order` si hace falta).
3. Si difieren y no hay transición en curso → **reconcile** hacia Dynamo target.
4. Si no se puede alinear → `failed` + alerta; **no** operar como si estuvieran iguales.

Objetivo operativo: **≥ 95% del tiempo** de vida de un trade OPEN en `synced` (métrica `protection_parity_ratio` en logs).

---

## 3. Objetivo (implementación)

Sistema **resiliente y verificable** que:

1. Coloque en Binance **exactamente una** orden de salida protectora vigente (SL inicial, BE o piso TPn).
2. **Cancele** la orden anterior al subir de nivel (SL→BE, BE→TP1, TP1→TP2, …).
3. **Verifique** contra Binance que la nueva orden está `NEW`/`PARTIALLY_FILLED` y la anterior ya no existe.
4. Si falla: **reintentos** con backoff → reintento en ciclos siguientes → **alerta Telegram admin** clara.
5. **Prohibido** cerrar `SL` / `BE` / `SL_TP*` por MARKET si no hay STOP confirmado en exchange (salvo TIME_STOP / admin explícito).
6. Mantener **paridad Dynamo ↔ Binance** en steady state; divergencia solo en transiciones acotadas.

---

## 4. Modelo de niveles (ejemplo)

Entry **0.283**, R ≈ **0.003** (SL ~1%).

| Nivel | Precio (ej.) | Rol en exchange |
|-------|--------------|-----------------|
| SL | 0.279 | STOP_LOSS_LIMIT trigger (protección inicial) |
| BE | ~0.283 × (1 − fee_buffer) ≈ **0.2829** | Nuevo STOP; cancelar SL |
| TP1 (1R) | 0.286 | Nuevo STOP; cancelar BE/SL |
| TP2 (2R) | 0.289 | Nuevo STOP; cancelar TP1 |
| TP3 (3R) | 0.292 | Nuevo STOP; cancelar TP2 |
| TPn (NR) | entry + n×R | Techo OCO limit (moonshot); STOP en piso TPn−1 o TPn |

**Nota:** en el ejemplo del usuario, **0.289 es TP2 (2R)**, no TP1.

**Regla Caso 1 (sin cambio):** al alcanzar TPn, el piso sube al precio de TPn; salida única si precio retrocede (`SL_TPn`).

---

## 5. Estado de protección

### 5.1 Campos Dynamo (trade)

```text
protection_level              # SL | BE | TP1 | … | TP6
protection_target_price       # precio STOP vigente
protection_order_id           # orderId STOP activo (reemplaza binance_stop_order_id)
protection_client_order_id
protection_sync_status        # synced | pending | failed | unprotected
                              # synced = paridad OK | pending = transición | failed = paridad rota
protection_last_sync_at       # ISO
protection_last_error         # truncado 500 chars
protection_retry_count
protection_alert_sent_at      # rate-limit alertas críticas
```

### 5.2 Máquina de estados

```text
ENTRY_FILLED → reconcile(SL) → verify → SYNCED(SL)

price >= BE  → cancel anterior → place STOP @ BE  → verify → SYNCED(BE)
price >= TP1 → cancel anterior → place STOP @ TP1 → verify → SYNCED(TP1)
… TP2 … TPn …

CLOSED: fill STOP en binance_events (preferido) | TIME_STOP MARKET | admin /confirmado
```

Todas las transiciones vía **`ExchangeProtectionManager`** (nuevo módulo).

---

## 6. Flujo cancel → place → verify

### 6.1 `reconcile_protection(trade, target_level, stop_price)`

1. **Cancelar** `protection_order_id` y/o OCO list del trade (idempotente si ya filled/canceled).
2. **Colocar** `STOP_LOSS_LIMIT` SELL con `clientOrderId = stop_order_client_id(trade_id, level)`.
3. **Verificar** (obligatorio):
   - `GET /api/v3/openOrders?symbol=PAIR`
   - Exactamente **una** orden SELL STOP* con `orderId` o `clientOrderId` esperado
   - `stopPrice` ≈ target (±1 tick)
   - `origQty` ≈ `base_qty` (±1 step)
   - Ningún STOP legacy del mismo trade (prefijo client id)
4. **Persistir** `protection_sync_status=synced` (paridad) o `pending`/`failed` + error.

### 6.2 Cuándo invocar

| Trigger | Acción |
|---------|--------|
| Post-entry BUY filled | `reconcile(SL)` + OCO ceiling (política actual) |
| Monitor: BE armado | `reconcile(BE)` |
| Monitor: ladder_level sube | `reconcile(TP{n})` |
| Cada ciclo monitor | **Paridad check**: si Dynamo ≠ Binance → reconcile o alerta |
| `close_reason` SL/BE/SL_TP* sin paridad | **No MARKET**; alertar admin |

### 6.3 Reintentos

| Fase | Comportamiento |
|------|----------------|
| Intentos 1–3 | Mismo ciclo monitor |
| 4–6 | Ciclos siguientes (~5 min) |
| 7+ | `failed` + Telegram CRÍTICO (cooldown 30 min) |

Env: `PROTECTION_MAX_RETRIES=6`, `EXCHANGE_PROTECTION_STRICT=true`.

---

## 7. Cierre del trade

### 7.1 Preferido

`binance_events` cierra con `avg_price` real cuando `protection_order_id` matchea.

Ampliar: match por `protection_client_order_id` (`S{level}{tradeId}`).

### 7.2 Prohibido (strict mode)

| close_reason | MARKET automático |
|--------------|-------------------|
| TIME_STOP | Sí |
| `/confirmado` admin | Sí |
| SL / BE / SL_TP* sin STOP synced | **No** — solo alerta admin |

**Eliminar** fallback MARKET en `position_monitor` para `protected_exit` cuando nunca hubo STOP verificado.

Si STOP synced existe: **esperar fill** (grace 15 min); no MARKET por “stale” salvo gap documentado + alerta.

### 7.3 Anomalía post-cierre

Si `close_reason` ∈ {SL_TP*, BE} y `|exit − protection_target| / R > 0.5`:

- Log `PROTECTION_SLIPPAGE_ANOMALY`
- Telegram warning

---

## 8. Alertas Telegram

### CRÍTICO (protección ausente)

```text
🚨 PROTECCIÓN EXCHANGE FALLIDA
Par: SNXUSDT | trade: abc123…
Objetivo: TP3 STOP @ 0.2503
Estado: failed tras 6 reintentos
Error: verify mismatch / 400 LOT_SIZE
Posición SIN STOP en Binance — NO se hará MARKET en escalera.
Revisar manualmente.
```

### OK (solo si verify pasó)

```text
📍 Escalera TP2 (SNXUSDT)
STOP Binance confirmado @ 0.2890 (orderId 12345)
Orden anterior cancelada ✓
```

---

## 9. Archivos a tocar

| Archivo | Cambio |
|---------|--------|
| `src/core/exchange_protection.py` | **Nuevo** — manager reconcile/verify/retry |
| `src/core/binance_client.py` | `get_open_orders`, `get_order` |
| `src/core/live_exit.py` | Delegar a manager |
| `src/lambdas/position_monitor/handler.py` | Strict exits; reconciliación pasiva |
| `src/lambdas/scanner/handler.py` | reconcile(SL) post-entry |
| `src/lambdas/binance_events/handler.py` | Match protection_order_id |
| `src/core/telegram_client.py` | Alertas críticas |
| `scripts/reconcile_open_live_protections.py` | One-shot trades OPEN huérfanos |

---

## 10. Tests

- BE cancela SL y verify OK
- TP1 cancela BE
- Verify fail → no `synced`
- Monitor no MARKET en SL_TP1 unprotected
- binance_events cierra en STOP fill

- Paridad check detecta drift y dispara reconcile

---

## 11. Criterios de aceptación

1. Post-entry: `protection_sync_status=synced` + 1 STOP en open orders.
2. BE: SL cancelado, STOP en BE presente.
3. TP1+: mismo patrón cancel/replace/verify.
4. Retroceso con STOP synced: cierre por websocket, slippage ≤ ~0.3R en testnet normal.
5. Verify falla 6×: Telegram CRÍTICO; trade OPEN; sin MARKET escalera.
6. Caso RUNE/SNX no reproducible en −3R con strict mode.
7. Trades OPEN: **≥ 95%** del tiempo en `protection_sync_status=synced` (medido en audit logs).
8. Tras cualquier transición BE/TPn, paridad verificada en el mismo ciclo o el siguiente.

---

## 12. Fuera de alcance v1

- Ventas parciales en TP1/TP2/TP3
- Migrar a STOP_MARKET (evaluar v2)
- Mainnet

---

## 13. Issue GitHub

**Title:** `[P0] Exchange-verified ladder: cancel/replace SL→BE→TPn + Binance verify + admin alert`

**Labels:** `bug`, `live-test`, `exchange`, `P0`, `reliability`

---

## 14. Resumen

**Espíritu:** Dynamo y Binance son **el mismo libro**; solo pueden diferir unos segundos (o un ciclo) mientras cancel/replace/verify está en curso. El resto del tiempo deben coincidir.

Ajustes clave:

1. Paridad como invariante, no solo “enviar orden”.
2. Nombrar bien TP2/TP3 (2R, 3R).
3. Verify obligatorio antes de `synced`.
4. Reconciliación pasiva cada ciclo si hay drift.
5. Sin MARKET en escalera sin paridad confirmada.
6. Cierre real = fill del STOP en exchange.
