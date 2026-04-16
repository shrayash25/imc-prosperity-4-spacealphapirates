import json
from typing import Any, Dict, List, Optional, Tuple
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState

POSITION_LIMIT = 80

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"

# ── Osmium: pure market-making on a mean-reverting, zero-drift instrument ─────
OSMIUM_HALF_SPREAD = 3              # v3: tighter inner layer (was 4) for more fills
OSMIUM_SPREAD_COLLAPSE_THRESH = 5
OSMIUM_WIDE_HALF_SPREAD = 8
OSMIUM_INV_SKEW_COEFF = 0.08
OSMIUM_EMA_ALPHA = 0.035
OSMIUM_TAKE_MARGIN = 0              # v3: back to 0 — stop adverse selection on takes

# ── Pepper Root: trend-following + skewed market-making ───────────────────────
PEPPER_DRIFT_PER_TICK = 0.10
PEPPER_BID_OFFSET = 3
PEPPER_ASK_OFFSET = 11
PEPPER_TREND_BASE_POS = 68
PEPPER_INV_SKEW_COEFF = 0.06
PEPPER_EMA_ALPHA = 0.20
PEPPER_TAKE_BUY_MARGIN = 8         # v3: wide enough to hit resting asks (was 2)
PEPPER_TAKE_SELL_MARGIN = 5         # default when building position
PEPPER_TAKE_SELL_MARGIN_AT_CAP = 3  # v3: tighter sell when at limit to churn spreads


