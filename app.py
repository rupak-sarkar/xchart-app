import streamlit as st
from datetime import date

st.set_page_config(page_title="XChart", layout="wide")

# Sidebar
st.sidebar.header("Chart Settings")
ticker = st.sidebar.text_input("Ticker", value="AAPL")
start_date = st.sidebar.date_input("Start Date", value=date(2023, 1, 1))
end_date = st.sidebar.date_input("End Date", value=date.today())
indicator = st.sidebar.multiselect("Indicators", ["RSI", "MACD", "Bollinger Bands", "EMA", "SMA"])

# Main Header
st.title("📈 XChart Investment Dashboard")
st.markdown("Analyze trends, overlay indicators, and make smarter decisions.")

# Chart Area
st.subheader(f"Price Chart for {ticker}")
st.info("Chart will appear here once data is loaded.")

# Insights Panel
st.markdown("### 📌 Key Insights")
st.write("• RSI suggests oversold conditions")
st.write("• MACD crossover detected")
