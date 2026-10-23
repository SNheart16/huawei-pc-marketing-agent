'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const C=require('../ui/demo-contracts.js');

// Synthetic fixtures below verify browser boundaries only; they are not real product results.
function checked() {
  const task={task_id:'task-offline',revision:9,current_strategy_id:'s-offline',current_strategy_version:2};
  const strategy={strategy_id:'s-offline',strategy_version:2,confirmation_status:'confirmed'};
  const asset={task_id:task.task_id,strategy_id:strategy.strategy_id,quality_issues:[],fact_check:{a_result:{final_check:{valid:true,task_id:task.task_id,saved_task_revision:9,strategy_id:strategy.strategy_id,strategy_version:2,
    overall:{status:'partial',text_usable:true,completed:false},text_check:{status:'passed'},image_check:{status:'unknown'},usable_text:{plain_text:'离线测试文字'}}}}};
  return {task,strategy,asset};
}
test('real demo binds actual task and strategy versions; no synthetic increment',()=>{
  const {task,strategy}=checked();assert.deepEqual(C.binding(task,strategy),{task_id:'task-offline',expected_revision:9,strategy_id:'s-offline',strategy_version:2});
  assert.throws(()=>C.binding({task_id:'task-offline'}));
});
test('partial permits checked text while unknown images do not become approved',()=>{
  const {task,strategy,asset}=checked();assert.equal(C.textUsable(asset,task,strategy,false),true);
  assert.equal(asset.fact_check.a_result.final_check.image_check.status,'unknown');
  assert.equal(C.textUsable(asset,task,strategy,true),false);
});
test('copy rejects changed task revision, strategy, unconfirmed and failed text',()=>{
  const {task,strategy,asset}=checked();
  assert.equal(C.textUsable(asset,{...task,revision:10},strategy,false),false);
  assert.equal(C.textUsable(asset,{...task,current_strategy_version:3},strategy,false),false);
  assert.equal(C.textUsable(asset,task,{...strategy,confirmation_status:'pending'},false),false);
  asset.fact_check.a_result.final_check.text_check.status='blocked';assert.equal(C.textUsable(asset,task,strategy,false),false);
});
test('copy never trusts B publication label without canonical final audit',()=>{
  const {task,strategy,asset}=checked();delete asset.fact_check.a_result;asset.can_publish=true;asset.text_usable=true;
  assert.equal(C.textUsable(asset,task,strategy,false),false);
});
test('card answers retain server IDs and reject fabricated or excessive selections',()=>{
  const cards=[{question_id:'q-server',mode:'single',options:[{option_id:'o-server'}]}];
  assert.deepEqual(C.cardAnswers(cards,{'q-server':['o-server']}),[{question_id:'q-server',option_ids:['o-server']}]);
  assert.throws(()=>C.cardAnswers(cards,{'q-server':['made-up']}));
  assert.throws(()=>C.cardAnswers(cards,{'q-server':['o-server','o-server']}));
});
test('unknown image without safe local URL is not rendered as a fake or external image',()=>{
  assert.equal(C.safeMedia(null),null);assert.equal(C.safeMedia('javascript:alert(1)'),null);
  assert.equal(C.safeMedia('https://example.com/guess.png'),null);
  assert.equal(C.safeMedia('/api/content/media/img-'+ 'a'.repeat(32)+'.svg'),'/api/content/media/img-'+ 'a'.repeat(32)+'.svg');
});
function browser(response) {
  const nodes=new Map(), calls=[];
  const element=id=>{
    if(nodes.has(id))return nodes.get(id);
    const el={id,value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,dataset:{},options:[],handlers:{},
      classList:{toggle(){}},addEventListener(name,fn){this.handlers[name]=fn;},add(option){this.options.push(option);},prepend(){},click(){},querySelectorAll(){return [];}};
    nodes.set(id,el);return el;
  };
  const clearButtons=['product_query','audience','platform','goal','scene','constraints','scenario_inputs.time','scenario_inputs.store','scenario_inputs.usage'].map(value=>{
    const el=element('clear-'+value);el.dataset.clear=value;return el;
  });
  const document={getElementById:element,querySelectorAll(selector){return selector==='[data-clear]'?clearButtons:[];},createElement(){return element('created');}};
  const context=vm.createContext({window:{DemoContracts:C,Pregenerated:require('../ui/pregenerated.js'),confirm(){return true;}},document,console,
    fetch:async(url,options)=>{
      calls.push({url,payload:options?.body && JSON.parse(options.body)});
      const value=typeof response==='function'?await response(calls.length,url):response;
      return {ok:value.success,status:value.success?201:value.error?.code==='VERSION_CONFLICT'?409:502,json:async()=>value};
    },
    AbortController,setTimeout,clearTimeout,setInterval,clearInterval,Option:function(text,value){this.value=value;},crypto:{randomUUID(){return 'offline-id';}},navigator:{clipboard:{writeText:async()=>{}}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/demo-flow.js'),'utf8'),context);
  return {calls,element,edit(id,value){element(id).value=value;element(id).handlers.input();},async click(id){element(id).handlers.click();await new Promise(resolve=>setTimeout(resolve,15));}};
}
test('page never calls paid models or prototype fixtures on mount',()=>{
  const ui=browser({success:true,data:{}});assert.equal(ui.calls.length,0);assert.equal(ui.element('copy').disabled,true);
});
test('understand error shows safe error and never claims whole workflow complete',async()=>{
  const ui=browser({success:false,data:null,error:{code:'UPSTREAM_HTTP_ERROR',message:'模型服务未完成请求。'}});
  ui.element('idea').value='离线需求';await ui.click('understand');
  assert.equal(ui.calls[0].url,'/api/agent/understand');
  assert.match(ui.element('error').textContent,/UPSTREAM_HTTP_ERROR/);
  assert.match(ui.element('status').textContent,/没有使用模拟结果/);
  assert.equal(ui.element('copy').disabled,true);
});
test('understand uses actual response task and continue uses returned revision',async()=>{
  const task={task_id:'task-actual-response',revision:7,workflow_status:'collecting_requirements',question_cards:[],fact_records:[],constraints:[]};
  const ui=browser({success:true,data:{task,understanding:{summary:'离线摘要',questions:['补充受众？']}}});
  ui.element('idea').value='离线需求';await ui.click('understand');ui.element('idea').value='面向大学生';await ui.click('continue');
  assert.equal(ui.calls[1].payload.task_id,'task-actual-response');assert.equal(ui.calls[1].payload.expected_revision,7);
});

test('version conflict restores actual task from error.details without replaying old answers',async()=>{
  const task={task_id:'task-current',revision:7,workflow_status:'collecting_requirements',question_cards:[],fact_records:[],constraints:[]};
  const ui=browser(index=>index===2?{success:false,data:null,error:{code:'VERSION_CONFLICT',message:'任务版本已改变。',details:{task:{...task,revision:8},blocking_items:['请确认当前需求']}}}:{success:true,data:{task:index===1?task:{...task,revision:8}}});
  ui.element('idea').value='离线需求';await ui.click('understand');
  ui.element('idea').value='面向大学生';await ui.click('continue');
  assert.match(ui.element('error').textContent,/VERSION_CONFLICT/);assert.match(ui.element('error').textContent,/请确认当前需求/);
  assert.match(ui.element('task-meta').textContent,/revision 8/);assert.equal(ui.calls.length,2);
  await ui.click('continue');assert.equal(ui.calls[2].payload.expected_revision,8);
});

test('old revision response never replaces current task or displayed requirement summary',async()=>{
  const task={task_id:'task-current',revision:7,workflow_status:'collecting_requirements',question_cards:[],fact_records:[],constraints:[]};
  const ui=browser(index=>({success:true,data:{task:{...task,revision:index===1?7:6},understanding:{summary:index===1?'当前摘要':'旧摘要'}}}));
  ui.element('idea').value='离线需求';await ui.click('understand');
  ui.element('idea').value='本轮补充';await ui.click('continue');
  assert.match(ui.element('error').textContent,/旧任务或旧版本/);
  assert.match(ui.element('task-meta').textContent,/revision 7/);assert.equal(ui.element('summary').textContent,'当前摘要');
});

test('explicit clear and manual edits are submitted; no strategy is implicitly confirmed',async()=>{
  const task={task_id:'task-current',revision:7,workflow_status:'ready_for_strategy',question_cards:[],fact_records:[],constraints:[],scene:'旧场景',audience:'旧受众',scenario_inputs:{time:{text:'旧时间'},store:{location_text:'旧门店'}}};
  const ui=browser({success:true,data:{task}});ui.element('idea').value='离线需求';await ui.click('understand');
  ui.edit('audience','新受众');await ui.click('clear-scene');await ui.click('clear-scenario_inputs.store');
  assert.equal(ui.element('audience').value,'新受众');assert.equal(ui.element('scene').value,'');assert.equal(ui.element('store').value,'');
  assert.equal(ui.element('confirm-strategy').disabled,true);assert.equal(ui.element('generate-content').disabled,true);
  await ui.click('continue');assert.equal(ui.calls[1].payload.updates.audience,'新受众');
  assert.deepEqual(ui.calls[1].payload.clear_fields,['scene','scenario_inputs.store']);assert.equal(ui.calls[1].payload.scenario_inputs,undefined);
  assert.equal(ui.calls.some(call=>call.url==='/api/strategy/confirm'),false);
});
