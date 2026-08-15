/* ============================================================
 * WorldSim 品宣动态 Logo · 动画引擎（worldsim-anim.js）
 * 由 index.htm 引用（<script src="worldsim-anim.js">）。
 * 动画逻辑与页面结构分离：index.htm 保持纯净，只承载
 * AI Agent 可读的 skill 介绍与安装指令（见 index.htm
 * 顶部注释与 JSON-LD）。
 *
 * 设计叙事（对齐 skill 设计哲学「活起来」）：
 *   1. 打字机苏醒 —— WorldSim — Where Worlds Come to Life 逐字亮起
 *      （整行同一字体 / 同一字号 / 同一高度，纯淡入+轻微辉光，无上下位移；
 *        打字光标颜色跟随前一个字符）
 *      —— World 与 Sim 之间有一拍细微停顿（数字世界到觉醒的过渡）
 *      —— Sim 与标语同为觉醒金，数字世界向觉醒世界的连接
 *      —— 「Come to 」打完有一拍悬念停顿（光标紧贴 to），空格与 Life
 *         在停顿后敲入；Life 逐字亮起的同时由觉醒金渐变为生命绿
 *   2. 停顿 —— 完整一行稍作停留（此刻 Life 已为生命绿）
 *   3. 向左消隐 —— 仅前缀「 — Where Worlds Come to 」快速向左收起消失；
 *      末尾的 Life 是同一个字形，随前缀收窄左移贴向 WorldSim
 *   4. 点亮 —— 中间补上「.」，Life 开始呼吸；副标题淡入
 *   终态 = WorldSim.Life —— 域名地址，形态不再缩短，稳定停留
 *
 * 配色语义（品牌叙事）：
 *   · World                = 数码青 --digital  数字世界未醒时的颜色（冷色休眠）
 *   · Sim → Where Worlds…  = 觉醒金 --wake     Westworld 里 host 的觉醒（金色黎明）
 *   · 最终 .Life           = 生命绿 --life     生命的颜色（脉搏荧光）
 *
 * 调参：改动下方 CFG 对象即可（时长/速度/停顿）。
 * 自检：URL 带 ?check=1 输出验证信息；?fast=1 压缩时长快速走完。
 * ============================================================ */

