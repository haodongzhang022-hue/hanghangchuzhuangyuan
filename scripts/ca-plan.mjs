// 通用变更感知测试选择内核（Generic CA planner）v4
// 输入: --all / --base=SHA / --src=... / --testglob=... / --map=... / --skip=... / --cachedir=... / --no-cache
// 输出(stdout): 执行计划 JSON [[testFile,"run"|"skip",key],...]；日志走 stderr。
import fs from 'fs';
import path from 'path';
import cp from 'child_process';
import crypto from 'crypto';

const repo = process.cwd();
const args = process.argv.slice(2);
const get=(k,d='')=>{const a=args.find(x=>x.startsWith('--'+k+'='));return a?a.slice(k.length+3):d;};
const FLAG=k=>args.includes('--'+k);

const FORCE_ALL=FLAG('all'), NO_CACHE=FLAG('no-cache');
const BASE_SHA=get('base');
const SRC_GLOB=get('src','src/ lib/ packages/ core/ engine/ app/');
const TEST_GLOB=get('testglob','');
const MAP_FILE=get('map','');
const SKIP_EXTRA=get('skip','docs/,README.md,.md,poc/,examples/,.github/,CHANGELOG.md');
const CA_TOOL=get('tool','scripts/ .cnb/ ci/ .github/ Makefile package.json package-lock.json pnpm-lock.yaml yarn-lock Dockerfile .dockerignore .gitlab-ci.yml').split(/\s+/).filter(Boolean);
const CACHE_DIR=get('cachedir',path.join(repo,'.testcache'));

function rel(p){ return path.relative(repo,p).split(path.sep).join('/'); }
function walkRel(dir, out=[]){
  let st; try{ st=fs.statSync(dir); }catch(e){ return out; }
  if(st.isDirectory()){ for(const n of fs.readdirSync(dir)) walkRel(path.join(dir,n),out); }
  else if(st.isFile()){ const r=rel(dir); if(!/node_modules/.test(r)&&!r.startsWith('.git')) out.push(r); }
  return out;
}
function git(...a){ try{ return cp.execFileSync('git',a,{cwd:repo,encoding:'utf8'}).trim(); }catch(e){ return ''; } }

