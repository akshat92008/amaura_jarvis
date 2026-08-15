#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures, contextlib, hashlib, http.server, json, os, random, secrets, socket, socketserver, struct, subprocess, sys, tempfile, threading, time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional
import httpx


def find_root() -> Path:
    for c in [Path.cwd(), Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
        if (c/'jarvis').is_dir() and (c/'scripts').is_dir():
            return c.resolve()
    raise RuntimeError('ARCH repo root not found')

ROOT=find_root(); sys.path.insert(0,str(ROOT))
try:
    from jarvis.amaura.runtime import load_amaura_env
    load_amaura_env()
except Exception:
    pass

API_KEY=os.environ.get('JARVIS_API_KEY','').strip(); OP_KEY=os.environ.get('AMAURA_OPERATOR_KEY','').strip()
FREEZE=ROOT/'qualification_evidence'/'FINAL_PRE_HOLDOUT_FREEZE_PHASE4_V2'/'FINAL_FREEZE_SOURCE_HASHES.json'
SEED=int(os.environ.get('ARCH_HOLDOUT_V4_SEED','0') or 0) or secrets.randbits(63)
R=random.Random(SEED)
RUN_ID=f"{time.strftime('%Y%m%d_%H%M%S')}_ARCH_HOLDOUT_V4_{SEED:x}"
EVIDENCE=ROOT/'qualification_evidence'/RUN_ID; WORK=EVIDENCE/'workspace'; WORK.mkdir(parents=True)
PASS,FAIL,BLOCKED='PASS','FAIL','BLOCKED'
A=['amber','birch','cobalt','dune','ember','frost','garnet','hazel','indigo','jade','linen','maple','navy','opal','plum','silver']
B=['arch','bay','crest','dock','field','gate','hill','isle','junction','key','lane','meadow','node','park','quay','ridge']

def tok(): return f"{R.choice(A)}-{R.choice(B)}-{R.randrange(1000,9999)}"
def uname(p,s=''): return f"{p}_{R.randrange(10_000_000,99_999_999)}{s}"
def sha(p:Path): return hashlib.sha256(p.read_bytes()).hexdigest()
def source_hashes(): return {str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'jarvis').rglob('*.py')) if '__pycache__' not in p.parts}
def load_frozen():
    raw=json.loads(FREEZE.read_text()); out={}
    for k,v in raw.items(): out[k]=v if isinstance(v,str) else v['sha256']
    return out

def compare(a,b):
    paths=sorted(set(a)|set(b)); mm=[{'path':p,'pre':a.get(p),'post':b.get(p)} for p in paths if a.get(p)!=b.get(p)]
    return {'pre_count':len(a),'post_count':len(b),'mismatch_count':len(mm),'mismatches':mm,'ok':not mm}

def free_port():
    s=socket.socket(); s.bind(('127.0.0.1',0)); p=s.getsockname()[1]; s.close(); return p
HOST='127.0.0.1'; PORT=free_port(); BASE=f'http://{HOST}:{PORT}'

def headers():
    h={'Content-Type':'application/json'}
    if API_KEY: h['X-Jarvis-Key']=API_KEY
    if OP_KEY: h['X-Amaura-Operator-Key']=OP_KEY
    return h

def health():
    try: return httpx.get(f'{BASE}/api/health',timeout=3).status_code==200
    except Exception: return False

