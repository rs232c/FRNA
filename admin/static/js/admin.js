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

    // Add unified button click handler inside DOMContentLoaded
    console.log('[FRNA Admin] Setting up unified button event handler...');
    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('button, .trash-btn, .restore-btn, .top-story-btn, .restore-trash-btn, .restore-auto-btn, .thumbs-up-btn, .thumbs-down-btn, .alert-btn, .top-article-btn, .on-target-btn, .off-target-btn, .relevance-breakdown-btn, .edit-article-btn, .good-fit-btn, .add-tags-btn');

        if (!btn) return;

        // Check if this is an admin action button (has data-action OR is one of our button classes)
        const isAdminButton = btn.classList.contains('trash-btn') ||
            btn.classList.contains('restore-btn') ||
            btn.classList.contains('restore-trash-btn') ||
            btn.classList.contains('restore-auto-btn') ||
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

        if (!isAdminButton) return;

        e.preventDefault();
        const articleId = btn.getAttribute('data-id');

        // Handle relevance breakdown button
        if (btn.classList.contains('relevance-breakdown-btn') || btn.getAttribute('data-action') === 'show-breakdown') {
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

        // Handle thumbs up button
        if (btn.classList.contains('thumbs-up-btn') || btn.getAttribute('data-action') === 'thumbs-up') {
            const zipCode = getZipCodeFromUrl();
            if (articleId && zipCode) {
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
                        btn.style.background = '#4caf50';
                        btn.style.opacity = '1';
                        btn.setAttribute('data-state', 'on');
                    }
                })
                .catch(e => console.error('Error with thumbs up:', e));
            }
            return;
        }

        // Handle thumbs down button
        if (btn.classList.contains('thumbs-down-btn') || btn.getAttribute('data-action') === 'thumbs-down') {
            const zipCode = getZipCodeFromUrl();
            if (articleId && zipCode) {
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
                    if (data.success) {
                        // Mark as rejected
                        const articleItem = btn.closest('.article-item');
                        if (articleItem) {
                            articleItem.style.opacity = '0.5';
                        }
                        setTimeout(() => location.reload(), 500);
                    }
                })
                .catch(e => console.error('Error with thumbs down:', e));
            }
            return;
        }

        // Handle top article button
        if (btn.classList.contains('top-article-btn') || btn.getAttribute('data-action') === 'toggle-top-article') {
            const zipCode = getZipCodeFromUrl();
            if (articleId && zipCode) {
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
                        document.querySelectorAll('.top-article-btn').forEach(otherBtn => {
                            if (otherBtn.getAttribute('data-id') == articleId) {
                                otherBtn.style.background = '#ffd700';
                                otherBtn.style.opacity = '1';
                                otherBtn.setAttribute('data-state', 'on');
                            } else {
                                otherBtn.style.background = 'transparent';
                                otherBtn.style.opacity = '0.5';
                                otherBtn.setAttribute('data-state', 'off');
                            }
                        });
                    }
                })
                .catch(e => console.error('Error toggling top article:', e));
            }
            return;
        }

        // Handle alert button
        if (btn.classList.contains('alert-btn') || btn.getAttribute('data-action') === 'toggle-alert') {
            const zipCode = getZipCodeFromUrl();
            if (articleId && zipCode) {
                const isCurrentlyAlert = btn.getAttribute('data-state') === 'on';
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
                        document.querySelectorAll('.alert-btn').forEach(otherBtn => {
                            if (otherBtn.getAttribute('data-id') == articleId) {
                                otherBtn.style.background = newState ? '#ff4444' : 'transparent';
                                otherBtn.style.opacity = newState ? '1' : '0.5';
                                otherBtn.setAttribute('data-state', newState ? 'on' : 'off');
                            }
                        });
                    }
                })
                .catch(e => console.error('Error toggling alert:', e));
            }
            return;
        }

        // Handle on-target button
        if (btn.classList.contains('on-target-btn') || btn.getAttribute('data-action') === 'on-target') {
            const zipCode = getZipCodeFromUrl();
            if (articleId && zipCode) {
                fetch('/admin/api/on-target', {
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
                        btn.style.opacity = '1';
                        btn.setAttribute('data-state', 'on');
                        const offTargetBtn = document.querySelector(`.off-target-btn[data-id="${articleId}"]`);
                        if (offTargetBtn) {
                            offTargetBtn.style.background = 'transparent';
                            offTargetBtn.style.opacity = '0.5';
                            offTargetBtn.setAttribute('data-state', 'off');
                        }
                    }
                })
                .catch(e => console.error('Error setting on-target:', e));
            }
            return;
        }

        // Handle off-target button
        if (btn.classList.contains('off-target-btn') || btn.getAttribute('data-action') === 'off-target') {
            const zipCode = getZipCodeFromUrl();
            if (articleId && zipCode) {
                fetch('/admin/api/off-target', {
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
                        btn.style.opacity = '1';
                        btn.setAttribute('data-state', 'on');
                        const onTargetBtn = document.querySelector(`.on-target-btn[data-id="${articleId}"]`);
                        if (onTargetBtn) {
                            onTargetBtn.style.background = 'transparent';
                            onTargetBtn.style.opacity = '0.5';
                            onTargetBtn.setAttribute('data-state', 'off');
                        }
                    }
                })
                .catch(e => console.error('Error setting off-target:', e));
            }
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
        if (btn.classList.contains('restore-btn') || btn.classList.contains('restore-trash-btn') || btn.classList.contains('restore-auto-btn') || btn.getAttribute('data-action') === 'restore-article') {
            if (typeof window.restoreArticle === 'function') {
                const rejectionType = btn.getAttribute('data-rejection-type') || 'manual';
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

        // Handle add tags button
        if (btn.classList.contains('add-tags-btn')) {
            if (typeof window.showRejectionTagsModal === 'function') {
                window.showRejectionTagsModal(articleId);
            } else {
                alert('Error: showRejectionTagsModal function not available. Please refresh the page.');
            }
            return;
        }
    });
    console.log('[FRNA Admin] ✅ Unified button event handler attached inside DOMContentLoaded');
})();

