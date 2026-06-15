from gnews import GNews
google_news = GNews(max_results=5)
results = google_news.get_news("Reliance Industries")
for r in results:
    print(r.get("title"), r.get("url"), r.get("published date"))
