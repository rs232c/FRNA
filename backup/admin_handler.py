"""
CGI handler for admin actions - can be used with simple HTTP server

NOTE: This file is deprecated. The current admin system uses:
- admin_server.py - HTTP server
- admin_simple.py - HTML generation
- admin_backend.py - Backend functions

This CGI handler is kept for backward compatibility but is not actively used.
"""
import cgi
import sys
import json
from admin_backend import toggle_article, set_image_visibility, reorder_articles, regenerate, add_custom_article

def handle_request():
    """Handle admin action requests"""
    form = cgi.FieldStorage()
    action = form.getvalue('action', '')
    
    if action == 'toggle':
        article_id = int(form.getvalue('id'))
        enabled = form.getvalue('enabled', 'false').lower() == 'true'
        toggle_article(article_id, enabled)
        print("Content-Type: text/html\n")
        print("OK")
    
    elif action == 'images':
        show = form.getvalue('show', 'false').lower() == 'true'
        set_image_visibility(show)
        print("Content-Type: text/html\n")
        print("OK")
    
    elif action == 'order':
        orders_json = form.getvalue('orders', '[]')
        orders = json.loads(orders_json)
        reorder_articles(orders)
        print("Content-Type: text/html\n")
        print("OK")
    
    elif action == 'regenerate':
        regenerate()
        print("Content-Type: text/html\n")
        print("OK - Website regenerated")
    
    elif action == 'add':
        title = form.getvalue('title')
        content = form.getvalue('content')
        source = form.getvalue('source', 'Custom Article')
        url = form.getvalue('url', '')
        add_custom_article(title, content, url, source)
        print("Content-Type: text/html\n")
        print("OK - Article added")
    
    else:
        print("Content-Type: text/html\n")
        print("ERROR - Unknown action")

if __name__ == '__main__':
    handle_request()



