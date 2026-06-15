import os
import sys

sys.path.append(os.path.join(os.getcwd(), 'backend'))

from src.data.groww_mcp import fetch_fundamentals_screener_sync
from src.utils.helpers import get_tickers

def check_intersection():
    print("Loading watchlist...")
    watchlist_tickers = get_tickers()
    print(f"Loaded {len(watchlist_tickers)} tickers from watchlist.")
    
    print("Fetching fundamental top 50 from Groww...")
    query = "high ROE, low debt to equity, high profit margins"
    results = fetch_fundamentals_screener_sync(query, max_results=50)
    
    fundamental_tickers_list = []
    for r in results:
        code = r.get("nse_script_code")
        if code and f"{code}.NS" not in fundamental_tickers_list:
            fundamental_tickers_list.append(f"{code}.NS")
            
    print(f"Fetched {len(fundamental_tickers_list)} fundamental tickers.")
    
    intersection = [t for t in watchlist_tickers if t in fundamental_tickers_list]
    
    print(f"\nIntersection size: {len(intersection)}")
    if intersection:
        print(f"Intersection tickers: {intersection}")
    else:
        print("Intersection is EMPTY.")
        print("\nTop 5 fundamental tickers returned by screener:")
        print(fundamental_tickers_list[:5])
        
if __name__ == "__main__":
    check_intersection()
