<template>
  <div class="app-bg" @mousemove="onMouseMove">
    <!-- 鼠标追踪光晕（顶层，pointer-events:none） -->
    <div class="cursor-spotlight" :style="{ '--mx': mouseX + 'px', '--my': mouseY + 'px' }"></div>

    <!-- 星空粒子层 -->
    <div class="stars">
      <span v-for="i in 40" :key="i" class="star" :style="starStyle(i)"></span>
    </div>

    <!-- 浮动色斑 -->
    <div class="bg-blob bg-blob-1"></div>
    <div class="bg-blob bg-blob-2"></div>
    <div class="bg-blob bg-blob-3"></div>

    <div class="container">
      <header class="hero">
        <h1 class="gradient-text">🧳 TripPlanner</h1>
        <p class="subtitle">
          <span class="dot-live"></span>
          5 Node LangGraph · 实时进度 · 8 维用户画像
        </p>
      </header>

      <!-- 画像面板 -->
      <Transition name="card">
        <section class="glass-card tilt" v-if="!planning" data-tilt @mousemove="onTilt" @mouseleave="offTilt">
          <h2><span class="h2-icon">🧠</span> 用户画像</h2>
          <div v-if="!profile.ready" class="profile-building">
            <div class="counter shimmer-num">{{ profile.trip_count || 0 }} <span class="slash">/</span> 5</div>
            <div class="hint">至少规划 5 次行程后显示偏好分析</div>
            <div v-if="profile.trip_count" class="hint-sub">已记录 {{ profile.trip_count }} 次</div>
            <div class="mini-progress">
              <div class="mini-fill" :style="{ width: Math.min((profile.trip_count||0)/5*100, 100) + '%' }"></div>
            </div>
          </div>
          <TransitionGroup v-else name="stagger" tag="div" class="profile-grid">
            <div class="pdim" v-for="(d, idx) in profileDims" :key="d.label" :style="{ '--delay': (idx*40) + 'ms' }">
              <div class="plabel">{{ d.icon }} {{ d.label }}</div>
              <div class="pval">{{ d.value || '—' }}</div>
            </div>
          </TransitionGroup>
        </section>
      </Transition>

      <!-- 降级面板 -->
      <Transition name="card">
        <div class="fallback" v-if="errors.length">
          <div class="ftitle"><span class="warn-dot"></span> 降级提示</div>
          <div class="fitem" v-for="(e, i) in errors" :key="e" :style="{ '--delay': (i*60)+'ms' }">▸ {{ e }}</div>
        </div>
      </Transition>

      <!-- 进度面板 -->
      <Transition name="card">
        <div class="progress-panel" v-if="planning">
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
            <div class="progress-glow" :style="{ left: progressPct + '%' }"></div>
          </div>
          <div class="flow-messages">
            <TransitionGroup name="flow-msg">
              <div v-for="msg in progressMessages" :key="msg.id"
                   :class="['flow-msg', msg.state]">
                <span class="msg-icon" v-if="msg.state === 'active'">
                  <span class="pulse-dot"></span>
                </span>
                <span class="msg-icon" v-else-if="msg.state === 'done'">
                  <span class="check">✓</span>
                </span>
                <span class="msg-icon" v-else-if="msg.state === 'failed'">⚠️</span>
                <span class="msg-body">{{ msg.text }}</span>
              </div>
            </TransitionGroup>
          </div>
        </div>
      </Transition>

      <!-- 表单 -->
      <Transition name="card">
        <section class="glass-card tilt" v-if="!planning" data-tilt @mousemove="onTilt" @mouseleave="offTilt">
          <h2><span class="h2-icon">📍</span> 规划行程</h2>
          <div class="form-row">
            <div class="fg"><label>出发地</label><input v-model="form.origin" placeholder="上海"></div>
            <div class="fg"><label>目的地</label><input v-model="form.city" placeholder="成都"></div>
            <div class="fg"><label>日期</label><input type="date" v-model="form.startDate"></div>
            <div class="fg sm"><label>天数</label><select v-model.number="form.days"><option v-for="d in [1,2,3,5,7]" :key="d" :value="d">{{ d }}天</option></select></div>
          </div>

          <div class="dim-label">🚄 出行方式</div>
          <div class="tags">
            <span v-for="t in transportModes" :key="t.val"
                  :class="['tag', { active: form.transportMode === t.val }]"
                  @click="pickTransport(t.val, $event)">{{ t.icon }} {{ t.label }}</span>
          </div>

          <div class="dim-label">🎯 景点偏好</div>
          <div class="tags"><span v-for="t in interests" :key="t.val" :class="['tag', { active: form.prefs.includes(t.val) }]" @click="toggle(t.val, $event)">{{ t.icon }} {{ t.label }}</span></div>

          <div class="dim-label">🍽 饮食</div>
          <div class="tags"><span v-for="t in diets" :key="t.val" :class="['tag', { active: form.prefs.includes(t.val) }]" @click="toggle(t.val, $event)">{{ t.icon }} {{ t.label }}</span></div>

          <div class="dim-label">🚇 交通</div>
          <div class="tags"><span v-for="t in transports" :key="t.val" :class="['tag', { active: form.prefs.includes(t.val) }]" @click="toggle(t.val, $event)">{{ t.icon }} {{ t.label }}</span></div>

          <div class="dim-label">⏱ 节奏</div>
          <div class="tags"><span v-for="t in paces" :key="t.val" :class="['tag', { active: form.prefs.includes(t.val) }]" @click="toggle(t.val, $event)">{{ t.icon }} {{ t.label }}</span></div>

          <div class="dim-label">🏨 住宿 / 💵 预算</div>
          <div class="tags">
            <span v-for="t in [...accommodations, ...budgets]" :key="t.val" :class="['tag', { active: form.prefs.includes(t.val) }]" @click="toggle(t.val, $event)">{{ t.icon }} {{ t.label }}</span>
          </div>

          <button class="btn" @click="startPlan" :disabled="!form.city">
            <span class="btn-shine"></span>
            <span class="btn-label">🚀 生成计划</span>
          </button>
        </section>
      </Transition>

      <!-- 结果 -->
      <TransitionGroup v-if="result" name="result-card" tag="div">
        <div class="glass-card tilt result-appear" key="head" :style="{ '--delay': '0ms' }" @mousemove="onTilt" @mouseleave="offTilt">
          <h2><span class="h2-icon">🗺</span> {{ result.city }}</h2>
          <div class="ic" v-if="result.intercity">🚄 {{ result.intercity.mode }} · {{ result.intercity.distance_km }}km · ¥{{ result.intercity.estimated_cost }}</div>
          <div class="meta">📅 {{ result.start_date }} 起 · {{ result.days.length }} 天 · <span class="total">¥<AnimatedNum :value="(result.budget||{}).total || 0" /></span></div>
          <div class="budget-bar" v-if="(result.budget||{}).total">
            <div v-for="(c,k) in budgetColors" :key="k"
                 :style="{ width: barGrown ? ((result.budget||{})[k]||0)/(result.budget||{}).total*100 + '%' : '0%', background: c }"
                 class="bar-seg"></div>
          </div>
          <div class="blegend">
            <span v-for="(label,k) in budgetLabels" :key="k">
              <span class="dot" :style="{ background: budgetColors[k] }"></span>
              {{ label }} ¥<AnimatedNum :value="(result.budget||{})[k]||0" />
            </span>
          </div>
        </div>

        <div class="glass-card tilt result-appear" v-if="result.weather_info?.length" key="weather" :style="{ '--delay': '80ms' }" @mousemove="onTilt" @mouseleave="offTilt">
          <h2><span class="h2-icon">🌡</span> 天气</h2>
          <div class="weather">
            <div class="wday" v-for="(w, i) in result.weather_info.slice(0,7)" :key="w.date" :style="{ '--delay': (i*50)+'ms' }">
              <div class="wdate">{{ w.date }}</div>
              <div class="wicon">{{ weatherIcons[w.day_weather] || '🌤' }}</div>
              <div class="wtemp">{{ w.day_temp }}°</div>
              <div class="wdesc">{{ w.day_weather }}</div>
            </div>
          </div>
        </div>

        <div class="glass-card tilt day-card result-appear" v-for="(d,i) in result.days" :key="'d'+i" :style="{ '--delay': (150 + i*80) + 'ms' }" @mousemove="onTilt" @mouseleave="offTilt">
          <h2><span class="h2-icon">📅</span> 第{{ i+1 }}天 <span class="date-sub">· {{ d.date }}</span></h2>
          <p class="desc">{{ d.description }}</p>
          <div class="item hotel-item" v-if="d.hotel">🏨 <strong>{{ d.hotel.name }}</strong> <span class="hint">{{ d.hotel.price_range }} · ¥{{ d.hotel.estimated_cost }}</span></div>
          <div class="item attr-item" v-for="a in d.attractions" :key="a.name">🏛 {{ a.name }} <span class="hint">{{ a.description }}</span></div>
          <div class="item meal-item" v-for="m in d.meals" :key="m.name">🍽 {{ m.name }} <span class="hint">¥{{ m.estimated_cost }}</span></div>
        </div>

        <div class="glass-card tilt result-appear" v-if="result.overall_suggestions" key="sugg" :style="{ '--delay': (200 + (result.days.length||0)*80) + 'ms' }" @mousemove="onTilt" @mouseleave="offTilt">
          <h2><span class="h2-icon">💡</span> 建议</h2>
          <div class="sugg" v-html="result.overall_suggestions.replace(/\n/g,'<br>')"></div>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, h, defineComponent } from 'vue'

