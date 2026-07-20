<template>
  <div class="app-wrapper">
    <!-- 动态渐变背景 -->
    <div class="bg-gradient"></div>
    <div class="bg-particles"></div>

    <div class="container">
      <!-- Header -->
      <header class="header">
        <div class="logo-icon">🧳</div>
        <h1>TripPlanner</h1>
        <p class="subtitle">5 Node LangGraph · SSE 实时进度 · 8 维用户画像</p>
      </header>

      <!-- 画像面板 -->
      <div class="glass-card" v-if="!planning">
        <h2 class="card-title"><span class="icon">🧠</span> 用户画像</h2>
        <div v-if="!profile.ready" class="profile-building">
          <div class="counter">{{ profile.trip_count || 0 }} <span class="counter-label">/ 5</span></div>
          <div class="hint">至少规划 5 次行程后显示偏好分析</div>
          <div v-if="profile.trip_count" class="hint-sub">已记录 {{ profile.trip_count }} 次</div>
        </div>
        <div v-else class="profile-grid">
          <div class="pdim" v-for="d in profileDims" :key="d.label">
            <div class="plabel">{{ d.icon }} {{ d.label }}</div>
            <div class="pval">{{ d.value || '—' }}</div>
          </div>
        </div>
      </div>

      <!-- 降级面板 -->
      <div class="fallback" v-if="errors.length">
        <div class="ftitle">⚠️ 降级提示</div>
        <div class="fitem" v-for="e in errors" :key="e">▸ {{ e }}</div>
      </div>

      <!-- 进度面板 — 带动态流动文字 -->
      <div class="progress-panel" v-if="planning">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progressPct + '%' }">
            <div class="progress-shimmer"></div>
          </div>
        </div>
        <div class="progress-pct">{{ progressPct }}%</div>
        <!-- 流动状态文字 -->
        <div class="flowing-status" :class="{ done: currentStatus.includes('✅') }">
          <span class="status-icon">{{ statusIcon }}</span>
          <span class="status-text">{{ currentStatus }}</span>
          <span class="status-dots" v-if="!currentStatus.includes('✅')">
            <span>.</span><span>.</span><span>.</span>
          </span>
        </div>
        <div class="nodes">
          <span v-for="n in nodes" :key="n.key" :class="['node', nodeStatus[n.key]]">
            <span class="node-icon">{{ n.icon }}</span>
            <span class="node-label">{{ n.label }}</span>
            <span class="node-check" v-if="nodeStatus[n.key] === 'done'">✓</span>
            <span class="node-x" v-if="nodeStatus[n.key] === 'failed'">✗</span>
          </span>
        </div>
      </div>

      <!-- 表单 -->
      <div class="glass-card" v-if="!planning">
        <h2 class="card-title"><span class="icon">📍</span> 规划行程</h2>
        <div class="form-row">
          <div class="fg"><label>出发地</label><input v-model="form.origin" placeholder="如：上海"></div>
          <div class="fg"><label>目的地</label><input v-model="form.city" placeholder="如：北京"></div>
          <div class="fg"><label>日期</label><input type="date" v-model="form.startDate"></div>
          <div class="fg sm"><label>天数</label><select v-model.number="form.days"><option v-for="d in [1,2,3,5,7]" :key="d" :value="d">{{ d }}天</option></select></div>
        </div>
        <div class="dim-label">🚄 出行方式</div>
        <div class="tags"><span v-for="t in transportModes" :key="t.val" :class="['tag', { active: form.transportMode === t.val }]" @click="form.transportMode = t.val">{{ t.icon }} {{ t.label }}</span></div>
        <div class="dim-label">🎯 景点偏好</div>
        <div class="tags"><span v-for="t in interests" :key="t.val" :class="['tag', { active: form.prefs.includes(t.val) }]" @click="toggle(t.val)">{{ t.icon }} {{ t.label }}</span></div>
        <div class="dim-label">🍽 饮食</div>
        <div class="tags"><span v-for="t in diets" :key="t.val" :class="['tag', { active: form.prefs.includes(t.val) }]" @click="toggle(t.val)">{{ t.icon }} {{ t.label }}</span></div>
        <div class="dim-label">🚇 交通</div>
        <div class="tags"><span v-for="t in transports" :key="t.val" :class="['tag', { active: form.prefs.includes(t.val) }]" @click="toggle(t.val)">{{ t.icon }} {{ t.label }}</span></div>
        <div class="dim-label">⏱ 节奏</div>
        <div class="tags"><span v-for="t in paces" :key="t.val" :class="['tag', { active: form.prefs.includes(t.val) }]" @click="toggle(t.val)">{{ t.icon }} {{ t.label }}</span></div>
        <div class="dim-label">🏨 住宿 / 💵 预算</div>
        <div class="tags">
          <span v-for="t in [...accommodations, ...budgets]" :key="t.val" :class="['tag', { active: form.prefs.includes(t.val) }]" @click="toggle(t.val)">{{ t.icon }} {{ t.label }}</span>
        </div>
        <button class="btn" @click="startPlan" :disabled="!form.city">
          <span class="btn-icon">🚀</span> 生成计划
        </button>
      </div>

      <!-- 结果 -->
      <div v-if="result" class="results-fade-in">
        <div class="glass-card">
          <h2 class="card-title"><span class="icon">🗺</span> {{ result.city }}</h2>
          <div class="ic" v-if="result.intercity">🚄 {{ result.intercity.mode }} · {{ result.intercity.distance_km }}km · ¥{{ result.intercity.estimated_cost }}</div>
          <div class="meta">📅 {{ result.start_date }} 起 · {{ result.days.length }} 天 · <span class="total">¥{{ (result.budget||{}).total || 0 }}</span></div>
          <div class="budget-bar" v-if="(result.budget||{}).total">
            <div v-for="(c,k) in budgetColors" :key="k" :style="{ width: ((result.budget||{})[k]||0)/(result.budget||{}).total*100 + '%', background: c }"></div>
          </div>
          <div class="blegend">
            <span v-for="(label,k) in budgetLabels" :key="k"><span class="dot" :style="{ background: budgetColors[k] }"></span>{{ label }} ¥{{ (result.budget||{})[k]||0 }}</span>
          </div>
        </div>
        <div class="glass-card" v-if="result.weather_info?.length">
          <h2 class="card-title"><span class="icon">🌡</span> 天气</h2>
          <div class="weather">
            <div class="wday" v-for="w in result.weather_info.slice(0,7)" :key="w.date">
              <div class="wdate">{{ w.date }}</div>
              <div class="wicon">{{ weatherIcons[w.day_weather] || '🌤' }}</div>
              <div class="wtemp">{{ w.day_temp }}°</div>
              <div class="wdesc">{{ w.day_weather }}</div>
            </div>
          </div>
        </div>
        <div class="glass-card day-card" v-for="(d,i) in result.days" :key="i">
          <h2 class="card-title"><span class="icon">📅</span> 第{{ i+1 }}天 — {{ d.date }}</h2>
          <p class="desc">{{ d.description }}</p>
          <div class="item" v-if="d.hotel">🏨 <strong>{{ d.hotel.name }}</strong> · {{ d.hotel.price_range }} · ¥{{ d.hotel.estimated_cost }}</div>
          <div class="item" v-for="a in d.attractions" :key="a.name">🏛 {{ a.name }} <span class="hint">{{ a.description?.slice(0,30) }}</span></div>
          <div class="item" v-for="m in d.meals" :key="m.name">🍽 {{ m.name }} <span class="hint">¥{{ m.estimated_cost }}</span></div>
        </div>
        <div class="glass-card" v-if="result.overall_suggestions">
          <h2 class="card-title"><span class="icon">💡</span> 建议</h2>
          <div class="sugg" v-html="result.overall_suggestions.replace(/\n/g,'<br>')"></div>
        </div>
      </div>

      <!-- Footer -->
      <footer class="footer">
        <p>TripPlanner · Multi-Agent Travel Planning System</p>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'

