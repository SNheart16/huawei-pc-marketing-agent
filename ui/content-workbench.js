/* Member B's adapter. A's guidance/strategy code stays untouched. */
(() => {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const P=window.Pregenerated;
  let host, busy = false, examples = [], catalog = [], capabilities = {}, lastError = '';
  const stages = {pending:'等待处理', generating_copy:'正在生成文案', generating_images:'正在读取预生成素材', checking:'正在提交最终核查', completed:'生成流程完成', failed:'处理失败'};
  const current = () => host.getDraft().outputs[host.getDraft().activePlatform];
  const asset = () => current()?.bAsset;
  const btn = (label, action, cls='mc-secondary', extra='') => `<button type="button" class="${cls}" data-action="b-${action}" ${busy ? 'disabled' : ''} ${extra}>${label}</button>`;
  async function api(path, method='GET', payload) {
    const ctrl = new AbortController(), timer = setTimeout(() => ctrl.abort(), 65000);
    try {
      const r = await fetch('/api/content' + path, {method, headers: {'Content-Type':'application/json'}, body: payload ? JSON.stringify(payload) : undefined, signal:ctrl.signal});
      const v = await r.json();
      if (!r.ok || !v.success) throw new Error(v.error?.message || '成果服务未完成请求。');
      return v.data;
    } finally {clearTimeout(timer);}
  }
  function apply(a, d=host.getDraft()) {
    lastError='';
    const previous = d.outputs[a.platform];
    const activeIndex = Math.max(0, previous?.bAsset?.images.findIndex(i=>i.image_id===previous.activeImageId) ?? 0);
    const activeId = a.images.some(i=>i.image_id===previous?.activeImageId) ? previous.activeImageId : a.images[Math.min(activeIndex,a.images.length-1)]?.image_id;
    d.outputs[a.platform] = {title:a.copy.title, body:a.copy.body, cta:a.copy.cta, asset_id:a.asset_id, bAsset:a,
      strategy:previous?.strategy || d.outputContext?.strategy || d.strategyContext?.strategy || {}, activeImageId:activeId};
    d.activePlatform = a.platform;
    if (host.getDraft() === d) {host.record(); host.render();}
  }
  async function poll(job, d) {
    const started = Date.now();
    while (!['completed','failed'].includes(job.status)) {
      const status = document.getElementById('b-job-status');
      const seconds=Math.floor((Date.now()-started)/1000);
      const progress=stages[job.status]+(job.status==='generating_images'?` · 已等待 ${seconds} 秒`:'');
      if (status) status.textContent = progress;
      host.toast(progress);
      await new Promise(resolve => setTimeout(resolve, 1000));
      job = await api('/jobs/' + job.job_id);
      if (Date.now() - started > 900000) throw new Error(`任务仍在服务端运行。任务号 ${job.job_id}，请稍后从接口读取，勿重复提交。`);
    }
    if (job.status === 'failed') throw new Error(job.error?.message || '生成失败，原稿保留。');
    const a = await api('/' + job.asset_id);
    if (d !== host.getDraft()) {host.toast('原任务已生成，未覆盖你当前正在编辑的任务。'); return a;}
    apply(a,d);
    host.navigate('results');
    host.toast(a.errors?.length?'部分图片未完成，已有文案和图片已保留。':'图文已生成，可继续编辑或保存。');
    return a;
  }
  function fromPrototype(d, brief, platform, productName) {
    const s = brief.strategy;
    // Prototype catalog text and manual ticks never become verified product evidence.
    return {task_id:d.taskId, confirmed:true, platform, copy_mode:capabilities.llm_configured?'llm':'assembly', image_count:1,
      strategy:{strategy_id:brief.strategyId, topic:s.contentTheme || s.name, audience:s.confirmedAudience || d.audience || '希望了解相关使用需求的读者',
        audience_need:s.audience_need || s.audienceNeed || s.coreIdea, core_message:s.copy || s.coreIdea,
        content_outline:[], content_angle:s.content_angle || s.contentFormat || '', content_format:s.contentFormat || '', cta:s.cta || '',
        tone:d.tone || '', constraints:d.extra || '', avoid:[], assumptions:['来自现有原型的规则策略，非联网检索结果'],
        pending_confirmations:['产品资料与实际受众需求尚需核实'], risk_notes:[]},
      product_context:{model:productName || '', facts:[]}, art_direction:'editorial'};
  }
  async function generate(d, brief, productName) {
    if (busy) throw new Error('正在生成，请等待。');
    const visual={image_mode:'pregenerated',image_count:3,model:productName};
    if(!visual) {host.render(); return;}
    if(d!==host.getDraft()) throw new Error('任务已切换，请重新确认当前任务。');
    busy=true;
    try {
      for (const platform of (brief.strategy.platforms?.length ? brief.strategy.platforms : ['通用草稿'])) {
        const request = fromPrototype(d,brief,platform,productName);
        Object.assign(request,visual); request.product_context.model=visual.model; delete request.model;
        request.idempotency_key=crypto.randomUUID();
        await poll(await api('/generate','POST',request),d);
      }
    } finally {busy=false; if (d===host.getDraft()) host.render();}
  }
  async function flush() {
    const o = current();
    if (!o?.bDirty) return;
    const a = o.bAsset;
    const updated = await api('/'+a.asset_id,'PATCH',{expected_version:a.version,copy:a.copy});
    apply(updated);
  }
  async function guarded(fn) {
    if (busy) return;
    busy=true; lastError='';
    host.render();
    try {await fn();} catch(e) {lastError=e.message || '操作未完成，当前编辑已保留。'; host.toast(lastError);}
    finally {busy=false; host.render();}
  }
  function exportBlob(value,name,type='application/json') {
    const url=URL.createObjectURL(new Blob([value],{type})), link=document.createElement('a');
    link.href=url; link.download=name; link.click(); setTimeout(()=>URL.revokeObjectURL(url),5000);
  }
  async function download(path,name,image=false) {
    const response=await fetch(path);
    if(!response.ok) throw new Error('文件不可用，未导出。');
    const blob=await response.blob();if(image && !blob.type.startsWith('image/'))throw new Error('图片内容不可用，未下载。');
    const url=URL.createObjectURL(blob), link=document.createElement('a');
    link.href=url; link.download=name; link.click(); setTimeout(()=>URL.revokeObjectURL(url),5000);
  }
  function render(o,d) {
    const a=o.bAsset, s=a.request.strategy;
    const image=a.images.find(i=>i.image_id===o.activeImageId) || a.images[0];
    const unchanged=!o.bDirty;
    const generated=image?.is_generated === true;
    const pregenerated=image?.source_type==='pre_generated';
    const hasProduct=image && ['official_asset_composite','user_asset_composite'].includes(image.source_type);
    const source=pregenerated?'团队提供的预生成素材 · 视觉 unknown':generated ? 'AI 参考原图生成 · 待核验' : image?.source_type==='official_asset_composite' ? '官方来源素材排版' : hasProduct ? '上传原图排版 · 待审核' : '主题信息卡 · 未使用产品图';
    const imageLabel=a.images.some(i=>i.source_type==='pre_generated')?'预生成素材 · 未调用生图 API':a.images.some(i=>i.is_generated)?'含实时 AI 生图':a.images.some(i=>['official_asset_composite','user_asset_composite'].includes(i.source_type))?'真实素材排版':a.images.length?'信息卡（缺少产品原图）':'待补充素材';
    const modes=(a.generation_mode==='llm'?'模型生成文案':'策略整理模式')+' · '+imageLabel+(a.generation_mode==='llm'?'':' · 未调用文案模型');
    const sourceLink=/^https:\/\//.test(image?.source_ref || '') ? `<a href="${esc(image.source_ref)}" target="_blank" rel="noopener">查看来源页面 ↗</a>` : generated||hasProduct?'用户提供原图，来源待审核':'请上传对应型号的原图后生成产品海报';
    return `<div class="mc-results-page b-workbench">
      <div class="mc-page-head"><div><h1>推广成果工作台</h1><p class="mc-muted">把已确认的方向，变成值得读、可追溯的作品。</p></div>${btn('导入 A 的策略','import')}</div>
      <section class="mc-result-summary"><div><div><span>推广主题</span><strong>${esc(s.topic)}</strong></div><div><span>产品</span><strong>${esc(a.request.product_context.model || '未指定型号')}</strong></div><div><span>发布平台</span><strong>${esc(a.platform)}</strong></div></div><span class="mc-result-status">${o.bDirty?'本地编辑待保存':`版本 ${a.version} · ${a.saved?'已保存':'预览草稿'}`}</span></section>
      <div class="b-row" aria-label="分平台成果">${['公众号','微信朋友圈','小红书'].map(p=>btn(p==='微信朋友圈'?'朋友圈':p,'platform',P?.platform(a.platform)===p?'mc-primary':'mc-secondary',`data-id="${p}"`)).join('')}</div>
      <div class="b-status-line" role="status"><span id="b-job-status">${busy?'正在处理，请稍候':modes}</span><span>${a.can_publish&&unchanged?'交付检查通过':'待审核，暂不可直接发布'}</span></div>
      ${lastError?`<div class="b-status-line" role="alert">${esc(lastError)}</div>`:''}
      ${a.errors?.length?`<div class="b-status-line" role="alert">${a.errors.map(e=>esc(e.message)).join('<br>')}</div>`:''}
      <div class="mc-results-workbench"><div class="mc-result-art-column"><section class="mc-panel mc-result-artwork">
      <div class="mc-panel-heading"><div><h2>当前推广作品</h2><p class="mc-muted">${esc(image?.role || '暂无图片')} · ${a.images.length} 张</p></div>${btn('下载原图','png','mc-link',image?'':'disabled')}</div>
      <div class="b-row">${btn('选择配图 / 更换配图','replace','mc-primary')}<span class="mc-muted">预生成素材 · 不调用生图 API · 保留当前文案</span></div>
      ${image?`<div class="b-poster"><img src="${esc(image.url)}" alt="${esc(image.alt)}" onerror="this.hidden=true;this.parentElement.nextElementSibling.hidden=false"></div><p hidden role="alert">图片加载失败，请更换可用素材。</p>`:'<p class="mc-muted">待补充素材：没有匹配的图片；文案保留。</p>'}
      <div class="mc-result-thumbnails">${a.images.map((i,n)=>`<button type="button" class="mc-result-thumb ${image?.image_id===i.image_id?'is-selected':''}" data-action="b-select" data-id="${i.image_id}"><img src="${esc(i.url)}" alt="${esc(i.role)}"><span>${n+1}</span></button>`).join('')}</div>
      <p class="mc-muted">${source}<br>${pregenerated?'直接展示完整原图，不重复叠加标题或文案。图片内文字不可编辑。系列匹配不代表精确配置已核验，图片视觉及授权待确认。':generated?'模型 '+esc(image.generation_model)+'；参考原图不代表外观完全一致。图内文字、产品细节与授权均需审核。':hasProduct?'产品素材未重绘；发布前仍需核对外观、图内文字与授权。':'当前图片不是已核验产品照片。'}</p>
      <div class="b-row">${btn('上移','up','mc-link',image?'':'disabled')}${btn('下移','down','mc-link',image?'':'disabled')}${btn('取消选择此图','remove','mc-link',image?'':'disabled')}</div>
      </section></div>
      <div class="mc-result-edit-column"><section class="mc-panel mc-editor"><div class="mc-panel-heading"><h2>修改文案</h2>${btn('重新生成','regenerate','mc-link')}</div>
      <label class="mc-field"><span>发布标题 <small>建议不超过 ${a.request.limits.title} 字</small></span><input data-b-copy="title" value="${esc(a.copy.title)}" maxlength="${a.request.limits.title}" ${busy?'disabled':''}></label>
      <label class="mc-field"><span>发布正文</span><textarea data-b-copy="body" rows="9" maxlength="${a.request.limits.body}" ${busy?'disabled':''}>${esc(a.copy.body)}</textarea></label>
      <label class="mc-field"><span>行动引导（策略未要求时留空）</span><input data-b-copy="cta" value="${esc(a.copy.cta)}" ${busy?'disabled':''}></label>
      <label class="mc-field"><span>话题标签（空格分隔）</span><input data-b-copy="hashtags" value="${esc(a.copy.hashtags.join(' '))}" ${busy?'disabled':''}></label>
      <div class="b-row">${btn('保存审核草稿','save','mc-primary')}${btn('复制审核稿','copy')}${btn('导出图文包','export')}</div>
      <details class="b-evidence" open><summary>事实与来源 ${a.request.product_context.facts.length} 项 · ${esc(a.fact_check_status)}</summary><p class="mc-muted">文案改动后，旧核查结论自动失效。此处展示 A 的结果，B 不替代事实核查。</p><ul>${a.publish_blockers.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
      ${a.request.product_context.facts.map(f=>`<p><strong>${esc(f.claim)}</strong><br><small>${esc(f.source_ref)}</small></p>`).join('')}
      ${a.request.excluded_facts?.length?`<p>生成时排除了 ${a.request.excluded_facts.length} 项缺来源、冲突、过期或型号不符的信息。</p>`:''}
      ${a.fact_check.claims?.map(c=>`<p>${esc(c.claim)} · ${esc(c.status)}<br><small>${esc(c.reason || '')}</small></p>`).join('') || ''}
      <div class="b-row">${btn('重新核查','validate')}${btn('导出核查请求','check-payload','mc-link')}</div></details>
      <details class="b-evidence"><summary>版本恢复与已保存成果</summary><div class="b-row">${btn('查看版本','versions')}${btn('读取已保存成果','history')}</div></details>
      </section><section class="mc-panel b-examples"><h2>同一产品，不同生活</h2><p class="mc-muted">三个明确标记的演示策略，查看不同受众的表达与版式。</p><div class="b-row">${[['study','新学期'],['work','移动办公'],['create','个人创作']].map(([id,label])=>btn(label,'example','mc-secondary',`data-id="${id}"`)).join('')}</div></section></div></div></div>`;
  }
  function modal(title, html, onSubmit) {
    const dialog=document.createElement('dialog'); dialog.className='mc-regenerate-dialog b-dialog';
    dialog.innerHTML=`<form method="dialog"><div class="mc-dialog-heading"><h2>${esc(title)}</h2><button class="mc-link" value="cancel">关闭</button></div>${html}</form>`;
    document.getElementById('marketing-creator-home').append(dialog);
    dialog.querySelector('form').addEventListener('submit',e=>{
      if(e.submitter?.value==='cancel') return;
      e.preventDefault(); const data=new FormData(e.target,e.submitter); dialog.close(); onSubmit(data);
    });
    dialog.addEventListener('close',()=>dialog.remove(),{once:true}); dialog.showModal();
    return dialog;
  }
  async function runExample(id) {
    if(!examples.length) examples=await api('/examples');
    const sample=examples.find(x=>x.id===id) || examples[0];
    const req=structuredClone(sample.request); req.task_id='demo-'+crypto.randomUUID(); req.idempotency_key=crypto.randomUUID();req.image_mode='pregenerated';
    const d=host.newContentTask(req);
    await poll(await api('/generate','POST',req),d);
  }
  async function action(name,id) {
    if(!name.startsWith('b-')) return false;
    name=name.slice(2);
    if(busy) return true;
    if(name==='example') {await guarded(()=>runExample(id)); return true;}
    if(name==='import') {
      modal('接收已确认策略',`<p>粘贴 A 交付的完整生成请求 JSON。保留事实来源与核实状态，不能只传主题。</p><textarea name="json" rows="12" required aria-label="策略 JSON"></textarea><button class="mc-primary">生成图文</button>`,data=>guarded(async()=>{
        const req=JSON.parse(data.get('json')); req.idempotency_key=crypto.randomUUID();req.image_mode='pregenerated';
        const job=await api('/generate','POST',req); const d=host.newContentTask(req); await poll(job,d);
      })); return true;
    }
    const a=asset(); if(!a) return true;
    const selected=a.images.find(i=>i.image_id===current().activeImageId) || a.images[0];
    if(name==='platform') {
      const found=Object.keys(host.getDraft().outputs).find(p=>(P?.platform(p) || p)===id && host.getDraft().outputs[p]?.bAsset);
      if(!found){host.toast('此平台尚无真实成稿。请先在需求中选择该平台并确认对应策略；当前稿件和图片已保留。');return true;}
      await guarded(async()=>{await flush();host.getDraft().activePlatform=found;host.record();});
      return true;
    }
    if(name==='select') {current().activeImageId=id; host.record(); host.render(); return true;}
    if(name==='regenerate') {
      modal('重新生成文案',`<p>只更新当前平台文案，保留已选图片和顺序。图片通过“选择配图”更换，不调用生图 API。</p><label class="mc-field"><span>文案方式</span><select name="copy_mode"><option value="assembly">策略整理 · 无模型调用</option><option value="llm" ${a.request.copy_mode==='llm'?'selected':''} ${capabilities.llm_configured?'':'disabled'}>AI 文案 · 使用服务额度</option></select></label><label class="mc-field"><span>调整方向</span><input name="adjustment" placeholder="例如：更简洁，突出已核实的特点"></label><button class="mc-primary">确认重新生成文案</button>`, data=>guarded(async()=>{
        await flush(); const latest=asset();
        await poll(await api('/regenerate','POST',{asset_id:latest.asset_id,expected_version:latest.version,scope:'copy',copy_mode:data.get('copy_mode'),image_mode:'pregenerated',adjustment:data.get('adjustment'),idempotency_key:crypto.randomUUID()}),host.getDraft());
      })); return true;
    }
    if(name==='replace' || name==='ai-poster') {
      await guarded(async()=>{catalog=await api('/catalog?model='+encodeURIComponent(a.request.product_context.model)+'&platform='+encodeURIComponent(a.platform));});
      if(!catalog.length) {host.toast('待补充素材：没有匹配当前型号及平台的素材，已有文案保留。'); return true;}
      modal('选择预生成配图',`<p>当前平台 ${esc(a.platform)}。可选择 0–4 张，不伪造补齐；保留文案，配图变化后旧核查失效。${catalog.length<2?'素材不足 2 张，请补充。':''}</p><div class="b-material-grid">${catalog.map(c=>`<label><img src="${esc(c.url)}" alt="${esc(c.theme || c.catalog_id)}" onerror="this.hidden=true;this.nextElementSibling.textContent='图片加载失败'"><span>${esc(c.theme || c.catalog_id)}</span><input type="checkbox" name="material" value="${esc(c.catalog_id)}" ${a.images.some(i=>i.image_id===c.catalog_id)?'checked':''}>选择此图<small>预生成素材 · 图片内文字不可编辑 · 视觉 unknown</small></label>`).join('')}</div><button class="mc-primary">应用所选素材</button>`,data=>guarded(async()=>{
        const chosen=data.getAll('material');if(chosen.length>4)throw new Error('每个平台最多选择 4 张素材。');
        await flush(); const latest=asset();
        const order=[...latest.images.map(i=>i.image_id).filter(id=>chosen.includes(id)),...chosen.filter(id=>!latest.images.some(i=>i.image_id===id))];
        apply(await api('/'+latest.asset_id,'PATCH',{expected_version:latest.version,selected_image_ids:order}));
      })); return true;
    }
    await guarded(async()=>{
      await flush(); const latest=asset(), base={asset_id:latest.asset_id,expected_version:latest.version};
      if(name==='save') {apply(await api('/save','POST',base)); host.toast('已保存审核草稿，可在已保存成果中读取。');}
      if(name==='validate') {apply(await api('/validate','POST',base)); host.toast(asset().fact_check_status==='passed'?'文案核查通过，请继续确认图片与授权。':'核查尚未通过，当前成果仍为审核草稿。');}
      if(name==='export') await download('/api/content/'+latest.asset_id+'/export',latest.asset_id+'-审核图文.zip');
      if(name==='check-payload') exportBlob(JSON.stringify(await api('/'+latest.asset_id+'/check-payload'),null,2),'A-最终核查请求.json');
      if(name==='copy') {await navigator.clipboard.writeText(['【审核草稿】',latest.copy.title,latest.copy.body,latest.copy.cta,latest.copy.hashtags.join(' ')].filter(Boolean).join('\n\n')); host.toast('已复制审核稿，核查未完成时不要直接发布。');}
      if(['up','down'].includes(name)) {
        const order=latest.images.map(i=>i.image_id), index=order.indexOf(selected.image_id), next=index+(name==='up'?-1:1);
        if(next<0||next>=order.length) return;
        [order[index],order[next]]=[order[next],order[index]];
        apply(await api('/'+latest.asset_id,'PATCH',{expected_version:latest.version,image_order:order}));
      }
      if(name==='remove') apply(await api('/'+latest.asset_id,'PATCH',{expected_version:latest.version,remove_image_id:selected?.image_id}));
      if(name==='png'&&selected) {
        if(selected.source_type==='pre_generated') {await download(selected.url,selected.url.split('/').pop(),true);return;}
        const response=await fetch(selected.url); if(!response.ok) throw new Error('图片无法读取。');
        const blob=await response.blob(), url=URL.createObjectURL(blob), img=new Image();
        try {await new Promise((resolve,reject)=>{img.onload=resolve; img.onerror=reject; img.src=url;});
          const canvas=document.createElement('canvas'); canvas.width=selected.width; canvas.height=selected.height; canvas.getContext('2d').drawImage(img,0,0);
          const png=await new Promise(resolve=>canvas.toBlob(resolve,'image/png')); if(!png) throw new Error('PNG 导出失败');
          exportBlob(png,selected.image_id+'.png','image/png');
        } finally {URL.revokeObjectURL(url);}
      }
      if(name==='versions') {
        const versions=await api('/'+latest.asset_id+'/versions');
        modal('恢复历史版本',`<p>恢复会创建新版本，旧记录仍保留，核查状态重新置为待核查。</p><select name="version">${versions.map(v=>`<option value="${v.version}">v${v.version} · ${esc(v.last_action)} · ${esc(v.updated_at)}</option>`).join('')}</select><button class="mc-primary">恢复该版本</button>`,data=>guarded(async()=>{const x=asset(); apply(await api('/restore','POST',{asset_id:x.asset_id,expected_version:x.version,version:Number(data.get('version'))}));}));
      }
      if(name==='history') {
        const records=await api('');
        modal('服务端已保存成果',`<p>${records.length} 份已保存草稿。删除不影响公共素材。</p><select name="asset_id">${records.map(r=>`<option value="${r.asset_id}">${esc(r.copy.title)} · v${r.version}</option>`).join('')}</select><button class="mc-primary" name="operation" value="open">打开</button><button class="mc-secondary" name="operation" value="delete">删除记录</button>`,data=>guarded(async()=>{
          const id=data.get('asset_id'); if(!id) return; const found=await api('/'+id);
          if(data.get('operation')==='delete') {await api('/'+id,'DELETE',{expected_version:found.version}); host.toast('已删除该条服务端记录，当前本地编辑仍保留。');}
          else {const d=host.newContentTask(found.request); apply(found,d); host.navigate('results');}
        }));
      }
    }); return true;
  }
  document.addEventListener('input',e=>{
    const key=e.target.dataset.bCopy;
    if(!key||!asset()||busy) return;
    const o=current(); o.bAsset.copy[key]=key==='hashtags'?e.target.value.split(/\s+/).filter(Boolean):e.target.value;
    o.bDirty=true; o.bAsset.can_publish=false; o.bAsset.fact_check_status='pending';
    o.bAsset.publish_blockers=['内容已修改，请保存并重新核查。'];
    o.title=o.bAsset.copy.title; o.body=o.bAsset.copy.body; o.cta=o.bAsset.copy.cta; host.record();
    const status=document.querySelector('.mc-result-status'); if(status) status.textContent='本地编辑待保存 · 旧核查已失效';
  });
  window.ContentB={render,action,generate,fromPrototype,api,bind(h){host=h;},async boot(){
    try {capabilities=await api('/capabilities');} catch {return;}
    const saved=new URLSearchParams(location.search).get('content_asset');
    if(saved && /^asset-[a-f0-9]{32}$/.test(saved)) {
      await guarded(async()=>{const found=await api('/'+saved); const d=host.newContentTask(found.request); apply(found,d); host.navigate('results');});
      history.replaceState(history.state,'',location.pathname+location.hash); return;
    }
    const sample=new URLSearchParams(location.search).get('content_demo');
    if(sample) {await guarded(()=>runExample(sample)); history.replaceState(history.state,'',location.pathname+location.hash);}
  }};
})();