(function () {
  'use strict';

  /* ---------- 调参 ---------- */
  var CFG = {
    wordmarkMs: 90,    // 字标每字间隔（数字苏醒的节奏）
    simGapMs:   0,   // World 打完 → Sim 开始前的一拍细微停顿（数字世界到觉醒的过渡）
    dashGapMs:  600,   // 字标 → 破折号之间的一拍呼吸
    taglineMs:  90,    // 标语每字间隔（host 觉醒前的轻诵）
    lifeGapMs:  120,   // 「Come to 」打完 → Life 出现前的一拍悬念停顿（光标紧贴 to）
    lifeCharMs: 240,    // Life 每字间隔（独立于标语；默认与 taglineMs 一致）
    holdMs:     1300,  // 完整一行后的停顿
    exitMs:     240,   // 前缀向左收起时长（快速）
    lifeDelay:  120,   // 收起开始后 Life 变色 / 点出现的延迟
    lifeMs:     480,   // 收起/点出现后到终态呼吸的过渡停留
    breatheMs:  10000,  // 终态呼吸停留（WorldSim.Life 多停留一会）
    fadeMs:     240,   // 循环淡出
    loopGapMs:  200   // 淡出后、下一轮开始前的循环间等待（黑场停顿）
  };

  var BRAND = {
    wordmark: 'WorldSim',
    lead:     ' — Where Worlds Come to ', // 前导空格+破折号+尾随空格（最终消失）
    life:     'Life'                       // 与标语同字形，最终保留为 .Life 的 Life
  };

  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 自检加速模式（?fast=1）：压缩全部 JS 时长 + CSS transition，动画完整路径瞬间走完 */
  var fastMode = location.search.indexOf('fast=1') !== -1;
  if (fastMode) {
    CFG.wordmarkMs = 0; CFG.simGapMs = 0; CFG.dashGapMs = 0; CFG.taglineMs = 0; CFG.lifeCharMs = 0; CFG.holdMs = 0;
    CFG.exitMs = 1; CFG.lifeDelay = 1; CFG.lifeMs = 2; CFG.breatheMs = 1; CFG.fadeMs = 1; CFG.loopGapMs = 0; CFG.lifeGapMs = 0;
    var _st = document.documentElement.style;
    _st.setProperty('--exit-dur', '0s');
    _st.setProperty('--life-dur', '0s');
  }
  var stageLog = (location.search.indexOf('check=1') !== -1) ? [] : null;

  var stageEl  = document.getElementById('stage');
  var logoEl   = document.getElementById('logo');
  var wordEl   = document.getElementById('wordmark');
  var tagEl    = document.getElementById('tagline');
  var leadEl   = document.getElementById('lead');
  var lifeEl   = document.getElementById('lifePart');
  var subEl    = document.getElementById('subtitle');
  var loopBox  = document.getElementById('loop');

  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var runId = 0;

  /* ---------- 视口适配：整行同字号，超宽则等比缩小（整体不变形） ---------- */
  function fitToViewport() {
    logoEl.style.fontSize = '';
    var probe = document.createElement('span');
    probe.style.cssText =
      'position:fixed;left:-9999px;top:0;visibility:hidden;white-space:nowrap;' +
      'font-family:' + getComputedStyle(logoEl).fontFamily + ';' +
      'font-weight:600;letter-spacing:.08em;';
    probe.style.fontSize = getComputedStyle(logoEl).fontSize;
    probe.textContent = BRAND.wordmark + BRAND.lead + BRAND.life;
    document.body.appendChild(probe);
    var full = probe.getBoundingClientRect().width;
    document.body.removeChild(probe);
    var avail = Math.min(window.innerWidth * 0.94, 1680);
    var base = parseFloat(getComputedStyle(logoEl).fontSize);
    if (full > avail) {
      logoEl.style.fontSize = Math.max(12, Math.floor(base * avail / full)) + 'px';
    }
  }

  /* ---------- 打字机 ---------- */
  function appendChar(parent, ch, cls) {
    var s = document.createElement('span');
    s.className = 'ch ' + cls;
    s.textContent = ch;
    parent.appendChild(s);
    syncCaretColor();
  }

  /* 光标颜色跟随前一个字符：读 logo 末尾最后一个可见字符的当前颜色；
     打字结束光标移除后无操作。无字符时继承青色（logo 默认 --digital）。 */
  function syncCaretColor() {
    var c = document.getElementById('caret');
    if (!c) return;
    var chs = logoEl.querySelectorAll('.ch');
    var last = chs[chs.length - 1];
    var col = last ? getComputedStyle(last).color : getComputedStyle(logoEl).color;
    c.style.color = col;
    c.style.boxShadow = '0 0 12px ' + (col.indexOf('rgb') === 0 ? col.replace('rgb', 'rgba').replace(')', ',.55)') : 'rgba(77,208,225,.55)');
  }

  function addCaret() {
    var c = document.createElement('span');
    c.className = 'caret';
    c.id = 'caret';
    // 插在 wordmark 与 tagline 之间（紧贴字标末尾；空 tagline 的 margin-left 会把光标推开）
    logoEl.insertBefore(c, tagEl);
    return c;
  }

  /* 光标位置随打字阶段移动：
     字标阶段在 wordmark 后紧贴字母；标语阶段移到 tagline 后（紧跟 Life）。 */
  function moveCaretAfterTagline() {
    var c = document.getElementById('caret');
    if (c) logoEl.appendChild(c);
  }

  /* 点：紧跟 WorldSim，与 Life 同字体同字号 */
  function addDot() {
    if (wordEl.querySelector('.dot')) return;
    var d = document.createElement('span');
    d.className = 'dot';
    d.textContent = '.';
    wordEl.appendChild(d);
  }

  function resetAll() {
    stageEl.classList.remove('fadeout');
    wordEl.textContent = '';
    tagEl.classList.remove('close');
    leadEl.textContent = '';
    leadEl.classList.remove('gone');
    leadEl.style.width = '';
    lifeEl.textContent = '';
    lifeEl.classList.remove('lit', 'breath');
    logoEl.classList.remove('pulse');
    subEl.classList.remove('show');
    var c = document.getElementById('caret');
    if (c) c.remove();
  }

  /* ---------- 主时间线 ---------- */
  async function playOnce(id) {
    var alive = function () { return id === runId; };
    resetAll();

    if (reduced) { /* 无障碍：直接终态 WorldSim.Life */
      wordEl.textContent = BRAND.wordmark;
      addDot();
      leadEl.textContent = BRAND.lead;
      leadEl.style.display = 'none';
      lifeEl.textContent = BRAND.life;
      lifeEl.classList.add('lit');
      subEl.classList.add('show');
      if (stageLog) stageLog.push('reduced-static');
      // reduced 路径为同步：延迟到宏任务，确保探针 __probeReady 已定义（探针块在 start() 之后求值）
      setTimeout(function () { if (window.__probeReady) window.__probeReady(); }, 0);
      return;
    }

    var caret = addCaret();

    // 1) 字标逐字点亮（World 数码青·数字世界未醒时；Sim 觉醒金，与标语同色，数字世界向觉醒世界的连接）
    for (var i = 0; i < BRAND.wordmark.length; i++) {
      appendChar(wordEl, BRAND.wordmark.charAt(i), i < 5 ? 'ch-w' : 'ch-sim');
      await sleep(CFG.wordmarkMs);
      if (!alive()) return;
      if (i === 4) {           // World 打完 → Sim 前的一拍细微停顿
        await sleep(CFG.simGapMs);
        if (!alive()) return;
      }
    }
    if (stageLog) stageLog.push('s1-wordmark:' + wordEl.textContent);
    // 2) 破折号前的呼吸
    await sleep(CFG.dashGapMs);
    if (!alive()) return;
    // 3) 标语逐字轻诵（觉醒金·host 苏醒；Life 逐字亮起的同时由金渐变为生命绿）
    moveCaretAfterTagline();  // 光标移到标语末尾（紧跟即将打出的字符）
    // 打「 — Where Worlds Come to」（不含尾随空格）：to 打完即停顿，光标紧贴 to
    for (var j = 0; j < BRAND.lead.length - 1; j++) {
      appendChar(leadEl, BRAND.lead.charAt(j), 'ch-t');
      await sleep(CFG.taglineMs);
      if (!alive()) return;
    }
    // Life 前的悬念停顿：to 打完 → Life 出现前的一拍（光标紧贴 to，不在空格后）
    await sleep(CFG.lifeGapMs);
    if (!alive()) return;
    // 敲入 to 与 Life 之间的空格，紧接 Life 苏醒
    appendChar(leadEl, BRAND.lead.charAt(BRAND.lead.length - 1), 'ch-t');
    await sleep(CFG.taglineMs);
    if (!alive()) return;
    // Life 苏醒与打字同步：渐变时长 = Life 每字间隔 × 字母数，打完最后一个字母即生命绿
    document.documentElement.style.setProperty('--life-dur', (BRAND.life.length * CFG.lifeCharMs) + 'ms');
    lifeEl.classList.add('lit');
    for (var k = 0; k < BRAND.life.length; k++) {
      appendChar(lifeEl, BRAND.life.charAt(k), 'ch-t');
      await sleep(CFG.lifeCharMs);
      if (!alive()) return;
    }
    if (stageLog) stageLog.push('s2-full:' + logoEl.textContent);
    // 4) 完整一行停顿（光标不消失，继续在 Life 后呼吸闪烁——像活着）
    await sleep(CFG.holdMs);
    if (!alive()) return;

    // 5) 前缀向左收起（先锁定宽度再收缩；Life 随布局左移贴向 WorldSim）
    caret.remove();  // 收起开始，打字光标撤走
    leadEl.style.width = leadEl.offsetWidth + 'px';
    tagEl.classList.add('close');
    // 强制回流，确保 width 从 px 值开始过渡
    void leadEl.offsetWidth;
    leadEl.classList.add('gone');
    logoEl.classList.add('pulse');

    // 6) 点出现（Life 已在打字阶段完成金→绿渐变）
    setTimeout(function () {
      if (!alive()) return;
      addDot();
    }, CFG.lifeDelay);
    await sleep(CFG.exitMs + CFG.lifeMs);
    if (!alive()) return;
    if (stageLog) stageLog.push('s3-collapsed:' + logoEl.textContent + ' leadW=' + leadEl.offsetWidth + ' leadGone=' + leadEl.classList.contains('gone'));

    // 7) 终态：WorldSim.Life = 域名地址，形态不再缩短，稳定停留
    lifeEl.classList.add('breath');
    subEl.classList.add('show');
    if (stageLog) stageLog.push('s4-final:' + logoEl.textContent);
    if (window.__probeReady) window.__probeReady();
    await sleep(CFG.breatheMs);
    if (!alive()) return;

    // 8) 循环：淡出 → 黑场停顿（循环间等待）→ 下一轮
    if (loopBox.checked) {
      stageEl.classList.add('fadeout');
      await sleep(CFG.fadeMs);
      if (!alive()) return;
      await sleep(CFG.loopGapMs);
      if (!alive()) return;
      runId++;
      playOnce(runId);
    }
  }

  function start() {
    runId++;
    playOnce(runId);
  }

  document.getElementById('replay').addEventListener('click', start);
  loopBox.addEventListener('change', function () { if (!loopBox.checked) runId++; });

  /* ---------- 星尘背景（记忆碎片·三色） ---------- */
  var canvas = document.getElementById('dust');
  var ctx = canvas.getContext('2d');
  var W = 0, H = 0, DPR = Math.min(window.devicePixelRatio || 1, 2);
  var particles = [];

  var DUST_COLORS = ['77,208,225', '237,182,78', '74,222,128']; // 数码青 / 觉醒金 / 生命绿

  function makeParticles() {
    particles = [];
    var count = Math.round(Math.min(60, (W * H) / 26000));
    for (var i = 0; i < count; i++) {
      var col = DUST_COLORS[i % 3];
      particles.push({
        x: Math.random() * W,
        y: Math.random() * H,
        r: 0.5 + Math.random() * 1.9,
        vx: (Math.random() - 0.5) * 0.10,
        vy: -(0.05 + Math.random() * 0.22),
        ph: Math.random() * Math.PI * 2,
        fr: 0.5 + Math.random() * 1.2,
        col: col,
        base: 0.08 + Math.random() * 0.28
      });
    }
  }

  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * DPR; canvas.height = H * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    if (!reduced) makeParticles();
  }

  var rafId = null;
  function tick(t) {
    ctx.clearRect(0, 0, W, H);
    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      p.x += p.vx; p.y += p.vy;
      if (p.y < -4) { p.y = H + 4; p.x = Math.random() * W; }
      if (p.x < -4) p.x = W + 4;
      if (p.x > W + 4) p.x = -4;
      var a = p.base + Math.sin(t * 0.001 * p.fr + p.ph) * p.base * 0.8;
      a = Math.max(0, Math.min(1, a));
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + p.col + ',' + a.toFixed(3) + ')';
      ctx.fill();
    }
    rafId = requestAnimationFrame(tick);
  }

  resize();
  window.addEventListener('resize', resize);
  document.addEventListener('visibilitychange', function () {
    if (document.hidden && rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
    else if (!document.hidden && rafId === null && !reduced) { rafId = requestAnimationFrame(tick); }
  });
  if (!reduced) rafId = requestAnimationFrame(tick);

  /* ---------- 无障碍模式 ---------- */
  if (reduced) {
    document.body.classList.add('reduce-motion');
    loopBox.checked = false;
  }

  /* ---------- 启动 ---------- */
  fitToViewport();
  window.addEventListener('resize', fitToViewport);
  start();

  /* ---------- 自检探针（URL 带 ?check=1 时输出验证信息；生产零影响） ----------
     reduced 分支为同步路径：playOnce 在 start() 内同步跑完，__probeReady 定义在此块（start 之后）。
     因此 reduced 分支调用 __probeReady 必须 setTimeout(0) 延迟到宏任务——脚本求值完成、本块定义就绪后才触发。 */
  if (location.search.indexOf('check=1') !== -1) {
    loopBox.checked = false; // 自检只跑一轮
    var probe = document.createElement('pre');
    probe.id = 'probe-out';
    probe.style.cssText =
      'position:fixed;left:8px;top:8px;z-index:99;max-height:82vh;overflow:auto;' +
      'background:rgba(0,0,0,.85);color:#9ff;font:11px/1.5 monospace;padding:8px;' +
      'white-space:pre-wrap;text-align:left;';
    document.body.appendChild(probe);

    var t0 = performance.now();
    var log = [];
    function ps() {
      var cs = getComputedStyle(logoEl);
      log.push(
        't=' + Math.round(performance.now() - t0) +
        ' txt=' + logoEl.textContent +
        ' leadW=' + leadEl.getBoundingClientRect().width.toFixed(1) +
        ' lifeCls=' + lifeEl.className.replace('ch ', '') +
        ' dot=' + (wordEl.querySelector('.dot') ? 1 : 0)
      );
    }
    var probeTimer = setInterval(ps, 120);

    window.__probeReady = function () {
      clearInterval(probeTimer);

      // 几何一致性：视觉可见字符（rect.width>0）的 top/height 范围
      var tops = [], heights = [];
      logoEl.querySelectorAll('.ch, .wordmark > span.dot').forEach(function (el) {
        var r = el.getBoundingClientRect();
        if (r.width > 0.5) { tops.push(Math.round(r.top)); heights.push(Math.round(r.height)); }
      });
      var topMin = Math.min.apply(null, tops), topMax = Math.max.apply(null, tops);
      var hMin = Math.min.apply(null, heights), hMax = Math.max.apply(null, heights);

      var cs = getComputedStyle(logoEl);
      var dotEl = wordEl.querySelector('.dot');
      var leadRect = leadEl.getBoundingClientRect();

      // 逐字符几何明细：定位 top/height 差异来源
      var perChar = [];
      logoEl.querySelectorAll('.ch, .wordmark > span.dot').forEach(function (el) {
        var r = el.getBoundingClientRect();
        if (r.width > 0.5) {
          perChar.push(
            JSON.stringify(el.textContent) + '@' +
            Math.round(r.top) + '/' + Math.round(r.height) + '/' + r.width.toFixed(0)
          );
        }
      });

      probe.textContent = [
        'FINAL logo text : ' + logoEl.textContent,
        'FINAL wordmark  : ' + wordEl.textContent,
        'FINAL life-part : ' + JSON.stringify(lifeEl.textContent) + ' cls=' + lifeEl.className,
        '',
        'font-family     : ' + cs.fontFamily,
        'logo     fs=' + cs.fontSize + ' lh=' + cs.lineHeight + ' w=' + cs.fontWeight,
        'wordmark fs=' + getComputedStyle(wordEl).fontSize,
        'lead     fs=' + getComputedStyle(leadEl).fontSize,
        'life     fs=' + getComputedStyle(lifeEl).fontSize + ' color=' + getComputedStyle(lifeEl).color,
        'dot      fs=' + (dotEl ? getComputedStyle(dotEl).fontSize : 'NONE'),
        '',
        'lead visual width : ' + leadRect.width.toFixed(1) + 'px (终态应≈0)',
        'logo visual width : ' + logoEl.getBoundingClientRect().width.toFixed(1) + 'px',
        'char-top  range: ' + topMin + '..' + topMax + ' (span=' + (topMax - topMin) + 'px)',
        'char-hgt  range: ' + hMin + '..' + hMax + ' (span=' + (hMax - hMin) + 'px)',
        '',
        '--- per-char (top/height/width) ---',
        perChar.join(' | '),
        '',
        '--- stage log ---',
        (stageLog || []).join('\n'),
        '',
        '--- 120ms 采样 ---',
        log.join('\n')
      ].join('\n');
    };
  }
})();