const API = 'http://localhost:8000'
const form = reactive({ origin: '上海', city: '北京', startDate: '', days: 3, prefs: [], transportMode: '高铁' })
const planning = ref(false), result = ref(null), errors = ref([]), progressPct = ref(0)
const profile = ref({ ready: false, trip_count: 0 })
const currentStatus = ref('')

const nodes = [
  { key: 'attraction', icon: '📍', label: '景点搜索' },
  { key: 'weather', icon: '🌤', label: '天气查询' },
  { key: 'hotel', icon: '🏨', label: '酒店搜索' },
  { key: 'memory', icon: '🧠', label: '画像加载' },
  { key: 'planner', icon: '📋', label: '行程规划' },
]
const nodeStatus = reactive(Object.fromEntries(nodes.map(n => [n.key, 'pending'])))

// 状态文字映射
const statusMessages = {
  attraction: { start: '📍 正在搜索景点信息...', done: '✅ 景点搜索完成' },
  weather: { start: '🌤 正在查询天气数据...', done: '✅ 天气查询完成' },
  hotel: { start: '🏨 正在搜索酒店信息...', done: '✅ 酒店搜索完成' },
  memory: { start: '🧠 正在加载用户画像...', done: '✅ 画像加载完成' },
  planner: { start: '📋 正在生成旅行计划...', done: '✅ 行程规划完成' },
}

