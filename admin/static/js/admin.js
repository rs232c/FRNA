/**
 * Admin Panel JavaScript
 * All button handlers and event delegation
 */

console.log('Admin script starting to load...');

// Utility functions for escaping
function escapeHtml(unsafe) {
    if (!unsafe) return '';
    var str = String(unsafe);
    str = str.split('&').join('&amp;');
    str = str.split('<').join('&lt;');
    str = str.split('>').join('&gt;');
    str = str.split('"').join('&quot;');
    str = str.split("'").join('&#039;');
    return str;
}

function escapeAttr(unsafe) {
    if (!unsafe) return '';
    var str = String(unsafe);
    str = str.split('&').join('&amp;');
    str = str.split('"').join('&quot;');
    str = str.split("'").join('&#x27;');
    str = str.split('<').join('&lt;');
    str = str.split('>').join('&gt;');
    return str;
}

// Extract zip code from URL
function getZipCodeFromUrl() {
    const pathParts = window.location.pathname.split('/');
    if (pathParts.length >= 3 && pathParts[1] === 'admin' && pathParts[2] && pathParts[2].length === 5) {
        let isAllDigits = true;
        for (let i = 0; i < pathParts[2].length; i++) {
            if (pathParts[2].charAt(i) < '0' || pathParts[2].charAt(i) > '9') {
                isAllDigits = false;
                break;
            }
        }
        if (isAllDigits) {
            return pathParts[2];
        }
    }
    return null;
}

