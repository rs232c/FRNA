/**
 * Admin Panel JavaScript
 * All button handlers and event delegation
 * FIXED: 2024-12-11 - Complete event delegation for ALL buttons
 */

console.log('[FRNA Admin] ✅ Admin script loading...');
console.log('[FRNA Admin] Build timestamp:', new Date().toISOString());

// Force dark theme immediately
document.documentElement.classList.add('dark');
document.body.style.background = '#0a0a0a';
document.body.style.color = '#ffffff';

// Toast notification system
function showToast(message, type = 'success') {
    // Remove existing toast
    const existingToast = document.getElementById('adminToast');
    if (existingToast) existingToast.remove();

    // Create new toast
    const toast = document.createElement('div');
    toast.id = 'adminToast';
    toast.className = `fixed top-4 right-4 z-[9999] px-4 py-2 rounded-lg shadow-lg text-white font-medium transition-all duration-300 ${type === 'success' ? 'bg-green-500' : type === 'error' ? 'bg-red-500' : 'bg-blue-500'}`;
    toast.textContent = message;

    document.body.appendChild(toast);

    // Auto remove after 3 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.remove();
        }
    }, 3000);
}

// Unified admin action function
function adminAction(articleId, actionType) {
    console.log(`[FRNA Admin] Executing action: ${actionType} on article ${articleId}`);

    const zipCode = getZipCodeFromUrl();

    fetch(`/admin/action/${articleId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || ''
        },
        credentials: 'same-origin',
        body: JSON.stringify({
            action: actionType,
            zip_code: zipCode
        })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            console.log(`[FRNA Admin] ✅ Action ${actionType} successful:`, data.message);
            showToast(data.message, 'success');

            // Update UI based on action type
            updateUIForAction(articleId, actionType, data);
        } else {
            console.error(`[FRNA Admin] ❌ Action ${actionType} failed:`, data.message);
            showToast(data.message || 'Action failed', 'error');
        }
    })
    .catch(error => {
        console.error(`[FRNA Admin] ❌ Action ${actionType} error:`, error);
        showToast(`Error: ${error.message}`, 'error');
    });
}

// Update UI after successful action
function updateUIForAction(articleId, actionType, data) {
    const articleItem = document.querySelector(`.article-item[data-id="${articleId}"]`);
    if (!articleItem) return;

    switch (actionType) {
        case 'trash':
            articleItem.style.opacity = '0.5';
            articleItem.style.background = 'rgba(255, 0, 0, 0.1)';
            // Update trash button to show restore
            const trashBtn = articleItem.querySelector('.trash-btn');
            if (trashBtn) {
                trashBtn.innerHTML = '🔄';
                trashBtn.className = trashBtn.className.replace('trash-btn', 'restore-btn');
                trashBtn.setAttribute('data-action', 'restore');
                trashBtn.title = 'Restore article';
            }
            break;

        case 'restore':
            articleItem.style.opacity = '1';
            articleItem.style.background = '';
            // Update restore button to show trash
            const restoreBtn = articleItem.querySelector('.restore-btn');
            if (restoreBtn) {
                restoreBtn.innerHTML = '🗑️';
                restoreBtn.className = restoreBtn.className.replace('restore-btn', 'trash-btn');
                restoreBtn.setAttribute('data-action', 'trash');
                restoreBtn.title = 'Move to trash';
            }
            break;

        case 'thumbs_up':
        case 'good_fit':
            const goodFitBtn = articleItem.querySelector('.thumbs-up-btn, .good-fit-btn');
            if (goodFitBtn) {
                goodFitBtn.style.background = '#4caf50';
                goodFitBtn.style.opacity = '1';
                goodFitBtn.setAttribute('data-state', 'on');
            }
            break;

        case 'thumbs_down':
            articleItem.style.opacity = '0.5';
            articleItem.style.background = 'rgba(255, 0, 0, 0.1)';
            break;

        case 'top_story':
            const topStoryBtn = articleItem.querySelector('.top-story-btn');
            if (topStoryBtn) {
                topStoryBtn.style.background = '#ff9800';
                topStoryBtn.style.opacity = '1';
                topStoryBtn.setAttribute('data-state', 'on');
            }
            break;

        case 'alert':
            const alertBtn = articleItem.querySelector('.alert-btn');
            if (alertBtn) {
                alertBtn.style.background = '#ff4444';
                alertBtn.style.opacity = '1';
                alertBtn.setAttribute('data-state', 'on');
            }
            break;
    }

    // Reload page after a short delay for some actions
    if (['thumbs_down', 'top_story', 'alert'].includes(actionType)) {
        setTimeout(() => location.reload(), 500);
    }
}

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

function matchesSelector(target, selector) {
    return target && target.matches && target.matches(selector);
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

// Update the article count in the header
function updateArticleCount() {
    const articlesList = document.getElementById('articles-list');
    const visibleArticles = articlesList.querySelectorAll('.article-item').length;
    const totalArticles = parseInt(articlesList.getAttribute('data-total-articles') || 0);

    const headerDiv = articlesList.querySelector('div');
    if (headerDiv) {
        const isTrash = window.location.pathname.includes('/trash');
        // Get rejected count from data attribute on articles-list
        const rejectedCount = articlesList ? (articlesList.getAttribute('data-rejected-count') || '0') : '0';
        const rejectedText = parseInt(rejectedCount) > 0 ? ` (${rejectedCount} in <a href="${window.location.pathname.replace('/trash', '').replace('/articles', '')}?tab=trash" style="color: #0078d4; text-decoration: underline;">🗑️ Trash</a>)` : '';
        headerDiv.innerHTML = `Showing ${visibleArticles} of ${totalArticles} article${totalArticles !== 1 ? 's' : ''}${isTrash ? '' : rejectedText}`;
    }
}

let showImagesToggleInFlight = false;
let showImagesTogglePromise = Promise.resolve();

// Button handler functions - make globally available
(function() {
    try {
        
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
            
            fetch('/admin/api/toggle-top-story', {
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
        
        // Reject article
        function rejectArticle(articleId) {
            console.log('rejectArticle function called with ID:', articleId);
            if (!articleId) {
                alert('Error: Article ID is missing');
                return;
            }

            const zipCode = getZipCodeFromUrl();

            const requestBody = {
                article_id: articleId,
                rejected: true
            };

            if (zipCode) {
                requestBody.zip_code = zipCode;
            }

            console.log('Making fetch request to /admin/api/reject-article with body:', requestBody);
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
                    // Don't reload for main articles view since UI is already updated
                } else {
                    alert('Error rejecting article: ' + (data ? data.message : 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error rejecting article:', e);
                alert('Error: ' + (e.message || 'Failed to reject article. Please try again.'));
            });
        }
        window.rejectArticle = rejectArticle;

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
                action: 'restore'
            };

            if (zipCode) {
                requestBody.zip_code = zipCode;
            }

            fetch('/admin/api/toggle-article', {
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
                    // Don't reload for main articles view since UI is already updated
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
        
        console.log('[FRNA Admin] ✅ All button handler functions defined:', {
            rejectArticle: typeof window.rejectArticle,
            restoreArticle: typeof window.restoreArticle,
            toggleTopStory: typeof window.toggleTopStory,
            toggleGoodFit: typeof window.toggleGoodFit,
            editArticle: typeof window.editArticle
        });
    } catch(e) {
        console.error('[FRNA Admin] ❌ Error defining button handler functions:', e);
        alert('Script error - check console. Some buttons may not work. Error: ' + e.message);
    }

    // Simplified button click handler - use adminAction for all admin buttons
    console.log('[FRNA Admin] Setting up simplified button event handler...');
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-action], .trash-btn, .restore-btn, .top-story-btn, .thumbs-up-btn, .thumbs-down-btn, .alert-btn, .top-article-btn, .on-target-btn, .off-target-btn, .good-fit-btn');

        if (!btn) return;

        e.preventDefault();
        const articleId = btn.getAttribute('data-id');
        if (!articleId) return;

        // Determine action type from button class or data-action attribute
        let actionType = btn.getAttribute('data-action');

        if (!actionType) {
            if (btn.classList.contains('trash-btn')) actionType = 'trash';
            else if (btn.classList.contains('restore-btn') || btn.classList.contains('restore-trash-btn') || btn.classList.contains('restore-auto-btn')) actionType = 'restore';
            else if (btn.classList.contains('thumbs-up-btn') || btn.classList.contains('good-fit-btn')) actionType = 'thumbs_up';
            else if (btn.classList.contains('thumbs-down-btn')) actionType = 'thumbs_down';
            else if (btn.classList.contains('top-story-btn')) actionType = 'top_story';
            else if (btn.classList.contains('top-article-btn')) actionType = 'top_article';
            else if (btn.classList.contains('alert-btn')) actionType = 'alert';
            else if (btn.classList.contains('on-target-btn')) actionType = 'on_target';
            else if (btn.classList.contains('off-target-btn')) actionType = 'off_target';
        }

        if (actionType) {
            adminAction(articleId, actionType);
        }
    });

    // Special handlers for complex buttons (edit, relevance breakdown, etc.)
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.relevance-breakdown-btn, .edit-article-btn, .add-tags-btn');

        if (!btn) return;

        e.preventDefault();
        const articleId = btn.getAttribute('data-id');

        // Handle relevance breakdown button
        if (btn.classList.contains('relevance-breakdown-btn')) {
            const modal = document.getElementById('relevanceBreakdownModal');
            const body = document.getElementById('relevanceBreakdownBody');
            if (!articleId || !modal || !body) return;

            body.innerHTML = '<div style="padding: 1rem;">Loading breakdown...</div>';
            modal.style.display = 'flex';

            fetch(`/admin/api/get-relevance-breakdown?id=${articleId}`, {
                method: 'GET',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin'
            })
            .then(r => r.json())
            .then(data => {
                if (data.article_id) {
                    body.innerHTML = `
                        <div style="padding: 1rem;">
                            <h3 style="color: #0078d4; margin-bottom: 1rem;">📊 Relevance Score Breakdown</h3>
                            <div style="display: grid; gap: 0.5rem;">
                                <div><strong>Article ID:</strong> ${data.article_id}</div>
                                <div><strong>Relevance Score:</strong> ${data.relevance_score}/100</div>
                                <div><strong>Keywords Matched:</strong> ${data.keywords_matched ? data.keywords_matched.join(', ') : 'None'}</div>
                                <div><strong>Categories Matched:</strong> ${data.categories_matched ? data.categories_matched.join(', ') : 'None'}</div>
                                <div><strong>Negative Factors:</strong> ${data.negative_factors ? data.negative_factors.join(', ') : 'None'}</div>
                                <div><strong>Analysis:</strong> ${data.analysis || 'No analysis available'}</div>
                            </div>
                        </div>
                    `;
                } else {
                    body.innerHTML = '<div style="padding: 1rem; color: #d32f2f;">Error loading relevance breakdown</div>';
                }
            })
            .catch(e => {
                console.error('Error loading relevance breakdown:', e);
                body.innerHTML = '<div style="padding: 1rem; color: #d32f2f;">Error loading relevance breakdown</div>';
            });
        }

        // Handle edit article button
        else if (btn.classList.contains('edit-article-btn')) {
            if (typeof window.editArticle === 'function') {
                window.editArticle(articleId);
            } else {
                showToast('Error: Edit function not available', 'error');
            }
        }

        // Handle add tags button
        else if (btn.classList.contains('add-tags-btn')) {
            if (typeof window.showRejectionTagsModal === 'function') {
                window.showRejectionTagsModal(articleId);
            } else {
                showToast('Error: Tags modal not available', 'error');
            }
        }
    });
    console.log('[FRNA Admin] ✅ Unified button event handler attached inside DOMContentLoaded');
})();

