# Bayesian Learning System for Article Filtering

## Problem
The current filtering system doesn't learn from user rejections. When an article about Cape Cod or Tiverton is rejected, similar articles still get through. We need a system that learns patterns from rejections and automatically filters similar articles.

## Solution
Implement a Naive Bayes classifier that learns from rejected articles and applies learned patterns during filtering.

## Implementation

### 1. Create `utils/bayesian_learner.py`
- **Feature Extraction**:
  - Extract keywords (important nouns, verbs, locations)
  - Identify nearby towns mentioned (Cape Cod, Tiverton, Somerset, Swansea, etc.)
  - Detect topics/categories
  - Check for Fall River connection (explicit mention or high relevance)
  - Extract n-grams (2-3 word phrases)
  
- **Naive Bayes Classifier**:
  - Calculate P(reject | features) = probability of rejection given features
  - Update model weights when articles are rejected
  - Use Laplace smoothing to handle unseen features
  
- **Similarity Detection**:
  - Compare new articles to learned rejection patterns
  - Calculate feature overlap score
  - Combine with Bayesian probability for final decision

### 2. Database Schema
Add table to store learned patterns:
```sql
CREATE TABLE IF NOT EXISTS rejection_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feature TEXT NOT NULL,
    feature_type TEXT,  -- 'keyword', 'location', 'topic', 'nearby_town'
    reject_count INTEGER DEFAULT 1,
    accept_count INTEGER DEFAULT 0,
    last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(feature, feature_type)
)
```

### 3. Integration Points

**In `admin.py` - `reject_article` endpoint**:
- After rejecting an article, extract features
- Train the Bayesian model with rejection example
- Update rejection_patterns table

**In `aggregator.py` - `filter_relevant_articles` method**:
- Before final acceptance, check Bayesian probability
- If P(reject) > 0.7 (70% confidence), filter the article
- Log Bayesian filtering decisions

### 4. Context-Aware Filtering
- **Nearby Towns Without Fall River Connection**:
  - If article mentions "Cape Cod" or "Tiverton" but no "Fall River" mention
  - AND relevance score < 15 (low local connection)
  - AND Bayesian probability of rejection > 0.6
  - → Filter out
  
- **Nearby Towns With Fall River Connection**:
  - If article mentions both nearby town AND Fall River
  - OR has high relevance score (>= 20)
  - → Allow through (even if Bayesian suggests rejection)

### 5. Learning Algorithm
- **Initial Training**: Extract features from all existing rejected articles
- **Incremental Learning**: Update model when new articles are rejected
- **Weight Decay**: Older rejections have less influence (optional)
- **Feature Importance**: Nearby towns and topics weighted higher than generic keywords

## Files to Create/Modify
- `utils/bayesian_learner.py` - New Bayesian learning system
- `database.py` - Add rejection_patterns table initialization
- `admin.py` - Train model when articles are rejected
- `aggregator.py` - Integrate Bayesian filtering

## Expected Behavior
1. User rejects article about "Cape Cod restaurant opening"
2. System extracts features: ["cape cod", "restaurant", "opening", nearby_town: "cape cod"]
3. Model learns: articles with "cape cod" + "restaurant" + no "fall river" = likely rejection
4. Next similar article: "New Cape Cod seafood restaurant opens" → Auto-filtered (P(reject) = 0.85)
5. But: "Fall River residents visit Cape Cod restaurant" → Allowed (has Fall River connection)