// ---- 测试识别 ----
function isTestFile(r){
  const b=r.split('/').pop();
  return /^test_.*\.(py|sh|bash|mjs|cjs|js|ts)$/.test(b)
      || /_test\.(py|mjs|cjs|js|ts)$/.test(b)
      || /\.(test|spec)\.(mjs|cjs|js|ts)$/.test(b);
}
function findTests(){
  const all=walkRel('.');
  const found=new Set();
  // 优先常见测试目录
  for(const d of ['tests','test','spec','__tests__','local-agent/tests','test_data']){
    for(const f of walkRel(d)) if(isTestFile(f)) found.add(f);
  }
  // 全仓兜底（去掉 node_modules/.git，已由 walkRel 排除）
  for(const f of all) if(isTestFile(f)) found.add(f);
  // 若给了 TEST_GLOB，用其精筛
  if(TEST_GLOB){
    const pats=TEST_GLOB.split(/\s+/).filter(Boolean);
    const reArr=pats.map(p=>new RegExp('^'+p.replace(/[.+^${}()|[\]\\]/g,'\\$&').replace(/\*\*/g,'__GS__').replace(/\*/g,'[^/]*').replace(/__GS__/g,'(?:.*)?')+'$'));
    const out=[...found].filter(f=>reArr.some(re=>re.test(f)));
    return out.sort();
  }
  return [...found].sort();
}
// ---- 依赖引用解析 ----
const SRC_ROOTS=SRC_GLOB.split(/\s+/).filter(Boolean);
function parseRefs(text){
  const s=new Set(); let m;
  const py=/(?:^\s*from\s+)([A-Za-z_][\w.]*)(?=\s+import|\s*$)|(?:^\s*import\s+)([A-Za-z_][\w.]+)/gm;
  while((m=py.exec(text))) s.add(m[1]||m[2]);
  const es=/(?:from\s+['"])(\.[^'"]*)|(?:import\s*\(\s*['"])(\.[^'"]*)|(?:require\s*\(\s*['"])(\.[^'"]*)/g;
  while((m=es.exec(text))) s.add(m[1]||m[2]||m[3]);
  return [...s];
}
function resolveFile(mod){
  const cand=[]; const exts=['.py','.js','.mjs','.cjs','.ts','.mts','.jsx','.tsx','.json',''];
  if(mod.startsWith('.')){
    const rp=mod.replace(/^\.\.?\/?/,'');
    for(const d of ['tests','test','spec','src','lib','local-agent','packages']){
      for(const e of exts) cand.push(path.join(d,rp+e));
    }
  } else {
    const rp=mod.replace(/\./g,'/');
    for(const r of SRC_ROOTS) for(const e of exts) cand.push(path.join(r,rp+e));
  }
  const ex=(c)=>{ try{ if(fs.statSync(c).isFile()) return rel(c); }catch(e){} return null; };
  for(const c of cand){ const r=ex(c); if(r) return r; }
  for(const c of cand){ for(const e of exts){ const r=ex(c+'/index'+e); if(r) return r; } }
  return null;
}
function coveredFiles(tf){
  const text=fs.readFileSync(path.join(repo,tf),'utf8');
  const files=new Set();
  for(const mod of parseRefs(text)){ const rf=resolveFile(mod); if(rf) files.add(rf); }
  return [...files];
}
// ---- 依赖索引 ----
const testFiles=findTests();
if(!testFiles.length){
  console.error('__NO_TESTS_FOUND__; use --testglob / CA_TEST_GLOB to locate tests.');
  process.exit(2);
}
const src2tests=new Map(), test2src=new Map();
for(const tf of testFiles){
  const cfs=coveredFiles(tf); test2src.set(tf,cfs);
  for(const sf of cfs){ if(!src2tests.has(sf)) src2tests.set(sf,[]); if(src2tests.get(sf).indexOf(tf)<0) src2tests.get(sf).push(tf); }
}
const staticMap=[];
if(MAP_FILE){ try{ for(const line of fs.readFileSync(path.join(repo,MAP_FILE),'utf8').split('\n')){ const t=line.split('#')[0].trim(); if(!t)continue; const i=t.indexOf('|'); if(i<0)continue; staticMap.push([t.slice(0,i).trim(),t.slice(i+1).split(',').map(s=>s.trim()).filter(Boolean)]); } }catch(e){} }

// ---- 变更收集（repo 相对路径）----
let changed=[];
if(!FORCE_ALL){
  if(BASE_SHA) changed=git('diff','--name-only',BASE_SHA+'...HEAD').split('\n').filter(Boolean);
  changed=changed.concat(git('diff','--name-only').split('\n').filter(Boolean));
  changed=[...new Set(changed.map(rel))];
}
const skipPrefixes=SKIP_EXTRA.split(',').map(s=>s.trim()).filter(Boolean);
const isNonTrigger=f=>skipPrefixes.some(p=>f.includes(p));

