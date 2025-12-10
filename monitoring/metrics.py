"""
Performance metrics and monitoring
"""
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# Metrics storage
_metrics = defaultdict(list)
_metrics_file = Path("metrics.json")


class MetricsCollector:
    """Collect and track performance metrics"""
    
    def __init__(self):
        self.metrics = defaultdict(list)
        self.metrics_file = _metrics_file
    
    def record_timing(self, operation: str, duration: float, metadata: Optional[Dict] = None):
        """Record timing for an operation"""
        entry = {
            "operation": operation,
            "duration": duration,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        self.metrics[operation].append(entry)
        
        # Keep only last 100 entries per operation
        if len(self.metrics[operation]) > 100:
            self.metrics[operation] = self.metrics[operation][-100:]
        
        logger.debug(f"Metric: {operation} took {duration:.2f}s")
    
    def record_count(self, metric_name: str, count: int, metadata: Optional[Dict] = None):
        """Record a count metric"""
        entry = {
            "metric": metric_name,
            "count": count,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        self.metrics[metric_name].append(entry)
    
    def get_stats(self, operation: Optional[str] = None) -> Dict:
        """Get statistics for an operation or all operations"""
        if operation:
            if operation not in self.metrics:
                return {}
            
            entries = self.metrics[operation]
            if not entries:
                return {}
            
            durations = [e["duration"] for e in entries if "duration" in e]
            if not durations:
                return {}
            
            return {
                "operation": operation,
                "count": len(entries),
                "avg_duration": sum(durations) / len(durations),
                "min_duration": min(durations),
                "max_duration": max(durations),
                "last_duration": durations[-1] if durations else None
            }
        else:
            # Return stats for all operations
            stats = {}
            for op in self.metrics.keys():
                stats[op] = self.get_stats(op)
            return stats
    
    def save_metrics(self):
        """Save metrics to file"""
        try:
            with open(self.metrics_file, 'w', encoding='utf-8') as f:
                json.dump(dict(self.metrics), f, default=str, indent=2)
        except Exception as e:
            logger.warning(f"Could not save metrics: {e}")
    
    def load_metrics(self):
        """Load metrics from file"""
        try:
            if self.metrics_file.exists():
                with open(self.metrics_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.metrics.update(data)
        except Exception as e:
            logger.warning(f"Could not load metrics: {e}")


# Global metrics collector
_metrics_collector = MetricsCollector()


def get_metrics() -> MetricsCollector:
    """Get global metrics collector"""
    return _metrics_collector


class TimingContext:
    """Context manager for timing operations"""
    
    def __init__(self, operation: str, metadata: Optional[Dict] = None):
        self.operation = operation
        self.metadata = metadata
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        get_metrics().record_timing(self.operation, duration, self.metadata)

