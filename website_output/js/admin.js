/**
 * Client-Side Admin Panel - Fully isolated per-zip
 */

class AdminPanel {
    constructor() {
        this.currentZip = null;
        this.articles = [];
        this.currentTab = 'articles';
        this.init();
    }

    async init() {
        // Get zip from URL path (e.g., /admin/02720) or query parameter (legacy)
        const path = window.location.pathname;
        const pathMatch = path.match(/^\/admin\/(\d{5})(?:\/.*)?$/); // Match /admin/02720 or /admin/02720/articles
        let zip = pathMatch ? pathMatch[1] : null;
        
        // Fallback to query parameter for legacy support
        if (!zip) {
            const urlParams = new URLSearchParams(window.location.search);
            zip = urlParams.get('z');
        }
        
        // Fallback: Extract from DOM data attribute (server-rendered pages)
        if (!zip || !/^\d{5}$/.test(zip)) {
            const container = document.getElementById('admin-container') || document.getElementById('articles-list');
            if (container) {
                const zipFromDom = container.getAttribute('data-zip-code');
                if (zipFromDom && /^\d{5}$/.test(zipFromDom)) {
                    zip = zipFromDom;
                }
            }
        }
        
        if (!zip || !/^\d{5}$/.test(zip)) {
            // Check if this is a server-rendered page with articles (might not need zip for display)
            const container = document.getElementById('articles-list');
            const hasArticles = container && container.querySelectorAll('.article-item').length > 0;
            if (hasArticles) {
                // Server-rendered page with articles - use a default or extract from articles
                console.warn('No zip code found, but articles exist in DOM. Using server-rendered mode.');
                // Try to continue without zip for server-rendered pages
                this.currentZip = null;
                this.extractArticlesFromDOM();
                this.setupEventListeners();
                return;
            }
            // No zip code - redirect to home with message
            alert('Please choose a zip code first');
            window.location.href = '/';
            return;
        }

        this.currentZip = zip;
        
        // Check if logged in (client-side check)
        // Skip login check for server-rendered pages (they're already authenticated server-side)
        const container = document.getElementById('articles-list');
        const isServerRendered = container && container.querySelectorAll('.article-item').length > 0;
        
        if (!isServerRendered) {
            const loggedIn = sessionStorage.getItem(`admin_logged_in_${zip}`);
            if (!loggedIn) {
                this.showLogin();
                return;
            }
        }

        // CRITICAL: Verify server session is still valid by making a test API call
        try {
            const testResponse = await fetch(`/admin/api/get-rejected-articles?zip_code=${encodeURIComponent(zip)}`, {
                method: 'GET',
                credentials: 'same-origin'
            });
            
            if (testResponse.status === 401) {
                // Server session expired or not set - need to re-authenticate
                console.warn('Server session expired, showing login');
                sessionStorage.removeItem(`admin_logged_in_${zip}`);
                this.showLogin();
                return;
            }
        } catch (error) {
            console.error('Error verifying server session:', error);
            // Continue anyway - might be a network error
        }

        // Show admin panel
        this.showAdminPanel();
        
        // Check if articles are already rendered (server-rendered page)
        const container = document.getElementById('articles-list');
        const hasExistingArticles = container && container.querySelectorAll('.article-item').length > 0;
        
        if (hasExistingArticles) {
            // Server-rendered page - extract articles from DOM, don't load from IndexedDB
            this.extractArticlesFromDOM();
            this.setupEventListeners();
        } else {
            // Client-side only page - load from IndexedDB
            this.loadArticles();
            this.setupEventListeners();
        }
    }

    showLogin() {
        // Get zip from URL if available
        const urlParams = new URLSearchParams(window.location.search);
        const zipFromUrl = urlParams.get('z');
        
        const container = document.getElementById('admin-container') || document.body;
        container.innerHTML = `
            <div style="min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #1a1a1a;">
                <div style="background: #252525; padding: 2rem; border-radius: 8px; max-width: 400px; width: 100%;">
                    <h1 style="color: #0078d4; margin-bottom: 1.5rem; text-align: center;">Zip Admin Login</h1>
                    ${!zipFromUrl ? '<p style="color: #ff9800; margin-bottom: 1rem; text-align: center; font-size: 0.9rem;">⚠️ Zip code required. Please enter your zip code.</p>' : ''}
                    <form id="loginForm" onsubmit="return false;">
                        <div style="margin-bottom: 1rem;">
                            <label style="display: block; color: #b0b0b0; margin-bottom: 0.5rem;">Zip Code (Username)</label>
                            <input type="text" id="loginZip" pattern="[0-9]{5}" maxlength="5" required value="${zipFromUrl || ''}"
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                        </div>
                        <div style="margin-bottom: 1.5rem;">
                            <label style="display: block; color: #b0b0b0; margin-bottom: 0.5rem;">Password</label>
                            <input type="password" id="loginPassword" required
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                        </div>
                        <button type="submit" onclick="window.adminPanel.handleLogin()"
                            style="width: 100%; padding: 0.75rem; background: #0078d4; color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 1rem;">
                            Login
                        </button>
                        <p style="color: #888; font-size: 0.85rem; margin-top: 1rem; text-align: center;">
                            Username = zip code (e.g., 02720)<br>
                            Password = "admin"
                        </p>
                        <p style="color: #888; font-size: 0.85rem; margin-top: 0.5rem; text-align: center;">
                            <a href="/admin/main" style="color: #60a5fa;">→ Main Admin (no zip)</a>
                        </p>
                        ${!zipFromUrl ? '<p style="color: #888; font-size: 0.85rem; margin-top: 0.5rem; text-align: center;"><a href="/" style="color: #60a5fa;">← Go back to choose zip code</a></p>' : ''}
                    </form>
                </div>
            </div>
        `;
    }

    showMainAdminLogin() {
        const container = document.getElementById('admin-container') || document.body;
        container.innerHTML = `
            <div style="min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #1a1a1a;">
                <div style="background: #252525; padding: 2rem; border-radius: 8px; max-width: 400px; width: 100%;">
                    <h1 style="color: #0078d4; margin-bottom: 1.5rem; text-align: center;">Main Admin Login</h1>
                    <p style="color: #ff9800; margin-bottom: 1rem; text-align: center; font-size: 0.9rem;">⚠️ Main admin manages global settings (not zip-specific)</p>
                    <form id="loginForm" onsubmit="return false;">
                        <div style="margin-bottom: 1.5rem;">
                            <label style="display: block; color: #b0b0b0; margin-bottom: 0.5rem;">Username</label>
                            <input type="text" id="loginUsername" required value="admin"
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                        </div>
                        <div style="margin-bottom: 1.5rem;">
                            <label style="display: block; color: #b0b0b0; margin-bottom: 0.5rem;">Password</label>
                            <input type="password" id="loginPassword" required
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                        </div>
                        <button type="submit" onclick="window.adminPanel.handleMainAdminLogin()"
                            style="width: 100%; padding: 0.75rem; background: #0078d4; color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 1rem;">
                            Login
                        </button>
                        <p style="color: #888; font-size: 0.85rem; margin-top: 1rem; text-align: center;">
                            Username = "admin"<br>
                            Password = "admin"
                        </p>
                        <p style="color: #888; font-size: 0.85rem; margin-top: 0.5rem; text-align: center;">
                            <a href="/" style="color: #60a5fa;">← Go back to site</a>
                        </p>
                    </form>
                </div>
            </div>
        `;
    }

    async handleMainAdminLogin() {
        const username = document.getElementById('loginUsername').value.trim();
        const password = document.getElementById('loginPassword').value;

        if (username !== 'admin' || password !== 'admin') {
            alert('Invalid credentials. Use username="admin" and password="admin"');
            return;
        }

        // CRITICAL: Authenticate with server to get session cookie
        try {
            const formData = new FormData();
            formData.append('username', username);
            formData.append('password', password);
            
            const response = await fetch('/admin/login', {
                method: 'POST',
                body: formData,
                credentials: 'same-origin'
            });
            
            if (response.ok || response.redirected) {
                // Login successful - server session is now set
                sessionStorage.setItem('admin_logged_in_main', 'true');
                this.isMainAdmin = true;
                this.currentZip = null;
                window.location.href = '/admin/main';
            } else {
                const errorData = await response.json().catch(() => ({ error: 'Login failed' }));
                alert('Login failed: ' + (errorData.error || 'Unknown error'));
            }
        } catch (error) {
            console.error('Login error:', error);
            alert('Error during login: ' + error.message);
        }
    }

    showMainAdminPanel() {
        const container = document.getElementById('admin-container') || document.body;
        container.innerHTML = `
            <div style="background: #1a1a1a; min-height: 100vh; padding: 2rem;">
                <div style="max-width: 1400px; margin: 0 auto;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem;">
                        <h1 style="color: #0078d4; font-size: 2rem;">Main Admin Panel (Global Settings)</h1>
                        <div style="display: flex; gap: 1rem;">
                            <a href="/" style="padding: 0.5rem 1rem; background: #252525; color: #e0e0e0; text-decoration: none; border-radius: 4px;">← Back to Site</a>
                            <button onclick="window.adminPanel.logout()" style="padding: 0.5rem 1rem; background: #d32f2f; color: white; border: none; border-radius: 4px; cursor: pointer;">Logout</button>
                        </div>
                    </div>
                    <div style="background: #252525; padding: 1.5rem; border-radius: 8px;">
                        <h2 style="color: #0078d4; margin-bottom: 1rem;">Main Admin Features</h2>
                        <p style="color: #b0b0b0; margin-bottom: 1rem;">Main admin manages global settings that apply to all zip codes.</p>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; margin-top: 1.5rem;">
                            <div style="background: #1a1a1a; padding: 1rem; border-radius: 8px;">
                                <h3 style="color: #0078d4; margin-bottom: 0.5rem;">Global Settings</h3>
                                <p style="color: #888; font-size: 0.9rem;">Configure system-wide settings</p>
                            </div>
                            <div style="background: #1a1a1a; padding: 1rem; border-radius: 8px;">
                                <h3 style="color: #0078d4; margin-bottom: 0.5rem;">All Zip Codes</h3>
                                <p style="color: #888; font-size: 0.9rem;">View and manage all zip codes</p>
                            </div>
                        </div>
                        <p style="color: #888; margin-top: 1.5rem; font-size: 0.9rem;">
                            💡 Tip: For zip-specific management, go to <a href="/admin/02720" style="color: #60a5fa;">/admin/02720</a> (replace 02720 with your zip code)
                        </p>
                    </div>
                </div>
            </div>
        `;
    }

    async handleLogin() {
        const zip = document.getElementById('loginZip').value.trim();
        const password = document.getElementById('loginPassword').value;

        if (!/^\d{5}$/.test(zip)) {
            alert('Please enter a valid 5-digit zip code');
            return;
        }

        if (password !== 'admin') {
            alert('Invalid password. Use "admin" as password.');
            return;
        }

        // CRITICAL: Authenticate with server to get session cookie
        try {
            const formData = new FormData();
            formData.append('username', zip);
            formData.append('password', password);
            
            const response = await fetch('/admin/login', {
                method: 'POST',
                body: formData,
                credentials: 'same-origin'
            });
            
            if (response.ok || response.redirected) {
                // Login successful - server session is now set
                // Store login state in sessionStorage for client-side checks
                sessionStorage.setItem(`admin_logged_in_${zip}`, 'true');
                this.currentZip = zip;
                
                // Redirect to admin with zip
                window.location.href = `/admin/${zip}`;
            } else {
                const errorData = await response.json().catch(() => ({ error: 'Login failed' }));
                alert('Login failed: ' + (errorData.error || 'Unknown error'));
            }
        } catch (error) {
            console.error('Login error:', error);
            alert('Error during login: ' + error.message);
        }
    }

