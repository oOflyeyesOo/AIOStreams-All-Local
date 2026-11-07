from concurrent.futures import ThreadPoolExecutor
import threading,time,unittest
from tools.search_broker import SearchCache
class SearchBrokerTests(unittest.TestCase):
    def test_identical_concurrent_queries_share_one_upstream_call(self):
        calls=[]
        def fetch(path,headers):calls.append(path);time.sleep(.05);return 200,{},b'fixture'
        cache=SearchCache(fetch)
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:cache.get('/search?q=fixture',{'X-Api-Key':'fixture-key'}),range(8)))
            self.assertEqual(len(calls),1);self.assertTrue(all(r[2]==b'fixture' for r in results))
            self.assertGreater(cache.status()['coalesced'],0)
            self.assertEqual(cache.get('/search?q=fixture',{'X-Api-Key':'fixture-key'})[0],200)
            self.assertEqual(len(calls),1)
        finally:cache.close()
    def test_credential_partitions_do_not_share_results(self):
        calls=[]
        cache=SearchCache(lambda p,h:(calls.append(p) or (200,{},h['X-Api-Key'].encode())))
        try:
            self.assertEqual(cache.get('/same',{'X-Api-Key':'account-a'})[2],b'account-a')
            self.assertEqual(cache.get('/same',{'X-Api-Key':'account-b'})[2],b'account-b')
            self.assertEqual(len(calls),2)
        finally:cache.close()
    def test_timeout_cooldown_prevents_repeated_work(self):
        calls=[]
        def fail(p,h):calls.append(p);raise TimeoutError()
        cache=SearchCache(fail)
        try:
            self.assertEqual(cache.get('/slow',{})[0],504)
            self.assertEqual(cache.get('/slow',{})[0],504)
            self.assertEqual(len(calls),1)
        finally:cache.close()
    def test_capacity_and_cache_memory_are_bounded(self):
        entered=threading.Event();release=threading.Event()
        def slow(p,h):entered.set();release.wait(1);return 200,{},b'1234'
        cache=SearchCache(slow,workers=1,byte_limit=8,max_entries=2)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                first=pool.submit(cache.get,'/one',{});entered.wait(1)
                self.assertEqual(cache.get('/two',{})[0],503);release.set();first.result()
            for i in range(5):cache.get('/item'+str(i),{})
            self.assertLessEqual(cache.status()['cacheBytes'],8)
            self.assertLessEqual(cache.status()['cacheEntries'],2)
        finally:release.set();cache.close()
