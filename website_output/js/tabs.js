/**
 * Tabs System - Handles tab navigation and filtering
 */

class TabsManager {
    constructor() {
        this.currentTab = 'all';
        this.init();
    }

    init() {
        // Get tab from URL or default to 'all'
        const urlParams = new URLSearchParams(window.location.search);
        const tabParam = urlParams.get('tab');
        if (tabParam) {
            this.currentTab = tabParam;
        }

        // Set up tab click handlers
        document.querySelectorAll('[data-tab]').forEach(tab => {
            tab.addEventListener('click', (e) => {
                e.preventDefault();
                const tabName = tab.dataset.tab;
                this.switchTab(tabName);
            });
        });

        // Update active tab
        this.updateActiveTab();
        
        // Filter articles by current tab
        this.filterArticles();
    }

    switchTab(tabName) {
        this.currentTab = tabName;
        
        // Update URL without reload
        const url = new URL(window.location);
        url.searchParams.set('tab', tabName);
        window.history.pushState({}, '', url);
        
        // Update active tab UI
        this.updateActiveTab();
        
        // Filter articles
        this.filterArticles();
    }

    updateActiveTab() {
        document.querySelectorAll('[data-tab]').forEach(tab => {
            if (tab.dataset.tab === this.currentTab) {
                tab.classList.add('bg-gray-700', 'text-blue-400');
                tab.classList.remove('text-gray-300', 'hover:bg-gray-700', 'hover:text-gray-100');
            } else {
                tab.classList.remove('bg-gray-700', 'text-blue-400');
                tab.classList.add('text-gray-300', 'hover:bg-gray-700', 'hover:text-gray-100');
            }
        });
    }

    filterArticles() {
        const articles = document.querySelectorAll('#articlesGrid article[data-category]');
        const heroSection = document.getElementById('hero-section');
        
        articles.forEach(article => {
            const category = article.dataset.category;
            
            if (this.currentTab === 'all' || !this.currentTab) {
                article.style.display = '';
            } else if (category === this.currentTab) {
                article.style.display = '';
            } else {
                article.style.display = 'none';
            }
        });

        // Also filter hero section if it has category
        if (heroSection) {
            const heroArticle = heroSection.querySelector('article, a[data-category]');
            if (heroArticle) {
                const category = heroArticle.dataset.category;
                if (this.currentTab === 'all' || !this.currentTab || category === this.currentTab) {
                    heroSection.style.display = '';
                } else {
                    heroSection.style.display = 'none';
                }
            }
        }
    }
}

// Initialize tabs manager
let tabsManager;
if (typeof window !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            tabsManager = new TabsManager();
            window.tabsManager = tabsManager;
        });
    } else {
        tabsManager = new TabsManager();
        window.tabsManager = tabsManager;
    }
}

