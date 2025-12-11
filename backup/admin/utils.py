"""
Admin utility functions for database operations
"""
import sqlite3
import logging
from contextlib import contextmanager
from config import DATABASE_CONFIG
from flask import session

logger = logging.getLogger(__name__)


@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_db_legacy():
    """Legacy database connection (use get_db context manager instead)"""
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    conn.row_factory = sqlite3.Row
    return conn


def validate_zip_code(zip_code: str) -> bool:
    """Validate zip code format"""
    if not zip_code:
        return False
    return zip_code.isdigit() and len(zip_code) == 5


def trash_article(article_id: int, zip_code: str) -> dict:
    """Move article to trash (reject it)"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Ensure is_rejected column exists
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
        conn.commit()
    except:
        pass
    
    # Get article data for Bayesian training
    cursor.execute('SELECT title, content, summary, source FROM articles WHERE id = ?', (article_id,))
    article_row = cursor.fetchone()
    article_data = None
    if article_row:
        article_data = {
            'title': article_row[0] or '',
            'content': article_row[1] or article_row[2] or '',
            'summary': article_row[2] or '',
            'source': article_row[3] or ''
        }
    
    # Get current display_order
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id
    
    # Check if entry exists
    cursor.execute('SELECT id FROM article_management WHERE article_id = ? AND zip_code = ?', (article_id, zip_code))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute('''
            UPDATE article_management 
            SET enabled = ?, display_order = ?, is_rejected = ?
            WHERE article_id = ? AND zip_code = ?
        ''', (0, display_order, 1, article_id, zip_code))
    else:
        cursor.execute('''
            INSERT INTO article_management (article_id, enabled, display_order, is_rejected, zip_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (article_id, 0, display_order, 1, zip_code))
    
    conn.commit()
    conn.close()
    
    # Train Bayesian model
    if article_data:
        try:
            from utils.bayesian_learner import BayesianLearner
            learner = BayesianLearner()
            learner.train_from_rejection(article_data)
            logger.info(f"Bayesian model trained from rejected article: '{article_data.get('title', '')[:50]}...'")
        except Exception as e:
            logger.warning(f"Could not train Bayesian model: {e}")
    
    return {'success': True, 'message': 'Article moved to trash'}


def restore_article(article_id: int, zip_code: str, rejection_type: str = 'manual') -> dict:
    """Restore article from trash"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Ensure columns exist
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
    except:
        pass
    
    if rejection_type == 'auto':
        cursor.execute('''
            UPDATE article_management 
            SET is_auto_rejected = 0, is_rejected = 0, enabled = 1, auto_reject_reason = NULL
            WHERE article_id = ? AND zip_code = ?
        ''', (article_id, zip_code))
    else:
        cursor.execute('''
            UPDATE article_management 
            SET is_rejected = 0, enabled = 1
            WHERE article_id = ? AND zip_code = ?
        ''', (article_id, zip_code))
    
    # If no rows were updated, create a new entry
    if cursor.rowcount == 0:
        cursor.execute('''
            INSERT INTO article_management (article_id, zip_code, enabled, is_rejected, is_auto_rejected, auto_reject_reason)
            VALUES (?, ?, 1, 0, 0, NULL)
        ''', (article_id, zip_code))
    
    conn.commit()
    conn.close()
    
    return {'success': True, 'message': 'Article restored'}


def toggle_top_story(article_id: int, zip_code: str, is_top_story: bool) -> dict:
    """Toggle top story status for an article"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Get current display_order
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id
    
    # Ensure columns exist
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_top_story INTEGER DEFAULT 0')
        conn.commit()
    except:
        pass
    
    cursor.execute('''
        INSERT OR REPLACE INTO article_management (article_id, enabled, display_order, is_top_article, is_top_story, zip_code, updated_at)
        VALUES (?, COALESCE((SELECT enabled FROM article_management WHERE article_id = ? AND zip_code = ?), 1),
                COALESCE((SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ?), ?),
                COALESCE((SELECT is_top_article FROM article_management WHERE article_id = ? AND zip_code = ?), 0), ?, ?, CURRENT_TIMESTAMP)
    ''', (article_id, article_id, zip_code, article_id, zip_code, article_id, article_id, zip_code, 1 if is_top_story else 0, zip_code))
    
    conn.commit()
    conn.close()
    
    return {'success': True}


def toggle_alert(article_id: int, zip_code: str, is_alert: bool) -> dict:
    """Toggle alert (siren) status for an article"""
    conn = get_db_legacy()
    cursor = conn.cursor()

    # Ensure column exists
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_alert INTEGER DEFAULT 0')
        conn.commit()
    except:
        pass

    # Get current display_order for stability
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id

    cursor.execute('''
        INSERT OR REPLACE INTO article_management (article_id, enabled, display_order, is_top_article, is_top_story, is_alert, zip_code, updated_at)
        VALUES (
            ?, 
            COALESCE((SELECT enabled FROM article_management WHERE article_id = ? AND zip_code = ?), 1),
            COALESCE((SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ?), ?),
            COALESCE((SELECT is_top_article FROM article_management WHERE article_id = ? AND zip_code = ?), 0),
            COALESCE((SELECT is_top_story FROM article_management WHERE article_id = ? AND zip_code = ?), 0),
            ?, 
            ?, 
            CURRENT_TIMESTAMP
        )
    ''', (
        article_id,
        article_id, zip_code,
        article_id, zip_code, display_order,
        article_id, zip_code,
        article_id, zip_code,
        1 if is_alert else 0,
        zip_code
    ))

    conn.commit()
    conn.close()

    return {'success': True, 'is_alert': is_alert}


def toggle_top_article(article_id: int, zip_code: str, is_top_article: bool) -> dict:
    """Toggle top article status for an article (exclusive - only one per zip)"""
    conn = get_db_legacy()
    cursor = conn.cursor()

    if is_top_article:
        # Unset all other top articles for this zip code
        cursor.execute('UPDATE article_management SET is_top_article = 0 WHERE zip_code = ?', (zip_code,))
    
    # Get current display_order
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id

    # Ensure columns exist
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_top_article INTEGER DEFAULT 0')
        conn.commit()
    except:
        pass

    cursor.execute('''
        INSERT OR REPLACE INTO article_management (article_id, enabled, display_order, is_top_article, is_top_story, zip_code, updated_at)
        VALUES (?, COALESCE((SELECT enabled FROM article_management WHERE article_id = ? AND zip_code = ?), 1), 
                COALESCE((SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ?), ?),
                ?,
                COALESCE((SELECT is_top_story FROM article_management WHERE article_id = ? AND zip_code = ?), 0), ?, CURRENT_TIMESTAMP)
    ''', (article_id, article_id, zip_code, article_id, zip_code, article_id, 1 if is_top_article else 0, article_id, zip_code, zip_code))
    
    conn.commit()
    conn.close()
    return {'success': True, 'message': 'Top article status updated'}


def toggle_alert(article_id: int, zip_code: str, is_alert: bool) -> dict:
    """Toggle alert status for an article (for urgent notifications)"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Get current display_order
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id
    
    # Ensure columns exist
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_alert INTEGER DEFAULT 0')
        conn.commit()
    except:
        pass
    
    cursor.execute('''
        INSERT OR REPLACE INTO article_management (article_id, enabled, display_order, is_top_article, is_top_story, is_alert, zip_code, updated_at)
        VALUES (?, COALESCE((SELECT enabled FROM article_management WHERE article_id = ? AND zip_code = ?), 1),
                COALESCE((SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ?), ?),
                COALESCE((SELECT is_top_article FROM article_management WHERE article_id = ? AND zip_code = ?), 0),
                COALESCE((SELECT is_top_story FROM article_management WHERE article_id = ? AND zip_code = ?), 0), ?, ?, CURRENT_TIMESTAMP)
    ''', (article_id, article_id, zip_code, article_id, zip_code, article_id, article_id, zip_code, article_id, zip_code, 1 if is_alert else 0, zip_code))
    
    conn.commit()
    conn.close()
    
    return {'success': True, 'message': 'Alert status updated'}