    showAdminPanel() {
        const container = document.getElementById('admin-container') || document.body;
        container.innerHTML = `
            <div style="background: #1a1a1a; min-height: 100vh; padding: 2rem;">
                <div style="max-width: 1400px; margin: 0 auto;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem;">
                        <h1 style="color: #0078d4; font-size: 2rem;">Admin Panel - Zip ${this.currentZip}</h1>
                        <div style="display: flex; gap: 1rem;">
                            <a href="/${this.currentZip}" style="padding: 0.5rem 1rem; background: #252525; color: #e0e0e0; text-decoration: none; border-radius: 4px;">← Back to Site</a>
                            <button onclick="window.adminPanel.logout()" style="padding: 0.5rem 1rem; background: #d32f2f; color: white; border: none; border-radius: 4px; cursor: pointer;">Logout</button>
                        </div>
                    </div>

                    <!-- Stats Dashboard -->
                    <div id="stats-dashboard" style="background: #252525; padding: 1.5rem; border-radius: 8px; margin-bottom: 2rem;">
                        <h2 style="color: #0078d4; margin-bottom: 1rem;">Statistics</h2>
                        <div id="stats-content" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                            <!-- Stats will be loaded here -->
                        </div>
                    </div>

                    <!-- Tabs -->
                    <div class="tabs" style="display: flex; gap: 0.5rem; margin-bottom: 1.5rem; border-bottom: 2px solid #404040; flex-wrap: wrap;">
                        <button class="tab-btn active" data-tab="articles" onclick="window.adminPanel.switchTab('articles')" style="padding: 0.75rem 1.5rem; background: transparent; border: none; color: #0078d4; cursor: pointer; font-size: 1rem; font-weight: 600; border-bottom: 2px solid #0078d4; margin-bottom: -2px;">📰 Articles</button>
                        <button class="tab-btn" data-tab="trash" onclick="window.adminPanel.switchTab('trash')" style="padding: 0.75rem 1.5rem; background: transparent; border: none; color: #b0b0b0; cursor: pointer; font-size: 1rem; font-weight: 600; border-bottom: 2px solid transparent; margin-bottom: -2px;">🗑️ Trash</button>
                        <button class="tab-btn" data-tab="auto-filtered" onclick="window.adminPanel.switchTab('auto-filtered')" style="padding: 0.75rem 1.5rem; background: transparent; border: none; color: #b0b0b0; cursor: pointer; font-size: 1rem; font-weight: 600; border-bottom: 2px solid transparent; margin-bottom: -2px;">🤖 Auto-Filtered</button>
                        <button class="tab-btn" data-tab="sources" onclick="window.adminPanel.switchTab('sources')" style="padding: 0.75rem 1.5rem; background: transparent; border: none; color: #b0b0b0; cursor: pointer; font-size: 1rem; font-weight: 600; border-bottom: 2px solid transparent; margin-bottom: -2px;">📡 Sources</button>
                        <button class="tab-btn" data-tab="stats" onclick="window.adminPanel.switchTab('stats')" style="padding: 0.75rem 1.5rem; background: transparent; border: none; color: #b0b0b0; cursor: pointer; font-size: 1rem; font-weight: 600; border-bottom: 2px solid transparent; margin-bottom: -2px;">📊 Stats</button>
                        <button class="tab-btn" data-tab="settings" onclick="window.adminPanel.switchTab('settings')" style="padding: 0.75rem 1.5rem; background: transparent; border: none; color: #b0b0b0; cursor: pointer; font-size: 1rem; font-weight: 600; border-bottom: 2px solid transparent; margin-bottom: -2px;">⚙️ Settings</button>
                        <button class="tab-btn" data-tab="relevance" onclick="window.adminPanel.switchTab('relevance')" style="padding: 0.75rem 1.5rem; background: transparent; border: none; color: #b0b0b0; cursor: pointer; font-size: 1rem; font-weight: 600; border-bottom: 2px solid transparent; margin-bottom: -2px;">🎯 Relevance</button>
                    </div>

                    <!-- Articles Tab -->
                    <div id="articles-tab" class="tab-content">
                        <div style="background: #252525; border-radius: 8px; overflow: hidden;">
                            <div id="articles-list">
                                <!-- Articles will be loaded here -->
                            </div>
                        </div>
                    </div>

                    <!-- Trash Tab -->
                    <div id="trash-tab" class="tab-content" style="display: none;">
                        <div style="background: #252525; border-radius: 8px; padding: 1.5rem;">
                            <div id="trash-list">
                                <!-- Trashed articles will be loaded here -->
                            </div>
                        </div>
                    </div>

                    <!-- Auto-Filtered Tab -->
                    <div id="auto-filtered-tab" class="tab-content" style="display: none;">
                        <div style="background: #252525; border-radius: 8px; padding: 1.5rem;">
                            <div id="auto-filtered-list">
                                <!-- Auto-filtered articles will be loaded here -->
                            </div>
                        </div>
                    </div>

                    <!-- Sources Tab -->
                    <div id="sources-tab" class="tab-content" style="display: none;">
                        <div style="background: #252525; border-radius: 8px; padding: 1.5rem;">
                            <div id="sources-list">
                                <!-- Sources will be loaded here -->
                            </div>
                        </div>
                    </div>

                    <!-- Stats Tab -->
                    <div id="stats-tab" class="tab-content" style="display: none;">
                        <div id="detailed-stats" style="background: #252525; border-radius: 8px; padding: 1.5rem;">
                            <!-- Detailed stats will be loaded here -->
                        </div>
                    </div>

                    <!-- Settings Tab -->
                    <div id="settings-tab" class="tab-content" style="display: none;">
                        <div style="background: #252525; border-radius: 8px; padding: 1.5rem;">
                            <div id="settings-content">
                                <!-- Settings will be loaded here -->
                            </div>
                        </div>
                    </div>

                    <!-- Relevance Tab -->
                    <div id="relevance-tab" class="tab-content" style="display: none;">
                        <div style="background: #252525; border-radius: 8px; padding: 1.5rem;">
                            <div id="relevance-content">
                                <!-- Relevance config will be loaded here -->
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    async loadArticles() {
        // CRITICAL: Ensure we have a zip code
        if (!this.currentZip || !/^\d{5}$/.test(this.currentZip)) {
            console.error('No valid zip code - cannot load articles');
            // Don't redirect if we're on a server-rendered page
            const container = document.getElementById('articles-list');
            if (container && container.children.length > 0) {
                // Articles already rendered by server, just extract them
                this.extractArticlesFromDOM();
                return;
            }
            alert('Invalid zip code. Redirecting...');
            window.location.href = 'index.html';
            return;
        }

        // Check if articles are already rendered in the DOM (server-rendered)
        const container = document.getElementById('articles-list');
        if (container && container.querySelectorAll('.article-item').length > 0) {
            // Articles already rendered by server - extract them from DOM
            this.extractArticlesFromDOM();
            return;
        }

        // Otherwise, load from IndexedDB if storageManager is available
        if (!window.storageManager) {
            console.warn('Storage manager not available, but articles may be server-rendered');
            // Try to extract from DOM anyway
            this.extractArticlesFromDOM();
            return;
        }

        // Load articles from IndexedDB - ONLY for this zip
        this.articles = await window.storageManager.getArticles(this.currentZip);
        
        // Sort by published date (newest first)
        this.articles.sort((a, b) => {
            const dateA = new Date(a.published || 0);
            const dateB = new Date(b.published || 0);
            return dateB - dateA;
        });

        this.renderArticles();
        this.updateStats();
    }

    extractArticlesFromDOM() {
        // Extract articles from server-rendered HTML
        const container = document.getElementById('articles-list');
        if (!container) return;

        // Try to get zip code from container data attribute
        if (!this.currentZip) {
            const zipFromContainer = container.getAttribute('data-zip-code');
            if (zipFromContainer && /^\d{5}$/.test(zipFromContainer)) {
                this.currentZip = zipFromContainer;
            } else {
                // Try admin-container
                const adminContainer = document.getElementById('admin-container');
                if (adminContainer) {
                    const zipFromAdmin = adminContainer.getAttribute('data-zip-code');
                    if (zipFromAdmin && /^\d{5}$/.test(zipFromAdmin)) {
                        this.currentZip = zipFromAdmin;
                    }
                }
            }
        }

        const articleItems = container.querySelectorAll('.article-item');
        if (articleItems.length === 0) {
            // No articles in DOM, try to keep existing content
            return;
        }

        // Extract article data from DOM elements
        this.articles = Array.from(articleItems).map(item => {
            const articleId = item.getAttribute('data-id') || item.getAttribute('data-article-id');
            const titleEl = item.querySelector('.article-title a, .article-title span');
            const metaEl = item.querySelector('.article-meta');
            const urlEl = item.querySelector('.article-title a');
            
            // Try to extract data from data attributes or DOM
            const title = titleEl ? titleEl.textContent.trim() : 'Untitled';
            const url = urlEl ? urlEl.href : '#';
            
            // Parse meta information
            let source = 'Unknown';
            let published = null;
            let category = null;
            let relevanceScore = null;
            let localScore = null;
            
            if (metaEl) {
                const metaText = metaEl.textContent;
                // Parse: "Source - YYYY-MM-DD • Category • Relevance: XX • Local: XX%"
                const parts = metaText.split('•');
                if (parts.length > 0) {
                    const firstPart = parts[0].trim();
                    const dashIndex = firstPart.indexOf(' - ');
                    if (dashIndex > 0) {
                        source = firstPart.substring(0, dashIndex).trim();
                        published = firstPart.substring(dashIndex + 3).trim();
                    } else {
                        source = firstPart;
                    }
                }
                if (parts.length > 1) {
                    category = parts[1].trim();
                }
                // Extract relevance score
                const relevanceMatch = metaText.match(/Relevance:\s*(\d+)/);
                if (relevanceMatch) {
                    relevanceScore = parseFloat(relevanceMatch[1]);
                }
                // Extract local score
                const localMatch = metaText.match(/Local:\s*(\d+)%/);
                if (localMatch) {
                    localScore = parseFloat(localMatch[1]);
                }
            }
            
            return {
                id: articleId,
                title: title,
                url: url,
                source: source,
                source_display: source,
                published: published,
                category: category,
                relevance_score: relevanceScore,
                local_score: localScore
            };
        });

        // Don't re-render, just update stats and setup event listeners
        this.updateStats();
        console.log(`Extracted ${this.articles.length} articles from server-rendered DOM`);
    }

    renderArticles() {
        const container = document.getElementById('articles-list');
        if (!container) return;

        // If articles are already rendered in DOM (server-rendered), don't clear them
        const existingArticles = container.querySelectorAll('.article-item');
        if (existingArticles.length > 0 && this.articles.length === 0) {
            // Articles exist in DOM but not in this.articles - extract them
            this.extractArticlesFromDOM();
            // Don't re-render, just update stats
            this.updateStats();
            return;
        }

        // CRITICAL: Ensure we have a zip code
        if (!this.currentZip) {
            // Check if we can extract zip from existing articles
            if (existingArticles.length > 0) {
                this.extractArticlesFromDOM();
                this.updateStats();
                return;
            }
            container.innerHTML = '<div style="padding: 2rem; text-align: center; color: #d32f2f;">Error: No zip code specified. Please reload with ?z=XXXXX</div>';
            return;
        }

        if (this.articles.length === 0) {
            // Only show "no articles" if we're sure there aren't any in the DOM
            if (existingArticles.length === 0) {
                container.innerHTML = '<div style="padding: 2rem; text-align: center; color: #888;">No articles found. Articles will appear here after news is fetched.</div>';
            }
            return;
        }

        // CRITICAL: Always use currentZip - never use any other zip
        const trashed = window.storageManager.getTrashed(this.currentZip);
        const disabled = window.storageManager.getDisabled(this.currentZip);
        const goodFit = window.storageManager.getGoodFitArticles(this.currentZip);
        const topStories = window.storageManager.getTopStories(this.currentZip);

        // Escape functions for safe HTML/JS rendering
        const escapeHtml = (str) => {
            if (!str) return '';
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        };
        
        const escapeJs = (str) => {
            if (!str) return '';
            return String(str)
                .replace(/\\/g, '\\\\')
                .replace(/'/g, "\\'")
                .replace(/"/g, '\\"')
                .replace(/\//g, '\\/')
                .replace(/\n/g, '\\n')
                .replace(/\r/g, '\\r')
                .replace(/\t/g, '\\t');
        };

        container.innerHTML = this.articles.map(article => {
            const articleId = escapeJs(article.id?.toString() || '');
            const isTrashed = trashed.includes(article.id?.toString());
            const isDisabled = disabled.includes(article.id?.toString());
            const isGoodFit = goodFit.includes(article.id?.toString());
            const isTopStory = topStories.includes(article.id?.toString());
            const formattedDate = escapeHtml(this.formatFullDate(article.published));
            const articleTitle = escapeHtml(article.title || 'Untitled');
            const articleUrl = escapeHtml(article.url || '#');
            const articleSource = escapeHtml(article.source_display || article.source || 'Unknown');
            const articleCategory = escapeHtml(article.category || '');
            
            // Get relevance and local scores
            const relevanceScore = article.relevance_score !== null && article.relevance_score !== undefined ? parseFloat(article.relevance_score) : null;
            const localScore = article.local_score !== null && article.local_score !== undefined ? parseFloat(article.local_score) : null;
            
            // Format relevance score display
            const relevanceDisplay = relevanceScore !== null ? `Relevance: ${Math.round(relevanceScore)}` : 'Relevance: N/A';
            
            // Format local score with meter
            let localDisplay = 'Local: N/A';
            let localMeterHtml = '';
            if (localScore !== null) {
                const localPercent = Math.round(localScore);
                let meterColor = '#d32f2f'; // red
                if (localPercent > 60) meterColor = '#4caf50'; // green
                else if (localPercent > 30) meterColor = '#ff9800'; // yellow/orange
                
                localDisplay = `Local: ${localPercent}%`;
                localMeterHtml = `
                    <span style="display: inline-block; width: 60px; height: 8px; background: #404040; border-radius: 4px; margin-left: 0.5rem; vertical-align: middle; overflow: hidden;">
                        <span style="display: block; width: ${localPercent}%; height: 100%; background: ${meterColor}; transition: width 0.3s;"></span>
                    </span>
                `;
            }

            if (isTrashed) return ''; // Don't show trashed articles in main list

            return `
                <div class="article-item" data-article-id="${articleId}" style="display: flex; align-items: center; padding: 1rem; border-bottom: 1px solid #404040; gap: 1rem; ${isDisabled ? 'opacity: 0.5;' : ''}">
                    <div style="flex: 1;">
                        <div class="article-title" style="font-weight: 600; margin-bottom: 0.25rem; color: #e0e0e0;">
                            <a href="${articleUrl}" target="_blank" style="color: #0078d4; text-decoration: none;">${articleTitle}</a>
                        </div>
                        <div class="article-meta" style="font-size: 0.85rem; color: #888;">
                            ${articleSource} • ${formattedDate}${articleCategory ? ` • ${articleCategory}` : ''} • ${relevanceDisplay} • ${localDisplay}${localMeterHtml}
                        </div>
                    </div>
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <button class="top-story-btn" data-id="${articleId}"
                            style="padding: 0.5rem; background: ${isTopStory ? '#ff9800' : '#252525'}; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1.2rem;" 
                            title="Mark as top story">
                            🎩
                        </button>
                        <button class="good-fit-btn" data-id="${articleId}"
                            style="padding: 0.5rem; background: ${isGoodFit ? '#4caf50' : '#252525'}; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1.2rem;" 
                            title="Mark as good fit">
                            👍
                        </button>
                        <button class="edit-article-btn" data-id="${articleId}"
                            style="padding: 0.5rem; background: #252525; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1.2rem;" 
                            title="Edit article">
                            ✏️
                        </button>
                        <button class="trash-btn" data-id="${articleId}"
                            style="padding: 0.5rem; background: #d32f2f; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1.2rem;" 
                            title="Delete">
                            👎
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    }

