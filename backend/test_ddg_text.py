from ddgs import DDGS
with DDGS() as ddgs:
    results = list(ddgs.text("Why did Indian market crash today?", max_results=3))
    for r in results:
        print(r)