const statusIcon = computed(() => {
  if (currentStatus.value.includes('✅')) return ''
  for (const n of nodes) {
    if (nodeStatus[n.key] === 'active') return n.icon
  }
  return '⏳'
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

function toggle(v) { const i = form.prefs.indexOf(v); i >= 0 ? form.prefs.splice(i, 1) : form.prefs.push(v) }

onMounted(async () => {
  form.startDate = new Date().toISOString().slice(0, 10)
  try { const r = await fetch(`${API}/api/profile`); profile.value = await r.json() } catch {}
})

async function startPlan() {
  planning.value = true; result.value = null; errors.value = []; progressPct.value = 0
  currentStatus.value = '⏳ 正在连接服务...'
  Object.keys(nodeStatus).forEach(k => nodeStatus[k] = 'pending')
  const params = new URLSearchParams({ city: form.city, days: form.days, origin: form.origin, start_date: form.startDate, transport_mode: form.transportMode, preferences: form.prefs.join(',') })
  const es = new EventSource(`${API}/api/trip/stream?${params}`)
  es.onmessage = (e) => {
    const d = JSON.parse(e.data)
    if (d.node === 'connected') {
      currentStatus.value = '🔌 已连接，开始规划...'
    }
    else if (d.status === 'start') {
      nodeStatus[d.node] = 'active'
      currentStatus.value = statusMessages[d.node]?.start || `${d.node} 进行中...`
      progressPct.value = (nodes.findIndex(n => n.key === d.node) / nodes.length) * 70
    }
    else if (d.status === 'done' && d.node !== 'done') {
      nodeStatus[d.node] = d.data?.status === 'failed' ? 'failed' : 'done'
      currentStatus.value = statusMessages[d.node]?.done || `${d.node} 完成`
      progressPct.value = ((nodes.findIndex(n => n.key === d.node) + 1) / nodes.length) * 70
    }
    else if (d.status === 'complete') {
      result.value = d.data; errors.value = d.data.errors || []
      progressPct.value = 100; currentStatus.value = '🎉 行程规划完成！'
      setTimeout(() => { planning.value = false }, 800)
      es.close(); loadProfile()
    }
    else if (d.status === 'error') {
      errors.value = [d.data?.message || '未知错误']
      currentStatus.value = '❌ 发生错误'
      planning.value = false; es.close()
    }
  }
  es.onerror = () => {
    if (planning.value) { errors.value = ['SSE 连接中断']; currentStatus.value = '❌ 连接中断' }
    planning.value = false; es.close()
  }
}

async function loadProfile() { try { const r = await fetch(`${API}/api/profile`); profile.value = await r.json() } catch {} }

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
/* ===== 全局重置与基础 ===== */
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  color: #e8e8ed;
  min-height: 100vh;
  overflow-x: hidden;
}

/* ===== 动态渐变背景 ===== */
.app-wrapper {
  position: relative;
  min-height: 100vh;
  background: #0a0a16;
  overflow: hidden;
}

.bg-gradient {
  position: fixed;
  inset: 0;
  z-index: 0;
  background:
    radial-gradient(ellipse 80% 60% at 20% 0%, rgba(124, 58, 237, 0.15), transparent 60%),
    radial-gradient(ellipse 70% 50% at 80% 50%, rgba(59, 130, 246, 0.12), transparent 60%),
    radial-gradient(ellipse 60% 50% at 50% 100%, rgba(16, 185, 129, 0.08), transparent 60%);
  animation: bgShift 15s ease-in-out infinite alternate;
}

@keyframes bgShift {
  0% { transform: scale(1) rotate(0deg); }
  100% { transform: scale(1.1) rotate(1deg); }
}

.bg-particles {
  position: fixed;
  inset: 0;
  z-index: 0;
  opacity: 0.3;
  background-image:
    radial-gradient(2px 2px at 20% 30%, rgba(124, 58, 237, 0.3), transparent),
    radial-gradient(2px 2px at 50% 70%, rgba(59, 130, 246, 0.3), transparent),
    radial-gradient(1px 1px at 80% 20%, rgba(16, 185, 129, 0.3), transparent),
    radial-gradient(2px 2px at 35% 85%, rgba(59, 130, 246, 0.2), transparent),
    radial-gradient(1px 1px at 65% 45%, rgba(124, 58, 237, 0.2), transparent),
    radial-gradient(2px 2px at 10% 60%, rgba(245, 158, 11, 0.2), transparent),
    radial-gradient(1px 1px at 90% 80%, rgba(16, 185, 129, 0.2), transparent);
}

/* ===== 主容器 ===== */
.container {
  position: relative;
  z-index: 1;
  max-width: 800px;
  margin: 0 auto;
  padding: 20px 24px 60px;
}

/* ===== Header ===== */
.header {
  text-align: center;
  padding: 40px 0 10px;
}

.logo-icon {
  font-size: 52px;
  filter: drop-shadow(0 4px 12px rgba(124, 58, 237, 0.4));
  animation: float 3s ease-in-out infinite;
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}

h1 {
  font-size: 36px;
  font-weight: 800;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, #a78bfa 0%, #7c3aed 30%, #3b82f6 70%, #10b981 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 8px 0 4px;
}

.subtitle {
  font-size: 13px;
  color: #6b7280;
  letter-spacing: 0.5px;
}

/* ===== 毛玻璃卡片 ===== */
.glass-card {
  background: rgba(26, 26, 46, 0.6);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 24px 28px;
  margin-bottom: 16px;
  box-shadow:
    0 4px 24px rgba(0, 0, 0, 0.3),
    0 1px 2px rgba(255, 255, 255, 0.04) inset;
  transition: all 0.3s ease;
}

.glass-card:hover {
  border-color: rgba(124, 58, 237, 0.2);
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.4),
    0 1px 2px rgba(255, 255, 255, 0.06) inset;
}

