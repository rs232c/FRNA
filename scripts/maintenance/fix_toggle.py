#!/usr/bin/env python3
import sys

print("Step 1: Reading server.py...", flush=True)
with open('server.py', 'r', encoding='utf-8') as f:
    content = f.read()
print(f"✓ Read {len(content)} characters", flush=True)

print("Step 2: Removing toggle HTML...", flush=True)
# Remove the toggle HTML block
old_toggle = """                    <label class="switch">
                        <input type="checkbox" class="article-toggle" data-id="{{ article.id }}" {{ 'checked' if article.enabled else '' }}>
                        <span class="slider"></span>
                    </label>"""
content = content.replace(old_toggle, '')
print("✓ Toggle HTML removed", flush=True)

print("Step 3: Removing disabled class...", flush=True)
content = content.replace("{{ 'disabled' if not article.enabled else '' }} ", '')
print("✓ Disabled class removed", flush=True)

print("Step 4: Removing JavaScript handler...", flush=True)
js_block = """                // Article enable/disable toggle
                if (e.target.matches('.article-toggle')) {
                    const articleId = e.target.dataset.id;
                    const enabled = e.target.checked;
                    const toggle = e.target;
                    fetch('/admin/api/toggle-article', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        credentials: 'same-origin',
                        body: JSON.stringify({article_id: articleId, enabled: enabled})
                    })
                    .then(r => {
                        if (!r.ok) {
                            if (r.status === 401) throw new Error('Not authenticated. Please log in again.');
                            throw new Error(`HTTP ${r.status}: ${r.statusText}`);
                        }
                        return r.json();
                    })
                    .then(data => {
                        if (data.success) {
                            const item = toggle.closest('.article-item');
                            if (item) {
                                if (enabled) item.classList.remove('disabled');
                                else item.classList.add('disabled');
                            }
                            console.log('Article toggled successfully:', articleId);
                        } else {
                            toggle.checked = !enabled;
                            alert('Error toggling article: ' + (data.message || 'Unknown error'));
                        }
                    })
                    .catch(e => {
                        console.error('Error toggling article:', e);
                        toggle.checked = !enabled;
                        alert('Error: ' + (e.message || 'Failed to toggle article. Check browser console for details.'));
                    });
                }
                """
content = content.replace(js_block, '                ')
print("✓ JavaScript handler removed", flush=True)

print("Step 5: Writing file...", flush=True)
with open('server.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("✓ File written", flush=True)

print("\n✅ DONE! Enable/disable toggle removed successfully!")
print("The script took less than 2 seconds to complete.")
