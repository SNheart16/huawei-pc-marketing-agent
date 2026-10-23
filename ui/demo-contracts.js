/* Small pure boundary helpers shared by the real demo and its offline tests. */
(function (root, factory) {
  const value = factory();
  if (typeof module === 'object' && module.exports) module.exports = value;
  else root.DemoContracts = value;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function binding(task, strategy) {
    if (!task?.task_id || !Number.isInteger(task.revision)) throw new Error('请先创建有效任务。');
    const value = {task_id: task.task_id, expected_revision: task.revision};
    if (strategy) Object.assign(value, {strategy_id: strategy.strategy_id, strategy_version: strategy.strategy_version});
    return value;
  }
  function currentStrategy(task, strategy) {
    return Boolean(task && strategy && task.current_strategy_id === strategy.strategy_id && task.current_strategy_version === strategy.strategy_version);
  }
  function finalResult(asset) { return asset?.fact_check?.a_result?.final_check || null; }
  function textUsable(asset, task, strategy, dirty) {
    const check = finalResult(asset);
    return Boolean(!dirty && currentStrategy(task, strategy) && strategy.confirmation_status === 'confirmed'
      && asset?.task_id === task.task_id && asset?.strategy_id === strategy.strategy_id
      && check?.valid === true && check?.task_id === task.task_id && check?.saved_task_revision === task.revision
      && check?.strategy_id === strategy.strategy_id && check?.strategy_version === strategy.strategy_version
      && check?.overall?.text_usable === true && check?.text_check?.status === 'passed'
      && typeof check?.usable_text?.plain_text === 'string' && check.usable_text.plain_text.length > 0
      && (asset?.quality_issues || []).length === 0);
  }
  function safeMedia(url) { return typeof url === 'string' && (/^\/api\/content\/media\/img-[a-f0-9]{32}\.(svg|png)$/.test(url) || /^\/assets\/pregenerated\/(wechat-article|moments|xiaohongshu)\/[a-zA-Z0-9_-]+\.(png|jpe?g|webp)$/.test(url)) ? url : null; }
  function cardAnswers(cards, selected) {
    return cards.flatMap(card => {
      const ids = selected[card.question_id] || [];
      if (!ids.length) return [];
      if (ids.some(id => !card.options.some(option => option.option_id === id)) || (card.mode === 'single' && ids.length !== 1)) throw new Error('卡片选择已变化，请重新选择。');
      return [{question_id: card.question_id, option_ids: ids}];
    });
  }
  return {binding, currentStrategy, finalResult, textUsable, safeMedia, cardAnswers};
});
