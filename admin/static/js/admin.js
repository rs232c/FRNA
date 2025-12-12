/**
 * Admin Panel JavaScript
 * All button handlers and event delegation
 * FIXED: 2024-12-11 - Complete event delegation for ALL buttons
 */

console.log('[FRNA Admin] ✅ Admin script loading...');
console.log('[FRNA Admin] Build timestamp:', new Date().toISOString());

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
        // Reject article
        function rejectArticle(articleId) {
            console.log('rejectArticle function called with ID:', articleId);
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
                console.log('performReject called with goToTrash:', goToTrash, 'articleId:', articleId, 'zipCode:', zipCode);
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
})();

// Unified event delegation for all buttons
// FIXED: Include ALL button classes in delegation check
console.log('[FRNA Admin] Event delegation initialized - all buttons should work');
document.addEventListener('click', async (e) => {
    const btn = e.target.closest('button, .trash-btn, .restore-btn, .top-story-btn, .restore-trash-btn, .thumbs-up-btn, .thumbs-down-btn, .alert-btn, .top-article-btn, .on-target-btn, .off-target-btn, .relevance-breakdown-btn, .edit-article-btn, .good-fit-btn, .add-tags-btn');
    
    if (!btn) return;
    
    // Check if this is an admin action button (has data-action OR is one of our button classes)
    const isAdminButton = btn.classList.contains('trash-btn') || 
        btn.classList.contains('restore-btn') || 
        btn.classList.contains('restore-trash-btn') || 
        btn.classList.contains('top-story-btn') ||
        btn.classList.contains('good-fit-btn') ||
        btn.classList.contains('thumbs-up-btn') ||
        btn.classList.contains('thumbs-down-btn') ||
        btn.classList.contains('top-article-btn') ||
        btn.classList.contains('alert-btn') ||
        btn.classList.contains('on-target-btn') ||
        btn.classList.contains('off-target-btn') ||
        btn.classList.contains('relevance-breakdown-btn') ||
        btn.classList.contains('edit-article-btn') ||
        btn.classList.contains('add-tags-btn') ||
        btn.getAttribute('data-action');
    
    if (!isAdminButton) {
        return;
    }
    
    e.preventDefault();
    e.stopPropagation();
    
    // Log which button was clicked for debugging
    console.log('[FRNA Admin] Button clicked:', btn.className, 'action:', btn.getAttribute('data-action'), 'id:', btn.dataset.id);
    
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
        console.log('Trash button clicked:', btn, 'article ID:', btn.getAttribute('data-id'));
        // Also train relevance model when trashing
        const articleId = btn.getAttribute('data-id');
        const zipCode = getZipCodeFromUrl();
        if (articleId && zipCode) {
            fetch('/admin/api/train-relevance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({
                    article_id: articleId,
                    zip_code: zipCode,
                    click_type: 'trash'
                })
            })
            .catch(e => console.error('Error training model:', e));
        }
        if (typeof window.rejectArticle === 'function') {
            console.log('Calling rejectArticle with ID:', articleId);
            window.rejectArticle(articleId);
        } else {
            alert('Error: rejectArticle function not available. Please refresh the page.');
        }
        return;
    }
    
    // Handle add tags button
    if (btn.classList.contains('add-tags-btn')) {
        const articleId = btn.getAttribute('data-id');
        if (typeof window.showRejectionTagsModal === 'function') {
            window.showRejectionTagsModal(articleId);
        } else {
            alert('Error: showRejectionTagsModal function not available. Please refresh the page.');
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
    
    
    if (btn.classList.contains('thumbs-up-btn') || btn.getAttribute('data-action') === 'thumbs-up') {
        const articleId = btn.getAttribute('data-id');
        const zipCode = getZipCodeFromUrl();
        if (articleId && zipCode) {
            // Train relevance model with positive feedback
            fetch('/admin/api/train-relevance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({
                    article_id: articleId,
                    zip_code: zipCode,
                    click_type: 'thumbs_up'
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    // Also toggle good fit state (UI update)
                    const currentState = btn.getAttribute('data-state') === 'on';
                    const newState = !currentState;

                    // Update UI
                    if (newState) {
                        btn.style.background = '#4caf50';
                        btn.style.opacity = '1';
                        btn.setAttribute('data-state', 'on');
                    } else {
                        btn.style.background = 'transparent';
                        btn.style.opacity = '0.5';
                        btn.setAttribute('data-state', 'off');
                    }

                    // Also call the good fit API to persist the state
                    const requestBody = {id: articleId, is_good_fit: newState};
                    if (zipCode) {
                        requestBody.zip_code = zipCode;
                    }

                    return fetch('/admin/api/good-fit', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        credentials: 'same-origin',
                        body: JSON.stringify(requestBody)
                    })
                    .then(r => r.json())
                    .then(goodFitData => {
                        if (!goodFitData.success) {
                            console.warn('Good fit state save failed:', goodFitData.message);
                        }
                    });
                }
            })
            .catch(e => console.error('Error with thumbs up:', e));
        }
        return;
    }
    
    if (btn.classList.contains('thumbs-down-btn') || btn.getAttribute('data-action') === 'thumbs-down') {
        const articleId = btn.getAttribute('data-id');
        const zipCode = getZipCodeFromUrl();
        if (articleId && zipCode) {
            // First, train the relevance model with negative feedback (don't wait for it)
            fetch('/admin/api/train-relevance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({
                    article_id: articleId,
                    zip_code: zipCode,
                    click_type: 'thumbs_down'
                })
            })
            .then(r => r.json())
            .then(data => {
                if (!data.success) {
                    console.warn('Training failed but continuing with reject:', data.message);
                }
            })
            .catch(e => {
                console.warn('Training error (continuing with reject):', e);
            });
            
            // Then, trash/reject the article directly (no confirmation for thumbs down)
            const requestBody = {
                article_id: articleId,
                rejected: true
            };
            
            if (zipCode) {
                requestBody.zip_code = zipCode;
            }
            
            fetch('/admin/api/reject-article', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
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
            .then(result => {
                if (result && result.success) {
                    // Update UI - mark article as rejected
                    const articleItem = btn.closest('.article-item');
                    if (articleItem) {
                        articleItem.classList.add('rejected');
                        articleItem.style.opacity = '0.5';
                    }
                    btn.style.opacity = '1';
                    btn.style.background = '#d32f2f';
                    // Reload to show updated state and pagination
                    setTimeout(() => location.reload(), 500);
                } else {
                    alert('Error rejecting article: ' + (result ? result.message : 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error rejecting article:', e);
                alert('Error: ' + (e.message || 'Failed to reject article. Please try again.'));
            });
        }
        return;
    }

    if (btn.classList.contains('top-story-btn') || btn.getAttribute('data-action') === 'toggle-top-story') {
        const articleId = btn.getAttribute('data-id');
        if (articleId && typeof window.toggleTopStory === 'function') {
            window.toggleTopStory(articleId);
        } else {
            alert('Error: toggleTopStory function not available. Please refresh the page.');
        }
        return;
    }

    if (btn.classList.contains('top-article-btn') || btn.getAttribute('data-action') === 'toggle-top-article') {
        const articleId = btn.getAttribute('data-id');
        const zipCode = getZipCodeFromUrl();
        if (articleId && zipCode) {
            // First, check if this article is currently the top article
            const currentState = btn.getAttribute('data-state') === 'on';

            fetch('/admin/api/toggle-top-article', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({
                    article_id: articleId,
                    zip_code: zipCode
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    // Update all top article buttons to reflect the new state
                    document.querySelectorAll('.top-article-btn').forEach(otherBtn => {
                        const btnArticleId = otherBtn.getAttribute('data-id');
                        if (btnArticleId == articleId) {
                            // This is the button we clicked
                            otherBtn.style.background = '#ffd700';
                            otherBtn.style.opacity = '1';
                            otherBtn.setAttribute('data-state', 'on');
                        } else {
                            // Other buttons should be off
                            otherBtn.style.background = 'transparent';
                            otherBtn.style.opacity = '0.5';
                            otherBtn.setAttribute('data-state', 'off');
                        }
                    });

                    // State updated in-place; no full reload
                } else {
                    alert('Error toggling top article: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error toggling top article:', e);
                alert('Error: ' + (e.message || 'Failed to toggle top article. Please try again.'));
            });
        }
        return;
    }

    if (btn.classList.contains('alert-btn') || btn.getAttribute('data-action') === 'toggle-alert') {
        const articleId = btn.getAttribute('data-id');
        const zipCode = getZipCodeFromUrl();
        if (articleId && zipCode) {
            const isCurrentlyAlert = btn.getAttribute('data-state') === 'on' || (btn.style.background && btn.style.background.includes('#ff4444'));
            const newState = !isCurrentlyAlert;

            fetch('/admin/api/toggle-alert', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({
                    article_id: articleId,
                    zip_code: zipCode,
                    is_alert: newState
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    // Update all alert buttons
                    document.querySelectorAll('.alert-btn').forEach(otherBtn => {
                        if (otherBtn.getAttribute('data-id') == articleId) {
                            otherBtn.style.background = newState ? '#ff4444' : 'transparent';
                            otherBtn.style.opacity = newState ? '1' : '0.5';
                            otherBtn.setAttribute('data-state', newState ? 'on' : 'off');
                        }
                    });
                    // State updated in-place; no full reload
                } else {
                    alert('Error toggling alert: ' + (data.message || data.error || 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error toggling alert:', e);
                alert('Error: ' + (e.message || 'Failed to toggle alert. Please try again.'));
            });
        }
        return;
    }

    if (btn.classList.contains('relevance-breakdown-btn') || btn.getAttribute('data-action') === 'show-breakdown') {
        const articleId = btn.getAttribute('data-id');
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
            if (data.success) {
                const parts = [];
                parts.push(`<div style="margin-bottom: 0.5rem;"><strong>Relevance:</strong> ${data.relevance_score ?? 'N/A'}</div>`);
                parts.push(`<div style="margin-bottom: 0.5rem;"><strong>Local power:</strong> ${data.local_score ?? 'N/A'}</div>`);
                parts.push(`<div style="margin-bottom: 0.5rem;"><strong>Category:</strong> ${data.category || 'N/A'}${data.category_confidence ? ' (' + Math.round(data.category_confidence) + '%)' : ''}</div>`);
                parts.push('<div style="margin: 0.75rem 0; font-weight: 600;">Details:</div>');
                if (data.breakdown && data.breakdown.length) {
                    parts.push('<ul style="margin: 0; padding-left: 1.2rem;">' + data.breakdown.map(item => `<li style="margin-bottom: 0.35rem;">${escapeHtml(item)}</li>`).join('') + '</ul>');
                } else {
                    parts.push('<div>No relevance factors found.</div>');
                }
                body.innerHTML = parts.join('');
            } else {
                body.innerHTML = `<div style="color: #d32f2f; padding: 1rem;">Error: ${escapeHtml(data.error || 'Failed to load breakdown')}</div>`;
            }
        })
        .catch(err => {
            console.error('Error fetching relevance breakdown:', err);
            body.innerHTML = `<div style="color: #d32f2f; padding: 1rem;">Error: ${escapeHtml(err.message || 'Failed to load breakdown')}</div>`;
        });

        return;
    }

    if (btn.classList.contains('target-btn') || btn.getAttribute('data-action') === 'analyze-target') {
        const articleId = btn.getAttribute('data-id') || btn.dataset.id;
        const zipCode = getZipCodeFromUrl();
        console.log('Target button clicked:', { articleId, zipCode, btn: btn });
        
        // Check if button is greyed out (no suggestions available)
        if (btn.getAttribute('data-no-suggestions') === 'true') {
            // Still allow click to show stats, but don't show error
            // The modal will show "no keywords" message
        }
        
        // Remove active state from all target buttons
        document.querySelectorAll('.target-btn').forEach(b => b.classList.remove('active'));
        
        // Add active state to clicked button
        btn.classList.add('active');
        
        if (!articleId) {
            console.error('Article ID missing from button:', btn);
            alert('Error: Article ID is missing');
            btn.classList.remove('active');
            return;
        }
        
        if (!zipCode) {
            console.error('Zip code not found in URL');
            alert('Error: Zip code not found. Please ensure you are on a zip-specific admin page.');
            btn.classList.remove('active');
            return;
        }
        
        // Check if function exists (try both window and global scope)
        const analysisFunc = window.showTargetAnalysis || (typeof showTargetAnalysis !== 'undefined' ? showTargetAnalysis : null);
        if (analysisFunc && typeof analysisFunc === 'function') {
            try {
                analysisFunc(articleId, zipCode);
            } catch (error) {
                console.error('Error calling showTargetAnalysis:', error);
                alert('Error: Failed to analyze article. Check console for details.');
                btn.classList.remove('active');
            }
        } else {
            console.error('showTargetAnalysis function not found. Available:', {
                windowShowTargetAnalysis: typeof window.showTargetAnalysis,
                showTargetAnalysis: typeof showTargetAnalysis,
                windowKeys: Object.keys(window).filter(k => k.includes('Target'))
            });
            alert('Error: Analysis function not loaded. Please refresh the page.');
            btn.classList.remove('active');
        }
        return;
    }

    if (btn.classList.contains('on-target-btn') || btn.getAttribute('data-action') === 'on-target') {
        const articleId = btn.getAttribute('data-id') || btn.dataset.id;
        const zipCode = getZipCodeFromUrl();
        
        if (!articleId || !zipCode) {
            alert('Error: Article ID or zip code missing');
            return;
        }
        
        const isCurrentlyOn = btn.getAttribute('data-state') === 'on';
        const newState = !isCurrentlyOn;
        
        // Update UI immediately
        if (newState) {
            btn.style.background = '#4caf50';
            btn.style.opacity = '1';
            btn.setAttribute('data-state', 'on');
            // Turn off the off-target button if it's active
            const offTargetBtn = document.querySelector(`.off-target-btn[data-id="${articleId}"]`);
            if (offTargetBtn) {
                offTargetBtn.style.background = 'transparent';
                offTargetBtn.style.opacity = '0.5';
                offTargetBtn.setAttribute('data-state', 'off');
            }
        } else {
            btn.style.background = 'transparent';
            btn.style.opacity = '0.5';
            btn.setAttribute('data-state', 'off');
        }
        
        fetch('/admin/api/on-target', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({id: articleId, zip_code: zipCode, is_on_target: newState})
        })
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                // Revert UI on error
                if (newState) {
                    btn.style.background = 'transparent';
                    btn.style.opacity = '0.5';
                    btn.setAttribute('data-state', 'off');
                } else {
                    btn.style.background = '#4caf50';
                    btn.style.opacity = '1';
                    btn.setAttribute('data-state', 'on');
                }
                alert('Error: ' + (data.message || 'Failed to save on-target status'));
            }
        })
        .catch(e => {
            // Revert UI on error
            if (newState) {
                btn.style.background = 'transparent';
                btn.style.opacity = '0.5';
                btn.setAttribute('data-state', 'off');
            } else {
                btn.style.background = '#4caf50';
                btn.style.opacity = '1';
                btn.setAttribute('data-state', 'on');
            }
            alert('Error: ' + (e.message || 'Failed to save on-target status'));
        });
        return;
    }
    
    if (btn.classList.contains('off-target-btn') || btn.getAttribute('data-action') === 'off-target') {
        const articleId = btn.getAttribute('data-id') || btn.dataset.id;
        const zipCode = getZipCodeFromUrl();
        
        if (!articleId || !zipCode) {
            alert('Error: Article ID or zip code missing');
            return;
        }
        
        const isCurrentlyOff = btn.getAttribute('data-state') === 'on';
        const newState = !isCurrentlyOff;
        
        // Update UI immediately
        if (newState) {
            btn.style.background = '#f44336';
            btn.style.opacity = '1';
            btn.setAttribute('data-state', 'on');
            // Turn off the on-target button if it's active
            const onTargetBtn = document.querySelector(`.on-target-btn[data-id="${articleId}"]`);
            if (onTargetBtn) {
                onTargetBtn.style.background = 'transparent';
                onTargetBtn.style.opacity = '0.5';
                onTargetBtn.setAttribute('data-state', 'off');
            }
        } else {
            btn.style.background = 'transparent';
            btn.style.opacity = '0.5';
            btn.setAttribute('data-state', 'off');
        }
        
        fetch('/admin/api/off-target', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({id: articleId, zip_code: zipCode})
        })
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                // Revert UI on error
                if (newState) {
                    btn.style.background = 'transparent';
                    btn.style.opacity = '0.5';
                    btn.setAttribute('data-state', 'off');
                } else {
                    btn.style.background = '#f44336';
                    btn.style.opacity = '1';
                    btn.setAttribute('data-state', 'on');
                }
                alert('Error: ' + (data.message || 'Failed to save off-target status'));
            }
        })
        .catch(e => {
            // Revert UI on error
            if (newState) {
                btn.style.background = 'transparent';
                btn.style.opacity = '0.5';
                btn.setAttribute('data-state', 'off');
            } else {
                btn.style.background = '#f44336';
                btn.style.opacity = '1';
                btn.setAttribute('data-state', 'on');
            }
            alert('Error: ' + (e.message || 'Failed to save off-target status'));
        });
        return;
    }
    
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
        
        // Build rejection reason display for both auto-filtered and manually rejected articles
        let rejectionReasonHtml = '';
        if (article.auto_reject_reason) {
            const reason = article.auto_reject_reason;
            const safeReason = escapeHtml(reason);
            
            // Parse tag information from reason
            let matchedTags = [];
            let missingTags = [];
            let baseReason = reason;
            
            // Check if reason contains tag information
            if (reason.includes('| Matched:') || reason.includes('| Missing:')) {
                const parts = reason.split(' | ');
                baseReason = parts[0]; // First part is the base reason
                
                for (let i = 1; i < parts.length; i++) {
                    const part = parts[i];
                    if (part.startsWith('Matched: ')) {
                        const tags = part.substring(9).split(', ');
                        matchedTags = tags;
                    } else if (part.startsWith('Missing: ')) {
                        const tags = part.substring(9).split(', ');
                        missingTags = tags;
                    }
                }
            }
            
            let tagDisplayHtml = '';
            if (matchedTags.length > 0 || missingTags.length > 0) {
                tagDisplayHtml = '<div style="margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid #404040;">';
                
                if (matchedTags.length > 0) {
                    tagDisplayHtml += '<div style="margin-bottom: 0.5rem;">';
                    tagDisplayHtml += '<strong style="color: #4caf50; font-size: 0.8rem;">✓ Matched Tags:</strong>';
                    tagDisplayHtml += '<div style="display: flex; flex-wrap: wrap; gap: 0.25rem; margin-top: 0.25rem;">';
                    matchedTags.forEach(tag => {
                        const safeTag = escapeHtml(tag);
                        tagDisplayHtml += `<span style="background: rgba(76, 175, 80, 0.2); color: #4caf50; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; border: 1px solid rgba(76, 175, 80, 0.3);">${safeTag}</span>`;
                    });
                    tagDisplayHtml += '</div></div>';
                }
                
                if (missingTags.length > 0) {
                    tagDisplayHtml += '<div>';
                    tagDisplayHtml += '<strong style="color: #ff9800; font-size: 0.8rem;">✗ Missing Tags:</strong>';
                    tagDisplayHtml += '<div style="display: flex; flex-wrap: wrap; gap: 0.25rem; margin-top: 0.25rem;">';
                    missingTags.forEach(tag => {
                        const safeTag = escapeHtml(tag);
                        tagDisplayHtml += `<span style="background: rgba(255, 152, 0, 0.2); color: #ff9800; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; border: 1px solid rgba(255, 152, 0, 0.3);">${safeTag}</span>`;
                    });
                    tagDisplayHtml += '</div></div>';
                }
                
                tagDisplayHtml += '</div>';
            }
            
            // Determine header text and color based on rejection type
            const headerText = isAuto ? '🤖 Auto-filter reason:' : '🗑️ Rejection reason:';
            const borderColor = isAuto ? '#ff9800' : '#d32f2f';
            const bgColor = isAuto ? 'rgba(255, 152, 0, 0.1)' : 'rgba(211, 47, 47, 0.1)';
            const textColor = isAuto ? '#ff9800' : '#d32f2f';
            
            rejectionReasonHtml = '<div style="font-size: 0.85rem; color: ' + textColor + '; margin-top: 0.5rem; padding: 0.75rem; background: ' + bgColor + '; border-left: 3px solid ' + borderColor + '; border-radius: 4px;">' +
                '<strong>' + headerText + '</strong> ' + escapeHtml(baseReason) +
                tagDisplayHtml +
                '</div>';
        }
        
        // Build tags display
        let tagsHtml = '';
        if (article.rejection_tags) {
            const tags = article.rejection_tags.split(',').map(t => t.trim()).filter(t => t);
            if (tags.length > 0) {
                tagsHtml = '<div style="margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid #404040;">' +
                    '<strong style="color: #667eea; font-size: 0.8rem;">🏷️ Rejection Tags:</strong>' +
                    '<div style="display: flex; flex-wrap: wrap; gap: 0.25rem; margin-top: 0.25rem;">';
                tags.forEach(tag => {
                    tagsHtml += `<span style="background: rgba(102, 126, 234, 0.2); color: #667eea; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; border: 1px solid rgba(102, 126, 234, 0.3);">${escapeHtml(tag)}</span>`;
                });
                tagsHtml += '</div></div>';
            }
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
            tagsHtml +
            '</div>' +
            '<div style="display: flex; gap: 0.75rem; margin-top: 1rem;">' +
            '<button class="add-tags-btn" data-id="' + escapeAttr(safeArticleId) + '" style="background: #667eea; color: white; padding: 0.5rem 1rem; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.9rem;">🏷️ Add Tags</button>' +
            '<button class="restore-trash-btn" data-id="' + escapeAttr(safeArticleId) + '" data-rejection-type="' + escapeAttr(rejectionType) + '" style="background: #4caf50; color: white; padding: 0.5rem 1rem; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.9rem;">↩️ Restore</button>' +
            '</div>' +
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

// Rejection tags management
let currentModalTags = [];

function showRejectionTagsModal(articleId) {
    // Get current tags first
    const article = allTrashArticles.find(a => a.id == articleId);
    const currentTags = article?.rejection_tags ? article.rejection_tags.split(',').map(t => t.trim()).filter(t => t) : [];
    currentModalTags = [...currentTags];
    
    // Get suggestions
    const zipCode = getZipCodeFromUrl();
    let url = `/admin/api/get-rejection-tag-suggestions?article_id=${encodeURIComponent(articleId)}`;
    if (zipCode) {
        url += `&zip_code=${encodeURIComponent(zipCode)}`;
    }
    
    fetch(url, {
        credentials: "same-origin",
        headers: {"Accept": "application/json"}
    })
    .then(r => r.json())
    .then(data => {
        if (!data.success) {
            alert('Error loading suggestions: ' + (data.message || 'Unknown error'));
            return;
        }
        
        const suggestions = data.suggestions;
        
        // Create modal
        let modal = document.getElementById('rejectionTagsModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'rejectionTagsModal';
            modal.className = 'modal';
            modal.style.display = 'none';
            document.body.appendChild(modal);
        }
        
        // Build suggestions HTML
        let suggestionsHtml = '';
        
        if (suggestions.towns && suggestions.towns.length > 0) {
            suggestionsHtml += '<div style="margin-bottom: 1rem;"><strong style="color: #e0e0e0; font-size: 0.9rem;">📍 Nearby Towns (from article):</strong><div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem;">';
            suggestions.towns.forEach(town => {
                suggestionsHtml += `<button class="tag-suggestion-btn" data-tag="${escapeAttr(town)}" style="padding: 0.4rem 0.8rem; background: #667eea; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 0.85rem;">${escapeHtml(town)}</button>`;
            });
            suggestionsHtml += '</div></div>';
        }
        
        if (suggestions.all_nearby_towns && suggestions.all_nearby_towns.length > 0) {
            suggestionsHtml += '<div style="margin-bottom: 1rem;"><strong style="color: #e0e0e0; font-size: 0.9rem;">🗺️ All Nearby Towns:</strong><div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem;">';
            suggestions.all_nearby_towns.forEach(town => {
                if (!suggestions.towns || !suggestions.towns.includes(town)) {
                    suggestionsHtml += `<button class="tag-suggestion-btn" data-tag="${escapeAttr(town)}" style="padding: 0.4rem 0.8rem; background: #555; color: #e0e0e0; border: 1px solid #777; border-radius: 4px; cursor: pointer; font-size: 0.85rem;">${escapeHtml(town)}</button>`;
                }
            });
            suggestionsHtml += '</div></div>';
        }
        
        if (suggestions.common_reasons && suggestions.common_reasons.length > 0) {
            suggestionsHtml += '<div style="margin-bottom: 1rem;"><strong style="color: #e0e0e0; font-size: 0.9rem;">📋 Common Reasons:</strong><div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem;">';
            suggestions.common_reasons.forEach(reason => {
                suggestionsHtml += `<button class="tag-suggestion-btn" data-tag="${escapeAttr(reason)}" style="padding: 0.4rem 0.8rem; background: #555; color: #e0e0e0; border: 1px solid #777; border-radius: 4px; cursor: pointer; font-size: 0.85rem;">${escapeHtml(reason)}</button>`;
            });
            suggestionsHtml += '</div></div>';
        }
        
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 600px; max-height: 80vh; overflow-y: auto;">
                <div class="modal-header">
                    <h2>Add Rejection Tags</h2>
                    <span class="close-modal" onclick="closeRejectionTagsModal()">&times;</span>
                </div>
                <div style="padding: 1.5rem;">
                    <div style="margin-bottom: 1.5rem;">
                        <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">Current Tags:</label>
                        <div id="currentTagsContainer" style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; min-height: 2rem; padding: 0.5rem; background: #1a1a1a; border-radius: 4px; border: 1px solid #404040;">
                        </div>
                    </div>
                    
                    <div style="margin-bottom: 1.5rem;">
                        <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">Suggestions:</label>
                        <div style="background: #1a1a1a; padding: 1rem; border-radius: 4px; border: 1px solid #404040;">
                            ${suggestionsHtml || '<p style="color: #888; font-style: italic;">No suggestions available</p>'}
                        </div>
                    </div>
                    
                    <div style="margin-bottom: 1.5rem;">
                        <label style="display: block; color: #e0e0e0; margin-bottom: 0.5rem; font-weight: 600;">Add Custom Tag:</label>
                        <div style="display: flex; gap: 0.5rem;">
                            <input type="text" id="customTagInput" placeholder="Enter custom tag..." style="flex: 1; padding: 0.5rem; background: #1a1a1a; border: 1px solid #404040; border-radius: 4px; color: #e0e0e0; font-size: 0.9rem;" onkeypress="if(event.key==='Enter') addCustomTag()">
                            <button onclick="addCustomTag()" style="padding: 0.5rem 1rem; background: #667eea; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Add</button>
                        </div>
                    </div>
                    
                    <div style="display: flex; gap: 0.75rem; justify-content: flex-end;">
                        <button type="button" onclick="closeRejectionTagsModal()" style="padding: 0.75rem 1.5rem; background: #666; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Cancel</button>
                        <button type="button" id="saveTagsBtn" style="padding: 0.75rem 1.5rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Save Tags</button>
                    </div>
                </div>
            </div>
        `;
        
        modal.style.display = 'flex';
        
        // Store article ID
        modal.dataset.articleId = articleId;
        
        // Update tags display
        updateModalTagsDisplay();
        
        // Add event listeners
        document.querySelectorAll('.tag-suggestion-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const tag = this.dataset.tag;
                addTagToModal(tag);
            });
        });
        
        document.getElementById('saveTagsBtn').addEventListener('click', function() {
            saveRejectionTags(articleId);
        });
        
        // Close on outside click
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                closeRejectionTagsModal();
            }
        });
    })
    .catch(e => {
        console.error('Error loading suggestions:', e);
        alert('Error loading tag suggestions: ' + e.message);
    });
}

function addTagToModal(tag) {
    if (tag && !currentModalTags.includes(tag)) {
        currentModalTags.push(tag);
        updateModalTagsDisplay();
    }
}

function removeTag(tag) {
    currentModalTags = currentModalTags.filter(t => t !== tag);
    updateModalTagsDisplay();
}

function addCustomTag() {
    const input = document.getElementById('customTagInput');
    const tag = input.value.trim();
    if (tag && !currentModalTags.includes(tag)) {
        currentModalTags.push(tag);
        input.value = '';
        updateModalTagsDisplay();
    }
}

function updateModalTagsDisplay() {
    const container = document.getElementById('currentTagsContainer');
    if (!container) return;
    
    if (currentModalTags.length > 0) {
        container.innerHTML = currentModalTags.map(tag => `
            <span style="display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0.8rem; background: #667eea; color: white; border-radius: 4px; font-size: 0.85rem;">
                ${escapeHtml(tag)}
                <button onclick="removeTag('${escapeAttr(tag)}')" style="background: rgba(255,255,255,0.2); border: none; color: white; border-radius: 50%; width: 1.2rem; height: 1.2rem; cursor: pointer; font-size: 0.7rem; padding: 0; line-height: 1;">×</button>
            </span>
        `).join('');
        
        // Re-attach remove handlers
        container.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('click', function() {
                const tagSpan = this.parentElement;
                const tag = tagSpan.textContent.trim().replace('×', '').trim();
                removeTag(tag);
            });
        });
    } else {
        container.innerHTML = '<span style="color: #888; font-style: italic;">No tags yet</span>';
    }
}

function closeRejectionTagsModal() {
    const modal = document.getElementById('rejectionTagsModal');
    if (modal) {
        modal.style.display = 'none';
        currentModalTags = [];
    }
}

function saveRejectionTags(articleId) {
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        alert('Zip code not found');
        return;
    }
    
    fetch('/admin/api/update-rejection-tags', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({
            article_id: articleId,
            tags: currentModalTags,
            zip_code: zipCode
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            closeRejectionTagsModal();
            // Reload trash to show updated tags
            if (typeof window.loadTrash === 'function') {
                window.loadTrash();
            }
        } else {
            alert('Error saving tags: ' + (data.message || 'Unknown error'));
        }
    })
    .catch(e => {
        console.error('Error saving tags:', e);
        alert('Error: ' + e.message);
    });
}

window.showRejectionTagsModal = showRejectionTagsModal;
window.closeRejectionTagsModal = closeRejectionTagsModal;
window.removeTag = removeTag;
window.addCustomTag = addCustomTag;

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
    if (!zipCode) {
        console.error('No zip code found in URL');
        const trashList = document.getElementById('trashList');
        if (trashList) {
            trashList.innerHTML = '<p style="padding: 2rem; text-align: center; color: #d32f2f; background: #252525; border-radius: 8px; border: 1px solid #404040;">' +
                '<strong>Error:</strong> Zip code not found in URL. Please navigate to /admin/[zip_code]/trash<br>' +
                '<button class="retry-trash-btn" style="margin-top: 1rem; padding: 0.5rem 1rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer;">Retry</button>' +
                '</p>';
        }
        return;
    }
    
    let url = '/admin/api/get-rejected-articles?zip_code=' + encodeURIComponent(zipCode);
    
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

// Handle retry button for trash page
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('retry-trash-btn')) {
        console.log('Retry trash button clicked');
        if (typeof window.loadTrash === 'function') {
            window.loadTrash();
        } else {
            console.error('loadTrash function not available');
            alert('Error: Cannot reload trash page. Please refresh the page.');
        }
    }
});

// Setup filter button handlers and search input
// Handle Load More button
document.addEventListener('click', function(e) {
    if (e.target.id === 'loadMoreBtn') {
        const btn = e.target;
        const offset = parseInt(btn.getAttribute('data-offset'));
        const zipCode = btn.getAttribute('data-zip-code');
        const showTrash = btn.getAttribute('data-show-trash') === 'true';

        btn.textContent = 'Loading...';
        btn.disabled = true;

        fetch(`/admin/${zipCode}/articles?offset=${offset}&show_trash=${showTrash}`, {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(r => r.text())
        .then(html => {
            // The response should be just the article HTML
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = html.trim();

            const newArticles = tempDiv.querySelectorAll('.article-item');

            const articlesList = document.getElementById('articles-list');
            const loadMoreContainer = btn.parentNode;

            newArticles.forEach(article => {
                articlesList.insertBefore(article, loadMoreContainer);
            });

            // Update the offset and button text
            const newOffset = offset + newArticles.length;
            btn.setAttribute('data-offset', newOffset);

            // Get total count from the articles list data attribute
            const totalArticles = parseInt(articlesList.getAttribute('data-total-articles') || 0);

            if (newOffset >= totalArticles) {
                // No more articles to load
                loadMoreContainer.remove();
            } else {
                // Update button text with remaining count
                const remaining = totalArticles - newOffset;
                btn.textContent = `Load More Articles (${remaining} remaining)`;
                btn.disabled = false;
            }
        })
        .catch(e => {
            console.error('Error loading more articles:', e);
            btn.textContent = 'Error loading articles';
            setTimeout(() => {
                btn.textContent = `Load More Articles`;
                btn.disabled = false;
            }, 2000);
        });
    }
});

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
        if (matchesSelector(e.target, '#showImages') || matchesSelector(e.target, '#showImagesSettings')) {
            const zipCode = getZipCodeFromUrl();
            const newValue = e.target.checked;
            const requestBody = {show_images: newValue};
            if (zipCode) {
                requestBody.zip_code = zipCode;
            }
            
            // #region agent log
            console.log('Toggle images: setting to', newValue, 'requestBody:', requestBody);
            fetch('http://127.0.0.1:7242/ingest/9497b7ee-78b4-45c5-99fd-3c5b05e85c0a', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    sessionId: 'debug-session',
                    runId: 'toggle-frontend',
                    hypothesisId: 'K',
                    location: 'admin/static/js/admin.js:1596',
                    message: 'Frontend toggle-images called',
                    data: {newValue: newValue, requestBody: requestBody, checkboxId: e.target.id},
                    timestamp: Date.now()
                })
            }).catch(() => {});
            // #endregion
            
            showImagesToggleInFlight = true;
            showImagesTogglePromise = fetch('/admin/api/toggle-images', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify(requestBody)
            })
            .then(r => r.json())
            .then(data => {
                // #region agent log
                console.log('Toggle images response:', data);
                fetch('http://127.0.0.1:7242/ingest/9497b7ee-78b4-45c5-99fd-3c5b05e85c0a', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        sessionId: 'debug-session',
                        runId: 'toggle-frontend',
                        hypothesisId: 'K',
                        location: 'admin/static/js/admin.js:1610',
                        message: 'Toggle images response received',
                        data: {success: data.success, show_images: data.show_images, response: data},
                        timestamp: Date.now()
                    })
                }).catch(() => {});
                // #endregion
                
                if (data.success) {
                    const otherCheckbox = e.target.matches('#showImages') ? 
                        document.getElementById('showImagesSettings') : 
                        document.getElementById('showImages');
                    if (otherCheckbox) {
                        otherCheckbox.checked = e.target.checked;
                    }
                    // #region agent log
                    console.log('Checkbox state synced. Current state:', e.target.checked);
                    fetch('http://127.0.0.1:7242/ingest/9497b7ee-78b4-45c5-99fd-3c5b05e85c0a', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            sessionId: 'debug-session',
                            runId: 'toggle-frontend',
                            hypothesisId: 'K',
                            location: 'admin/static/js/admin.js:1618',
                            message: 'Checkbox state after sync',
                            data: {checkboxChecked: e.target.checked, otherCheckboxChecked: otherCheckbox ? otherCheckbox.checked : null},
                            timestamp: Date.now()
                        })
                    }).catch(() => {});
                    // #endregion
                } else {
                    // #region agent log
                    console.error('Toggle images failed:', data);
                    fetch('http://127.0.0.1:7242/ingest/9497b7ee-78b4-45c5-99fd-3c5b05e85c0a', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            sessionId: 'debug-session',
                            runId: 'toggle-frontend',
                            hypothesisId: 'K',
                            location: 'admin/static/js/admin.js:1625',
                            message: 'Toggle images failed',
                            data: {error: data.error || 'Unknown error', response: data},
                            timestamp: Date.now()
                        })
                    }).catch(() => {});
                    // #endregion
                    // Revert checkbox on failure
                    e.target.checked = !e.target.checked;
                }
            })
            .catch(e => {
                console.error('Error toggling images:', e);
                // #region agent log
                fetch('http://127.0.0.1:7242/ingest/9497b7ee-78b4-45c5-99fd-3c5b05e85c0a', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        sessionId: 'debug-session',
                        runId: 'toggle-frontend',
                        hypothesisId: 'K',
                        location: 'admin/static/js/admin.js:1635',
                        message: 'Toggle images network error',
                        data: {error: e.message || String(e)},
                        timestamp: Date.now()
                    })
                }).catch(() => {});
                // #endregion
                e.target.checked = !e.target.checked;
            })
            .finally(() => {
                showImagesToggleInFlight = false;
            });
        }
        
        // Source enabled toggle (new button style)
        if (matchesSelector(e.target, '.source-enabled-btn') || e.target.closest('.source-enabled-btn')) {
            const btn = e.target.closest('.source-enabled-btn') || e.target;
            const sourceKey = btn.dataset.source;
            const currentState = btn.dataset.state === 'on';
            const newState = !currentState;
            
            // Update UI immediately
            btn.dataset.state = newState ? 'on' : 'off';
            btn.style.background = newState ? '#4caf50' : 'transparent';
            btn.style.opacity = newState ? '1' : '0.5';
            btn.textContent = newState ? '✓' : '✕';
            btn.title = newState ? 'Disable source' : 'Enable source';
            
            // Save to server
            const zipCode = getZipCodeFromUrl();
            const requestBody = {
                source: sourceKey,
                setting: 'enabled',
                value: newState
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
                if (!data.success) {
                    // Revert on error
                    btn.dataset.state = currentState ? 'on' : 'off';
                    btn.style.background = currentState ? '#4caf50' : 'transparent';
                    btn.style.opacity = currentState ? '1' : '0.5';
                    btn.textContent = currentState ? '✓' : '✕';
                    btn.title = currentState ? 'Disable source' : 'Enable source';
                    alert('Error saving source setting: ' + (data.message || 'Unknown error'));
                } else {
                    // Show success indicator
                    const indicator = document.createElement('span');
                    indicator.style.cssText = 'color: #4caf50; margin-left: 0.5rem; font-size: 0.85rem; font-weight: 600;';
                    indicator.textContent = '✓ Saved';
                    btn.parentElement.appendChild(indicator);
                    setTimeout(() => indicator.remove(), 2000);
                }
            })
            .catch(e => {
                // Revert on error
                btn.dataset.state = currentState ? 'on' : 'off';
                btn.style.background = currentState ? '#4caf50' : 'transparent';
                btn.style.opacity = currentState ? '1' : '0.5';
                btn.textContent = currentState ? '✓' : '✕';
                btn.title = currentState ? 'Disable source' : 'Enable source';
                alert('Error: ' + e.message);
            });
        }
        
        // Edit source button
        if (matchesSelector(e.target, '.edit-source-btn') || e.target.closest('.edit-source-btn')) {
            const btn = e.target.closest('.edit-source-btn') || e.target;
            const sourceKey = btn.getAttribute('data-source-key') || btn.dataset.sourceKey;
            if (sourceKey && typeof window.editSource === 'function') {
                e.preventDefault();
                e.stopPropagation();
                window.editSource(sourceKey);
            }
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
        if (matchesSelector(e.target, '.relevance-score-tooltip')) {
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
                    
                    // Header with scores
                    const header = document.createElement('div');
                    header.style.cssText = 'margin-bottom: 0.5rem; color: #fff;';
                    header.innerHTML = `
                        <div style="font-weight: 700; margin-bottom: 0.25rem;">Relevance: ${data.relevance_score ?? 'N/A'}</div>
                        <div style="font-weight: 700; margin-bottom: 0.25rem;">Local power: ${data.local_score ?? 'N/A'}</div>
                        <div style="font-weight: 700;">Category: ${data.category || 'N/A'}${data.category_confidence ? ' (' + Math.round(data.category_confidence) + '%)' : ''}</div>
                    `;
                    tooltipElement.appendChild(header);

                    // Create content
                    const title = document.createElement('div');
                    title.textContent = 'Relevance Breakdown:';
                    title.style.cssText = 'font-weight: 600; margin-bottom: 0.5rem; color: #fff;';
                    tooltipElement.appendChild(title);
                    
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
        if (matchesSelector(e.target, '.relevance-score-tooltip')) {
            tooltipTimeout = setTimeout(function() {
                if (tooltipElement) {
                    tooltipElement.remove();
                    tooltipElement = null;
                }
            }, 200);
        }
    }, true);

    // Modal close for relevance breakdown
    const relevanceModal = document.getElementById('relevanceBreakdownModal');
    const relevanceClose = document.getElementById('relevanceBreakdownClose');
    if (relevanceClose) {
        relevanceClose.addEventListener('click', () => {
            if (relevanceModal) relevanceModal.style.display = 'none';
        });
    }
    if (relevanceModal) {
        relevanceModal.addEventListener('click', (e) => {
            if (e.target === relevanceModal) {
                relevanceModal.style.display = 'none';
            }
        });
    }
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

// Regenerate website for current zip code (fast, quick regenerate)
// If no zip_code, regenerates main website_output directory
async function regenerateWebsite(evt) {
    let zipCode = getZipCodeFromUrl();

    if (!zipCode) {
        const pathMatch = window.location.pathname.match(/\/admin\/(\d{5})/);
        if (pathMatch) {
            zipCode = pathMatch[1];
        }
    }

    if (!zipCode) {
        const zipElement = document.querySelector('[data-zip-code]');
        if (zipElement) zipCode = zipElement.getAttribute('data-zip-code');
    }

    if (showImagesToggleInFlight) {
        await showImagesTogglePromise;
    }
    const regenMessage = `Regenerating rebuilds the cached static site to apply the image toggle. Source fetches are throttled to roughly five minutes, so this only rewrites the front-end output—proceed?`;
    if (!confirm(regenMessage)) {
        return;
    }

    // Allow regeneration without zip_code (generates to main website_output)
    // if (!zipCode) {
    //     alert('Zip code not found. Navigate to a zip-specific admin page.');
    //     console.error('Unable to determine zip code for regeneration from URL or page.');
    //     return;
    // }

    const button = evt?.target || document.querySelector('button[onclick*="regenerateWebsite"]');
    const originalText = button?.textContent || 'Regenerate Website';

    if (button) {
        button.disabled = true;
        button.textContent = '⏳ Regenerating...';
        button.style.opacity = '0.6';
        button.style.cursor = 'wait';
    }

    const createProgressBox = () => {
        const existing = document.getElementById('regenProgress');
        if (existing) existing.remove();

        const wrapper = document.createElement('div');
        wrapper.id = 'regenProgress';
        wrapper.style.cssText = 'margin-top: 1rem; padding: 1rem; background: #121212; border: 1px solid #333; border-radius: 10px; font-size: 0.9rem;';
        wrapper.innerHTML = `
            <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:0.6rem;">
                <div class="regen-spinner" style="width:18px;height:18px;border:2px solid #333;border-top:2px solid #38bdf8;border-radius:50%;animation:regenSpin 1s linear infinite;"></div>
                <strong style="color:#38bdf8;">Regenerating website${zipCode ? ' for ' + zipCode : ''}...</strong>
            </div>
            <div id="regenStatus" style="color:#888;">⏳ Starting quick regeneration</div>
        `;
        if (!document.getElementById('regenSpinnerStyle')) {
            const style = document.createElement('style');
            style.id = 'regenSpinnerStyle';
            style.textContent = '@keyframes regenSpin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }';
            document.head.appendChild(style);
        }
        return wrapper;
    };

        const progressBox = createProgressBox();
        if (button?.parentElement) {
            button.parentElement.insertBefore(progressBox, button.nextSibling);
        } else {
            document.body.appendChild(progressBox);
        }

        const updateStatus = message => {
            const statusEl = document.getElementById('regenStatus');
            if (statusEl) statusEl.textContent = message;
        };
        
        // Update progress box message if no zip_code
        if (!zipCode && progressBox) {
            const statusEl = progressBox.querySelector('#regenStatus');
            if (statusEl) {
                statusEl.textContent = '⏳ Starting quick regeneration (main website)...';
            }
            const strongEl = progressBox.querySelector('strong');
            if (strongEl) {
                strongEl.textContent = 'Regenerating main website...';
            }
        }

    const finalize = (message, isError = false) => {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
            button.style.opacity = '1';
            button.style.cursor = 'pointer';
        }

        if (progressBox) {
            progressBox.style.borderColor = isError ? '#dc2626' : '#22c55e';
            progressBox.innerHTML = `<div style="color:${isError ? '#f87171' : '#22c55e'}; font-weight:600;">${isError ? '✗ ' : '✓ '} ${message}</div>`;
            setTimeout(() => progressBox.remove(), 5000);
        }
    };

    const requestBody = {};
    if (zipCode) {
        requestBody.zip_code = zipCode;
    }
    
    fetch('/admin/api/regenerate', {
        method: 'POST',
        cache: 'no-store',
        headers: {
            'Content-Type': 'application/json',
            'Cache-Control': 'no-store'
        },
        credentials: 'same-origin',
        body: JSON.stringify(requestBody)
    })
    .then(async r => {
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
            throw new Error(data.message || `HTTP ${r.status}`);
        }
        return data;
    })
    .then(data => {
        if (data.success) {
            updateStatus('✓ Quick regeneration kicked off. Estimating 30-60 seconds.');
            setTimeout(() => finalize('Website regenerated successfully!'), 60000);
        } else {
            throw new Error(data.message || 'Failed to regenerate website');
        }
    })
    .catch(err => {
        console.error('Regeneration error:', err);
        finalize(err.message || 'Failed to regenerate website', true);
    });
}
window.regenerateWebsite = regenerateWebsite;

// Regenerate all websites (with fresh data)
function regenerateAll() {
    const zipCode = getZipCodeFromUrl();
    
    // If we're on a zip-specific admin page, regenerate that zip with fresh data
    if (zipCode) {
        if (!confirm(`Regenerate website for zip code ${zipCode} with fresh data from all sources? This may take several minutes.`)) {
            return;
        }
        
        const btn = event?.target || document.querySelector('button[onclick*="regenerateAll"]');
        const originalText = btn?.textContent || '🔄 Regenerate All (Fresh Data)';
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Fetching fresh data...';
        }
        
        fetch('/admin/api/regenerate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({ force_refresh: true, zip_code: zipCode })
        })
        .then(r => r.json())
        .then(data => {
            if (btn) {
                btn.disabled = false;
                btn.textContent = originalText;
            }
            if (data.success) {
                alert('Website regenerated with fresh data from all sources!');
            } else {
                alert('Error: ' + (data.message || 'Failed to regenerate website'));
            }
        })
        .catch(e => {
            if (btn) {
                btn.disabled = false;
                btn.textContent = originalText;
            }
            alert('Error: ' + (e.message || 'Failed to regenerate website'));
        });
    } else {
        // Main admin - regenerate all zip codes
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
}
window.regenerateAll = regenerateAll;

// Rerun relevance scoring on all articles
function rerunRelevanceScoring() {
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        alert('Zip code not found in URL');
        return;
    }
    
    if (!confirm(`This will recalculate relevance scores for ALL articles and move articles that fail relevance to trash. This may take several minutes. Continue?`)) {
        return;
    }
    
    const btn = document.getElementById('rerunRelevanceBtn');
    const statusDiv = document.getElementById('rerunRelevanceStatus');
    const originalText = btn.textContent;
    
    btn.disabled = true;
    btn.textContent = 'Processing...';
    statusDiv.style.display = 'block';
    statusDiv.querySelector('p').textContent = 'Starting relevance recalculation...';
    
    fetch('/admin/api/rerun-relevance-scoring', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({ zip_code: zipCode })
    })
    .then(async r => {
        // Check if response is JSON
        const contentType = r.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            // Response is not JSON - likely an HTML error page
            const text = await r.text();
            throw new Error(`Server returned ${r.status} ${r.statusText}. Response: ${text.substring(0, 200)}`);
        }
        return r.json();
    })
    .then(data => {
        btn.disabled = false;
        btn.textContent = originalText;
        
        if (data.success) {
            statusDiv.querySelector('p').innerHTML = `
                <strong style="color: #4caf50;">✓ Success!</strong><br>
                Processed ${data.processed_count || 0} articles<br>
                ${data.auto_rejected_count || 0} articles moved to trash<br>
                ${data.kept_count || 0} articles kept
            `;
        } else {
            statusDiv.querySelector('p').innerHTML = `<strong style="color: #f44336;">Error:</strong> ${data.message || 'Unknown error'}`;
        }
    })
    .catch(e => {
        btn.disabled = false;
        btn.textContent = originalText;
        statusDiv.querySelector('p').innerHTML = `<strong style="color: #f44336;">Error:</strong> ${e.message || 'Failed to rerun relevance scoring'}`;
        console.error('Rerun relevance scoring error:', e);
    });
}
window.rerunRelevanceScoring = rerunRelevanceScoring;

// Add new source
function addNewSource() {
    // Show edit modal with empty source
    showEditSourceModal({
        key: '',
        name: '',
        url: '',
        rss: '',
        category: 'news',
        relevance_score: ''
    });
}
window.addNewSource = addNewSource;

// Edit source
function editSource(sourceKey) {
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        alert('Zip code not found');
        return;
    }
    
    fetch(`/admin/api/get-source?key=${encodeURIComponent(sourceKey)}&zip=${encodeURIComponent(zipCode)}`, {
        credentials: 'same-origin'
    })
    .then(r => r.json())
    .then(data => {
        if (data.success && data.source) {
            showEditSourceModal(data.source);
        } else {
            alert('Error loading source: ' + (data.message || 'Unknown error'));
        }
    })
    .catch(e => {
        alert('Error: ' + e.message);
    });
}
window.editSource = editSource;

// Show edit source modal
function showEditSourceModal(source) {
    let modal = document.getElementById('editSourceModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'editSourceModal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 600px;">
                <div class="modal-header">
                    <h2>${source.key ? 'Edit' : 'Add'} Source</h2>
                    <span class="close-modal" onclick="closeEditSourceModal()">&times;</span>
                </div>
                <form id="editSourceForm" onsubmit="saveSourceEdit(event); return false;">
                    <input type="hidden" id="editSourceKey" name="key" value="${escapeAttr(source.key || '')}">
                    <div class="form-group">
                        <label>Name:</label>
                        <input type="text" id="editSourceName" name="name" value="${escapeAttr(source.name || '')}" required>
                    </div>
                    <div class="form-group">
                        <label>URL:</label>
                        <input type="url" id="editSourceUrl" name="url" value="${escapeAttr(source.url || '')}" required>
                    </div>
                    <div class="form-group">
                        <label>RSS URL (optional):</label>
                        <input type="url" id="editSourceRss" name="rss" value="${escapeAttr(source.rss || '')}">
                    </div>
                    <div class="form-group">
                        <label>Category:</label>
                        <select id="editSourceCategory" name="category">
                            <option value="news" ${source.category === 'news' ? 'selected' : ''}>News</option>
                            <option value="entertainment" ${source.category === 'entertainment' ? 'selected' : ''}>Entertainment</option>
                            <option value="sports" ${source.category === 'sports' ? 'selected' : ''}>Sports</option>
                            <option value="local" ${source.category === 'local' ? 'selected' : ''}>Local</option>
                            <option value="media" ${source.category === 'media' ? 'selected' : ''}>Media</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Relevance Score (optional):</label>
                        <input type="number" id="editSourceRelevance" name="relevance_score" 
                               value="${source.relevance_score !== undefined ? source.relevance_score : ''}" 
                               step="0.1" min="0" placeholder="e.g., 15.0">
                        <small style="color: #888; display: block; margin-top: 0.25rem;">Higher scores = more relevant articles</small>
                    </div>
                    <div class="form-actions">
                        <button type="submit" style="padding: 0.75rem 1.5rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Save</button>
                        <button type="button" onclick="closeEditSourceModal()" style="padding: 0.75rem 1.5rem; background: #666; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; margin-left: 0.5rem;">Cancel</button>
                    </div>
                </form>
            </div>
        `;
        document.body.appendChild(modal);
    } else {
        // Update existing modal
        document.getElementById('editSourceKey').value = source.key || '';
        document.getElementById('editSourceName').value = source.name || '';
        document.getElementById('editSourceUrl').value = source.url || '';
        document.getElementById('editSourceRss').value = source.rss || '';
        document.getElementById('editSourceCategory').value = source.category || 'news';
        document.getElementById('editSourceRelevance').value = source.relevance_score !== undefined ? source.relevance_score : '';
        modal.querySelector('h2').textContent = (source.key ? 'Edit' : 'Add') + ' Source';
    }
    
    modal.style.display = 'block';
}
window.showEditSourceModal = showEditSourceModal;

// Close edit source modal
function closeEditSourceModal() {
    const modal = document.getElementById('editSourceModal');
    if (modal) {
        modal.style.display = 'none';
    }
}
window.closeEditSourceModal = closeEditSourceModal;

// Save source edit
function saveSourceEdit(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    const zipCode = getZipCodeFromUrl();
    if (!zipCode) {
        alert('Zip code not found');
        return;
    }
    
    const data = {
        key: formData.get('key'),
        name: formData.get('name'),
        url: formData.get('url'),
        rss: formData.get('rss') || null,
        category: formData.get('category'),
        relevance_score: formData.get('relevance_score') || null,
        zip_code: zipCode
    };
    
    const isNew = !data.key;
    const endpoint = isNew ? '/admin/api/add-source' : '/admin/api/edit-source';
    
    fetch(endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify(data)
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            closeEditSourceModal();
            location.reload();
        } else {
            alert('Error saving source: ' + (result.message || 'Unknown error'));
        }
    })
    .catch(e => {
        alert('Error: ' + e.message);
    });
}
window.saveSourceEdit = saveSourceEdit;

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

