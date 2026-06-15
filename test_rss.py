import os
import sys

sys.path.append(os.path.join(os.getcwd(), 'backend'))
from src.data.news import fetch_news_google_rss

def test_rss():
    print("Testing standard query...")
    res = fetch_news_google_rss("TCS", max_results=2)
    for r in res:
        print(f"Title: {r['title']}")
        
    print("\nTesting quoted query...")
    import urllib.parse
    import requests
    import feedparser
    from datetime import datetime, timedelta
    
    query = '"TCS" stock'
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    resp = requests.get(url, timeout=8)
    feed = feedparser.parse(resp.text)
    for entry in feed.entries[:2]:
        print(f"Title: {entry.get('title')}")

if __name__ == "__main__":
    test_rss()
