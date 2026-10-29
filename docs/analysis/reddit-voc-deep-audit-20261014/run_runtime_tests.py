import os,sys,unittest,json,importlib,time
from pathlib import Path
root=Path('/Users/pray/project/Reddit_VOC')
sys.path[:0]=[str(root/'src'),str(root)]
sys.dont_write_bytecode=True
os.environ['PYTHONPATH']=str(root/'src')+':'+str(root)
for key in ['DEEPSEEK_API_KEY','TIKHUB_API_KEY','DINGTALK_WEBHOOK_URL','DINGTALK_WEBHOOK_SECRET']:
    os.environ.pop(key,None)
for key in ['REDDIT_VOC_ENABLE_TIKHUB','REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND','REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION']:
    os.environ[key]='0'
def guard(event,args):
    if event=='socket.connect':
        raise PermissionError('audit_network_disabled')
sys.addaudithook(guard)
modules=['test_daily_report_ops','test_daily_report_launcher']
suite=unittest.TestSuite(); unavailable={}
for name in modules:
    try:
        module=importlib.import_module('tests.'+name)
    except ImportError as exc:
        unavailable[name]=str(exc)
        continue
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
start=time.monotonic()
with Path('/tmp/reddit-voc-audit-20261014/runtime-tests.log').open('w') as log:
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
summary={'runner':'stdlib unittest; socket.connect denied','requested_modules':len(modules),'unavailable_modules':unavailable,'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'elapsed_seconds':round(time.monotonic()-start,2)}
Path('/tmp/reddit-voc-audit-20261014/runtime-tests.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False,indent=2))
