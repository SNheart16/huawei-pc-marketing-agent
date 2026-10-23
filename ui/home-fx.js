/* 首页 v4 效果层：几何粒子光线、苹果式滚动动效、侧边栏收起状态恢复。
   只作用于静态 DOM；不触碰路由、状态与数据结构。 */
(function () {
  "use strict";
  var root = document.getElementById("marketing-creator-home");
  if (!root) return;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* 侧边栏收起状态恢复（prototype.js 的点击委托负责切换） */
  try {
    if (localStorage.getItem("mc-side-collapsed") === "1") {
      var app = root.querySelector(".mc-app");
      if (app) app.classList.add("collapsed");
      var btn = root.querySelector(".mc-collapse-btn");
      if (btn) btn.setAttribute("aria-label", "展开侧边栏");
    }
  } catch (e) { /* 私有模式下忽略 */ }

  /* 苹果式滚动：进入视口升起 + hero 视差淡出 */
  if (!reduced) {
    var revealSelectors = [".mc-home-head", ".mc-home-products", ".mc-home-platforms", ".mc-composer", ".mc-below", ".mc-trust", ".mc-recommendation-head", "#mc-opportunity-cards", ".mc-gallery-foot"];
    var targets = [];
    revealSelectors.forEach(function (sel) {
      var el = root.querySelector(sel);
      if (el) { el.classList.add("reveal"); targets.push(el); }
    });
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) { entry.target.classList.add("is-in"); io.unobserve(entry.target); }
        });
      }, { threshold: 0.15 });
      targets.forEach(function (el) { io.observe(el); });
    } else {
      targets.forEach(function (el) { el.classList.add("is-in"); });
    }

    var hero = document.getElementById("mc-hero");
    var ticking = false;
    window.addEventListener("scroll", function () {
      if (ticking || !hero || !hero.isConnected) return;
      ticking = true;
      requestAnimationFrame(function () {
        var y = window.scrollY, vh = window.innerHeight;
        if (y < vh) {
          var p = y / vh;
          hero.style.transform = "translateY(" + y * 0.12 + "px)";
          hero.style.opacity = String(1 - p * 0.45);
        }
        ticking = false;
      });
    }, { passive: true });
  }

  /* 几何粒子光线画布：按需求暂时停用（保留滚动动效与侧边栏状态恢复） */
  return;
  var cv = document.getElementById("mc-fx");
  if (!cv || !cv.getContext) return;
  var ctx = cv.getContext("2d");
  var host = cv.parentElement;
  var W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
  var RED = "228,0,43", INK = "90,90,98";
  var particles = [], rays = [];

  function rand(a, b) { return a + Math.random() * (b - a); }
  function resize() {
    W = host.clientWidth; H = host.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.width = W + "px"; cv.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    seed();
    if (reduced) drawFrame(0);
  }
  function seed() {
    particles = [];
    var n = Math.round(W * H / 22000);
    for (var i = 0; i < n; i++) {
      particles.push({ x: rand(0, W), y: rand(0, H * 0.9), s: rand(1.6, 3.6),
        vx: rand(-0.08, 0.08), vy: rand(-0.05, 0.05), a: rand(0.22, 0.5),
        red: Math.random() < 0.45, sq: Math.random() < 0.5, ph: rand(0, Math.PI * 2) });
    }
    rays = [];
    var rn = Math.max(4, Math.round(W / 320));
    for (var j = 0; j < rn; j++) {
      rays.push({ x: rand(0, W), y: rand(H * 0.05, H * 0.75), len: rand(320, 680),
        angle: rand(-0.62, -0.38), w: rand(1.2, 2.4), a: rand(0.14, 0.26),
        red: Math.random() < 0.6, sp: rand(0.06, 0.16) });
    }
  }
  function drawFrame(t) {
    ctx.clearRect(0, 0, W, H);
    for (var i = 0; i < rays.length; i++) {
      var r = rays[i];
      var dx = Math.cos(r.angle) * r.len, dy = Math.sin(r.angle) * r.len;
      var ox = Math.cos(t / 4000 * r.sp * 10 + i) * 18;
      ctx.strokeStyle = "rgba(" + (r.red ? RED : INK) + "," + r.a + ")";
      ctx.lineWidth = r.w;
      ctx.beginPath(); ctx.moveTo(r.x + ox, r.y); ctx.lineTo(r.x + ox + dx, r.y + dy); ctx.stroke();
      ctx.fillStyle = "rgba(" + (r.red ? RED : INK) + "," + (r.a + 0.10) + ")";
      ctx.fillRect(r.x + ox + dx - 1.5, r.y + dy - 1.5, 3, 3);
    }
    for (var k = 0; k < particles.length; k++) {
      var p = particles[k];
      p.x += p.vx; p.y += p.vy;
      if (p.x < -6) p.x = W + 6; if (p.x > W + 6) p.x = -6;
      if (p.y < -6) p.y = H * 0.9; if (p.y > H * 0.9 + 6) p.y = -6;
      var tw = 0.65 + 0.35 * Math.sin(t / 900 + p.ph);
      ctx.fillStyle = "rgba(" + (p.red ? RED : INK) + "," + (p.a * tw).toFixed(3) + ")";
      if (p.sq) ctx.fillRect(p.x - p.s / 2, p.y - p.s / 2, p.s, p.s);
      else { ctx.beginPath(); ctx.arc(p.x, p.y, p.s / 2, 0, Math.PI * 2); ctx.fill(); }
    }
  }
  function loop(t) { drawFrame(t || 0); requestAnimationFrame(loop); }
  window.addEventListener("resize", resize);
  resize();
  if (!reduced) requestAnimationFrame(loop);
})();