const API = 'http://localhost:8000'
const USER_ID_STORAGE_KEY = "tripplanner.user_id"

function getUserId() {
  let userId = localStorage.getItem(USER_ID_STORAGE_KEY)
  if (!userId) {
    userId = crypto.randomUUID()
    localStorage.setItem(USER_ID_STORAGE_KEY, userId)
  }
  return userId
}

const userId = getUserId()
const form = reactive({ origin: '上海', city: '北京', startDate: '', days: 3, prefs: [], transportMode: '高铁' })
const planning = ref(false), result = ref(null), errors = ref([]), progressPct = ref(0)
const profile = ref({ ready: false, trip_count: 0 })
const barGrown = ref(false)

// ── 鼠标追踪光晕 ──
const mouseX = ref(0), mouseY = ref(0)
function onMouseMove(e) { mouseX.value = e.clientX; mouseY.value = e.clientY }

// ── 3D tilt hover ──
function onTilt(e) {
  const el = e.currentTarget
  const rect = el.getBoundingClientRect()
  const x = (e.clientX - rect.left) / rect.width - 0.5
  const y = (e.clientY - rect.top) / rect.height - 0.5
  el.style.transform = `perspective(1000px) rotateX(${-y*4}deg) rotateY(${x*4}deg) translateZ(0)`
  el.style.setProperty('--mx-local', (e.clientX - rect.left) + 'px')
  el.style.setProperty('--my-local', (e.clientY - rect.top) + 'px')
}
function offTilt(e) {
  const el = e.currentTarget
  el.style.transform = ''
}