.card-title {
  font-size: 17px;
  font-weight: 700;
  margin-bottom: 14px;
  color: #e8e8ed;
}

.card-title .icon {
  margin-right: 6px;
}

/* ===== 表单 ===== */
.form-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.fg { flex: 1; min-width: 100px; } .fg.sm { flex: 0 0 80px; }
.fg label {
  display: block;
  font-size: 12px;
  color: #9ca3af;
  margin-bottom: 5px;
  font-weight: 500;
  letter-spacing: 0.3px;
}
.fg input, .fg select {
  width: 100%;
  padding: 11px 14px;
  background: rgba(15, 15, 26, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  color: #e8e8ed;
  font-size: 14px;
  transition: all 0.2s ease;
  outline: none;
}
.fg input:focus, .fg select:focus {
  border-color: rgba(124, 58, 237, 0.5);
  box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.1);
}
.fg input::placeholder { color: #4b5563; }

.dim-label {
  font-size: 12px;
  color: #9ca3af;
  margin: 14px 0 8px;
  font-weight: 500;
  letter-spacing: 0.3px;
}

.tags { display: flex; gap: 8px; flex-wrap: wrap; }
.tag {
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(15, 15, 26, 0.6);
  color: #9ca3af;
  user-select: none;
  transition: all 0.2s ease;
  font-weight: 500;
}
.tag:hover {
  border-color: rgba(124, 58, 237, 0.3);
  color: #c4b5fd;
}
.tag.active {
  background: linear-gradient(135deg, #7c3aed, #6d28d9);
  color: #fff;
  border-color: #7c3aed;
  box-shadow: 0 2px 8px rgba(124, 58, 237, 0.3);
}

.btn {
  width: 100%;
  padding: 15px;
  background: linear-gradient(135deg, #7c3aed, #3b82f6);
  border: none;
  border-radius: 12px;
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  margin-top: 18px;
  transition: all 0.3s ease;
  box-shadow: 0 4px 16px rgba(124, 58, 237, 0.3);
  letter-spacing: 0.5px;
}
.btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 24px rgba(124, 58, 237, 0.4);
}
.btn:active:not(:disabled) {
  transform: translateY(0);
}
.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}
.btn-icon { margin-right: 4px; }

/* ===== 进度面板 ===== */
.progress-panel {
  margin-bottom: 24px;
  background: rgba(26, 26, 46, 0.5);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 24px 28px;
}

.progress-bar {
  height: 8px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #7c3aed, #3b82f6, #10b981);
  background-size: 200% 100%;
  border-radius: 4px;
  transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  animation: gradientFlow 2s ease-in-out infinite;
}

.progress-shimmer {
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.15), transparent);
  animation: shimmer 1.5s ease-in-out infinite;
}

