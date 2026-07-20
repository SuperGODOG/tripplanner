<template>
  <div class="container">
    <h1>🧳 TripPlanner</h1>
    <p class="subtitle">5 Node LangGraph · SSE 实时进度 · 8 维用户画像</p>

    <!-- 画像面板 -->
    <div class="card" v-if="!planning">
      <h2>🧠 用户画像</h2>
      <div v-if="!profile.ready" class="profile-building">
        <div class="counter">{{ profile.trip_count || 0 }} / 5</div>
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

    <!-- 进度条 -->
    <div class="progress-panel" v-if="planning">
      <div class="progress-bar"><div class="progress-fill" :style="{ width: progressPct + '%' }"></div></div>
      <div class="nodes">
        <span v-for="n in nodes" :key="n.key" :class="['node', nodeStatus[n.key]]">{{ n.icon }} {{ n.label }}</span>
      </div>
    </div>

    <!-- 表单 -->
    <div class="card" v-if="!planning">
      <h2>📍 规划行程</h2>
      <div class="form-row">
        <div class="fg"><label>出发地</label><input v-model="form.origin"></div>
        <div class="fg"><label>目的地</label><input v-model="form.city"></div>
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
      <button class="btn" @click="startPlan" :disabled="!form.city">🚀 生成计划</button>
    </div>

    <!-- 结果 -->
    <div v-if="result">
      <div class="card">
        <h2>🗺 {{ result.city }}</h2>
        <div class="ic" v-if="result.intercity">🚄 {{ result.intercity.mode }} · {{ result.intercity.distance_km }}km · ¥{{ result.intercity.estimated_cost }}</div>
        <div class="meta">📅 {{ result.start_date }} 起 · {{ result.days.length }} 天 · <span class="total">¥{{ (result.budget||{}).total || 0 }}</span></div>
        <div class="budget-bar" v-if="(result.budget||{}).total">
          <div v-for="(c,k) in budgetColors" :key="k" :style="{ width: ((result.budget||{})[k]||0)/(result.budget||{}).total*100 + '%', background: c }"></div>
        </div>
        <div class="blegend">
          <span v-for="(label,k) in budgetLabels" :key="k"><span class="dot" :style="{ background: budgetColors[k] }"></span>{{ label }} ¥{{ (result.budget||{})[k]||0 }}</span>
        </div>
      </div>
      <div class="card" v-if="result.weather_info?.length">
        <h2>🌡 天气</h2>
        <div class="weather">
          <div class="wday" v-for="w in result.weather_info.slice(0,7)" :key="w.date">
            <div class="wdate">{{ w.date }}</div>
            <div class="wicon">{{ weatherIcons[w.day_weather] || '🌤' }}</div>
            <div class="wtemp">{{ w.day_temp }}°</div>
            <div class="wdesc">{{ w.day_weather }}</div>
          </div>
        </div>
      </div>
      <div class="card day-card" v-for="(d,i) in result.days" :key="i">
        <h2>📅 第{{ i+1 }}天 — {{ d.date }}</h2>
        <p class="desc">{{ d.description }}</p>
        <div class="item" v-if="d.hotel">🏨 <strong>{{ d.hotel.name }}</strong> · {{ d.hotel.price_range }} · ¥{{ d.hotel.estimated_cost }}</div>
        <div class="item" v-for="a in d.attractions" :key="a.name">🏛 {{ a.name }} <span class="hint">{{ a.description?.slice(0,30) }}</span></div>
        <div class="item" v-for="m in d.meals" :key="m.name">🍽 {{ m.name }} <span class="hint">¥{{ m.estimated_cost }}</span></div>
      </div>
      <div class="card" v-if="result.overall_suggestions">
        <h2>💡 建议</h2>
        <div class="sugg" v-html="result.overall_suggestions.replace(/\n/g,'<br>')"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'

const API = 'http://localhost:8000'
const form = reactive({ origin: '上海', city: '北京', startDate: '', days: 3, prefs: [], transportMode: '高铁' })
const planning = ref(false), result = ref(null), errors = ref([]), progressPct = ref(0)
const profile = ref({ ready: false, trip_count: 0 })

