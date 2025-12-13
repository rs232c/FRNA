#!/usr/bin/env python3
"""
Test the improved data pipeline on recent articles
"""

import sqlite3
from aggregator import NewsAggregator
from config import DATABASE_CONFIG

def test_pipeline_improvements():
    """Test the improved pipeline on recent articles"""

    print("TESTING IMPROVED DATA PIPELINE")
    print("=" * 50)

    # Get the last 100 articles from database
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, title, content, summary, source, relevance_score, published
        FROM articles
        WHERE zip_code = '02720'
        ORDER BY id DESC
        LIMIT 100
    ''')

    recent_articles = []
    for row in cursor.fetchall():
        article_id, title, content, summary, source, old_score, published = row
        recent_articles.append({
            'id': article_id,
            'title': title,
            'content': content or '',
            'summary': summary or '',
            'source': source,
            'relevance_score': old_score,
            'published': published
        })

    conn.close()

    print(f"Testing on {len(recent_articles)} recent articles...")

    # Test with improved aggregator
    aggregator = NewsAggregator()

    # Reprocess articles
    print("\nReprocessing with improved pipeline...")
    filtered_articles = aggregator.filter_relevant_articles(recent_articles, zip_code="02720")

    # Analyze results
    before_stats = {
        'total': len(recent_articles),
        'would_be_enabled': sum(1 for a in recent_articles if a.get('relevance_score', 0) >= 25),  # Old threshold
        'avg_score': sum(a.get('relevance_score', 0) for a in recent_articles) / len(recent_articles)
    }

    after_stats = {
        'total': len(filtered_articles),
        'enabled': len(filtered_articles),
        'avg_score': sum(a.get('_relevance_score', 0) for a in filtered_articles) / max(1, len(filtered_articles))
    }

    print("\nBEFORE/AFTER COMPARISON:")
    print("-" * 40)
    print(f"BEFORE: {before_stats['total']} articles, {before_stats['would_be_enabled']} enabled ({before_stats['would_be_enabled']/before_stats['total']*100:.1f}%), avg score {before_stats['avg_score']:.1f}")
    print(f"AFTER:  {after_stats['total']} articles, {after_stats['enabled']} enabled ({after_stats['enabled']/after_stats['total']*100:.1f}%), avg score {after_stats['avg_score']:.1f}")

    improvement = {
        'articles_saved': after_stats['enabled'] - before_stats['would_be_enabled'],
        'score_improvement': after_stats['avg_score'] - before_stats['avg_score']
    }

    print("\nIMPROVEMENTS:")
    print(f"  Articles preserved: +{improvement['articles_saved']} ({improvement['articles_saved']/before_stats['total']*100:.1f}%)")
    print(f"  Relevance score: +{improvement['score_improvement']:.1f} points")

    # Show top 5 articles that were saved
    print("\nTOP ARTICLES NOW INCLUDED:")
    for i, article in enumerate(filtered_articles[:5]):
        score = article.get('_relevance_score', 0)
        source = article.get('source', 'Unknown')
        title = article.get('title', '')[:50]
        print(f"  {i+1}. {score:.1f}: {title}... ({source})")

    # Check source-specific improvements
    print("\nSOURCE-SPECIFIC IMPROVEMENTS:")
    source_stats = {}
    for article in recent_articles:
        source = article.get('source', 'Unknown')
        if source not in source_stats:
            source_stats[source] = {'before': 0, 'after': 0, 'total': 0}
        source_stats[source]['total'] += 1
        if article.get('relevance_score', 0) >= 25:
            source_stats[source]['before'] += 1

    for article in filtered_articles:
        source = article.get('source', 'Unknown')
        if source in source_stats:
            source_stats[source]['after'] += 1

    for source, stats in sorted(source_stats.items(), key=lambda x: x[1]['total'], reverse=True)[:5]:
        before_pct = stats['before'] / max(1, stats['total']) * 100
        after_pct = stats['after'] / max(1, stats['total']) * 100
        improvement = after_pct - before_pct
        print(f"  {source}: {stats['before']}/{stats['total']} -> {stats['after']}/{stats['total']} ({improvement:+.1f}%)")

    return improvement

if __name__ == "__main__":
    test_pipeline_improvements()