@keyframes gradientFlow {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(200%); }
}

.progress-pct {
  font-size: 13px;
  color: #9ca3af;
  text-align: right;
  margin-bottom: 8px;
  font-weight: 600;
}

/* ===== 流动状态文字 ===== */
.flowing-status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 20px;
  margin: 12px 0 16px;
  background: rgba(124, 58, 237, 0.08);
  border: 1px solid rgba(124, 58, 237, 0.15);
  border-radius: 12px;
  font-size: 15px;
  font-weight: 600;
  color: #c4b5fd;
  transition: all 0.5s ease;
}

.flowing-status.done {
  background: rgba(16, 185, 129, 0.08);
  border-color: rgba(16, 185, 129, 0.2);
  color: #6ee7b7;
}

.status-icon {
  font-size: 20px;
}

.status-text {
  letter-spacing: 0.3px;
}

/* 流动省略号动画 */
.status-dots span {
  animation: dotPulse 1.4s infinite;
  font-weight: bold;
  font-size: 20px;
  line-height: 0;
}
.status-dots span:nth-child(2) { animation-delay: 0.2s; }
.status-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dotPulse {
  0%, 20% { opacity: 0; }
  50% { opacity: 1; }
  100% { opacity: 0; }
}

/* ===== 节点状态列表 ===== */
.nodes {
  display: flex;
  justify-content: space-between;
  gap: 4px;
}

.node {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #4b5563;
  padding: 6px 10px;
  border-radius: 8px;
  background: rgba(15, 15, 26, 0.4);
  transition: all 0.3s ease;
  white-space: nowrap;
}

.node.active {
  color: #a78bfa;
  background: rgba(124, 58, 237, 0.1);
  box-shadow: 0 0 12px rgba(124, 58, 237, 0.15);
  animation: pulseGlow 2s ease-in-out infinite;
}

.node.done {
  color: #6ee7b7;
  background: rgba(16, 185, 129, 0.08);
}

.node.failed {
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.08);
}

