from __future__ import annotations

import json
import os

import requests

from src.config import binance_credentials_configured, settings
from src.core.auto_sim_utils import calcular_pnl_circunstancial
from src.core.capital import get_capital_snapshot
from src.core.binance_client import BinanceClient
from src.core.config_store import ConfigStore
from src.core.pairs_manager import PairsManager
from src.core.market_session import format_market_session_from_iso
from src.core.trades_manager import TradesManager

COMMANDS_HELP = {
    "/menu": "Muestra este menu contextual con todos los comandos.",
    "/status": "Estado actual del bot (pausa, capital, riesgo).",
    "/contexto": "Lista pares activos y estado operativo.",
    "/capital <monto>": "Actualiza capital total usado por el bot.",
    "/riesgo <pct>": "Actualiza riesgo por trade (max 10%).",
    "/pausar": "Pausa el scanner de oportunidades.",
    "/reanudar": "Reanuda el scanner.",
    "/pares": "Lista todos los pares configurados.",
    "/agregar <PAR>": "Agrega un nuevo par (ej: SOLUSDT).",
    "/pausarpar <PAR>": "Pausa un par puntual.",
    "/activarpar <PAR>": "Reactiva un par puntual.",
    "/estrategias <PAR>": "Muestra estrategias habilitadas para el par.",
    "/simular": "Posiciones SIM abiertas con P&L circunstancial.",
    "/simconfig <PAR> <manual|auto|disabled>": "Modo de simulacion por par.",
    "/simstatus": "Modo y stats de sim por par.",
    "/simstats <PAR>": "Stats de simulacion de un par.",
    "/confirmado <PAR>": "Cierra operacion REAL abierta del par como MANUAL.",
    "/historial": "Ultimas 20 operaciones cerradas con P&L.",
    "/resumen": "Resumen general de operaciones (abiertas/cerradas/modo).",
    "/rendimiento": "Metricas globales de winrate y P&L neto.",
    "/operacion <trade_id>": "Muestra todos los detalles de una operacion puntual.",
}


def _normalize_cmd(part0: str) -> str:
    """Telegram manda /cmd@BotName; dejamos solo /cmd."""
    base = part0.split("@", 1)[0].lower()
    return base if base.startswith("/") else f"/{base}"


def _send_message(text: str, chat_id: str | int | None = None) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    target = chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not target:
        return
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": target, "text": text},
        timeout=15,
    ).raise_for_status()


