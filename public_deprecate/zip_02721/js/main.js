document.addEventListener('DOMContentLoaded', function() {
    // Lazy load images using Intersection Observer
    if ('IntersectionObserver' in window) {
        const imageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    if (img.dataset.src) {
                        img.src = img.dataset.src;
                        img.removeAttribute('data-src');
                        observer.unobserve(img);
                    }
                }
            });
        }, {
            rootMargin: '50px' // Start loading 50px before image enters viewport
        });
        
        // Observe all images with data-src
        document.querySelectorAll('img[data-src]').forEach(img => {
            imageObserver.observe(img);
        });
    } else {
        // Fallback for browsers without IntersectionObserver
        document.querySelectorAll('img[data-src]').forEach(img => {
            img.src = img.dataset.src;
            img.removeAttribute('data-src');
        });
    }
    
    // Progressive article loading - show first 20, load more on scroll
    const articlesGrid = document.getElementById('articlesGrid');
    if (articlesGrid) {
        const allArticles = Array.from(articlesGrid.querySelectorAll('.article-tile'));
        const initialCount = 20;
        let visibleCount = initialCount;
        
        // Hide articles beyond initial count
        allArticles.forEach((article, index) => {
            if (index >= initialCount) {
                article.style.display = 'none';
                article.classList.add('lazy-article');
            }
        });
        
        // Show "Load More" button if there are more articles
        if (allArticles.length > initialCount) {
            const loadMoreBtn = document.createElement('button');
            loadMoreBtn.textContent = 'Load More Articles';
            loadMoreBtn.className = 'load-more-btn';
            loadMoreBtn.style.cssText = 'display: block; margin: 2rem auto; padding: 1rem 2rem; background: #1e88e5; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1rem; font-weight: 600;';
            loadMoreBtn.addEventListener('click', function() {
                const toShow = Math.min(visibleCount + 10, allArticles.length);
                for (let i = visibleCount; i < toShow; i++) {
                    allArticles[i].style.display = '';
                }
                visibleCount = toShow;
                
                if (visibleCount >= allArticles.length) {
                    this.style.display = 'none';
                }
            });
            articlesGrid.parentNode.appendChild(loadMoreBtn);
        }
        
        // Infinite scroll (optional - uncomment to enable)
        /*
        let loading = false;
        window.addEventListener('scroll', function() {
            if (loading) return;
            
            if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 1000) {
                loading = true;
                const toShow = Math.min(visibleCount + 10, allArticles.length);
                for (let i = visibleCount; i < toShow; i++) {
                    allArticles[i].style.display = '';
                }
                visibleCount = toShow;
                loading = false;
            }
        });
        */
    }
    
    // Navigation tab switching
    const navTabs = document.querySelectorAll('.nav-tab[data-tab]');
    const allTiles = document.querySelectorAll('.tile[data-category]');
    const featuredTile = document.querySelector('.featured-tile');
    
    navTabs.forEach(tab => {
        tab.addEventListener('click', function(e) {
            e.preventDefault();
            navTabs.forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            
            const targetTab = this.dataset.tab;
            
            // Show/hide featured tile
            if (featuredTile) {
                if (targetTab === 'all' || targetTab === 'news' || !targetTab || featuredTile.dataset.category === targetTab) {
                    featuredTile.style.display = '';
                } else {
                    featuredTile.style.display = 'none';
                }
            }
            
            // Filter articles in grid
            if (articlesGrid) {
                const articleTiles = articlesGrid.querySelectorAll('.article-tile');
                articleTiles.forEach(tile => {
                    const tileCategory = tile.dataset.category;
                    if (targetTab === 'all' || !targetTab) {
                        tile.style.display = '';
                    } else if (tileCategory === targetTab) {
                        tile.style.display = '';
                    } else {
                        tile.style.display = 'none';
                    }
                });
            }
            
            // Also filter all tiles (for featured tile)
            allTiles.forEach(tile => {
                const tileCategory = tile.dataset.category;
                if (targetTab === 'all' || !targetTab) {
                    tile.style.display = '';
                } else if (tileCategory === targetTab) {
                    tile.style.display = '';
                } else {
                    tile.style.display = 'none';
                }
            });
        });
    });
    
    // Related articles toggle function
    function toggleRelated(button) {
        const list = button.nextElementSibling;
        if (list.style.display === 'none') {
            list.style.display = 'block';
            button.textContent = button.textContent.replace('📎', '📌');
        } else {
            list.style.display = 'none';
            button.textContent = button.textContent.replace('📌', '📎');
        }
    }
    window.toggleRelated = toggleRelated;
    
    // Advanced search filters
    function toggleSearchFilters() {
        const filters = document.getElementById('searchFilters');
        if (filters) {
            filters.style.display = filters.style.display === 'none' ? 'block' : 'none';
        }
    }
    window.toggleSearchFilters = toggleSearchFilters;
    
    function clearFilters() {
        document.getElementById('searchInput').value = '';
        document.getElementById('filterCategory').value = '';
        document.getElementById('filterNeighborhood').value = '';
        document.getElementById('filterSource').value = '';
        document.getElementById('filterDateRange').value = '';
        performSearch();
    }
    window.clearFilters = clearFilters;
    
    // Populate source filter dropdown (if not already populated from template)
    function populateSourceFilter() {
        const sourceSelect = document.getElementById('filterSource');
        // If dropdown already has options (from template), skip population
        if (sourceSelect && sourceSelect.options.length > 1) {
            return;
        }
        if (!sourceSelect) return;
        
        const sources = new Set();
        document.querySelectorAll('.tile-source').forEach(el => {
            const sourceText = el.textContent.split(' - ')[0].trim();
            if (sourceText) sources.add(sourceText);
        });
        
        sources.forEach(source => {
            const option = document.createElement('option');
            option.value = source;
            option.textContent = source;
            sourceSelect.appendChild(option);
        });
    }
    
    function performSearch() {
        const searchTerm = (document.getElementById('searchInput')?.value || '').toLowerCase();
        const categoryFilter = document.getElementById('filterCategory')?.value || '';
        const neighborhoodFilter = document.getElementById('filterNeighborhood')?.value || '';
        const sourceFilter = document.getElementById('filterSource')?.value || '';
        const dateRangeFilter = document.getElementById('filterDateRange')?.value || '';
        
        const allTiles = document.querySelectorAll('.article-tile, .featured-tile');
        let visibleCount = 0;
        
        allTiles.forEach(tile => {
            let matches = true;
            
            // Text search
            if (searchTerm.length >= 2) {
                const title = tile.querySelector('.tile-title, .tile-title-small')?.textContent.toLowerCase() || '';
                const summary = tile.querySelector('.tile-summary, .tile-summary-small')?.textContent.toLowerCase() || '';
                if (!title.includes(searchTerm) && !summary.includes(searchTerm)) {
                    matches = false;
                }
            }
            
            // Category filter
            if (categoryFilter && matches) {
                const tileCategory = tile.dataset.category || '';
                if (tileCategory !== categoryFilter) {
                    matches = false;
                }
            }
            
            // Neighborhood filter
            if (neighborhoodFilter && matches) {
                const neighborhoods = tile.dataset.neighborhoods || '';
                if (!neighborhoods.includes(neighborhoodFilter)) {
                    matches = false;
                }
            }
            
            // Source filter
            if (sourceFilter && matches) {
                const sourceEl = tile.querySelector('.tile-source');
                if (sourceEl) {
                    const sourceText = sourceEl.textContent.split(' - ')[0].trim();
                    if (sourceText !== sourceFilter) {
                        matches = false;
                    }
                }
            }
            
            // Date range filter
            if (dateRangeFilter && matches) {
                const sourceEl = tile.querySelector('.tile-source');
                if (sourceEl) {
                    const dateText = sourceEl.textContent;
                    const now = new Date();
                    let cutoffDate = null;
                    
                    if (dateRangeFilter === 'today') {
                        cutoffDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                    } else if (dateRangeFilter === 'week') {
                        cutoffDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
                    } else if (dateRangeFilter === 'month') {
                        cutoffDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
                    }
                    
                    // Simple date check - if date text doesn't contain today's date or recent dates, hide
                    // This is a simplified check; full implementation would parse dates properly
                    if (cutoffDate && !dateText.includes(now.getMonth() + 1 + '/' + now.getDate())) {
                        // Could be improved with proper date parsing
                    }
                }
            }
            
            if (matches) {
                tile.style.display = '';
                if (searchTerm.length >= 2) {
                    tile.style.border = '2px solid #1e88e5';
                } else {
                    tile.style.border = '';
                }
                visibleCount++;
            } else {
                tile.style.display = 'none';
                tile.style.border = '';
            }
        });
        
        // Show message if no results
        const articlesGrid = document.getElementById('articlesGrid');
        if (articlesGrid) {
            let noResultsMsg = articlesGrid.querySelector('.no-results-message');
            if (visibleCount === 0 && (searchTerm || categoryFilter || neighborhoodFilter || sourceFilter || dateRangeFilter)) {
                if (!noResultsMsg) {
                    noResultsMsg = document.createElement('div');
                    noResultsMsg.className = 'no-results-message';
                    noResultsMsg.style.cssText = 'text-align:center; padding:3rem; color:#888;';
                    noResultsMsg.textContent = 'No articles found matching your search criteria.';
                    articlesGrid.appendChild(noResultsMsg);
                }
                noResultsMsg.style.display = 'block';
            } else if (noResultsMsg) {
                noResultsMsg.style.display = 'none';
            }
        }
    }
    
    // Enhanced search with filters
    const searchInput = document.getElementById('searchInput');
    const filterCategory = document.getElementById('filterCategory');
    const filterSource = document.getElementById('filterSource');
    const filterDateRange = document.getElementById('filterDateRange');
    
    let searchTimeout;
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(performSearch, 300);
        });
        
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                clearTimeout(searchTimeout);
                performSearch();
            }
        });
    }
    
    if (filterCategory) {
        filterCategory.addEventListener('change', performSearch);
    }
    const filterNeighborhood = document.getElementById('filterNeighborhood');
    if (filterNeighborhood) {
        filterNeighborhood.addEventListener('change', performSearch);
    }
    if (filterSource) {
        filterSource.addEventListener('change', performSearch);
    }
    if (filterDateRange) {
        filterDateRange.addEventListener('change', performSearch);
    }
    
    // Populate source filter on page load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', populateSourceFilter);
    } else {
        populateSourceFilter();
    }
    
    // Back to top button
    const backToTopBtn = document.getElementById('backToTop');
    if (backToTopBtn) {
        window.addEventListener('scroll', function() {
            if (window.pageYOffset > 300) {
                backToTopBtn.classList.add('show');
            } else {
                backToTopBtn.classList.remove('show');
            }
        });
    }
    
    function scrollToTop() {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    }
    window.scrollToTop = scrollToTop;
    
    // Set active mobile nav item based on current page
    const currentPath = window.location.pathname;
    document.querySelectorAll('.mobile-nav-item').forEach(item => {
        const href = item.getAttribute('href');
        if (currentPath.includes(href) || (currentPath === '/' && href === 'index.html')) {
            item.classList.add('active');
        }
    });
    
    // Newsletter signup
    function handleNewsletterSignup(event) {
        event.preventDefault();
        const email = document.getElementById('newsletterEmail').value;
        const messageEl = document.getElementById('newsletterMessage');
        
        // Store in localStorage for now (can be sent to server later)
        const subscribers = JSON.parse(localStorage.getItem('newsletter_subscribers') || '[]');
        if (!subscribers.includes(email)) {
            subscribers.push(email);
            localStorage.setItem('newsletter_subscribers', JSON.stringify(subscribers));
            messageEl.textContent = '✓ Thank you for subscribing!';
            messageEl.style.color = '#4caf50';
            document.getElementById('newsletterEmail').value = '';
        } else {
            messageEl.textContent = 'You are already subscribed.';
            messageEl.style.color = '#ff9800';
        }
        
        setTimeout(() => {
            messageEl.textContent = '';
        }, 5000);
    }
    window.handleNewsletterSignup = handleNewsletterSignup;
    
    // Copy article link function
    function copyArticleLink(url, button) {
        navigator.clipboard.writeText(url).then(() => {
            const originalText = button.textContent;
            button.textContent = '✓';
            button.style.color = '#4caf50';
            setTimeout(() => {
                button.textContent = originalText;
                button.style.color = '';
            }, 2000);
        }).catch(err => {
            console.error('Failed to copy:', err);
            // Fallback: select text
            const textArea = document.createElement('textarea');
            textArea.value = url;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            button.textContent = '✓';
            setTimeout(() => {
                button.textContent = '🔗';
            }, 2000);
        });
    }
    window.copyArticleLink = copyArticleLink;
    
    
    // Top Stories Slider
    let currentTopStorySlide = 0;
    const topStoriesTrack = document.querySelector('.top-stories-track');
    const topStoriesSlides = document.querySelectorAll('.story-slide');
    const topStoriesDots = document.querySelectorAll('.slider-dots .dot');
    
    function updateTopStoriesSlider() {
        if (topStoriesTrack && topStoriesSlides.length > 0) {
            topStoriesTrack.style.transform = `translateX(-${currentTopStorySlide * 100}%)`;
            
            // Update dots
            topStoriesDots.forEach((dot, index) => {
                dot.classList.toggle('active', index === currentTopStorySlide);
            });
        }
    }
    
    function nextTopStory() {
        if (!topStoriesSlides || topStoriesSlides.length === 0) return;
        currentTopStorySlide = (currentTopStorySlide + 1) % topStoriesSlides.length;
        updateTopStoriesSlider();
    }
    window.nextTopStory = nextTopStory;
    
    function prevTopStory() {
        if (!topStoriesSlides || topStoriesSlides.length === 0) return;
        currentTopStorySlide = (currentTopStorySlide - 1 + topStoriesSlides.length) % topStoriesSlides.length;
        updateTopStoriesSlider();
    }
    window.prevTopStory = prevTopStory;
    
    function goToTopStory(index) {
        if (!topStoriesSlides || index < 0 || index >= topStoriesSlides.length) return;
        currentTopStorySlide = index;
        updateTopStoriesSlider();
    }
    window.goToTopStory = goToTopStory;
    
    // Auto-advance slider every 5 seconds
    if (topStoriesSlides && topStoriesSlides.length > 1) {
        setInterval(() => {
            nextTopStory();
        }, 5000);
    }
});