'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

function setup() {
  const handlers={}, notices=[];
  let draft={taskId:'t',audience:'学生',tone:'自然',extra:'不写价格',outputs:{},activePlatform:'小红书'};
  const context=vm.createContext({window:{},document:{addEventListener(k,f){handlers[k]=f;},querySelector(){return {textContent:''};}},console,AbortController,setTimeout,clearTimeout,
    fetch:async()=>({ok:false,json:async()=>({success:false,error:{message:'服务失败'}})})});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/content-workbench.js'),'utf8'),context);
  const api=context.window.ContentB;
  api.bind({getDraft:()=>draft,record(){},render(){},toast(v){notices.push(v);}});
  return {api,draft,handlers,notices};
}

test('prototype adapter sends full strategy and never upgrades catalog or manual ticks to evidence',()=>{
  const {api,draft}=setup();draft.facts={specs:{confirmed:true,note:'用户写的99小时'}};
  const brief={strategyId:'s',strategy:{name:'选购清单',contentTheme:'开学选购',coreIdea:'按常用软件确认需求',copy:'从软件版本开始',cta:'',contentFormat:'清单',platforms:['小红书']}};
  const req=api.fromPrototype(draft,brief,'小红书','HUAWEI MateBook Pro S');
  assert.equal(req.task_id,'t');assert.equal(req.strategy.strategy_id,'s');assert.equal(req.strategy.core_message,'从软件版本开始');
  assert.equal(req.strategy.cta,'');assert.equal(req.product_context.facts.length,0);assert.equal(req.copy_mode,'assembly');
});

test('service errors are surfaced rather than converted to simulated success',async()=>{
  const {api}=setup();await assert.rejects(()=>api.api('/generate','POST',{}),/服务失败/);
});

test('editing invalidates publication status and preserves picture identity and task',()=>{
  const {draft,handlers}=setup();draft.outputs['小红书']={bAsset:{copy:{title:'旧标题',body:'旧文案',cta:'',hashtags:[]},images:[{image_id:'original'}],can_publish:true,fact_check_status:'passed'}};
  handlers.input({target:{dataset:{bCopy:'body'},value:'手写正文'}});
  const o=draft.outputs['小红书'];assert.equal(o.body,'手写正文');assert.equal(o.bAsset.images[0].image_id,'original');
  assert.equal(o.bAsset.can_publish,false);assert.equal(o.bAsset.fact_check_status,'pending');assert.equal(o.bDirty,true);assert.equal(draft.taskId,'t');
});

test('B renderer escapes model content and labels generation/checking truthfully',()=>{
  const {api}=setup();const asset={request:{strategy:{topic:'<script>x</script>'},product_context:{model:'PC',facts:[]},limits:{title:20}},copy:{title:'<img onerror=x>',body:'safe',cta:'',hashtags:[]},platform:'小红书',images:[],generation_mode:'assembly',version:1,fact_check_status:'pending',fact_check:{claims:[]},publish_blockers:['待确认']};
  const html=api.render({bAsset:asset},{});
  assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img onerror=x>'));assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('未调用文案模型'));assert.ok(html.includes('暂不可直接发布'));
});

test('AI image is distinguished from unchanged source photo',()=>{
  const {api}=setup();const asset={request:{strategy:{topic:'学习任务'},product_context:{model:'PC',facts:[]},limits:{title:20}},copy:{title:'标题',body:'正文',cta:'',hashtags:[]},platform:'小红书',images:[{image_id:'i',url:'/api/content/media/i.png',is_generated:true,generation_model:'test-model',source_ref:'https://example.com',role:'封面'}],generation_mode:'llm',version:1,fact_check_status:'pending',fact_check:{claims:[]},publish_blockers:['待确认']};
  const html=api.render({bAsset:asset},{});
  assert.ok(html.includes('含实时 AI 生图'));assert.ok(html.includes('参考原图不代表外观完全一致'));
  assert.ok(!html.includes('产品素材未重绘'));
});

test('information cards are not labelled as product posters or photo layouts',()=>{
  const {api}=setup();const asset={request:{strategy:{topic:'电脑选购'},product_context:{model:'HUAWEI MateBook X Pro',facts:[]},limits:{title:20}},copy:{title:'标题',body:'正文',cta:'',hashtags:[]},platform:'小红书',images:[{image_id:'i',url:'/api/content/media/i.svg',source_type:'editorial_card',is_generated:false,role:'主题封面'}],generation_mode:'llm',version:1,fact_check_status:'pending',fact_check:{claims:[]},publish_blockers:['待确认']};
  const html=api.render({bAsset:asset},{});
  assert.ok(html.includes('信息卡（缺少产品原图）'));
  assert.ok(html.includes('选择配图 / 更换配图'));
  assert.ok(!html.includes('生成 AI 海报'));
  assert.ok(!html.includes('真实素材排版'));
});

test('pre-generated artwork is displayed unchanged and remains visually unknown',()=>{
  const {api}=setup();const asset={request:{strategy:{topic:'学习任务'},product_context:{model:'PC',facts:[]},limits:{title:20}},copy:{title:'标题',body:'正文',cta:'',hashtags:[]},platform:'小红书',images:[{image_id:'fixed-01',url:'/assets/pregenerated/xiaohongshu/fixed-01.jpg',source_type:'pre_generated',visual_check_status:'unknown',contains_text:true,role:'封面'}],generation_mode:'llm',version:1,fact_check_status:'pending',fact_check:{claims:[]},publish_blockers:['图片待确认']};
  const html=api.render({bAsset:asset},{});
  assert.ok(html.includes('预生成素材 · 未调用生图 API'));assert.ok(html.includes('视觉 unknown'));
  assert.ok(html.includes('不重复叠加标题或文案'));assert.ok(html.includes('图片内文字不可编辑'));
  assert.ok(!html.includes('AI 创意海报'));assert.ok(!html.includes('<canvas'));
});
