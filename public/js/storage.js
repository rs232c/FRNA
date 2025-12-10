/**
 * Client-Side Storage Manager - Per-zip data isolation
 * Uses localStorage for simple data and IndexedDB for articles
 */

class StorageManager {
    constructor() {
        this.dbName = 'FRNA_NewsDB';
        this.dbVersion = 1;
        this.db = null;
        this.dbReady = this.initDB(); // Store promise for async initialization
    }

    // Helper method to ensure DB is ready before use
    async ensureDBReady() {
        if (!this.db) {
            await this.dbReady;
        }
        return this.db;
    }

    async initDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.dbVersion);
            
            request.onerror = () => reject(request.error);
            request.onsuccess = () => {
                this.db = request.result;
                resolve(this.db);
            };
            
            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                
                // Create object stores for each zip (we'll create dynamically)
                // For now, create a general articles store
                if (!db.objectStoreNames.contains('articles')) {
                    const articlesStore = db.createObjectStore('articles', { keyPath: 'id' });
                    articlesStore.createIndex('zip', 'zip', { unique: false });
                    articlesStore.createIndex('published', 'published', { unique: false });
                }
                
                if (!db.objectStoreNames.contains('settings')) {
                    db.createObjectStore('settings', { keyPath: 'key' });
                }
            };
        });
    }

    // Validation helper
    _validateZip(zip) {
        if (!zip || !/^\d{5}$/.test(zip)) {
            throw new Error(`Invalid zip code: ${zip}. Must be 5 digits.`);
        }
        return zip;
    }

    // LocalStorage methods (per-zip) - CRITICAL: All methods validate zip
    getBayesianData(zip) {
        zip = this._validateZip(zip);
        const key = `bayesian_${zip}`;
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : { keywords: {}, totalGood: 0, totalBad: 0 };
    }

    setBayesianData(zip, data) {
        zip = this._validateZip(zip);
        const key = `bayesian_${zip}`;
        localStorage.setItem(key, JSON.stringify(data));
    }

    getTopStories(zip) {
        zip = this._validateZip(zip);
        const key = `topStories_${zip}`;
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : [];
    }

    setTopStories(zip, storyIds) {
        zip = this._validateZip(zip);
        const key = `topStories_${zip}`;
        localStorage.setItem(key, JSON.stringify(storyIds));
    }

    addTopStory(zip, articleId) {
        zip = this._validateZip(zip);
        const topStories = this.getTopStories(zip);
        const articleIdStr = articleId?.toString();
        if (!topStories.includes(articleIdStr)) {
            topStories.push(articleIdStr);
            this.setTopStories(zip, topStories);
        }
    }

    removeTopStory(zip, articleId) {
        zip = this._validateZip(zip);
        const topStories = this.getTopStories(zip);
        const articleIdStr = articleId?.toString();
        const filtered = topStories.filter(id => id !== articleIdStr);
        this.setTopStories(zip, filtered);
    }

    getTrashed(zip) {
        zip = this._validateZip(zip);
        const key = `trashed_${zip}`;
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : [];
    }

    addTrashed(zip, articleId) {
        zip = this._validateZip(zip);
        const trashed = this.getTrashed(zip);
        const articleIdStr = articleId?.toString();
        if (!trashed.includes(articleIdStr)) {
            trashed.push(articleIdStr);
            const key = `trashed_${zip}`;
            localStorage.setItem(key, JSON.stringify(trashed));
        }
    }

    removeTrashed(zip, articleId) {
        zip = this._validateZip(zip);
        const trashed = this.getTrashed(zip);
        const articleIdStr = articleId?.toString();
        const filtered = trashed.filter(id => id !== articleIdStr);
        const key = `trashed_${zip}`;
        localStorage.setItem(key, JSON.stringify(filtered));
    }

    getDisabled(zip) {
        zip = this._validateZip(zip);
        const key = `disabled_${zip}`;
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : [];
    }

    setDisabled(zip, articleId, disabled) {
        zip = this._validateZip(zip);
        const disabledList = this.getDisabled(zip);
        const articleIdStr = articleId?.toString();
        if (disabled && !disabledList.includes(articleIdStr)) {
            disabledList.push(articleIdStr);
        } else if (!disabled) {
            const index = disabledList.indexOf(articleIdStr);
            if (index > -1) disabledList.splice(index, 1);
        }
        const key = `disabled_${zip}`;
        localStorage.setItem(key, JSON.stringify(disabledList));
    }

    getRelevanceScores(zip) {
        zip = this._validateZip(zip);
        const key = `relevanceScores_${zip}`;
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : {};
    }

    setRelevanceScore(zip, articleId, score) {
        zip = this._validateZip(zip);
        const scores = this.getRelevanceScores(zip);
        scores[articleId] = score;
        const key = `relevanceScores_${zip}`;
        localStorage.setItem(key, JSON.stringify(scores));
    }

    getGoodFitArticles(zip) {
        zip = this._validateZip(zip);
        const key = `goodFit_${zip}`;
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : [];
    }

    // Relevance Configuration (per-zip)
    getRelevanceConfig(zip) {
        zip = this._validateZip(zip);
        const key = `relevanceConfig_${zip}`;
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : {
            high_relevance: [],
            medium_relevance: [],
            local_places: [],
            topic_keywords: {},
            source_credibility: {},
            clickbait_patterns: []
        };
    }

    setRelevanceConfig(zip, config) {
        zip = this._validateZip(zip);
        const key = `relevanceConfig_${zip}`;
        localStorage.setItem(key, JSON.stringify(config));
    }

    // Sources Configuration (per-zip)
    getSources(zip) {
        zip = this._validateZip(zip);
        const key = `sources_${zip}`;
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : {};
    }

    setSources(zip, sources) {
        zip = this._validateZip(zip);
        const key = `sources_${zip}`;
        localStorage.setItem(key, JSON.stringify(sources));
    }

    // Settings (per-zip)
    getSettings(zip) {
        zip = this._validateZip(zip);
        const key = `settings_${zip}`;
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : {
            show_images: true,
            relevance_threshold: 10.0,
            ai_filtering_enabled: false,
            auto_regenerate: false,
            regenerate_interval: 10
        };
    }

    setSettings(zip, settings) {
        zip = this._validateZip(zip);
        const key = `settings_${zip}`;
        localStorage.setItem(key, JSON.stringify(settings));
    }

    // Auto-filtered articles (per-zip)
    getAutoFiltered(zip) {
        zip = this._validateZip(zip);
        const key = `autoFiltered_${zip}`;
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : [];
    }

    addAutoFiltered(zip, articleId, reason) {
        zip = this._validateZip(zip);
        const autoFiltered = this.getAutoFiltered(zip);
        const articleIdStr = articleId?.toString();
        if (!autoFiltered.find(item => item.id === articleIdStr)) {
            autoFiltered.push({ id: articleIdStr, reason: reason || 'Auto-filtered' });
            const key = `autoFiltered_${zip}`;
            localStorage.setItem(key, JSON.stringify(autoFiltered));
        }
    }

    removeAutoFiltered(zip, articleId) {
        zip = this._validateZip(zip);
        const autoFiltered = this.getAutoFiltered(zip);
        const articleIdStr = articleId?.toString();
        const filtered = autoFiltered.filter(item => item.id !== articleIdStr);
        const key = `autoFiltered_${zip}`;
        localStorage.setItem(key, JSON.stringify(filtered));
    }

    addGoodFit(zip, articleId) {
        zip = this._validateZip(zip);
        const goodFit = this.getGoodFitArticles(zip);
        const articleIdStr = articleId?.toString();
        if (!goodFit.includes(articleIdStr)) {
            goodFit.push(articleIdStr);
            const key = `goodFit_${zip}`;
            localStorage.setItem(key, JSON.stringify(goodFit));
            this.updateBayesianFromGoodFit(zip, articleId);
        }
    }

    removeGoodFit(zip, articleId) {
        zip = this._validateZip(zip);
        const goodFit = this.getGoodFitArticles(zip);
        const articleIdStr = articleId?.toString();
        const filtered = goodFit.filter(id => id !== articleIdStr);
        const key = `goodFit_${zip}`;
        localStorage.setItem(key, JSON.stringify(filtered));
    }

    // Update Bayesian data from good fit articles
    updateBayesianFromGoodFit(zip, articleId) {
        // This will be called when we have article data
        // For now, just increment totalGood
        const bayesian = this.getBayesianData(zip);
        bayesian.totalGood++;
        this.setBayesianData(zip, bayesian);
    }

    // IndexedDB methods for articles - CRITICAL: All methods validate zip
    async saveArticle(zip, article) {
        zip = this._validateZip(zip);
        await this.ensureDBReady(); // Wait for DB to be ready
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction(['articles'], 'readwrite');
            const store = transaction.objectStore('articles');
            const articleWithZip = { ...article, zip };
            const request = store.put(articleWithZip);
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }

    async getArticles(zip) {
        zip = this._validateZip(zip);
        await this.ensureDBReady(); // Wait for DB to be ready
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction(['articles'], 'readonly');
            const store = transaction.objectStore('articles');
            const index = store.index('zip');
            const request = index.getAll(zip);
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error);
        });
    }

    async deleteArticle(zip, articleId) {
        zip = this._validateZip(zip);
        await this.ensureDBReady(); // Wait for DB to be ready
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction(['articles'], 'readwrite');
            const store = transaction.objectStore('articles');
            const request = store.delete(articleId);
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    }

    // Settings storage - CRITICAL: All methods validate zip
    async getSetting(zip, key) {
        zip = this._validateZip(zip);
        await this.ensureDBReady(); // Wait for DB to be ready
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction(['settings'], 'readonly');
            const store = transaction.objectStore('settings');
            const fullKey = `${zip}_${key}`;
            const request = store.get(fullKey);
            request.onsuccess = () => {
                resolve(request.result ? request.result.value : null);
            };
            request.onerror = () => reject(request.error);
        });
    }

    async setSetting(zip, key, value) {
        zip = this._validateZip(zip);
        await this.ensureDBReady(); // Wait for DB to be ready
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction(['settings'], 'readwrite');
            const store = transaction.objectStore('settings');
            const fullKey = `${zip}_${key}`;
            const request = store.put({ key: fullKey, value });
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    }
}

// Initialize storage manager
let storageManager;
if (typeof window !== 'undefined') {
    storageManager = new StorageManager();
    window.storageManager = storageManager;
}

