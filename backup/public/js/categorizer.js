/**
 * Article Categorizer - Auto-categorizes articles based on content
 */

class ArticleCategorizer {
    constructor() {
        this.keywords = {
            sports: [
                'sport', 'game', 'team', 'player', 'coach', 'stadium', 'match', 'score',
                'football', 'basketball', 'baseball', 'soccer', 'hockey', 'golf', 'tennis',
                'championship', 'tournament', 'league', 'athlete', 'coaching', 'playoff'
            ],
            entertainment: [
                'entertainment', 'movie', 'show', 'music', 'concert', 'celebrity', 'actor',
                'theater', 'performance', 'festival', 'comedy', 'drama', 'film', 'album',
                'artist', 'singer', 'band', 'tour', 'premiere', 'award'
            ],
            media: [
                'video', 'youtube', 'watch', 'stream', 'media', 'broadcast', 'television',
                'tv', 'podcast', 'radio', 'interview', 'documentary', 'series', 'episode'
            ],
            events: [
                'event', 'meeting', 'festival', 'concert', 'workshop', 'seminar',
                'celebration', 'gathering', 'show', 'performance', 'exhibition',
                'fair', 'market', 'sale', 'tournament', 'competition', 'race',
                'parade', 'ceremony', 'announcement', 'happening', 'activity',
                'upcoming', 'coming', 'this weekend', 'next week'
            ],
            news: [
                'news', 'report', 'breaking', 'update', 'announcement', 'statement',
                'government', 'city', 'mayor', 'council', 'policy', 'law', 'crime',
                'accident', 'fire', 'police', 'emergency', 'weather', 'forecast'
            ]
        };
    }

    categorize(article) {
        const text = `${article.title || ''} ${article.summary || ''} ${article.content || ''}`.toLowerCase();
        
        // Count keyword matches for each category
        const scores = {};
        for (const [category, keywords] of Object.entries(this.keywords)) {
            scores[category] = keywords.filter(keyword => text.includes(keyword)).length;
        }
        
        // Find category with highest score
        let maxScore = 0;
        let bestCategory = 'news'; // Default
        
        for (const [category, score] of Object.entries(scores)) {
            if (score > maxScore) {
                maxScore = score;
                bestCategory = category;
            }
        }
        
        // If no strong match, use default
        if (maxScore === 0) {
            return 'news';
        }
        
        return bestCategory;
    }

    categorizeBatch(articles) {
        return articles.map(article => {
            if (!article.category) {
                article.category = this.categorize(article);
            }
            return article;
        });
    }
}

// Initialize categorizer
let categorizer;
if (typeof window !== 'undefined') {
    categorizer = new ArticleCategorizer();
    window.categorizer = categorizer;
}

