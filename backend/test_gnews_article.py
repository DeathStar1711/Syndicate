from gnews import GNews
google_news = GNews(max_results=1)
results = google_news.get_news("Reliance Industries")
for r in results:
    print("Title:", r.get("title"))
    try:
        article = google_news.get_full_article(r.get("url"))
        print("Article preview:", article.text[:200] if article else "None")
    except Exception as e:
        print("Failed to get article:", e)
