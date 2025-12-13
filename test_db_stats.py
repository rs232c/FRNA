#!/usr/bin/env python3
"""
Test script for database stats functionality
"""

try:
    from admin.services import get_database_stats
    print('SUCCESS: get_database_stats function imported successfully')

    stats = get_database_stats()
    print('SUCCESS: Database stats retrieved successfully')

    print(f'   Total articles: {stats["article_stats"]["total"]}')
    print(f'   Database size: {stats["database_info"]["size_mb"]} MB')
    print(f'   Tables: {stats["database_info"]["tables"]}')
    print(f'   Training samples: {stats["ai_ml_stats"]["training_samples"]}')
    print(f'   Data completeness: {stats["health_stats"]["data_completeness"]}%')
    print('SUCCESS: All database stats functions working')

except Exception as e:
    print(f'ERROR: {e}')
    import traceback
    traceback.print_exc()