// ── 星空位置（组件挂载时一次生成）──
const starSeeds = Array.from({ length: 40 }, () => ({
  top: Math.random() * 100,
  left: Math.random() * 100,
  size: 1 + Math.random() * 2,
  delay: Math.random() * 5,
  dur: 3 + Math.random() * 4,
}))
function starStyle(i) {
  const s = starSeeds[i-1]
  return {
    top: s.top + '%',
    left: s.left + '%',
    width: s.size + 'px',
    height: s.size + 'px',
    animationDelay: s.delay + 's',
    animationDuration: s.dur + 's',
  }
}

// ── 数字 count-up 组件（就地定义，不新建文件）──
const AnimatedNum = defineComponent({
  props: { value: { type: Number, default: 0 }, duration: { type: Number, default: 700 } },
  setup(props) {
    const shown = ref(0)
    let raf
    watch(() => props.value, (v) => {
      const from = shown.value, to = v, start = performance.now()
      const step = (t) => {
        const p = Math.min(1, (t - start) / props.duration)
        // easeOutCubic
        const e = 1 - Math.pow(1 - p, 3)
        shown.value = Math.round(from + (to - from) * e)
        if (p < 1) raf = requestAnimationFrame(step)
      }
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(step)
    }, { immediate: true })
    return () => h('span', { class: 'anum' }, shown.value)
  }
})

// ── 流动文案 ──
const flowState = reactive({
  attraction: 'pending', hotel: 'pending',
  memory: 'pending', planner: 'pending', connected: 'pending'
})

const stageMessages = {
  connected:  { start: (city) => `🔗 正在连接服务器...`, done: null },
  attraction: { start: (city) => `📍 正在搜索${city}的景点...`,  done: (city) => `✅ 景点搜索完成`, failed: (city) => `⚠️ 景点搜索失败，使用降级数据` },
  hotel:      { start: (city) => `🏨 正在搜索${city}酒店...`,  done: (city) => `✅ 酒店搜索完成`, failed: (city) => `⚠️ 酒店搜索失败，使用降级数据` },
  memory:     { start: (city) => `🧠 正在加载用户画像...`,    done: (city) => `✅ 画像加载完成` },
  planner:    { start: (city) => `📋 正在生成${city}旅行计划...`, done: (city) => `🎉 计划生成完毕！` },
}

const progressMessages = computed(() => {
  const city = form.city || '目的地'
  const msgs = []
  const order = ['attraction', 'hotel', 'memory', 'planner']

  for (const node of order) {
    const s = flowState[node]
    if (s === 'active') {
      msgs.push({ id: node + '-active', text: stageMessages[node].start(city), state: 'active' })
      break
    } else if (s === 'done') {
      msgs.push({ id: node + '-done', text: stageMessages[node].done(city), state: 'done' })
    } else if (s === 'failed') {
      msgs.push({ id: node + '-failed', text: stageMessages[node].failed(city), state: 'failed' })
    }
  }

  if (order.every(n => flowState[n] === 'done' || flowState[n] === 'failed')) {
    msgs.push({ id: 'all-done', text: '✨ 所有数据准备就绪！', state: 'done' })
  }

  return msgs
})

