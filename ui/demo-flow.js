/* Real, in-process A → B demo. No prototype data, model calls on mount, or persisted evidence. */
(() => {
  'use strict';
  const C = window.DemoContracts;
  const P = window.Pregenerated;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = {task:null, strategy:null, handoff:null, asset:null, factCheck:null, selectedFacts:new Set(),
    dirty:new Set(), clears:new Set(), contentDirty:false, busy:false, generation:0, job:null, pending:false,
    materialPlatform:'公众号',materialDrafts:{},materialError:'',materialProduct:''};
  const fields = ['product_query','platform','audience','goal','scene','constraints','time','store','landmarks','usage'];
  const scenarioPaths = {time:'scenario_inputs.time',store:'scenario_inputs.store',landmarks:'scenario_inputs.store.nearby_landmarks',usage:'scenario_inputs.usage'};
  const names = {collecting_requirements:'仍需补充需求',ready_for_strategy:'需求充分 · 产品事实尚需核查',researching:'正在读取产品资料',awaiting_user_confirmation:'等待人工确认策略',strategy_confirmed:'策略已确认',failed:'当前步骤未完成'};
  const join = values => (values || []).join('\n');
  let timer = null;
  function log(path, outcome) {
    const li = document.createElement('li');
    li.textContent = `${new Date().toLocaleTimeString()} · ${path} · ${outcome}`;
    $('events').prepend(li);
  }
  function notice(text, warning=false) { $('status').textContent=text; $('status').classList.toggle('warning',warning); }
  function showError(text) { $('error').textContent=text; $('error').hidden=!text; }
  function setTask(task) {
    if (!task) return;
    if (state.task && task.task_id !== state.task.task_id) return;
    if (state.task && task.revision < state.task.revision) return;
    if (state.task && task.product_query !== state.task.product_query) {
      state.factCheck=null;state.selectedFacts.clear();
      state.materialDrafts={};state.materialError='产品已变化，请重新读取适用素材。';
    }
    state.task = task;
    if (state.strategy && !C.currentStrategy(task,state.strategy)) {
      state.strategy=null; state.handoff=null; state.asset=null; state.job=null; state.contentDirty=false;
    }
  }
  function materialKey(value=state.materialPlatform) { return P.key(state.task?.product_query || formValue('product_query'),value); }
  function materialDraft(value=state.materialPlatform) {
    return state.materialDrafts[materialKey(value)] ||= {items:[],ids:[],loaded:false,copy:null};
  }
  function currentMaterialPlatform() { return P.platform(state.asset?.platform || state.task?.platform); }
  function rememberAsset() {
    if(!state.asset)return;
    const draft=materialDraft(state.asset.platform);
    draft.ids=(state.asset.images || []).filter(i=>i.source_type==='pre_generated').map(i=>i.image_id);
    draft.copy={title:$('copy-title').value,body:$('copy-body').value,cta:$('copy-cta').value,hashtags:$('copy-tags').value};
  }
  async function loadMaterials() {
    const model=state.task?.product_query || formValue('product_query');
    if(!model)throw new Error('请先填写产品型号；不会推荐其他产品的图片。');
    const draft=materialDraft();
    draft.items=await request('/api/content/catalog?model='+encodeURIComponent(model)+'&platform='+encodeURIComponent(state.materialPlatform),null,'GET');
    draft.loaded=true;state.materialError='';
    const allowed=new Set(draft.items.map(i=>i.material_id || i.catalog_id));
    draft.ids=draft.ids.filter(id=>allowed.has(id));
    if(!draft.initialized && !draft.ids.length)draft.ids=P.recommendations(draft.items,state.strategy?.topic || state.task?.scene);
    draft.initialized=true;
    renderMaterials();
  }
  async function saveTextEdits() {
    if(!state.contentDirty || !state.asset)return;
    const updated=await request('/api/content/'+state.asset.asset_id,{expected_version:state.asset.version,copy:{title:formValue('copy-title'),body:formValue('copy-body'),cta:formValue('copy-cta'),hashtags:formValue('copy-tags').split(/[；;\n]+/).map(s=>s.trim()).filter(Boolean)}},'PATCH');
    state.asset=updated;state.contentDirty=false;rememberAsset();
  }
  async function applyMaterialSelection(ids) {
    const draft=materialDraft();
    if(state.asset && currentMaterialPlatform()===state.materialPlatform) {
      await saveTextEdits();
      const updated=await request('/api/content/'+state.asset.asset_id,{expected_version:state.asset.version,selected_image_ids:ids},'PATCH');
      applyAsset(updated);
      notice('当前平台配图已更新；文案保留。旧最终核查已失效，请重新核查。',true);
    }
    draft.ids=ids;
    renderMaterials();
  }
  function renderMaterials() {
    if(!P)return;
    const draft=materialDraft(), active=currentMaterialPlatform(), same=!state.asset || active===state.materialPlatform;
    $('material-tabs').innerHTML=P.platforms.map(value=>`<button type="button" data-material-platform="${esc(value)}" aria-pressed="${value===state.materialPlatform}" ${state.busy?'disabled':''}>${value==='微信朋友圈'?'朋友圈':esc(value)}</button>`).join('');
    $('material-context').textContent=`当前栏目：${state.materialPlatform} · 产品：${state.task?.product_query || formValue('product_query') || '尚未指定'}${!same?'。此栏目选择仅保留为草稿，当前成稿属于 '+active+'。':''}`;
    $('material-status').textContent=state.materialError || (!draft.loaded?'点击“选择配图”读取素材。':draft.items.length===0?'待补充素材：没有匹配当前产品与平台的素材。':`已有 ${draft.items.length} 张 · 已选择 ${draft.ids.length} 张（最多 4 张）${draft.items.length<2?' · 素材不足，请补充':''}`);
    const ordered=[...draft.ids.map(id=>draft.items.find(i=>(i.material_id || i.catalog_id)===id)).filter(Boolean),...draft.items.filter(i=>!draft.ids.includes(i.material_id || i.catalog_id))];
    $('material-library').innerHTML=ordered.map(item=>{
      const id=item.material_id || item.catalog_id,index=draft.ids.indexOf(id),url=P.safeUrl(item.url),selected=index>=0;
      return `<article class="material ${selected?'selected':''}">${url?`<img src="${esc(url)}" alt="${esc(item.theme || '预生成素材')}" data-material-image="${esc(id)}">`:'<p class="error">素材地址不可用</p>'}<strong>${selected?index+1+' · ':''}${esc(item.theme || id)}</strong><p>${esc(item.product_model || item.model)} · 预生成素材</p><p class="muted">${item.contains_text?'图片内文字不可编辑，不叠加文案。':''}视觉核查 unknown · 授权待确认</p><p class="muted">${esc(item.source_note || item.source_ref || '')}</p><div class="actions"><button data-material-action="toggle" data-id="${esc(id)}" ${state.busy?'disabled':''}>${selected?'取消选择':'选择此图'}</button>${selected?`<button data-material-action="up" data-id="${esc(id)}" ${index===0 || state.busy?'disabled':''}>上移</button><button data-material-action="down" data-id="${esc(id)}" ${index===draft.ids.length-1 || state.busy?'disabled':''}>下移</button><button data-material-action="download" data-id="${esc(id)}" ${!url || state.busy?'disabled':''}>下载原图</button>`:''}</div></article>`;
    }).join('');
    $('material-tabs').querySelectorAll('[data-material-platform]').forEach(button=>button.addEventListener('click',()=>{rememberAsset();state.materialPlatform=button.dataset.materialPlatform;state.materialError='';renderMaterials();renderAsset();if(!materialDraft().loaded && (state.task?.product_query || formValue('product_query')))run('正在读取该平台预生成素材',loadMaterials);}));
    $('material-library').querySelectorAll('[data-material-image]').forEach(img=>img.addEventListener('error',()=>{img.hidden=true;const warning=document.createElement('p');warning.className='error';warning.textContent='图片加载失败，请重新读取或补充该素材。';img.after(warning);}));
    $('material-library').querySelectorAll('[data-material-action]').forEach(button=>button.addEventListener('click',()=>run('正在更新预生成素材',async()=>{
      const id=button.dataset.id,action=button.dataset.materialAction;
      if(action==='download') {
        const item=draft.items.find(i=>(i.material_id || i.catalog_id)===id),url=P.safeUrl(item?.url);
        if(!url)throw new Error('素材地址不可用。');
        const response=await fetch(url);if(!response.ok)throw new Error('图片无法读取，未下载。');
        const blob=await response.blob();if(!blob.type.startsWith('image/'))throw new Error('素材不是可用图片，未下载。');
        download(blob,url.split('/').pop());return;
      }
      await applyMaterialSelection(action==='toggle'?P.select(draft.ids,id):P.move(draft.ids,id,action==='up'?-1:1));
    })));
  }
  async function request(path, payload, method='POST', generation=state.generation) {
    const ctrl=new AbortController();
    // A strategy can contain several bounded model stages; a UI wait does not cancel server work.
    const timeout=setTimeout(()=>ctrl.abort(), 1800000);
    let response, value;
    try {
      response=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:method==='GET'?undefined:JSON.stringify(payload),signal:ctrl.signal});
      value=await response.json();
    } catch(e) {
      state.pending=true;
      log(path,e.name==='AbortError'?'页面等待超时 · 服务端可能仍在处理':'无法读取接口响应');
      throw new Error(e.name==='AbortError'?'页面等待超时；服务端可能仍在处理。不要重复提交，请读取最新任务或成果任务后再操作。':'接口连接或响应解析失败；请确认服务仍运行。不要自动重复生成，请先读取最新任务。');
    } finally {clearTimeout(timeout);}
    if (generation!==state.generation) throw new Error('忽略旧会话的异步返回。');
    const returnedTask=value.data?.task || value.error?.details?.task || value.error?.task;
    if (returnedTask && state.task && (returnedTask.task_id!==state.task.task_id || returnedTask.revision<state.task.revision)) {
      throw new Error('忽略旧任务或旧版本的异步返回；当前页面状态已保留。');
    }
    setTask(returnedTask);
    log(path,`${response.status} · ${value.success?'接口已处理':value.error?.code || 'ERROR'}`);
    if (!response.ok || !value.success) {
      if ([409,401].includes(response.status)) state.handoff=null;
      const details = value.data?.blocking_items || value.data?.assessment?.blocking_items || value.error?.details?.blocking_items || [];
      const suffix=details.length?'\n阻断项：'+details.map(item=>typeof item==='string'?item:item.claim || item.reason || item.field_path).filter(Boolean).join('；'):'';
      const code=value.error?.code || 'REQUEST_FAILED';
      const recovery=response.status===409?'\n请读取最新任务；不要自动重放旧卡片或旧版本。':response.status===401?'\n凭证验证失败；暂停模型操作，修正服务进程环境后重启。':'';
      throw new Error(`${code}：${value.error?.message || '请求未完成。'}${suffix}${recovery}`);
    }
    state.pending=false;
    return value.data;
  }
  async function run(label, action) {
    if (state.busy) return;
    state.busy=true; showError('');
    const started=Date.now();
    notice(label+'，请勿重复点击。');
    timer=setInterval(()=>notice(`${label} · 已等待 ${Math.floor((Date.now()-started)/1000)} 秒。模型耗时不会被展示为生成完成。`),1000);
    render();
    try {await action();}
    catch(e) {showError(e.message || '操作未完成，当前输入保留。');notice('当前步骤未完成；没有使用模拟结果。',true);}
    finally {clearInterval(timer);state.busy=false;render();}
  }
  function formValue(id) { return $(id).value.trim(); }
  function scenarioInput(onlyDirty=false) {
    const result={};
    if ((!onlyDirty || state.dirty.has('time')) && !state.clears.has('scenario_inputs.time') && formValue('time')) result.time={text:formValue('time')};
    if ((!onlyDirty || state.dirty.has('usage')) && !state.clears.has('scenario_inputs.usage') && formValue('usage')) result.usage={text:formValue('usage')};
    const store={};
    if (!state.clears.has('scenario_inputs.store')) {
      if ((!onlyDirty || state.dirty.has('store')) && formValue('store')) store.location_text=formValue('store');
      if ((!onlyDirty || state.dirty.has('landmarks')) && formValue('landmarks')) store.nearby_landmarks=formValue('landmarks').split(/[；;\n]+/).map(s=>s.trim()).filter(Boolean);
    }
    if (Object.keys(store).length) result.store=store;
    return result;
  }
  function selectedCards() {
    const selected={};
    document.querySelectorAll('#cards input:checked').forEach(input=>(selected[input.dataset.question]??=[]).push(input.value));
    return C.cardAnswers(state.task?.question_cards || [],selected);
  }
  function fillTask() {
    const task=state.task;
    if (!task) return;
    const values={...task,constraints:join(task.constraints),time:task.scenario_inputs?.time?.text || '',
      store:task.scenario_inputs?.store?.location_text || '',landmarks:(task.scenario_inputs?.store?.nearby_landmarks || []).join('；'),usage:task.scenario_inputs?.usage?.text || ''};
    // Never overwrite a user edit merely because an unrelated async response arrived.
    fields.forEach(id=>{if(!state.dirty.has(id)) {
      if (id==='platform' && values[id] && !Array.from($(id).options).some(o=>o.value===values[id])) $(id).add(new Option(values[id],values[id]));
      $(id).value=values[id] || '';
    }});
  }
  function renderCards() {
    const selected={};
    document.querySelectorAll('#cards input:checked').forEach(input=>(selected[input.dataset.question]??=[]).push(input.value));
    $('cards').innerHTML=(state.task?.question_cards || []).map(card=>`<fieldset><legend>${esc(card.prompt)}</legend><p class="muted">服务端卡片 · ${card.mode==='multiple'?'可多选':'单选'} · 版本 ${esc(card.issued_revision)}</p>${card.options.map(option=>`<label class="card-option"><input type="${card.mode==='multiple'?'checkbox':'radio'}" name="${esc(card.question_id)}" data-question="${esc(card.question_id)}" value="${esc(option.option_id)}" ${selected[card.question_id]?.includes(option.option_id)?'checked':''} ${state.busy?'disabled':''}>${esc(option.label)}</label>`).join('')}${card.allow_free_text?'<p class="muted">也可以在上方填写自己的想法，连同本轮提交。</p>':''}</fieldset>`).join('');
  }
  function checkItems(results) {
    return (results || []).map(entry=>{const item=entry.check || entry;return `<div class="check-item ${item.status==='supported'?'passed':item.status==='not_applicable'?'':'blocked'}"><strong>${esc(item.status)}</strong> · ${entry.field_path?esc(entry.field_path)+' · ':''}${esc(item.claim)}<p>${esc(item.reason)}</p><p class="ref">${esc((item.source_refs || []).join('；'))}</p>${item.suggested_action?`<p class="muted">处理建议：${esc(item.suggested_action)}</p>`:''}</div>`;}).join('');
  }
  function renderFacts() {
    const facts=state.task?.fact_records || [];
    $('facts').innerHTML=facts.map(f=>`<div class="fact"><label><input type="checkbox" class="fact-select" data-fact="${esc(f.fact_id)}" ${state.selectedFacts.has(f.fact_id)?'checked':''} ${state.busy?'disabled':''}><span>${esc(f.claim)} <span class="badge">${esc(f.status)}</span></span></label><details><summary>原文与实际来源</summary><p>${esc(f.evidence_text)}</p><p class="ref">${esc(f.source_ref)} · ${esc(f.source_type)} · 有效期 ${esc(f.valid_until || '未提供')}</p></details></div>`).join('');
    const supported=facts.filter(f=>f.status==='supported').length;
    $('facts-status').textContent=facts.length?`${facts.length} 条候选 · ${supported} 条可用`:'待检索';
    if (state.factCheck) $('fact-results').innerHTML=`<p>核查计数：${esc(JSON.stringify(state.factCheck.counts || {}))}</p>${checkItems(state.factCheck.results)}${(state.factCheck.warnings || []).map(w=>`<p class="muted">${esc(w)}</p>`).join('')}`;
  }
  function renderStrategy() {
    const s=state.strategy;
    $('strategy-status').textContent=s?(s.confirmation_status==='confirmed'?'已人工确认':'请阅读并确认'):'待生成';
    if (!s) { $('strategy').innerHTML='';$('strategy-check').innerHTML='';$('handoff-json').textContent='尚未取得'; return; }
    const items=[['任务摘要',s.task_summary],['主题',s.topic],['受众及依据',`${s.audience?.description || ''}\n${s.audience?.basis || ''}`],['需求推断',s.audience_need],['核心表达',s.core_message],['内容角度',s.content_angle],['形式',s.content_format],['CTA',s.cta || '不设置'],['引用事实',(s.fact_references || []).join('；')],['推断',join(s.assumptions)],['待确认偏好',join(s.pending_confirmations)],['风险与来源限制',join(s.risk_notes)]];
    $('strategy').innerHTML=`<dl>${items.map(([label,value])=>`<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`).join('')}</dl><h3>顾客将看到什么</h3><ol class="strategy-list">${(s.content_outline || []).map(section=>`<li><strong>${esc(section.section)}</strong>：${esc(section.purpose)}<p class="ref">${esc((section.fact_references || []).join('；'))}</p></li>`).join('')}</ol>`;
    $('handoff-json').textContent=state.handoff?JSON.stringify(state.handoff,null,2):'确认策略后，由服务端返回同一任务的真实交接对象。';
  }
  function renderAsset() {
    const asset=state.asset;
    $('content-editor').hidden=!asset;
    if (!asset) {
      $('content-status').textContent=state.job?'处理中':'待生成';
      ['copy','download-text','download-package','save-check'].forEach(id=>{$(id).disabled=true;});
      return;
    }
    const check=C.finalResult(asset);
    const usable=C.textUsable(asset,state.task,state.strategy,state.contentDirty || state.dirty.size>0);
    $('content-status').textContent=state.contentDirty?'手工编辑 · 待重新核查':check?.overall?.status || asset.fact_check_status || '待核查';
    $('copy').disabled=state.busy || !usable;
    $('download-text').disabled=state.busy || !usable;
    $('download-package').disabled=state.busy || !usable || Boolean(P && state.materialPlatform!==P.platform(asset.platform));
    $('save-check').disabled=state.busy || state.dirty.size>0 || !C.currentStrategy(state.task,state.strategy);
    $('edit-warning').textContent=state.contentDirty?'文案已手工修改。旧核查已在页面撤下，复制和下载禁用；请重新核查。':'手工编辑不会被核查覆盖。文字通过后可复制；图片仍为待确认，审核包不是可直接发布成果。';
    $('visuals').innerHTML=(asset.images || []).map(image=>{
      const url=C.safeMedia(image.url);
      return `<div class="visual">${url?`<img src="${esc(url)}" alt="预生成素材，视觉内容待确认" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><p class="error" hidden>图片加载失败，请重新选择可用素材。</p>`:'<p>无可用图片 URL · 待确认</p>'}<p><strong>预生成素材 · 图片待确认 · unknown</strong></p><p class="muted">${esc(image.name || image.image_id)}</p><p class="ref">${esc(image.source_ref || image.source || '')}</p><p class="muted">原图直接展示，不叠加文案。不代表型号外观、图片内文字或授权已经通过。</p></div>`;
    }).join('') || '<p class="muted">无图片：缺项，不能视为图片核验通过。</p>';
    $('final-result').innerHTML=check?`<div class="notice ${check.overall?.text_usable?'warning':'error'}"><strong>整体 ${esc(check.overall?.status)} · 文字 ${esc(check.text_check?.status)} · 图片 ${esc(check.image_check?.status)}</strong><p>可用文字：${check.overall?.text_usable?'是':'否'}；整套完成：${check.overall?.completed?'是':'否'}；可直接发布：${check.overall?.ready_to_publish?'是':'否'}</p></div>${checkItems(check.text_check?.results)}${[...(check.warnings || []),...(asset.publish_blockers || [])].map(w=>`<p class="muted">${esc(w)}</p>`).join('')}`:`<p class="notice warning">最终核查尚未成功完成：${esc(asset.fact_check?.reason || '请查看具体错误并在确认当前版本后重试核查。')}。复制已禁用。</p>`;
  }
  function render() {
    const t=state.task;
    $('task-meta').textContent=t?`${t.task_id}\nrevision ${t.revision}`:'尚未创建任务';
    $('workflow').textContent=t?names[t.workflow_status] || t.workflow_status:'从需求开始';
    $('requirements-status').textContent=state.dirty.size?'有尚未提交的修改':t?(names[t.workflow_status] || t.workflow_status):'待输入';
    $('task-snapshot').textContent=t?JSON.stringify({task_id:t.task_id,revision:t.revision,product_query:t.product_query,audience:t.audience,platform:t.platform,goal:t.goal,scene:t.scene,constraints:t.constraints,field_status:t.field_status,scenario_inputs:t.scenario_inputs,excluded_scenes:t.excluded_scenes},null,2):'无任务';
    fillTask();renderCards();renderFacts();renderStrategy();
    document.querySelectorAll('input,textarea,select,button').forEach(el=>{el.disabled=state.busy;});
    $('understand').disabled=state.busy || Boolean(t) || state.pending;
    $('continue').disabled=state.busy || !t || state.pending;
    $('refresh').disabled=state.busy || !t;
    const clean=state.dirty.size===0 && !state.pending;
    $('research').disabled=state.busy || !t?.product_query || !clean;
    $('check-facts').disabled=state.busy || !state.selectedFacts.size || !clean;
    $('generate-strategy').disabled=state.busy || !t?.fact_records?.some(f=>f.status==='supported') || !clean;
    $('confirm-strategy').disabled=state.busy || !C.currentStrategy(t,state.strategy) || state.strategy?.confirmation_status!=='pending' || !clean;
    $('handoff').disabled=state.busy || !C.currentStrategy(t,state.strategy) || state.strategy?.confirmation_status!=='confirmed' || !clean;
    $('generate-content').disabled=state.busy || !state.handoff || !clean || Boolean(state.job && !['completed','failed'].includes(state.job.status));
    $('resume-job').hidden=!state.job;
    $('resume-job').disabled=state.busy || !state.job;
    renderAsset();
    renderMaterials();
  }
  function setSummary(data) {
    const understanding=data.understanding || data.interpretation;
    if (!understanding) return;
    $('summary').textContent=[understanding.summary,...(understanding.questions || []),...(data.missing_information?.length?['仍需补充：'+data.missing_information.join('；')]:[])].filter(Boolean).join('\n');
  }
  async function applyUnderstanding(data) {
    state.dirty.clear();state.clears.clear();state.handoff=null;
    $('idea').value='';setSummary(data);render();
    notice(data.task.workflow_status==='ready_for_strategy'?'需求已充分；请只读检索并核查产品事实。':'已理解当前想法。请选择服务端卡片或补充一个关键信息。');
  }
  $('understand').addEventListener('click',()=>run('正在真实理解推广想法',async()=>{
    if (!formValue('idea')) throw new Error('请先描述本次推广想法。');
    const payload={source:'direct',user_input:formValue('idea')};
    fields.filter(id=>!['time','store','landmarks','usage'].includes(id)).forEach(id=>{if(formValue(id))payload[id]=id==='constraints'?formValue(id).split('\n').filter(Boolean):formValue(id);});
    const scenarios=scenarioInput();if(Object.keys(scenarios).length)payload.scenario_inputs=scenarios;
    await applyUnderstanding(await request('/api/agent/understand',payload));
  }));
  $('continue').addEventListener('click',()=>run('正在理解本轮补充与修改',async()=>{
    const payload={...C.binding(state.task),user_input:formValue('idea'),updates:{},clear_fields:[...state.clears]};
    state.dirty.forEach(id=>{if(!scenarioPaths[id] && !state.clears.has(id))payload.updates[id]=id==='constraints'?formValue(id).split('\n').filter(Boolean):formValue(id);});
    const scenarios=scenarioInput(true);if(Object.keys(scenarios).length)payload.scenario_inputs=scenarios;
    const answers=selectedCards();if(answers.length)payload.card_answers=answers;
    if(!payload.user_input && !Object.keys(payload.updates).length && !payload.clear_fields.length && !answers.length && !payload.scenario_inputs)throw new Error('请补充文字、修改需求或选择一张卡片。');
    await applyUnderstanding(await request('/api/agent/continue',payload));
  }));
  fields.forEach(id=>$(id).addEventListener('input',()=>{
    state.dirty.add(id);state.clears.delete(scenarioPaths[id] || id);
    if(id==='landmarks')state.clears.delete('scenario_inputs.store');
    state.handoff=null;render();
  }));
  document.querySelectorAll('[data-clear]').forEach(button=>button.addEventListener('click',()=>{
    const path=button.dataset.clear;state.clears.add(path);
    const ids=path==='scenario_inputs.store'?['store','landmarks']:fields.filter(id=>(scenarioPaths[id] || id)===path);
    ids.forEach(id=>{$(id).value='';state.dirty.add(id);});
    state.handoff=null;render();
  }));
  $('refresh').addEventListener('click',()=>run('正在读取当前服务任务',async()=>{
    const data=await request('/api/demo/tasks/'+encodeURIComponent(state.task.task_id),null,'GET');
    setTask(data.task || data);state.pending=false;
    notice('已读取服务端最新任务。旧卡片答案不会自动重放；尚未提交的手工输入保留。');
  }));
  $('new-task').addEventListener('click',()=>{
    if(state.busy)return;
    if(state.task && !window.confirm('新建会话不会删除服务端原任务，但页面将切换到新需求。是否继续？'))return;
    state.generation++;Object.assign(state,{task:null,strategy:null,handoff:null,asset:null,factCheck:null,job:null,pending:false,contentDirty:false,materialDrafts:{},materialError:''});state.dirty.clear();state.clears.clear();state.selectedFacts.clear();
    fields.forEach(id=>$(id).value='');$('idea').value='';$('summary').textContent='';$('source').textContent='尚未检索知识来源。';$('fact-results').innerHTML='';$('job-status').textContent='';showError('');notice('新会话尚未调用模型。');render();
  });
  $('research').addEventListener('click',()=>run('正在只读检索当前精确产品',async()=>{
    const data=await request('/api/agent/research',C.binding(state.task));
    state.factCheck=null;state.selectedFacts=new Set((state.task.fact_records || []).slice(0,2).map(f=>f.fact_id));
    const source=data.research?.knowledge_source || {};
    $('source').textContent=`来源 ${source.mode || '未知'} · live=${String(source.live)} · ${source.name || ''}。${(data.research?.warnings || []).join('；')}`;
    notice(`检索得到 ${state.task.fact_records.length} 条候选事实。仅选择与本次目标相关的事实继续核查。`);
  }));
  $('facts').addEventListener('change',event=>{
    if(!event.target.dataset.fact)return;
    event.target.checked?state.selectedFacts.add(event.target.dataset.fact):state.selectedFacts.delete(event.target.dataset.fact);render();
  });
  $('check-facts').addEventListener('click',()=>run('正在核查选中的真实候选事实',async()=>{
    const claims=state.task.fact_records.filter(f=>state.selectedFacts.has(f.fact_id)).map(f=>({claim:f.claim,fact_references:[f.fact_id]}));
    if(!claims.length)throw new Error('请至少选择一条实际候选事实。');
    const data=await request('/api/facts/check',{...C.binding(state.task),claims});state.factCheck=data.fact_check;
    notice(`接口已处理；supported=${state.factCheck?.counts?.supported || 0}。只允许当前有效白名单事实进入策略。`);
  }));
  $('generate-strategy').addEventListener('click',()=>run('正在生成真实策略并逐项核查',async()=>{
    const data=await request('/api/strategy/generate',C.binding(state.task));state.strategy=data.strategy;state.handoff=null;state.asset=null;
    $('strategy-check').innerHTML=`<h3>策略逐项核查</h3>${checkItems(data.fact_check?.results)}`;
    notice('真实策略已生成且完成必要核查。请阅读内容，再由你点击确认；尚未生成最终图文。');
  }));
  $('confirm-strategy').addEventListener('click',()=>run('正在提交你的明确策略确认',async()=>{
    const data=await request('/api/strategy/confirm',C.binding(state.task,state.strategy));state.strategy=data.strategy;
    notice('当前策略已由服务端确认。请取得真实 handoff 后进入 B 图文工作台。');
  }));
  $('handoff').addEventListener('click',()=>run('正在取得当前已确认策略的交接对象',async()=>{
    const data=await request('/api/strategy/handoff',C.binding(state.task,state.strategy));state.handoff=data.handoff;
    notice('已取得同一任务的真实 handoff；产品事实、条件和来源将交给 B，不使用演示目录。');
  }));
  function applyAsset(asset) {
    const audit=C.finalResult(asset);
    if(!C.currentStrategy(state.task,state.strategy) || asset.task_id!==state.task?.task_id || asset.strategy_id!==state.strategy?.strategy_id || (audit && audit.strategy_version!==state.strategy.strategy_version))throw new Error('成果属于旧任务或旧策略，没有覆盖当前页面。');
    setTask(asset.fact_check?.a_result?.task);
    state.asset=asset;state.contentDirty=false;
    $('copy-title').value=asset.copy.title || '';$('copy-body').value=asset.copy.body || '';$('copy-cta').value=asset.copy.cta || '';$('copy-tags').value=(asset.copy.hashtags || []).join('；');
    rememberAsset();
    const check=C.finalResult(asset);
    notice(check?.overall?.text_usable?'实际成稿文字通过，图片待确认。可复制已核查文字或下载审核包；不能称整套图文已核验通过。':`实际成果已生成，但最终核查 ${check?.overall?.status || asset.fact_check_status || '尚未完成'}。请查看逐项结论，修正文案后重新核查。`,!check?.overall?.text_usable);
  }
  async function pollJob() {
    const taskId=state.task.task_id,strategyId=state.strategy.strategy_id,strategyVersion=state.strategy.strategy_version,generation=state.generation,started=Date.now();
    while (state.job && !['completed','failed'].includes(state.job.status)) {
      if(generation!==state.generation || taskId!==state.task?.task_id || strategyId!==state.strategy?.strategy_id || strategyVersion!==state.strategy?.strategy_version)throw new Error('旧任务的成果回包已忽略。');
      $('job-status').textContent=`${state.job.status} · 已等待 ${Math.floor((Date.now()-started)/1000)} 秒 · ${state.job.job_id}`;
      if(Date.now()-started>1800000)throw new Error('成果任务仍可能运行，请读取同一成果任务，不要重新生成。');
      await new Promise(resolve=>setTimeout(resolve,1300));
      state.job=await request('/api/content/jobs/'+state.job.job_id,null,'GET',generation);
    }
    if(state.job.status==='failed')throw new Error(`${state.job.error?.code || 'CONTENT_FAILED'}：${state.job.error?.message || '图文任务失败，未使用模拟结果。'}`);
    applyAsset(await request('/api/content/'+state.job.asset_id,null,'GET',generation));
    $('job-status').textContent=`成果任务完成 · ${state.job.job_id} · ${state.asset.asset_id} v${state.asset.version}`;
  }
  $('generate-content').addEventListener('click',()=>run('正在从真实 handoff 生成图文并执行 A 最终核查',async()=>{
    state.materialPlatform=P.platform(state.task.platform) || '公众号';
    const desired=materialDraft().loaded?[...materialDraft().ids]:null;
    state.job=await request('/api/content/from-handoff',{...C.binding(state.task,state.strategy),copy_mode:$('copy-mode').value,image_mode:'pregenerated',image_count:3,idempotency_key:crypto.randomUUID()});
    await pollJob();
    await loadMaterials();
    if(desired && JSON.stringify(desired)!==JSON.stringify(state.asset.images.map(i=>i.image_id)))await applyMaterialSelection(desired);
  }));
  $('resume-job').addEventListener('click',()=>run('正在读取同一个成果任务',pollJob));
  ['copy-title','copy-body','copy-cta','copy-tags'].forEach(id=>$(id).addEventListener('input',()=>{state.contentDirty=true;rememberAsset();renderAsset();}));
  $('load-materials').addEventListener('click',()=>run('正在读取预生成素材（不调用模型）',loadMaterials));
  $('save-check').addEventListener('click',()=>run('正在保存手工编辑并重新执行最终核查',async()=>{
    if(state.contentDirty) {
      const updated=await request('/api/content/'+state.asset.asset_id,{expected_version:state.asset.version,copy:{title:formValue('copy-title'),body:formValue('copy-body'),cta:formValue('copy-cta'),hashtags:formValue('copy-tags').split(/[；;\n]+/).map(s=>s.trim()).filter(Boolean)}},'PATCH');
      // An unsuccessful check must not erase the saved manual text.
      state.asset=updated;state.contentDirty=false;
    }
    applyAsset(await request('/api/content/validate',{asset_id:state.asset.asset_id,expected_version:state.asset.version}));
  }));
  function usableText() {
    if(!C.textUsable(state.asset,state.task,state.strategy,state.contentDirty || state.dirty.size>0))throw new Error('当前文字尚未通过有效最终核查，或已经修改。');
    return C.finalResult(state.asset).usable_text.plain_text;
  }
  $('copy').addEventListener('click',async()=>{
    try {await navigator.clipboard.writeText(usableText());notice('已复制当前最终核查通过的 plain_text。图片仍待确认。');}
    catch(e){showError(e.message || '浏览器未允许复制，请使用下载文字。');}
  });
  function download(blob,name) {const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  $('download-text').addEventListener('click',()=>{try{download(new Blob([usableText()],{type:'text/plain;charset=utf-8'}),'已核查文字-图片待确认.txt');}catch(e){showError(e.message);}});
  $('download-package').addEventListener('click',()=>run('正在下载审核包',async()=>{
    if(state.materialPlatform!==P.platform(state.asset?.platform))throw new Error('当前素材栏目与成稿平台不同，请切回当前成稿平台后导出审核包。');
    usableText();const response=await fetch('/api/content/'+state.asset.asset_id+'/export');if(!response.ok)throw new Error('审核包下载失败，原成果保留。');
    download(await response.blob(),'图文审核包-图片待确认.zip');notice('审核包已下载。图片未知和来源限制随包保留，不代表可直接发布。');
  }));
  render();
})();