// Button handler functions - make globally available
(function() {
    try {
        // Reject article
        function rejectArticle(articleId) {
            console.log('Rejecting article:', articleId);
            if (!articleId) {
                alert('Error: Article ID is missing');
                return;
            }
            
            const zipCode = getZipCodeFromUrl();
            
            // Create custom confirmation dialog
            let confirmModal = document.getElementById('trashConfirmModal');
            if (!confirmModal) {
                confirmModal = document.createElement('div');
                confirmModal.id = 'trashConfirmModal';
                confirmModal.className = 'modal';
                confirmModal.style.display = 'none';
                confirmModal.innerHTML = `
                    <div class="modal-content" style="max-width: 400px;">
                        <div class="modal-header">
                            <h2>Move to Trash?</h2>
                            <span class="close-modal" onclick="closeTrashConfirmModal()">&times;</span>
                        </div>
                        <div style="padding: 1.5rem;">
                            <p style="margin-bottom: 1.5rem; color: #e0e0e0;">This article will be hidden from the website.</p>
                            <div style="display: flex; gap: 0.75rem; justify-content: flex-end;">
                                <button type="button" onclick="closeTrashConfirmModal()" style="padding: 0.75rem 1.5rem; background: #666; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Cancel</button>
                                <button type="button" id="trashConfirmStay" style="padding: 0.75rem 1.5rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Stay on Page</button>
                                <button type="button" id="trashConfirmGo" style="padding: 0.75rem 1.5rem; background: #d32f2f; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Go to Trash</button>
                            </div>
                        </div>
                    </div>
                `;
                document.body.appendChild(confirmModal);
            }
            
            // Show modal
            confirmModal.style.display = 'block';
            
            // Remove old event listeners by cloning
            const newModal = confirmModal.cloneNode(true);
            confirmModal.parentNode.replaceChild(newModal, confirmModal);
            confirmModal = newModal;
            
            // Add event listeners
            function closeTrashConfirmModal() {
                confirmModal.style.display = 'none';
            }
            window.closeTrashConfirmModal = closeTrashConfirmModal;
            
            // Handle clicking outside modal
            confirmModal.addEventListener('click', function(e) {
                if (e.target === confirmModal) {
                    closeTrashConfirmModal();
                }
            });
            
            // Handle reject action
            function performReject(goToTrash) {
                const requestBody = {
                    article_id: articleId,
                    rejected: true
                };
                
                if (zipCode) {
                    requestBody.zip_code = zipCode;
                }
                
                fetch('/admin/api/reject-article', {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    credentials: "same-origin",
                    body: JSON.stringify(requestBody)
                })
                .then(r => {
                    if (!r.ok) {
                        if (r.status === 401) {
                            throw new Error('Not authenticated. Please log in again.');
                        }
                        throw new Error('HTTP ' + r.status + ': ' + r.statusText);
                    }
                    return r.json();
                })
                .then(data => {
                    if (data && data.success) {
                        closeTrashConfirmModal();
                        if (goToTrash) {
                            if (zipCode) {
                                window.location.href = `/admin/${zipCode}/trash`;
                            } else {
                                window.location.href = '/admin/trash';
                            }
                        } else {
                            // Stay on page - reload to show updated state
                            location.reload();
                        }
                    } else {
                        alert('Error rejecting article: ' + (data ? data.message : 'Unknown error'));
                    }
                })
                .catch(e => {
                    console.error('Error rejecting article:', e);
                    alert('Error: ' + (e.message || 'Failed to reject article. Please try again.'));
                });
            }
            
            document.getElementById('trashConfirmGo').addEventListener('click', () => performReject(true));
            document.getElementById('trashConfirmStay').addEventListener('click', () => performReject(false));
        }
        window.rejectArticle = rejectArticle;
        
        // Toggle top story
        function toggleTopStory(articleId) {
            console.log('toggleTopStory called with articleId:', articleId);
            const button = document.querySelector(`.top-story-btn[data-id="${articleId}"]`);
            const goodFitButton = document.querySelector(`.good-fit-btn[data-id="${articleId}"]`);
            if (!button) {
                console.error('Button not found for articleId:', articleId);
                return;
            }
            const isCurrentlyTop = button.getAttribute('data-state') === 'on' || (button.style.background && button.style.background.includes('#ff9800'));
            const newState = !isCurrentlyTop;
            
            const zipCode = getZipCodeFromUrl();
            const requestBody = {id: articleId, is_top_story: newState};
            if (zipCode) {
                requestBody.zip_code = zipCode;
            }
            
            fetch('/admin/api/top-story', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify(requestBody)
            })
            .then(r => {
                if (!r.ok) {
                    if (r.status === 401) {
                        throw new Error('Not authenticated. Please log in again.');
                    }
                    throw new Error(`HTTP ${r.status}: ${r.statusText}`);
                }
                return r.json();
            })
            .then(data => {
                if (data && data.success) {
                    if (button) {
                        if (newState) {
                            button.style.background = '#ff9800';
                            button.style.border = 'none';
                            button.style.borderRadius = '50%';
                            button.style.opacity = '1';
                            button.setAttribute('data-state', 'on');
                            // Top hat and thumbs up can both be on - no mutual exclusion
                        } else {
                            button.style.background = 'transparent';
                            button.style.border = 'none';
                            button.style.opacity = '0.5';
                            button.setAttribute('data-state', 'off');
                        }
                    }
                    setTimeout(() => location.reload(), 300);
                } else {
                    alert('Error toggling top story: ' + (data ? data.message : 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error toggling top story:', e);
                alert('Error: ' + (e.message || 'Failed to toggle top story. Please try again.'));
            });
        }
        window.toggleTopStory = toggleTopStory;
        
        // Toggle good fit
        function toggleGoodFit(articleId) {
            console.log('toggleGoodFit called with articleId:', articleId);
            const button = document.querySelector(`.good-fit-btn[data-id="${articleId}"]`);
            const topStoryButton = document.querySelector(`.top-story-btn[data-id="${articleId}"]`);
            if (!button) {
                console.error('Button not found for articleId:', articleId);
                return;
            }
            const isCurrentlyGood = button.getAttribute('data-state') === 'on' || (button.style.background && button.style.background.includes('#4caf50'));
            const newState = !isCurrentlyGood;
            
            if (newState) {
                button.style.background = '#4caf50';
                button.style.border = 'none';
                button.style.borderRadius = '50%';
                button.style.opacity = '1';
                button.setAttribute('data-state', 'on');
                // Top hat and thumbs up can both be on - no mutual exclusion
            } else {
                button.style.background = 'transparent';
                button.style.border = 'none';
                button.style.opacity = '0.5';
                button.setAttribute('data-state', 'off');
            }
            
            const zipCode = getZipCodeFromUrl();
            const requestBody = {id: articleId, is_good_fit: newState};
            if (zipCode) {
                requestBody.zip_code = zipCode;
            }
            
            fetch('/admin/api/good-fit', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify(requestBody)
            })
            .then(r => {
                if (!r.ok) {
                    if (r.status === 401) {
                        throw new Error('Not authenticated. Please log in again.');
                    }
                    throw new Error(`HTTP ${r.status}: ${r.statusText}`);
                }
                return r.json();
            })
            .then(data => {
                if (data && data.success) {
                    console.log('Good fit state saved:', newState);
                } else {
                    // Revert UI on error
                    if (newState) {
                        button.style.background = 'transparent';
                        button.style.border = 'none';
                        button.style.opacity = '0.5';
                        button.setAttribute('data-state', 'off');
                    } else {
                        button.style.background = '#4caf50';
                        button.style.border = 'none';
                        button.style.borderRadius = '50%';
                        button.style.opacity = '1';
                        button.setAttribute('data-state', 'on');
                    }
                    alert('Error saving good fit: ' + (data ? data.message : 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error saving good fit:', e);
                if (newState) {
                    button.style.background = 'transparent';
                    button.style.border = 'none';
                    button.style.opacity = '0.5';
                    button.setAttribute('data-state', 'off');
                } else {
                    button.style.background = '#4caf50';
                    button.style.border = 'none';
                    button.style.borderRadius = '50%';
                    button.style.opacity = '1';
                    button.setAttribute('data-state', 'on');
                }
                alert('Error: ' + (e.message || 'Failed to save good fit. Please try again.'));
            });
        }
        window.toggleGoodFit = toggleGoodFit;
        
        // Edit article
        function editArticle(articleId) {
            console.log('Editing article:', articleId);
            if (!articleId) {
                alert('Error: Article ID is missing');
                return;
            }
            fetch('/admin/api/get-article?id=' + encodeURIComponent(articleId), {credentials: 'same-origin'})
                .then(r => {
                    if (!r.ok) {
                        if (r.status === 401) {
                            throw new Error('Not authenticated. Please log in again.');
                        }
                        throw new Error('HTTP ' + r.status + ': ' + r.statusText);
                    }
                    return r.json();
                })
                .then(data => {
                    if (data && data.success && data.article) {
                        const article = data.article;
                        if (typeof showEditModal === 'function') {
                            showEditModal(article);
                        } else {
                            alert('Error: Edit modal function not available');
                        }
                    } else {
                        alert('Error loading article: ' + (data ? data.message : 'Unknown error'));
                    }
                })
                .catch(e => {
                    console.error('Error loading article:', e);
                    alert('Error: ' + (e.message || 'Failed to load article. Please try again.'));
                });
        }
        window.editArticle = editArticle;
        
        // Restore article
        function restoreArticle(articleId, rejectionType) {
            console.log('Restoring article:', articleId, 'type:', rejectionType);
            if (!articleId) {
                alert('Error: Article ID is missing');
                return;
            }
            
            const zipCode = getZipCodeFromUrl();
            const requestBody = {
                article_id: articleId,
                rejection_type: rejectionType || 'manual'
            };
            
            if (zipCode) {
                requestBody.zip_code = zipCode;
            }
            
            fetch('/admin/api/restore-article', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify(requestBody)
            })
            .then(r => {
                if (!r.ok) {
                    if (r.status === 401) {
                        throw new Error('Not authenticated. Please log in again.');
                    }
                    throw new Error(`HTTP ${r.status}: ${r.statusText}`);
                }
                return r.json();
            })
            .then(data => {
                if (data && data.success) {
                    if (typeof window.loadTrash === 'function') {
                        window.loadTrash();
                    } else {
                        location.reload();
                    }
                } else {
                    alert('Error restoring article: ' + (data ? data.message : 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error restoring article:', e);
                alert('Error: ' + (e.message || 'Failed to restore article. Please try again.'));
            });
        }
        window.restoreArticle = restoreArticle;
        
        console.log('Button handler functions defined');
    } catch(e) {
        console.error('Error defining button handler functions:', e);
        alert('Script error - check console. Some buttons may not work. Error: ' + e.message);
    }
})();

// Unified event delegation for all buttons
document.addEventListener('click', async (e) => {
    const btn = e.target.closest('button, .trash-btn, .restore-btn, .top-story-btn, .restore-trash-btn');
    
    if (!btn) return;
    
    if (!btn.classList.contains('trash-btn') && 
        !btn.classList.contains('restore-btn') && 
        !btn.classList.contains('restore-trash-btn') && 
        !btn.classList.contains('top-story-btn') &&
        !btn.classList.contains('good-fit-btn') &&
        !btn.classList.contains('edit-article-btn') &&
        !btn.getAttribute('data-action')) {
        return;
    }
    
    e.preventDefault();
    e.stopPropagation();
    
    const id = btn.dataset.id || btn.closest('[data-id]')?.dataset.id;
    
    if (!id) {
        console.error('No data-id found on button:', btn);
        return;
    }
    
    const articleId = parseInt(id);
    if (isNaN(articleId)) {
        console.error('Invalid article ID:', id);
        return;
    }
    
    // Handle trash button
    if (btn.classList.contains('trash-btn') || btn.getAttribute('data-action') === 'trash-article') {
        if (typeof window.rejectArticle === 'function') {
            window.rejectArticle(articleId);
        } else {
            alert('Error: rejectArticle function not available. Please refresh the page.');
        }
        return;
    }
    
    // Handle restore button
    if (btn.classList.contains('restore-btn') || btn.classList.contains('restore-trash-btn') || btn.getAttribute('data-action') === 'restore-article') {
        const rejectionType = btn.getAttribute('data-rejection-type') || 'manual';
        if (typeof window.restoreArticle === 'function') {
            window.restoreArticle(articleId, rejectionType);
        } else {
            alert('Error: restoreArticle function not available. Please refresh the page.');
        }
        return;
    }
    
    // Handle top story button
    if (btn.classList.contains('top-story-btn') || btn.getAttribute('data-action') === 'toggle-top-story') {
        if (typeof window.toggleTopStory === 'function') {
            window.toggleTopStory(articleId);
        } else {
            alert('Error: toggleTopStory function not available. Please refresh the page.');
        }
        return;
    }
    
    // Handle good fit button
    if (btn.classList.contains('good-fit-btn') || btn.getAttribute('data-action') === 'toggle-good-fit') {
        if (typeof window.toggleGoodFit === 'function') {
            window.toggleGoodFit(articleId);
        } else {
            alert('Error: toggleGoodFit function not available. Please refresh the page.');
        }
        return;
    }
    
    // Handle edit article button
    if (btn.classList.contains('edit-article-btn') || btn.getAttribute('data-action') === 'edit-article') {
        if (typeof window.editArticle === 'function') {
            window.editArticle(articleId);
        } else {
            alert('Error: editArticle function not available. Please refresh the page.');
        }
        return;
    }
});

console.log('Unified button event handler attached');

// Store all trash articles for filtering
let allTrashArticles = [];
let currentTrashFilter = 'all';
let currentSearchTerm = '';

// Filter trash articles based on selected filter and search term
function filterTrashArticles(filter, searchTerm) {
    currentTrashFilter = filter;
    currentSearchTerm = searchTerm || '';
    const trashList = document.getElementById('trashList');
    if (!trashList) return;
    
    // Update filter buttons
    document.querySelectorAll('.trash-filter-btn').forEach(btn => {
        const btnFilter = btn.getAttribute('data-filter');
        if (btnFilter === filter) {
            btn.classList.add('active');
            btn.style.background = '#0078d4';
            btn.style.color = 'white';
            btn.style.border = 'none';
        } else {
            btn.classList.remove('active');
            btn.style.background = '#404040';
            btn.style.color = '#e0e0e0';
            btn.style.border = '1px solid #555';
        }
    });
    
    // Update clear button visibility
    const clearBtn = document.getElementById('trashSearchClear');
    if (clearBtn) {
        clearBtn.style.display = searchTerm && searchTerm.trim() ? 'block' : 'none';
    }
    
    // Filter articles by rejection type first
    let filteredArticles = allTrashArticles;
    if (filter === 'manual') {
        filteredArticles = allTrashArticles.filter(article => {
            const rejectionType = article.rejection_type || (article.is_auto_rejected ? 'auto' : 'manual');
            return rejectionType === 'manual';
        });
    } else if (filter === 'auto') {
        filteredArticles = allTrashArticles.filter(article => {
            const rejectionType = article.rejection_type || (article.is_auto_rejected ? 'auto' : 'manual');
            return rejectionType === 'auto';
        });
    }
    
    // Then filter by search term if provided
    if (searchTerm && searchTerm.trim()) {
        const searchLower = searchTerm.toLowerCase().trim();
        filteredArticles = filteredArticles.filter(article => {
            // Search in title
            const title = (article.title || '').toLowerCase();
            if (title.includes(searchLower)) return true;
            
            // Search in source
            const source = (article.source || '').toLowerCase();
            if (source.includes(searchLower)) return true;
            
            // Search in auto-reject reason
            if (article.auto_reject_reason) {
                const reason = article.auto_reject_reason.toLowerCase();
                if (reason.includes(searchLower)) return true;
            }
            
            // Search in publication date (if search looks like a date)
            if (article.published) {
                const published = article.published.toLowerCase();
                if (published.includes(searchLower)) return true;
            }
            
            return false;
        });
    }
    
    // Clear and re-render filtered articles
    trashList.innerHTML = '';
    
    if (filteredArticles.length === 0) {
        let emptyMsg = '';
        if (searchTerm && searchTerm.trim()) {
            emptyMsg = `No articles found matching "${escapeHtml(searchTerm)}"`;
            if (filter !== 'all') {
                const filterName = filter === 'manual' ? 'manually rejected' : 'auto-filtered';
                emptyMsg += ` in ${filterName} articles`;
            }
        } else {
            emptyMsg = filter === 'all' ? 'No articles in trash' : 
                        filter === 'manual' ? 'No manually rejected articles' : 
                        'No auto-filtered articles';
        }
        trashList.innerHTML = '<p style="padding: 2rem; text-align: center; color: #888; background: #252525; border-radius: 8px; font-size: 1.1rem; border: 1px solid #404040;">' + emptyMsg + '</p>';
        updateTrashFilterCount(0, allTrashArticles.length, filter, searchTerm);
        return;
    }
    
    filteredArticles.forEach(function(article) {
        const articleId = article.id;
        const rejectionType = article.rejection_type || (article.is_auto_rejected ? 'auto' : 'manual');
        const isManual = rejectionType === 'manual';
        const isAuto = rejectionType === 'auto';
        const borderColor = isManual ? '#d32f2f' : '#764ba2';
        const badgeText = isManual ? '🗑️ Manually Rejected' : '🤖 Auto-Filtered';
        const badgeClass = isManual ? 'badge-manual' : 'badge-auto';
        
        const articleCard = document.createElement('div');
        articleCard.className = 'trash-article-card';
        articleCard.setAttribute('data-rejection-type', rejectionType);
        articleCard.style.cssText = 'background: #252525; padding: 0; margin-bottom: 1.5rem; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.3); overflow: hidden; border-left: 5px solid ' + borderColor + '; border: 1px solid #404040;';
        
        const safeTitle = escapeHtml(article.title || 'No title');
        const safeSource = escapeHtml(article.source || 'Unknown');
        const publishedDate = article.published ? article.published.substring(0, 10) : null;
        const safePublished = publishedDate ? escapeHtml(publishedDate) : 'N/A';
        const safeArticleId = escapeHtml(String(articleId));
        
        const relevanceScore = article.relevance_score !== null && article.relevance_score !== undefined ? 
            Math.round(article.relevance_score) : 'N/A';
        const relevanceColor = relevanceScore !== 'N/A' && relevanceScore >= 50 ? '#4caf50' : 
            (relevanceScore !== 'N/A' && relevanceScore >= 30 ? '#ff9800' : '#888');
        
        // Build rejection reason display for auto-filtered articles
        let rejectionReasonHtml = '';
        if (isAuto && article.auto_reject_reason) {
            const safeReason = escapeHtml(article.auto_reject_reason);
            rejectionReasonHtml = '<div style="font-size: 0.85rem; color: #ff9800; margin-top: 0.5rem; padding: 0.5rem; background: rgba(255, 152, 0, 0.1); border-left: 3px solid #ff9800; border-radius: 4px;">' +
                '<strong>🤖 Auto-filter reason:</strong> ' + safeReason +
                '</div>';
        }
        
        let cardHtml = '<div style="padding: 1.5rem; border-bottom: 1px solid #404040;">' +
            '<div style="display: flex; align-items: flex-start; gap: 1rem; margin-bottom: 0.5rem;">' +
            '<div style="flex: 1;">' +
            '<div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem;">' +
            '<div class="badge-container ' + badgeClass + '">' + escapeHtml(badgeText) + '</div>' +
            '</div>' +
            '<div style="font-weight: 600; font-size: 1.1rem; color: #e0e0e0; margin-bottom: 0.5rem;">' + safeTitle + '</div>' +
            '<div style="font-size: 0.85rem; color: #888;">' + safeSource + ' - ' + safePublished + '</div>' +
            '<div style="font-size: 0.85rem; color: #888; margin-top: 0.25rem;">Relevance: <strong style="color: ' + relevanceColor + ';">' + relevanceScore + '</strong></div>' +
            rejectionReasonHtml +
            '</div>' +
            '<button class="restore-trash-btn" data-id="' + escapeAttr(safeArticleId) + '" data-rejection-type="' + escapeAttr(rejectionType) + '" style="background: #4caf50; color: white; padding: 0.5rem 1rem; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.9rem;">↩️ Restore</button>' +
            '</div>' +
            '</div>';
        
        articleCard.innerHTML = cardHtml;
        trashList.appendChild(articleCard);
    });
    
    updateTrashFilterCount(filteredArticles.length, allTrashArticles.length, filter, searchTerm);
}

// Update filter count display
function updateTrashFilterCount(visible, total, filter, searchTerm) {
    const countText = document.getElementById('trashFilterCountText');
    if (!countText) return;
    
    if (total === 0) {
        countText.textContent = 'No articles';
    } else if (searchTerm && searchTerm.trim()) {
        const searchDisplay = escapeHtml(searchTerm.trim());
        if (filter === 'all') {
            countText.textContent = `Showing ${visible} of ${total} articles matching "${searchDisplay}"`;
        } else {
            const filterName = filter === 'manual' ? 'manually rejected' : 'auto-filtered';
            countText.textContent = `Showing ${visible} of ${total} ${filterName} articles matching "${searchDisplay}"`;
        }
    } else if (filter === 'all') {
        countText.textContent = `Showing all ${total} article${total !== 1 ? 's' : ''}`;
    } else {
        const filterName = filter === 'manual' ? 'manually rejected' : 'auto-filtered';
        countText.textContent = `Showing ${visible} of ${total} ${filterName} article${visible !== 1 ? 's' : ''}`;
    }
}

// Clear search function
function clearTrashSearch() {
    const searchInput = document.getElementById('trashSearchInput');
    if (searchInput) {
        searchInput.value = '';
        filterTrashArticles(currentTrashFilter, '');
    }
}
window.clearTrashSearch = clearTrashSearch;

// Load trash function
window.loadTrash = function loadTrash() {
    console.log('loadTrash called');
    const trashList = document.getElementById('trashList');
    if (!trashList) {
        console.error('trashList element not found!');
        return;
    }
    
    trashList.innerHTML = '<p style="padding: 2rem; text-align: center; color: #888; background: #252525; border-radius: 8px; border: 1px solid #404040;">Loading rejected articles...</p>';
    
    const zipCode = getZipCodeFromUrl();
    let url = '/admin/api/get-rejected-articles';
    if (zipCode) {
        url += '?zip_code=' + encodeURIComponent(zipCode);
    }
    
    fetch(url, {
        credentials: "same-origin",
        headers: {"Accept": "application/json"}
    })
    .then(function(response) {
        if (!response.ok) {
            if (response.status === 401) {
                return Promise.reject(new Error('Not authenticated. Please log in again.'));
            }
            return response.text().then(function(text) {
                var msg = 'HTTP ' + response.status;
                try {
                    var errorData = JSON.parse(text);
                    if (errorData.error) msg = errorData.error;
                    else if (errorData.message) msg = errorData.message;
                } catch (e) {
                    if (text) msg += ': ' + text.substring(0, 200);
                }
                return Promise.reject(new Error(msg));
            });
        }
        return response.json();
    })
    .then(function(data) {
        // Store all articles for filtering
        allTrashArticles = (data && data.success && data.articles) ? data.articles : [];
        
        // Apply current filter and search
        const searchInput = document.getElementById('trashSearchInput');
        const searchTerm = searchInput ? searchInput.value : '';
        filterTrashArticles(currentTrashFilter, searchTerm);
    })
    .catch(function(e) {
        console.error('Error loading trash:', e);
        const trashList = document.getElementById('trashList');
        if (trashList) {
            const errorMsg = e.message || 'Unknown error occurred';
            trashList.innerHTML = '<p style="padding: 2rem; text-align: center; color: #d32f2f; background: #252525; border-radius: 8px; border: 1px solid #404040;">' +
                '<strong>Error loading trash:</strong> ' + escapeHtml(errorMsg) + '<br>' +
                '<button class="retry-trash-btn" style="margin-top: 1rem; padding: 0.5rem 1rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer;">Retry</button>' +
                '</p>';
        }
        updateTrashFilterCount(0, 0, 'all');
    });
};

// Setup filter button handlers and search input
document.addEventListener('DOMContentLoaded', function() {
    // Filter button handlers
    document.getElementById('trashFilterAll')?.addEventListener('click', function() {
        const searchInput = document.getElementById('trashSearchInput');
        const searchTerm = searchInput ? searchInput.value : '';
        filterTrashArticles('all', searchTerm);
    });
    document.getElementById('trashFilterManual')?.addEventListener('click', function() {
        const searchInput = document.getElementById('trashSearchInput');
        const searchTerm = searchInput ? searchInput.value : '';
        filterTrashArticles('manual', searchTerm);
    });
    document.getElementById('trashFilterAuto')?.addEventListener('click', function() {
        const searchInput = document.getElementById('trashSearchInput');
        const searchTerm = searchInput ? searchInput.value : '';
        filterTrashArticles('auto', searchTerm);
    });
    
    // Search input handler with debouncing
    let searchTimeout;
    const searchInput = document.getElementById('trashSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            const searchTerm = this.value;
            searchTimeout = setTimeout(function() {
                filterTrashArticles(currentTrashFilter, searchTerm);
            }, 300); // Wait 300ms after user stops typing
        });
        
        // Also trigger on Enter key
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                clearTimeout(searchTimeout);
                filterTrashArticles(currentTrashFilter, this.value);
            }
        });
    }
});

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('Admin panel JavaScript initializing...');
    
    // Sortable functionality removed - not needed
    
    // Toggle handlers
    document.body.addEventListener('change', function(e) {
        // Show images toggle
        if (e.target.matches('#showImages') || e.target.matches('#showImagesSettings')) {
            const zipCode = getZipCodeFromUrl();
            const requestBody = {show_images: e.target.checked};
            if (zipCode) {
                requestBody.zip_code = zipCode;
            }
            
            fetch('/admin/api/toggle-images', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify(requestBody)
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    const otherCheckbox = e.target.matches('#showImages') ? 
                        document.getElementById('showImagesSettings') : 
                        document.getElementById('showImages');
                    if (otherCheckbox) otherCheckbox.checked = e.target.checked;
                }
            })
            .catch(e => {
                console.error('Error toggling images:', e);
                e.target.checked = !e.target.checked;
            });
        }
        
        // Source enabled toggle
        if (e.target.matches('.source-enabled')) {
            const sourceKey = e.target.dataset.source;
            const enabled = e.target.checked;
            updateSourceSetting(sourceKey, 'enabled', enabled, e.target);
        }
        
    });
    
    // Load trash if on trash tab
    if (window.location.pathname.includes('/trash')) {
        setTimeout(function() {
            if (typeof window.loadTrash === 'function') {
                window.loadTrash();
            }
        }, 300);
    }
    
    // Relevance score tooltip
    let tooltipElement = null;
    let tooltipTimeout = null;
    
    document.addEventListener('mouseenter', function(e) {
        if (e.target.matches('.relevance-score-tooltip')) {
            const articleId = e.target.dataset.articleId;
            if (!articleId) return;
            
            // Clear any existing timeout
            if (tooltipTimeout) {
                clearTimeout(tooltipTimeout);
            }
            
            // Remove existing tooltip
            if (tooltipElement) {
                tooltipElement.remove();
            }
            
            // Fetch relevance breakdown
            fetch(`/admin/api/get-relevance-breakdown?id=${articleId}`, {
                method: 'GET',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin'
            })
            .then(r => r.json())
            .then(data => {
                if (data.success && data.breakdown) {
                    // Create tooltip element
                    tooltipElement = document.createElement('div');
                    tooltipElement.style.cssText = `
                        position: absolute;
                        background: #1a1a1a;
                        color: #e0e0e0;
                        padding: 0.75rem 1rem;
                        border-radius: 6px;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                        z-index: 10000;
                        max-width: 400px;
                        font-size: 0.9rem;
                        line-height: 1.6;
                        pointer-events: none;
                    `;
                    
                    // Create content
                    const title = document.createElement('div');
                    title.textContent = 'Relevance Breakdown:';
                    title.style.cssText = 'font-weight: 600; margin-bottom: 0.5rem; color: #fff;';
                    tooltipElement.appendChild(title);
                    
                    const list = document.createElement('div');
                    data.breakdown.forEach(item => {
                        const itemDiv = document.createElement('div');
                        itemDiv.textContent = item;
                        itemDiv.style.cssText = 'margin-bottom: 0.25rem;';
                        tooltipElement.appendChild(itemDiv);
                    });
                    
                    // Position tooltip
                    const rect = e.target.getBoundingClientRect();
                    tooltipElement.style.left = (rect.left + rect.width / 2) + 'px';
                    tooltipElement.style.top = (rect.bottom + 8) + 'px';
                    tooltipElement.style.transform = 'translateX(-50%)';
                    
                    document.body.appendChild(tooltipElement);
                }
            })
            .catch(err => {
                console.error('Error fetching relevance breakdown:', err);
            });
        }
    }, true);
    
    document.addEventListener('mouseleave', function(e) {
        if (e.target.matches('.relevance-score-tooltip')) {
            tooltipTimeout = setTimeout(function() {
                if (tooltipElement) {
                    tooltipElement.remove();
                    tooltipElement = null;
                }
            }, 200);
        }
    }, true);
});