def expire_old_flags(zip_code: str) -> dict:
    """Auto-expire flags based on updated_at timestamp:
    - Top Hat (is_top_story): 3 days
    - Star (is_top_article): 5 days
    - Alert (is_alert): 3 days
    """
    from datetime import datetime, timedelta
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    now = datetime.now()
    three_days_ago = now - timedelta(days=3)
    five_days_ago = now - timedelta(days=5)
    
    expired_count = 0
    
    # Get all article_management entries with flags set for this zip
    cursor.execute('''
        SELECT article_id, is_top_story, is_top_article, is_alert, updated_at
        FROM article_management
        WHERE zip_code = ?
        AND (is_top_story = 1 OR is_top_article = 1 OR is_alert = 1)
        AND updated_at IS NOT NULL
    ''', (zip_code,))
    
    rows = cursor.fetchall()
    
    for row in rows:
        article_id = row[0]
        is_top_story = row[1]
        is_top_article = row[2]
        is_alert = row[3]
        updated_at_str = row[4]
        
        if not updated_at_str:
            continue
        
        try:
            # Parse timestamp (handle various formats)
            updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00').split('+')[0])
            age_days = (now - updated_at).total_seconds() / 86400
            
            needs_update = False
            new_is_top_story = is_top_story
            new_is_top_article = is_top_article
            new_is_alert = is_alert
            
            # Check Top Hat expiration (3 days)
            if is_top_story == 1 and age_days > 3:
                new_is_top_story = 0
                needs_update = True
                expired_count += 1
            
            # Check Star expiration (5 days)
            if is_top_article == 1 and age_days > 5:
                new_is_top_article = 0
                needs_update = True
                expired_count += 1
            
            # Check Alert expiration (3 days)
            if is_alert == 1 and age_days > 3:
                new_is_alert = 0
                needs_update = True
                expired_count += 1
            
            # Update if any flags expired
            if needs_update:
                # Get current display_order and enabled status
                cursor.execute('''
                    SELECT enabled, display_order FROM article_management 
                    WHERE article_id = ? AND zip_code = ? 
                    ORDER BY ROWID DESC LIMIT 1
                ''', (article_id, zip_code))
                current_row = cursor.fetchone()
                enabled = current_row[0] if current_row else 1
                display_order = current_row[1] if current_row else article_id
                
                cursor.execute('''
                    INSERT OR REPLACE INTO article_management 
                    (article_id, enabled, display_order, is_top_story, is_top_article, is_alert, zip_code, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (article_id, enabled, display_order, new_is_top_story, new_is_top_article, new_is_alert, zip_code))
        
        except Exception as e:
            logger.warning(f"Error parsing updated_at for article {article_id}: {e}")
            continue
    
    conn.commit()
    conn.close()
    
    logger.info(f"Expired {expired_count} flags for zip {zip_code}")
    return {'success': True, 'expired_count': expired_count}


def is_person_name(keyword: str, title_words: list = None) -> bool:
    """Check if keyword is likely a person's name"""
    keyword_lower = keyword.lower()
    
    # Common first names (common ones)
    common_first_names = ['john', 'mary', 'james', 'robert', 'michael', 'william', 'david', 'richard', 
                         'joseph', 'thomas', 'charles', 'christopher', 'daniel', 'matthew', 'anthony',
                         'mark', 'donald', 'steven', 'paul', 'andrew', 'joshua', 'kenneth', 'kevin',
                         'brian', 'george', 'edward', 'ronald', 'timothy', 'jason', 'jeffrey', 'ryan',
                         'jacob', 'gary', 'nicholas', 'eric', 'stephen', 'jonathan', 'larry', 'justin',
                         'scott', 'brandon', 'benjamin', 'samuel', 'frank', 'gregory', 'raymond',
                         'alexander', 'patrick', 'jack', 'dennis', 'jerry', 'tyler', 'aaron', 'jose',
                         'henry', 'adam', 'douglas', 'nathan', 'zachary', 'peter', 'kyle', 'noah',
                         'ethan', 'jeremy', 'walter', 'christian', 'keith', 'roger', 'terry', 'gerald',
                         'harold', 'sean', 'austin', 'carl', 'arthur', 'lawrence', 'dylan', 'jesse',
                         'jordan', 'bryan', 'billy', 'joe', 'bruce', 'gabriel', 'logan', 'albert',
                         'ralph', 'roy', 'juan', 'wayne', 'eugene', 'louis', 'russell', 'wayne',
                         'bobby', 'victor', 'martin', 'ernest', 'phillip', 'todd', 'jesse', 'craig',
                         'alan', 'shawn', 'clarence', 'sean', 'philip', 'chris', 'johnny', 'earl',
                         'jimmy', 'antonio', 'danny', 'bryan', 'tony', 'luis', 'mike', 'stanley',
                         'leonard', 'nathaniel', 'manuel', 'rodney', 'curtis', 'norman', 'allen',
                         'marvin', 'vincent', 'glenn', 'jeffery', 'travis', 'jeff', 'chad', 'jacob',
                         'lee', 'melvin', 'alfred', 'kyle', 'francis', 'bradley', 'jesus', 'herbert',
                         'frederick', 'ray', 'joel', 'edwin', 'don', 'eddie', 'ricky', 'troy',
                         'randy', 'barry', 'alexander', 'bernard', 'mario', 'leroy', 'francisco',
                         'marcus', 'micheal', 'theodore', 'clifford', 'miguel', 'oscar', 'jay',
                         'jim', 'tom', 'calvin', 'alex', 'jon', 'ronnie', 'bill', 'lloyd',
                         'tommy', 'leon', 'derek', 'warren', 'darrell', 'jerome', 'floyd', 'leo',
                         'alvin', 'tim', 'wesley', 'gordon', 'dean', 'greg', 'jorge', 'duane',
                         'pedro', 'doug', 'derrick', 'dan', 'lewis', 'zachary', 'corey', 'herman',
                         'maurice', 'vernon', 'roberto', 'clyde', 'glen', 'hector', 'shane', 'ricardo',
                         'sam', 'rick', 'lester', 'brent', 'ramon', 'charlie', 'tyler', 'gilbert',
                         'gene', 'marc', 'reginald', 'ruben', 'brett', 'angel', 'nathaniel', 'rafael',
                         'leslie', 'edgar', 'milton', 'raul', 'ben', 'chester', 'cecil', 'duane',
                         'franklin', 'andre', 'elmer', 'brad', 'gabriel', 'ron', 'mitchell', 'roland',
                         'arnold', 'harvey', 'jared', 'adrian', 'karl', 'cory', 'claude', 'erik',
                         'darryl', 'jamie', 'neil', 'jessie', 'christian', 'javier', 'fernando',
                         'clinton', 'ted', 'mathew', 'tyrone', 'darren', 'lonnie', 'lance', 'cody',
                         'julio', 'kelly', 'kurt', 'allan', 'nelson', 'guy', 'clayton', 'hugh',
                         'max', 'dwayne', 'dwight', 'armando', 'felix', 'jimmie', 'everett', 'jordan',
                         'ian', 'wallace', 'ken', 'bob', 'jaime', 'casey', 'alfredo', 'alberto',
                         'dave', 'ivan', 'johnnie', 'sidney', 'byron', 'julian', 'isaac', 'morris',
                         'clifton', 'willard', 'daryl', 'ross', 'virgil', 'andy', 'marshall', 'salvador',
                         'perry', 'kirk', 'sergio', 'marion', 'tracy', 'seth', 'kent', 'terrance',
                         'rene', 'eduardo', 'terrence', 'enrique', 'freddie', 'wade', 'austin',
                         'sarah', 'jennifer', 'lisa', 'nancy', 'karen', 'betty', 'helen', 'sandra',
                         'donna', 'carol', 'ruth', 'sharon', 'michelle', 'laura', 'sarah', 'kimberly',
                         'deborah', 'jessica', 'shirley', 'cynthia', 'angela', 'melissa', 'brenda',
                         'amy', 'anna', 'rebecca', 'virginia', 'kathleen', 'pamela', 'martha',
                         'debra', 'amanda', 'stephanie', 'carolyn', 'christine', 'marie', 'janet',
                         'catherine', 'frances', 'ann', 'joyce', 'diane', 'alice', 'julie', 'heather',
                         'teresa', 'doris', 'gloria', 'evelyn', 'jean', 'cheryl', 'mildred', 'katherine',
                         'joan', 'ashley', 'judith', 'rose', 'janice', 'kelly', 'nicole', 'judy',
                         'christina', 'kathy', 'theresa', 'beverly', 'denise', 'tammy', 'irene',
                         'jane', 'lori', 'rachel', 'marilyn', 'andrea', 'kathryn', 'louise', 'sara',
                         'anne', 'jacqueline', 'wanda', 'bonnie', 'julia', 'ruby', 'lois', 'tina',
                         'phyllis', 'norma', 'paula', 'diana', 'annie', 'lillian', 'emily', 'robin',
                         'peggy', 'crystal', 'gladys', 'rita', 'dawn', 'connie', 'florence', 'tracy',
                         'edna', 'tiffany', 'carmen', 'rosa', 'cindy', 'grace', 'wendy', 'victoria',
                         'edith', 'kim', 'sherry', 'sylvia', 'josephine', 'thelma', 'shannon', 'sheila',
                         'ethel', 'ellen', 'eleanor', 'francis', 'suzanne', 'maria', 'audrey', 'kristin',
                         'jean', 'cheryl', 'agnes', 'bertha', 'marion', 'charlotte', 'monica', 'dolores',
                         'carmen', 'ana', 'terri', 'jacqueline', 'kristi', 'candice', 'yvonne', 'jeanette',
                         'sue', 'elaine', 'kristine', 'anne', 'carrie', 'lisa', 'wendy', 'angela',
                         'donna', 'kathleen', 'nancy', 'betty', 'helen', 'sandra', 'donna', 'carol',
                         'ruth', 'sharon', 'michelle', 'laura', 'sarah', 'kimberly', 'deborah', 'jessica']
    
    # Check if it's a common first name
    if keyword_lower in common_first_names:
        return True
    
    # Check if it's a single capitalized word (likely a name unless it's a known place)
    if keyword[0].isupper() and len(keyword.split()) == 1:
        # If it appears in title as a standalone word, likely a name
        if title_words and keyword in title_words:
            # Check if it's followed by common name patterns
            keyword_idx = -1
            for i, word in enumerate(title_words):
                if word == keyword:
                    keyword_idx = i
                    break
            if keyword_idx >= 0:
                # Check surrounding words for name patterns
                if keyword_idx < len(title_words) - 1:
                    next_word = title_words[keyword_idx + 1].lower()
                    # Common patterns: "John Smith", "Mary,", "James said"
                    if next_word in ['said', 'told', 'reported', 'according', 'added', 'noted', 'explained']:
                        return True
                    # If next word is also capitalized, likely a name
                    if title_words[keyword_idx + 1][0].isupper():
                        return True
    
    # Check for name patterns like "John's" or "Mary's"
    if keyword_lower.endswith("'s") and len(keyword) > 3:
        return True
    
    return False


def is_common_word(keyword: str) -> bool:
    """Check if keyword is a common word that doesn't add relevance"""
    keyword_lower = keyword.lower()
    
    # Comprehensive stop words list
    stop_words = {
        # Articles
        'the', 'a', 'an',
        # Prepositions
        'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'up', 'about', 'into', 'through',
        'during', 'including', 'against', 'among', 'throughout', 'despite', 'towards', 'upon',
        'concerning', 'to', 'of', 'in', 'for', 'on', 'at', 'by', 'with', 'from', 'up', 'about',
        # Conjunctions
        'and', 'or', 'but', 'nor', 'so', 'yet', 'for', 'as', 'if', 'when', 'where', 'while',
        # Pronouns
        'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them', 'this', 'that',
        'these', 'those', 'who', 'whom', 'whose', 'which', 'what',
        # Common verbs
        'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
        'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'cannot',
        # Common news words
        'said', 'says', 'told', 'tells', 'reported', 'reports', 'according', 'added', 'noted', 'explained',
        'stated', 'announced', 'declared', 'mentioned', 'revealed', 'confirmed', 'denied',
        # Generic terms
        'article', 'report', 'news', 'story', 'update', 'information', 'officials', 'residents', 'people',
        'community', 'local', 'city', 'town', 'state', 'county', 'area', 'region', 'neighborhood',
        'officer', 'officers', 'police', 'department', 'fire', 'emergency', 'service', 'services',
        'time', 'times', 'day', 'days', 'week', 'weeks', 'month', 'months', 'year', 'years',
        'new', 'old', 'first', 'last', 'next', 'previous', 'recent', 'latest', 'early', 'late',
        'more', 'most', 'less', 'least', 'many', 'much', 'some', 'any', 'all', 'every', 'each',
        'other', 'another', 'such', 'same', 'very', 'too', 'also', 'only', 'just', 'even', 'still',
        'also', 'well', 'back', 'down', 'out', 'off', 'over', 'under', 'again', 'further', 'then',
        'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each', 'every', 'both',
        'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same',
        'so', 'than', 'too', 'very', 'can', 'will', 'just', 'don', 'should', 'now', 'get', 'got',
        'make', 'made', 'take', 'took', 'come', 'came', 'see', 'saw', 'know', 'knew', 'think', 'thought',
        'give', 'gave', 'find', 'found', 'go', 'went', 'say', 'said', 'tell', 'told', 'ask', 'asked',
        'work', 'worked', 'call', 'called', 'try', 'tried', 'need', 'needed', 'feel', 'felt', 'become',
        'became', 'leave', 'left', 'put', 'put', 'mean', 'meant', 'keep', 'kept', 'let', 'let',
        'begin', 'began', 'seem', 'seemed', 'help', 'helped', 'show', 'showed', 'hear', 'heard',
        'play', 'played', 'run', 'ran', 'move', 'moved', 'like', 'liked', 'live', 'lived', 'believe',
        'believed', 'bring', 'brought', 'happen', 'happened', 'write', 'wrote', 'sit', 'sat',
        'stand', 'stood', 'lose', 'lost', 'pay', 'paid', 'meet', 'met', 'include', 'included',
        'continue', 'continued', 'set', 'set', 'learn', 'learned', 'change', 'changed', 'lead', 'led',
        'understand', 'understood', 'watch', 'watched', 'follow', 'followed', 'stop', 'stopped',
        'create', 'created', 'speak', 'spoke', 'read', 'read', 'spend', 'spent', 'grow', 'grew',
        'open', 'opened', 'walk', 'walked', 'win', 'won', 'teach', 'taught', 'offer', 'offered',
        'remember', 'remembered', 'consider', 'considered', 'appear', 'appeared', 'buy', 'bought',
        'serve', 'served', 'die', 'died', 'send', 'sent', 'build', 'built', 'stay', 'stayed',
        'fall', 'fell', 'cut', 'cut', 'reach', 'reached', 'kill', 'killed', 'raise', 'raised',
        'pass', 'passed', 'sell', 'sold', 'decide', 'decided', 'return', 'returned', 'build', 'built',
        'join', 'joined', 'save', 'saved', 'agree', 'agreed', 'hit', 'hit', 'produce', 'produced',
        'eat', 'ate', 'cover', 'covered', 'catch', 'caught', 'draw', 'drew', 'choose', 'chose',
        'wear', 'wore', 'break', 'broke', 'seek', 'sought', 'throw', 'threw', 'deal', 'dealt',
        'fight', 'fought', 'lay', 'laid', 'lie', 'lay', 'ride', 'rode', 'ring', 'rang', 'rise',
        'rose', 'shake', 'shook', 'shine', 'shone', 'shoot', 'shot', 'shut', 'shut', 'sing', 'sang',
        'sink', 'sank', 'sleep', 'slept', 'slide', 'slid', 'speak', 'spoke', 'speed', 'sped',
        'spend', 'spent', 'spin', 'spun', 'spit', 'spat', 'split', 'split', 'spread', 'spread',
        'spring', 'sprang', 'stand', 'stood', 'steal', 'stole', 'stick', 'stuck', 'sting', 'stung',
        'strike', 'struck', 'swear', 'swore', 'sweep', 'swept', 'swim', 'swam', 'swing', 'swung',
        'take', 'took', 'teach', 'taught', 'tear', 'tore', 'tell', 'told', 'think', 'thought',
        'throw', 'threw', 'understand', 'understood', 'wake', 'woke', 'wear', 'wore', 'weep', 'wept',
        'win', 'won', 'wind', 'wound', 'write', 'wrote'
    }
    
    return keyword_lower in stop_words


def is_date_or_number(keyword: str) -> bool:
    """Check if keyword contains dates or numbers"""
    import re
    
    # Check if contains digits
    if re.search(r'\d', keyword):
        return True
    
    # Check for year patterns (2020-2030)
    if re.search(r'\b(20[0-3][0-9]|19[0-9]{2})\b', keyword):
        return True
    
    # Check for month names (standalone)
    months = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 
              'september', 'october', 'november', 'december', 'jan', 'feb', 'mar', 'apr',
              'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    keyword_lower = keyword.lower()
    if keyword_lower in months and len(keyword.split()) == 1:
        return True
    
    # Check for day names
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
            'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    if keyword_lower in days:
        return True
    
    # Check if it's just a number
    try:
        float(keyword.replace(',', '').replace('$', '').replace('%', ''))
        return True
    except ValueError:
        pass
    
    return False


def is_source_name(keyword: str, article_source: str = None) -> bool:
    """Check if keyword matches source name"""
    if not article_source:
        return False
    
    keyword_lower = keyword.lower()
    source_lower = article_source.lower()
    
    # Check if keyword is part of source name
    if keyword_lower in source_lower or source_lower in keyword_lower:
        return True
    
    # Check against known source names from config
    try:
        from config import NEWS_SOURCES
        for source_key, source_config in NEWS_SOURCES.items():
            source_name = source_config.get('name', '').lower()
            if keyword_lower in source_name or source_name in keyword_lower:
                return True
            # Check source key
            if keyword_lower == source_key.lower():
                return True
    except:
        pass
    
    # Common source-related terms
    source_terms = ['reporter', 'news', 'herald', 'gazette', 'times', 'journal', 'tribune',
                    'post', 'press', 'chronicle', 'observer', 'review', 'sun', 'star', 'globe',
                    'media', 'network', 'channel', 'station', 'radio', 'tv', 'television']
    
    # If keyword is a single source term, exclude it
    if keyword_lower in source_terms and len(keyword.split()) == 1:
        return True
    
    return False


def strip_html_tags(text: str) -> str:
    """Remove HTML tags and entities from text"""
    import re
    import html
    if not text:
        return ''
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode HTML entities
    text = html.unescape(text)
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def contains_html(keyword: str) -> bool:
    """Check if keyword contains HTML tags or entities"""
    import re
    # Check for HTML tags (including partial/malformed)
    if re.search(r'<[^>]*', keyword) or re.search(r'[^<]*>', keyword):
        return True
    # Check for HTML entities
    if re.search(r'&[a-z#0-9]+;', keyword.lower()):
        return True
    # Check for URLs
    if re.search(r'https?://|www\.', keyword.lower()):
        return True
    # Check for email addresses
    if re.search(r'@', keyword):
        return True
    # Check for common HTML attributes
    if re.search(r'(href|src|class|id|style)=', keyword.lower()):
        return True
    return False


def is_generic_term(keyword: str) -> bool:
    """Check if keyword is a generic term that doesn't add relevance"""
    keyword_lower = keyword.lower()
    
    # Generic news/journalism terms
    generic_terms = {
        'article', 'articles', 'report', 'reports', 'reporting', 'news', 'story', 'stories',
        'update', 'updates', 'information', 'details', 'according', 'officials', 'official',
        'residents', 'resident', 'people', 'person', 'persons', 'community', 'communities',
        'local', 'locals', 'city', 'cities', 'town', 'towns', 'state', 'states', 'county',
        'counties', 'area', 'areas', 'region', 'regions', 'neighborhood', 'neighborhoods',
        'officer', 'officers', 'police', 'department', 'departments', 'fire', 'emergency',
        'service', 'services', 'agency', 'agencies', 'organization', 'organizations',
        'group', 'groups', 'committee', 'committees', 'board', 'boards', 'council', 'councils',
        'meeting', 'meetings', 'event', 'events', 'incident', 'incidents', 'accident', 'accidents',
        'crash', 'crashes', 'investigation', 'investigations', 'case', 'cases', 'situation',
        'situations', 'issue', 'issues', 'problem', 'problems', 'concern', 'concerns',
        'matter', 'matters', 'subject', 'subjects', 'topic', 'topics', 'question', 'questions',
        'answer', 'answers', 'response', 'responses', 'statement', 'statements', 'comment',
        'comments', 'remark', 'remarks', 'announcement', 'announcements', 'release', 'releases',
        'press', 'media', 'public', 'private', 'government', 'municipal', 'federal', 'state',
        'county', 'local', 'national', 'international', 'regional', 'district', 'district',
        'authority', 'authorities', 'administration', 'administrations', 'office', 'offices',
        'building', 'buildings', 'facility', 'facilities', 'property', 'properties', 'site',
        'sites', 'location', 'locations', 'place', 'places', 'address', 'addresses', 'street',
        'streets', 'road', 'roads', 'avenue', 'avenues', 'boulevard', 'boulevards', 'drive',
        'drives', 'lane', 'lanes', 'way', 'ways', 'court', 'courts', 'circle', 'circles',
        'plaza', 'plazas', 'park', 'parks', 'square', 'squares', 'center', 'centers', 'centre',
        'centres', 'complex', 'complexes', 'development', 'developments', 'project', 'projects',
        'program', 'programs', 'programme', 'programmes', 'initiative', 'initiatives', 'plan',
        'plans', 'proposal', 'proposals', 'proposal', 'proposals', 'suggestion', 'suggestions',
        'idea', 'ideas', 'concept', 'concepts', 'notion', 'notions', 'thought', 'thoughts',
        'opinion', 'opinions', 'view', 'views', 'perspective', 'perspectives', 'point', 'points',
        'aspect', 'aspects', 'factor', 'factors', 'element', 'elements', 'component', 'components',
        'part', 'parts', 'piece', 'pieces', 'section', 'sections', 'segment', 'segments',
        'portion', 'portions', 'share', 'shares', 'percentage', 'percentages', 'percent',
        'percents', 'rate', 'rates', 'ratio', 'ratios', 'proportion', 'proportions', 'amount',
        'amounts', 'quantity', 'quantities', 'number', 'numbers', 'figure', 'figures', 'total',
        'totals', 'sum', 'sums', 'value', 'values', 'worth', 'worths', 'cost', 'costs', 'price',
        'prices', 'fee', 'fees', 'charge', 'charges', 'payment', 'payments', 'bill', 'bills',
        'invoice', 'invoices', 'account', 'accounts', 'balance', 'balances', 'budget', 'budgets',
        'fund', 'funds', 'funding', 'fundings', 'money', 'moneys', 'cash', 'cashes', 'dollar',
        'dollars', 'cent', 'cents', 'penny', 'pennies', 'nickel', 'nickels', 'dime', 'dimes',
        'quarter', 'quarters', 'half', 'halves', 'whole', 'wholes', 'full', 'fulls', 'empty',
        'empties', 'complete', 'completes', 'finished', 'finishes', 'done', 'dones', 'ready',
        'readies', 'prepared', 'prepares', 'set', 'sets', 'ready', 'readies', 'available',
        'availables', 'free', 'frees', 'busy', 'busies', 'occupied', 'occupies', 'taken',
        'takes', 'used', 'uses', 'unused', 'unuses', 'new', 'news', 'old', 'olds', 'young',
        'youngs', 'fresh', 'freshes', 'stale', 'stales', 'recent', 'recents', 'latest', 'latests',
        'current', 'currents', 'present', 'presents', 'past', 'pasts', 'future', 'futures',
        'previous', 'previouses', 'prior', 'priors', 'earlier', 'earliers', 'later', 'laters',
        'next', 'nexts', 'following', 'followings', 'subsequent', 'subsequents', 'final', 'finals',
        'last', 'lasts', 'first', 'firsts', 'initial', 'initials', 'beginning', 'beginnings',
        'start', 'starts', 'end', 'ends', 'finish', 'finishes', 'conclusion', 'conclusions',
        'ending', 'endings', 'closing', 'closings', 'closure', 'closures', 'completion', 'completions',
        'termination', 'terminations', 'cessation', 'cessations', 'stop', 'stops', 'halt', 'halts',
        'pause', 'pauses', 'break', 'breaks', 'interruption', 'interruptions', 'disruption',
        'disruptions', 'disturbance', 'disturbances', 'interference', 'interferences', 'obstruction',
        'obstructions', 'blockage', 'blockages', 'barrier', 'barriers', 'obstacle', 'obstacles',
        'hindrance', 'hindrances', 'impediment', 'impediments', 'difficulty', 'difficulties',
        'problem', 'problems', 'trouble', 'troubles', 'issue', 'issues', 'concern', 'concerns',
        'worry', 'worries', 'anxiety', 'anxieties', 'fear', 'fears', 'dread', 'dreads', 'terror',
        'terrors', 'horror', 'horrors', 'panic', 'panics', 'alarm', 'alarms', 'alert', 'alerts',
        'warning', 'warnings', 'caution', 'cautions', 'advisory', 'advisories', 'notice',
        'notices', 'notification', 'notifications', 'announcement', 'announcements', 'bulletin',
        'bulletins', 'message', 'messages', 'communication', 'communications', 'correspondence',
        'correspondences', 'letter', 'letters', 'mail', 'mails', 'email', 'emails', 'post',
        'posts', 'package', 'packages', 'parcel', 'parcels', 'shipment', 'shipments', 'delivery',
        'deliveries', 'transport', 'transports', 'transportation', 'transportations', 'transit',
        'transits', 'travel', 'travels', 'trip', 'trips', 'journey', 'journeys', 'voyage',
        'voyages', 'expedition', 'expeditions', 'adventure', 'adventures', 'excursion', 'excursions',
        'outing', 'outings', 'visit', 'visits', 'visitation', 'visitations', 'call', 'calls',
        'appointment', 'appointments', 'meeting', 'meetings', 'conference', 'conferences',
        'convention', 'conventions', 'gathering', 'gatherings', 'assembly', 'assemblies',
        'congregation', 'congregations', 'crowd', 'crowds', 'group', 'groups', 'team', 'teams',
        'squad', 'squads', 'unit', 'units', 'division', 'divisions', 'section', 'sections',
        'department', 'departments', 'branch', 'branches', 'office', 'offices', 'bureau',
        'bureaus', 'agency', 'agencies', 'organization', 'organizations', 'institution',
        'institutions', 'establishment', 'establishments', 'facility', 'facilities', 'venue',
        'venues', 'location', 'locations', 'place', 'places', 'site', 'sites', 'spot', 'spots',
        'point', 'points', 'position', 'positions', 'post', 'posts', 'station', 'stations',
        'base', 'bases', 'headquarters', 'headquarterses', 'main', 'mains', 'central', 'centrals',
        'primary', 'primaries', 'principal', 'principals', 'chief', 'chiefs', 'main', 'mains',
        'leading', 'leadings', 'top', 'tops', 'highest', 'highests', 'supreme', 'supremes',
        'ultimate', 'ultimates', 'final', 'finals', 'last', 'lasts', 'end', 'ends', 'conclusion',
        'conclusions', 'result', 'results', 'outcome', 'outcomes', 'consequence', 'consequences',
        'effect', 'effects', 'impact', 'impacts', 'influence', 'influences', 'power', 'powers',
        'force', 'forces', 'strength', 'strengths', 'might', 'mights', 'energy', 'energies',
        'vigor', 'vigors', 'vitality', 'vitalities', 'life', 'lives', 'existence', 'existences',
        'being', 'beings', 'entity', 'entities', 'thing', 'things', 'object', 'objects',
        'item', 'items', 'article', 'articles', 'piece', 'pieces', 'part', 'parts', 'component',
        'components', 'element', 'elements', 'factor', 'factors', 'aspect', 'aspects', 'feature',
        'features', 'characteristic', 'characteristics', 'trait', 'traits', 'quality', 'qualities',
        'property', 'properties', 'attribute', 'attributes', 'mark', 'marks', 'sign', 'signs',
        'indication', 'indications', 'signal', 'signals', 'symbol', 'symbols', 'token', 'tokens',
        'badge', 'badges', 'emblem', 'emblems', 'insignia', 'insignias', 'logo', 'logos',
        'brand', 'brands', 'label', 'labels', 'tag', 'tags', 'name', 'names', 'title', 'titles',
        'heading', 'headings', 'headline', 'headlines', 'caption', 'captions', 'subtitle',
        'subtitles', 'subheading', 'subheadings', 'header', 'headers', 'footer', 'footers',
        'footer', 'footers', 'note', 'notes', 'annotation', 'annotations', 'comment', 'comments',
        'remark', 'remarks', 'observation', 'observations', 'notice', 'notices', 'attention',
        'attentions', 'awareness', 'awarenesses', 'consciousness', 'consciousnesses', 'knowledge',
        'knowledges', 'understanding', 'understandings', 'comprehension', 'comprehensions',
        'grasp', 'grasps', 'grip', 'grips', 'hold', 'holds', 'clutch', 'clutches', 'seize',
        'seizes', 'grab', 'grabs', 'snatch', 'snatches', 'catch', 'catches', 'capture',
        'captures', 'take', 'takes', 'get', 'gets', 'obtain', 'obtains', 'acquire', 'acquires',
        'gain', 'gains', 'earn', 'earns', 'win', 'wins', 'achieve', 'achieves', 'attain',
        'attains', 'reach', 'reaches', 'accomplish', 'accomplishes', 'complete', 'completes',
        'finish', 'finishes', 'fulfill', 'fulfills', 'satisfy', 'satisfies', 'meet', 'meets',
        'suit', 'suits', 'fit', 'fits', 'match', 'matches', 'correspond', 'corresponds',
        'agree', 'agrees', 'accord', 'accords', 'harmonize', 'harmonizes', 'coordinate',
        'coordinates', 'synchronize', 'synchronizes', 'align', 'aligns', 'line', 'lines',
        'arrange', 'arranges', 'organize', 'organizes', 'order', 'orders', 'sort', 'sorts',
        'classify', 'classifies', 'categorize', 'categorizes', 'group', 'groups', 'cluster',
        'clusters', 'bunch', 'bunches', 'batch', 'batches', 'set', 'sets', 'collection',
        'collections', 'assembly', 'assemblies', 'gathering', 'gatherings', 'meeting', 'meetings',
        'conference', 'conferences', 'convention', 'conventions', 'congress', 'congresses',
        'parliament', 'parliaments', 'legislature', 'legislatures', 'assembly', 'assemblies',
        'council', 'councils', 'board', 'boards', 'committee', 'committees', 'commission',
        'commissions', 'panel', 'panels', 'jury', 'juries', 'tribunal', 'tribunals', 'court',
        'courts', 'bench', 'benches', 'judge', 'judges', 'justice', 'justices', 'magistrate',
        'magistrates', 'referee', 'referees', 'umpire', 'umpires', 'arbitrator', 'arbitrators',
        'mediator', 'mediators', 'negotiator', 'negotiators', 'intermediary', 'intermediaries',
        'go-between', 'go-betweens', 'middleman', 'middlemen', 'broker', 'brokers', 'agent',
        'agents', 'representative', 'representatives', 'delegate', 'delegates', 'deputy',
        'deputies', 'substitute', 'substitutes', 'replacement', 'replacements', 'stand-in',
        'stand-ins', 'understudy', 'understudies', 'backup', 'backups', 'reserve', 'reserves',
        'spare', 'spares', 'extra', 'extras', 'additional', 'additionals', 'supplementary',
        'supplementaries', 'complementary', 'complementaries', 'supplementary', 'supplementaries',
        'extra', 'extras', 'bonus', 'bonuses', 'premium', 'premiums', 'reward', 'rewards',
        'prize', 'prizes', 'award', 'awards', 'honor', 'honors', 'honour', 'honours', 'trophy',
        'trophies', 'medal', 'medals', 'badge', 'badges', 'ribbon', 'ribbons', 'certificate',
        'certificates', 'diploma', 'diplomas', 'degree', 'degrees', 'qualification',
        'qualifications', 'credential', 'credentials', 'license', 'licenses', 'licence',
        'licences', 'permit', 'permits', 'authorization', 'authorizations', 'authorisation',
        'authorisations', 'approval', 'approvals', 'consent', 'consents', 'agreement',
        'agreements', 'assent', 'assents', 'acceptance', 'acceptances', 'admission',
        'admissions', 'acknowledgment', 'acknowledgments', 'acknowledgement', 'acknowledgements',
        'recognition', 'recognitions', 'appreciation', 'appreciations', 'gratitude', 'gratitudes',
        'thanks', 'thank', 'thankful', 'grateful', 'appreciative', 'obliged', 'indebted',
        'beholden', 'grateful', 'thankful', 'appreciative', 'obliged', 'indebted', 'beholden'
    }
    
    return keyword_lower in generic_terms


def should_exclude_keyword(keyword: str, article_source: str = None, title_words: list = None) -> bool:
    """Check if keyword should be excluded from suggestions"""
    if contains_html(keyword):
        return True
    if is_person_name(keyword, title_words):
        return True
    if is_common_word(keyword):
        return True
    if is_date_or_number(keyword):
        return True
    if is_source_name(keyword, article_source):
        return True
    if is_generic_term(keyword):
        return True
    return False


def analyze_article_target(article_id: int, zip_code: str) -> dict:
    """Deep analysis of an article to identify why it's relevant and suggest keywords
    
    Args:
        article_id: Article ID to analyze
        zip_code: Zip code for zip-specific analysis
    
    Returns:
        Dict with relevance breakdown and suggested keywords
    """
    import re
    from collections import Counter
    from utils.relevance_calculator import calculate_relevance_score_with_tags, load_relevance_config
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Get article data with all metadata
    cursor.execute('SELECT title, content, summary, source, published, url, category, primary_category, category_confidence FROM articles WHERE id = ?', (article_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {'success': False, 'error': 'Article not found'}
    
    title = row[0] or ''
    content_raw = row[1] or row[2] or ''
    summary_raw = row[2] or ''
    source = row[3] or ''
    published = row[4] or ''
    url = row[5] or ''
    category = row[6] if row[6] else ''
    primary_category = row[7] if row[7] else ''
    category_confidence = row[8] if row[8] is not None else 0.0
    
    # Strip HTML from content and summary before processing
    content = strip_html_tags(content_raw)
    summary = strip_html_tags(summary_raw)
    
    article = {
        'id': article_id,
        'title': title,
        'content': content,
        'summary': summary,
        'source': source,
        'published': published
    }
    
    # Get relevance breakdown
    relevance_score, tag_info = calculate_relevance_score_with_tags(article, zip_code=zip_code)
    
    # Load current relevance config to check against
    config = load_relevance_config(zip_code=zip_code)
    
    # Extract text for keyword analysis
    combined_text = f"{title} {content} {summary}".lower()
    title_words = title.split()
    
    # Extract potential keywords
    suggested_keywords = {
        'high_relevance': [],
        'local_places': [],
        'topic_keywords': []
    }
    
    # Extract proper nouns (capitalized words, likely names/places)
    proper_nouns = []
    for word in title_words:
        if word and word[0].isupper() and len(word) > 2:
            # Skip common words
            if word.lower() not in ['the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by']:
                proper_nouns.append(word)
    
    # Extract repeated phrases (2+ words that appear multiple times)
    words = re.findall(r'\b\w+\b', combined_text)
    # Get 2-word phrases
    two_word_phrases = []
    for i in range(len(words) - 1):
        phrase = f"{words[i]} {words[i+1]}"
        if len(phrase) > 5:  # Skip very short phrases
            two_word_phrases.append(phrase)
    
    # Count phrase frequency
    phrase_counts = Counter(two_word_phrases)
    repeated_phrases = [phrase for phrase, count in phrase_counts.items() if count >= 2 and len(phrase) > 5]
    
    # Extract 3-word phrases
    three_word_phrases = []
    for i in range(len(words) - 2):
        phrase = f"{words[i]} {words[i+1]} {words[i+2]}"
        if len(phrase) > 8:
            three_word_phrases.append(phrase)
    
    phrase_counts_3 = Counter(three_word_phrases)
    repeated_phrases_3 = [phrase for phrase, count in phrase_counts_3.items() if count >= 2 and len(phrase) > 8]
    
    # Categorize keywords
    existing_high_relevance = set(config.get('high_relevance', []))
    existing_local_places = set(config.get('local_places', []))
    existing_topic_keywords = set(config.get('topic_keywords', {}).keys())
    
    # Location indicators (words that suggest a place)
    location_indicators = ['street', 'avenue', 'road', 'boulevard', 'park', 'plaza', 'center', 'centre', 
                          'school', 'hospital', 'library', 'building', 'bridge', 'river', 'parkway']
    
    # Check proper nouns
    for noun in proper_nouns:
        noun_lower = noun.lower()
        # Skip if already in config
        if noun_lower in existing_high_relevance or noun_lower in existing_local_places:
            continue
        
        # Filter out unwanted keywords
        if should_exclude_keyword(noun, source, title_words):
            continue
        
        # Check if it looks like a location
        if any(indicator in combined_text.lower() for indicator in location_indicators if noun_lower in combined_text.lower()):
            suggested_keywords['local_places'].append({
                'keyword': noun_lower,
                'confidence': 'high',
                'reason': 'Proper noun with location indicators'
            })
        elif len(noun) > 4:  # Longer proper nouns are more likely to be places
            suggested_keywords['local_places'].append({
                'keyword': noun_lower,
                'confidence': 'medium',
                'reason': 'Proper noun (potential location)'
            })
    
    # Check repeated phrases
    all_phrases = repeated_phrases + repeated_phrases_3
    for phrase in all_phrases[:20]:  # Limit to top 20
        phrase_lower = phrase.lower()
        
        # Skip if already in config
        if phrase_lower in existing_high_relevance or phrase_lower in existing_local_places or phrase_lower in existing_topic_keywords:
            continue
        
        # Filter out unwanted keywords
        if should_exclude_keyword(phrase, source, title_words):
            continue
        
        # Skip common phrases
        if phrase_lower in ['the city', 'the town', 'the state', 'the county', 'the area', 'the community']:
            continue
        
        # Check if phrase contains location indicators
        if any(indicator in phrase_lower for indicator in location_indicators):
            suggested_keywords['local_places'].append({
                'keyword': phrase_lower,
                'confidence': 'high',
                'reason': f'Repeated phrase ({phrase_counts.get(phrase, phrase_counts_3.get(phrase, 0))}x) with location indicator'
            })
        # Check if it matches topic patterns
        elif any(topic in phrase_lower for topic in ['city council', 'mayor', 'police', 'fire', 'school', 'business', 'event']):
            suggested_keywords['topic_keywords'].append({
                'keyword': phrase_lower,
                'confidence': 'high',
                'reason': f'Repeated phrase ({phrase_counts.get(phrase, phrase_counts_3.get(phrase, 0))}x) matching topic pattern'
            })
        else:
            # Default to high_relevance
            suggested_keywords['high_relevance'].append({
                'keyword': phrase_lower,
                'confidence': 'medium',
                'reason': f'Repeated phrase ({phrase_counts.get(phrase, phrase_counts_3.get(phrase, 0))}x)'
            })
    
    # Extract single important words (nouns that appear multiple times)
    word_counts = Counter(words)
    important_words = [(word, count) for word, count in word_counts.items() 
                      if count >= 3 and len(word) > 4 and word.lower() not in ['that', 'this', 'with', 'from', 'their', 'there', 'these', 'those', 'which', 'would', 'could', 'should']]
    important_words.sort(key=lambda x: x[1], reverse=True)
    
    for word, count in important_words[:15]:  # Top 15
        word_lower = word.lower()
        if word_lower in existing_high_relevance or word_lower in existing_local_places or word_lower in existing_topic_keywords:
            continue
        
        # Filter out unwanted keywords
        if should_exclude_keyword(word, source, title_words):
            continue
        
        suggested_keywords['high_relevance'].append({
            'keyword': word_lower,
            'confidence': 'medium',
            'reason': f'Frequent word ({count}x)'
        })
    
    # Count total suggested keywords (after all filtering)
    total_suggested = sum(len(kw_list) for kw_list in suggested_keywords.values())
    
    # Build breakdown with article metadata
    breakdown = {
        'total_score': relevance_score,
        'matched_tags': tag_info.get('matched', []),
        'missing_tags': tag_info.get('missing', []),
        'source': source,
        'published': published,
        'has_suggestions': total_suggested > 0  # Flag indicating if any keywords can be added
    }
    
    # Use primary_category if available, otherwise fall back to category
    display_category = primary_category if primary_category and primary_category.strip() else (category if category and category.strip() else '')
    
    # Article metadata for display
    article_metadata = {
        'id': article_id,
        'title': title,
        'source': source,
        'source_display': source,  # Can be enhanced later
        'published': published,
        'url': url,
        'category': category,
        'primary_category': primary_category,
        'display_category': display_category,  # The category to actually display
        'category_confidence': float(category_confidence) if category_confidence else 0.0,
        'summary': summary[:200] + '...' if len(summary) > 200 else summary  # Truncated summary
    }
    
    return {
        'success': True,
        'breakdown': breakdown,
        'suggested_keywords': suggested_keywords,
        'article': article_metadata
    }


def toggle_good_fit(article_id: int, zip_code: str, is_good_fit: bool) -> dict:
    """Toggle good fit status for an article"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Ensure is_good_fit column exists
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_good_fit INTEGER DEFAULT 0')
        conn.commit()
    except:
        pass
    
    # Get current display_order
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id
    
    # Check if entry exists
    cursor.execute('SELECT id FROM article_management WHERE article_id = ? AND zip_code = ?', (article_id, zip_code))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute('''
            UPDATE article_management 
            SET is_good_fit = ?, display_order = ?
            WHERE article_id = ? AND zip_code = ?
        ''', (1 if is_good_fit else 0, display_order, article_id, zip_code))
    else:
        cursor.execute('''
            INSERT INTO article_management (article_id, enabled, display_order, is_good_fit, zip_code)
            VALUES (?, 1, ?, ?, ?)
        ''', (article_id, display_order, 1 if is_good_fit else 0, zip_code))
    
    conn.commit()
    
    # Recalculate relevance scores when good fit is enabled
    if is_good_fit:
        try:
            from aggregator import NewsAggregator
            from utils.relevance_calculator import calculate_relevance_score
            
            # Get article data
            cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
            article_row = cursor.fetchone()
            
            if article_row:
                article = {key: article_row[key] for key in article_row.keys()}
                
                # Recalculate relevance score
                relevance_score = calculate_relevance_score(article, zip_code=zip_code)
                
                # Calculate local focus score (0-10)
                local_focus_score = calculate_local_focus_score(article, zip_code=zip_code)
                
                # Update article with new scores
                cursor.execute('''
                    UPDATE articles 
                    SET relevance_score = ?, local_score = ?
                    WHERE id = ?
                ''', (relevance_score, local_focus_score, article_id))
                
                conn.commit()
                logger.info(f"Recalculated relevance for article {article_id}: relevance={relevance_score:.1f}, local_focus={local_focus_score:.1f}/10")
                
                # Train the category classifier if article has a primary_category
                try:
                    primary_category = article.get('primary_category')
                    if primary_category:
                        from utils.category_classifier import CategoryClassifier
                        classifier = CategoryClassifier(zip_code)
                        article_for_training = {
                            'title': article.get('title', ''),
                            'content': article.get('content', ''),
                            'summary': article.get('summary', ''),
                            'source': article.get('source', '')
                        }
                        classifier.train_from_feedback(article_for_training, primary_category, is_positive=True)
                        logger.info(f"Trained classifier from good fit: article {article_id}, category {primary_category}")
                except Exception as e:
                    logger.warning(f"Could not train classifier from good fit: {e}")
                    # Don't fail if training fails
        except Exception as e:
            logger.warning(f"Could not recalculate relevance for article {article_id}: {e}")
            # Don't fail the good fit toggle if relevance calc fails
    
    conn.close()
    
    logger.info(f"Article {article_id} good fit set to {is_good_fit} for zip {zip_code}")
    return {'success': True, 'message': f'Good fit {"enabled" if is_good_fit else "disabled"}'}


def map_category_to_classifier(category_slug: str) -> str:
    """Map new category slugs to classifier category names"""
    mapping = {
        "local-news": "News",
        "crime": "Crime",
        "sports": "Sports",
        "events": "Entertainment",  # Classifier uses "Entertainment" not "Events"
        "weather": "News",
        "business": "Business",
        "schools": "Schools",
        "food": "News",
        "obituaries": "News"
    }
    # Also handle old category names
    old_to_new = {
        "news": "News",
        "entertainment": "Entertainment",
        "sports": "Sports",
        "local": "News",
        "custom": "News",
        "media": "Entertainment"
    }
    # First check if it's already a classifier category name
    if category_slug in ["News", "Crime", "Sports", "Entertainment", "Events", "Politics", "Schools", "Business", "Health", "Traffic", "Fire"]:
        return category_slug
    # Check new category slugs
    if category_slug in mapping:
        return mapping[category_slug]
    # Check old category names
    if category_slug in old_to_new:
        return old_to_new[category_slug]
    # Default fallback
    return "News"


def map_classifier_to_category(classifier_category: str) -> str:
    """Map classifier category names back to new category slugs"""
    mapping = {
        "News": "local-news",
        "Crime": "crime",
        "Sports": "sports",
        "Entertainment": "events",
        "Events": "events",
        "Business": "business",
        "Schools": "schools",
        "Politics": "local-news",
        "Health": "local-news",
        "Traffic": "local-news",
        "Fire": "local-news"
    }
    return mapping.get(classifier_category, "local-news")


def calculate_local_focus_score(article: dict, zip_code: str = None) -> float:
    """Calculate local focus score (0-10) based on Fall River mentions
    Weighted by location: byline > title > content
    Excludes source names like "Fall River Reporter"
    
    Args:
        article: Article dict with title, content, source, byline, author, etc.
        zip_code: Optional zip code for zip-specific config
    
    Returns:
        Local focus score between 0.0 and 10.0
    """
    try:
        content = article.get("content", article.get("summary", "")).lower()
        title = article.get("title", "").lower()
        source = article.get("source", "").lower()
        byline = article.get("byline", article.get("author", "")).lower()
        
        # Fall River variations to check
        fall_river_variations = [
            "fall river",
            "fallriver",
            "fall-river"
        ]
        
        score = 0.0
        max_score = 10.0
        
        # Check byline (highest weight - 4 points per mention, max 4 points)
        if byline:
            byline_mentions = sum(1 for variant in fall_river_variations if variant in byline)
            if byline_mentions > 0:
                score += min(4.0, byline_mentions * 4.0)
        
        # Check title (medium weight - 2 points per mention, max 4 points)
        # But exclude if it's just the source name
        if title:
            # Check if title contains source name patterns (like "Fall River Reporter")
            source_name_patterns = ["fall river reporter", "fall river news", "herald news"]
            is_source_name = any(pattern in title for pattern in source_name_patterns)
            
            if not is_source_name:
                title_mentions = sum(1 for variant in fall_river_variations if variant in title)
                if title_mentions > 0:
                    score += min(4.0, title_mentions * 2.0)
        
        # Check content (lower weight - 0.2 points per mention, max 2 points)
        if content:
            content_mentions = sum(1 for variant in fall_river_variations if variant in content)
            if content_mentions > 0:
                # Count unique mentions (approximate by checking first 10)
                unique_mentions = min(10, content_mentions)
                score += min(2.0, unique_mentions * 0.2)
        
        return min(max_score, score)
    except Exception as e:
        logger.warning(f"Error calculating local focus score: {e}")
        return 0.0


def get_articles(zip_code: str, show_trash: bool = False) -> list:
    """Get articles for a zip code"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Build WHERE clause
    where_clauses = ['a.zip_code = ?']
    where_params = [zip_code]
    
    # Rejection filter
    where_clauses.append('((am.is_rejected IS NULL AND ? = 0) OR (am.is_rejected = ?))')
    where_params.extend([1 if show_trash else 0, 1 if show_trash else 0])
    
    where_sql = ' AND '.join(where_clauses)
    query_params = ([zip_code] * 2) + where_params
    
    cursor.execute(f'''
        SELECT a.*, 
               COALESCE(am.enabled, 1) as enabled,
               COALESCE(am.display_order, a.id) as display_order,
               COALESCE(am.is_rejected, 0) as is_rejected,
               COALESCE(am.is_top_story, 0) as is_top_story,
               COALESCE(am.is_stellar, 0) as is_stellar,
               COALESCE(am.is_good_fit, 0) as is_good_fit
        FROM articles a
        LEFT JOIN (
            SELECT article_id, enabled, display_order, is_rejected, is_top_story, is_stellar, is_good_fit
            FROM article_management
            WHERE zip_code = ?
            AND ROWID IN (
                SELECT MAX(ROWID) 
                FROM article_management 
                WHERE zip_code = ?
                GROUP BY article_id
            )
        ) am ON a.id = am.article_id
        WHERE {where_sql}
        ORDER BY 
            CASE WHEN a.published IS NOT NULL AND a.published != '' THEN a.published ELSE '1970-01-01' END DESC,
            COALESCE(am.display_order, a.id) ASC
    ''', query_params)
    
    articles = [dict(row) for row in cursor.fetchall()]
    
    # Remove duplicates
    seen_ids = set()
    unique_articles = []
    for article in articles:
        article_id = article.get('id')
        if article_id and article_id not in seen_ids:
            seen_ids.add(article_id)
            unique_articles.append(article)
    
    # Calculate relevance scores for articles that don't have them
    from utils.relevance_calculator import calculate_relevance_score
    for article in unique_articles:
        if article.get('relevance_score') is None:
            article['relevance_score'] = calculate_relevance_score(article)
    
    conn.close()
    return unique_articles


def get_rejected_articles(zip_code: str) -> list:
    """Get rejected articles for trash tab"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Ensure columns exist
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
        conn.commit()
    except:
        pass
    
    cursor.execute('''
        SELECT a.*, 
               a.relevance_score,
               COALESCE(am.is_rejected, 0) as is_rejected,
               COALESCE(am.is_auto_rejected, 0) as is_auto_rejected,
               am.auto_reject_reason,
               CASE 
                   WHEN am.is_auto_rejected = 1 THEN 'auto'
                   WHEN am.is_rejected = 1 THEN 'manual'
                   ELSE 'unknown'
               END as rejection_type,
               am.ROWID as rejection_rowid
        FROM articles a
        INNER JOIN article_management am ON a.id = am.article_id
        WHERE am.zip_code = ?
        AND am.is_rejected = 1
        AND am.ROWID = (
            SELECT MAX(ROWID)
            FROM article_management
            WHERE article_id = a.id
            AND zip_code = ?
            AND is_rejected = 1
        )
        ORDER BY am.ROWID DESC
        LIMIT 100
    ''', (zip_code, zip_code))
    
    articles = []
    for row in cursor.fetchall():
        article = {key: row[key] for key in row.keys()}
        articles.append(article)
    
    conn.close()
    return articles


def get_sources(zip_code: str) -> dict:
    """Get sources configuration for a zip code"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    sources_config = {}
    
    if zip_code:
        # Get zip-specific source settings
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_%"', (zip_code,))
        source_settings = {}
        for row in cursor.fetchall():
            key = row['key']
            if key.startswith('source_'):
                parts = key.replace('source_', '').split('_', 1)
                if len(parts) == 2:
                    source_key = parts[0]
                    setting = parts[1]
                    if source_key not in source_settings:
                        source_settings[source_key] = {}
                    source_settings[source_key][setting] = row['value']
        
        # Get custom sources
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "custom_source_%"', (zip_code,))
        for row in cursor.fetchall():
            import json
            source_key = row['key'].replace('custom_source_', '')
            try:
                custom_data = json.loads(row['value'])
                custom_data['key'] = source_key
                sources_config[source_key] = custom_data
            except:
                pass
        
        # Get source overrides
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_override_%"', (zip_code,))
        for row in cursor.fetchall():
            import json
            source_key = row['key'].replace('source_override_', '')
            try:
                override_data = json.loads(row['value'])
                if source_key in sources_config:
                    sources_config[source_key].update(override_data)
                else:
                    from config import NEWS_SOURCES
                    if source_key in NEWS_SOURCES:
                        sources_config[source_key] = dict(NEWS_SOURCES[source_key])
                        sources_config[source_key].update(override_data)
                    else:
                        sources_config[source_key] = override_data
                    sources_config[source_key]['key'] = source_key
            except:
                pass
        
        # Apply settings
        for source_key in sources_config:
            if source_key in source_settings:
                if 'enabled' in source_settings[source_key]:
                    sources_config[source_key]['enabled'] = source_settings[source_key]['enabled'] == '1'
                if 'require_fall_river' in source_settings[source_key]:
                    sources_config[source_key]['require_fall_river'] = source_settings[source_key]['require_fall_river'] == '1'
    
    conn.close()
    return sources_config


def get_stats(zip_code: str) -> dict:
    """Get statistics for a zip code"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    stats = {}
    
    # Total articles
    if zip_code:
        cursor.execute('SELECT COUNT(*) FROM articles WHERE zip_code = ?', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM articles')
    stats['total_articles'] = cursor.fetchone()[0]
    
    # Active articles
    if zip_code:
        cursor.execute('''
            SELECT COUNT(DISTINCT a.id) FROM articles a
            LEFT JOIN article_management am ON a.id = am.article_id AND am.zip_code = ?
            WHERE (a.zip_code = ? OR a.zip_code IS NULL)
            AND COALESCE(am.is_rejected, 0) = 0
        ''', (zip_code, zip_code))
    else:
        cursor.execute('''
            SELECT COUNT(DISTINCT a.id) FROM articles a
            LEFT JOIN article_management am ON a.id = am.article_id
            WHERE COALESCE(am.is_rejected, 0) = 0
        ''')
    stats['active_articles'] = cursor.fetchone()[0]
    
    # Rejected articles
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM article_management
            WHERE is_rejected = 1 AND zip_code = ?
        ''', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE is_rejected = 1')
    stats['rejected_articles'] = cursor.fetchone()[0]
    
    # Top stories
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM article_management
            WHERE is_top_story = 1 AND zip_code = ?
        ''', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE is_top_story = 1')
    stats['top_stories'] = cursor.fetchone()[0]
    
    # Disabled articles
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM article_management
            WHERE enabled = 0 AND zip_code = ?
        ''', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE enabled = 0')
    stats['disabled_articles'] = cursor.fetchone()[0]
    
    # Articles by source
    if zip_code:
        cursor.execute('''
            SELECT source, COUNT(*) as count 
            FROM articles 
            WHERE zip_code = ? OR zip_code IS NULL
            GROUP BY source 
            ORDER BY count DESC
        ''', (zip_code,))
    else:
        cursor.execute('''
            SELECT source, COUNT(*) as count 
            FROM articles 
            GROUP BY source 
            ORDER BY count DESC
        ''')
    stats['articles_by_source'] = [{'source': row[0], 'count': row[1]} for row in cursor.fetchall()]
    
    # Articles by category
    if zip_code:
        cursor.execute('''
            SELECT COALESCE(category, 'uncategorized') as cat, COUNT(*) as count 
            FROM articles 
            WHERE zip_code = ? OR zip_code IS NULL
            GROUP BY cat 
            ORDER BY count DESC
        ''', (zip_code,))
    else:
        cursor.execute('''
            SELECT COALESCE(category, 'uncategorized') as cat, COUNT(*) as count 
            FROM articles 
            GROUP BY cat 
            ORDER BY count DESC
        ''')
    stats['articles_by_category'] = [{'category': row[0], 'count': row[1]} for row in cursor.fetchall()]
    
    # Category keywords and counts
    # Get category keywords from website_generator
    category_keywords = {
        "local-news": ["news", "update", "report", "announcement", "city", "town", "community"],
        "crime": ["crime", "police", "arrest", "suspect", "investigation", "charges", "court", "trial", "criminal"],
        "sports": ["sport", "football", "basketball", "baseball", "hockey", "athlete", "game", "team", "player"],
        "events": ["event", "concert", "show", "festival", "entertainment", "performance", "celebration"],
        "weather": ["weather", "forecast", "temperature", "rain", "snow", "storm", "climate"],
        "business": ["business", "company", "development", "economic", "commerce", "retail", "store", "shop"],
        "schools": ["school", "student", "teacher", "education", "academic", "college", "university", "graduation"],
        "food": ["food", "restaurant", "dining", "cafe", "menu", "chef", "cuisine", "meal"],
        "obituaries": ["obituary", "death", "passed away", "memorial", "funeral", "died", "remembered"]
    }
    
    # Get category article counts and keyword counts
    stats['categories_detail'] = []
    for category_slug, keywords in category_keywords.items():
        # Get article count for this category using keyword matching
        category_name = category_slug.replace('-', ' ').title()
        
        # Build SQL query to count articles matching any keyword in this category
        keyword_conditions = []
        params = []
        for keyword in keywords:
            keyword_conditions.append("(LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(summary) LIKE ?)")
            keyword_pattern = f'%{keyword}%'
            params.extend([keyword_pattern, keyword_pattern, keyword_pattern])
        
        where_clause = " OR ".join(keyword_conditions)
        if zip_code:
            query = f'''
                SELECT COUNT(DISTINCT id) FROM articles 
                WHERE (zip_code = ? OR zip_code IS NULL)
                AND ({where_clause})
            '''
            params = [zip_code] + params
        else:
            query = f'''
                SELECT COUNT(DISTINCT id) FROM articles 
                WHERE {where_clause}
            '''
        
        cursor.execute(query, params)
        article_count = cursor.fetchone()[0]
        
        stats['categories_detail'].append({
            'category': category_name,
            'slug': category_slug,
            'article_count': article_count,
            'keyword_count': len(keywords),
            'keywords': keywords
        })
    
    # Recent articles (last 7 days)
    from datetime import datetime, timedelta
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM articles 
            WHERE ((published IS NOT NULL AND published > ?) 
               OR (published IS NULL AND created_at > ?))
            AND (zip_code = ? OR zip_code IS NULL)
        ''', (week_ago, week_ago, zip_code))
    else:
        cursor.execute('''
            SELECT COUNT(*) FROM articles 
            WHERE ((published IS NOT NULL AND published > ?) 
               OR (published IS NULL AND created_at > ?))
        ''', (week_ago, week_ago))
    stats['articles_last_7_days'] = cursor.fetchone()[0]
    
    # Source fetch stats
    cursor.execute('SELECT source_key, last_fetch_time, last_article_count FROM source_fetch_tracking')
    stats['source_fetch_stats'] = [{'source': row[0], 'last_fetch': row[1], 'count': row[2]} for row in cursor.fetchall()]
    
    conn.close()
    return stats


def get_settings(zip_code: str) -> dict:
    """Get settings (merge global and zip-specific)"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    settings = {}
    
    # Get global settings
    cursor.execute('SELECT key, value FROM admin_settings')
    for row in cursor.fetchall():
        settings[row['key']] = row['value']
    
    # Get zip-specific settings (override global)
    if zip_code:
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ?', (zip_code,))
        for row in cursor.fetchall():
            settings[row['key']] = row['value']
    
    conn.close()
    return settings


def init_admin_db():
    """Initialize admin settings table"""
    from database import ArticleDatabase
    db = ArticleDatabase()
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Create admin_settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                value TEXT
            )
        ''')
        
        # Create article_management table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS article_management (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER,
                enabled INTEGER DEFAULT 1,
                display_order INTEGER DEFAULT 0,
                FOREIGN KEY (article_id) REFERENCES articles (id)
            )
        ''')
        
        # Add columns if they don't exist
        for col in ['is_rejected', 'is_top_story', 'is_auto_rejected', 'auto_reject_reason', 'zip_code', 'is_stellar', 'is_good_fit']:
            try:
                cursor.execute(f'ALTER TABLE article_management ADD COLUMN {col} INTEGER DEFAULT 0')
            except:
                pass
        
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
        except:
            pass
        
        # Create admin_settings_zip table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings_zip (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zip_code TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                UNIQUE(zip_code, key)
            )
        ''')
        
        # Create index
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_admin_settings_zip_code ON admin_settings_zip(zip_code)')
        except:
            pass
        
        # Create categories table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                zip_code TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, zip_code)
            )
        ''')
        
        # Create index on categories
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_categories_zip_code ON categories(zip_code)')
        except:
            pass
        
        # Initialize default categories for all zip codes
        from config import CATEGORY_SLUGS
        
        # Old categories to remove
        old_categories = ['news', 'entertainment', 'sports', 'local', 'custom', 'media']
        
        # Get all zip codes from articles
        cursor.execute('SELECT DISTINCT zip_code FROM articles WHERE zip_code IS NOT NULL')
        zip_codes = [row[0] for row in cursor.fetchall()]
        # Also check admin_settings_zip for zip codes
        cursor.execute('SELECT DISTINCT zip_code FROM admin_settings_zip WHERE zip_code IS NOT NULL')
        zip_codes.extend([row[0] for row in cursor.fetchall()])
        zip_codes = list(set(zip_codes))  # Remove duplicates
        
        # If no zip codes found, use a default (02720 for Fall River)
        if not zip_codes:
            zip_codes = ['02720']
        
        # Update categories for each zip code
        for zip_code in zip_codes:
            # Remove old categories
            for old_cat in old_categories:
                try:
                    cursor.execute('''
                        DELETE FROM categories WHERE name = ? AND zip_code = ?
                    ''', (old_cat, zip_code))
                except:
                    pass
            
            # Insert new categories (using slugs as names)
            for slug, name in CATEGORY_SLUGS.items():
                try:
                    # Use REPLACE to update if exists, insert if not
                    cursor.execute('''
                        INSERT OR REPLACE INTO categories (name, zip_code)
                        VALUES (?, ?)
                    ''', (slug, zip_code))
                except:
                    pass
        
        # Special handling for 02720 - ensure it has all new categories
        zip_code_02720 = '02720'
        # Remove all old categories for 02720
        for old_cat in old_categories:
            try:
                cursor.execute('''
                    DELETE FROM categories WHERE name = ? AND zip_code = ?
                ''', (old_cat, zip_code_02720))
            except:
                pass
        
        # Insert all new categories for 02720
        for slug, name in CATEGORY_SLUGS.items():
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO categories (name, zip_code)
                    VALUES (?, ?)
                ''', (slug, zip_code_02720))
            except:
                pass
        
        # Initialize default settings
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('show_images', '1')
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('relevance_threshold', '10')
        ''')
        
        conn.commit()