const transportModes = [{ val: '高铁', icon: '🚄', label: '高铁' },{ val: '飞机', icon: '✈️', label: '飞机' },{ val: '自驾', icon: '🚗', label: '自驾' }]
const interests = [{ val: '历史文化', icon: '🏛', label: '历史文化' },{ val: '美食', icon: '🍜', label: '美食' },{ val: '自然风光', icon: '🏔', label: '自然风光' },{ val: '购物', icon: '🛍', label: '购物' },{ val: '亲子', icon: '👶', label: '亲子' }]
const diets = [{ val: '不吃辣', icon: '🥬', label: '不吃辣' },{ val: '爱吃辣', icon: '🌶', label: '爱吃辣' },{ val: '清淡', icon: '🥗', label: '清淡' },{ val: '重口味', icon: '🍛', label: '重口味' },{ val: '当地特色', icon: '🏠', label: '当地特色' }]
const transports = [{ val: '地铁优先', icon: '🚇', label: '地铁' },{ val: '打车优先', icon: '🚕', label: '打车' },{ val: '自驾', icon: '🚗', label: '自驾' },{ val: '公共交通', icon: '🚌', label: '公交' }]
const paces = [{ val: '悠闲慢游', icon: '🌿', label: '悠闲' },{ val: '适中', icon: '🚶', label: '适中' },{ val: '紧凑高效', icon: '🏃', label: '紧凑' }]
const accommodations = [{ val: '经济型酒店', icon: '💰', label: '经济型' },{ val: '中端型酒店', icon: '🏨', label: '中端型' },{ val: '高端型酒店', icon: '🏢', label: '高端型' },{ val: '豪华型酒店', icon: '👑', label: '豪华型' }]
const budgets = [{ val: '穷游', icon: '🎒', label: '穷游' },{ val: '经济适用', icon: '💡', label: '经济适用' },{ val: '舒适享受', icon: '✨', label: '舒适' },{ val: '奢华体验', icon: '💎', label: '奢华' }]
const budgetColors = { total_attractions: '#7c3aed', total_hotels: '#3b82f6', total_meals: '#f59e0b', total_transportation: '#10b981' }
const budgetLabels = { total_attractions: '景点', total_hotels: '酒店', total_meals: '餐饮', total_transportation: '交通' }
const weatherIcons = { '晴': '☀️', '多云': '⛅', '阴': '☁️', '雨': '🌧', '雪': '❄️', '雷阵雨': '⛈' }

// tag 点击时触发 pop 动画（重置 class 强制重播）
function toggle(v, e) { const i = form.prefs.indexOf(v); i >= 0 ? form.prefs.splice(i, 1) : form.prefs.push(v); popTag(e) }
function pickTransport(v, e) { form.transportMode = v; popTag(e) }
function popTag(e) {
  const el = e?.currentTarget
  if (!el) return
  el.classList.remove('popped')
  void el.offsetWidth  // 强制重排以重启动画
  el.classList.add('popped')
}

onMounted(async () => {
  const today = new Date();
  form.startDate = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  try { const r = await fetch(`${API}/api/profile?user_id=${encodeURIComponent(userId)}`); profile.value = await r.json() } catch {}
})

const nodeOrder = ['attraction', 'hotel', 'memory', 'planner']
const progressSteps = [15, 35, 55, 70]