// Source setting update
function updateSourceSetting(sourceKey, setting, value, toggleElement) {
    const originalChecked = toggleElement.checked;
    toggleElement.disabled = true;
    
    const zipCode = getZipCodeFromUrl();
    const requestBody = {
        source: sourceKey,
        setting: setting,
        value: value
    };
    if (zipCode) {
        requestBody.zip_code = zipCode;
    }
    
    fetch('/admin/api/source', {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "same-origin",
        body: JSON.stringify(requestBody)
    })
    .then(r => r.json())
    .then(data => {
        toggleElement.disabled = false;
        if (data.success) {
            console.log('Source setting saved:', sourceKey, setting, value);
            const parent = toggleElement.closest('.toggle-switch') || toggleElement.parentElement;
            let indicator = parent.querySelector('.save-indicator');
            if (!indicator) {
                indicator = document.createElement('span');
                indicator.className = 'save-indicator';
                indicator.style.cssText = 'color: #4caf50; margin-left: 0.5rem; font-size: 0.85rem; font-weight: 600;';
                parent.appendChild(indicator);
            }
            indicator.textContent = '✓ Saved';
            setTimeout(() => {
                if (indicator) indicator.remove();
            }, 2000);
        } else {
            toggleElement.checked = !originalChecked;
            alert('Error saving source setting: ' + (data.message || 'Unknown error'));
        }
    })
    .catch(e => {
        toggleElement.disabled = false;
        toggleElement.checked = !originalChecked;
        alert('Error: ' + e.message);
    });
}

