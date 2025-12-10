/**
 * Stats Manager - Calculates real-time statistics from article data
 */

class StatsManager {
    constructor() {
        this.stats = {};
    }

    updateStats(zip, articles) {
        // CRITICAL: Must have zip code
        if (!zip || !/^\d{5}$/.test(zip) || !window.storageManager) {
            console.error('Invalid zip code for stats:', zip);
            return;
        }

        // CRITICAL: Always use the zip parameter - never use any other zip
        const trashed = window.storageManager.getTrashed(zip);
        const disabled = window.storageManager.getDisabled(zip);
        const topStories = window.storageManager.getTopStories(zip);
        const goodFit = window.storageManager.getGoodFitArticles(zip);

        // Calculate stats
        const total = articles.length;
        const trashedCount = trashed.length;
        const disabledCount = disabled.length;
        const active = total - trashedCount - disabledCount;
        const topStoriesCount = topStories.length;
        const goodFitCount = goodFit.length;

        // Last 7 days
        const sevenDaysAgo = new Date();
        sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
        const last7Days = articles.filter(article => {
            if (!article.published) return false;
            const pubDate = new Date(article.published);
            return pubDate >= sevenDaysAgo;
        }).length;

        // Per-source breakdown
        const sourceBreakdown = {};
        articles.forEach(article => {
            const source = article.source_display || article.source || 'Unknown';
            sourceBreakdown[source] = (sourceBreakdown[source] || 0) + 1;
        });

        this.stats[zip] = {
            total,
            active,
            trashed: trashedCount,
            disabled: disabledCount,
            topStories: topStoriesCount,
            goodFit: goodFitCount,
            last7Days,
            sourceBreakdown
        };

        this.renderStats(zip);
    }

    renderStats(zip) {
        const stats = this.stats[zip];
        if (!stats) return;

        // Render quick stats
        const quickStatsContainer = document.getElementById('stats-content');
        if (quickStatsContainer) {
            quickStatsContainer.innerHTML = `
                <div style="background: #1a1a1a; padding: 1rem; border-radius: 4px;">
                    <div style="color: #888; font-size: 0.85rem; margin-bottom: 0.5rem;">Total Articles</div>
                    <div style="color: #0078d4; font-size: 2rem; font-weight: bold;">${stats.total}</div>
                </div>
                <div style="background: #1a1a1a; padding: 1rem; border-radius: 4px;">
                    <div style="color: #888; font-size: 0.85rem; margin-bottom: 0.5rem;">Active</div>
                    <div style="color: #4caf50; font-size: 2rem; font-weight: bold;">${stats.active}</div>
                </div>
                <div style="background: #1a1a1a; padding: 1rem; border-radius: 4px;">
                    <div style="color: #888; font-size: 0.85rem; margin-bottom: 0.5rem;">Rejected</div>
                    <div style="color: #d32f2f; font-size: 2rem; font-weight: bold;">${stats.trashed}</div>
                </div>
                <div style="background: #1a1a1a; padding: 1rem; border-radius: 4px;">
                    <div style="color: #888; font-size: 0.85rem; margin-bottom: 0.5rem;">Top Stories</div>
                    <div style="color: #ff9800; font-size: 2rem; font-weight: bold;">${stats.topStories}</div>
                </div>
                <div style="background: #1a1a1a; padding: 1rem; border-radius: 4px;">
                    <div style="color: #888; font-size: 0.85rem; margin-bottom: 0.5rem;">Last 7 Days</div>
                    <div style="color: #9c27b0; font-size: 2rem; font-weight: bold;">${stats.last7Days}</div>
                </div>
                <div style="background: #1a1a1a; padding: 1rem; border-radius: 4px;">
                    <div style="color: #888; font-size: 0.85rem; margin-bottom: 0.5rem;">Good Fit</div>
                    <div style="color: #4caf50; font-size: 2rem; font-weight: bold;">${stats.goodFit}</div>
                </div>
            `;
        }

        // Render detailed stats
        const detailedStatsContainer = document.getElementById('detailed-stats');
        if (detailedStatsContainer) {
            const sourceList = Object.entries(stats.sourceBreakdown)
                .sort((a, b) => b[1] - a[1])
                .map(([source, count]) => `
                    <div style="display: flex; justify-content: space-between; padding: 0.75rem; border-bottom: 1px solid #404040;">
                        <span style="color: #e0e0e0;">${source}</span>
                        <span style="color: #0078d4; font-weight: bold;">${count}</span>
                    </div>
                `).join('');

            detailedStatsContainer.innerHTML = `
                <div style="background: #252525; padding: 1.5rem; border-radius: 8px; margin-bottom: 1rem;">
                    <h3 style="color: #0078d4; margin-bottom: 1rem;">Source Breakdown</h3>
                    <div style="background: #1a1a1a; border-radius: 4px; overflow: hidden;">
                        ${sourceList || '<div style="padding: 1rem; color: #888;">No source data available</div>'}
                    </div>
                </div>
            `;
        }
    }
}

// Initialize stats manager
let statsManager;
if (typeof window !== 'undefined') {
    statsManager = new StatsManager();
    window.statsManager = statsManager;
}