const nodes = [
  { key: 'attraction', icon: '📍', label: '景点' }, { key: 'weather', icon: '🌤', label: '天气' },
  { key: 'hotel', icon: '🏨', label: '酒店' }, { key: 'memory', icon: '🧠', label: '画像' },
  { key: 'planner', icon: '📋', label: '规划' },
]
const nodeStatus = reactive(Object.fromEntries(nodes.map(n => [n.key, 'pending'])))

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
  Object.keys(nodeStatus).forEach(k => nodeStatus[k] = 'pending')
  const params = new URLSearchParams({ city: form.city, days: form.days, origin: form.origin, start_date: form.startDate, transport_mode: form.transportMode, preferences: form.prefs.join(',') })
  const es = new EventSource(`${API}/api/trip/stream?${params}`)
  es.onmessage = (e) => {
    const d = JSON.parse(e.data)
    if (d.status === 'start') { nodeStatus[d.node] = 'active'; progressPct.value = (nodes.findIndex(n => n.key === d.node) / nodes.length) * 70 }
    else if (d.status === 'done') { nodeStatus[d.node] = d.data?.status === 'failed' ? 'failed' : 'done'; progressPct.value = ((nodes.findIndex(n => n.key === d.node) + 1) / nodes.length) * 70 }
    else if (d.status === 'complete') { result.value = d.data; errors.value = d.data.errors || []; progressPct.value = 100; planning.value = false; es.close(); loadProfile() }
    else if (d.status === 'error') { errors.value = [d.data?.message || '未知错误']; planning.value = false; es.close() }
  }
  es.onerror = () => { if (planning.value) { errors.value = ['SSE 连接中断']; planning.value = false } es.close() }
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
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f0f1a; color: #e0e0e0; min-height: 100vh; }
.container { max-width: 760px; margin: 0 auto; padding: 20px; }
h1 { text-align: center; padding: 30px 0 10px; background: linear-gradient(135deg, #7c3aed, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.subtitle { text-align: center; font-size: 13px; color: #666; margin-bottom: 20px; }
.card { background: #1a1a2e; border-radius: 12px; padding: 24px; margin-bottom: 16px; border: 1px solid #2a2a4a; }
.card h2 { font-size: 16px; margin-bottom: 12px; color: #a78bfa; }
.form-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.fg { flex: 1; min-width: 90px; } .fg.sm { flex: 0 0 80px; }
.fg label { display: block; font-size: 12px; color: #888; margin-bottom: 4px; }
.fg input, .fg select { width: 100%; padding: 10px 12px; background: #0f0f1a; border: 1px solid #2a2a4a; border-radius: 8px; color: #e0e0e0; font-size: 14px; }
.dim-label { font-size: 12px; color: #888; margin: 12px 0 6px; }
.tags { display: flex; gap: 6px; flex-wrap: wrap; }
.tag { padding: 5px 12px; border-radius: 14px; font-size: 12px; cursor: pointer; border: 1px solid #2a2a4a; background: #0f0f1a; color: #888; user-select: none; }
.tag.active { background: #7c3aed; color: #fff; border-color: #7c3aed; }
.btn { width: 100%; padding: 14px; background: linear-gradient(135deg, #7c3aed, #3b82f6); border: none; border-radius: 8px; color: #fff; font-size: 16px; font-weight: 600; cursor: pointer; margin-top: 14px; }
.btn:disabled { opacity: 0.4; }
.progress-panel { margin-bottom: 20px; }
.progress-bar { height: 6px; background: #2a2a4a; border-radius: 3px; overflow: hidden; margin-bottom: 10px; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #7c3aed, #3b82f6); transition: width 1s ease; border-radius: 3px; }
.nodes { display: flex; justify-content: space-between; font-size: 12px; }
.node { color: #555; } .node.active { color: #7c3aed; font-weight: bold; } .node.done { color: #34d399; } .node.failed { color: #f87171; }
.profile-building { text-align: center; padding: 20px; color: #888; }
.counter { font-size: 36px; color: #7c3aed; font-weight: 700; margin: 8px 0; }
.hint { font-size: 13px; } .hint-sub { font-size: 12px; color: #a78bfa; margin-top: 6px; }
.profile-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }
.pdim { background: #0f0f1a; border-radius: 8px; padding: 10px; }
.plabel { font-size: 11px; color: #666; margin-bottom: 4px; }
.pval { font-size: 13px; color: #a78bfa; font-weight: 600; }
.fallback { background: #332211; border: 1px solid #886622; border-radius: 8px; padding: 14px; margin-bottom: 16px; }
.ftitle { font-weight: 600; color: #ffa500; margin-bottom: 6px; }
.fitem { font-size: 12px; color: #e0c080; padding: 2px 0; }
.ic { font-size: 13px; color: #a78bfa; margin: 6px 0; padding: 6px 10px; background: #0f0f1a; border-radius: 6px; }
.meta { font-size: 13px; color: #888; margin-top: 4px; }
.total { font-size: 18px; font-weight: 700; color: #34d399; }
.budget-bar { display: flex; height: 6px; border-radius: 3px; overflow: hidden; margin: 8px 0; }
.blegend { display: flex; gap: 14px; font-size: 12px; color: #888; flex-wrap: wrap; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 4px; }
.weather { display: flex; gap: 10px; flex-wrap: wrap; }
.wday { background: #0f0f1a; padding: 10px 12px; border-radius: 8px; text-align: center; min-width: 80px; }
.wdate { font-size: 11px; color: #888; } .wicon { font-size: 24px; margin: 4px 0; } .wtemp { font-size: 14px; font-weight: 600; } .wdesc { font-size: 11px; color: #aaa; }
.day-card { border-left: 3px solid #7c3aed; }
.desc { font-size: 13px; color: #aaa; margin-bottom: 10px; }
.item { padding: 4px 0; font-size: 13px; }
.sugg { font-size: 13px; color: #aaa; line-height: 1.8; padding: 10px; background: #0f0f1a; border-radius: 8px; }
</style>