// Edit modal functions
function showEditModal(article) {
    // Create or show edit modal
    let modal = document.getElementById('editArticleModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'editArticleModal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h2>Edit Article</h2>
                    <span class="close-modal" onclick="closeEditModal()">&times;</span>
                </div>
                <form id="editArticleForm" onsubmit="saveArticleEdit(event)">
                    <input type="hidden" id="editArticleId" name="id">
                    <div class="form-group">
                        <label>Title:</label>
                        <input type="text" id="editArticleTitle" name="title" required>
                    </div>
                    <div class="form-group">
                        <label>Summary:</label>
                        <textarea id="editArticleSummary" name="summary" rows="4"></textarea>
                    </div>
                    <div class="form-group">
                        <label>Publication Date:</label>
                        <input type="datetime-local" id="editArticlePublished" name="published">
                    </div>
                    <div class="form-group">
                        <label>URL:</label>
                        <input type="url" id="editArticleUrl" name="url">
                    </div>
                    <div class="form-group">
                        <label>Category:</label>
                        <select id="editArticleCategory" name="category">
                            <option value="local-news">📰 Local News</option>
                            <option value="crime">🚨 Crime & Public Safety</option>
                            <option value="sports">⚽ Sports</option>
                            <option value="events">🎬 Entertainment & Events</option>
                            <option value="weather">🌤️ Weather</option>
                            <option value="business">💼 Business & Development</option>
                            <option value="schools">🏫 Schools</option>
                            <option value="food">🍽️ Food & Drink</option>
                            <option value="obituaries">🕯️ Obituaries</option>
                        </select>
                    </div>
                    <div class="form-actions">
                        <button type="submit">Save</button>
                        <button type="button" onclick="closeEditModal()">Cancel</button>
                    </div>
                </form>
            </div>
        `;
        document.body.appendChild(modal);
    }
    
    // Populate form
    document.getElementById('editArticleId').value = article.id;
    document.getElementById('editArticleTitle').value = article.title || '';
    document.getElementById('editArticleSummary').value = article.summary || '';
    document.getElementById('editArticleUrl').value = article.url || '';
    // Map old category names to new slugs when loading
    const categoryMapping = {
        'news': 'local-news',
        'entertainment': 'events',
        'sports': 'sports',
        'local': 'local-news',
        'custom': 'local-news',
        'media': 'events'
    };
    const articleCategory = article.category || 'local-news';
    const mappedCategory = categoryMapping[articleCategory] || articleCategory;
    document.getElementById('editArticleCategory').value = mappedCategory;
    
    // Format date for datetime-local input
    if (article.published) {
        try {
            const date = new Date(article.published);
            const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
            document.getElementById('editArticlePublished').value = localDate.toISOString().slice(0, 16);
        } catch (e) {
            document.getElementById('editArticlePublished').value = '';
        }
    } else {
        document.getElementById('editArticlePublished').value = '';
    }
    
    modal.style.display = 'block';
}
window.showEditModal = showEditModal;

function closeEditModal() {
    const modal = document.getElementById('editArticleModal');
    if (modal) {
        modal.style.display = 'none';
    }
}
window.closeEditModal = closeEditModal;

function saveArticleEdit(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    const data = {
        id: formData.get('id'),
        title: formData.get('title'),
        summary: formData.get('summary'),
        url: formData.get('url'),
        category: formData.get('category'),
        published: formData.get('published')
    };
    
    // Convert datetime-local to ISO format
    if (data.published) {
        const date = new Date(data.published);
        data.published = date.toISOString();
    }
    
    fetch('/admin/api/edit-article', {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "same-origin",
        body: JSON.stringify(data)
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            closeEditModal();
            location.reload();
        } else {
            alert('Error saving article: ' + (result.message || 'Unknown error'));
        }
    })
    .catch(e => {
        alert('Error: ' + e.message);
    });
}
window.saveArticleEdit = saveArticleEdit;

// Close modal when clicking outside
window.addEventListener('click', function(event) {
    const modal = document.getElementById('editArticleModal');
    if (event.target == modal) {
        closeEditModal();
    }
});

// Relevance management functions
function addRelevanceItem(category, item) {
    if (!item || !item.trim()) {
        alert('Please enter a value');
        return;
    }
    
    const zipCode = getZipCodeFromUrl();
    fetch('/admin/api/relevance-item', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({
            category: category,
            item: item.trim(),
            zip_code: zipCode
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('Error: ' + (data.message || 'Failed to add item'));
        }
    })
    .catch(e => {
        alert('Error: ' + e.message);
    });
}
window.addRelevanceItem = addRelevanceItem;

function addTopicKeyword() {
    const keyword = document.getElementById('topicKeywordInput').value.trim();
    const points = parseFloat(document.getElementById('topicPointsInput').value);
    if (!keyword) {
        alert('Please enter a keyword');
        return;
    }
    if (isNaN(points) || points < 0) {
        alert('Please enter a valid point value');
        return;
    }
    
    const zipCode = getZipCodeFromUrl();
    fetch('/admin/api/relevance-item', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({
            category: 'topic_keywords',
            item: keyword,
            points: points,
            zip_code: zipCode
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('Error: ' + (data.message || 'Failed to add keyword'));
        }
    })
    .catch(e => {
        alert('Error: ' + e.message);
    });
}
window.addTopicKeyword = addTopicKeyword;

function addSourceCredibility() {
    const source = document.getElementById('sourceInput').value.trim();
    const points = parseFloat(document.getElementById('sourcePointsInput').value);
    if (!source) {
        alert('Please enter a source name');
        return;
    }
    if (isNaN(points) || points < 0) {
        alert('Please enter a valid point value');
        return;
    }
    
    const zipCode = getZipCodeFromUrl();
    fetch('/admin/api/relevance-item', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({
            category: 'source_credibility',
            item: source,
            points: points,
            zip_code: zipCode
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('Error: ' + (data.message || 'Failed to add source'));
        }
    })
    .catch(e => {
        alert('Error: ' + e.message);
    });
}
window.addSourceCredibility = addSourceCredibility;

// Remove relevance item handler
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('remove-relevance-btn') || e.target.closest('.remove-relevance-btn')) {
        const btn = e.target.classList.contains('remove-relevance-btn') ? e.target : e.target.closest('.remove-relevance-btn');
        const category = btn.getAttribute('data-category');
        const item = btn.getAttribute('data-item');
        
        if (!confirm(`Remove "${item}" from ${category}?`)) {
            return;
        }
        
        const zipCode = getZipCodeFromUrl();
        fetch('/admin/api/relevance-item', {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({
                category: category,
                item: item,
                zip_code: zipCode
            })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                location.reload();
            } else {
                alert('Error: ' + (data.message || 'Failed to remove item'));
            }
        })
        .catch(e => {
            alert('Error: ' + e.message);
        });
    }
});

// Load Bayesian statistics
function loadBayesianStats() {
    const statsDiv = document.getElementById('bayesianStats');
    if (!statsDiv) return;
    
    fetch('/admin/api/bayesian-stats', {
        credentials: 'same-origin',
        headers: {'Accept': 'application/json'}
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            const stats = data.stats;
            statsDiv.innerHTML = `
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                    <div style="background: rgba(255,255,255,0.1); padding: 1rem; border-radius: 6px;">
                        <div style="font-size: 0.9rem; opacity: 0.9;">Rejected Articles Trained</div>
                        <div style="font-size: 2rem; font-weight: bold; margin-top: 0.5rem;">${stats.reject_count || 0}</div>
                    </div>
                    <div style="background: rgba(255,255,255,0.1); padding: 1rem; border-radius: 6px;">
                        <div style="font-size: 0.9rem; opacity: 0.9;">Accepted Articles</div>
                        <div style="font-size: 2rem; font-weight: bold; margin-top: 0.5rem;">${stats.accept_count || 0}</div>
                    </div>
                    <div style="background: rgba(255,255,255,0.1); padding: 1rem; border-radius: 6px;">
                        <div style="font-size: 0.9rem; opacity: 0.9;">Learned Patterns</div>
                        <div style="font-size: 2rem; font-weight: bold; margin-top: 0.5rem;">${stats.pattern_count || 0}</div>
                    </div>
                </div>
            `;
        } else {
            statsDiv.innerHTML = '<p>Unable to load statistics</p>';
        }
    })
    .catch(e => {
        console.error('Error loading Bayesian stats:', e);
        statsDiv.innerHTML = '<p>Error loading statistics</p>';
    });
}

// Load stats on page load if on relevance tab
if (window.location.pathname.includes('/relevance')) {
    document.addEventListener('DOMContentLoaded', loadBayesianStats);
}

// Save relevance threshold
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('save-threshold-btn')) {
        const threshold = parseInt(document.getElementById('relevanceThreshold').value);
        if (isNaN(threshold) || threshold < 0 || threshold > 100) {
            alert('Please enter a valid threshold (0-100)');
            return;
        }
        
        const zipCode = getZipCodeFromUrl();
        fetch('/admin/api/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({
                key: 'relevance_threshold',
                value: threshold.toString(),
                zip_code: zipCode
            })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert('Threshold saved successfully');
            } else {
                alert('Error: ' + (data.message || 'Failed to save threshold'));
            }
        })
        .catch(e => {
            alert('Error: ' + e.message);
        });
    }
});

// Toggle explanation
function toggleExplanation(id) {
    const el = document.getElementById(id);
    const toggle = document.getElementById(id + 'Toggle');
    if (el && toggle) {
        if (el.style.display === 'none') {
            el.style.display = 'block';
            toggle.textContent = '▲';
        } else {
            el.style.display = 'none';
            toggle.textContent = '▼';
        }
    }
}
window.toggleExplanation = toggleExplanation;

function closeExplanation(id) {
    const el = document.getElementById(id);
    const toggle = document.getElementById(id + 'Toggle');
    if (el && toggle) {
        el.style.display = 'none';
        toggle.textContent = '▼';
    }
}
window.closeExplanation = closeExplanation;

// Regenerate website for current zip code
function regenerateWebsite() {
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        alert('Zip code not found in URL');
        return;
    }
    
    if (!confirm(`Regenerate website for zip code ${zipCode}?`)) {
        return;
    }
    
    fetch(`/admin/api/regenerate?zip=${encodeURIComponent(zipCode)}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin'
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            alert('Website regeneration started. This may take a few minutes.');
        } else {
            alert('Error: ' + (data.message || 'Failed to regenerate website'));
        }
    })
    .catch(e => {
        alert('Error: ' + e.message);
    });
}
window.regenerateWebsite = regenerateWebsite;

