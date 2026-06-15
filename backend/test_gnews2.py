from gnews import GNews
google_news = GNews(max_results=2)
results = google_news.get_news("Reliance Industries")
for r in results:
    print(r.keys())
    print("Description:", r.get("description"))