    toggleArticle(articleId, enabled) {
        if (!window.storageManager || !this.currentZip) return;
        // CRITICAL: Always use currentZip - never use any other zip
        window.storageManager.setDisabled(this.currentZip, articleId, !enabled);
        this.renderArticles();
        this.updateStats();
    }

    toggleGoodFit(articleId) {
        if (!this.currentZip) {
            // Server-rendered page - use API
            this.toggleGoodFitViaAPI(articleId);
            return;
        }
        if (!window.storageManager) return;
        // CRITICAL: Always use currentZip - never use any other zip
        const goodFit = window.storageManager.getGoodFitArticles(this.currentZip);
        if (goodFit.includes(articleId)) {
            window.storageManager.removeGoodFit(this.currentZip, articleId);
        } else {
            window.storageManager.addGoodFit(this.currentZip, articleId);
            // Update Bayesian from this article
            this.updateBayesianFromArticle(articleId);
        }
        this.renderArticles();
    }

    async toggleGoodFitViaAPI(articleId) {
        // Good fit might not have a dedicated API endpoint
        // For now, just toggle the visual state and reload
        // The server-rendered page will handle persistence
        try {
            // Try to use a generic toggle or just reload to let server handle it
            // Since there's no dedicated endpoint, we'll just update the UI and let the page reload
            location.reload();
        } catch (error) {
            console.error('Error toggling good fit:', error);
            alert('Error: ' + error.message);
        }
    }

    trashArticle(articleId) {
        if (!confirm('Are you sure you want to trash this article?')) return;
        
        if (!this.currentZip) {
            // Server-rendered page - use API
            this.trashArticleViaAPI(articleId);
            return;
        }
        if (!window.storageManager) return;
        // CRITICAL: Always use currentZip - never use any other zip
        window.storageManager.addTrashed(this.currentZip, articleId);
        this.renderArticles();
        this.updateStats();
    }