// Regenerate all websites
function regenerateAll() {
    if (!confirm('Regenerate websites for all zip codes? This may take several minutes.')) {
        return;
    }
    
    fetch('/admin/api/regenerate-all', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin'
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            alert('Website regeneration started for all zip codes. This may take several minutes.');
        } else {
            alert('Error: ' + (data.message || 'Failed to regenerate websites'));
        }
    })
    .catch(e => {
        alert('Error: ' + e.message);
    });
}
window.regenerateAll = regenerateAll;

// Add new source
function addNewSource() {
    const name = prompt('Enter source name:');
    if (!name) return;
    
    const url = prompt('Enter source URL:');
    if (!url) return;
    
    const zipCode = getZipCodeFromUrl();
    const requestBody = {
        name: name,
        url: url,
        enabled: true
    };
    if (zipCode) {
        requestBody.zip_code = zipCode;
    }
    
    fetch('/admin/api/add-source', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify(requestBody)
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            alert('Source added successfully');
            location.reload();
        } else {
            alert('Error: ' + (data.message || 'Failed to add source'));
        }
    })
    .catch(e => {
        alert('Error: ' + e.message);
    });
}
window.addNewSource = addNewSource;

// Retrain all categories
function retrainAllCategories() {
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        alert('Zip code not found in URL');
        return;
    }
    
    if (!confirm(`Retrain all categories for zip code ${zipCode}? This may take a few minutes.`)) {
        return;
    }
    
    // Show loading state
    const button = event?.target || document.querySelector('button[onclick*="retrainAllCategories"]');
    const originalText = button?.textContent || '🔄 Retrain All Categories';
    if (button) {
        button.disabled = true;
        button.textContent = '⏳ Retraining...';
    }
    
    // Show progress in stats div
    const statsDiv = document.getElementById('categoryStats');
    if (statsDiv) {
        const originalHTML = statsDiv.innerHTML;
        statsDiv.innerHTML = '<div style="text-align: center; padding: 2rem; color: #666;"><p>⏳ Retraining categories... This may take a few minutes.</p><p style="font-size: 0.9rem;">Please wait...</p></div>';
    }
    
    fetch('/admin/api/retrain-categories', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({zip_code: zipCode})
    })
    .then(r => {
        if (!r.ok) {
            return r.text().then(text => {
                throw new Error(`HTTP ${r.status}: ${text.substring(0, 100)}`);
            });
        }
        return r.json();
    })
    .then(data => {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
        
        if (data.success) {
            const count = data.message?.match(/\d+/)?.[0] || 'all';
            alert(`Categories retrained successfully! Updated ${count} articles.`);
            // Reload category stats
            if (statsDiv) {
                loadCategoryStats();
            } else {
                location.reload();
            }
        } else {
            alert('Error: ' + (data.message || 'Failed to retrain categories'));
            if (statsDiv) {
                loadCategoryStats(); // Reload stats even on error
            }
        }
    })
    .catch(e => {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
        alert('Error: ' + e.message);
        if (statsDiv) {
            loadCategoryStats(); // Reload stats even on error
        }
    });
}
window.retrainAllCategories = retrainAllCategories;