def _handle_command(text: str, config: ConfigStore, pairs: PairsManager, trades: TradesManager) -> str:
    parts = text.strip().split()
    cmd = _normalize_cmd(parts[0])

    if cmd == "/menu" or cmd == "/help":
        return "Menu de comandos disponibles\n\n" + "\n".join(
            f"{k}\n  - {v}" for k, v in COMMANDS_HELP.items()
        )
    if cmd == "/status":
        return (
            "Estado bot\n"
            f"- scanner_paused: {'SI' if config.is_paused() else 'NO'}\n"
            f"- capital_total: {config.get_capital(settings.capital_total):.2f}\n"
            f"- risk_pct: {config.get_risk_pct(settings.risk_per_trade_pct) * 100:.1f}%"
        )
    if cmd == "/contexto":
        active = pairs.get_active_pairs()
        lines = [f"{p.pair}: {'activo' if p.active else 'pausado'} | estrategias={len(p.strategies)}" for p in active]
        return "Contexto (pares activos)\n" + ("\n".join(lines) if lines else "Sin pares activos")
    if cmd == "/capital":
        if len(parts) >= 2:
            # Solo permitir cambiar el capital inicial si no hay trades registrados
            try:
                nuevo = float(parts[1].replace(",", "."))
            except ValueError:
                return "Formato invalido. Usa /capital 1183.50"
            if trades.list_trades():
                snap = get_capital_snapshot().as_dict()
                return (
                    "❌ No se puede cambiar el capital inicial con operaciones ya registradas.\n"
                    f"Capital inicial actual: {snap['capital_inicial']:.2f}\n"
                    "Usa /reset_capital cuando no haya posiciones abiertas para iniciar una nueva sesion."
                )
            # Sin trades: actualizar capital_inicial y capital_total en ConfigTable
            config.set_number("capital_inicial", nuevo)
            config.set_capital(nuevo)
            return f"Capital inicial actualizado a {nuevo:.2f}"
        cap = get_capital_snapshot().as_dict()
        pnl_emoji = "📈" if cap["pnl_cerrado"] >= 0 else "📉"
        dd_text = (
            f"⚠️ Drawdown: {cap['drawdown_actual']:.1%}"
            if cap["drawdown_actual"] > 0
            else "✅ Sin drawdown"
        )
        riesgo_prox = cap["capital_total"] * settings.risk_per_trade_pct
        return (
            "💼 ESTADO DEL CAPITAL SIMULADO\n\n"
            f"💰 Capital inicial:    ${cap['capital_inicial']:,.2f}\n"
            f"{pnl_emoji} P&L cerrado:       ${cap['pnl_cerrado']:+,.2f}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Capital total:      ${cap['capital_total']:,.2f}\n\n"
            f"🔒 Bloqueado ({cap['posiciones_abiertas']} ops): -${cap['capital_bloqueado']:,.2f}\n"
            f"✅ Disponible:         ${cap['capital_disponible']:,.2f}\n\n"
            f"{dd_text}\n"
            f"Riesgo proxima op:    ${riesgo_prox:,.2f}  ({settings.risk_per_trade_pct*100:.1f}%)"
        )
    if cmd == "/riesgo" and len(parts) >= 2:
        pct = min(float(parts[1]) / 100.0, 0.10)
        config.set_risk_pct(pct)
        return f"Riesgo actualizado a {pct * 100:.1f}%"
    if cmd == "/pausar":
        config.set_paused(True)
        return "Scanner pausado"
    if cmd == "/reanudar":
        config.set_paused(False)
        return "Scanner reanudado"
    if cmd == "/pares":
        all_pairs = pairs.get_all_pairs()
        if not all_pairs:
            return "No hay pares configurados"
        lines = [f"{p.pair} | {'activo' if p.active else 'pausado'} | estrategias={len(p.strategies)}" for p in all_pairs]
        return "Pares configurados\n" + "\n".join(lines)
    if cmd == "/agregar" and len(parts) >= 2:
        pairs.add_pair(parts[1])
        return f"Par agregado: {parts[1].upper()}"
    if cmd == "/pausarpar" and len(parts) >= 2:
        ok = pairs.set_active(parts[1], False)
        return f"Par pausado: {parts[1].upper()}" if ok else "Par no encontrado"
    if cmd == "/activarpar" and len(parts) >= 2:
        ok = pairs.set_active(parts[1], True)
        return f"Par activado: {parts[1].upper()}" if ok else "Par no encontrado"
    if cmd == "/estrategias" and len(parts) >= 2:
        p = pairs.get_pair(parts[1])
        if not p:
            return "Par no encontrado"
        return f"Estrategias {p.pair}\n" + "\n".join(f"- {s}" for s in p.strategies)
    if cmd == "/simular":
        sims = trades.get_all_open_trades()
        if not sims:
            return "No hay posiciones abiertas en este momento."
        bc = BinanceClient()
        lines_out = []
        total_pnl = 0.0
        total_risk = 0.0
        for i, t in enumerate(sims[:20], start=1):
            pair = str(t.get("pair", ""))
            px = bc.get_price(pair)
            ent = float(t.get("entry_price", 0) or 0)
            size = float(t.get("position_size_usd", 100) or 100)
            comm_in = float(t.get("entry_commission_usd", size * 0.001) or 0)
            pu, pp = calcular_pnl_circunstancial(ent, px, size, comm_in)
            total_pnl += pu
            total_risk += float(t.get("risk_usd", 0) or 0)
            auto = "🤖 AUTO" if str(t.get("sim_source", "")).startswith("auto") else "👤 MANUAL"
            lines_out.append(
                f"{i}) {pair}  {auto}  |  {t.get('strategy')}\n"
                f"   Entrada: {ent:.4f}  |  Ahora: {px:.4f}\n"
                f"   P&L:  {pu:+.2f} USD  ({pp:+.2f}%)"
            )
        pct_tot = (total_pnl / sum(float(x.get("position_size_usd", 100) or 100) for x in sims)) * 100 if sims else 0
        tail = f"\n─────────────────\n💼 P&L total abierto (estim.): {total_pnl:+.2f} USD (~{pct_tot:+.2f}% pond.)\n"
        tail += f"Riesgo expuesto (sum risk_usd): {total_risk:.2f} USD"
        return "📊 POSICIONES ABIERTAS (" + str(len(sims)) + ")\n\n" + "\n\n".join(lines_out) + tail
    if cmd == "/simconfig" and len(parts) >= 3:
        par = parts[1].upper().strip()
        mode = parts[2].lower().strip()
        if mode not in ("manual", "auto", "disabled"):
            return "Modo invalido. Use: manual | auto | disabled"
        ok = pairs.set_sim_mode(par, mode)
        if not ok:
            return "Par no encontrado"
        if mode == "auto":
            return f"✅ {par} en modo AUTO-SIM. Todas las senales se simularan automaticamente."
        if mode == "manual":
            return f"✅ {par} en modo MANUAL. Recibiras senales con botones."
        return f"✅ {par} en modo DISABLED. Solo notificaciones sin simulacion."
    if cmd == "/simstatus":
        rows = pairs.get_all_pairs()
        if not rows:
            return "Sin pares"
        lines = ["📊 ESTADO DE SIMULACION\n"]
        total_t = 0
        total_w = 0
        total_pnl = 0.0
        for p in rows:
            sm = getattr(p, "sim_mode", "manual")
            icon = "🤖 AUTO" if sm == "auto" else ("⛔ OFF" if sm == "disabled" else "👤 MANUAL")
            st = p.sim_stats or {}
            ts = int(st.get("total_sim", 0) or 0)
            gw = int(st.get("ganadoras", 0) or 0)
            pnl = float(st.get("pnl_total_usd", 0) or 0)
            wr = (100 * gw / ts) if ts else 0.0
            rav = float(st.get("r_multiple_avg", 0) or 0)
            total_t += ts
            total_w += gw
            total_pnl += pnl
            lines.append(
                f"{p.pair}  {icon}  trades={ts}  win={wr:.0f}%  Ravg={rav:+.1f}  P&L={pnl:+.0f}"
            )
        wt = (100 * total_w / total_t) if total_t else 0.0
        lines.append(f"\nTotal SIM acumulado (stats): {total_t} trades | win ~{wt:.0f}% | P&L {total_pnl:+.0f}")
        return "\n".join(lines)
    if cmd == "/simstats" and len(parts) >= 2:
        p = pairs.get_pair(parts[1])
        if not p:
            return "Par no encontrado"
        st = p.sim_stats or {}
        ts = int(st.get("total_sim", 0) or 0)
        gw = int(st.get("ganadoras", 0) or 0)
        pl = int(st.get("perdedoras", 0) or 0)
        pnl = float(st.get("pnl_total_usd", 0) or 0)
        rav = float(st.get("r_multiple_avg", 0) or 0)
        wr = (100 * gw / ts) if ts else 0.0
        return (
            f"📈 ESTADISTICAS {p.pair}\n"
            f"Modo: {getattr(p, 'sim_mode', 'manual')}\n"
            f"Total trades (sim_stats): {ts}\n"
            f"Ganadoras: {gw}  Perdedoras: {pl}  Win%: {wr:.0f}%\n"
            f"R multiple avg: {rav:+.2f}\n"
            f"P&L acumulado (stats): {pnl:+.2f} USD\n"
            f"Objetivo auto-trade: {100 - ts} trades hasta minimo 100 (si aplica)"
        )
    if cmd == "/confirmado" and len(parts) >= 2:
        trade = trades.find_open_real_by_pair(parts[1])
        if not trade:
            return "No hay operacion REAL abierta para ese par"
        exit_price = float(trade.get("entry_price", 0) or 0)
        trades.close_trade(trade["trade_id"], "MANUAL", exit_price)
        return f"Operacion REAL confirmada/cerrada: {trade['trade_id']}"
    if cmd == "/historial":
        rows = trades.list_recent_closed(limit=20)
        if not rows:
            return "Sin operaciones cerradas todavia"
        lines = [
            f"id={t.get('trade_id')} | {t.get('pair')} | {t.get('mode')} | {t.get('close_reason')} | net={float(t.get('net_pnl_usd', 0) or 0):+.2f}"
            for t in rows
        ]
        return "Historial (ultimas cerradas)\n" + "\n".join(lines)
    if cmd == "/resumen":
        s = trades.get_summary()
        open_count = len(trades.list_open())
        return (
            "Resumen operativo\n"
            f"- total: {s['total']}\n"
            f"- abiertas: {open_count}\n"
            f"- cerradas: {s['closed']}\n"
            f"- REAL: {s['by_mode']['REAL']} | SIM: {s['by_mode']['SIM']}\n"
            f"- neto acumulado: {s['net_pnl']:+.2f} USD"
        )
    if cmd == "/rendimiento":
        s = trades.get_summary()
        winrate = (s["wins"] / s["closed"] * 100.0) if s["closed"] else 0.0
        return (
            "Rendimiento\n"
            f"- operaciones cerradas: {s['closed']}\n"
            f"- winrate: {winrate:.1f}%\n"
            f"- P&L neto: {s['net_pnl']:+.2f} USD"
        )
    if cmd == "/operacion" and len(parts) >= 2:
        t = trades.get_trade(parts[1].strip())
        if not t:
            return "Operacion no encontrada"
        reason_text = t.get("close_reason_text") or _reason_text_from_code(t.get("close_reason"))
        mercado = t.get("market_session") or format_market_session_from_iso(str(t.get("started_at", "")))
        keys = [
            "trade_id",
            "mode",
            "status",
            "pair",
            "strategy",
            "timeframe",
            "entry_price",
            "sl_price",
            "tp1_price",
            "tp2_price",
            "started_at",
            "ended_at",
            "close_reason",
            "close_reason_text",
            "exit_price",
            "gross_pnl_usd",
            "commission_usd",
            "net_pnl_usd",
            "max_favorable_excursion",
            "max_adverse_excursion",
        ]
        lines = [f"- reason: {reason_text}"] if reason_text else []
        lines.append(f"- mercado_activo: {mercado}")
        for k in keys:
            if k in t:
                lines.append(f"- {k}: {t.get(k)}")
        return "Detalle operacion\n" + "\n".join(lines)
    return (
        "Comando no soportado. Usa /menu para ver todos los comandos disponibles."
    )


