from typing import Dict, List, Any
from datamodel import OrderDepth, TradingState, Order, Symbol

class Trader:
    # Prosperity 4 enforces a strict maximum position limit of 80 for these assets.
    # We must track this to avoid the engine canceling our orders.
    POSITION_LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80
    }

    def run(self, state: TradingState) -> tuple[Dict[Symbol, List[Order]], int, str]:
        """
        The core engine method. Takes the current state of the market
        and outputs your desired trades.
        """
        result = {}
        conversions = 0
        # traderData allows you to pass string states between iterations if needed
        trader_data = state.traderData if state.traderData else ""

        for product in state.order_depths:
            # Skip any products we haven't built logic for yet
            if product not in self.POSITION_LIMITS:
                continue

            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            
            # Fetch our current inventory position (defaults to 0 if we have none)
            current_position = state.position.get(product, 0)
            limit = self.POSITION_LIMITS[product]

            # We need both sides of the book to calculate a fair mid-price
            if len(order_depth.sell_orders) > 0 and len(order_depth.buy_orders) > 0:
                
                # order_depth.sell_orders is a dict of {price: quantity}
                best_ask = min(order_depth.sell_orders.keys())
                best_bid = max(order_depth.buy_orders.keys())
                
                # Calculate the fair mid-price
                mid_price = (best_ask + best_bid) / 2
                
                # Market Making: Quote our own buy/sell prices around the mid
                # Prices must be integers in the Prosperity engine
                my_buy_price = int(mid_price - 1)
                my_sell_price = int(mid_price + 1)

                # --- BUY LOGIC ---
                # How much can we buy without exceeding the hard limit of +80?
                max_buy_qty = limit - current_position
                if max_buy_qty > 0:
                    print(f"[{state.timestamp}] Bidding {max_buy_qty}x {product} at {my_buy_price}")
                    orders.append(Order(product, my_buy_price, max_buy_qty))

                # --- SELL LOGIC ---
                # How much can we sell without exceeding the hard limit of -80?
                # Note: Sells are represented by negative quantities
                max_sell_qty = -limit - current_position
                if max_sell_qty < 0:
                    print(f"[{state.timestamp}] Asking {-max_sell_qty}x {product} at {my_sell_price}")
                    orders.append(Order(product, my_sell_price, max_sell_qty))
            
            # Append the list of orders for this specific product to our result dictionary
            result[product] = orders

        # The engine expects exactly this tuple return format
        return result, conversions, trader_data