// Add new category
function addNewCategory() {
    const input = document.getElementById('newCategoryInput');
    if (!input) {
        alert('Category input field not found');
        return;
    }
    
    const categoryName = input.value.trim();
    if (!categoryName) {
        alert('Please enter a category name');
        return;
    }
    
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        alert('Zip code not found in URL');
        return;
    }
    
    fetch('/admin/api/add-category', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({
            category: categoryName,
            zip_code: zipCode
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            alert('Category added successfully');
            location.reload();
        } else {
            alert('Error: ' + (data.message || 'Failed to add category'));
        }
    })
    .catch(e => {
        alert('Error: ' + e.message);
    });
}
window.addNewCategory = addNewCategory;

// Load category statistics
function loadCategoryStats() {
    const statsDiv = document.getElementById('categoryStats');
    if (!statsDiv) return;
    
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        statsDiv.innerHTML = '<p style="color: #d32f2f;">Error: Zip code not found</p>';
        return;
    }
    
    const url = `/admin/api/category-stats?zip_code=${encodeURIComponent(zipCode)}`;
    console.log('Fetching category stats from:', url);
    
    fetch(url, {
        method: 'GET',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) {
            // If response is not OK, try to get error message
            return r.text().then(text => {
                throw new Error(`HTTP ${r.status}: ${text.substring(0, 100)}`);
            });
        }
        // Check if response is JSON
        const contentType = r.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            return r.text().then(text => {
                throw new Error('Response is not JSON. Received: ' + text.substring(0, 100));
            });
        }
        return r.json();
    })
    .then(data => {
        if (data.success) {
            let html = '<div style="display: grid; gap: 1.5rem;">';
            
            // Training Statistics Section (show first)
            if (data.training_stats) {
                const stats = data.training_stats;
                const totalExamples = stats.total_examples || 0;
                const isActive = stats.bayesian_active || false;
                
                html += '<div style="padding: 1.5rem; background: ' + (isActive ? '#e8f5e9' : '#fff3e0') + '; border-left: 4px solid ' + (isActive ? '#4caf50' : '#ff9800') + '; border-radius: 8px;">';
                html += '<h3 style="margin-top: 0; margin-bottom: 1rem; color: #333; display: flex; align-items: center; gap: 0.5rem;">';
                html += '<span>' + (isActive ? '✅' : '⚠️') + '</span>';
                html += '<span>Category Training Status</span>';
                html += '</h3>';
                
                html += '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1rem;">';
                html += '<div><strong style="color: #333;">Total Training Examples:</strong> <span style="color: #666;">' + totalExamples + '</span></div>';
                html += '<div><strong style="color: #333;">Positive Examples:</strong> <span style="color: #4caf50;">' + (stats.total_positive || 0) + '</span></div>';
                html += '<div><strong style="color: #333;">Negative Examples:</strong> <span style="color: #f44336;">' + (stats.total_negative || 0) + '</span></div>';
                html += '</div>';
                
                html += '<div style="padding: 0.75rem; background: ' + (isActive ? '#c8e6c9' : '#ffe0b2') + '; border-radius: 4px; margin-bottom: 1rem;">';
                html += '<strong style="color: #333;">Bayesian Learning:</strong> ';
                if (isActive) {
                    html += '<span style="color: #2e7d32; font-weight: 600;">ACTIVE</span> ';
                    html += '<span style="color: #666; font-size: 0.9rem;">(Using learned patterns from ' + totalExamples + ' examples)</span>';
                } else {
                    html += '<span style="color: #e65100; font-weight: 600;">COLD-START MODE</span> ';
                    html += '<span style="color: #666; font-size: 0.9rem;">(Using keyword matching only. Need ' + (50 - totalExamples) + ' more examples to activate)</span>';
                }
                html += '</div>';
                
                // Training examples per category
                if (stats.category_training && Object.keys(stats.category_training).length > 0) {
                    html += '<div style="margin-top: 1rem;">';
                    html += '<h4 style="margin-bottom: 0.75rem; color: #333; font-size: 0.95rem;">Training Examples by Category:</h4>';
                    html += '<div style="display: grid; gap: 0.5rem;">';
                    Object.entries(stats.category_training).forEach(([category, catStats]) => {
                        html += '<div style="display: flex; justify-content: space-between; padding: 0.5rem; background: white; border-radius: 4px; font-size: 0.9rem;">';
                        html += '<span style="color: #333;">' + escapeHtml(category) + '</span>';
                        html += '<span style="color: #666;">';
                        html += '<span style="color: #4caf50;">+' + catStats.positive + '</span>';
                        html += ' / <span style="color: #f44336;">-' + catStats.negative + '</span>';
                        html += ' (<strong>' + catStats.total + '</strong> total)';
                        html += '</span>';
                        html += '</div>';
                    });
                    html += '</div></div>';
                }
                
                html += '</div>';
            }
            
            // Database categories with expandable keyword lists
            if (data.db_categories && data.db_categories.length > 0) {
                html += '<div>';
                html += '<h4 style="margin-bottom: 0.75rem; color: #333;">Categories in Database</h4>';
                html += '<div style="display: grid; gap: 0.75rem;">';
                
                // Map slugs to display names and emojis
                const categoryInfo = {
                    'local-news': { name: 'Local News', emoji: '📰' },
                    'crime': { name: 'Crime & Public Safety', emoji: '🚨' },
                    'sports': { name: 'Sports', emoji: '⚽' },
                    'events': { name: 'Entertainment & Events', emoji: '🎬' },
                    'weather': { name: 'Weather', emoji: '🌤️' },
                    'business': { name: 'Business & Development', emoji: '💼' },
                    'schools': { name: 'Schools', emoji: '🏫' },
                    'food': { name: 'Food & Drink', emoji: '🍽️' },
                    'obituaries': { name: 'Obituaries', emoji: '🕯️' }
                };
                
                // Sort categories by display name
                const sortedCats = data.db_categories.sort((a, b) => {
                    const nameA = categoryInfo[a]?.name || a;
                    const nameB = categoryInfo[b]?.name || b;
                    return nameA.localeCompare(nameB);
                });
                
                sortedCats.forEach(cat => {
                    const info = categoryInfo[cat] || { name: cat, emoji: '📁' };
                    const displayName = info.name;
                    const emoji = info.emoji;
                    const keywordCount = data.keyword_counts[cat] || 0;
                    const keywords = (data.category_keywords && data.category_keywords[cat]) || [];
                    const categoryId = 'category-' + cat.replace(/[^a-z0-9]/g, '-');
                    const isExpanded = keywordCount > 0; // Expand if has keywords
                    
                    // Category card header
                    html += `<div style="border: 1px solid #ddd; border-radius: 8px; overflow: hidden; background: white;">`;
                    html += `<div style="padding: 1rem; cursor: pointer; background: #f5f5f5; display: flex; align-items: center; justify-content: space-between;" onclick="toggleCategoryKeywords('${categoryId}')">`;
                    html += `<div style="display: flex; align-items: center; gap: 0.5rem;">`;
                    html += `<span style="font-size: 1.2rem;">${emoji}</span>`;
                    html += `<span style="font-weight: 600; color: #333;">${escapeHtml(displayName)}</span>`;
                    html += `<span style="color: #666; font-size: 0.9rem;">(${keywordCount} keywords)</span>`;
                    html += `</div>`;
                    html += `<span id="${categoryId}-toggle" style="font-size: 1.2rem; user-select: none; color: #666;">${isExpanded ? '▼' : '▶'}</span>`;
                    html += `</div>`;
                    
                    // Expandable keyword list
                    html += `<div id="${categoryId}" style="display: ${isExpanded ? 'block' : 'none'}; padding: 1rem; background: #f9f9f9; border-top: 1px solid #ddd;">`;
                    
                    if (keywords.length > 0) {
                        html += `<div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem;">`;
                        keywords.forEach((keyword, idx) => {
                            const keywordEscaped = escapeHtml(keyword).replace(/'/g, "&#39;").replace(/"/g, "&quot;");
                            html += `<span style="display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0.75rem; background: white; border: 1px solid #ddd; border-radius: 4px; font-size: 0.9rem;">`;
                            html += `<span style="color: #333;">${escapeHtml(keyword)}</span>`;
                            html += `<button onclick="removeCategoryKeyword('${cat}', ${JSON.stringify(keyword)}, '${categoryId}')" style="background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer; font-size: 0.85rem;" title="Remove keyword">🗑️</button>`;
                            html += `</span>`;
                        });
                        html += `</div>`;
                    } else {
                        html += `<p style="color: #666; font-size: 0.9rem; margin-bottom: 1rem; font-style: italic;">No keywords yet. Add your first keyword below.</p>`;
                    }
                    
                    // Add keyword input
                    html += `<div style="display: flex; gap: 0.5rem; align-items: center;">`;
                    html += `<input type="text" id="${categoryId}-input" placeholder="Enter keyword..." style="flex: 1; padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; font-size: 0.9rem;" onkeypress="if(event.key==='Enter') addCategoryKeyword('${cat}', '${categoryId}')">`;
                    html += `<button onclick="addCategoryKeyword('${cat}', '${categoryId}')" style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 0.9rem;">Add</button>`;
                    html += `</div>`;
                    
                    html += `</div>`;
                    html += `</div>`;
                });
                html += '</div></div>';
            } else {
                html += '<div><p style="color: #666;">No categories found in database. Add keywords using the inline keyword manager above.</p></div>';
            }
            
            // Category usage from articles
            if (data.category_counts && data.category_counts.length > 0) {
                html += '<div>';
                html += '<h4 style="margin-bottom: 0.75rem; color: #333;">Articles by Category</h4>';
                html += '<div style="display: grid; gap: 0.5rem;">';
                data.category_counts.forEach(item => {
                    html += `<div style="display: flex; justify-content: space-between; padding: 0.5rem; background: #f5f5f5; border-radius: 4px;">
                        <span style="color: #333; font-weight: 500;">${escapeHtml(item.category)}</span>
                        <span style="color: #666;">${item.count} articles</span>
                    </div>`;
                });
                html += '</div></div>';
            }
            
            // Primary category usage (from classifier)
            if (data.primary_category_counts && data.primary_category_counts.length > 0) {
                html += '<div>';
                html += '<h4 style="margin-bottom: 0.75rem; color: #333;">Articles by Primary Category (Classifier)</h4>';
                html += '<div style="display: grid; gap: 0.5rem;">';
                data.primary_category_counts.forEach(item => {
                    html += `<div style="display: flex; justify-content: space-between; padding: 0.5rem; background: #f5f5f5; border-radius: 4px;">
                        <span style="color: #333; font-weight: 500;">${escapeHtml(item.category)}</span>
                        <span style="color: #666;">${item.count} articles</span>
                    </div>`;
                });
                html += '</div></div>';
            }
            
            html += '</div>';
            statsDiv.innerHTML = html;
        } else {
            statsDiv.innerHTML = '<p style="color: #d32f2f;">Error loading statistics: ' + escapeHtml(data.error || 'Unknown error') + '</p>';
        }
    })
    .catch(e => {
        console.error('Category stats error:', e);
        statsDiv.innerHTML = '<p style="color: #d32f2f;">Error: ' + escapeHtml(e.message) + '</p>';
    });
}
window.loadCategoryStats = loadCategoryStats;

