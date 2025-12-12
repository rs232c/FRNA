"""
Script to train Bayesian model from existing rejected articles
Run this once to initialize the model with historical rejections
"""
import sqlite3
import logging
from utils.bayesian_learner import BayesianLearner
from config import DATABASE_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def train_from_existing_rejections():
    """Train Bayesian model from all existing rejected articles"""
    db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
    learner = BayesianLearner()
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all rejected articles
        cursor.execute('''
            SELECT a.title, a.content, a.summary, a.source
            FROM articles a
            JOIN article_management am ON a.id = am.article_id
            WHERE am.is_rejected = 1
        ''')
        
        rejected_articles = cursor.fetchall()
        conn.close()
        
        logger.info(f"Found {len(rejected_articles)} rejected articles to train from")
        
        trained = 0
        for row in rejected_articles:
            title, content, summary, source = row
            article = {
                'title': title or '',
                'content': content or summary or '',
                'summary': summary or '',
                'source': source or ''
            }
            
            if article['title'] or article['content']:
                learner.train_from_rejection(article)
                trained += 1
        
        logger.info(f"Trained Bayesian model from {trained} rejected articles")
        logger.info("Model is now ready to filter similar articles")
        
    except Exception as e:
        logger.error(f"Error training from existing rejections: {e}")

if __name__ == "__main__":
    train_from_existing_rejections()

