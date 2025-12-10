"""Quick script to fetch more articles without strict filtering"""
from aggregator import NewsAggregator
from database import ArticleDatabase

print("Fetching articles (relaxed filtering)...")
aggregator = NewsAggregator()

# Temporarily relax filtering
original_keywords = aggregator.aggregation_config.get("keywords_filter", [])
aggregator.aggregation_config["keywords_filter"] = []  # Remove keyword requirement

# Collect articles
all_articles = aggregator.collect_all_articles()
print(f"Collected {len(all_articles)} total articles")

# Filter only by date (past month) and minimum length
from datetime import datetime, timedelta
one_month_ago = datetime.now() - timedelta(days=30)

filtered = []
for article in all_articles:
    content = article.get("content", article.get("summary", ""))
    if len(content) < 100:
        continue
    
    # Check date
    try:
        pub_str = article.get("published", "")
        if pub_str:
            pub_date = datetime.fromisoformat(pub_str.replace('Z', '+00:00').split('+')[0])
            days_old = (datetime.now() - pub_date.replace(tzinfo=None)).days
            if days_old <= 45:  # Past 45 days
                filtered.append(article)
        else:
            filtered.append(article)  # Include if no date
    except:
        filtered.append(article)  # Include if date parsing fails

print(f"Filtered to {len(filtered)} articles from past month")

# Save to database
db = ArticleDatabase()
db.save_articles(filtered)
print(f"Saved {len(filtered)} articles to database")

# Restore original config
aggregator.aggregation_config["keywords_filter"] = original_keywords



