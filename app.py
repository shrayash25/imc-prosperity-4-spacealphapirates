import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# 1. Page Configuration
st.set_page_config(page_title="IMC Prosperity Trade Viewer", layout="wide", page_icon="📈")

def load_data(file):
    # IMC Prosperity CSVs are semicolon-separated
    df = pd.read_csv(file, sep=';')
    return df

st.title("📈 IMC Prosperity Data Viewer")
st.markdown("Upload your round CSV files to view order book data, mid prices, and spreads.")

# 2. File Uploader
uploaded_file = st.file_uploader("Upload Prices CSV", type=["csv"])

if uploaded_file is not None:
    # Load and cache the data
    with st.spinner("Loading data..."):
        df = load_data(uploaded_file)
    
    # 3. Sidebar Filters
    st.sidebar.header("Filters")
    products = df['product'].unique()
    selected_product = st.sidebar.selectbox("Select a Product", products)
    
    # Filter data by product
    product_df = df[df['product'] == selected_product].copy()
    product_df = product_df.sort_values(by=['day', 'timestamp'])
    
    # Optional: Filter by Day if multiple days exist
    days = product_df['day'].unique()
    if len(days) > 1:
        selected_day = st.sidebar.selectbox("Select Day", days)
        product_df = product_df[product_df['day'] == selected_day]
    
    st.subheader(f"Market Data for {selected_product}")

    # 4. Metrics Summary
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Starting Mid Price", f"{product_df['mid_price'].iloc[0]:.2f}")
    col2.metric("Ending Mid Price", f"{product_df['mid_price'].iloc[-1]:.2f}")
    col3.metric("Max Price", f"{product_df['mid_price'].max():.2f}")
    col4.metric("Min Price", f"{product_df['mid_price'].min():.2f}")

    # 5. Interactive Plotly Chart
    fig = go.Figure()

    # Add Ask Line
    fig.add_trace(go.Scatter(
        x=product_df['timestamp'], 
        y=product_df['ask_price_1'],
        mode='lines',
        name='Ask Price 1',
        line=dict(color='#ff4b4b', width=1),
        opacity=0.7
    ))

    # Add Mid Line
    fig.add_trace(go.Scatter(
        x=product_df['timestamp'], 
        y=product_df['mid_price'],
        mode='lines',
        name='Mid Price',
        line=dict(color='#ffffff', width=2)
    ))

    # Add Bid Line
    fig.add_trace(go.Scatter(
        x=product_df['timestamp'], 
        y=product_df['bid_price_1'],
        mode='lines',
        name='Bid Price 1',
        line=dict(color='#00c853', width=1),
        opacity=0.7
    ))

    # Chart formatting
    fig.update_layout(
        title=f"{selected_product} Order Book Top Level",
        xaxis_title="Timestamp",
        yaxis_title="Price",
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        margin=dict(l=0, r=0, t=40, b=0)
    )

    # Display Chart
    st.plotly_chart(fig, use_container_width=True)

    # 6. Raw Data Expander
    with st.expander("View Raw Data"):
        st.dataframe(product_df, use_container_width=True)
else:
    st.info("Please upload a CSV file to get started.")
