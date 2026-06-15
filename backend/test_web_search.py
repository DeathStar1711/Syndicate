from src.llm.tools import perform_web_search

print("Testing Ticker Search (RELIANCE.NS):")
results_ticker = perform_web_search("RELIANCE.NS recent news", max_results=2)
print(results_ticker)

print("\n------------------\n")

print("Testing General Search:")
results_general = perform_web_search("Indian market crash today", max_results=2)
print(results_general)
