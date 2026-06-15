try:
    from googlesearch import search
    results = search("reliance industries news", num_results=5, advanced=True)
    for r in results:
        print(r.title, r.url, r.description)
except Exception as e:
    print("Failed:", e)