def _handle_callback(callback_query: dict) -> str:
    data = callback_query.get("data", "")
    parts = data.split("|")
    if len(parts) < 4:
        return "Accion invalida"
    action, pair, strategy, entry = parts[0], parts[1], parts[2], parts[3]

    if action == "IGNORE":
        return f"Ignorada señal {pair} ({strategy})"

    if action == "ENTER" and not binance_credentials_configured():
        return (
            "Modo REAL no disponible: faltan BINANCE_API_KEY y BINANCE_SECRET en el despliegue. "
            "Usa SIMULAR o configura las keys y redespliega."
        )

    trades = TradesManager()
    mode = "REAL" if action == "ENTER" else "SIM"
    entry_price = float(entry)
    sl_price = entry_price * 0.99
    tp1_price = entry_price * 1.01
    tp2_price = entry_price * 1.02
    size = 100.0
    trade_id = trades.open_trade(
        {
            "pair": pair,
            "strategy": strategy,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "position_size_usd": size,
            "risk_usd": settings.capital_total * settings.risk_per_trade_pct,
            "entry_commission_usd": size * 0.001,
            "sim_source": "telegram_callback",
            "tp1_hit": False,
            "trailing_activated": False,
            "timeframe": "30m",
            "max_favorable_excursion": entry_price,
            "max_adverse_excursion": entry_price,
        },
        mode=mode,
    )
    return f"{'Orden REAL registrada' if mode == 'REAL' else 'Simulacion iniciada'}\n{pair} | {strategy}\ntrade_id: {trade_id}"