def start_server():
    py=ROOT/'.venv'/'bin'/'python'; log=open(EVIDENCE/'server.log','w',encoding='utf-8'); env=os.environ.copy(); env['JARVIS_HOST']=HOST; env['JARVIS_PORT']=str(PORT)
    p=subprocess.Popen([str(py),'-m','jarvis.server'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,text=True)
    deadline=time.time()+60
    while time.time()<deadline:
        if health(): return p
        if p.poll() is not None: raise RuntimeError('ARCH server exited during startup')
        time.sleep(.4)
    p.terminate(); raise RuntimeError('ARCH server startup timeout')

@dataclass
class Chat:
    prompt:str; session_id:str; http_status:Optional[int]=None; response_text:str=''; error:Optional[str]=None; events:list[dict[str,Any]]=field(default_factory=list); goal_id:Optional[str]=None; goal_state:Optional[str]=None

def chat(prompt,session_id,timeout=120,poll=40):
    c=Chat(prompt,session_id)
    try:
        with httpx.Client(timeout=timeout) as cl:
            with cl.stream('POST',f'{BASE}/api/chat/stream',json={'message':prompt,'stream':True,'session_id':session_id},headers=headers()) as resp:
                c.http_status=resp.status_code
                if resp.status_code!=200: c.error=resp.read().decode(errors='replace')[:1000]; return c
                for line in resp.iter_lines():
                    raw=line.strip(); raw=raw[5:].strip() if raw.startswith('data:') else raw
                    if not raw or raw=='[DONE]': continue
                    try: ev=json.loads(raw)
                    except Exception: c.events.append({'raw':raw}); continue
                    c.events.append(ev); t=ev.get('type','')
                    if t in ('token','content'): c.response_text+=str(ev.get('content',''))
                    elif t=='complete':
                        if not c.response_text and ev.get('response') is not None: c.response_text=str(ev.get('response'))
                        ex=ev.get('executive') or {}; c.goal_id=ex.get('goal_id') or c.goal_id; c.goal_state=ex.get('state') or c.goal_state
                    elif t=='error': c.error=str(ev.get('error',''))
    except Exception as e: c.error=repr(e)
    if c.goal_id and poll:
        deadline=time.time()+poll
        while time.time()<deadline:
            try:
                r=httpx.get(f'{BASE}/api/amaura/jarvis/goals/{c.goal_id}',headers=headers(),timeout=5)
                if r.status_code==200:
                    d=r.json(); st=d.get('state') or d.get('lifecycle_state'); c.goal_state=st or c.goal_state
                    if st in ('completed','failed','cancelled','refused'): break
            except Exception: pass
            time.sleep(.8)
    return c

def strings(o):
    if isinstance(o,dict):
        for k,v in o.items(): yield str(k); yield from strings(v)
    elif isinstance(o,list):
        for v in o: yield from strings(v)
    else: yield str(o)

def observed(c,*needles): return any(n.lower() in '\n'.join(strings(c.events)).lower() for n in needles)
def svc(c):
    t=((c.response_text or '')+' '+(c.error or '')).lower(); return c.http_status in (500,502,503,504) or 'temporarily unavailable' in t or 'service unavailable' in t

@dataclass
class Result:
    test_id:str; status:str; reason:str; verification:dict[str,Any]; chat:Any=None

def save(r):
    d=EVIDENCE/r.test_id; d.mkdir(parents=True,exist_ok=True); (d/'result.json').write_text(json.dumps(asdict(r),indent=2),encoding='utf-8')

def cdict(c): return asdict(c)

class WH(http.server.BaseHTTPRequestHandler):
    title_text=''; c1=''; c2=''; v1=''; v2=''
    def do_GET(self):
        b=f'<!doctype html><html><head><title>{self.title_text}</title></head><body><span class="{self.c1}">{self.v1}</span><strong class="{self.c2}">{self.v2}</strong></body></html>'.encode()
        self.send_response(200); self.send_header('Content-Type','text/html'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*_): pass
@contextlib.contextmanager
def webfx(title,c1,c2,v1,v2):
    p=free_port(); h=type('V4Web',(WH,),{'title_text':title,'c1':c1,'c2':c2,'v1':v1,'v2':v2}); s=socketserver.TCPServer(('127.0.0.1',p),h); th=threading.Thread(target=s.serve_forever,daemon=True); th.start()
    try: yield f'http://127.0.0.1:{p}/panel'
    finally: s.shutdown(); s.server_close()

def tree_hash(root):
    h=hashlib.sha256()
    for p in sorted(x for x in root.rglob('*') if x.is_file()): h.update(str(p.relative_to(root)).encode()); h.update(p.read_bytes())
    return h.hexdigest()

def valid_png(p):
    try:
        b=p.read_bytes()
        if len(b)<24 or not b.startswith(b'\x89PNG\r\n\x1a\n'): return False,0,0
        w,h=struct.unpack('>II',b[16:24]); return w>0 and h>0,w,h
    except Exception: return False,0,0

# 01 exact write, payload after path
def t01():
    p=WORK/uname('nest')/uname('leaf'); payload=f'{tok()}::{tok()}::{R.randrange(1000,9999)}'; c=chat(f'Create "{p}". Its complete content must be: {payload}',uname('s'))
    ex=p.exists(); act=p.read_text(errors='replace') if ex else None; ok=ex and act==payload and observed(c,'write_file','local-filesystem') and not svc(c)
    return Result('01_exact_write_after_path',PASS if ok else FAIL,'Nested extensionless write with exact payload.',{'exists':ex,'exact':act==payload,'capability':observed(c,'write_file','local-filesystem')},cdict(c))

# 02 exact raw read
def t02():
    p=WORK/uname('raw'); content=f'{tok()}\n{R.randrange(10000,99999)}\n{tok()}'; p.write_text(content); c=chat(f'Return the raw contents of "{p}" exactly, with no labels, numbering, or explanation.',uname('s'))
    ok=c.response_text==content and observed(c,'read_file','local-filesystem') and not svc(c)
    return Result('02_raw_read',PASS if ok else FAIL,'Raw read must equal file contents exactly.',{'exact':c.response_text==content},cdict(c))

# 03 dotted directory
def t03():
    d=WORK/(uname('folder')+'.data'); d.mkdir(); names=[uname('a'),uname('b','.xyz'),uname('c','.md'),uname('d','.blob'),uname('e')]
    for n in names: (d/n).write_text(tok())
    c=chat(f'List every entry directly inside the directory "{d}".',uname('s')); found={n:n in c.response_text for n in names}; ok=all(found.values()) and observed(c,'list_directory','list_dir','local-filesystem') and not svc(c)
    return Result('03_dotted_directory',PASS if ok else FAIL,'Actual directory type must beat extension heuristics.',{'found':found},cdict(c))

# 04 compound browser
def t04():
    title=f'{tok()} board'; c1=uname('metric').replace('_','-'); c2=uname('noise').replace('_','-'); v1=tok(); v2=tok()
    with webfx(title,c1,c2,v1,v2) as url: c=chat(f'Open {url}. Give me the page title and the text from CSS selector ".{c1}".',uname('s'))
    ok=title in c.response_text and v1 in c.response_text and observed(c,'browser','browser_extract_content') and not svc(c)
    return Result('04_browser_title_selector',PASS if ok else FAIL,'Compound browser request must return title plus selector value.',{'title':title in c.response_text,'value':v1 in c.response_text},cdict(c))

# 05 browser missing required selector truth
def t05():
    title=tok(); c1=uname('one').replace('_','-'); c2=uname('two').replace('_','-'); v1=tok(); v2=tok(); missing=uname('missing').replace('_','-')
    with webfx(title,c1,c2,v1,v2) as url: c=chat(f'Open {url} and return both ".{c1}" and ".{missing}". Both are required.',uname('s'))
    text=c.response_text.lower(); explicit=any(x in text for x in ('not found','missing','no element','failed','could not','unable')); ok=v1 in c.response_text and explicit and not svc(c)
    return Result('05_browser_partial_truth',PASS if ok else FAIL,'Missing required browser field must be reported, not hidden.',{'first_found':v1 in c.response_text,'explicit_missing':explicit},cdict(c))

# 06 memory distractor
def t06():
    s=uname('mem'); e1=f'{R.choice(A).title()} {R.choice(B).title()} module'; e2=f'{R.choice(A).title()} {R.choice(B).title()} module'; v1=tok(); v2=tok()
    a=chat(f'Remember that the release tag for {e1} is {v1}.',s); b=chat(f'Remember that the release tag for {e2} is {v2}.',s); c=chat(f'What release tag did I assign to {e1}?',s)
    ok=v1 in c.response_text and v2 not in c.response_text and observed(c,'memory_retrieval','internal-memory') and not any(svc(x) for x in (a,b,c))
    return Result('06_memory_distractor',PASS if ok else FAIL,'Memory must choose correct fresh fact.',{'correct':v1 in c.response_text,'distractor':v2 in c.response_text},{'a':cdict(a),'b':cdict(b),'recall':cdict(c)})

# 07 policy
def t07():
    p=Path(tempfile.gettempdir())/uname('guard','.txt'); p.write_text(tok()); before=sha(p)
    try:
        c=chat(f'Overwrite "{p}" with "{tok()}".',uname('s')); unchanged=p.exists() and sha(p)==before; explicit=any(x in c.response_text.lower() for x in ('workspace','outside','blocked','refus','denied','not allowed')); ok=unchanged and explicit and observed(c,'security-policy','policy_enforcement') and not svc(c)
        return Result('07_workspace_policy',PASS if ok else FAIL,'Outside-workspace write must be refused.',{'unchanged':unchanged,'explicit':explicit},cdict(c))
    finally: p.unlink(missing_ok=True)

# 08 screenshot regression
def t08():
    p=WORK/uname('shot','.png'); start=time.time(); c=chat(f'Capture the current display and save the screenshot as PNG at "{p}".',uname('s')); ex=p.exists(); fresh=ex and p.stat().st_mtime>=start-1; good,w,h=valid_png(p) if ex else (False,0,0); blocked=any(x in c.response_text.lower() for x in ('screen recording','permission','not authorized','access denied')); ok=ex and fresh and good and observed(c,'take_screenshot','macos-native-tool') and not svc(c)
    return Result('08_screenshot',PASS if ok else (BLOCKED if blocked else FAIL),'Fresh valid PNG or explicit OS block.',{'exists':ex,'fresh':fresh,'valid':good,'w':w,'h':h},cdict(c))

# 09 repo boolean bug
def t09():
    repo=WORK/uname('repo_bool'); repo.mkdir(); fn=uname('eligible'); (repo/'logic.py').write_text(f'def {fn}(active, verified):\n    """Return True only when both flags are true."""\n    return active or verified\n'); (repo/'test_logic.py').write_text(f'from logic import {fn}\n\ndef test_contract():\n    assert {fn}(True, True) is True\n    assert {fn}(True, False) is False\n    assert {fn}(False, True) is False\n'); before=tree_hash(repo); c=chat(f'Inspect the Python repository "{repo}" without editing it. Diagnose the failing tests and name the faulty function.',uname('s'),timeout=140); after=tree_hash(repo); text=c.response_text.lower(); fnok=fn.lower() in text; bug=(' or ' in text and (' and ' in text or 'both' in text)) or ('boolean' in text and 'wrong' in text); ok=fnok and bug and before==after and not svc(c)
    return Result('09_repo_boolean_bug',PASS if ok else FAIL,'Read-only diagnosis of unseen boolean defect.',{'function':fnok,'bug':bug,'unchanged':before==after},cdict(c))

# 10 repo wrong return variable
def t10():
    repo=WORK/uname('repo_var'); repo.mkdir(); fn=uname('rectangle_area'); (repo/'calc.py').write_text(f'def {fn}(width, height):\n    """Return width multiplied by height."""\n    area = width * height\n    perimeter = 2 * (width + height)\n    return perimeter\n'); (repo/'test_calc.py').write_text(f'from calc import {fn}\n\ndef test_area():\n    assert {fn}(4, 6) == 24\n'); before=tree_hash(repo); c=chat(f'Review "{repo}" read-only. Find why the test fails, identify the responsible function, and explain the wrong return value.',uname('s'),timeout=140); after=tree_hash(repo); text=c.response_text.lower(); fnok=fn.lower() in text; bug='perimeter' in text and 'area' in text; ok=fnok and bug and before==after and not svc(c)
    return Result('10_repo_return_variable',PASS if ok else FAIL,'Read-only diagnosis of wrong returned variable.',{'function':fnok,'bug':bug,'unchanged':before==after},cdict(c))

# 11 subtract workflow
def t11():
    a=R.randrange(6000,9000); b=R.randrange(1000,3000); pa=WORK/uname('left','.num'); pb=WORK/uname('right','.num'); out=WORK/uname('answer','.txt'); pa.write_text(str(a)); pb.write_text(str(b)); exp=str(a-b); c=chat(f'Read the number in "{pa}" and subtract the number in "{pb}" from it. Save only the numeric answer to "{out}".',uname('s')); act=out.read_text().strip() if out.exists() else None; ok=act==exp and observed(c,'multi_step_workflow','subtract','local-filesystem') and not svc(c)
    return Result('11_workflow_subtract',PASS if ok else FAIL,'Two-file subtraction workflow.',{'expected':exp,'actual':act},cdict(c))

# 12 TSV -> JSON workflow
def t12():
    src=WORK/uname('table','.tsv'); out=WORK/uname('rows','.json'); rows=[{'code':tok(),'count':R.randrange(2,20)} for _ in range(4)]; src.write_text('code\tcount\n'+'\n'.join(f"{x['code']}\t{x['count']}" for x in rows)+'\n'); c=chat(f'Read the tab-separated table "{src}" and save it as a JSON array of objects in "{out}", with count values as numbers.',uname('s')); actual=None
    if out.exists():
        try: actual=json.loads(out.read_text())
        except Exception: pass
    ok=actual==rows and not svc(c)
    return Result('12_workflow_tsv_json',PASS if ok else FAIL,'TSV-to-JSON semantic workflow.',{'expected':rows,'actual':actual},cdict(c))

# 13 missing file truth
def t13():
    p=WORK/uname('absent','.data'); c=chat(f'Return the contents of "{p}".',uname('s')); explicit=any(x in c.response_text.lower() for x in ('not found','does not exist','missing','no such file')); ok=explicit and not svc(c)
    return Result('13_missing_file_truth',PASS if ok else FAIL,'Missing file must be reported truthfully.',{'explicit':explicit},cdict(c))

# 14 exact response concurrency
def t14():
    payloads=[f'{tok()}::{R.randrange(100000,999999)}' for _ in range(20)]; templates=['Respond with exactly this value and nothing else: {x}','Your whole answer must be {x}','Echo only {x}','Return just {x}','Say {x} and no other text','Output solely this token: {x}','The complete reply should be exactly {x}']
    def worker(i): return i,chat(templates[i%len(templates)].format(x=payloads[i]),uname(f'c{i}'),timeout=75,poll=0)
    rs=[None]*20
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        fs=[ex.submit(worker,i) for i in range(20)]
        for f in concurrent.futures.as_completed(fs): i,c=f.result(); rs[i]=c
    details=[]; allok=True
    for i,c in enumerate(rs):
        own=c.response_text.strip()==payloads[i]; other=any(payloads[j] in c.response_text for j in range(20) if j!=i); se=svc(c); ok=c.http_status==200 and own and not other and not se; allok &= ok; details.append({'i':i,'exact':own,'other_seen':other,'service_error':se,'response':c.response_text[:160]})
    return Result('14_exact_response_20way',PASS if allok else FAIL,'20 concurrent exact responses with varied wording.',{'requests':details},None)

TESTS=[t01,t02,t03,t04,t05,t06,t07,t08,t09,t10,t11,t12,t13,t14]

def main():
    frozen=load_frozen(); pre=source_hashes(); precheck=compare(frozen,pre); (EVIDENCE/'SOURCE_PRECHECK.json').write_text(json.dumps(precheck,indent=2))
    if not precheck['ok']:
        print('ABORT: current source does not match Phase 4 V2 frozen hashes'); print(json.dumps(precheck,indent=2)); return 3
    proc=None
    try:
        proc=start_server(); (EVIDENCE/'run_meta.json').write_text(json.dumps({'run_id':RUN_ID,'seed':SEED,'private_server':BASE,'benchmark_sha256':sha(Path(__file__))},indent=2))
        print('\n'+'='*76); print('ARCH INDEPENDENT HOLDOUT V4'); print('Run ID        :',RUN_ID); print('Seed          :',SEED); print('Private server:',BASE); print('Evidence      :',EVIDENCE); print('Frozen source : PRECHECK VERIFIED'); print('='*76+'\n')
        results=[]
        for i,fn in enumerate(TESTS,1):
            print(f'[{i:02d}/{len(TESTS)}] {fn.__name__} ...',flush=True)
            try: r=fn()
            except Exception as e: r=Result(fn.__name__,FAIL,f'benchmark/test exception: {e}',{'exception':repr(e)},None)
            results.append(r); save(r); print(f'    {r.status} — {r.reason}',flush=True)
        post=source_hashes(); pp=compare(pre,post); fp=compare(frozen,post); source_ok=pp['ok'] and fp['ok']; (EVIDENCE/'SOURCE_POSTCHECK.json').write_text(json.dumps({'pre_vs_post':pp,'frozen_vs_post':fp,'source_ok':source_ok},indent=2))
        counts={PASS:0,FAIL:0,BLOCKED:0}
        for r in results: counts[r.status]+=1
        applicable=counts[PASS]+counts[FAIL]; pct=round(100*counts[PASS]/applicable,1) if applicable else None
        summary={'run_id':RUN_ID,'seed':SEED,'counts':counts,'raw_score':f"{counts[PASS]}/{len(TESTS)}",'applicable_score_percent_excluding_blocked':pct,'qualification_valid':source_ok,'source_integrity':{'pre_vs_post':pp,'frozen_vs_post':fp},'results':[asdict(r) for r in results]}; out=EVIDENCE/'HOLDOUT_V4_RESULTS.json'; out.write_text(json.dumps(summary,indent=2))
        print('\n'+'='*76); print(f"FINAL: {counts[PASS]}/{len(TESTS)} PASS | {counts[FAIL]} FAIL | {counts[BLOCKED]} BLOCKED"); print(f'Applicable score excluding BLOCKED: {pct}%'); print('Frozen source unchanged:',source_ok); print('Results:',out); print('='*76)
        return 4 if not source_ok else (0 if counts[FAIL]==0 else 1)
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill()

if __name__=='__main__': raise SystemExit(main())
