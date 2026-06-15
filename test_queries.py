import os
import sys

sys.path.append(os.path.join(os.getcwd(), 'backend'))

from src.data.groww_mcp import fetch_fundamentals_screener_sync
from src.utils.helpers import get_tickers

def test_queries():
    watchlist_tickers = get_tickers()
    
    queries = [
        "Nifty 100 stocks with high ROE and low debt",
        "Large cap stocks with high ROE, low debt to equity, high profit margins",
        "Top Nifty 50 companies by ROE",
        "High ROE mid cap stocks"
    ]
    
    for query in queries:
        print(f"\n--- Testing Query: '{query}' ---")
        results = fetch_fundamentals_screener_sync(query, max_results=50)
        
        fundamental_tickers_list = []
        for r in results:
            code = r.get("nse_script_code")
            if code and f"{code}.NS" not in fundamental_tickers_list:
                fundamental_tickers_list.append(f"{code}.NS")
                
        intersection = [t for t in watchlist_tickers if t in fundamental_tickers_list]
        print(f"Total returned: {len(fundamental_tickers_list)}")
        print(f"Intersection size: {len(intersection)}")
        if intersection:
            print(f"Intersection: {intersection[:5]}")
        else:
            if fundamental_tickers_list:
                print(f"Top 5 returned: {fundamental_tickers_list[:5]}")
            else:
                print("No results returned.")

if __name__ == "__main__":
    test_queries()