async function startPlan() {
  planning.value = true; result.value = null; errors.value = []; progressPct.value = 0
  barGrown.value = false
  Object.keys(flowState).forEach(k => flowState[k] = 'pending')

  const params = new URLSearchParams({
    user_id: userId,
    origin: form.origin,
    city: form.city,
    days: form.days,
    start_date: form.startDate,
    transport_mode: form.transportMode,
    preferences: form.prefs.join(','),
  })

  try {
    const resp = await fetch(`${API}/api/trip/stream?${params}`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`)
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop()  // 最后一个可能是半截，留下
      for (const frame of frames) {
        const line = frame.split('\n').find(l => l.startsWith('data: '))
        if (!line) continue
        let evt
        try { evt = JSON.parse(line.slice(6)) } catch { continue }
        handleStreamEvent(evt)
      }
    }
  } catch (err) {
    nodeOrder.forEach(n => { if (flowState[n] === 'active') flowState[n] = 'failed' })
    errors.value = ['请求失败: ' + err.message]
    planning.value = false
  }
}

function handleStreamEvent(evt) {
  const { node, status, data } = evt
  if (node === 'error' || node === 'cancelled') {
    nodeOrder.forEach(n => { if (flowState[n] === 'active') flowState[n] = 'failed' })
    errors.value.push(data?.message || `${node} 事件`)
    planning.value = false
    return
  }
  if (node === 'done' && status === 'complete') {
    result.value = data
    errors.value = data.errors || []
    progressPct.value = 100
    nodeOrder.forEach(n => { flowState[n] = 'done' })
    setTimeout(() => { planning.value = false }, 800)
    setTimeout(() => { barGrown.value = true }, 1000)
    loadProfile()
    return
  }
  // 节点进度事件：attraction / hotel / memory / planner
  const idx = nodeOrder.indexOf(node)
  if (idx < 0) return
  flowState[node] = status === 'done' ? 'done' : (status === 'failed' ? 'failed' : 'active')
  if (status === 'done' || status === 'failed') progressPct.value = progressSteps[idx]
}

async function loadProfile() { try { const r = await fetch(`${API}/api/profile?user_id=${encodeURIComponent(userId)}`); profile.value = await r.json() } catch {} }

const profileDims = computed(() => {
  const p = profile.value?.profile || {}
  return [
    { icon: '🚄', label: '出行', value: p.intercity_mode },
    { icon: '📏', label: '距离', value: p.distance_pref },
    { icon: '🏨', label: '住宿', value: p.accommodation || p.hotel_tier },
    { icon: '💵', label: '预算', value: p.budget_tier || p.budget_range },
    { icon: '🍽', label: '饮食', value: (p.diet || []).join(' · ') },
    { icon: '🚇', label: '交通', value: (p.transport || []).join(' · ') },
    { icon: '⏱', label: '节奏', value: p.pace },
    { icon: '🎯', label: '兴趣', value: (p.interests || []).join(' · ') },
  ]
})
</script>

<style>
/* ═══════════════════ 全局重置 ═══════════════════ */
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --c-purple: #a78bfa;
  --c-blue: #60a5fa;
  --c-green: #34d399;
  --c-orange: #f59e0b;
  --c-pink: #f472b6;
  --c-bg-1: #0a0a1a;
  --c-bg-2: #120b24;
  --c-bg-3: #0a1628;
  --glass-bg: rgba(255, 255, 255, 0.04);
  --glass-border: rgba(255, 255, 255, 0.08);
}
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  color: #e0e0e0;
  min-height: 100vh;
  overflow-x: hidden;
  font-feature-settings: 'kern', 'liga', 'clig', 'calt';
  -webkit-font-smoothing: antialiased;
}

/* ═══════════════════ 动态背景 ═══════════════════ */
.app-bg {
  min-height: 100vh;
  background:
    radial-gradient(1200px 800px at 20% -10%, rgba(124, 58, 237, 0.15), transparent 60%),
    radial-gradient(1000px 700px at 90% 10%, rgba(59, 130, 246, 0.12), transparent 60%),
    linear-gradient(135deg, var(--c-bg-1) 0%, var(--c-bg-2) 30%, var(--c-bg-3) 60%, #0f0a1a 100%);
  position: relative;
  overflow: hidden;
}

/* 鼠标追踪光晕 */
.cursor-spotlight {
  position: fixed;
  top: 0; left: 0;
  width: 100vw; height: 100vh;
  pointer-events: none;
  z-index: 2;
  background: radial-gradient(320px 320px at var(--mx, -1000px) var(--my, -1000px),
              rgba(167, 139, 250, 0.08), transparent 70%);
  transition: background 60ms linear;
}

/* 星空 */
.stars { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.star {
  position: absolute;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 50%;
  animation: twinkle infinite ease-in-out;
  box-shadow: 0 0 6px rgba(255, 255, 255, 0.4);
}
@keyframes twinkle {
  0%, 100% { opacity: 0.1; transform: scale(0.6); }
  50% { opacity: 0.9; transform: scale(1); }
}

/* 浮动色斑 */
.bg-blob {
  position: fixed;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.18;
  pointer-events: none;
  z-index: 0;
}
.bg-blob-1 { width: 500px; height: 500px; background: #7c3aed; top: -100px; left: -100px; animation: floatBlob 20s ease-in-out infinite; }
.bg-blob-2 { width: 400px; height: 400px; background: #3b82f6; top: 50%; right: -50px; animation: floatBlob 25s ease-in-out infinite reverse; }
.bg-blob-3 { width: 350px; height: 350px; background: var(--c-orange); bottom: -80px; left: 30%; animation: floatBlob 18s ease-in-out infinite 5s; }
@keyframes floatBlob {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -50px) scale(1.1); }
  66% { transform: translate(-20px, 20px) scale(0.9); }
}

/* ═══════════════════ 容器 ═══════════════════ */
.container {
  max-width: 820px;
  margin: 0 auto;
  padding: 30px 20px 60px;
  position: relative;
  z-index: 1;
}

/* Hero */
.hero { text-align: center; padding: 30px 0 24px; }
h1 {
  font-size: 42px;
  font-weight: 800;
  letter-spacing: -0.5px;
  line-height: 1.1;
}
.gradient-text {
  background: linear-gradient(115deg, #a78bfa 0%, #60a5fa 40%, #34d399 70%, #a78bfa 100%);
  background-size: 300% 100%;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  color: transparent;
  animation: gradientShift 8s ease infinite;
  filter: drop-shadow(0 4px 20px rgba(124, 58, 237, 0.25));
}
@keyframes gradientShift {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}
.subtitle {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 13px;
  color: #888;
  margin-top: 10px;
  letter-spacing: 0.5px;
}
.dot-live {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--c-green);
  box-shadow: 0 0 8px var(--c-green);
  animation: pulseGreen 2s ease-in-out infinite;
}
@keyframes pulseGreen {
  0%, 100% { opacity: 0.6; box-shadow: 0 0 4px var(--c-green); }
  50% { opacity: 1; box-shadow: 0 0 12px var(--c-green); }
}

/* ═══════════════════ 毛玻璃卡片 ═══════════════════ */
.glass-card {
  position: relative;
  background: var(--glass-bg);
  backdrop-filter: blur(24px) saturate(140%);
  -webkit-backdrop-filter: blur(24px) saturate(140%);
  border: 1px solid var(--glass-border);
  border-radius: 18px;
  padding: 26px 28px;
  margin-bottom: 18px;
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
  transition: box-shadow 0.35s ease, border-color 0.35s ease, transform 0.15s ease-out;
  overflow: hidden;
}
/* 微反光边框 —— 用伪元素画一层随鼠标移动的高光 */
.glass-card::before {
  content: '';
  position: absolute; inset: 0;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(135deg, rgba(167, 139, 250, 0.3), transparent 40%, transparent 60%, rgba(96, 165, 250, 0.25));
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
          mask-composite: exclude;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.35s ease;
}
.glass-card:hover::before { opacity: 1; }
.glass-card:hover {
  border-color: rgba(167, 139, 250, 0.2);
  box-shadow: 0 16px 48px rgba(124, 58, 237, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.08);
}
/* 卡片内 spotlight 跟随鼠标 */
.tilt::after {
  content: '';
  position: absolute; inset: 0;
  pointer-events: none;
  background: radial-gradient(220px 220px at var(--mx-local, 50%) var(--my-local, 50%), rgba(167, 139, 250, 0.08), transparent 60%);
  opacity: 0;
  transition: opacity 0.3s ease;
  border-radius: inherit;
}
.tilt:hover::after { opacity: 1; }

.glass-card h2 {
  font-size: 15px;
  margin-bottom: 16px;
  color: #c4b5fd;
  font-weight: 600;
  letter-spacing: 0.3px;
  display: flex; align-items: center; gap: 8px;
}
.h2-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 26px; height: 26px;
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.2), rgba(59, 130, 246, 0.15));
  border: 1px solid rgba(167, 139, 250, 0.2);
  font-size: 14px;
}
.date-sub { color: #666; font-weight: 400; margin-left: 4px; font-size: 13px; }

/* ═══════════════════ 表单 ═══════════════════ */
.form-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
.fg { flex: 1; min-width: 90px; }
.fg.sm { flex: 0 0 80px; }
.fg label { display: block; font-size: 10px; color: #666; margin-bottom: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; }
.fg input, .fg select {
  width: 100%; padding: 10px 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  color: #e0e0e0;
  font-size: 14px;
  font-family: inherit;
  transition: all 0.25s ease;
}
.fg input::placeholder { color: #555; }
.fg input:focus, .fg select:focus {
  outline: none;
  border-color: rgba(167, 139, 250, 0.5);
  background: rgba(255, 255, 255, 0.05);
  box-shadow: 0 0 0 4px rgba(124, 58, 237, 0.15), 0 4px 20px rgba(124, 58, 237, 0.1);
}

.dim-label {
  font-size: 10px; color: #666;
  margin: 18px 0 8px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
}
.tags { display: flex; gap: 6px; flex-wrap: wrap; }
.tag {
  padding: 7px 14px;
  border-radius: 20px;
  font-size: 12px;
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #999;
  user-select: none;
  transition: color 0.2s, border-color 0.2s, background 0.2s, box-shadow 0.2s;
  backdrop-filter: blur(4px);
}
.tag:hover {
  border-color: rgba(167, 139, 250, 0.35);
  color: #ccc;
  background: rgba(255, 255, 255, 0.05);
}
.tag.active {
  background: linear-gradient(135deg, #7c3aed, #6d28d9);
  color: #fff;
  border-color: #7c3aed;
  box-shadow: 0 4px 14px rgba(124, 58, 237, 0.35), 0 0 0 1px rgba(255,255,255,0.05) inset;
}
.tag.popped { animation: popTag 380ms cubic-bezier(0.34, 1.56, 0.64, 1); }
@keyframes popTag {
  0% { transform: scale(1); }
  40% { transform: scale(1.14); }
  70% { transform: scale(0.96); }
  100% { transform: scale(1); }
}

/* ═══════════════════ 按钮（带 shine 扫光） ═══════════════════ */
.btn {
  position: relative;
  width: 100%;
  padding: 14px;
  background: linear-gradient(135deg, #7c3aed, #3b82f6);
  border: none; border-radius: 12px;
  color: #fff; font-size: 15px; font-weight: 600;
  cursor: pointer; margin-top: 20px;
  transition: transform 0.15s ease, box-shadow 0.3s ease;
  letter-spacing: 0.5px;
  overflow: hidden;
  box-shadow: 0 4px 20px rgba(124, 58, 237, 0.25);
}
.btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 10px 30px rgba(124, 58, 237, 0.4);
}
.btn:active:not(:disabled) { transform: translateY(0) scale(0.99); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-label { position: relative; z-index: 2; }
.btn-shine {
  position: absolute; top: 0; left: -100%;
  width: 60%; height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.35), transparent);
  transform: skewX(-20deg);
  pointer-events: none;
}
.btn:hover:not(:disabled) .btn-shine { animation: shine 1.1s ease-out; }
@keyframes shine {
  0% { left: -100%; }
  100% { left: 130%; }
}

/* ═══════════════════ 进度面板 ═══════════════════ */
.progress-panel { margin-bottom: 30px; }
.progress-bar {
  position: relative;
  height: 6px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 20px;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #7c3aed, #3b82f6, #34d399);
  background-size: 200% 100%;
  animation: progressShimmer 2s ease-in-out infinite;
  border-radius: 3px;
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 0 10px rgba(124, 58, 237, 0.5);
}
.progress-glow {
  position: absolute; top: 50%;
  width: 20px; height: 20px;
  background: radial-gradient(circle, rgba(255,255,255,0.8), transparent 70%);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  transition: left 0.6s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}
@keyframes progressShimmer {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

.flow-messages { display: flex; flex-direction: column; gap: 8px; }
.flow-msg {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 18px;
  border-radius: 12px;
  font-size: 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  transition: all 0.4s ease;
}
.flow-msg.active {
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.14), rgba(59, 130, 246, 0.08));
  border-color: rgba(167, 139, 250, 0.3);
  box-shadow: 0 0 24px rgba(124, 58, 237, 0.12);
}
.flow-msg.done { color: #86efac; }
.flow-msg.done .check {
  display: inline-block;
  color: var(--c-green);
  font-weight: 700;
  animation: checkPop 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes checkPop {
  0% { transform: scale(0) rotate(-30deg); opacity: 0; }
  100% { transform: scale(1) rotate(0); opacity: 1; }
}
.flow-msg.failed { color: #f87171; background: rgba(248, 113, 113, 0.08); border-color: rgba(248, 113, 113, 0.2); }
.msg-icon { flex-shrink: 0; width: 20px; display: flex; align-items: center; justify-content: center; font-size: 14px; }
.pulse-dot {
  width: 10px; height: 10px;
  background: #a78bfa;
  border-radius: 50%;
  display: inline-block;
  animation: pulseRing 1.5s ease-in-out infinite;
}
@keyframes pulseRing {
  0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(167, 139, 250, 0.5); }
  50% { transform: scale(1.25); box-shadow: 0 0 0 10px rgba(167, 139, 250, 0); }
}
.msg-body { flex: 1; line-height: 1.4; }

/* Vue Transition — 流动文案 */
.flow-msg-enter-active { transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1); }
.flow-msg-leave-active { transition: all 0.3s ease-in; }
.flow-msg-enter-from { opacity: 0; transform: translateY(-10px); }
.flow-msg-leave-to { opacity: 0; transform: translateX(20px); }

/* ═══════════════════ 画像 ═══════════════════ */
.profile-building { text-align: center; padding: 20px 10px 14px; color: #888; }
.counter {
  font-size: 44px;
  background: linear-gradient(135deg, #7c3aed, #3b82f6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  font-weight: 800;
  margin: 8px 0;
  letter-spacing: -1px;
}
.shimmer-num {
  background: linear-gradient(135deg, #a78bfa, #60a5fa, #34d399, #a78bfa);
  background-size: 300% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: gradientShift 4s ease infinite;
}
.slash { color: #444; font-weight: 300; margin: 0 4px; }
.hint { font-size: 13px; }
.hint-sub { font-size: 12px; color: #a78bfa; margin-top: 6px; }
.mini-progress {
  height: 3px; background: rgba(255,255,255,0.06);
  border-radius: 2px; margin: 14px auto 0; max-width: 200px; overflow: hidden;
}
.mini-fill {
  height: 100%;
  background: linear-gradient(90deg, #7c3aed, #3b82f6);
  border-radius: 2px;
  transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 0 8px rgba(124, 58, 237, 0.4);
}
.profile-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }
.pdim {
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px; padding: 12px 14px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  transition: background 0.2s, border-color 0.2s, transform 0.2s;
}
.pdim:hover {
  background: rgba(124, 58, 237, 0.06);
  border-color: rgba(167, 139, 250, 0.2);
  transform: translateY(-1px);
}
.plabel { font-size: 11px; color: #777; margin-bottom: 4px; }
.pval { font-size: 13px; color: #c4b5fd; font-weight: 600; }

/* stagger 入场（画像 grid、结果卡片） */
.stagger-enter-active, .result-card-enter-active { transition: opacity 0.5s cubic-bezier(0.4, 0, 0.2, 1), transform 0.5s cubic-bezier(0.4, 0, 0.2, 1); }
.stagger-enter-from, .result-card-enter-from { opacity: 0; transform: translateY(16px); }

/* ═══════════════════ 降级面板 ═══════════════════ */
.fallback {
  background: rgba(255, 165, 0, 0.06);
  border: 1px solid rgba(255, 165, 0, 0.22);
  border-radius: 12px; padding: 14px 18px; margin-bottom: 16px;
  backdrop-filter: blur(10px);
}
.ftitle {
  font-weight: 600; color: #ffb84d; margin-bottom: 6px;
  display: flex; align-items: center; gap: 8px;
}
.warn-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #ffb84d;
  animation: pulseGreen 1.6s ease-in-out infinite;
  box-shadow: 0 0 6px #ffb84d;
}
.fitem {
  font-size: 12px; color: #e0c080; padding: 2px 0;
  animation: fadeInUp 0.4s ease-out both;
  animation-delay: var(--delay, 0ms);
}
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ═══════════════════ 结果卡片 ═══════════════════ */
.result-appear {
  animation: slideUp 0.5s cubic-bezier(0.4, 0, 0.2, 1) both;
  animation-delay: var(--delay, 0ms);
}
@keyframes slideUp {
  from { opacity: 0; transform: translateY(24px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.ic {
  font-size: 13px; color: #c4b5fd; margin: 6px 0;
  padding: 10px 14px;
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.08), rgba(59, 130, 246, 0.06));
  border-radius: 10px;
  border: 1px solid rgba(167, 139, 250, 0.15);
}
.meta { font-size: 13px; color: #888; margin-top: 8px; }
.total {
  font-size: 22px;
  font-weight: 800;
  background: linear-gradient(135deg, #34d399, #10b981);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-variant-numeric: tabular-nums;
}
.anum { font-variant-numeric: tabular-nums; }

.budget-bar {
  display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin: 12px 0;
  background: rgba(255,255,255,0.04);
  box-shadow: inset 0 1px 3px rgba(0,0,0,0.3);
}
.bar-seg {
  height: 100%;
  transition: width 1.1s cubic-bezier(0.65, 0, 0.35, 1);
  box-shadow: inset 0 0 8px rgba(255,255,255,0.15);
}
.blegend { display: flex; gap: 16px; font-size: 12px; color: #999; flex-wrap: wrap; margin-top: 4px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; box-shadow: 0 0 6px currentColor; }

/* 天气 */
.weather { display: flex; gap: 10px; flex-wrap: wrap; }
.wday {
  background: rgba(255, 255, 255, 0.03);
  padding: 12px 14px;
  border-radius: 12px;
  text-align: center;
  min-width: 82px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  transition: transform 0.25s ease, border-color 0.25s, background 0.25s;
  animation: fadeInUp 0.45s ease-out both;
  animation-delay: var(--delay, 0ms);
}
.wday:hover {
  transform: translateY(-3px);
  border-color: rgba(167, 139, 250, 0.25);
  background: rgba(124, 58, 237, 0.06);
}
.wdate { font-size: 11px; color: #888; }
.wicon { font-size: 28px; margin: 4px 0; filter: drop-shadow(0 2px 6px rgba(0,0,0,0.3)); }
.wtemp { font-size: 15px; font-weight: 700; color: #e0e0e0; font-variant-numeric: tabular-nums; }
.wdesc { font-size: 11px; color: #aaa; }

/* 每日行程卡 */
.day-card {
  border-left: 3px solid transparent;
  background:
    linear-gradient(var(--glass-bg), var(--glass-bg)) padding-box,
    linear-gradient(180deg, #7c3aed, #3b82f6) border-box;
  border: 1px solid transparent;
  border-left: 3px solid #7c3aed;
}
.desc { font-size: 13px; color: #aaa; margin-bottom: 12px; line-height: 1.6; }
.item {
  padding: 7px 12px;
  font-size: 13px;
  border-radius: 8px;
  margin: 3px 0;
  transition: background 0.2s, transform 0.2s;
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.item:hover { background: rgba(255,255,255,0.03); transform: translateX(3px); }
.item .hint { color: #888; font-size: 12px; margin-left: 4px; }
.hotel-item { border-left: 2px solid #3b82f6; }
.attr-item { border-left: 2px solid #7c3aed; }
.meal-item { border-left: 2px solid #f59e0b; }

.sugg {
  font-size: 13px; color: #b8b8b8;
  line-height: 1.8;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

/* ═══════════════════ 卡片入场 Transition ═══════════════════ */
.card-enter-active { transition: opacity 0.45s ease-out, transform 0.45s cubic-bezier(0.4, 0, 0.2, 1); }
.card-leave-active { transition: opacity 0.3s ease-in, transform 0.3s ease-in; }
.card-enter-from { opacity: 0; transform: translateY(20px) scale(0.98); }
.card-leave-to { opacity: 0; transform: translateY(-10px) scale(0.98); }

/* ═══════════════════ 响应式 ═══════════════════ */
@media (max-width: 640px) {
  h1 { font-size: 32px; }
  .container { padding: 20px 14px 40px; }
  .glass-card { padding: 20px 18px; border-radius: 14px; }
  .weather { gap: 6px; }
  .wday { min-width: 68px; padding: 10px; }
  .cursor-spotlight { display: none; }
}

/* 减弱动效 —— 尊重系统设置 */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  .bg-blob { animation: none; }
  .gradient-text { animation: none; }
}
</style>