// Target Analysis Functions
function showTargetAnalysis(articleId, zipCode) {
    const modal = document.getElementById('targetAnalysisModal');
    const content = document.getElementById('targetAnalysisContent');
    
    if (!modal || !content) {
        alert('Target analysis modal not found. Please refresh the page.');
        return;
    }
    
    // Show modal with loading state
    modal.style.display = 'block';
    content.innerHTML = `
        <div style="text-align: center; padding: 2rem;">
            <div class="spinner" style="border: 4px solid #404040; border-top: 4px solid #0078d4; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto;"></div>
            <p style="margin-top: 1rem; color: #888;">Analyzing article...</p>
        </div>
    `;
    
    // Fetch analysis
    fetch('/admin/api/analyze-target', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({
            article_id: articleId,
            zip_code: zipCode
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            displayTargetAnalysis(data, articleId, zipCode);
            // Update button state based on whether suggestions are available
            updateTargetButtonState(articleId, data.breakdown && data.breakdown.has_suggestions);
        } else {
            content.innerHTML = `
                <div style="padding: 2rem; text-align: center;">
                    <p style="color: #d32f2f;">Error: ${data.error || 'Failed to analyze article'}</p>
                    <button onclick="closeTargetModal()" style="margin-top: 1rem; padding: 0.5rem 1rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer;">Close</button>
                </div>
            `;
        }
    })
    .catch(e => {
        console.error('Error analyzing target:', e);
        content.innerHTML = `
            <div style="padding: 2rem; text-align: center;">
                <p style="color: #d32f2f;">Error: ${e.message || 'Failed to analyze article'}</p>
                <button onclick="closeTargetModal()" style="margin-top: 1rem; padding: 0.5rem 1rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer;">Close</button>
            </div>
        `;
    });
}