def _reason_text_from_code(code: str | None) -> str:
    normalized = str(code or "").upper().strip()
    mapping = {
        "SL": "Stop loss alcanzado",
        "TP1": "Take profit 1 alcanzado",
        "TP2": "Take profit 2 alcanzado",
        "TRAILING_SL": "Trailing stop activado y ejecutado",
        "MANUAL": "Cierre manual confirmado",
        "INVALID": "Operacion cerrada por estado inconsistente",
    }
    return mapping.get(normalized, f"Cierre por {normalized or 'motivo no informado'}")


def handler(event, context):
    body = event.get("body", "{}")
    if event.get("isBase64Encoded"):
        # API Gateway HTTP API usually sends plain text body, kept for compatibility.
        body = body
    payload = json.loads(body) if isinstance(body, str) else body
    callback_query = payload.get("callback_query")
    if callback_query:
        response_text = _handle_callback(callback_query)
        cq_chat = (callback_query.get("message") or {}).get("chat", {}).get("id")
        _send_message(response_text, chat_id=cq_chat)
        return {"statusCode": 200, "body": json.dumps({"ok": True, "response": response_text})}

    message = payload.get("message") or {}
    text = message.get("text", "")
    if not text.startswith("/"):
        return {"statusCode": 200, "body": json.dumps({"ok": True, "ignored": True})}

    chat_id = message.get("chat", {}).get("id")
    config = ConfigStore()
    pairs = PairsManager()
    trades = TradesManager()
    response_text = _handle_command(text, config, pairs, trades)
    _send_message(response_text, chat_id=chat_id)
    return {"statusCode": 200, "body": json.dumps({"ok": True, "response": response_text})}