class Trader:
    """
    Production trading algorithm for IMC Prosperity 4, Round 1 (v3).

    v3 fixes vs v2 (informed by 201246.log analysis):
      1. Pepper take margin 2 -> 8 (hit resting asks, fill to 80 in ~10% of day)
      2. Osmium take margin 2 -> 0 (stop negative-edge aggressive takes)
      3. Micro-price replaces VWAP mid (fixes deep-book bias)
      4. Osmium inner layer 4 -> 3, layer step 2 -> 3, weights 60/25/15
      5. Pepper sell threshold drops to fair+3 when at position limit (churn)
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

        mid = self._micro_price(order_depth)
        spread = self._calc_spread(order_depth)

        prev_ema = ts.get("osmium_ema", 10_000.0)
        if mid is not None:
            ema = OSMIUM_EMA_ALPHA * mid + (1 - OSMIUM_EMA_ALPHA) * prev_ema
            fair = ema
        else:
            fair = prev_ema
            ema = prev_ema
        ts["osmium_ema"] = ema

        if spread is not None and spread < OSMIUM_SPREAD_COLLAPSE_THRESH:
            half_spread = OSMIUM_WIDE_HALF_SPREAD
        else:
            half_spread = OSMIUM_HALF_SPREAD

        skew = OSMIUM_INV_SKEW_COEFF * position

        buy_capacity = POSITION_LIMIT - position
        sell_capacity = POSITION_LIMIT + position

        # Conservative aggressive layer: only take clearly mispriced orders
        buy_take = int(round(fair + OSMIUM_TAKE_MARGIN))
        sell_take = int(round(fair - OSMIUM_TAKE_MARGIN))

        orders += self._take_sells_below(order_depth, buy_take, buy_capacity, OSMIUM)
        filled_buy = sum(o.quantity for o in orders if o.quantity > 0)
        buy_capacity -= filled_buy

        orders += self._take_buys_above(order_depth, sell_take, sell_capacity, OSMIUM)
        filled_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        sell_capacity -= filled_sell

        # v3: tighter inner layer, wider spacing, heavier inner weight
        orders += self._multilevel_quotes(
            OSMIUM, fair, half_spread, skew, buy_capacity, sell_capacity,
            layers=3, layer_step=3,
            size_weights=[0.60, 0.25, 0.15],
        )

        return orders

    # ── Intarian Pepper Root: Trend-Following + Skewed MM ─────────────────

    def _trade_pepper(self, state: TradingState, ts: dict) -> List[Order]:
        orders: List[Order] = []
        order_depth = state.order_depths[PEPPER]
        position = state.position.get(PEPPER, 0)

        mid = self._micro_price(order_depth)

        prev_ema = ts.get("pepper_ema", None)
        if mid is not None:
            if prev_ema is not None:
                ema = PEPPER_EMA_ALPHA * mid + (1 - PEPPER_EMA_ALPHA) * prev_ema
            else:
                ema = mid
            fair = ema + PEPPER_DRIFT_PER_TICK
        else:
            fair = prev_ema if prev_ema is not None else 12000.0
            ema = fair
        ts["pepper_ema"] = ema

        inventory_deviation = position - PEPPER_TREND_BASE_POS
        skew = PEPPER_INV_SKEW_COEFF * inventory_deviation

        buy_capacity = POSITION_LIMIT - position
        sell_capacity = POSITION_LIMIT + position

        # v3: wide take margin to hit resting asks and fill to 80 fast
        buy_take = int(round(fair + PEPPER_TAKE_BUY_MARGIN))
        orders += self._take_sells_below(order_depth, buy_take, buy_capacity, PEPPER)
        filled_buy = sum(o.quantity for o in orders if o.quantity > 0)
        buy_capacity -= filled_buy

        # v3: position-dependent sell threshold — churn at cap, protect when building
        if position >= POSITION_LIMIT - 5:
            sell_take = int(round(fair + PEPPER_TAKE_SELL_MARGIN_AT_CAP))
        else:
            sell_take = int(round(fair + PEPPER_TAKE_SELL_MARGIN))
        orders += self._take_buys_above(order_depth, sell_take, sell_capacity, PEPPER)
        filled_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        sell_capacity -= filled_sell

        orders += self._multilevel_quotes(
            PEPPER, fair, PEPPER_BID_OFFSET, skew, buy_capacity, sell_capacity,
            layers=3, layer_step=2,
            ask_base_offset=PEPPER_ASK_OFFSET,
        )

        return orders

    # ── Order-book helpers ────────────────────────────────────────────────

    def _micro_price(self, od: OrderDepth) -> Optional[float]:
        """
        v3: L1 micro-price weighted by order imbalance.

        When bid volume > ask volume, price is pulled toward the ask
        (buyers are aggressive, price likely to tick up), and vice versa.
        Avoids the deep-book bias of the old VWAP mid.
        """
        if not od.buy_orders or not od.sell_orders:
            if od.buy_orders:
                return float(max(od.buy_orders.keys()))
            if od.sell_orders:
                return float(min(od.sell_orders.keys()))
            return None

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        bid_vol = od.buy_orders[best_bid]
        ask_vol = abs(od.sell_orders[best_ask])

        total = bid_vol + ask_vol
        if total == 0:
            return (best_bid + best_ask) / 2.0

        imb = bid_vol / total
        return best_ask * imb + best_bid * (1 - imb)

    def _calc_spread(self, od: OrderDepth) -> Optional[float]:
        if od.buy_orders and od.sell_orders:
            return min(od.sell_orders.keys()) - max(od.buy_orders.keys())
        return None

    def _multilevel_quotes(
        self,
        symbol: str,
        fair: float,
        bid_base_offset: float,
        skew: float,
        buy_capacity: int,
        sell_capacity: int,
        layers: int = 3,
        layer_step: int = 2,
        ask_base_offset: Optional[float] = None,
        size_weights: Optional[List[float]] = None,
    ) -> List[Order]:
        """
        Place multiple passive order layers instead of a single level.
        v3: accepts custom size_weights for per-product tuning.
        """
        if ask_base_offset is None:
            ask_base_offset = bid_base_offset

        if size_weights is None:
            size_weights = [0.60, 0.25, 0.15]
        weights = size_weights[:layers]
        total_w = sum(weights)
        weights = [w / total_w for w in weights]

        orders: List[Order] = []

        for i in range(layers):
            offset_extra = i * layer_step
            bid_price = int(round(fair - bid_base_offset - offset_extra - skew))
            ask_price = int(round(fair + ask_base_offset + offset_extra - skew))

            bid_qty = max(1, int(round(buy_capacity * weights[i])))
            ask_qty = max(1, int(round(sell_capacity * weights[i])))

            if buy_capacity > 0 and bid_qty > 0:
                actual_bid = min(bid_qty, buy_capacity)
                orders.append(Order(symbol, bid_price, actual_bid))
                buy_capacity -= actual_bid

            if sell_capacity > 0 and ask_qty > 0:
                actual_ask = min(ask_qty, sell_capacity)
                orders.append(Order(symbol, ask_price, -actual_ask))
                sell_capacity -= actual_ask

        return orders

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