// Toggle category keywords expand/collapse
function toggleCategoryKeywords(categoryId) {
    const element = document.getElementById(categoryId);
    const toggle = document.getElementById(categoryId + '-toggle');
    if (element) {
        if (element.style.display === 'none') {
            element.style.display = 'block';
            if (toggle) toggle.textContent = '▼';
        } else {
            element.style.display = 'none';
            if (toggle) toggle.textContent = '▶';
        }
    }
}
window.toggleCategoryKeywords = toggleCategoryKeywords;

// Add keyword to category
function addCategoryKeyword(categorySlug, categoryId) {
    const input = document.getElementById(categoryId + '-input');
    if (!input) return;
    
    const keyword = input.value.trim();
    if (!keyword) {
        alert('Please enter a keyword');
        return;
    }
    
    if (keyword.length < 2) {
        alert('Keyword must be at least 2 characters');
        return;
    }
    
    if (keyword.length > 100) {
        alert('Keyword must be less than 100 characters');
        return;
    }
    
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        alert('Zip code not found');
        return;
    }
    
    // Disable input and show loading
    input.disabled = true;
    const originalValue = input.value;
    
    fetch('/admin/api/category-keyword', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({
            category: categorySlug,
            keyword: keyword,
            zip_code: zipCode
        })
    })
    .then(r => {
        if (!r.ok) {
            return r.json().then(data => {
                throw new Error(data.error || data.message || 'Failed to add keyword');
            });
        }
        return r.json();
    })
    .then(data => {
        if (data.success) {
            input.value = '';
            input.disabled = false;
            // Reload category stats to show new keyword
            loadCategoryStats();
        } else {
            throw new Error(data.error || data.message || 'Failed to add keyword');
        }
    })
    .catch(e => {
        input.disabled = false;
        alert('Error: ' + e.message);
    });
}
window.addCategoryKeyword = addCategoryKeyword;

