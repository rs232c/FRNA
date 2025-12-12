/**
 * Article Renderer - Renders articles dynamically
 */

class ArticleRenderer {
    constructor() {
        this.currentArticles = [];
        this.currentZip = null;
    }

    async renderArticles(articles, zipCode) {
        // CRITICAL: Must have zip code
        if (!zipCode || !/^\d{5}$/.test(zipCode)) {
            console.error('Invalid zip code for article rendering:', zipCode);
            return;
        }
        
        // Save current scroll position to prevent jumping
        const scrollY = window.scrollY;
        const scrollX = window.scrollX;
        
        this.currentArticles = articles || [];
        this.currentZip = zipCode;
        
        // SYNC TOP STORIES FROM DATABASE TO LOCALSTORAGE - CRITICAL FOR PER-ZIP ISOLATION
        if (window.storageManager) {
            try {
                const response = await fetch(`/api/get-top-stories?zip_code=${zipCode}`);
                if (response.ok) {
                    const data = await response.json();
                    if (data.success && data.top_stories) {
                        // Sync top stories from database to localStorage
                        window.storageManager.setTopStories(zipCode, data.top_stories);
                        console.log(`Synced ${data.top_stories.length} top stories from database for zip ${zipCode}`);
                    }
                }
            } catch (error) {
                console.warn('Could not sync top stories from database:', error);
            }
        }
        
        // Filter out trashed and disabled articles - CRITICAL: Always use zipCode parameter
        if (window.storageManager) {
            const trashed = window.storageManager.getTrashed(zipCode);
            const disabled = window.storageManager.getDisabled(zipCode);
            
            this.currentArticles = this.currentArticles.filter(article => {
                const articleId = article.id?.toString();
                return !trashed.includes(articleId) && !disabled.includes(articleId);
            });
        }

        // Sort by published date (newest first)
        this.currentArticles.sort((a, b) => {
            const dateA = new Date(a.published || 0);
            const dateB = new Date(b.published || 0);
            return dateB - dateA;
        });

        // Render hero card (biggest + best image) - ONLY ONCE
        this.renderHeroCard();
        
        // Render articles grid
        this.renderArticlesGrid();
        
        // Update sidebar (trending, latest, etc.)
        this.renderSidebar();
        
        // Restore scroll position after a brief delay to prevent jumping
        requestAnimationFrame(() => {
            window.scrollTo(scrollX, scrollY);
        });
    }

