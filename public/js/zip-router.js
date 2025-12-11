/**
 * Zip Code Router - Handles zip code routing and landing page
 */

class ZipRouter {
    constructor() {
        this.currentZip = null;
        this.init();
    }

    init() {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.doInit());
        } else {
            this.doInit();
        }
    }

    doInit() {
        // Get zip from URL path (e.g., /02720) or query parameter (legacy support)
        const path = window.location.pathname;
        const pathMatch = path.match(/^\/(\d{5})$/); // Match /02720 format
        const zipFromPath = pathMatch ? pathMatch[1] : null;
        
        // Also check query parameter for legacy support
        const urlParams = new URLSearchParams(window.location.search);
        const zipParam = urlParams.get('z');
        
        // Also check localStorage for persisted zip
        const storedZip = localStorage.getItem('currentZip');
        
        if (zipFromPath) {
            // Zip code in URL path: /02720 - ALWAYS use this, even if localStorage has different zip
            this.setZip(zipFromPath);
        } else if (zipParam) {
            // Legacy: zip in query parameter ?z=XXXXX - redirect to path-based
            window.location.href = `/${zipParam}`;
            return;
        } else if (storedZip && /^\d{5}$/.test(storedZip)) {
            // Only redirect to stored zip if no zip in URL and stored zip is valid
            // This allows users to bookmark or directly access different zip codes
            window.location.href = `/${storedZip}`;
            return;
        } else {
            // No zip - default to 02720 (Fall River)
            window.location.href = '/02720';
            return;
        }
    }

    setZip(zipCode) {
        if (!this.isValidZip(zipCode)) {
            console.error('Invalid zip code:', zipCode);
            this.showLandingPage();
            return;
        }
        
        this.currentZip = zipCode;
        localStorage.setItem('currentZip', zipCode);
        
        // Dispatch custom event so other components can update immediately
        window.dispatchEvent(new CustomEvent('zipChanged', { detail: { zip: zipCode } }));
        
        // Hide landing page if visible
        const landingPage = document.getElementById('landing-page');
        if (landingPage) {
            landingPage.style.display = 'none';
        }
        
        // Show main content
        const mainContent = document.getElementById('main-content');
        if (mainContent) {
            mainContent.style.display = 'block';
        }
        
        // Load existing articles from storage first, then fetch new ones
        setTimeout(async () => {
            try {
                // Try to load articles from storage first (for instant display)
                if (window.storageManager && window.articleRenderer) {
                    try {
                        const storedArticles = await window.storageManager.getArticles(zipCode);
                        if (storedArticles && storedArticles.length > 0) {
                            console.log('Loading', storedArticles.length, 'articles from storage for zip', zipCode);
                            await window.articleRenderer.renderArticles(storedArticles, zipCode);
                        }
                    } catch (err) {
                        console.error('Error loading articles from storage:', err);
                        // Continue even if storage fails
                    }
                } else {
                    console.warn('StorageManager or ArticleRenderer not available yet');
                }
                
                // Then fetch fresh news
                if (window.newsFetcher) {
                    try {
                        console.log('Fetching fresh news for zip:', zipCode);
                        const articles = await window.newsFetcher.fetchForZip(zipCode);
                        console.log('Fresh news fetched, articles:', articles.length);
                        // Articles will be rendered by news-fetcher.js after fetch
                    } catch (err) {
                        console.error('Error fetching news:', err);
                        // Show user-friendly error if needed
                    }
                } else {
                    console.warn('NewsFetcher not available yet, retrying...');
                    setTimeout(() => {
                        if (window.newsFetcher) {
                            window.newsFetcher.fetchForZip(zipCode).catch(err => {
                                console.error('Error in retry fetch:', err);
                            });
                        }
                    }, 500);
                }
            } catch (err) {
                console.error('Fatal error in setZip:', err);
            }
        }, 100);
    }

    isValidZip(zipCode) {
        return zipCode && /^\d{5}$/.test(zipCode);
    }

    showLandingPage() {
        // Hide main content
        const mainContent = document.getElementById('main-content');
        if (mainContent) {
            mainContent.style.display = 'none';
        }
        
        // Show or create landing page
        let landingPage = document.getElementById('landing-page');
        if (!landingPage) {
            landingPage = this.createLandingPage();
            document.body.insertBefore(landingPage, document.body.firstChild);
        }
        landingPage.style.display = 'flex';
    }

    createLandingPage() {
        const landing = document.createElement('div');
        landing.id = 'landing-page';
        landing.className = 'min-h-screen flex items-center justify-center px-4 bg-gray-900';
        landing.innerHTML = `
            <div class="max-w-2xl w-full text-center">
                <h1 class="text-5xl md:text-6xl font-extrabold mb-6 bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
                    Local News Portal
                </h1>
                <p class="text-xl text-gray-400 mb-8">
                    Get the latest news for your area
                </p>
                
                <form id="zipForm" onsubmit="handleZipSubmit(event)" class="mb-8">
                    <div class="flex flex-col sm:flex-row gap-4 max-w-lg mx-auto">
                        <input 
                            type="text" 
                            id="zipInput" 
                            placeholder="Enter your zip code (e.g., 02720)"
                            pattern="[0-9]{5}"
                            maxlength="5"
                            required
                            class="flex-1 px-6 py-4 bg-gray-800 border border-gray-700 rounded-xl text-gray-100 text-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                        >
                        <button 
                            type="submit"
                            class="px-8 py-4 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-xl transition-all duration-300 hover:scale-105 shadow-lg hover:shadow-xl"
                        >
                            Get News →
                        </button>
                    </div>
                    <p class="text-sm text-gray-500 mt-4">
                        Example: 02720 for Fall River, MA • 10001 for New York, NY
                    </p>
                </form>
                
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mt-12">
                    <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
                        <div class="text-4xl mb-4">📰</div>
                        <h3 class="text-lg font-semibold mb-2">Local News</h3>
                        <p class="text-gray-400 text-sm">Stay informed about what's happening in your community</p>
                    </div>
                    <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
                        <div class="text-4xl mb-4">⚡</div>
                        <h3 class="text-lg font-semibold mb-2">Real-Time Updates</h3>
                        <p class="text-gray-400 text-sm">Get the latest stories from multiple sources</p>
                    </div>
                    <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
                        <div class="text-4xl mb-4">📍</div>
                        <h3 class="text-lg font-semibold mb-2">Location-Based</h3>
                        <p class="text-gray-400 text-sm">News tailored to your zip code</p>
                    </div>
                </div>
            </div>
        `;
        return landing;
    }

    getCurrentZip() {
        // Always prioritize URL path over localStorage
        const path = window.location.pathname;
        const pathMatch = path.match(/^\/(\d{5})$/);
        if (pathMatch) {
            return pathMatch[1];
        }
        return this.currentZip || localStorage.getItem('currentZip');
    }
    
    changePinnedZip(newZip) {
        if (!this.isValidZip(newZip)) {
            console.error('Invalid zip code:', newZip);
            return false;
        }
        
        // Update localStorage
        localStorage.setItem('currentZip', newZip);
        
        // Update current zip
        this.currentZip = newZip;
        
        // Redirect to new zip
        window.location.href = `/${newZip}`;
        return true;
    }
    
    clearZip() {
        // Clear localStorage
        localStorage.removeItem('currentZip');
        
        // Clear current zip
        this.currentZip = null;
        
        // Redirect to landing page (root)
        window.location.href = '/';
    }
}

// Global handler for zip form submission
function handleZipSubmit(event) {
    event.preventDefault();
    const zipInput = document.getElementById('zipInput');
    const zipCode = zipInput.value.trim();
    
    if (zipCode.length === 5 && /^[0-9]{5}$/.test(zipCode)) {
        // Use path-based routing: /02720
        window.location.href = `/${zipCode}`;
    } else {
        alert('Please enter a valid 5-digit zip code');
        zipInput.focus();
    }
}

// Initialize router on page load
let zipRouter;
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        zipRouter = new ZipRouter();
        window.zipRouter = zipRouter;
    });
} else {
    zipRouter = new ZipRouter();
    window.zipRouter = zipRouter;
}