// Remove keyword from category
function removeCategoryKeyword(categorySlug, keyword, categoryId) {
    if (!confirm(`Remove keyword "${keyword}" from this category?`)) {
        return;
    }
    
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        alert('Zip code not found');
        return;
    }
    
    fetch('/admin/api/category-keyword', {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({
            category: categorySlug,
            keyword: keyword,
            zip_code: zipCode
        })
    })
    .then(r => {
        if (!r.ok) {
            return r.json().then(data => {
                throw new Error(data.error || data.message || 'Failed to remove keyword');
            });
        }
        return r.json();
    })
    .then(data => {
        if (data.success) {
            // Reload category stats to update keyword list
            loadCategoryStats();
        } else {
            throw new Error(data.error || data.message || 'Failed to remove keyword');
        }
    })
    .catch(e => {
        alert('Error: ' + e.message);
    });
}
window.removeCategoryKeyword = removeCategoryKeyword;

// Recategorize all articles
function recategorizeAllArticles() {
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        alert('Zip code not found in URL');
        return;
    }
    
    if (!confirm(`Recategorize all articles for zip code ${zipCode}? This will update categories based on current keywords and training data. This may take a few minutes.`)) {
        return;
    }
    
    // Show loading state
    const button = event?.target || document.querySelector('button[onclick*="recategorizeAllArticles"]');
    const originalText = button?.textContent || '🔄 Recategorize All Articles';
    if (button) {
        button.disabled = true;
        button.textContent = '⏳ Recategorizing...';
    }
    
    fetch('/admin/api/recategorize-all', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({zip_code: zipCode})
    })
    .then(r => {
        if (!r.ok) {
            return r.text().then(text => {
                throw new Error(`HTTP ${r.status}: ${text.substring(0, 100)}`);
            });
        }
        return r.json();
    })
    .then(data => {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
        
        if (data.success) {
            const count = data.message?.match(/\d+/)?.[0] || 'all';
            alert(`Articles recategorized successfully! Updated ${count} articles.`);
        } else {
            alert('Error: ' + (data.message || 'Failed to recategorize articles'));
        }
    })
    .catch(e => {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
        alert('Error: ' + e.message);
    });
}
window.recategorizeAllArticles = recategorizeAllArticles;

// Recalculate all category info
function recalculateCategoryInfo() {
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        alert('Zip code not found in URL');
        return;
    }
    
    if (!confirm(`Recalculate all category information for zip code ${zipCode}? This will update categories, primary categories, and local focus scores for all articles. This may take a few minutes.`)) {
        return;
    }
    
    const button = event?.target || document.querySelector('button[onclick*="recalculateCategoryInfo"]');
    const originalText = button?.textContent || '🔄 Recalculate Category Info';
    if (button) {
        button.disabled = true;
        button.textContent = '⏳ Recalculating...';
    }
    
    fetch('/admin/api/recalculate-categories', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({zip_code: zipCode})
    })
    .then(r => {
        if (!r.ok) {
            return r.text().then(text => {
                throw new Error(`HTTP ${r.status}: ${text.substring(0, 100)}`);
            });
        }
        return r.json();
    })
    .then(data => {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
        
        if (data.success) {
            const count = data.message?.match(/\d+/)?.[0] || 'all';
            alert(`Category info recalculated successfully! Updated ${count} articles.`);
        } else {
            alert('Error: ' + (data.message || 'Failed to recalculate category info'));
        }
    })
    .catch(e => {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
        alert('Error: ' + e.message);
    });
}
window.recalculateCategoryInfo = recalculateCategoryInfo;

// Auto-load category stats when on categories tab
document.addEventListener('DOMContentLoaded', function() {
    if (window.location.pathname.includes('/categories')) {
        setTimeout(loadCategoryStats, 300);
    }
});

// Save regenerate settings
function saveRegenerateSettings() {
    // Get values from input fields (checkboxes may not exist)
    const regenerateIntervalEl = document.getElementById('regenerateInterval');
    const sourceFetchIntervalEl = document.getElementById('sourceFetchInterval');
    
    if (!regenerateIntervalEl || !sourceFetchIntervalEl) {
        alert('Error: Settings fields not found. Please refresh the page.');
        return;
    }
    
    const regenerateInterval = parseInt(regenerateIntervalEl.value || '10');
    const sourceFetchInterval = parseInt(sourceFetchIntervalEl.value || '10');
    
    // Try to get checkboxes if they exist (for backward compatibility)
    const autoRegenerate = document.getElementById('autoRegenerate')?.checked ?? true;
    const regenerateOnLoad = document.getElementById('regenerateOnLoad')?.checked ?? false;
    
    if (isNaN(regenerateInterval) || regenerateInterval < 1 || regenerateInterval > 1440) {
        alert('Regenerate interval must be between 1 and 1440 minutes');
        regenerateIntervalEl.focus();
        return;
    }
    
    if (isNaN(sourceFetchInterval) || sourceFetchInterval < 1 || sourceFetchInterval > 1440) {
        alert('Source fetch interval must be between 1 and 1440 minutes');
        sourceFetchIntervalEl.focus();
        return;
    }
    
    // Show loading state
    const button = event?.target || document.querySelector('button[onclick*="saveRegenerateSettings"]');
    const originalText = button?.textContent || '💾 Save All Settings';
    if (button) {
        button.disabled = true;
        button.textContent = '⏳ Saving...';
    }
    
    fetch('/admin/api/regenerate-settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({
            auto_regenerate: autoRegenerate,
            regenerate_interval: regenerateInterval,
            regenerate_on_load: regenerateOnLoad,
            source_fetch_interval: sourceFetchInterval
        })
    })
    .then(response => response.json())
    .then(data => {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
        
        if (data.success) {
            alert('Settings saved successfully!\n\n' +
                  `Regenerate Interval: ${regenerateInterval} minutes\n` +
                  `Source Fetch Interval: ${sourceFetchInterval} minutes\n\n` +
                  'Note: Restart main.py to apply changes immediately.');
        } else {
            alert('Error saving settings: ' + (data.error || data.message || 'Unknown error'));
        }
    })
    .catch(error => {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
        console.error('Error:', error);
        alert('Error saving settings: ' + error.message);
    });
}
window.saveRegenerateSettings = saveRegenerateSettings;

console.log('Admin script loaded');

