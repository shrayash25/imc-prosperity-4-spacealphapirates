import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 1. Page Configuration
st.set_page_config(page_title="Prosperity Terminal", layout="wide", page_icon="📈")

@st.cache_data
def load_data(file):
    return pd.read_csv(file, sep=';')

def add_technical_indicators(df, sma_window, bb_window, bb_std):
    """Calculates typical TradingView indicators on the mid price."""
    df = df.copy()
    # Simple Moving Average
    df[f'SMA_{sma_window}'] = df['mid_price'].rolling(window=sma_window).mean()
    
    # Bollinger Bands
    rolling_mean = df['mid_price'].rolling(window=bb_window).mean()
    rolling_std = df['mid_price'].rolling(window=bb_window).std()
    df['BB_Upper'] = rolling_mean + (rolling_std * bb_std)
    df['BB_Lower'] = rolling_mean - (rolling_std * bb_std)
    return df

def render_product_dashboard(product_df, product_name, trades_df=None, show_sma=False, show_bb=False, sma_window=20, bb_window=20):
    if product_df.empty:
        st.warning(f"No price data found for {product_name}.")
        return

    # Calculate Indicators
    product_df = add_technical_indicators(product_df, sma_window, bb_window, 2)

    st.subheader(f"Terminal: {product_name}")

    # --- 3-Pane Plotly Subplot Setup ---
    fig = make_subplots(
        rows=3, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.03,
        row_heights=[0.6, 0.2, 0.2], # Price gets 60%, Volume 20%, PnL 20%
        subplot_titles=(f"Price Action & Order Book", "Level 1 Volume Pressure", "Cumulative PnL")
    )

    # -----------------------------------
    # PANE 1: PRICE ACTION & INDICATORS
    # -----------------------------------
    # Bid/Ask/Mid Lines
    fig.add_trace(go.Scatter(x=product_df['timestamp'], y=product_df['ask_price_1'], mode='lines', name='Ask 1', line=dict(color='#ff4b4b', width=1), opacity=0.6), row=1, col=1)
    fig.add_trace(go.Scatter(x=product_df['timestamp'], y=product_df['mid_price'], mode='lines', name='Mid Price', line=dict(color='#ffffff', width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=product_df['timestamp'], y=product_df['bid_price_1'], mode='lines', name='Bid 1', line=dict(color='#00c853', width=1), opacity=0.6), row=1, col=1)

    # Indicators
    if show_sma:
        fig.add_trace(go.Scatter(x=product_df['timestamp'], y=product_df[f'SMA_{sma_window}'], mode='lines', name=f'SMA {sma_window}', line=dict(color='#fbc02d', width=1.5, dash='dot')), row=1, col=1)
    if show_bb:
        fig.add_trace(go.Scatter(x=product_df['timestamp'], y=product_df['BB_Upper'], mode='lines', name='BB Upper', line=dict(color='#29b6f6', width=1, dash='dash'), opacity=0.5), row=1, col=1)
        fig.add_trace(go.Scatter(x=product_df['timestamp'], y=product_df['BB_Lower'], mode='lines', name='BB Lower', line=dict(color='#29b6f6', width=1, dash='dash'), opacity=0.5, fill='tonexty', fillcolor='rgba(41, 182, 246, 0.1)'), row=1, col=1)

    # Executed Trades Overlay
    if trades_df is not None and not trades_df.empty:
        product_trades = trades_df[trades_df['symbol'] == product_name]
        if not product_trades.empty:
            fig.add_trace(go.Scatter(
                x=product_trades['timestamp'], y=product_trades['price'],
                mode='markers', name='Trades',
                marker=dict(color='#e040fb', size=7, line=dict(width=1, color='white')),
                text=product_trades['quantity'].apply(lambda x: f"Qty: {x}"),
                hoverinfo="x+y+text"
            ), row=1, col=1)

    # -----------------------------------
    # PANE 2: VOLUME PRESSURE
    # -----------------------------------
    # Plotting Ask Volume (Red/Negative) and Bid Volume (Green/Positive) to see market pressure
    fig.add_trace(go.Bar(x=product_df['timestamp'], y=product_df['bid_volume_1'], name='Bid Vol', marker_color='rgba(0, 200, 83, 0.7)'), row=2, col=1)
    fig.add_trace(go.Bar(x=product_df['timestamp'], y=-product_df['ask_volume_1'], name='Ask Vol', marker_color='rgba(255, 75, 75, 0.7)'), row=2, col=1)

    # -----------------------------------
    # PANE 3: PROFIT & LOSS
    # -----------------------------------
    if 'profit_and_loss' in product_df.columns:
        # Color the PnL line based on whether it is positive or negative
        pnl_color = '#00c853' if product_df['profit_and_loss'].iloc[-1] >= 0 else '#ff4b4b'
        fig.add_trace(go.Scatter(
            x=product_df['timestamp'], y=product_df['profit_and_loss'],
            mode='lines', name='PnL',
            line=dict(color=pnl_color, width=2),
            fill='tozeroy', fillcolor=f"rgba({ '0,200,83' if pnl_color == '#00c853' else '255,75,75'}, 0.1)"
        ), row=3, col=1)

    # Global Formatting
    fig.update_layout(
        template="plotly_dark",
        hovermode="x unified",
        barmode='relative', # Stacks the volume bars symmetrically
        height=800, # Taller chart to accommodate subplots
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    # Hide x-axis labels for top two plots to keep it clean
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    fig.update_xaxes(showticklabels=False, row=2, col=1)
    fig.update_xaxes(title_text="Timestamp", row=3, col=1)

    st.plotly_chart(fig, use_container_width=True)

# Main App Execution
st.title("📈 IMC Prosperity: Quant Terminal")

# Sidebar for Technical Indicator Settings
with st.sidebar:
    st.header("⚙️ Terminal Settings")
    st.markdown("Customize your TradingView-style indicators.")
    show_sma = st.toggle("Show SMA", value=False)
    sma_window = st.slider("SMA Window (Ticks)", 5, 100, 20) if show_sma else 20
    
    show_bb = st.toggle("Show Bollinger Bands", value=False)
    bb_window = st.slider("BB Window (Ticks)", 5, 100, 20) if show_bb else 20

# File Uploaders
col_up1, col_up2 = st.columns(2)
with col_up1:
    prices_file = st.file_uploader("Upload Prices CSV", type=["csv"])
with col_up2:
    trades_file = st.file_uploader("Upload Trades CSV", type=["csv"])

if prices_file is not None:
    df_prices = load_data(prices_file)
    df_trades = load_data(trades_file) if trades_file is not None else None

    p1 = "ASH_COATED_OSMIUM"
    p2 = "INTARIAN_PEPPER_ROOT"
    df_p1 = df_prices[df_prices['product'] == p1].sort_values(by='timestamp')
    df_p2 = df_prices[df_prices['product'] == p2].sort_values(by='timestamp')

    st.divider()

    # Layout Selector
    layout = st.radio("Viewing Layout:", ["Tabs", "Stacked Vertically", "Side-by-Side"], horizontal=True)

    if layout == "Tabs":
        tab1, tab2 = st.tabs([p1, p2])
        with tab1:
            render_product_dashboard(df_p1, p1, df_trades, show_sma, show_bb, sma_window, bb_window)
        with tab2:
            render_product_dashboard(df_p2, p2, df_trades, show_sma, show_bb, sma_window, bb_window)
            
    elif layout == "Stacked Vertically":
        render_product_dashboard(df_p1, p1, df_trades, show_sma, show_bb, sma_window, bb_window)
        st.divider()
        render_product_dashboard(df_p2, p2, df_trades, show_sma, show_bb, sma_window, bb_window)
        
    elif layout == "Side-by-Side":
        col1, col2 = st.columns(2)
        with col1:
            render_product_dashboard(df_p1, p1, df_trades, show_sma, show_bb, sma_window, bb_window)
        with col2:
            render_product_dashboard(df_p2, p2, df_trades, show_sma, show_bb, sma_window, bb_window)

else:
    st.info("Awaiting Prices CSV to initialize terminal...")
