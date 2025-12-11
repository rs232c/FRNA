/**
 * Category Settings UI Component
 * Provides a modal interface for users to toggle categories on/off
 */

class CategorySettingsUI {
    constructor() {
        this.modal = null;
        this.preferences = window.CategoryPreferences;
        this.init();
    }

    init() {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.createModal());
        } else {
            this.createModal();
        }
    }

    /**
     * Create the settings modal
     */
    createModal() {
        // Create modal HTML
        const modalHTML = `
            <div id="categorySettingsModal" class="hidden fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm">
                <div class="bg-[#1a1a1a] border border-gray-700 rounded-lg p-6 max-w-2xl w-full mx-4 shadow-2xl max-h-[90vh] overflow-y-auto" onclick="event.stopPropagation()">
                    <div class="flex items-center justify-between mb-6">
                        <h3 class="text-2xl font-bold text-white">Category Settings</h3>
                        <button id="closeCategorySettings" class="text-gray-400 hover:text-white transition-colors">
                            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                            </svg>
                        </button>
                    </div>
                    
                    <p class="text-gray-400 mb-6 text-sm">Choose which categories appear in your navigation:</p>
                    
                    <!-- Primary Categories -->
                    <div class="mb-6">
                        <h4 class="text-lg font-semibold text-gray-300 mb-3">Primary Navigation</h4>
                        <div id="primaryCategories" class="space-y-2">
                            <!-- Will be populated dynamically -->
                        </div>
                    </div>
                    
                    <!-- Secondary Categories -->
                    <div class="mb-6">
                        <h4 class="text-lg font-semibold text-gray-300 mb-3">Secondary Navigation</h4>
                        <div id="secondaryCategories" class="space-y-2">
                            <!-- Will be populated dynamically -->
                        </div>
                    </div>
                    
                    <!-- Actions -->
                    <div class="flex gap-3 pt-4 border-t border-gray-700">
                        <button id="resetCategoryDefaults" class="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg font-medium transition-colors">
                            Reset to Defaults
                        </button>
                        <button id="closeCategorySettingsBtn" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors ml-auto">
                            Done
                        </button>
                    </div>
                </div>
            </div>
        `;

        // Insert modal into body
        document.body.insertAdjacentHTML('beforeend', modalHTML);
        this.modal = document.getElementById('categorySettingsModal');

        // Populate categories
        this.populateCategories();

        // Attach event listeners
        this.attachEventListeners();
    }

    /**
     * Populate category toggles
     */
    populateCategories() {
        const primaryContainer = document.getElementById('primaryCategories');
        const secondaryContainer = document.getElementById('secondaryCategories');

        if (!primaryContainer || !secondaryContainer) return;

        primaryContainer.innerHTML = '';
        secondaryContainer.innerHTML = '';

        const allCategories = this.preferences.getAllCategories();
        
        allCategories.forEach(slug => {
            const row = this.preferences.getCategoryRow(slug);
            const displayName = this.preferences.getCategoryDisplayName(slug);
            const isEnabled = this.preferences.isCategoryEnabled(slug);
            const container = row === 'primary' ? primaryContainer : secondaryContainer;

            const toggleHTML = `
                <label class="flex items-center justify-between p-3 bg-[#0f0f0f] rounded-lg border border-gray-800 hover:border-gray-700 transition-colors cursor-pointer">
                    <span class="text-gray-200 font-medium">${displayName}</span>
                    <div class="relative inline-block w-12 h-6">
                        <input type="checkbox" 
                               class="sr-only category-toggle" 
                               data-category-slug="${slug}"
                               ${isEnabled ? 'checked' : ''}>
                        <div class="toggle-slider w-12 h-6 rounded-full transition-colors ${isEnabled ? 'bg-blue-600' : 'bg-gray-700'}">
                            <div class="toggle-knob absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${isEnabled ? 'transform translate-x-6' : ''}"></div>
                        </div>
                    </div>
                </label>
            `;

            container.insertAdjacentHTML('beforeend', toggleHTML);
        });
    }

    /**
     * Attach event listeners
     */
    attachEventListeners() {
        // Close buttons
        const closeBtn = document.getElementById('closeCategorySettings');
        const closeBtn2 = document.getElementById('closeCategorySettingsBtn');
        
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.hide());
        }
        if (closeBtn2) {
            closeBtn2.addEventListener('click', () => this.hide());
        }

        // Close on background click
        if (this.modal) {
            this.modal.addEventListener('click', (e) => {
                if (e.target === this.modal) {
                    this.hide();
                }
            });
        }

        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !this.modal.classList.contains('hidden')) {
                this.hide();
            }
        });

        // Category toggles
        document.addEventListener('change', (e) => {
            if (e.target.classList.contains('category-toggle')) {
                const slug = e.target.dataset.categorySlug;
                const enabled = e.target.checked;
                this.preferences.toggleCategory(slug, enabled);
                this.updateToggleVisual(e.target, enabled);
            }
        });

        // Reset to defaults
        const resetBtn = document.getElementById('resetCategoryDefaults');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                this.preferences.resetToDefaults();
                this.populateCategories();
            });
        }
    }

    /**
     * Update toggle visual state
     */
    updateToggleVisual(checkbox, enabled) {
        const slider = checkbox.nextElementSibling;
        const knob = slider.querySelector('.toggle-knob');
        
        if (enabled) {
            slider.classList.add('bg-blue-600');
            slider.classList.remove('bg-gray-700');
            knob.classList.add('transform', 'translate-x-6');
        } else {
            slider.classList.remove('bg-blue-600');
            slider.classList.add('bg-gray-700');
            knob.classList.remove('transform', 'translate-x-6');
        }
    }

    /**
     * Show the modal
     */
    show() {
        if (this.modal) {
            this.modal.classList.remove('hidden');
            // Refresh categories in case preferences changed elsewhere
            this.populateCategories();
        }
    }

    /**
     * Hide the modal
     */
    hide() {
        if (this.modal) {
            this.modal.classList.add('hidden');
        }
    }
}

// Create global instance
window.CategorySettingsUI = new CategorySettingsUI();