function displayTargetAnalysis(data, articleId, zipCode) {
    const content = document.getElementById('targetAnalysisContent');
    const breakdown = data.breakdown || {};
    const suggested = data.suggested_keywords || {};
    const article = data.article || {};
    
    // Format published date
    let publishedDate = 'N/A';
    if (article.published) {
        try {
            const date = new Date(article.published);
            publishedDate = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        } catch(e) {
            publishedDate = article.published;
        }
    }
    
    let html = `
        <div style="margin-bottom: 2rem; background: #1a1a1a; padding: 1.5rem; border-radius: 8px; border: 1px solid #404040;">
            <h3 style="color: #0078d4; margin-bottom: 1rem; border-bottom: 2px solid #404040; padding-bottom: 0.5rem;">📄 Article Information</h3>
            <div style="display: grid; grid-template-columns: auto 1fr; gap: 0.75rem 1.5rem; margin-bottom: 1rem;">
                <div style="font-weight: 600; color: #888;">Title:</div>
                <div style="color: #e0e0e0;">${escapeHtml(article.title || 'N/A')}</div>
                
                <div style="font-weight: 600; color: #888;">Source:</div>
                <div style="color: #e0e0e0;">${escapeHtml(article.source || 'N/A')}</div>
                
                <div style="font-weight: 600; color: #888;">Category:</div>
                <div style="color: #e0e0e0;">
                    ${article.display_category ? `
                        <span style="background: #0078d4; color: white; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.85rem;">${escapeHtml(article.display_category)}</span>
                        ${article.category_confidence && article.category_confidence > 0 ? `<span style="color: #888; font-size: 0.85rem; margin-left: 0.5rem;">(${Math.round(article.category_confidence)}%)</span>` : ''}
                        ${article.primary_category && article.primary_category !== article.display_category ? `<span style="background: #404040; color: white; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.85rem; margin-left: 0.5rem;">${escapeHtml(article.primary_category)}</span>` : ''}
                    ` : '<span style="color: #888;">Not categorized</span>'}
                </div>
                
                <div style="font-weight: 600; color: #888;">Published:</div>
                <div style="color: #e0e0e0;">${publishedDate}</div>
                
                ${article.url ? `
                <div style="font-weight: 600; color: #888;">URL:</div>
                <div style="color: #0078d4;">
                    <a href="${escapeAttr(article.url)}" target="_blank" rel="noopener" style="color: #0078d4; text-decoration: none; word-break: break-all;">
                        ${escapeHtml(article.url.length > 60 ? article.url.substring(0, 60) + '...' : article.url)}
                    </a>
                </div>
                ` : ''}
                
                ${article.summary ? `
                <div style="font-weight: 600; color: #888;">Summary:</div>
                <div style="color: #e0e0e0; font-size: 0.9rem; line-height: 1.5;">${escapeHtml(article.summary)}</div>
                ` : ''}
            </div>
        </div>
        
        <div style="margin-bottom: 2rem;">
            <h3 style="color: #0078d4; margin-bottom: 1rem;">📊 Relevance Score Breakdown</h3>
            <div style="background: #1a1a1a; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                <div style="font-size: 2rem; font-weight: bold; color: ${breakdown.total_score >= 70 ? '#4caf50' : breakdown.total_score >= 40 ? '#ff9800' : '#d32f2f'};">
                    ${breakdown.total_score ? breakdown.total_score.toFixed(1) : '0'}/100
                </div>
            </div>
            
            <div style="margin-bottom: 1rem;">
                <h4 style="color: #e0e0e0; margin-bottom: 0.5rem;">✅ Matched Tags:</h4>
                <div>
                    ${breakdown.matched_tags && breakdown.matched_tags.length > 0 
                        ? breakdown.matched_tags.map(tag => `<span class="matched-tag">${tag}</span>`).join('')
                        : '<span style="color: #888;">No matches found</span>'}
                </div>
            </div>
            
            ${breakdown.missing_tags && breakdown.missing_tags.length > 0 ? `
            <div style="margin-bottom: 1rem;">
                <h4 style="color: #e0e0e0; margin-bottom: 0.5rem;">⚠️ Missing Tags:</h4>
                <div>
                    ${breakdown.missing_tags.map(tag => `<span class="missing-tag">${tag}</span>`).join('')}
                </div>
            </div>
            ` : ''}
        </div>
        
        <div style="margin-bottom: 2rem;">
            <h3 style="color: #0078d4; margin-bottom: 1rem;">💡 Suggested Keywords</h3>
            <p style="color: #888; margin-bottom: 1rem; font-size: 0.9rem;">Click keywords to select them (toggle on/off):</p>
    `;
    
    // Add keyword sections
    const categories = [
        { key: 'high_relevance', label: 'High Relevance Keywords', icon: '📍', class: 'high-relevance' },
        { key: 'local_places', label: 'Local Places', icon: '🏛️', class: 'local-places' },
        { key: 'topic_keywords', label: 'Topic Keywords', icon: '📰', class: 'topic-keywords' }
    ];
    
    let hasKeywords = false;
    categories.forEach(cat => {
        const keywords = suggested[cat.key] || [];
        if (keywords.length > 0) {
            hasKeywords = true;
            html += `
                <div style="margin-bottom: 2rem;">
                    <h4 style="color: #e0e0e0; margin-bottom: 1rem; font-size: 1rem;">${cat.icon} ${cat.label}</h4>
                    <div id="keywords-${cat.key}" class="keyword-grid">
            `;
            
            keywords.forEach((kw, idx) => {
                const keywordId = `kw-${cat.key}-${idx}`;
                html += `
                    <button type="button" 
                            class="keyword-toggle ${cat.class}" 
                            id="${keywordId}"
                            data-keyword="${escapeAttr(kw.keyword)}" 
                            data-category="${escapeAttr(cat.key)}"
                            data-confidence="${escapeAttr(kw.confidence)}"
                            title="${escapeAttr(kw.reason)}">
                        <span class="keyword-toggle-text">${escapeHtml(kw.keyword)}</span>
                        <span class="keyword-confidence-badge confidence-${escapeAttr(kw.confidence)}">${escapeHtml(kw.confidence)}</span>
                        <span class="keyword-reason">${escapeHtml(kw.reason.length > 40 ? kw.reason.substring(0, 40) + '...' : kw.reason)}</span>
                    </button>
                `;
            });
            
            html += `
                    </div>
                </div>
            `;
        }
    });
    
    if (!hasKeywords) {
        html += `
            <div style="padding: 2rem; text-align: center; background: #1a1a1a; border-radius: 8px; border: 1px solid #404040;">
                <p style="color: #888; font-size: 1rem; margin-bottom: 0.5rem;">No new keywords found to suggest.</p>
                <p style="color: #666; font-size: 0.85rem;">All relevant keywords from this article are already in your relevance configuration.</p>
            </div>
        `;
    }
    
    html += `
        </div>
        
        <div style="display: flex; gap: 1rem; justify-content: flex-end; margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #404040;">
            <button onclick="closeTargetModal()" style="padding: 0.75rem 1.5rem; background: #404040; color: white; border: none; border-radius: 4px; cursor: pointer;">Cancel</button>
            ${hasKeywords ? `<button id="addKeywordsBtn" onclick="addSelectedKeywords(${articleId}, '${zipCode}')" style="padding: 0.75rem 1.5rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Add Selected Keywords (0)</button>` : ''}
        </div>
    `;
    
    content.innerHTML = html;
    
    // Add click handlers for toggle buttons
    if (hasKeywords) {
        categories.forEach(cat => {
            const keywords = suggested[cat.key] || [];
            keywords.forEach((kw, idx) => {
                const keywordId = `kw-${cat.key}-${idx}`;
                const btn = document.getElementById(keywordId);
                if (btn) {
                    btn.addEventListener('click', function() {
                        this.classList.toggle('selected');
                        updateAddButtonText();
                    });
                }
            });
        });
        updateAddButtonText();
    }
}

function updateAddButtonText() {
    const selectedButtons = document.querySelectorAll('.keyword-toggle.selected');
    const count = selectedButtons.length;
    const addBtn = document.getElementById('addKeywordsBtn');
    if (addBtn) {
        addBtn.textContent = `Add Selected Keywords (${count})`;
        addBtn.disabled = count === 0;
        addBtn.style.opacity = count === 0 ? '0.5' : '1';
        addBtn.style.cursor = count === 0 ? 'not-allowed' : 'pointer';
    }
}

function addSelectedKeywords(articleId, zipCode) {
    const selectedButtons = document.querySelectorAll('#targetAnalysisContent .keyword-toggle.selected');
    const keywords = [];
    
    if (selectedButtons.length === 0) {
        alert('Please select at least one keyword to add.');
        return;
    }
    
    selectedButtons.forEach(btn => {
        const keyword = btn.getAttribute('data-keyword');
        const category = btn.getAttribute('data-category');
        if (keyword && category) {
            keywords.push({ keyword, category });
        }
    });
    
    const button = event.target;
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = 'Adding...';
    
    fetch('/admin/api/add-target-keywords', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({
            article_id: articleId,
            zip_code: zipCode,
            keywords: keywords
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            alert(`Successfully added ${data.added_count} keyword(s)${data.skipped_count > 0 ? `, skipped ${data.skipped_count} duplicate(s)` : ''}.`);
            closeTargetModal();
            // Optionally reload the page to see updated relevance config
            setTimeout(() => location.reload(), 500);
        } else {
            alert('Error adding keywords: ' + (data.error || 'Unknown error'));
            button.disabled = false;
            button.textContent = originalText;
        }
    })
    .catch(e => {
        console.error('Error adding keywords:', e);
        alert('Error: ' + (e.message || 'Failed to add keywords'));
        button.disabled = false;
        button.textContent = originalText;
    });
}

function updateTargetButtonState(articleId, hasSuggestions) {
    // Update target button styling based on whether suggestions are available
    document.querySelectorAll('.target-btn').forEach(btn => {
        if (btn.getAttribute('data-id') == articleId) {
            if (!hasSuggestions) {
                // Grey out button if no suggestions
                btn.style.opacity = '0.3';
                btn.style.cursor = 'not-allowed';
                btn.title = 'No new keywords available to add';
                btn.setAttribute('data-no-suggestions', 'true');
            } else {
                // Reset to normal state
                btn.style.opacity = '0.5';
                btn.style.cursor = 'pointer';
                btn.title = 'Analyze article and suggest keywords';
                btn.removeAttribute('data-no-suggestions');
            }
        }
    });
}

function closeTargetModal() {
    const modal = document.getElementById('targetAnalysisModal');
    if (modal) {
        modal.style.display = 'none';
    }
    // Remove active state from all target buttons when modal closes
    document.querySelectorAll('.target-btn').forEach(b => b.classList.remove('active'));
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('targetAnalysisModal');
    if (event.target == modal) {
        closeTargetModal();
    }
}

window.showTargetAnalysis = showTargetAnalysis;
window.closeTargetModal = closeTargetModal;
window.addSelectedKeywords = addSelectedKeywords;
window.updateTargetButtonState = updateTargetButtonState;

// Tab switching functionality
document.addEventListener('DOMContentLoaded', function() {
    // Hide all tab content except the active one
    const tabContents = document.querySelectorAll('.tab-content');
    const activeTab = document.querySelector('.tab-btn.active');

    if (activeTab) {
        const activeTabName = activeTab.getAttribute('href').split('tab=')[1] || 'articles';
        const activeContentId = activeTabName + 'Tab';

        // Hide all tab content
        tabContents.forEach(content => {
            content.style.display = 'none';
        });

        // Show active tab content
        const activeContent = document.getElementById(activeContentId);
        if (activeContent) {
            activeContent.style.display = 'block';
        }
    }
});

console.log('Admin script loaded');

