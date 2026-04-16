import json
from typing import Any, Dict, List, Tuple
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState

POSITION_LIMIT = 80

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"

# Osmium: pure market-making on a mean-reverting, zero-drift instrument
OSMIUM_FAIR_VALUE_ANCHOR = 10_000
OSMIUM_HALF_SPREAD = 7          # inside the ~16-tick market spread
OSMIUM_SPREAD_COLLAPSE_THRESH = 6  # widen when spread < this
OSMIUM_WIDE_HALF_SPREAD = 10    # fallback when spread collapses
OSMIUM_INV_SKEW_COEFF = 0.15   # skew per unit of inventory
OSMIUM_EMA_ALPHA = 0.05         # slow EMA blending toward anchor

# Pepper Root: trend-following + skewed market-making
PEPPER_DRIFT_PER_TICK = 0.10
PEPPER_BID_OFFSET = 5           # tighter on the buy side (trend is up)
PEPPER_ASK_OFFSET = 9           # wider on the sell side
PEPPER_TREND_BASE_POS = 30      # base long position to ride the trend
PEPPER_INV_SKEW_COEFF = 0.12
PEPPER_EMA_ALPHA = 0.15         # faster EMA to track trending price


class Trader:
    """
    Production trading algorithm for IMC Prosperity 4, Round 1.

    Products:
        ASH_COATED_OSMIUM  — pure market-making (zero drift, bid-ask bounce)
        INTARIAN_PEPPER_ROOT — trend long + skewed market-making (+1000/day drift)

    State is persisted across ticks via traderData (JSON string).
    """

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}
        conversions = 0

        trader_state = self._load_state(state.traderData)

        if OSMIUM in state.order_depths:
            result[OSMIUM] = self._trade_osmium(state, trader_state)

        if PEPPER in state.order_depths:
            result[PEPPER] = self._trade_pepper(state, trader_state)

        trader_data = json.dumps(trader_state, cls=ProsperityEncoder)
        return result, conversions, trader_data

    # ── Ash-Coated Osmium: Pure Market Making ─────────────────────────────

    def _trade_osmium(self, state: TradingState, ts: dict) -> List[Order]:
        orders: List[Order] = []
        order_depth = state.order_depths[OSMIUM]
        position = state.position.get(OSMIUM, 0)

        mid = self._calc_mid(order_depth)
        spread = self._calc_spread(order_depth)

        prev_ema = ts.get("osmium_ema", OSMIUM_FAIR_VALUE_ANCHOR)
        if mid is not None:
            ema = OSMIUM_EMA_ALPHA * mid + (1 - OSMIUM_EMA_ALPHA) * prev_ema
            # Blend the EMA toward the known anchor to prevent drift
            fair = 0.7 * ema + 0.3 * OSMIUM_FAIR_VALUE_ANCHOR
        else:
            fair = prev_ema
            ema = prev_ema
        ts["osmium_ema"] = ema

        # Determine quoting half-spread — widen if market spread collapses
        if spread is not None and spread < OSMIUM_SPREAD_COLLAPSE_THRESH:
            half_spread = OSMIUM_WIDE_HALF_SPREAD
        else:
            half_spread = OSMIUM_HALF_SPREAD

        # Inventory skew: shift quotes to reduce position
        skew = OSMIUM_INV_SKEW_COEFF * position
        bid_price = int(round(fair - half_spread - skew))
        ask_price = int(round(fair + half_spread - skew))

        buy_capacity = POSITION_LIMIT - position
        sell_capacity = POSITION_LIMIT + position

        # Layer 1: Aggressively take mispriced orders
        orders += self._take_sells_below(order_depth, int(round(fair)), buy_capacity, OSMIUM)
        filled_buy = sum(o.quantity for o in orders if o.quantity > 0)
        buy_capacity -= filled_buy

        orders += self._take_buys_above(order_depth, int(round(fair)), sell_capacity, OSMIUM)
        filled_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        sell_capacity -= filled_sell

        # Layer 2: Passive quotes at our computed bid/ask
        if buy_capacity > 0:
            orders.append(Order(OSMIUM, bid_price, buy_capacity))
        if sell_capacity > 0:
            orders.append(Order(OSMIUM, ask_price, -sell_capacity))

        return orders

    # ── Intarian Pepper Root: Trend-Following + Skewed MM ─────────────────

    def _trade_pepper(self, state: TradingState, ts: dict) -> List[Order]:
        orders: List[Order] = []
        order_depth = state.order_depths[PEPPER]
        position = state.position.get(PEPPER, 0)

        mid = self._calc_mid(order_depth)
        spread = self._calc_spread(order_depth)

        prev_ema = ts.get("pepper_ema", None)
        if mid is not None:
            if prev_ema is not None:
                ema = PEPPER_EMA_ALPHA * mid + (1 - PEPPER_EMA_ALPHA) * prev_ema
            else:
                ema = mid
            # Adjust fair value upward by the known per-tick drift
            fair = ema + PEPPER_DRIFT_PER_TICK
        else:
            fair = prev_ema if prev_ema is not None else 12000.0
            ema = fair
        ts["pepper_ema"] = ema

        # Skew to maintain a long bias: the target is PEPPER_TREND_BASE_POS
        inventory_deviation = position - PEPPER_TREND_BASE_POS
        skew = PEPPER_INV_SKEW_COEFF * inventory_deviation

        bid_price = int(round(fair - PEPPER_BID_OFFSET - skew))
        ask_price = int(round(fair + PEPPER_ASK_OFFSET - skew))

        buy_capacity = POSITION_LIMIT - position
        sell_capacity = POSITION_LIMIT + position

        # Layer 1: Aggressive taking — buy anything priced below fair (trend is up)
        take_threshold = int(round(fair - 1))
        orders += self._take_sells_below(order_depth, take_threshold, buy_capacity, PEPPER)
        filled_buy = sum(o.quantity for o in orders if o.quantity > 0)
        buy_capacity -= filled_buy

        # Only sell into bids that are clearly above fair (don't fight the trend)
        sell_threshold = int(round(fair + 2))
        orders += self._take_buys_above(order_depth, sell_threshold, sell_capacity, PEPPER)
        filled_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        sell_capacity -= filled_sell

        # Layer 2: Skewed passive quotes
        if buy_capacity > 0:
            orders.append(Order(PEPPER, bid_price, buy_capacity))
        if sell_capacity > 0:
            orders.append(Order(PEPPER, ask_price, -sell_capacity))

        return orders

    # ── Order-book helpers ────────────────────────────────────────────────

    def _calc_mid(self, od: OrderDepth) -> float | None:
        if od.buy_orders and od.sell_orders:
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            return (best_bid + best_ask) / 2.0
        if od.buy_orders:
            return float(max(od.buy_orders.keys()))
        if od.sell_orders:
            return float(min(od.sell_orders.keys()))
        return None

    def _calc_spread(self, od: OrderDepth) -> float | None:
        if od.buy_orders and od.sell_orders:
            return min(od.sell_orders.keys()) - max(od.buy_orders.keys())
        return None

    def _take_sells_below(
        self, od: OrderDepth, threshold: int, capacity: int, symbol: str
    ) -> List[Order]:
        """Buy against any sell orders priced at or below threshold."""
        orders: List[Order] = []
        if capacity <= 0:
            return orders
        remaining = capacity
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price > threshold or remaining <= 0:
                break
            # sell_orders volumes are negative in the Prosperity data model
            ask_vol = -od.sell_orders[ask_price]
            fill = min(ask_vol, remaining)
            if fill > 0:
                orders.append(Order(symbol, ask_price, fill))
                remaining -= fill
        return orders

    def _take_buys_above(
        self, od: OrderDepth, threshold: int, capacity: int, symbol: str
    ) -> List[Order]:
        """Sell against any buy orders priced at or above threshold."""
        orders: List[Order] = []
        if capacity <= 0:
            return orders
        remaining = capacity
        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price < threshold or remaining <= 0:
                break
            bid_vol = od.buy_orders[bid_price]
            fill = min(bid_vol, remaining)
            if fill > 0:
                orders.append(Order(symbol, bid_price, -fill))
                remaining -= fill
        return orders

    # ── State persistence ─────────────────────────────────────────────────

    def _load_state(self, trader_data: str) -> dict:
        if trader_data and trader_data.strip():
            try:
                return json.loads(trader_data)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}
