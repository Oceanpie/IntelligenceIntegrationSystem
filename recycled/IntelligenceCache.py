import datetime
import threading
from typing import Optional, Callable

from ServiceComponent.IntelligenceHubDefines import APPENDIX_TIME_ARCHIVED, APPENDIX_MAX_RATE_SCORE
from ServiceComponent.IntelligenceQueryEngine import IntelligenceQueryEngine
from Tools.DateTimeUtility import get_aware_time


class IntelligenceCache:
    def __init__(self, db_archive, threshold: int, count_limit: int, period_limit: Optional[datetime.timedelta]):
        self.threshold = threshold
        self.db_archive = db_archive
        self.count_limit = count_limit
        self.period_limit = period_limit

        self.lock = threading.Lock()
        self.cache = []  # Sorted by data['APPENDIX'][APPENDIX_TIME_ARCHIVED] in descending order

    def encache(self, data: dict) -> bool:
        """
        Insert data into cache in descending order based on APPENDIX_TIME_ARCHIVED.

        Args:
            data: ArchivedData object to be cached

        Returns:
            bool: True if successfully cached else False
        """
        with self.lock:
            # Get the archive time from appendix
            archive_time = data.get('APPENDIX', {}).get(APPENDIX_TIME_ARCHIVED, None)
            if not archive_time:
                return False

            if data.get('APPENDIX', {}).get(APPENDIX_MAX_RATE_SCORE, 10) < self.threshold:
                return False

            if not self.cache:
                self.cache.insert(0, data)
                return True

            # Find the correct position to insert (maintain descending order)
            for i, cached_item in enumerate(self.cache):
                cached_time = cached_item['APPENDIX'][APPENDIX_TIME_ARCHIVED]

                # 如果新数据时间更晚，插入到当前位置前面
                if archive_time > cached_time:
                    insert_index = i
                    break
            else:
                # 循环正常结束（未break），说明新数据是最早的，插入到末尾
                insert_index = len(self.cache)

            # Insert at the found position
            self.cache.insert(insert_index, data)
            self._check_drop_out_of_period(self.cache)

            return True

    def load_cache(self) -> bool:
        """
        Load data from database into cache for the specified cache period.

        Returns:
            bool: True if loading was successful, False otherwise
        """
        try:
            # Create query engine and build query
            query_engine = IntelligenceQueryEngine(self.db_archive)

            if self.count_limit:
                results, count = query_engine.query_intelligence(threshold = self.threshold, skip = 0, limit = self.count_limit)
            else:
                # Calculate time range for query
                end_time = get_aware_time()
                start_time = end_time - self.period_limit

                # Execute query and process results
                results, count = query_engine.query_intelligence(archive_period=(start_time, end_time))

            results_sorted = sorted(
                    results,
                    key=lambda item: item['APPENDIX'][APPENDIX_TIME_ARCHIVED],
                    reverse=True
                )
            self._check_drop_out_of_period(results_sorted)

            with self.lock:
                self.cache = results_sorted

                return True

        except Exception as e:
            print(f"Error loading cache: {e}")
            return False

    def get_cached_data(self,
                        filter_func: Optional[Callable[[dict], bool]] = None,
                        map_function: Optional[Callable[[dict], any]] = None,
                        limit: Optional[int] = 0) -> list:
        """
        Retrieve data from cache with optional filtering and mapping.

        Args:
            filter_func: Function to filter cached items
            map_function: Function to transform cached items
            limit: Data limit (0 means no limit)

        Returns:
            list: Processed cached data
        """
        with self.lock:
            # Handle limit = 0 (no limit) or negative values
            if limit is None or limit <= 0:
                limit = None

            # Apply filtering with early termination if limit is set
            if filter_func:
                filtered_data = []
                for item in self.cache:
                    if filter_func(item):
                        filtered_data.append(item)
                        if limit is not None and len(filtered_data) >= limit:
                            break
            else:
                # If no filter, just take the first 'limit' items
                filtered_data = self.cache[:limit] if limit is not None else self.cache

            # Apply mapping if provided
            if map_function:
                result = [map_function(item) for item in filtered_data]
            else:
                result = filtered_data

            return result

    def _check_drop_out_of_period(self, cache_queue: list):
        """
        Remove expired data from cache based on period_limit.
        """
        if self.period_limit:
            current_time = get_aware_time()
            cutoff_time = current_time - self.period_limit
        else:
            cutoff_time = None

        # Remove items from the end until we reach data within the cache period
        while cache_queue:
            if self.count_limit and len(cache_queue) > self.count_limit:
                cache_queue.pop()
                continue
            if cutoff_time:
                oldest_item = cache_queue[-1]
                oldest_time = oldest_item['APPENDIX'][APPENDIX_TIME_ARCHIVED]
                if oldest_time < cutoff_time:
                    cache_queue.pop()
                    continue
            break
