"""
CSS styles for the website generator
Minimal custom styles - most layout handled by Tailwind CSS
"""

def get_css_content() -> str:
    """Get minimal CSS content - only custom styles not handled by Tailwind"""
    return """/* ============================================
   Minimal Custom Styles
   (Most styling handled by Tailwind CSS)
   ============================================ */

/* Base reset and font smoothing */
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* Smooth scroll */
html {
    scroll-behavior: smooth;
}

/* Line clamp utilities (if Tailwind doesn't provide) */
.line-clamp-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.line-clamp-3 {
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

/* Lazy image loading */
.lazy-image {
    opacity: 0;
    transition: opacity 0.3s;
}

.lazy-image.loaded {
    opacity: 1;
}

/* Focus states for accessibility */
*:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
}

/* Selection color */
::selection {
    background: #3b82f6;
    color: white;
}

::-moz-selection {
    background: #3b82f6;
    color: white;
}

/* Masonry grid equal heights */
#articlesGrid {
    display: grid;
    grid-auto-rows: 1fr;
    align-items: start; /* Align items to top */
}

#articlesGrid > article {
    display: flex;
    flex-direction: column;
    height: 100%; /* Fill grid cell */
}

/* Smooth image transitions */
img {
    transition: transform 0.5s ease, opacity 0.3s ease;
}

/* Fixed positioning for badges */
.fixed {
    position: fixed;
}

/* Ensure cards maintain equal height in grid */
.grid > * {
    min-height: 0;
}

/* Smooth hover transitions */
article {
    transition: transform 0.3s ease, box-shadow 0.3s ease;
}

/* Enhanced shadow on hover */
article:hover {
    transform: scale(1.03);
    box-shadow: 0 25px 50px -12px rgba(59, 130, 246, 0.2);
}

/* Hero carousel styles */
.top-stories-track {
    overflow: hidden;
    display: flex;
    position: relative;
    width: 100%;
}

.story-slide {
    min-width: 0;
    flex-shrink: 0;
    flex-grow: 0;
    width: 100%;
}

/* Square card aspect ratio support */
.aspect-square {
    aspect-ratio: 1 / 1;
}
"""
