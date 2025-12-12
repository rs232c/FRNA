/**
 * Category Preferences Manager
 * Manages user preferences for which categories to show/hide in navigation
 * Stores preferences in localStorage
 */

class CategoryPreferences {
    constructor() {
        this.storageKey = 'categoryPreferences';
        this.defaultCategories = {
            'local-news': true,
            'crime': true,
            'sports': true,
            'obituaries': true,
            'food': true,
            'media': true,
            'scanner': true,
            'weather': true,
            'submit-tip': true,
            'lost-found': true,
            'events': true
        };
        this.init();
    }

    init() {
        // Initialize preferences if they don't exist
        if (!this.getPreferences()) {
            this.resetToDefaults();
        }
    }

    /**
     * Get all preferences from localStorage
     */
    getPreferences() {
        try {
            const stored = localStorage.getItem(this.storageKey);
            if (stored) {
                return JSON.parse(stored);
            }
        } catch (e) {
            console.error('Error reading category preferences:', e);
        }
        return null;
    }

    /**
     * Save preferences to localStorage
     */
    savePreferences(prefs) {
        try {
            localStorage.setItem(this.storageKey, JSON.stringify(prefs));
            // Dispatch event for other components to listen
            window.dispatchEvent(new CustomEvent('categoryPreferencesChanged', { detail: prefs }));
        } catch (e) {
            console.error('Error saving category preferences:', e);
        }
    }

    /**
     * Get list of enabled category slugs
     */
    getEnabledCategories() {
        const prefs = this.getPreferences();
        if (!prefs) return Object.keys(this.defaultCategories);
        
        return Object.keys(prefs).filter(slug => prefs[slug] === true);
    }

    /**
     * Check if a specific category is enabled
     */
    isCategoryEnabled(slug) {
        const prefs = this.getPreferences();
        if (!prefs) {
            // Default: all categories enabled
            return this.defaultCategories[slug] !== false;
        }
        return prefs[slug] === true;
    }

    /**
     * Toggle a category on/off
     */
    toggleCategory(slug, enabled) {
        const prefs = this.getPreferences() || { ...this.defaultCategories };
        prefs[slug] = enabled;
        this.savePreferences(prefs);
        return prefs;
    }

    /**
     * Reset all categories to default (all enabled)
     */
    resetToDefaults() {
        this.savePreferences({ ...this.defaultCategories });
    }

    /**
     * Get all available categories
     */
    getAllCategories() {
        return Object.keys(this.defaultCategories);
    }

    /**
     * Get category display name from slug
     */
    getCategoryDisplayName(slug) {
        const nameMap = {
            'local-news': 'Local',
            'crime': 'Police & Fire',
            'sports': 'Sports',
            'obituaries': 'Obituaries',
            'food': 'Food & Drink',
            'media': 'Media',
            'scanner': 'Scanner',
            'weather': 'Weather',
            'submit-tip': 'Submit Tip',
            'lost-found': 'Lost & Found',
            'events': 'Events'
        };
        return nameMap[slug] || slug;
    }

    /**
     * Get category row (primary or secondary)
     */
    getCategoryRow(slug) {
        const primaryCategories = ['local-news', 'crime', 'sports', 'obituaries', 'food'];
        return primaryCategories.includes(slug) ? 'primary' : 'secondary';
    }
}

// Create global instance
window.CategoryPreferences = new CategoryPreferences();

