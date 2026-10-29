import sys,os,json,sqlite3,tempfile,ast,csv
from pathlib import Path
from datetime import datetime,timezone
from dataclasses import replace
from unittest.mock import patch
from types import SimpleNamespace
ROOT=Path('/Users/pray/project/Reddit_VOC')
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
sys.dont_write_bytecode=True
def guard(event,args):
    if event=='socket.connect': raise PermissionError('audit_network_disabled')
sys.addaudithook(guard)
from reddit_voc.storage import VocStore
from reddit_voc.models import RedditThread,DailyCollectionSummary
from reddit_voc.collector import collect_daily_reddit,build_listing_url,_derive_status,_reanalyze_run_with_deepseek
from reddit_voc.tikhub import collect_daily_tikhub,_derive_provider_status
from reddit_voc.report_source_state import classify_report_source_state
from reddit_voc.ops import build_missed_run_report
from tests.test_daily_collector import FakeRunner
from tests.test_webapp import WebappPayloadTests
from webapp import app
from openpyxl import Workbook,load_workbook
results={}
with tempfile.TemporaryDirectory(prefix='reddit-voc-repro-') as t:
    base=Path(t); store=VocStore(base/'runs.db'); store.migrate()
    listing=(ROOT/'tests/fixtures/reddit_listing_browser_json.json').read_text()
    detail=(ROOT/'tests/fixtures/reddit_thread_browser_json.json').read_text()
    listing_url=build_listing_url('ExclusivelyPumping')
    detail_url='https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/.json'
    for run_id in ['audit_A','audit_B']:
        if run_id=='audit_B':
            try:
                collect_daily_reddit(store,run_id='audit_raw_collision',runner=FakeRunner({listing_url:listing,detail_url:detail}),subreddits=['ExclusivelyPumping'],anchor_utc=datetime(2026,7,7,23,tzinfo=timezone.utc))
            except ValueError as exc:
                results['F03_browser_raw_collision']=str(exc)
            listing+='\n'; detail+='\n'
        summary=collect_daily_reddit(store,run_id=run_id,runner=FakeRunner({listing_url:listing,detail_url:detail}),subreddits=['ExclusivelyPumping'],anchor_utc=datetime(2026,7,7,23,tzinfo=timezone.utc))
        results[run_id]={'status':summary.status,'raw_count':store.count_for_run('raw_captures',run_id),'post_count':store.count_for_run('reddit_threads',run_id)}
    results['F02_history_after_reobserve']={table:store.count_for_run(table,'audit_A') for table in ['reddit_threads','reddit_comments','analysis_results','raw_captures']}
    results['F03_browser_raw_second_run']=store.count_for_run('raw_captures','audit_B')
    class FailedClient:
        def get_json(self,*a,**kw): raise TimeoutError('synthetic_failure')
    failed=collect_daily_tikhub(store,run_id='audit_B',client=FailedClient(),subreddits=['ExclusivelyPumping'],search_terms=['Momcozy'],anchor_utc=datetime(2026,7,7,23,tzinfo=timezone.utc))
    results['F04_failed_recollect']={'status':failed.status,'post_count_after':store.count_for_run('reddit_threads','audit_B')}
    summary=DailyCollectionSummary(run_id='synthetic',status='failed',window_start_utc='',window_end_utc='',subreddits=[],discovered_posts=1,relevant_posts=0,issues=[{'stage':'listing','reason':'synthetic_partial_failure'}])
    capped=DailyCollectionSummary(run_id='synthetic',status='failed',window_start_utc='',window_end_utc='',subreddits=[],relevant_posts=2,ingested_threads=1,coverage={'full':1})
    results['F16_truncated_status']={'browser':_derive_status(capped),'tikhub':_derive_provider_status(capped)}
    results['F05_empty_despite_failure']={'browser':_derive_status(summary),'tikhub':_derive_provider_status(summary),'report_gate':classify_report_source_state(status=_derive_provider_status(summary),post_count=0,comment_count=0)}
    failed_store=VocStore(base/'failed-only.db'); failed_store.migrate()
    failed_store.upsert_run('audit_failed_only','failed','2026-07-06T23:00:00+00:00','2026-07-07T23:00:00+00:00')
    results['F09_missed_run'] = build_missed_run_report(failed_store,anchor_utc=datetime(2026,7,7,23,tzinfo=timezone.utc))
    with store.connect() as conn:
        results['F10_query_plan']=[list(row) for row in conn.execute('EXPLAIN QUERY PLAN SELECT * FROM reddit_comments WHERE run_id=?',('audit_A',))]
    # Exercise the actual legacy analyzer reanalysis path with a fake provider result.
    post=RedditThread(post_id='audit_p',run_id='audit_C',raw_capture_id='audit_raw',subreddit='audit',title='audit',source_url='https://www.reddit.com/r/audit/comments/audit_p/',created_at_utc=datetime(2026,7,7,5,tzinfo=timezone.utc))
    store.upsert_run('audit_C','success','2026-07-06T23:00:00+00:00','2026-07-07T23:00:00+00:00'); store.upsert_thread(post)
    fake=SimpleNamespace(item_id='post:audit_p',sentiment_label='negative',sentiment_score=-0.8,topic='troubleshooting',severity='high',pain_points=['leakage'])
    with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic_dummy_not_a_secret'}),patch('reddit_voc.collector.analyze_batch_with_deepseek',return_value=[fake]):
        _reanalyze_run_with_deepseek(store,'audit_C',authorize_provider_call=True)
    with store.connect() as conn:
        row=conn.execute('SELECT analysis_version,provider_call,confidence FROM analysis_results WHERE run_id=?',('audit_C',)).fetchone()
        results['F08_analysis_provenance']=dict(row)
    # Reuse the repository fixture; no real project database or raw content is read.
    fixture=WebappPayloadTests('test_dashboard_reads_sqlite_and_detail_translation'); fixture.setUp()
    try:
        data=app.build_dashboard_payload('all')
        results['F01_api_fields']={k:k in data['posts'][0] for k in ['author_hash','selftext','raw_capture_id','comments','db_name']}
        private=app.OUTPUT_DIR/'private'/'audit-marker.txt'; private.parent.mkdir(); private.write_text('synthetic marker')
        results['F01_artifact_unlisted_file_readable']=app.resolve_artifact_path('private/audit-marker.txt')==private.resolve()
    finally: fixture.tearDown()
    # Compile original AST functions to avoid unrelated optional PIL import.
    tree=ast.parse((ROOT/'src/reddit_voc/daily_report.py').read_text())
    function_names={'_write_prevalidated_xlsx','_unicode_chunks','_normalize_media_url','_download_media_to_file','_make_media_filename'}
    import re,hashlib,mimetypes
    from urllib.parse import urlparse
    from urllib.request import Request
    from urllib.error import HTTPError,URLError
    scope=dict(Workbook=Workbook,Path=Path,re=re,hashlib=hashlib,mimetypes=mimetypes,urlparse=urlparse,Request=Request,HTTPError=HTTPError,URLError=URLError,DEFAULT_MEDIA_DIR='media')
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='PREVALIDATED_DETAIL_COLUMNS' for x in node.targets):
            scope['PREVALIDATED_DETAIL_COLUMNS']=ast.literal_eval(node.value)
    compile_tree=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in function_names],type_ignores=[])
    exec(compile(ast.fix_missing_locations(compile_tree),'daily_report.py [original AST subset]','exec'),scope)
    xlsx=base/'formula.xlsx'
    scope['_write_prevalidated_xlsx'](xlsx,rows=[{'标题原文':'=1+1'}],content_fields=[])
    wb=load_workbook(xlsx,data_only=False)
    col=scope['PREVALIDATED_DETAIL_COLUMNS'].index('标题原文')+1
    cell=wb['detail'].cell(row=2,column=col)
    results['F06_xlsx_formula']={'data_type':cell.data_type,'value':cell.value}; wb.close()
    observed={}
    class Response:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def getheader(self,*a): return 'image/png'
        def read(self,*a): observed['read_arguments']=list(a); return b'audit_image_placeholder'
    def fake_open(req,**kw): observed['url']=req.full_url; return Response()
    scope['urlopen']=fake_open
    scope['_download_media_to_file']('http://127.0.0.1/audit.png',output_dir=base,run_id='audit',post_id='audit',index=0)
    results['F07_media_request']=observed
Path('/tmp/reddit-voc-audit-20261014/reproductions.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps(results,ensure_ascii=False,indent=2))