const selected=new Set();
if(FORCE_ALL || changed.length===0){ for(const tf of testFiles) selected.add(tf); }
else{
  const triggers=changed.filter(f=>f&&!isNonTrigger(f));
  if(!triggers.length){ process.stdout.write('[]'); console.error('纯文档/非触发变更 → 无需跑行为测试'); process.exit(0); }
  for(const f of triggers){
    if(testFiles.indexOf(f)>=0){ selected.add(f); continue; }
    let hit=false;
    if(src2tests.has(f)){ for(const tf of src2tests.get(f)) selected.add(tf); hit=true; }
    for(const [pat,tlist] of staticMap){ if(f.includes(pat)){ for(const tf of tlist) selected.add(tf); hit=true; } }
    if(!hit){
      // 基建/工具/CI 配置文件变更：若无对应测试则视为“非业务变更”，不兜底全量
      const isTool = CA_TOOL.some(p=> f.startsWith(p) || f===p || f.includes('/'+p));
      const isCfgTop = /^\.?[\w.-]+\.(yml|yaml|json|toml|ini|cfg|lock)$/.test(f.split('/').pop());
      if(!(isTool || isCfgTop)){ for(const tf of testFiles) selected.add(tf); }
    }
  }
}
// ---- 指纹缓存 ----
const sha1=s=>crypto.createHash('sha1').update(s).digest('hex');
const blobHash=fp=>{ try{return sha1(fs.readFileSync(path.join(repo,fp)));}catch(e){return 'missing';} };
function computeKey(tf){ const p=['TF:'+blobHash(tf)]; for(const sf of (test2src.get(tf)||[])) p.push('|'+sf+':'+blobHash(sf)); return sha1(p.join('')); }
fs.mkdirSync(CACHE_DIR,{recursive:true});
const cf=path.join(CACHE_DIR,'results.json');
let cache={}; try{ cache=JSON.parse(fs.readFileSync(cf,'utf8')); }catch(e){}
const plan=[];
for(const tf of [...selected].sort()){
  const key=computeKey(tf), prev=cache[tf];
  const canSkip=!NO_CACHE && prev && prev.key===key && prev.result==='pass';
  plan.push([tf,canSkip?'skip':'run',key]);
}
const runs=plan.filter(p=>p[1]==='run').length, skips=plan.filter(p=>p[1]==='skip').length;
console.error(`测试文件 ${testFiles.length}；选中受影响 ${selected.size}；本批实跑 ${runs} / 缓存跳过 ${skips}`);
process.stdout.write(JSON.stringify(plan));

// ---- 缓存回写入口：--writecache --cachedir=... --files="t1 t2 ..." ----
if (FLAG('writecache')){
  const files=(get('files','')||'').trim().split(/\s+/).filter(Boolean);
  const cdir=get('cachedir',path.join(repo,'.testcache'));
  fs.mkdirSync(cdir,{recursive:true});
  const cfp=path.join(cdir,'results.json');
  let cache={}; try{ cache=JSON.parse(fs.readFileSync(cfp,'utf8')); }catch(e){}
  const sha1=s=>crypto.createHash('sha1').update(s).digest('hex');
  const blobHash=fp=>{ try{return sha1(fs.readFileSync(path.join(repo,fp)));}catch(e){return 'missing';} };
  for(const tf of files){
    const text=(()=>{try{return fs.readFileSync(path.join(repo,tf),'utf8');}catch(e){return '';}})();
    const refs=new Set(); let m;
    const py=/(?:^\s*from\s+)([A-Za-z_][\w.]*)(?=\s+import|\s*$)|(?:^\s*import\s+)([A-Za-z_][\w.]+)/gm;
    while((m=py.exec(text))) refs.add(m[1]||m[2]);
    const es=/(?:from\s+['"])(\.[^'"]*)|(?:import\s*\(\s*['"])(\.[^'"]*)|(?:require\s*\(\s*['"])(\.[^'"]*)/g;
    while((m=es.exec(text))) refs.add(m[1]||m[2]||m[3]);
    const sr=SRC_GLOB.split(/\s+/).filter(Boolean);
    const cfs=[];
    for(const mod of refs){
      const rp=mod.startsWith('.')?mod.replace(/^\.\.?\/?/,''):mod.replace(/\./g,'/');
      const dirs=mod.startsWith('.')?['tests','test','spec','src','lib','local-agent','packages']:sr;
      let hit=null;
      for(const d of dirs){ for(const e of ['.py','.js','.mjs','.cjs','.ts','.json','']){ const c=path.join(d,rp+e); try{ if(fs.statSync(c).isFile()){hit=c;break;} }catch(e2){} } if(hit)break; }
      if(hit) cfs.push(rel(hit));
    }
    const key=['TF:'+blobHash(tf)].concat(cfs.map(s=>'|'+s+':'+blobHash(s))).join('');
    cache[tf]={key:sha1(key),result:'pass'};
  }
  fs.mkdirSync(cdir,{recursive:true});
  fs.writeFileSync(cfp,JSON.stringify(cache,null,1));
  process.stdout.write('cache written '+files.length+' entries\n');
  process.exit(0);
}
