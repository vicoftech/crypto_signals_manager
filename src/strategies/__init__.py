from src.strategies.ema_pullback import EMAPullbackStrategy
from src.strategies.macd_cross import MACDCrossStrategy
from src.strategies.momentum import MomentumContinuationStrategy
from src.strategies.orb import ORBStrategy
from src.strategies.range_breakout import RangeBreakoutStrategy
from src.strategies.support_bounce import SupportBounceStrategy

STRATEGY_REGISTRY = {
    "EMAPullback": EMAPullbackStrategy(),
    "RangeBreakout": RangeBreakoutStrategy(),
    "SupportBounce": SupportBounceStrategy(),
    "MACDCross": MACDCrossStrategy(),
    "ORB": ORBStrategy(),
    "Momentum": MomentumContinuationStrategy(),
}