.node-icon { font-size: 14px; }
.node-check { color: #34d399; font-weight: bold; margin-left: 2px; }
.node-x { color: #f87171; font-weight: bold; margin-left: 2px; }

@keyframes pulseGlow {
  0%, 100% { box-shadow: 0 0 8px rgba(124, 58, 237, 0.1); }
  50% { box-shadow: 0 0 16px rgba(124, 58, 237, 0.25); }
}

/* ===== 画像面板 ===== */
.profile-building {
  text-align: center;
  padding: 20px;
  color: #9ca3af;
}

.counter {
  font-size: 42px;
  font-weight: 800;
  background: linear-gradient(135deg, #a78bfa, #7c3aed);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 10px 0;
}

.counter-label {
  font-size: 20px;
  color: #6b7280;
}

.hint { font-size: 13px; color: #6b7280; margin-top: 6px; }
.hint-sub { font-size: 12px; color: #a78bfa; margin-top: 6px; }

.profile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px;
}

.pdim {
  background: rgba(15, 15, 26, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 10px;
  padding: 12px;
  transition: all 0.2s ease;
}
.pdim:hover {
  border-color: rgba(124, 58, 237, 0.15);
  background: rgba(15, 15, 26, 0.8);
}

.plabel { font-size: 11px; color: #6b7280; margin-bottom: 5px; }
.pval { font-size: 13px; color: #c4b5fd; font-weight: 600; }

/* ===== 降级面板 ===== */
.fallback {
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 16px;
  backdrop-filter: blur(20px);
}
.ftitle { font-weight: 700; color: #fbbf24; margin-bottom: 8px; font-size: 14px; }
.fitem { font-size: 13px; color: #fde68a; padding: 3px 0; }

/* ===== 结果卡片 ===== */
.results-fade-in {
  animation: fadeInUp 0.5s ease-out;
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.ic {
  font-size: 13px;
  color: #c4b5fd;
  margin: 8px 0;
  padding: 8px 14px;
  background: rgba(124, 58, 237, 0.06);
  border: 1px solid rgba(124, 58, 237, 0.1);
  border-radius: 8px;
}

.meta { font-size: 13px; color: #9ca3af; margin-top: 6px; }
.total {
  font-size: 20px;
  font-weight: 800;
  background: linear-gradient(135deg, #34d399, #10b981);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.budget-bar {
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  margin: 10px 0;
}
.budget-bar div {
  transition: width 0.6s ease;
}

.blegend {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #9ca3af;
  flex-wrap: wrap;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  margin-right: 5px;
}

.weather { display: flex; gap: 10px; flex-wrap: wrap; }
.wday {
  background: rgba(15, 15, 26, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.05);
  padding: 12px 14px;
  border-radius: 10px;
  text-align: center;
  min-width: 85px;
  transition: all 0.2s ease;
}
.wday:hover {
  border-color: rgba(59, 130, 246, 0.2);
  background: rgba(15, 15, 26, 0.8);
}
.wdate { font-size: 11px; color: #6b7280; }
.wicon { font-size: 28px; margin: 6px 0; }
.wtemp { font-size: 15px; font-weight: 700; color: #e8e8ed; }
.wdesc { font-size: 11px; color: #9ca3af; margin-top: 2px; }

.day-card {
  border-left: 3px solid #7c3aed !important;
}

.desc { font-size: 14px; color: #d1d5db; margin-bottom: 12px; line-height: 1.6; }

.item {
  padding: 6px 0;
  font-size: 14px;
  color: #d1d5db;
}
.item .hint {
  color: #6b7280;
  font-size: 12px;
}

.sugg {
  font-size: 14px;
  color: #d1d5db;
  line-height: 1.9;
  padding: 14px;
  background: rgba(15, 15, 26, 0.6);
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.04);
}

/* ===== Footer ===== */
.footer {
  text-align: center;
  padding: 30px 0 20px;
  color: #374151;
  font-size: 12px;
  letter-spacing: 0.5px;
}
</style>
