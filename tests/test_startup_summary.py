import importlib.util
import json
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('startup_summary',Path(__file__).with_name('summarize_startup.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class StartupSummaryTests(unittest.TestCase):
    def test_no_raw_error_logs_or_urls_are_forwarded(self):
        secret='fixture-sensitive-marker'
        state={'Status':'running','ExitCode':0,'OOMKilled':False,'Error':secret,
               'Health':{'Status':'unhealthy','Log':[{'ExitCode':1,'Output':'Unexpected status code: 503 '+secret}]}}
        result=module.summarize(state,'fetch failed https://example.invalid/'+secret+' ENOTFOUND')
        self.assertEqual(result['checks'][0]['httpStatus'],503)
        self.assertTrue(result['logSignals']['dnsFailure'])
        self.assertNotIn(secret,json.dumps(result));self.assertNotIn('https://',json.dumps(result))
