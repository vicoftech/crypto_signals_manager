from __future__ import annotations

from src.core.config_store import ConfigStore

_CONFIG_KEY = "accounting_epoch_started_at"


def get_accounting_epoch_iso() -> str:
    return ConfigStore().get_str(_CONFIG_KEY, "").strip()


def _norm_iso(ts: str) -> str:
    t = (ts or "").strip()
    if t.endswith("Z"):
        t = t.replace("Z", "+00:00", 1)
    return t


def trade_in_accounting_window(trade: dict, epoch_iso: str) -> bool:
    """Si epoch_iso es vacio, no filtra. Si no, abiertas por started_at, cerradas por ended_at."""
    if not epoch_iso:
        return True
    st = str(trade.get("status", "")).upper()
    if st == "CLOSED":
        ref = str(trade.get("ended_at") or trade.get("started_at") or "")
    else:
        ref = str(trade.get("started_at") or "")
    if not ref:
        return True
    return _norm_iso(ref) >= _norm_iso(epoch_iso)


def format_accounting_line_short() -> str:
    """Una linea para Telegram: pie de corte / linea base."""
    epoch = get_accounting_epoch_iso()
    if epoch:
        d = _norm_iso(epoch)[:10]
        return (
            f"Cierres y totales en comandos: desde {d} (corte en config). "
            f"P&L en /capital: misma linea base (capital_inicial al corte)."
        )
    return (
        "P&L en /capital: linea base actual. "
        "Clave `accounting_epoch_started_at` en config para alinear resumenes con un corte; "
        "si no, /resumen y /rendimiento usan todo el historial de la tabla."
    )


def format_accounting_block() -> str:
    """Bloque multilinea para /capital y resumenes."""
    epoch = get_accounting_epoch_iso()
    if epoch:
        d = _norm_iso(epoch)[:10]
        return (
            f"Contabilidad\n"
            f"- Corte: {d} (UTC) — cierres y agregados desde ahi (clave en config).\n"
            f"- P&L y capital en /capital: respecto a capital_inicial al mismo corte."
        )
    return (
        "Contabilidad\n"
        f"- Corte: configura clave `accounting_epoch_started_at` (ISO UTC) en la tabla de config "
        f"para que /resumen, /rendimiento e /historial excluyan cierres anteriores al corte."
    )