    renderHeroCard() {
        const heroContainer = document.getElementById('hero-section');
        if (!heroContainer) return;
        
        // PREVENT DUPLICATE HERO CARDS - Clear container first
        heroContainer.innerHTML = '';

        // Find article with best image (highest resolution, most recent)
        // EXCLUDE top stories from hero (they go in sidebar)
        const topStories = window.storageManager ? window.storageManager.getTopStories(this.currentZip) : [];
        const topStoryIds = new Set(topStories.map(id => id.toString()));
        
        let heroArticle = null;
        let bestScore = -1;

        for (const article of this.currentArticles.slice(0, 10)) {
            // Skip if this is a top story (top stories go in sidebar, not hero)
            if (topStoryIds.has(article.id?.toString())) {
                continue;
            }
            
            if (article.image_url) {
                const score = this.scoreArticleForHero(article);
                if (score > bestScore) {
                    bestScore = score;
                    heroArticle = article;
                }
            }
        }

        // Fallback to first article if no image (but still exclude top stories)
        if (!heroArticle && this.currentArticles.length > 0) {
            for (const article of this.currentArticles) {
                if (!topStoryIds.has(article.id?.toString())) {
                    heroArticle = article;
                    break;
                }
            }
        }

        if (!heroArticle) {
            heroContainer.innerHTML = '';
            return;
        }

        const formattedDate = this.formatDate(heroArticle.published);
        // Use primary_category if available, fallback to category
        const heroCategory = heroArticle.primary_category || heroArticle.category || 'News';
        const categoryInfo = this.getCategoryInfo(heroCategory);
        const sourceGradient = this.getSourceGradient(heroArticle.source_display || heroArticle.source);
        const sourceInitials = this.getSourceInitials(heroArticle.source_display || heroArticle.source);

        // Get 2 secondary articles for right side
        const secondaryArticles = this.currentArticles
            .filter(a => a.id?.toString() !== heroArticle.id?.toString())
            .slice(0, 2);

        heroContainer.innerHTML = `
            <div class="mb-8">
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <!-- Hero Article (Left, 2 columns) -->
                    <div class="lg:col-span-2">
                        <a href="${heroArticle.url}" target="_blank" rel="noopener" class="group block">
                            <div class="bg-gray-800 rounded-lg overflow-hidden shadow-lg hover:shadow-xl transition-all duration-300">
                                ${heroArticle.image_url ? `
                                    <div class="relative h-96 overflow-hidden">
                                        <img data-src="${heroArticle.image_url}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E" alt="${heroArticle.title}" loading="lazy" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500 lazy-image">
                                        <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent"></div>
                                        <div class="absolute bottom-0 left-0 right-0 p-6">
                                            <div class="text-xs font-semibold text-blue-400 mb-2 uppercase tracking-wider">${heroArticle.source_display || heroArticle.source}</div>
                                            <h2 class="text-3xl lg:text-4xl font-bold text-white mb-3 line-clamp-3 group-hover:text-blue-300 transition-colors leading-tight">${heroArticle.title}</h2>
                                            <div class="text-sm text-gray-300">${formattedDate}</div>
                                        </div>
                                    </div>
                                ` : `
                                    <div class="relative h-96 bg-gradient-to-br ${sourceGradient} flex items-center justify-center">
                                        <div class="text-center p-6">
                                            <div class="text-xs font-semibold text-blue-200 mb-2 uppercase tracking-wider">${heroArticle.source_display || heroArticle.source}</div>
                                            <h2 class="text-3xl lg:text-4xl font-bold text-white mb-3 line-clamp-3">${heroArticle.title}</h2>
                                            <div class="text-sm text-gray-200">${formattedDate}</div>
                                        </div>
                                    </div>
                                `}
                            </div>
                        </a>
                    </div>

                    <!-- Secondary Articles (Right, 1 column) -->
                    <div class="lg:col-span-1 space-y-4">
                        ${secondaryArticles.map(article => {
                            const secDate = this.formatDate(article.published);
                            const secSourceGradient = this.getSourceGradient(article.source_display || article.source);
                            return `
                                <a href="${article.url}" target="_blank" rel="noopener" class="group block">
                                    <div class="bg-gray-800 rounded-lg overflow-hidden shadow-md hover:shadow-lg transition-all duration-300">
                                        ${article.image_url ? `
                                            <div class="relative h-48 overflow-hidden">
                                                <img data-src="${article.image_url}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E" alt="${article.title}" loading="lazy" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500 lazy-image">
                                                <div class="absolute inset-0 bg-gradient-to-t from-black/70 to-transparent"></div>
                                            </div>
                                        ` : `
                                            <div class="relative h-48 bg-gradient-to-br ${secSourceGradient} flex items-center justify-center">
                                                <div class="text-center p-4">
                                                    <div class="text-4xl font-black text-white/90 drop-shadow-lg">${this.getSourceInitials(article.source_display || article.source)}</div>
                                                </div>
                                            </div>
                                        `}
                                        <div class="p-4">
                                            <div class="text-xs font-semibold text-blue-400 mb-1">${article.source_display || article.source}</div>
                                            <h3 class="text-lg font-bold text-gray-100 mb-2 line-clamp-2 group-hover:text-blue-400 transition-colors">${article.title}</h3>
                                            <div class="text-xs text-gray-400">${secDate}</div>
                                        </div>
                                    </div>
                                </a>
                            `;
                        }).join('')}
                    </div>
                </div>
            </div>

            <!-- Top Stories Section (Below Hero) -->
            <div class="mb-8 bg-gray-800 rounded-lg p-6 border border-gray-700">
                <div class="flex items-center gap-2 mb-4">
                    <span class="text-2xl">🔥</span>
                    <h3 class="text-xl font-bold text-gray-100">Top stories</h3>
                </div>
                <div class="space-y-3">
                    ${this.getTopStoriesList().map(article => {
                        const topDate = this.formatDate(article.published);
                        return `
                            <a href="${article.url}" target="_blank" rel="noopener" class="block group hover:bg-gray-700 -mx-2 px-2 py-2 rounded transition-colors">
                                <div class="flex items-start gap-3">
                                    <div class="flex-1 min-w-0">
                                        <div class="text-sm font-semibold text-gray-100 group-hover:text-blue-400 transition-colors line-clamp-2 mb-1">${article.title}</div>
                                        <div class="text-xs text-gray-400">${article.source_display || article.source} • ${topDate}</div>
                                    </div>
                                </div>
                            </a>
                        `;
                    }).join('')}
                    ${this.getTopStoriesList().length > 0 ? `
                        <a href="#" class="text-sm text-blue-400 hover:text-blue-300 font-semibold inline-block mt-2">See more →</a>
                    ` : '<div class="text-sm text-gray-400 py-2">No top stories yet. Mark articles as top stories in admin panel.</div>'}
                </div>
            </div>
        `;

        // Trigger lazy image loading - use IntersectionObserver to prevent layout shifts and scroll jumping
        setTimeout(() => {
            const images = heroContainer.querySelectorAll('img[data-src]');
            const imageObserver = new IntersectionObserver((entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        // Prevent scroll jump by loading image without triggering layout shift
                        const tempImg = new Image();
                        tempImg.onload = () => {
                            img.src = img.dataset.src;
                            img.classList.add('loaded');
                        };
                        tempImg.src = img.dataset.src;
                        observer.unobserve(img);
                    }
                });
            }, { rootMargin: '50px' });
            images.forEach(img => imageObserver.observe(img));
        }, 100);
    }

    getTopStoriesList() {
        // CRITICAL: Must have zip code and storage manager
        if (!this.currentZip || !window.storageManager) {
            return [];
        }
        
        // Get top 5 stories (excluding hero) - CRITICAL: Always use currentZip
        const topStories = window.storageManager.getTopStories(this.currentZip);
        const topStoryIds = new Set(topStories.map(id => id.toString()));
        
        return this.currentArticles
            .filter(article => topStoryIds.has(article.id?.toString()))
            .slice(0, 5);
    }

    renderArticlesGrid() {
        const gridContainer = document.getElementById('articlesGrid');
        if (!gridContainer) return;

        // CRITICAL: Must have zip code
        if (!this.currentZip || !window.storageManager) {
            gridContainer.innerHTML = '<div class="col-span-full text-center py-12"><p class="text-gray-400">No zip code specified</p></div>';
            return;
        }

        // Get top stories to exclude from grid - CRITICAL: Always use currentZip
        const topStories = window.storageManager.getTopStories(this.currentZip);
        const topStoryIds = new Set(topStories.map(id => id.toString()));

        // Filter out hero article and top stories
        const gridArticles = this.currentArticles.filter(article => {
            const articleId = article.id?.toString();
            return !topStoryIds.has(articleId);
        }).slice(0, 30); // Limit to 30 articles

        if (gridArticles.length === 0) {
            gridContainer.innerHTML = `
                <div class="col-span-full text-center py-12">
                    <p class="text-gray-400">No articles found. Check back soon!</p>
                </div>
            `;
            return;
        }

        // Clear existing content
        gridContainer.innerHTML = '';
        
        // Create article elements
        gridArticles.forEach(article => {
            const formattedDate = this.formatDate(article.published);
            // Use primary_category if available, fallback to category
            const articleCategory = article.primary_category || article.category || 'News';
            const categoryInfo = this.getCategoryInfo(articleCategory);
            const sourceGradient = this.getSourceGradient(article.source_display || article.source);
            const sourceInitials = this.getSourceInitials(article.source_display || article.source);

            const articleHTML = `
                <article class="bg-gray-800 rounded-xl overflow-hidden shadow-lg border border-gray-700 flex flex-col h-full" data-category="${articleCategory.toLowerCase()}" data-primary-category="${articleCategory}">
                    ${article.image_url ? `
                        <div class="relative h-48 overflow-hidden bg-gradient-to-br from-gray-700 to-gray-900">
                            <img data-src="${article.image_url}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E" alt="${article.title}" loading="lazy" class="w-full h-full object-cover hover:scale-110 transition-transform duration-500 lazy-image">
                        </div>
                    ` : `
                        <div class="relative h-48 overflow-hidden bg-gradient-to-br ${sourceGradient} flex items-center justify-center">
                            <div class="absolute inset-0 opacity-10" style="background-image: repeating-linear-gradient(45deg, transparent, transparent 10px, rgba(255,255,255,0.05) 10px, rgba(255,255,255,0.05) 20px);"></div>
                            <div class="absolute bottom-0 left-0 right-0 h-16 opacity-5">
                                <svg viewBox="0 0 400 100" class="w-full h-full" preserveAspectRatio="none">
                                    <path d="M0,100 L0,80 L20,75 L40,70 L60,65 L80,60 L100,55 L120,50 L140,45 L160,50 L180,55 L200,60 L220,65 L240,70 L260,75 L280,80 L300,75 L320,70 L340,65 L360,60 L380,55 L400,50 L400,100 Z" fill="white"/>
                                </svg>
                            </div>
                            <div class="text-center relative z-10">
                                <div class="text-6xl font-black text-white/90 drop-shadow-2xl tracking-tight" style="text-shadow: 0 4px 12px rgba(0,0,0,0.3);">${sourceInitials}</div>
                                <div class="mt-2 text-xs text-white/70 uppercase tracking-widest font-bold">${(article.source_display || article.source || '').substring(0, 20)}${(article.source_display || article.source || '').length > 20 ? '...' : ''}</div>
                            </div>
                        </div>
                    `}
                    
                    <div class="p-5 flex-1 flex flex-col">
                        <div class="flex items-center gap-2 mb-3">
                            <span class="text-lg">${categoryInfo.icon}</span>
                            <span class="text-xs font-semibold uppercase tracking-wider" style="color: ${categoryInfo.color};">${categoryInfo.name}</span>
                        </div>
                        
                        <h3 class="text-lg font-bold mb-2 line-clamp-2 text-gray-100 hover:text-blue-400 transition-colors">
                            <a href="${article.url}" target="_blank" rel="noopener" class="article-title-link">${article.title}</a>
                        </h3>
                        
                        <p class="text-gray-300 text-sm mb-4 line-clamp-3 flex-1">${(article.summary || '').substring(0, 100)}...</p>
                        
                        <div class="flex items-center justify-between text-xs text-gray-500 mb-4 pt-4 border-t border-gray-700">
                            <span class="font-medium text-gray-400">${article.source_display || article.source}</span>
                            <span>${formattedDate}</span>
                        </div>
                        
                        <div class="flex items-center justify-between" style="position: relative; z-index: 1;">
                            <a href="${article.url}" target="_blank" rel="noopener" class="text-blue-400 hover:text-blue-300 text-sm font-semibold transition-colors">
                                Read more →
                            </a>
                            <div class="flex gap-2" style="position: relative; z-index: 10;">
                                <a href="https://twitter.com/intent/tweet?url=${encodeURIComponent(article.url)}&text=${encodeURIComponent(article.title)}" target="_blank" rel="noopener" class="text-gray-500 hover:text-blue-400 transition-colors" title="Share on Twitter">🐦</a>
                                <a href="https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(article.url)}" target="_blank" rel="noopener" class="text-gray-500 hover:text-blue-600 transition-colors" title="Share on Facebook">📘</a>
                                <button type="button" data-copy-url="${this.escapeHtml(article.url)}" class="copy-link-btn text-gray-500 hover:text-green-400 transition-colors cursor-pointer border-none bg-transparent p-0 m-0" style="pointer-events: auto !important; z-index: 100 !important; position: relative !important; cursor: pointer !important;" title="Copy link">🔗</button>
                            </div>
                        </div>
                    </div>
                </article>
            `;
            
            // Create element and append
            const articleDiv = document.createElement('div');
            articleDiv.innerHTML = articleHTML;
            const articleElement = articleDiv.firstElementChild;
            gridContainer.appendChild(articleElement);
            
            // Attach click handler directly to the copy button AFTER it's in the DOM
            const copyBtn = articleElement.querySelector('.copy-link-btn');
            if (copyBtn) {
                const articleUrl = article.url;
                
                // Helper function for fallback copy (defined here to have access to articleUrl)
                const fallbackCopyText = (url, button) => {
                    const textArea = document.createElement('textarea');
                    textArea.value = url;
                    textArea.style.position = 'fixed';
                    textArea.style.left = '-999999px';
                    textArea.style.top = '-999999px';
                    document.body.appendChild(textArea);
                    textArea.focus();
                    textArea.select();
                    try {
                        document.execCommand('copy');
                        button.textContent = '✓';
                        button.style.color = '#4caf50';
                        setTimeout(() => {
                            button.textContent = '🔗';
                            button.style.color = '';
                        }, 2000);
                    } catch (err) {
                        console.error('Fallback copy failed:', err);
                    }
                    document.body.removeChild(textArea);
                };
                
                // Use onclick as a fallback - this will definitely work
                copyBtn.onclick = function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    
                    const url = this.dataset.copyUrl || articleUrl;
                    
                    console.log('Copy button clicked, URL:', url);
                    
                    if (!url) {
                        console.warn('Copy button has no URL');
                        return false;
                    }
                    
                    // Try to use the global function first
                    if (window.copyArticleLink && typeof window.copyArticleLink === 'function') {
                        try {
                            window.copyArticleLink(url, this);
                            return false;
                        } catch (err) {
                            console.error('Error calling copyArticleLink:', err);
                        }
                    }
                    
                    // Fallback: use clipboard API
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(url).then(() => {
                            const originalText = this.textContent;
                            this.textContent = '✓';
                            this.style.color = '#4caf50';
                            setTimeout(() => {
                                this.textContent = originalText;
                                this.style.color = '';
                            }, 2000);
                        }).catch(err => {
                            console.error('Failed to copy:', err);
                            fallbackCopyText(url, this);
                        });
                    } else {
                        fallbackCopyText(url, this);
                    }
                    
                    return false;
                };
                
                // Also add event listener as backup
                copyBtn.addEventListener('click', function(e) {
                    console.log('Event listener also fired');
                }, true);
            } else {
                console.warn('Copy button not found in article element');
            }
        });

        // Trigger lazy image loading
        setTimeout(() => {
            const images = gridContainer.querySelectorAll('img[data-src]');
            const imageObserver = new IntersectionObserver((entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        img.src = img.dataset.src;
                        img.classList.add('loaded');
                        observer.unobserve(img);
                    }
                });
            });
            images.forEach(img => imageObserver.observe(img));
        }, 100);

    }

    renderSidebar() {
        const sidebar = document.querySelector('aside.lg\\:col-span-3');
        if (!sidebar) {
            // Try alternative selector
            const altSidebar = document.querySelector('.lg\\:col-span-3');
            if (altSidebar) {
                this.renderSidebarContent(altSidebar);
            }
            return;
        }
        this.renderSidebarContent(sidebar);
    }

    renderSidebarContent(sidebar) {
        // CRITICAL: Always use currentZip - never use any other zip
        if (!this.currentZip || !window.storageManager) return;
        
        // Get top stories for sidebar - CRITICAL: Always use currentZip
        const topStories = window.storageManager.getTopStories(this.currentZip);
        const topStoryIds = new Set(topStories.map(id => id.toString()));
        
        // Get top stories articles (excluding hero)
        const topStoriesArticles = this.currentArticles
            .filter(article => topStoryIds.has(article.id?.toString()))
            .slice(0, 5);

        // Get trending articles (recent with high engagement)
        const trendingArticles = this.getTrendingArticles().slice(0, 5);

        // Get latest stories (most recent, excluding top stories)
        const latestStories = this.currentArticles
            .filter(article => !topStoryIds.has(article.id?.toString()))
            .slice(0, 5);

        // Get entertainment articles
        const entertainmentArticles = this.currentArticles
            .filter(article => {
                const cat = article.primary_category || article.category || 'News';
                return cat.toLowerCase() === 'entertainment';
            })
            .slice(0, 10);

        sidebar.innerHTML = `
            ${topStoriesArticles.length > 0 ? `
                <div class="bg-gray-800 rounded-xl p-5 border border-gray-700">
                    <div class="flex items-center gap-2 mb-4">
                        <span class="text-xl">🔥</span>
                        <h3 class="text-lg font-bold text-gray-100">Top Stories</h3>
                    </div>
                    <div class="space-y-4">
                        ${topStoriesArticles.map(article => {
                            const formattedDate = this.formatDate(article.published);
                            const sourceGradient = this.getSourceGradient(article.source_display || article.source);
                            const sourceInitials = this.getSourceInitials(article.source_display || article.source);
                            return `
                                <a href="${article.url}" target="_blank" rel="noopener" class="block group">
                                    <div class="flex gap-3 pb-4 border-b border-gray-700 last:border-0 hover:bg-gray-750 -mx-2 px-2 rounded-lg transition-colors">
                                        ${article.image_url ? `
                                            <div class="flex-shrink-0 w-20 h-20 rounded-lg overflow-hidden bg-gradient-to-br from-gray-700 to-gray-900">
                                                <img data-src="${article.image_url}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E" alt="${article.title}" loading="lazy" class="w-full h-full object-cover group-hover:scale-110 transition-transform duration-300 lazy-image">
                                            </div>
                                        ` : `
                                            <div class="flex-shrink-0 w-20 h-20 rounded-lg bg-gradient-to-br ${sourceGradient} flex items-center justify-center relative overflow-hidden">
                                                <div class="absolute inset-0 opacity-10" style="background-image: repeating-linear-gradient(45deg, transparent, transparent 5px, rgba(255,255,255,0.05) 5px, rgba(255,255,255,0.05) 10px);"></div>
                                                <div class="text-xl font-black text-white/90 drop-shadow-lg relative z-10">${sourceInitials}</div>
                                            </div>
                                        `}
                                        <div class="flex-1 min-w-0">
                                            <h4 class="text-sm font-semibold text-gray-100 group-hover:text-blue-400 transition-colors line-clamp-2 mb-1">${article.title}</h4>
                                            <div class="text-xs text-gray-500">${article.source_display || article.source}</div>
                                        </div>
                                    </div>
                                </a>
                            `;
                        }).join('')}
                    </div>
                </div>
            ` : ''}
            
            ${trendingArticles.length > 0 ? `
                <div class="bg-gray-800 rounded-xl p-5 border border-gray-700">
                    <div class="flex items-center gap-2 mb-4">
                        <span class="text-xl">📈</span>
                        <h3 class="text-lg font-bold text-gray-100">Trending Now</h3>
                    </div>
                    <div class="space-y-3">
                        ${trendingArticles.map(article => {
                            const formattedDate = this.formatDate(article.published);
                            return `
                                <a href="${article.url}" target="_blank" rel="noopener" class="block group">
                                    <div class="flex items-start gap-2 pb-3 border-b border-gray-700 last:border-0 hover:bg-gray-750 -mx-2 px-2 rounded-lg transition-colors">
                                        <span class="text-lg flex-shrink-0">🔥</span>
                                        <div class="flex-1 min-w-0">
                                            <div class="text-xs text-gray-500 mb-1">${article.source_display || article.source} • ${formattedDate}</div>
                                            <h4 class="text-sm font-semibold text-gray-100 group-hover:text-orange-400 transition-colors line-clamp-2">${article.title}</h4>
                                        </div>
                                    </div>
                                </a>
                            `;
                        }).join('')}
                    </div>
                </div>
            ` : ''}
            
            ${latestStories.length > 0 ? `
                <div class="bg-gray-800 rounded-xl p-5 border border-gray-700">
                    <div class="flex items-center gap-2 mb-4">
                        <span class="text-xl">🕐</span>
                        <h3 class="text-lg font-bold text-gray-100">Latest</h3>
                    </div>
                    <div class="space-y-3">
                        ${latestStories.map(article => {
                            const formattedDate = this.formatDate(article.published);
                            return `
                                <a href="${article.url}" target="_blank" rel="noopener" class="block group">
                                    <div class="flex items-start gap-2 pb-3 border-b border-gray-700 last:border-0 hover:bg-gray-750 -mx-2 px-2 rounded-lg transition-colors">
                                        <span class="text-lg flex-shrink-0">🕐</span>
                                        <div class="flex-1 min-w-0">
                                            <div class="text-xs text-gray-500 mb-1">${article.source_display || article.source} • ${formattedDate}</div>
                                            <h4 class="text-sm font-semibold text-gray-100 group-hover:text-blue-400 transition-colors line-clamp-2">${article.title}</h4>
                                        </div>
                                    </div>
                                </a>
                            `;
                        }).join('')}
                    </div>
                </div>
            ` : ''}
            
            ${entertainmentArticles.length > 0 ? `
                <div class="bg-gray-800 rounded-xl p-5 border border-gray-700">
                    <h3 class="text-lg font-bold text-gray-100 mb-4">Entertainment</h3>
                    <div class="space-y-3">
                        ${entertainmentArticles.map(article => {
                            const formattedDate = this.formatDate(article.published);
                            return `
                                <a href="${article.url}" target="_blank" rel="noopener" class="block group">
                                    <div class="pb-3 border-b border-gray-700 last:border-0 hover:bg-gray-750 -mx-2 px-2 rounded-lg transition-colors">
                                        <div class="text-xs text-gray-500 mb-1">${article.source_display || article.source} - ${formattedDate}</div>
                                        <h4 class="text-sm font-semibold text-gray-100 group-hover:text-purple-400 transition-colors line-clamp-2">${article.title}</h4>
                                    </div>
                                </a>
                            `;
                        }).join('')}
                    </div>
                </div>
            ` : ''}
        `;

        // Trigger lazy image loading for sidebar images
        setTimeout(() => {
            const images = sidebar.querySelectorAll('img[data-src]');
            const imageObserver = new IntersectionObserver((entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        img.src = img.dataset.src;
                        img.classList.add('loaded');
                        observer.unobserve(img);
                    }
                });
            });
            images.forEach(img => imageObserver.observe(img));
        }, 100);
    }

    getTrendingArticles() {
        // CRITICAL: Must have zip code
        if (!this.currentZip || !window.storageManager) {
            return [];
        }
        
        // Get articles from last 7 days, sorted by recency and relevance
        const sevenDaysAgo = new Date();
        sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
        
        const trending = this.currentArticles
            .filter(article => {
                if (!article.published) return false;
                const pubDate = new Date(article.published);
                return pubDate >= sevenDaysAgo;
            })
            .map(article => {
                // Calculate trending score
                const daysOld = (Date.now() - new Date(article.published || 0)) / (1000 * 60 * 60 * 24);
                let score = 0;
                
                if (daysOld < 1) score += 100;
                else if (daysOld < 3) score += 50;
                else if (daysOld < 7) score += 25;
                
                // Boost if marked as good fit - CRITICAL: Always use currentZip
                const goodFit = window.storageManager.getGoodFitArticles(this.currentZip);
                if (goodFit.includes(article.id?.toString())) {
                    score += 30;
                }
                
                article._trendingScore = score;
                return article;
            })
            .sort((a, b) => b._trendingScore - a._trendingScore);
        
        return trending;
    }

    scoreArticleForHero(article) {
        let score = 0;
        
        // Prefer recent articles
        const daysOld = (Date.now() - new Date(article.published || 0)) / (1000 * 60 * 60 * 24);
        if (daysOld < 1) score += 100;
        else if (daysOld < 3) score += 50;
        else if (daysOld < 7) score += 25;
        
        // Prefer articles with images
        if (article.image_url) score += 50;
        
        // Prefer news category
        if (article.category === 'news') score += 20;
        
        return score;
    }

    formatDate(dateString) {
        if (!dateString) return 'Recently';
        try {
            const date = new Date(dateString);
            const now = new Date();
            const diffMs = now - date;
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);
            
            if (diffMins < 1) return 'Just now';
            if (diffMins < 60) return `${diffMins}m ago`;
            if (diffHours < 24) return `${diffHours}h ago`;
            if (diffDays < 7) return `${diffDays}d ago`;
            
            return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        } catch (error) {
            return 'Recently';
        }
    }

    filterByCategory(articles, category) {
        if (!category || category === 'all') {
            return articles;
        }
        
        // Map tab names to primary_category values (case-insensitive)
        const categoryMap = {
            'news': 'News',
            'crime': 'Crime',
            'sports': 'Sports',
            'entertainment': 'Entertainment',
            'events': 'Events',
            'politics': 'Politics',
            'schools': 'Schools',
            'business': 'Business',
            'health': 'Health',
            'traffic': 'Traffic'
        };
        
        const targetCategory = categoryMap[category.toLowerCase()] || category;
        
        return articles.filter(article => {
            // Use primary_category if available, fallback to category
            const articleCategory = article.primary_category || article.category || 'News';
            return articleCategory.toLowerCase() === targetCategory.toLowerCase();
        });
    }
    
    getCategoryInfo(category) {
        // Normalize category name (handle both old and new category names)
        const normalized = (category || '').toLowerCase();
        
        const categories = {
            news: { name: 'News', icon: '📰', color: '#1e88e5' },
            crime: { name: 'Crime', icon: '🚨', color: '#d32f2f' },
            sports: { name: 'Sports', icon: '⚽', color: '#00acc1' },
            entertainment: { name: 'Entertainment', icon: '🎬', color: '#8e24aa' },
            events: { name: 'Events', icon: '📅', color: '#5e35b1' },
            politics: { name: 'Politics', icon: '🏛️', color: '#1976d2' },
            schools: { name: 'Schools', icon: '🎓', color: '#388e3c' },
            business: { name: 'Business', icon: '💼', color: '#f57c00' },
            health: { name: 'Health', icon: '🏥', color: '#c2185b' },
            traffic: { name: 'Traffic', icon: '🚦', color: '#fbc02d' },
            fire: { name: 'Fire', icon: '🔥', color: '#ff5722' },
            // Legacy categories for backward compatibility
            local: { name: 'Local', icon: '📍', color: '#f57c00' },
            media: { name: 'Media', icon: '🎥', color: '#c2185b' }
        };
        return categories[normalized] || categories.news;
    }

    getSourceGradient(source) {
        if (!source) return 'from-blue-600 to-purple-700';
        
        const sourceLower = source.toLowerCase();
        if (sourceLower.includes('fall river reporter') || sourceLower.includes('fallriverreporter')) {
            return 'from-purple-600 to-blue-700';
        }
        if (sourceLower.includes('herald news')) {
            return 'from-red-600 to-black';
        }
        if (sourceLower.includes('fun107') || sourceLower.includes('fun 107')) {
            return 'from-orange-500 to-yellow-500';
        }
        if (sourceLower.includes('wpri')) {
            return 'from-cyan-600 to-blue-700';
        }
        
        // Default gradient based on hash
        let hash = 0;
        for (let i = 0; i < source.length; i++) {
            hash = source.charCodeAt(i) + ((hash << 5) - hash);
        }
        const gradients = [
            'from-blue-600 to-indigo-700',
            'from-indigo-600 to-purple-700',
            'from-purple-600 to-pink-700',
            'from-cyan-600 to-blue-700',
            'from-emerald-600 to-teal-700',
            'from-violet-600 to-purple-700'
        ];
        return gradients[Math.abs(hash) % gradients.length];
    }

    getSourceInitials(source) {
        if (!source) return 'FR';
        
        const sourceLower = source.toLowerCase();
        if (sourceLower.includes('fall river reporter') || sourceLower.includes('fallriverreporter')) {
            return 'FR';
        }
        if (sourceLower.includes('herald news')) {
            return 'HN';
        }
        if (sourceLower.includes('fun107') || sourceLower.includes('fun 107')) {
            return '107';
        }
        if (sourceLower.includes('wpri')) {
            return 'WP';
        }
        
        // Extract first letters
        const words = source.split(' ');
        if (words.length >= 2) {
            return (words[0][0] + words[1][0]).toUpperCase();
        }
        return source.substring(0, 2).toUpperCase();
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize article renderer
let articleRenderer;
if (typeof window !== 'undefined') {
    try {
        articleRenderer = new ArticleRenderer();
        window.articleRenderer = articleRenderer;
    } catch (error) {
        console.error('Failed to initialize ArticleRenderer:', error);
    }
}

