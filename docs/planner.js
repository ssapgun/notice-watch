// 자동 플래너 계산 (AI 없음). 같은 규칙이 planner.py 에 있다: 한쪽을 고치면 다른 쪽도 고칠 것.
// 날짜는 'YYYY-MM-DD' 문자열로만 다룬다 (시간대 영향을 받지 않게 UTC 로 계산).
(function (root) {
  const DAY = 86400000;
  const toMs = s => Date.parse(s + "T00:00:00Z");
  const fromMs = ms => new Date(ms).toISOString().slice(0, 10);
  const addDays = (s, n) => fromMs(toMs(s) + n * DAY);
  const weekday = s => (new Date(toMs(s)).getUTCDay() + 6) % 7;   // 0=월 ... 6=일

  const SET = {hours: [120, 120, 120, 120, 120, 240, 240], off: [], window: 7, eta_min: 0.3};
  const settingsOf = pl => Object.assign({}, SET, pl.settings || {});
  const costOf = (item, course) => item.min * (course.mult || 1);
  function avail(st, d) { return st.off.includes(d) ? 0 : (st.hours[weekday(d)] || 0); }

  // 소화율: 최근 n일 실제 완료량 / 계획량. 기록이 없으면 1, 범위는 eta_min ~ 1
  function etaOf(pl, today) {
    const st = settingsOf(pl), log = pl.log || {};
    let planned = 0, done = 0;
    for (let i = 1; i <= st.window; i++) {
      const d = addDays(today, -i);
      if (!log[d] || !(log[d].planned > 0)) continue;
      planned += log[d].planned;
      for (const c of pl.courses || []) for (const it of c.items) if (it.done === d) done += costOf(it, c);
    }
    if (!planned) return 1;
    return Math.min(1, Math.max(st.eta_min, done / planned));
  }

  function daysLeft(st, d, deadline) {
    let n = 0;
    for (let x = d; x <= deadline; x = addDays(x, 1)) if (avail(st, x) > 0) n++;
    return n || 1;
  }

  function compute(pl, today) {
    const st = settingsOf(pl), eta = etaOf(pl, today), EPS = 1e-9;
    const courses = (pl.courses || []).map((c, order) => {
      const queue = c.items.filter(it => !it.done);
      return {c, order, queue, remain: queue.reduce((a, it) => a + costOf(it, c), 0),
              doneToday: c.items.filter(it => it.done === today).reduce((a, it) => a + costOf(it, c), 0)};
    });
    const dated = courses.filter(x => x.c.deadline).sort((a, b) => a.c.deadline < b.c.deadline ? -1 : a.c.deadline > b.c.deadline ? 1 : a.order - b.order);
    const free = courses.filter(x => !x.c.deadline);
    const doneTodayAll = courses.reduce((a, x) => a + x.doneToday, 0);
    const days = [];

    for (let i = 0, d = today; i < 730 && courses.some(x => x.queue.length); i++, d = addDays(d, 1)) {
      const full = avail(st, d);
      if (full <= 0) continue;
      const isToday = d === today;
      let cap = Math.max(0, full - (isToday ? doneTodayAll : 0));
      let placedAny = isToday && doneTodayAll > 0;
      const items = [];
      const take = x => {
        const it = x.queue[0], cost = costOf(it, x.c);
        if (cost > cap + EPS && placedAny) return 0;     // 안 들어가면 다음 날로 (차시는 쪼개지 않는다)
        x.queue.shift();
        x.remain -= cost;
        cap = Math.max(0, cap - cost);
        placedAny = true;
        items.push({cid: x.c.id, iid: it.id, course: x.c.name, title: it.title, min: it.min, cost,
                    late: !!(x.c.deadline && d > x.c.deadline)});
        return cost;
      };
      for (const x of dated) {
        if (!x.queue.length) continue;
        const already = isToday ? x.doneToday : 0;
        const quota = (x.remain + already) / (eta * daysLeft(st, d, x.c.deadline)) - already;
        let used = 0;
        while (x.queue.length && used < quota - EPS && (cap > EPS || !placedAny)) {
          const got = take(x);
          if (!got) break;
          used += got;
        }
      }
      for (const x of free) {
        while (x.queue.length && (cap > EPS || !placedAny)) { if (!take(x)) break; }
      }
      if (items.length || isToday) days.push({date: d, items, total: items.reduce((a, it) => a + it.cost, 0), avail: full});
    }
    if (!days.length || days[0].date !== today) days.unshift({date: today, items: [], total: 0, avail: avail(st, today)});

    // 마감 경고: 그 마감까지 끝내야 할 양 / 소화율 - 쓸 수 있는 시간 > 0 이면 못 맞춘다
    const warnings = [];
    let cum = 0;
    const seen = {};
    const remainAt = x => x.c.items.filter(it => !it.done).reduce((a, it) => a + costOf(it, x.c), 0);
    for (const x of dated) {
      const r = remainAt(x);
      if (!r) continue;
      cum += r;
      (seen[x.c.deadline] = seen[x.c.deadline] || []).push(x.c.name);
      if (dated.filter(y => y.c.deadline === x.c.deadline && remainAt(y) > 0).pop() !== x) continue;   // 같은 마감은 한 번만
      let have = 0;
      for (let d = today; d <= x.c.deadline; d = addDays(d, 1)) have += avail(st, d);
      have = Math.max(0, have - doneTodayAll);
      const need = cum / eta, short = need - have;
      if (short > EPS) warnings.push({deadline: x.c.deadline, courses: seen[x.c.deadline], need, have, short, overdue: x.c.deadline < today});
    }
    return {today, eta, days, warnings};
  }

  // 붙여넣은 목차 → 차시 목록. 시간을 못 찾은 줄은 defaultMin 을 쓰고 noTime 으로 표시한다
  const SKIP = /^(\d{1,3}|no\.?|unit|번호|차시|즐겨찾기|강의리스트전체|보기|개별자료|최종학습일|강의시간|강의명|강의\s*제목|제목|강의\s*목록|목차|학습\s*시간|강의\s*시간|재생\s*시간|시간|진도(율)?|수강(하기)?|복습(하기)?|강의\s*보기|재생|다운로드|학습\s*하기|\d{1,3}\s*%)$/i;
  function parseDuration(line) {
    let m;
    if ((m = line.match(/(\d{1,2}):(\d{2}):(\d{2})/))) return {min: +m[1] * 60 + +m[2] + +m[3] / 60, hit: m[0]};
    if ((m = line.match(/(\d+)\s*시간(?:\s*(\d+)\s*분)?/))) return {min: +m[1] * 60 + (+m[2] || 0), hit: m[0]};
    if ((m = line.match(/(\d+)\s*분(?:\s*(\d+)\s*초)?/))) return {min: +m[1] + (+m[2] || 0) / 60, hit: m[0]};
    if ((m = line.match(/(?<![\d.:/-])(\d{1,3}):(\d{2})(?![\d:])/))) return {min: +m[1] + +m[2] / 60, hit: m[0]};
    return null;
  }
  const isHeader = line => line.split(" ").every(w => SKIP.test(w));   // '번호 강의명 시간 진도율' 같은 표 제목 줄
  const TAIL = /(\s+(\d{1,3}\s*%|수강(하기)?|복습(하기)?|강의\s*보기|학습\s*하기|재생|다운로드|pdf|mp3|-|\d{4}[-.]\d{1,2}[-.]\d{1,2}))+$/i;   // 줄 끝의 진도율·버튼 글자
  function parse(text, defaultMin) {
    const items = [];
    for (const raw of String(text || "").split(/\r?\n/)) {
      const line = raw.replace(/\s+/g, " ").trim();
      if (!line || isHeader(line)) continue;
      const dur = parseDuration(line);
      const title = (" " + (dur ? line.replace(dur.hit, " ") : line)).replace(/[()\[\]]\s*[()\[\]]/g, " ").replace(/\s+/g, " ").replace(TAIL, "").replace(/^\s*(대기|수강|완료|학습중)\s+/, "").replace(/[\s|·,-]+$/, "").trim();
      if (dur && (!title || SKIP.test(title))) {       // 시간만 있는 줄은 바로 앞 차시의 시간
        const prev = items[items.length - 1];
        if (prev && prev.noTime) { prev.min = Math.round(dur.min * 10) / 10; prev.noTime = false; }
        continue;
      }
      items.push({title, min: dur ? Math.round(dur.min * 10) / 10 : defaultMin, noTime: !dur});
    }
    return items;
  }

  const api = {compute, parse, etaOf, addDays, weekday, settingsOf, costOf};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.Planner = api;
})(typeof window !== "undefined" ? window : globalThis);