    async trashArticleViaAPI(articleId) {
        try {
            const response = await fetch('/admin/api/reject-article', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({article_id: articleId, rejected: true})
            });
            if (response.ok) {
                location.reload();
            } else {
                alert('Error trashing article');
            }
        } catch (error) {
            console.error('Error trashing article:', error);
            alert('Error: ' + error.message);
        }
    }

    toggleTopStory(articleId) {
        if (!this.currentZip) {
            // Server-rendered page - use API
            this.toggleTopStoryViaAPI(articleId);
            return;
        }
        if (!window.storageManager) return;
        // CRITICAL: Always use currentZip - never use any other zip
        const topStories = window.storageManager.getTopStories(this.currentZip);
        if (topStories.includes(articleId)) {
            window.storageManager.removeTopStory(this.currentZip, articleId);
        } else {
            window.storageManager.addTopStory(this.currentZip, articleId);
        }
        this.renderArticles();
        this.updateStats();
    }

    async toggleTopStoryViaAPI(articleId) {
        // Get current state from button
        const button = document.querySelector(`.top-story-btn[data-id="${articleId}"]`);
        const isCurrentlyTop = button && button.style.background.includes('#ff9800');
        const newState = !isCurrentlyTop;
        
        try {
            const response = await fetch('/admin/api/top-story', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({id: articleId, is_top_story: newState})
            });
            const result = await response.json();
            if (result.success) {
                location.reload();
            } else {
                alert('Error toggling top story: ' + (result.error || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error toggling top story:', error);
            alert('Error: ' + error.message);
        }
    }

    updateBayesianFromArticle(articleId) {
        if (!this.currentZip) return;
        const article = this.articles.find(a => a.id?.toString() === articleId);
        if (!article) return;

        // CRITICAL: Always use currentZip - never use any other zip
        const bayesian = window.storageManager.getBayesianData(this.currentZip);
        const text = `${article.title} ${article.summary}`.toLowerCase();
        
        // Extract keywords (simple word extraction)
        const words = text.match(/\b[a-z]{4,}\b/g) || [];
        words.forEach(word => {
            if (!bayesian.keywords[word]) {
                bayesian.keywords[word] = { good: 0, bad: 0 };
            }
            bayesian.keywords[word].good++;
        });
        
        bayesian.totalGood++;
        // CRITICAL: Always use currentZip - never use any other zip
        window.storageManager.setBayesianData(this.currentZip, bayesian);
    }

    formatFullDate(dateString) {
        if (!dateString) return 'No date';
        try {
            const date = new Date(dateString);
            return date.toLocaleDateString('en-US', { 
                month: 'short', 
                day: '2-digit', 
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            }).replace(',', ' –');
        } catch (error) {
            return 'Invalid date';
        }
    }

    updateStats() {
        if (!window.statsManager || !this.currentZip) return;
        // CRITICAL: Always use currentZip - never use any other zip
        window.statsManager.updateStats(this.currentZip, this.articles);
    }

    switchTab(tab) {
        this.currentTab = tab;
        
        // Update tab buttons
        document.querySelectorAll('.tab-btn').forEach(btn => {
            if (btn.dataset.tab === tab) {
                btn.classList.add('active');
                btn.style.color = '#0078d4';
                btn.style.borderBottomColor = '#0078d4';
            } else {
                btn.classList.remove('active');
                btn.style.color = '#b0b0b0';
                btn.style.borderBottomColor = 'transparent';
            }
        });

        // Hide all tabs
        const allTabs = ['articles', 'trash', 'auto-filtered', 'sources', 'stats', 'settings', 'relevance'];
        allTabs.forEach(t => {
            const tabEl = document.getElementById(`${t}-tab`);
            if (tabEl) tabEl.style.display = 'none';
        });

        // Show selected tab
        const selectedTab = document.getElementById(`${tab}-tab`);
        if (selectedTab) {
            selectedTab.style.display = 'block';
        }

        // Load tab content
        if (tab === 'articles') {
            this.renderArticles();
        } else if (tab === 'trash') {
            this.renderTrash();
        } else if (tab === 'auto-filtered') {
            this.renderAutoFiltered();
        } else if (tab === 'sources') {
            this.renderSources();
        } else if (tab === 'stats') {
            this.updateStats();
        } else if (tab === 'settings') {
            this.renderSettings();
        } else if (tab === 'relevance') {
            this.renderRelevance();
        }
    }

    async renderTrash() {
        console.log('renderTrash called, currentZip:', this.currentZip);
        
        if (!this.currentZip) {
            console.error('renderTrash: No currentZip set');
            return;
        }
        
        let container = document.getElementById('trash-list');
        if (!container) {
            console.error('renderTrash: trash-list container not found');
            // Try to find the trash tab and create container if needed
            const trashTab = document.getElementById('trash-tab');
            if (trashTab) {
                console.log('Found trash-tab, creating trash-list container');
                const newContainer = document.createElement('div');
                newContainer.id = 'trash-list';
                trashTab.appendChild(newContainer);
                container = newContainer;
            } else {
                console.error('renderTrash: trash-tab not found either');
                return;
            }
        }

        // Show loading state
        container.innerHTML = '<p style="color: #888; text-align: center; padding: 2rem;">Loading trashed articles...</p>';

        try {
            const url = `/admin/api/get-rejected-articles?zip_code=${encodeURIComponent(this.currentZip)}`;
            console.log('renderTrash: Fetching from:', url);
            
            // CRITICAL: Pass zip_code as query parameter - endpoint requires it
            const response = await fetch(url, {
                credentials: 'same-origin'
            });
            
            console.log('renderTrash: Response status:', response.status, response.statusText);
            
            let data;
            if (!response.ok) {
                // Try to read error response body for better error messages
                let errorText = `HTTP error! status: ${response.status}`;
                try {
                    const text = await response.text();
                    console.error('Error response body:', text);
                    if (text) {
                        errorText += ` - ${text.substring(0, 200)}`;
                    }
                } catch (e) {
                    console.error('Error reading error response body:', e);
                }
                throw new Error(errorText);
            }
            
            try {
                data = await response.json();
                console.log('renderTrash: Received data:', data);
            } catch (jsonError) {
                console.error('Error parsing JSON response:', jsonError);
                throw new Error(`Invalid JSON response: ${jsonError.message}`);
            }

            if (!data.success) {
                console.error('renderTrash: API returned success=false:', data);
                container.innerHTML = `<p style="color: #d32f2f; text-align: center; padding: 2rem;">Error loading trash: ${data.message || data.error || 'Unknown error'}</p>`;
                return;
            }

            const trashedArticles = data.articles || [];
            console.log('renderTrash: Found', trashedArticles.length, 'trashed articles');

            if (trashedArticles.length === 0) {
                container.innerHTML = '<p style="color: #888; text-align: center; padding: 2rem;">No trashed articles.</p>';
                return;
            }

            // Escape HTML to prevent XSS
            const escapeHtml = (str) => {
                if (!str) return '';
                const div = document.createElement('div');
                div.textContent = str;
                return div.innerHTML;
            };

            // Escape JavaScript string for use in onclick handlers
            // Escape all special characters that could break JavaScript strings or be interpreted as regex
            const escapeJs = (str) => {
                if (!str) return '';
                return String(str)
                    .replace(/\\/g, '\\\\')  // Escape backslashes first
                    .replace(/'/g, "\\'")    // Escape single quotes
                    .replace(/"/g, '\\"')    // Escape double quotes
                    .replace(/\//g, '\\/')   // Escape forward slashes (regex delimiter)
                    .replace(/\n/g, '\\n')   // Escape newlines
                    .replace(/\r/g, '\\r')   // Escape carriage returns
                    .replace(/\t/g, '\\t');  // Escape tabs
            };

            container.innerHTML = trashedArticles.map(article => {
                const articleId = (article.id || article.article_id)?.toString() || '';
                const articleTitle = escapeHtml(article.title || 'Untitled');
                const articleUrl = escapeHtml(article.url || '#');
                const source = escapeHtml(article.source_display || article.source || 'Unknown');
                const formattedDate = escapeHtml(this.formatFullDate(article.published || article.created_at));
                
                return `
                    <div style="display: flex; align-items: center; padding: 1rem; border-bottom: 1px solid #404040; gap: 1rem;">
                        <div style="flex: 1;">
                            <div style="font-weight: 600; margin-bottom: 0.25rem; color: #e0e0e0;">
                                <a href="${articleUrl}" target="_blank" style="color: #0078d4; text-decoration: none;">${articleTitle}</a>
                            </div>
                            <div style="font-size: 0.85rem; color: #888;">
                                ${source} • ${formattedDate}
                            </div>
                        </div>
                        <button class="restore-trash-btn" data-id="${escapeHtml(articleId)}" 
                            style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">
                            Restore
                        </button>
                        <button class="delete-trash-btn" data-id="${escapeHtml(articleId)}" 
                            style="padding: 0.5rem 1rem; background: #d32f2f; color: white; border: none; border-radius: 4px; cursor: pointer;">
                            Delete
                        </button>
                    </div>
                `;
            }).join('');
            
            // Set up event listeners using event delegation (better for dynamic content)
            // Use event delegation on the container instead of individual buttons
            container.addEventListener('click', (e) => {
                // Check if clicked element or its parent is a restore button
                const restoreBtn = e.target.closest('.restore-trash-btn');
                if (restoreBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    const articleId = restoreBtn.getAttribute('data-id') || restoreBtn.dataset.id;
                    if (articleId) {
                        console.log('Restore button clicked, articleId:', articleId);
                        this.restoreArticle(articleId);
                    } else {
                        console.error('No data-id found on restore button');
                    }
                    return;
                }
                
                // Check if clicked element or its parent is a delete button
                const deleteBtn = e.target.closest('.delete-trash-btn');
                if (deleteBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    const articleId = deleteBtn.getAttribute('data-id') || deleteBtn.dataset.id;
                    if (articleId) {
                        console.log('Delete button clicked, articleId:', articleId);
                        this.deleteArticlePermanently(articleId);
                    } else {
                        console.error('No data-id found on delete button');
                    }
                    return;
                }
            });
        } catch (error) {
            console.error('Error loading trash:', error);
            console.error('Error stack:', error.stack);
            if (container) {
                container.innerHTML = `<p style="color: #d32f2f; text-align: center; padding: 2rem;">Error loading trash: ${error.message}</p>`;
            }
        }
    }

    async renderAutoFiltered() {
        if (!this.currentZip) return;
        
        const container = document.getElementById('auto-filtered-list');
        if (!container) return;

        // Show loading state
        container.innerHTML = '<p style="color: #888; text-align: center; padding: 2rem;">Loading auto-filtered articles...</p>';

        try {
            // CRITICAL: Pass zip_code as query parameter - endpoint requires it
            const response = await fetch(`/admin/api/get-auto-filtered?zip_code=${encodeURIComponent(this.currentZip)}`, {
                credentials: 'same-origin'
            });
            
            let data;
            if (!response.ok) {
                // Try to read error response body for better error messages
                let errorText = `HTTP error! status: ${response.status}`;
                try {
                    const text = await response.text();
                    console.error('Error response body:', text);
                    if (text) {
                        errorText += ` - ${text.substring(0, 200)}`;
                    }
                } catch (e) {
                    // Ignore if we can't read the body
                }
                throw new Error(errorText);
            }
            
            try {
                data = await response.json();
            } catch (jsonError) {
                console.error('Error parsing JSON response:', jsonError);
                throw new Error(`Invalid JSON response: ${jsonError.message}`);
            }

            if (!data.success) {
                container.innerHTML = `<p style="color: #d32f2f; text-align: center; padding: 2rem;">Error loading auto-filtered: ${data.message || 'Unknown error'}</p>`;
                return;
            }

            const autoFilteredArticles = data.articles || [];

            if (autoFilteredArticles.length === 0) {
                container.innerHTML = '<p style="color: #888; text-align: center; padding: 2rem;">No auto-filtered articles.</p>';
                return;
            }

            // Escape HTML to prevent XSS
            const escapeHtml = (str) => {
                if (!str) return '';
                const div = document.createElement('div');
                div.textContent = str;
                return div.innerHTML;
            };

            // Escape JavaScript string for use in onclick handlers
            // Escape all special characters that could break JavaScript strings or be interpreted as regex
            const escapeJs = (str) => {
                if (!str) return '';
                return String(str)
                    .replace(/\\/g, '\\\\')  // Escape backslashes first
                    .replace(/'/g, "\\'")    // Escape single quotes
                    .replace(/"/g, '\\"')    // Escape double quotes
                    .replace(/\//g, '\\/')   // Escape forward slashes (regex delimiter)
                    .replace(/\n/g, '\\n')   // Escape newlines
                    .replace(/\r/g, '\\r')   // Escape carriage returns
                    .replace(/\t/g, '\\t');  // Escape tabs
            };

            container.innerHTML = autoFilteredArticles.map(article => {
                const articleId = (article.id || article.article_id)?.toString() || '';
                const articleTitle = escapeHtml(article.title || 'Untitled');
                const articleUrl = escapeHtml(article.url || '#');
                const source = escapeHtml(article.source_display || article.source || 'Unknown');
                const formattedDate = escapeHtml(this.formatFullDate(article.published || article.created_at));
                const reason = escapeHtml(article.reason || article.filter_reason || 'Auto-filtered');
                
                return `
                    <div style="display: flex; align-items: center; padding: 1rem; border-bottom: 1px solid #404040; gap: 1rem;">
                        <div style="flex: 1;">
                            <div style="font-weight: 600; margin-bottom: 0.25rem; color: #e0e0e0;">
                                <a href="${articleUrl}" target="_blank" style="color: #0078d4; text-decoration: none;">${articleTitle}</a>
                            </div>
                            <div style="font-size: 0.85rem; color: #888;">
                                ${source} • ${formattedDate}
                            </div>
                            <div style="font-size: 0.8rem; color: #ff9800; margin-top: 0.25rem;">
                                Reason: ${reason}
                            </div>
                        </div>
                        <button class="restore-auto-filtered-btn" data-article-id="${escapeHtml(articleId)}" 
                            style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">
                            Restore
                        </button>
                    </div>
                `;
            }).join('');
            
            // Set up event listeners using event delegation (better for dynamic content)
            container.addEventListener('click', (e) => {
                // Check if clicked element or its parent is a restore button
                const restoreBtn = e.target.closest('.restore-auto-filtered-btn');
                if (restoreBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    const articleId = restoreBtn.getAttribute('data-article-id');
                    if (articleId) {
                        this.restoreAutoFiltered(articleId);
                    }
                }
            });
        } catch (error) {
            console.error('Error loading auto-filtered:', error);
            container.innerHTML = `<p style="color: #d32f2f; text-align: center; padding: 2rem;">Error loading auto-filtered: ${error.message}</p>`;
        }
    }

    async renderSources() {
        if (!this.currentZip) return;
        
        const container = document.getElementById('sources-list');
        if (!container) return;
        
        // Show loading state
        container.innerHTML = '<p style="color: #888; text-align: center; padding: 2rem;">Loading sources...</p>';
        
        try {
            // Fetch sources from API - zip_code is already in URL, good!
            const response = await fetch(`/admin/api/get-sources?zip_code=${encodeURIComponent(this.currentZip)}`, {
                credentials: 'same-origin'
            });
            
            let data;
            if (!response.ok) {
                // Try to read error response body for better error messages
                let errorText = `HTTP error! status: ${response.status}`;
                try {
                    const text = await response.text();
                    console.error('Error response body:', text);
                    if (text) {
                        errorText += ` - ${text.substring(0, 200)}`;
                    }
                } catch (e) {
                    // Ignore if we can't read the body
                }
                throw new Error(errorText);
            }
            
            try {
                data = await response.json();
            } catch (jsonError) {
                console.error('Error parsing JSON response:', jsonError);
                throw new Error(`Invalid JSON response: ${jsonError.message}`);
            }
            
            if (!data.success) {
                container.innerHTML = `<p style="color: #d32f2f; text-align: center; padding: 2rem;">Error loading sources: ${data.message || 'Unknown error'}</p>`;
                return;
            }
            
            const sources = data.sources || [];
            
            if (sources.length === 0) {
                container.innerHTML = `
                    <div style="padding: 2rem; text-align: center; background: #252525; border-radius: 8px; margin-bottom: 1rem; border: 1px solid #404040;">
                        <p style="color: #666; margin-bottom: 1rem;">No sources configured for this zip code.</p>
                        <button onclick="window.adminPanel.addNewSource()" style="padding: 0.75rem 1.5rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">
                            + Add Source
                        </button>
                    </div>
                `;
                return;
            }
            
            // Escape HTML to prevent XSS and fix regex issues
            const escapeHtml = (str) => {
                if (!str) return '';
                const div = document.createElement('div');
                div.textContent = str;
                return div.innerHTML;
            };
            
            // Escape JavaScript string for use in onclick handlers
            // Escape all special characters that could break JavaScript strings or be interpreted as regex
            const escapeJs = (str) => {
                if (!str) return '';
                return String(str)
                    .replace(/\\/g, '\\\\')  // Escape backslashes first
                    .replace(/'/g, "\\'")    // Escape single quotes
                    .replace(/"/g, '\\"')    // Escape double quotes
                    .replace(/\//g, '\\/')   // Escape forward slashes (regex delimiter)
                    .replace(/\n/g, '\\n')   // Escape newlines
                    .replace(/\r/g, '\\r')   // Escape carriage returns
                    .replace(/\t/g, '\\t');  // Escape tabs
            };
            
            container.innerHTML = sources.map(source => {
                const sourceKey = escapeJs(source.key || '');
                const sourceName = escapeHtml(source.name || 'Unknown');
                const sourceUrl = escapeHtml(source.url || '');
                const category = escapeHtml(source.category || 'news');
                const relevanceScore = source.relevance_score !== null && source.relevance_score !== undefined ? source.relevance_score : -1;
                const isEnabled = source.enabled !== false;
                const requireFallRiver = source.require_fall_river === true;
                
                let relevanceDisplay = '';
                if (relevanceScore >= 0) {
                    const color = relevanceScore >= 20 ? '#4caf50' : relevanceScore >= 10 ? '#ff9800' : '#f44336';
                    relevanceDisplay = `
                        <div style="color: #666; font-size: 0.9rem; margin-top: 0.25rem;">
                            Relevance Score: <strong style="color: ${color};">${relevanceScore.toFixed(1)}</strong> points
                        </div>
                    `;
                } else {
                    relevanceDisplay = `
                        <div style="color: #999; font-size: 0.9rem; margin-top: 0.25rem; font-style: italic;">
                            No relevance score set
                        </div>
                    `;
                }
                
                return `
                    <div class="source-item" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid #404040; gap: 2rem;">
                        <div class="source-info" style="flex: 1;">
                            <div class="source-name" style="font-size: 1.2rem; font-weight: 600; color: #e0e0e0; margin-bottom: 0.5rem;">${sourceName}</div>
                            <div class="source-url" style="font-size: 0.9rem; color: #888; margin-bottom: 0.25rem;">${sourceUrl}</div>
                            <div class="source-category" style="font-size: 0.85rem; color: #666;">Category: ${category}</div>
                            ${relevanceDisplay}
                        </div>
                        <div class="source-actions" style="display: flex; gap: 2rem; align-items: center;">
                            <button onclick="window.adminPanel.editSource('${sourceKey}')" 
                                style="padding: 0.5rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1.2rem;" 
                                title="Edit source">✏️</button>
                            <div class="toggle-switch" style="display: flex; align-items: center; gap: 0.5rem;">
                                <label style="font-size: 0.85rem; color: #b0b0b0;">Enabled:</label>
                                <label class="switch" style="position: relative; display: inline-block; width: 50px; height: 24px;">
                                    <input type="checkbox" class="source-enabled" data-source="${sourceKey}" ${isEnabled ? 'checked' : ''} 
                                        onchange="window.adminPanel.updateSourceSetting('${sourceKey}', 'enabled', this.checked ? '1' : '0')"
                                        style="opacity: 0; width: 0; height: 0;">
                                    <span class="slider" style="position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: ${isEnabled ? '#0078d4' : '#ccc'}; transition: .4s; border-radius: 24px;">
                                        <span style="position: absolute; content: ''; height: 18px; width: 18px; left: 3px; bottom: 3px; background-color: white; transition: .4s; border-radius: 50%; transform: ${isEnabled ? 'translateX(26px)' : 'translateX(0)'};"></span>
                                    </span>
                                </label>
                            </div>
                            <div class="toggle-switch" style="display: flex; align-items: center; gap: 0.5rem;">
                                <label style="font-size: 0.85rem; color: #b0b0b0;">Require Fall River:</label>
                                <label class="switch" style="position: relative; display: inline-block; width: 50px; height: 24px;">
                                    <input type="checkbox" class="source-filter" data-source="${sourceKey}" ${requireFallRiver ? 'checked' : ''} 
                                        onchange="window.adminPanel.updateSourceSetting('${sourceKey}', 'require_fall_river', this.checked ? '1' : '0')"
                                        style="opacity: 0; width: 0; height: 0;">
                                    <span class="slider" style="position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: ${requireFallRiver ? '#0078d4' : '#ccc'}; transition: .4s; border-radius: 24px;">
                                        <span style="position: absolute; content: ''; height: 18px; width: 18px; left: 3px; bottom: 3px; background-color: white; transition: .4s; border-radius: 50%; transform: ${requireFallRiver ? 'translateX(26px)' : 'translateX(0)'};"></span>
                                    </span>
                                </label>
                            </div>
                        </div>
                    </div>
                `;
            }).join('') + `
                <div style="margin-top: 1.5rem;">
                    <button onclick="window.adminPanel.addNewSource()" style="padding: 0.75rem 1.5rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">
                        + Add Source
                    </button>
                </div>
                <div style="margin-top: 1.5rem; padding: 1rem; background: #1a1a1a; border-radius: 4px;">
                    <p style="color: #888; font-size: 0.9rem;">
                        <strong>Note:</strong> "Require Fall River" means only articles mentioning "Fall River" will be included from that source.
                        This helps filter out irrelevant content from larger regional sources like Fun107 and WPRI.
                    </p>
                </div>
            `;
        } catch (error) {
            console.error('Error loading sources:', error);
            container.innerHTML = `<p style="color: #d32f2f; text-align: center; padding: 2rem;">Error loading sources: ${error.message}</p>`;
        }
    }

    renderSettings() {
        if (!this.currentZip || !window.storageManager) return;
        
        const container = document.getElementById('settings-content');
        if (!container) return;

        const settings = window.storageManager.getSettings(this.currentZip);

        container.innerHTML = `
            <h2 style="color: #0078d4; margin-bottom: 1.5rem;">Settings for Zip ${this.currentZip}</h2>
            
            <div style="background: #1a1a1a; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                <label style="display: flex; align-items: center; gap: 1rem; cursor: pointer;">
                    <input type="checkbox" ${settings.show_images ? 'checked' : ''} 
                        onchange="window.adminPanel.updateSetting('show_images', this.checked)"
                        style="width: 20px; height: 20px;">
                    <span style="color: #e0e0e0;">Show Images</span>
                </label>
            </div>

            <div style="background: #1a1a1a; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem;">Relevance Threshold</label>
                <input type="number" value="${settings.relevance_threshold || 10}" step="0.1" min="0"
                    onchange="window.adminPanel.updateSetting('relevance_threshold', parseFloat(this.value))"
                    style="width: 100%; padding: 0.5rem; background: #252525; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0;">
            </div>

            <div style="background: #1a1a1a; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                <label style="display: flex; align-items: center; gap: 1rem; cursor: pointer;">
                    <input type="checkbox" ${settings.ai_filtering_enabled ? 'checked' : ''} 
                        onchange="window.adminPanel.updateSetting('ai_filtering_enabled', this.checked)"
                        style="width: 20px; height: 20px;">
                    <span style="color: #e0e0e0;">AI Filtering Enabled</span>
                </label>
            </div>

            <div style="background: #1a1a1a; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                <label style="display: flex; align-items: center; gap: 1rem; cursor: pointer;">
                    <input type="checkbox" ${settings.auto_regenerate ? 'checked' : ''} 
                        onchange="window.adminPanel.updateSetting('auto_regenerate', this.checked)"
                        style="width: 20px; height: 20px;">
                    <span style="color: #e0e0e0;">Auto Regenerate</span>
                </label>
            </div>

            <div style="background: #1a1a1a; padding: 1rem; border-radius: 8px;">
                <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem;">Regenerate Interval (minutes)</label>
                <input type="number" value="${settings.regenerate_interval || 10}" min="1"
                    onchange="window.adminPanel.updateSetting('regenerate_interval', parseInt(this.value))"
                    style="width: 100%; padding: 0.5rem; background: #252525; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0;">
            </div>
        `;
    }

    renderRelevance() {
        if (!this.currentZip || !window.storageManager) return;
        
        const container = document.getElementById('relevance-content');
        if (!container) return;

        const config = window.storageManager.getRelevanceConfig(this.currentZip);
        const settings = window.storageManager.getSettings(this.currentZip);
        const threshold = settings.relevance_threshold || 10.0;

        // Escape HTML for safe rendering
        const escapeHtml = (str) => {
            if (!str) return '';
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        };

        container.innerHTML = `
            <h2 style="color: #0078d4; margin-bottom: 1.5rem;">Relevance Configuration for Zip ${this.currentZip}</h2>
            
            <!-- Auto-Filter Threshold Section -->
            <div style="margin-bottom: 2rem; padding: 1.5rem; background: #1e3a5f; border-left: 4px solid #2196f3; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">
                <h3 style="margin-top: 0; margin-bottom: 1rem; color: #e0e0e0;">Auto-Filter Threshold</h3>
                <p style="color: #b0b0b0; font-size: 0.9rem; margin-bottom: 1rem;">
                    Articles with relevance scores below this threshold will be automatically filtered out during aggregation. 
                    They will be saved and appear in the "Auto-Filtered" tab for review.
                </p>
                <div style="display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;">
                    <label style="font-weight: 600; color: #e0e0e0;">Minimum Relevance Score:</label>
                    <input type="number" id="relevanceThreshold" value="${threshold}" step="0.1" min="0" max="100" 
                        style="padding: 0.5rem; background: #252525; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; width: 100px;">
                    <button onclick="window.adminPanel.saveRelevanceThreshold()" 
                        style="padding: 0.5rem 1rem; background: #2196f3; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">
                        Save Threshold
                    </button>
                    <span id="thresholdSaveStatus" style="color: #4caf50; font-weight: 600; display: none;">✓ Saved</span>
                </div>
            </div>
            
            <!-- Recalculate All Relevance Scores Section -->
            <div style="margin-bottom: 2rem; padding: 1.5rem; background: #3d2817; border-left: 4px solid #ff9800; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">
                <h3 style="margin-top: 0; margin-bottom: 1rem; color: #e0e0e0;">Recalculate All Relevance Scores</h3>
                <p style="color: #b0b0b0; font-size: 0.9rem; margin-bottom: 1rem;">
                    Recalculate relevance scores for all existing articles using the current relevance configuration. 
                    This is useful after making changes to keywords, places, topics, or scoring rules.
                </p>
                <button onclick="window.adminPanel.recalculateRelevanceScores()" 
                    style="padding: 0.75rem 1.5rem; background: #ff9800; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 1rem;">
                    🔄 Recalculate All Relevance Scores
                </button>
                <p style="color: #b0b0b0; font-size: 0.85rem; margin-top: 0.5rem;">
                    This will update all articles in this zip code with new relevance scores based on your current configuration.
                </p>
            </div>
            
            <p style="color: #b0b0b0; margin-bottom: 2rem; line-height: 1.6;">
                Manage the keywords, places, topics, and sources that affect article relevance scores. 
                Changes take effect immediately for new articles.
            </p>
            
            <!-- High Relevance Keywords -->
            <div style="margin-bottom: 2rem; padding: 1.5rem; background: #1a1a1a; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">
                <h3 style="margin-top: 0; margin-bottom: 1rem; color: #0078d4;">High Relevance Keywords (10 points each)</h3>
                <div style="margin-bottom: 1rem;">
                    <input type="text" id="highRelevanceInput" placeholder="Add keyword (e.g., 'fall river')" 
                        style="padding: 0.5rem; background: #252525; border: 1px solid #404040; border-radius: 4px; width: 300px; color: #e0e0e0; margin-right: 0.5rem;">
                    <button onclick="window.adminPanel.addRelevanceItem('high_relevance', document.getElementById('highRelevanceInput').value)" 
                        style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">
                        Add
                    </button>
                </div>
                <div class="relevance-items" id="highRelevanceItems" style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
                    ${(config.high_relevance || []).map(item => `
                        <div class="relevance-item" style="display: inline-flex; align-items: center; padding: 0.5rem 1rem; background: #2d5016; border-radius: 4px; gap: 0.5rem;">
                            <span style="color: #e0e0e0;">${escapeHtml(item)}</span>
                            <button onclick="window.adminPanel.removeRelevanceItem('high_relevance', '${escapeHtml(item)}')" 
                                style="background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer; font-size: 0.85rem;">🗑️</button>
                        </div>
                    `).join('')}
                </div>
            </div>
            
            <!-- Medium Relevance Keywords (Ignore Keywords) -->
            <div style="margin-bottom: 2rem; padding: 1.5rem; background: #1a1a1a; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">
                <h3 style="margin-top: 0; margin-bottom: 1rem; color: #0078d4;">Ignore Keywords (Nearby Towns)</h3>
                <p style="color: #b0b0b0; font-size: 0.9rem; margin-bottom: 1rem; padding: 0.75rem; background: #3d2817; border-left: 4px solid #ff9800; border-radius: 4px;">
                    <strong>Note:</strong> Articles mentioning these nearby towns will be heavily penalized (-15 points) unless Fall River is also mentioned. 
                    If Fall River is mentioned, they get a small bonus (+1 point). This helps filter out articles about nearby towns that aren't relevant.
                </p>
                <div style="margin-bottom: 1rem;">
                    <input type="text" id="mediumRelevanceInput" placeholder="Add keyword (e.g., 'somerset')" 
                        style="padding: 0.5rem; background: #252525; border: 1px solid #404040; border-radius: 4px; width: 300px; color: #e0e0e0; margin-right: 0.5rem;">
                    <button onclick="window.adminPanel.addRelevanceItem('medium_relevance', document.getElementById('mediumRelevanceInput').value)" 
                        style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">
                        Add
                    </button>
                </div>
                <div class="relevance-items" id="mediumRelevanceItems" style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
                    ${(config.medium_relevance || []).map(item => `
                        <div class="relevance-item" style="display: inline-flex; align-items: center; padding: 0.5rem 1rem; background: #3d2817; border-radius: 4px; gap: 0.5rem;">
                            <span style="color: #e0e0e0;">${escapeHtml(item)}</span>
                            <button onclick="window.adminPanel.removeRelevanceItem('medium_relevance', '${escapeHtml(item)}')" 
                                style="background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer; font-size: 0.85rem;">🗑️</button>
                        </div>
                    `).join('')}
                </div>
            </div>
            
            <!-- Local Places -->
            <div style="margin-bottom: 2rem; padding: 1.5rem; background: #1a1a1a; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">
                <h3 style="margin-top: 0; margin-bottom: 1rem; color: #0078d4;">Local Places (3 points each)</h3>
                <div style="margin-bottom: 1rem;">
                    <input type="text" id="localPlacesInput" placeholder="Add place (e.g., 'battleship cove')" 
                        style="padding: 0.5rem; background: #252525; border: 1px solid #404040; border-radius: 4px; width: 300px; color: #e0e0e0; margin-right: 0.5rem;">
                    <button onclick="window.adminPanel.addRelevanceItem('local_places', document.getElementById('localPlacesInput').value)" 
                        style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">
                        Add
                    </button>
                </div>
                <div class="relevance-items" id="localPlacesItems" style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
                    ${(config.local_places || []).map(item => `
                        <div class="relevance-item" style="display: inline-flex; align-items: center; padding: 0.5rem 1rem; background: #1e3a5f; border-radius: 4px; gap: 0.5rem;">
                            <span style="color: #e0e0e0;">${escapeHtml(item)}</span>
                            <button onclick="window.adminPanel.removeRelevanceItem('local_places', '${escapeHtml(item)}')" 
                                style="background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer; font-size: 0.85rem;">🗑️</button>
                        </div>
                    `).join('')}
                </div>
            </div>
            
            <!-- Topic Keywords -->
            <div style="margin-bottom: 2rem; padding: 1.5rem; background: #1a1a1a; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">
                <h3 style="margin-top: 0; margin-bottom: 1rem; color: #0078d4;">Topic Keywords (Variable Points)</h3>
                <div style="margin-bottom: 1rem;">
                    <input type="text" id="topicKeywordInput" placeholder="Keyword" 
                        style="padding: 0.5rem; background: #252525; border: 1px solid #404040; border-radius: 4px; width: 200px; color: #e0e0e0; margin-right: 0.5rem;">
                    <input type="number" id="topicPointsInput" placeholder="Points" step="0.1" 
                        style="padding: 0.5rem; background: #252525; border: 1px solid #404040; border-radius: 4px; width: 100px; color: #e0e0e0; margin-right: 0.5rem;">
                    <button onclick="window.adminPanel.addRelevanceItem('topic_keywords', document.getElementById('topicKeywordInput').value, parseFloat(document.getElementById('topicPointsInput').value))" 
                        style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">
                        Add
                    </button>
                </div>
                <div class="relevance-items" id="topicKeywordsItems">
                    ${Object.entries(config.topic_keywords || {}).map(([keyword, points]) => `
                        <div class="relevance-item" style="display: flex; align-items: center; margin: 0.5rem 0; padding: 0.75rem; background: #2d1b3d; border-radius: 4px; gap: 0.5rem;">
                            <span style="flex: 1; font-weight: 600; color: #e0e0e0;">${escapeHtml(keyword)}</span>
                            <input type="number" value="${points}" step="0.1" 
                                onchange="window.adminPanel.updateTopicKeywordPoints('${escapeHtml(keyword)}', parseFloat(this.value))" 
                                style="width: 80px; padding: 0.25rem; background: #252525; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; margin: 0 0.5rem;">
                            <span style="margin-right: 0.5rem; color: #b0b0b0;">points</span>
                            <button onclick="window.adminPanel.removeRelevanceItem('topic_keywords', '${escapeHtml(keyword)}')" 
                                style="background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer; font-size: 0.85rem;">🗑️</button>
                        </div>
                    `).join('')}
                </div>
            </div>
            
            <!-- Source Credibility (Read-Only) -->
            <div style="margin-bottom: 2rem; padding: 1.5rem; background: #1a1a1a; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">
                <h3 style="margin-top: 0; margin-bottom: 1rem; color: #0078d4;">Source Credibility (Variable Points)</h3>
                <p style="color: #b0b0b0; font-size: 0.9rem; margin-bottom: 1rem; padding: 0.75rem; background: #3d2817; border-left: 4px solid #ff9800; border-radius: 4px;">
                    <strong>Note:</strong> Source credibility scores are managed on the <a href="#" onclick="window.adminPanel.switchTab('sources'); return false;" style="color: #60a5fa; text-decoration: underline;">Sources page</a>. 
                    Edit a source to set or change its relevance score. This section is read-only for reference.
                </p>
                <div class="relevance-items" id="sourceCredibilityItems">
                    ${Object.keys(config.source_credibility || {}).length > 0 ? 
                        Object.entries(config.source_credibility || {}).map(([source, points]) => {
                            const color = points >= 20 ? '#4caf50' : points >= 10 ? '#ff9800' : '#f44336';
                            return `
                                <div class="relevance-item" style="display: flex; align-items: center; margin: 0.5rem 0; padding: 0.75rem; background: #3d2817; border-radius: 4px; gap: 0.5rem;">
                                    <span style="flex: 1; font-weight: 600; color: #e0e0e0;">${escapeHtml(source)}</span>
                                    <span style="width: 80px; padding: 0.25rem; margin: 0 0.5rem; text-align: right; font-weight: 600; color: ${color};">
                                        ${points.toFixed(1)}
                                    </span>
                                    <span style="margin-right: 0.5rem; color: #b0b0b0;">points</span>
                                </div>
                            `;
                        }).join('') :
                        '<p style="color: #888; font-style: italic; padding: 1rem;">No source credibility scores configured. Add sources on the Sources page to set their relevance scores.</p>'
                    }
                </div>
            </div>
            
            <!-- Clickbait Patterns -->
            <div style="margin-bottom: 2rem; padding: 1.5rem; background: #1a1a1a; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">
                <h3 style="margin-top: 0; margin-bottom: 1rem; color: #0078d4;">Clickbait Patterns (Penalty: -5 points each)</h3>
                <div style="margin-bottom: 1rem;">
                    <input type="text" id="clickbaitInput" placeholder="Add pattern (e.g., 'you won't believe')" 
                        style="padding: 0.5rem; background: #252525; border: 1px solid #404040; border-radius: 4px; width: 300px; color: #e0e0e0; margin-right: 0.5rem;">
                    <button onclick="window.adminPanel.addRelevanceItem('clickbait_patterns', document.getElementById('clickbaitInput').value)" 
                        style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">
                        Add
                    </button>
                </div>
                <div class="relevance-items" id="clickbaitItems" style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
                    ${(config.clickbait_patterns || []).map(item => `
                        <div class="relevance-item" style="display: inline-flex; align-items: center; padding: 0.5rem 1rem; background: #4d1a1a; border-radius: 4px; gap: 0.5rem;">
                            <span style="color: #e0e0e0;">${escapeHtml(item)}</span>
                            <button onclick="window.adminPanel.removeRelevanceItem('clickbait_patterns', '${escapeHtml(item)}')" 
                                style="background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer; font-size: 0.85rem;">🗑️</button>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    updateSetting(key, value) {
        if (!this.currentZip || !window.storageManager) return;
        const settings = window.storageManager.getSettings(this.currentZip);
        settings[key] = value;
        window.storageManager.setSettings(this.currentZip, settings);
        alert('Setting saved!');
    }

    saveRelevanceThreshold() {
        if (!this.currentZip || !window.storageManager) return;
        const input = document.getElementById('relevanceThreshold');
        if (!input) return;
        
        const threshold = parseFloat(input.value);
        if (isNaN(threshold) || threshold < 0) {
            alert('Please enter a valid threshold value (0 or greater)');
            return;
        }
        
        const settings = window.storageManager.getSettings(this.currentZip);
        settings.relevance_threshold = threshold;
        window.storageManager.setSettings(this.currentZip, settings);
        
        // Show save status
        const statusEl = document.getElementById('thresholdSaveStatus');
        if (statusEl) {
            statusEl.style.display = 'inline';
            setTimeout(() => {
                statusEl.style.display = 'none';
            }, 2000);
        }
    }

    recalculateRelevanceScores() {
        if (!this.currentZip || !window.storageManager) return;
        
        if (!confirm('Recalculate relevance scores for all articles in this zip code? This may take a moment.')) {
            return;
        }
        
        // Get all articles for this zip
        window.storageManager.getArticles(this.currentZip).then(articles => {
            const config = window.storageManager.getRelevanceConfig(this.currentZip);
            let updated = 0;
            
            articles.forEach(article => {
                const score = this.calculateRelevanceScore(article, config);
                window.storageManager.setRelevanceScore(this.currentZip, article.id, score);
                updated++;
            });
            
            alert(`Recalculated relevance scores for ${updated} articles.`);
        }).catch(err => {
            console.error('Error recalculating scores:', err);
            alert('Error recalculating scores. Check console for details.');
        });
    }

    calculateRelevanceScore(article, config) {
        const content = (article.content || article.summary || '').toLowerCase();
        const title = (article.title || '').toLowerCase();
        const combined = `${title} ${content}`;
        
        let score = 0.0;
        
        // High relevance keywords (10 points each)
        const highRelevance = config.high_relevance || [];
        for (const keyword of highRelevance) {
            if (combined.includes(keyword.toLowerCase())) {
                score += 10.0;
            }
        }
        
        // Medium relevance keywords - penalize if Fall River not mentioned
        const mediumRelevance = config.medium_relevance || [];
        const hasFallRiver = combined.includes('fall river') || combined.includes('fallriver');
        
        for (const keyword of mediumRelevance) {
            if (combined.includes(keyword.toLowerCase())) {
                if (hasFallRiver) {
                    score += 1.0; // Small bonus if Fall River also mentioned
                } else {
                    score -= 15.0; // Heavy penalty if Fall River not mentioned
                }
            }
        }
        
        // Local places (3 points each)
        const localPlaces = config.local_places || [];
        for (const place of localPlaces) {
            if (combined.includes(place.toLowerCase())) {
                score += 3.0;
            }
        }
        
        // Topic keywords (variable points)
        const topicKeywords = config.topic_keywords || {};
        for (const [keyword, points] of Object.entries(topicKeywords)) {
            if (combined.includes(keyword.toLowerCase())) {
                score += points;
            }
        }
        
        // Source credibility
        const source = (article.source || '').toLowerCase();
        const sourceCredibility = config.source_credibility || {};
        if (sourceCredibility[source] !== undefined) {
            score += sourceCredibility[source];
        }
        
        // Clickbait patterns (-5 points each)
        const clickbaitPatterns = config.clickbait_patterns || [];
        for (const pattern of clickbaitPatterns) {
            if (combined.includes(pattern.toLowerCase())) {
                score -= 5.0;
            }
        }
        
        return Math.max(0, score); // Don't allow negative scores
    }

    addRelevanceItem(category, item, points) {
        if (!this.currentZip || !window.storageManager) return;
        
        // If item is not provided, try to get from input field
        if (!item) {
            const inputId = category === 'high_relevance' ? 'highRelevanceInput' :
                          category === 'medium_relevance' ? 'mediumRelevanceInput' :
                          category === 'local_places' ? 'localPlacesInput' :
                          category === 'clickbait_patterns' ? 'clickbaitInput' :
                          category === 'topic_keywords' ? 'topicKeywordInput' : null;
            
            if (inputId) {
                const input = document.getElementById(inputId);
                if (input) {
                    item = input.value.trim();
                    if (category === 'topic_keywords') {
                        const pointsInput = document.getElementById('topicPointsInput');
                        if (pointsInput) {
                            points = parseFloat(pointsInput.value);
                        }
                    }
                }
            }
        }
        
        if (!item) return;
        
        const config = window.storageManager.getRelevanceConfig(this.currentZip);
        
        // Handle different category types
        if (category === 'topic_keywords') {
            // Topic keywords is an object with keyword:points
            if (!config.topic_keywords) config.topic_keywords = {};
            if (points === undefined || isNaN(points)) {
                alert('Points are required for topic keywords');
                return;
            }
            config.topic_keywords[item] = points;
            // Clear inputs
            const keywordInput = document.getElementById('topicKeywordInput');
            const pointsInput = document.getElementById('topicPointsInput');
            if (keywordInput) keywordInput.value = '';
            if (pointsInput) pointsInput.value = '';
        } else {
            // All other categories are arrays
            if (!config[category]) config[category] = [];
            if (config[category].includes(item)) {
                alert('This item already exists');
                return;
            }
            config[category].push(item);
            // Clear input
            const inputId = category === 'high_relevance' ? 'highRelevanceInput' :
                          category === 'medium_relevance' ? 'mediumRelevanceInput' :
                          category === 'local_places' ? 'localPlacesInput' :
                          category === 'clickbait_patterns' ? 'clickbaitInput' : null;
            if (inputId) {
                const input = document.getElementById(inputId);
                if (input) input.value = '';
            }
        }
        
        window.storageManager.setRelevanceConfig(this.currentZip, config);
        this.renderRelevance();
    }

    removeRelevanceItem(category, item) {
        if (!this.currentZip || !window.storageManager) return;
        const config = window.storageManager.getRelevanceConfig(this.currentZip);
        
        if (category === 'topic_keywords') {
            // Topic keywords is an object
            if (config.topic_keywords && config.topic_keywords[item] !== undefined) {
                delete config.topic_keywords[item];
                window.storageManager.setRelevanceConfig(this.currentZip, config);
                this.renderRelevance();
            }
        } else {
            // All other categories are arrays
            if (config[category]) {
                config[category] = config[category].filter(i => i !== item);
                window.storageManager.setRelevanceConfig(this.currentZip, config);
                this.renderRelevance();
            }
        }
    }

    updateTopicKeywordPoints(keyword, points) {
        if (!this.currentZip || !window.storageManager) return;
        if (isNaN(points)) {
            alert('Please enter a valid number');
            return;
        }
        
        const config = window.storageManager.getRelevanceConfig(this.currentZip);
        if (!config.topic_keywords) config.topic_keywords = {};
        config.topic_keywords[keyword] = points;
        window.storageManager.setRelevanceConfig(this.currentZip, config);
    }

    async updateSourceSetting(sourceKey, setting, value) {
        if (!this.currentZip) return;
        
        try {
            const response = await fetch('/admin/api/source', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({
                    source: sourceKey,
                    setting: setting,
                    value: value
                })
            });
            const data = await response.json();
            
            if (data.success) {
                console.log(`Source ${sourceKey} ${setting} updated to ${value}`);
                // Reload sources to show updated state
                await this.renderSources();
            } else {
                alert('Error updating source setting: ' + (data.error || data.message));
            }
        } catch (err) {
            console.error('Error updating source setting:', err);
            alert('Error updating source setting');
        }
    }
    
    updateSourceCredibility(source, points) {
        if (!this.currentZip || !window.storageManager) return;
        const config = window.storageManager.getRelevanceConfig(this.currentZip);
        if (!config.source_credibility) config.source_credibility = {};
        config.source_credibility[source] = points;
        window.storageManager.setRelevanceConfig(this.currentZip, config);
    }

    removeSourceCredibility(source) {
        if (!this.currentZip || !window.storageManager) return;
        const config = window.storageManager.getRelevanceConfig(this.currentZip);
        if (config.source_credibility) {
            delete config.source_credibility[source];
            window.storageManager.setRelevanceConfig(this.currentZip, config);
            this.renderRelevance();
        }
    }

    async restoreArticle(articleId) {
        if (!this.currentZip) return;
        if (!confirm('Restore this article from trash?')) return;
        
        try {
            // Use the toggle-article API to enable the article (which removes it from trash)
            // CRITICAL: Include zip_code in request body
            const response = await fetch('/admin/api/toggle-article', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({
                    article_id: parseInt(articleId),
                    enabled: true,
                    zip_code: this.currentZip  // CRITICAL: Include zip_code
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.success) {
                // Reload trash and articles
                await this.renderTrash();
                await this.loadArticles();
                this.updateStats();
            } else {
                alert('Error restoring article: ' + (data.message || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error restoring article:', error);
            alert('Error: ' + error.message);
        }
    }

    async deleteArticlePermanently(articleId) {
        if (!this.currentZip) return;
        if (!confirm('Permanently delete this article? This cannot be undone.')) return;
        
        try {
            // TODO: Add delete-article API endpoint if needed
            // For now, just disable it and remove from trash
            // CRITICAL: Include zip_code in request body
            const response = await fetch('/admin/api/toggle-article', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({
                    article_id: parseInt(articleId),
                    enabled: false,
                    zip_code: this.currentZip  // CRITICAL: Include zip_code
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.success) {
                await this.renderTrash();
                this.updateStats();
                alert('Article disabled. Full deletion not yet implemented via API.');
            } else {
                alert('Error deleting article: ' + (data.message || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error deleting article:', error);
            alert('Error: ' + error.message);
        }
    }

    async restoreAutoFiltered(articleId) {
        if (!this.currentZip) return;
        if (!confirm('Restore this article? It will be enabled and removed from auto-filtered list.')) return;
        
        try {
            // CRITICAL: Include zip_code in request body
            const response = await fetch('/admin/api/restore-auto-filtered', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({
                    article_id: parseInt(articleId),
                    zip_code: this.currentZip  // CRITICAL: Include zip_code
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.success) {
                // Reload auto-filtered and articles
                await this.renderAutoFiltered();
                await this.loadArticles();
                this.updateStats();
            } else {
                alert('Error restoring article: ' + (data.message || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error restoring auto-filtered article:', error);
            alert('Error: ' + error.message);
        }
    }

    addNewSource() {
        // Show the edit modal with empty fields for new source
        this.showEditSourceModal({
            key: '',
            name: '',
            url: '',
            rss: '',
            category: 'news',
            relevance_score: ''
        });
    }

    async editSource(sourceKey) {
        try {
            const response = await fetch(`/admin/api/get-source?key=${encodeURIComponent(sourceKey)}`, {
                credentials: 'same-origin'
            });
            const data = await response.json();
            
            if (data.success && data.source) {
                this.showEditSourceModal(data.source);
            } else {
                alert('Error loading source: ' + (data.message || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error loading source:', error);
            alert('Error: ' + error.message);
        }
    }

    showEditSourceModal(source) {
        let modal = document.getElementById('editSourceModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'editSourceModal';
            modal.style.cssText = 'display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; overflow: auto; background-color: rgba(0,0,0,0.5);';
            modal.innerHTML = `
                <div style="background-color: #252525; margin: 5% auto; padding: 0; border-radius: 8px; width: 90%; max-width: 600px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid #404040;">
                        <h2 style="color: #0078d4; margin: 0;" id="editSourceModalTitle">Edit Source</h2>
                        <span onclick="window.adminPanel.closeEditSourceModal()" style="color: #888; font-size: 2rem; font-weight: bold; cursor: pointer; line-height: 1;">&times;</span>
                    </div>
                    <form id="editSourceForm" onsubmit="window.adminPanel.saveSourceEdit(event)" style="padding: 1.5rem;">
                        <input type="hidden" id="editSourceKey" name="key">
                        <div style="margin-bottom: 1rem;">
                            <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">Name:</label>
                            <input type="text" id="editSourceName" name="name" required 
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                        </div>
                        <div style="margin-bottom: 1rem;">
                            <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">URL:</label>
                            <input type="url" id="editSourceUrl" name="url" required 
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                        </div>
                        <div style="margin-bottom: 1rem;">
                            <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">RSS URL:</label>
                            <input type="url" id="editSourceRss" name="rss" 
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                        </div>
                        <div style="margin-bottom: 1rem;">
                            <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">Category:</label>
                            <select id="editSourceCategory" name="category" 
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                                <option value="news">News</option>
                                <option value="entertainment">Entertainment</option>
                                <option value="sports">Sports</option>
                                <option value="media">Media</option>
                                <option value="local">Local</option>
                            </select>
                        </div>
                        <div style="margin-bottom: 1.5rem;">
                            <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">Relevance Score (points):</label>
                            <input type="number" id="editSourceRelevanceScore" name="relevance_score" step="1" min="0" max="100" placeholder="e.g., 25" 
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                            <small style="color: #888; display: block; margin-top: 0.25rem;">Points added to articles from this source (0-100). Higher = more credible/relevant.</small>
                        </div>
                        <div style="display: flex; gap: 1rem; justify-content: flex-end;">
                            <button type="submit" style="padding: 0.75rem 1.5rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 1rem;">Save</button>
                            <button type="button" onclick="window.adminPanel.closeEditSourceModal()" style="padding: 0.75rem 1.5rem; background: #404040; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 1rem;">Cancel</button>
                        </div>
                    </form>
                </div>
            `;
            document.body.appendChild(modal);
            
            // Close modal when clicking outside
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.closeEditSourceModal();
                }
            });
        }
        
        // Populate fields
        setTimeout(() => {
            const titleField = document.getElementById('editSourceModalTitle');
            const keyField = document.getElementById('editSourceKey');
            const nameField = document.getElementById('editSourceName');
            const urlField = document.getElementById('editSourceUrl');
            const rssField = document.getElementById('editSourceRss');
            const categoryField = document.getElementById('editSourceCategory');
            const relevanceScoreField = document.getElementById('editSourceRelevanceScore');
            
            if (titleField) titleField.textContent = source.key ? 'Edit Source' : 'Add New Source';
            if (keyField) keyField.value = source.key || '';
            if (nameField) nameField.value = source.name || '';
            if (urlField) urlField.value = source.url || '';
            if (rssField) rssField.value = source.rss || '';
            if (categoryField) categoryField.value = source.category || 'news';
            if (relevanceScoreField) relevanceScoreField.value = source.relevance_score !== null && source.relevance_score !== undefined ? source.relevance_score : '';
        }, 100);
        
        modal.style.display = 'block';
    }

    closeEditSourceModal() {
        const modal = document.getElementById('editSourceModal');
        if (modal) {
            modal.style.display = 'none';
        }
    }

    async saveSourceEdit(event) {
        event.preventDefault();
        const form = event.target;
        const formData = new FormData(form);
        const key = formData.get('key');
        const data = {
            key: key,
            name: formData.get('name'),
            url: formData.get('url'),
            rss: formData.get('rss'),
            category: formData.get('category'),
            relevance_score: formData.get('relevance_score')
        };
        
        // If no key, it's a new source - use add-source endpoint
        const endpoint = key ? '/admin/api/edit-source' : '/admin/api/add-source';
        
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify(data)
            });
            const result = await response.json();
            
            if (result.success) {
                this.closeEditSourceModal();
                // Reload sources
                await this.renderSources();
            } else {
                alert('Error saving source: ' + (result.message || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error saving source:', error);
            alert('Error: ' + error.message);
        }
    }

    async editArticle(articleId) {
        try {
            const response = await fetch(`/admin/api/get-article?id=${encodeURIComponent(articleId)}`, {
                credentials: 'same-origin'
            });
            const data = await response.json();
            
            if (data.success && data.article) {
                this.showEditArticleModal(data.article);
            } else {
                alert('Error loading article: ' + (data.message || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error loading article:', error);
            alert('Error: ' + error.message);
        }
    }

    showEditArticleModal(article) {
        let modal = document.getElementById('editArticleModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'editArticleModal';
            modal.style.cssText = 'display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; overflow: auto; background-color: rgba(0,0,0,0.5);';
            modal.innerHTML = `
                <div style="background-color: #252525; margin: 5% auto; padding: 0; border-radius: 8px; width: 90%; max-width: 700px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); max-height: 90vh; overflow-y: auto;">
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid #404040;">
                        <h2 style="color: #0078d4; margin: 0;">Edit Article</h2>
                        <span onclick="window.adminPanel.closeEditArticleModal()" style="color: #888; font-size: 2rem; font-weight: bold; cursor: pointer; line-height: 1;">&times;</span>
                    </div>
                    <form id="editArticleForm" onsubmit="window.adminPanel.saveArticleEdit(event)" style="padding: 1.5rem;">
                        <input type="hidden" id="editArticleId" name="id">
                        <div style="margin-bottom: 1rem;">
                            <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">Title:</label>
                            <input type="text" id="editArticleTitle" name="title" required 
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                        </div>
                        <div style="margin-bottom: 1rem;">
                            <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">Summary:</label>
                            <textarea id="editArticleSummary" name="summary" rows="4"
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem; resize: vertical;"></textarea>
                        </div>
                        <div style="margin-bottom: 1rem;">
                            <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">Category:</label>
                            <select id="editArticleCategory" name="category" 
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                                <option value="news">News</option>
                                <option value="entertainment">Entertainment</option>
                                <option value="sports">Sports</option>
                                <option value="media">Media</option>
                                <option value="local">Local</option>
                            </select>
                        </div>
                        <div style="margin-bottom: 1rem;">
                            <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">URL:</label>
                            <input type="url" id="editArticleUrl" name="url" 
                                style="width: 100%; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                        </div>
                        <div style="margin-bottom: 1rem;">
                            <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">Relevance Score (0-100):</label>
                            <div style="display: flex; gap: 0.5rem; align-items: center;">
                                <button type="button" onclick="window.adminPanel.adjustRelevanceScore(-5)" style="padding: 0.5rem 1rem; background: #404040; color: white; border: none; border-radius: 4px; cursor: pointer;">-5</button>
                                <button type="button" onclick="window.adminPanel.adjustRelevanceScore(-1)" style="padding: 0.5rem 1rem; background: #404040; color: white; border: none; border-radius: 4px; cursor: pointer;">-1</button>
                                <input type="number" id="editArticleRelevanceScore" name="relevance_score" step="1" min="0" max="100" 
                                    style="flex: 1; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                                <button type="button" onclick="window.adminPanel.adjustRelevanceScore(1)" style="padding: 0.5rem 1rem; background: #404040; color: white; border: none; border-radius: 4px; cursor: pointer;">+1</button>
                                <button type="button" onclick="window.adminPanel.adjustRelevanceScore(5)" style="padding: 0.5rem 1rem; background: #404040; color: white; border: none; border-radius: 4px; cursor: pointer;">+5</button>
                            </div>
                        </div>
                        <div style="margin-bottom: 1.5rem;">
                            <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">Local Score (0-100%):</label>
                            <div style="display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.5rem;">
                                <button type="button" onclick="window.adminPanel.adjustLocalScore(-10)" style="padding: 0.5rem 1rem; background: #404040; color: white; border: none; border-radius: 4px; cursor: pointer;">-10</button>
                                <button type="button" onclick="window.adminPanel.adjustLocalScore(-1)" style="padding: 0.5rem 1rem; background: #404040; color: white; border: none; border-radius: 4px; cursor: pointer;">-1</button>
                                <input type="number" id="editArticleLocalScore" name="local_score" step="1" min="0" max="100" 
                                    style="flex: 1; padding: 0.75rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 1rem;">
                                <button type="button" onclick="window.adminPanel.adjustLocalScore(1)" style="padding: 0.5rem 1rem; background: #404040; color: white; border: none; border-radius: 4px; cursor: pointer;">+1</button>
                                <button type="button" onclick="window.adminPanel.adjustLocalScore(10)" style="padding: 0.5rem 1rem; background: #404040; color: white; border: none; border-radius: 4px; cursor: pointer;">+10</button>
                            </div>
                            <div id="localScoreMeter" style="width: 100%; height: 12px; background: #404040; border-radius: 6px; overflow: hidden; margin-top: 0.5rem;">
                                <div id="localScoreMeterFill" style="height: 100%; width: 0%; background: #d32f2f; transition: width 0.3s, background 0.3s;"></div>
                            </div>
                            <small style="color: #888; display: block; margin-top: 0.25rem;">Local relevance percentage (0-100%)</small>
                        </div>
                        <div style="display: flex; gap: 1rem; justify-content: flex-end;">
                            <button type="submit" style="padding: 0.75rem 1.5rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 1rem;">Save</button>
                            <button type="button" onclick="window.adminPanel.closeEditArticleModal()" style="padding: 0.75rem 1.5rem; background: #404040; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 1rem;">Cancel</button>
                        </div>
                    </form>
                </div>
            `;
            document.body.appendChild(modal);
            
            // Close modal when clicking outside
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.closeEditArticleModal();
                }
            });
        }
        
        // Populate fields
        setTimeout(() => {
            const idField = document.getElementById('editArticleId');
            const titleField = document.getElementById('editArticleTitle');
            const summaryField = document.getElementById('editArticleSummary');
            const categoryField = document.getElementById('editArticleCategory');
            const urlField = document.getElementById('editArticleUrl');
            const relevanceScoreField = document.getElementById('editArticleRelevanceScore');
            const localScoreField = document.getElementById('editArticleLocalScore');
            
            if (idField) idField.value = article.id || '';
            if (titleField) titleField.value = article.title || '';
            if (summaryField) summaryField.value = article.summary || '';
            if (categoryField) categoryField.value = article.category || 'news';
            if (urlField) urlField.value = article.url || '';
            if (relevanceScoreField) {
                relevanceScoreField.value = article.relevance_score !== null && article.relevance_score !== undefined ? article.relevance_score : '';
            }
            if (localScoreField) {
                localScoreField.value = article.local_score !== null && article.local_score !== undefined ? article.local_score : '';
                this.updateLocalScoreMeter();
            }
            
            // Add event listeners for live meter updates
            if (localScoreField) {
                localScoreField.addEventListener('input', () => this.updateLocalScoreMeter());
            }
        }, 100);
        
        modal.style.display = 'block';
    }

    updateLocalScoreMeter() {
        const localScoreField = document.getElementById('editArticleLocalScore');
        const meterFill = document.getElementById('localScoreMeterFill');
        if (!localScoreField || !meterFill) return;
        
        const value = parseFloat(localScoreField.value) || 0;
        const percent = Math.max(0, Math.min(100, value));
        
        let color = '#d32f2f'; // red
        if (percent > 60) color = '#4caf50'; // green
        else if (percent > 30) color = '#ff9800'; // yellow/orange
        
        meterFill.style.width = percent + '%';
        meterFill.style.background = color;
    }

    adjustRelevanceScore(delta) {
        const field = document.getElementById('editArticleRelevanceScore');
        if (!field) return;
        const current = parseFloat(field.value) || 0;
        const newValue = Math.max(0, Math.min(100, current + delta));
        field.value = newValue;
    }

    adjustLocalScore(delta) {
        const field = document.getElementById('editArticleLocalScore');
        if (!field) return;
        const current = parseFloat(field.value) || 0;
        const newValue = Math.max(0, Math.min(100, current + delta));
        field.value = newValue;
        this.updateLocalScoreMeter();
    }

    closeEditArticleModal() {
        const modal = document.getElementById('editArticleModal');
        if (modal) {
            modal.style.display = 'none';
        }
    }

    async saveArticleEdit(event) {
        event.preventDefault();
        const form = event.target;
        const formData = new FormData(form);
        const articleId = formData.get('id');
        const data = {
            id: articleId,
            title: formData.get('title'),
            summary: formData.get('summary'),
            category: formData.get('category'),
            url: formData.get('url'),
            relevance_score: formData.get('relevance_score') || null,
            local_score: formData.get('local_score') || null
        };
        
        try {
            const response = await fetch('/admin/api/edit-article', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify(data)
            });
            const result = await response.json();
            
            if (result.success) {
                this.closeEditArticleModal();
                // Reload articles
                await this.loadArticles();
            } else {
                alert('Error saving article: ' + (result.message || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error saving article:', error);
            alert('Error: ' + error.message);
        }
    }

    deleteSource(key) {
        if (!this.currentZip) return;
        if (confirm('Delete this source?')) {
            // TODO: Add delete-source API endpoint if needed
            alert('Delete source functionality not yet implemented. Please use the server-side admin for now.');
        }
    }

    setupEventListeners() {
        // Event delegation for article action buttons - use window.adminPanel to ensure correct instance
        // Use capture phase and ensure DOM is ready
        const attachArticleHandlers = () => {
            // Remove any existing listener first to avoid duplicates
            if (this._articleHandler) {
                document.body.removeEventListener('click', this._articleHandler, true);
            }
            
            // Create handler that uses window.adminPanel instead of this
            this._articleHandler = (e) => {
                // Check for top story button
                const topStoryBtn = e.target.closest('.top-story-btn');
                if (topStoryBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    const articleId = topStoryBtn.getAttribute('data-id');
                    if (articleId && window.adminPanel) {
                        try {
                            window.adminPanel.toggleTopStory(articleId);
                        } catch (error) {
                            console.error('Error calling toggleTopStory:', error);
                        }
                    }
                    return;
                }
                
                // Check for good fit button
                const goodFitBtn = e.target.closest('.good-fit-btn');
                if (goodFitBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    const articleId = goodFitBtn.getAttribute('data-id');
                    if (articleId && window.adminPanel) {
                        try {
                            window.adminPanel.toggleGoodFit(articleId);
                        } catch (error) {
                            console.error('Error calling toggleGoodFit:', error);
                        }
                    }
                    return;
                }
                
                // Check for edit article button
                const editBtn = e.target.closest('.edit-article-btn');
                if (editBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    const articleId = editBtn.getAttribute('data-id');
                    if (articleId && window.adminPanel) {
                        try {
                            window.adminPanel.editArticle(articleId);
                        } catch (error) {
                            console.error('Error calling editArticle:', error);
                            alert('Error opening edit modal: ' + error.message);
                        }
                    }
                    return;
                }
                
                // Check for trash button (thumbs down)
                const trashBtn = e.target.closest('.trash-btn');
                if (trashBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    const articleId = trashBtn.getAttribute('data-id');
                    if (articleId && window.adminPanel) {
                        try {
                            window.adminPanel.trashArticle(articleId);
                        } catch (error) {
                            console.error('Error calling trashArticle:', error);
                            alert('Error trashing article: ' + error.message);
                        }
                    }
                    return;
                }
            };
            
            // Attach with capture phase for early interception
            document.body.addEventListener('click', this._articleHandler, true);
            console.log('Article button event listeners attached');
        };
        
        // Attach immediately if DOM is ready, otherwise wait
        if (document.body) {
            attachArticleHandlers();
        } else {
            document.addEventListener('DOMContentLoaded', attachArticleHandlers);
        }
    }

    logout() {
        if (this.isMainAdmin) {
            sessionStorage.removeItem('admin_logged_in_main');
            window.location.href = '/admin/main';
        } else if (this.currentZip) {
            sessionStorage.removeItem(`admin_logged_in_${this.currentZip}`);
            window.location.href = `/admin/${this.currentZip}`;
        } else {
            window.location.href = '/';
        }
    }
}

// Initialize admin panel
let adminPanel;
if (typeof window !== 'undefined') {
    const initAdminPanel = () => {
        // Check if this is a server-rendered admin page (has articles already in DOM)
        const container = document.getElementById('articles-list');
        const isServerRendered = container && container.querySelectorAll('.article-item').length > 0;
        
        // Only initialize if not server-rendered OR if we need to add event handlers
        // For server-rendered pages, we still want event handlers but don't want to clear articles
        adminPanel = new AdminPanel();
        window.adminPanel = adminPanel;
        
        // If server-rendered, extract articles from DOM instead of loading from IndexedDB
        if (isServerRendered) {
            console.log('Server-rendered page detected, extracting articles from DOM');
            // Don't call loadArticles() which would try to load from IndexedDB
            // Just extract existing articles and setup event listeners
            adminPanel.extractArticlesFromDOM();
            adminPanel.setupEventListeners();
        }
    };
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAdminPanel);
    } else {
        initAdminPanel();
    }
}

