import yfinance as yf
stock = yf.Ticker("RELIANCE.NS")
print(stock.news)
