import streamlit as st
import yfinance as yf
import pandas_ta as ta
import plotly.graph_objects as go
from datetime import date

# Page config
st.set_page_config(page_title="XChart", layout="wide")

# Sidebar controls
st.sidebar.header("Chart Settings")
ticker = st.sidebar.text_input("Ticker", value="AAPL")
start_date = st.sidebar.date_input("Start Date", value=date(2023, 1, 1))
end_date = st.sidebar.date_input("End Date", value=date.today())
indicators = st.sidebar.multiselect("Indicators", ["RSI", "MACD", "Bollinger Bands", "EMA", "SMA"])

# Header
st.title("📈 XChart Investment Dashboard")
st.markdown("Analyze trends, overlay indicators, and make smarter decisions.")

# Fetch data
data = yf.download(ticker, start=start_date, end=end_date)
if data.empty:
    st.error("No data found. Please check the ticker or date range.")
    st.stop()

# Calculate indicators
if "RSI" in indicators:
    data["RSI"] = ta.rsi(data["Close"])
if "MACD" in indicators:
    macd = ta.macd(data["Close"])
    data["MACD"] = macd["MACD_12_26_9"]
if "Bollinger Bands" in indicators:
    bb = ta.bbands(data["Close"])
    data["BBL"] = bb["BBL_20_2.0"]
    data["BBU"] = bb["BBU_20_2.0"]
if "EMA" in indicators:
    data["EMA"] = ta.ema(data["Close"])
if "SMA" in indicators:
    data["SMA"] = ta.sma(data["Close"])

# Plot chart
fig = go.Figure()
fig.add_trace(go.Candlestick(
    x=data.index,
    open=data["Open"],
    high=data["High"],
    low=data["Low"],
    close=data["Close"],
    name="Candlestick"
))

if "EMA" in indicators:
    fig.add_trace(go.Scatter(x=data.index, y=data["EMA"], name="EMA", line=dict(color="blue")))
if "SMA" in indicators:
    fig.add_trace(go.Scatter(x=data.index, y=data["SMA"], name="SMA", line=dict(color="orange")))
if "Bollinger Bands" in indicators:
    fig.add_trace(go.Scatter(x=data.index, y=data["BBL"], name="BB Lower", line=dict(color="gray", dash="dot")))
    fig.add_trace(go.Scatter(x=data.index, y=data["BBU"], name="BB Upper", line=dict(color="gray", dash="dot")))

st.plotly_chart(fig, use_container_width=True)

# Insights panel
st.markdown("### 📌 Key Insights")
if "RSI" in indicators:
    rsi_value = data["RSI"].iloc[-1]
    if rsi_value < 30:
        st.warning(f"RSI ({rsi_value:.2f}) indicates oversold conditions.")
    elif rsi_value > 70:
        st.info(f"RSI ({rsi_value:.2f}) indicates overbought conditions.")
    else:
        st.success(f"RSI ({rsi_value:.2f}) is in neutral range.")

if "MACD" in indicators:
    macd_value = data["MACD"].iloc[-1]
    st.write(f"MACD value: {macd_value:.2f}")

# Footer
st.markdown("---")
st.markdown("© 2025 [XChart.in](https://www.xchart.in) | Built by Rupak Sarkar", unsafe_allow_html=True)
