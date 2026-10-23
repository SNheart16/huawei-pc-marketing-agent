'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const P=require('../ui/pregenerated.js');
const C=require('../ui/demo-contracts.js');

test('three platform columns reuse backend values and aliases, with no poster column',()=>{
  assert.deepEqual(P.platforms,['公众号','微信朋友圈','小红书']);
  assert.equal(P.platform('门店朋友圈'),'微信朋友圈');assert.equal(P.platform('微信公众号'),'公众号');
  assert.equal(P.platform('门店海报'),null);
});
test('platform selection/order keys are isolated and retained when switching',()=>{
  const drafts={};const model='HUAWEI MateBook X Pro';
  drafts[P.key(model,'公众号')]=['article-1','article-2'];
  drafts[P.key(model,'门店朋友圈')]=['moment-1','moment-2'];
  drafts[P.key(model,'小红书')]=['xhs-1'];
  drafts[P.key(model,'公众号')]=P.move(drafts[P.key(model,'公众号')],'article-2',-1);
  assert.deepEqual(drafts[P.key(model,'公众号')],['article-2','article-1']);
  assert.deepEqual(drafts[P.key(model,'微信朋友圈')],['moment-1','moment-2']);
  assert.equal(drafts[P.key('MateBook 14','公众号')],undefined);
});
test('select/remove and order keep only actual chosen IDs, enforce four limit',()=>{
  const original=['a','b'];assert.deepEqual(P.select(original,'a'),['b']);
  assert.deepEqual(P.select(original,'c'),['a','b','c']);assert.deepEqual(original,['a','b']);
  assert.deepEqual(P.move(original,'a',-1),original);assert.deepEqual(P.move(original,'a',1),['b','a']);
  assert.throws(()=>P.select(['a','b','c','d'],'e'),/最多/);
});
test('fixed media URLs use real static root and reject traversal and external credentials',()=>{
  const url='/assets/pregenerated/wechat-article/article-01.png';assert.equal(P.safeUrl(url),url);assert.equal(C.safeMedia(url),url);
  for(const invalid of ['/ui/assets/pregenerated/moments/x.png','/assets/pregenerated/moments/../secret.png','https://example.com/x.png','file:///D:/x.png'])assert.equal(P.safeUrl(invalid),null);
});
test('topic recommendations rank only supplied matching catalog and never synthesize duplicates',()=>{
  const items=[{material_id:'a',theme:'轻办公'},{material_id:'b',theme:'开学季'},{material_id:'c',theme:'创作'}];
  assert.deepEqual(P.recommendations(items,'开学季'),['b','a','c']);assert.deepEqual(P.recommendations([],'开学季'),[]);
});
test('fixed-image entrypoints retain real copy generation and contain no AI image mode',()=>{
  const demo=fs.readFileSync(path.join(__dirname,'../ui/demo-flow.js'),'utf8');
  const b=fs.readFileSync(path.join(__dirname,'../ui/content-workbench.js'),'utf8');
  assert.ok(demo.includes("image_mode:'pregenerated'"));assert.ok(b.includes("scope:'copy'"));
  assert.ok(!demo.includes("image_mode:'ai_reference'"));assert.ok(!b.includes('ai_reference'));
  assert.ok(demo.includes('selected_image_ids:ids'));assert.ok(b.includes('selected_image_ids:order'));
  assert.ok(demo.includes('图片加载失败'));assert.ok(b.includes('图片加载失败'));
});
