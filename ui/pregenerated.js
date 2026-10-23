/* Shared boundaries for the fixed-image library. No image-generation requests. */
(function (root, factory) {
  const value = factory();
  if (typeof module === 'object' && module.exports) module.exports = value;
  else root.Pregenerated = value;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const platforms = ['公众号', '微信朋友圈', '小红书'];
  function platform(value) {
    if (['公众号', '微信公众号'].includes(value)) return '公众号';
    if (['朋友圈', '微信朋友圈', '门店朋友圈'].includes(value)) return '微信朋友圈';
    return value === '小红书' ? value : null;
  }
  function safeUrl(value) {
    return typeof value === 'string' && /^\/assets\/pregenerated\/(wechat-article|moments|xiaohongshu)\/[a-zA-Z0-9_-]+\.(png|jpe?g|webp)$/.test(value) ? value : null;
  }
  function key(model, value) { return String(model || '').trim() + '|' + platform(value); }
  function select(ids, id, limit=4) {
    if (ids.includes(id)) return ids.filter(x => x !== id);
    if (ids.length >= limit) throw new Error('每个平台最多选择 4 张素材；请先取消一张。');
    return [...ids, id];
  }
  function move(ids, id, delta) {
    const result = [...ids], index = result.indexOf(id), next = index + delta;
    if (index >= 0 && next >= 0 && next < result.length) [result[index], result[next]] = [result[next], result[index]];
    return result;
  }
  function recommendations(items, topic) {
    const words = String(topic || '').split(/[\s、，。；]+/).filter(Boolean);
    return items.map((item,index)=>({item,index,score:words.reduce((n,word)=>n+(String(item.theme || '').includes(word)?1:0),0)}))
      .sort((a,b)=>b.score-a.score || a.index-b.index).slice(0,4).map(x=>x.item.material_id || x.item.catalog_id);
  }
  return {platforms, platform, safeUrl, key, select, move, recommendations};
});
