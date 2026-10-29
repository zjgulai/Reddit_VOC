import os,sys,unittest,json,importlib,time
from pathlib import Path
root=Path('/Users/pray/project/Reddit_VOC')
sys.path[:0]=[str(root/'src'),str(root)]
sys.dont_write_bytecode=True
for key in ['DEEPSEEK_API_KEY','TIKHUB_API_KEY','DINGTALK_WEBHOOK_URL','DINGTALK_WEBHOOK_SECRET']:
    os.environ.pop(key,None)
for key in ['REDDIT_VOC_ENABLE_TIKHUB','REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND','REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION']:
    os.environ[key]='0'
def guard(event,args):
    if event=='socket.connect':
        raise PermissionError('audit_network_disabled')
sys.addaudithook(guard)
modules=['test_daily_collector','test_tikhub_collector','test_raw_artifacts','test_webapp','test_keywords_analyzer','test_time_window','test_dingtalk_delivery','test_deepseek_client','test_backfill_storage','test_backfill_provider','test_backfill_validation','test_backfill_profile','test_backfill_seed','test_browser_profile','test_provider_attempt_ledger','test_source_batch','test_daily_source_batch_export','test_v2_center_canonical_export','test_product_entity_resolution','test_reddit_v3_reporting_periods','test_reddit_v3_content_integrity','test_ops_governance','test_translation_pipeline','test_report_contracts']
suite=unittest.TestSuite(); unavailable={}
for name in modules:
    try:
        module=importlib.import_module('tests.'+name)
    except ImportError as exc:
        unavailable[name]=str(exc)
        continue
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
start=time.monotonic()
with Path('/tmp/reddit-voc-audit-20261014/backend-tests.log').open('w') as log:
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
summary={'runner':'stdlib unittest; socket.connect denied','requested_modules':len(modules),'unavailable_modules':unavailable,'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'elapsed_seconds':round(time.monotonic()-start,2)}
Path('/tmp/reddit-voc-audit-20261014/backend-tests.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False,indent=2))
