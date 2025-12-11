/**
 * Navigation Filter
 * Filters navigation items based on user category preferences
 */

class NavigationFilter {
    constructor() {
        this.preferences = window.CategoryPreferences;
        this.init();
    }

    init() {
        // Wait for DOM and preferences to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.applyFilters());
        } else {
            this.applyFilters();
        }

        // Listen for preference changes
        window.addEventListener('categoryPreferencesChanged', () => {
            this.applyFilters();
        });
    }

    /**
     * Apply filters to navigation based on preferences
     */
    applyFilters() {
        if (!this.preferences) {
            // Wait a bit and try again
            setTimeout(() => this.applyFilters(), 100);
            return;
        }

        // Filter desktop navigation
        this.filterDesktopNavigation();
        
        // Filter mobile navigation
        this.filterMobileNavigation();
    }

    /**
     * Filter desktop navigation links
     */
    filterDesktopNavigation() {
        const navLinks = document.querySelectorAll('.nav-category-link');
        
        navLinks.forEach(link => {
            const categorySlug = link.dataset.categorySlug;
            
            if (categorySlug) {
                const isEnabled = this.preferences.isCategoryEnabled(categorySlug);
                
                if (!isEnabled) {
                    // Hide the link and its separator
                    link.style.display = 'none';
                    // Hide separator after this link if it exists
                    const nextSibling = link.nextSibling;
                    if (nextSibling && nextSibling.nodeType === 3 && nextSibling.textContent.trim() === '•') {
                        nextSibling.style.display = 'none';
                    }
                    // Also check for separator before (if it's a text node)
                    const prevSibling = link.previousSibling;
                    if (prevSibling && prevSibling.nodeType === 3 && prevSibling.textContent.trim() === '•') {
                        prevSibling.style.display = 'none';
                    }
                } else {
                    link.style.display = '';
                    // Show separators
                    const nextSibling = link.nextSibling;
                    if (nextSibling && nextSibling.nodeType === 3) {
                        nextSibling.style.display = '';
                    }
                    const prevSibling = link.previousSibling;
                    if (prevSibling && prevSibling.nodeType === 3) {
                        prevSibling.style.display = '';
                    }
                }
            }
        });

        // Clean up orphaned separators (separators with no visible links around them)
        this.cleanupSeparators();
    }

    /**
     * Filter mobile navigation menu
     */
    filterMobileNavigation() {
        const mobileNavLinks = document.querySelectorAll('#mobileNavMenu .nav-category-link');
        
        mobileNavLinks.forEach(link => {
            const categorySlug = link.dataset.categorySlug;
            
            if (categorySlug) {
                const isEnabled = this.preferences.isCategoryEnabled(categorySlug);
                
                if (!isEnabled) {
                    link.style.display = 'none';
                } else {
                    link.style.display = '';
                }
            }
        });
    }

    /**
     * Clean up orphaned separators (separators between hidden items)
     */
    cleanupSeparators() {
        // Find all navigation containers (desktop nav rows)
        const navRows = document.querySelectorAll('.hidden.lg\\:flex .flex.flex-wrap');
        
        navRows.forEach(container => {
            if (!container) return;
            
            const children = Array.from(container.childNodes);
            children.forEach((node) => {
                // Check if it's a separator (text node with • or span with •)
                if (node.nodeType === 3 && node.textContent.trim() === '•') {
                    const prevLink = this.findPreviousVisibleLink(node);
                    const nextLink = this.findNextVisibleLink(node);
                    
                    // If no visible links on either side, hide separator
                    if (!prevLink || !nextLink) {
                        node.style.display = 'none';
                    } else {
                        node.style.display = '';
                    }
                } else if (node.nodeType === 1 && node.tagName === 'SPAN' && node.textContent.trim() === '•') {
                    // Handle span separators
                    const prevLink = this.findPreviousVisibleLink(node);
                    const nextLink = this.findNextVisibleLink(node);
                    
                    if (!prevLink || !nextLink) {
                        node.style.display = 'none';
                    } else {
                        node.style.display = '';
                    }
                }
            });
        });
    }

    /**
     * Find previous visible link node
     */
    findPreviousVisibleLink(node) {
        let current = node.previousSibling;
        while (current) {
            if (current.nodeType === 1 && current.classList.contains('nav-category-link') && current.style.display !== 'none') {
                return current;
            }
            current = current.previousSibling;
        }
        return null;
    }

    /**
     * Find next visible link node
     */
    findNextVisibleLink(node) {
        let current = node.nextSibling;
        while (current) {
            if (current.nodeType === 1 && current.classList.contains('nav-category-link') && current.style.display !== 'none') {
                return current;
            }
            current = current.nextSibling;
        }
        return null;
    }

    /**
     * Check if category page should be accessible
     */
    isCategoryPageAccessible(categorySlug) {
        if (!categorySlug) return true; // Home page is always accessible
        return this.preferences.isCategoryEnabled(categorySlug);
    }
}

// Initialize navigation filter
window.NavigationFilter = new NavigationFilter();

// Attach settings button click handler
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        attachSettingsButton();
        checkCategoryPageAccess();
    });
} else {
    attachSettingsButton();
    checkCategoryPageAccess();
}

function attachSettingsButton() {
    const settingsBtn = document.getElementById('categorySettingsBtn');
    if (settingsBtn && window.CategorySettingsUI) {
        settingsBtn.addEventListener('click', () => {
            window.CategorySettingsUI.show();
        });
    }
}

/**
 * Check if current page is a category page and if it's disabled
 */
function checkCategoryPageAccess() {
    if (!window.CategoryPreferences || !window.NavigationFilter) {
        // Wait a bit and try again
        setTimeout(checkCategoryPageAccess, 100);
        return;
    }

    // Check if we're on a category page
    const pathMatch = window.location.pathname.match(/\/category\/([^\/]+)/);
    if (pathMatch) {
        const categorySlug = pathMatch[1].replace('.html', '');
        
        if (!window.CategoryPreferences.isCategoryEnabled(categorySlug)) {
            // Category is disabled, redirect to home
            const homePath = window.location.pathname.includes('/category/') ? '../../' : '../';
            alert('This category has been disabled in your settings.');
            window.location.href = homePath + 'index.html';
        }
    }
}

// Also intercept navigation clicks to category pages
document.addEventListener('click', (e) => {
    const link = e.target.closest('a[data-category-slug]');
    if (link && window.CategoryPreferences && window.NavigationFilter) {
        const categorySlug = link.dataset.categorySlug;
        if (categorySlug && !window.CategoryPreferences.isCategoryEnabled(categorySlug)) {
            e.preventDefault();
            alert('This category has been disabled in your settings.');
            return false;
        }
    }
}, true);

