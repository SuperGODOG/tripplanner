<template>
  <div class="container">
    <h1>🧳 TripPlanner</h1>
    <p class="subtitle">多智能体旅行规划 · 实时进度可视化</p>

    <!-- 进度条 -->
    <div class="progress-panel" v-if="planning">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
      </div>
      <div class="nodes">
        <span v-for="n in nodes" :key="n.key"
          :class="['node', nodeStatus[n.key]]">
          {{ n.icon }} {{ n.label }}
        </span>
      </div>
    </div>

    <!-- 表单 -->
    <div class="card" v-if="!planning">
      <h2>📍 规划行程</h2>
      <div class="form-row">
        <div class="fg"><label>出发地</label><input v-model="form.origin" placeholder="上海"></div>
        <div class="fg"><label>目的地</label><input v-model="form.city" placeholder="北京"></div>
        <div class="fg"><label>日期</label><input type="date" v-model="form.startDate"></div>
        <div class="fg sm"><label>天数</label>
          <select v-model.number="form.days">
            <option v-for="d in [1,2,3,5,7]" :key="d" :value="d">{{ d }}天</option>
          </select>
        </div>
      </div>
      <div class="tags">
        <span v-for="t in tagCategories" :key="t.val"
          :class="['tag', { active: form.prefs.includes(t.val) }]"
          @click="togglePref(t.val)">{{ t.icon }} {{ t.label }}</span>
      </div>
      <button class="btn" @click="startPlan" :disabled="!form.city">🚀 生成计划</button>
    </div>

    <!-- 结果 -->
    <div v-if="result">
      <div class="card" v-if="result.intercity">
        <h2>🚄 城际交通</h2>
        <p>{{ result.intercity.mode }} · {{ result.intercity.distance_km }}km · ¥{{ result.intercity.estimated_cost }}</p>
      </div>
      <div class="card" v-for="(day, i) in result.days" :key="i">
        <h2>📅 第{{ i+1 }}天 — {{ day.date }}</h2>
        <p class="desc">{{ day.description }}</p>
        <div class="item" v-if="day.hotel">🏨 <strong>{{ day.hotel.name }}</strong> {{ day.hotel.price_range }}</div>
        <div class="item" v-for="a in day.attractions" :key="a.name">🏛 {{ a.name }}</div>
        <div class="item" v-for="m in day.meals" :key="m.name">🍽 {{ m.name }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'

const API = 'http://localhost:8000'
const form = reactive({ origin: '上海', city: '北京', startDate: new Date().toISOString().slice(0, 10), days: 3, prefs: ['历史文化'], transportMode: '高铁' })
const planning = ref(false)
const result = ref(null)
const progressPct = ref(0)

const nodes = [
  { key: 'attraction', icon: '📍', label: '景点' },
  { key: 'weather', icon: '🌤', label: '天气' },
  { key: 'hotel', icon: '🏨', label: '酒店' },
  { key: 'memory', icon: '🧠', label: '画像' },
  { key: 'planner', icon: '📋', label: '规划' },
]
const nodeStatus = reactive(Object.fromEntries(nodes.map(n => [n.key, 'pending'])))
const nodeOrder = nodes.map(n => n.key)

const tagCategories = [
  { val: '历史文化', icon: '🏛', label: '历史文化' }, { val: '美食', icon: '🍜', label: '美食' },
  { val: '自然风光', icon: '🏔', label: '自然风光' }, { val: '购物', icon: '🛍', label: '购物' },
  { val: '不吃辣', icon: '🥬', label: '不吃辣' }, { val: '爱吃辣', icon: '🌶', label: '爱吃辣' },
  { val: '地铁优先', icon: '🚇', label: '地铁' }, { val: '自驾', icon: '🚗', label: '自驾' },
  { val: '经济型酒店', icon: '💰', label: '经济型' }, { val: '豪华型酒店', icon: '👑', label: '豪华型' },
]
function togglePref(v) { const i = form.prefs.indexOf(v); i >= 0 ? form.prefs.splice(i, 1) : form.prefs.push(v) }

onMounted(() => form.startDate = new Date().toISOString().slice(0, 10))

async function startPlan() {
  planning.value = true; result.value = null; progressPct.value = 0
  Object.keys(nodeStatus).forEach(k => nodeStatus[k] = 'pending')

  const params = new URLSearchParams({
    city: form.city, days: form.days, origin: form.origin,
    start_date: form.startDate, transport_mode: form.transportMode,
    preferences: form.prefs.join(',')
  })
  const es = new EventSource(`${API}/api/trip/stream?${params}`)

  es.onmessage = (e) => {
    const d = JSON.parse(e.data)
    if (d.status === 'start') {
      nodeStatus[d.node] = 'active'
      progressPct.value = (nodeOrder.indexOf(d.node) / nodes.length) * 100
    } else if (d.status === 'done') {
      nodeStatus[d.node] = d.data?.status === 'failed' ? 'failed' : 'done'
      progressPct.value = ((nodeOrder.indexOf(d.node) + 1) / nodes.length) * 100
    } else if (d.status === 'complete') {
      result.value = d.data; progressPct.value = 100
      planning.value = false; es.close()
    } else if (d.status === 'error') {
      planning.value = false; es.close()
    }
  }
  es.onerror = () => { planning.value = false; es.close() }
}
</script>

<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f0f1a; color: #e0e0e0; min-height: 100vh; }
.container { max-width: 720px; margin: 0 auto; padding: 20px; }
h1 { text-align: center; padding: 30px 0 10px; background: linear-gradient(135deg, #7c3aed, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.subtitle { text-align: center; font-size: 13px; color: #666; margin-bottom: 20px; }
.card { background: #1a1a2e; border-radius: 12px; padding: 24px; margin-bottom: 16px; border: 1px solid #2a2a4a; }
.card h2 { font-size: 16px; margin-bottom: 12px; color: #a78bfa; }
.form-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.fg { flex: 1; min-width: 90px; } .fg.sm { flex: 0 0 80px; }
.fg label { display: block; font-size: 12px; color: #888; margin-bottom: 4px; }
.fg input, .fg select { width: 100%; padding: 10px 12px; background: #0f0f1a; border: 1px solid #2a2a4a; border-radius: 8px; color: #e0e0e0; font-size: 14px; }
.tags { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 14px; }
.tag { padding: 5px 12px; border-radius: 14px; font-size: 12px; cursor: pointer; border: 1px solid #2a2a4a; background: #0f0f1a; color: #888; user-select: none; }
.tag.active { background: #7c3aed; color: #fff; border-color: #7c3aed; }
.btn { width: 100%; padding: 14px; background: linear-gradient(135deg, #7c3aed, #3b82f6); border: none; border-radius: 8px; color: #fff; font-size: 16px; font-weight: 600; cursor: pointer; }
.btn:disabled { opacity: 0.4; }
.progress-panel { margin-bottom: 20px; }
.progress-bar { height: 6px; background: #2a2a4a; border-radius: 3px; overflow: hidden; margin-bottom: 10px; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #7c3aed, #3b82f6); transition: width 1s ease; border-radius: 3px; }
.nodes { display: flex; justify-content: space-between; font-size: 12px; }
.node { color: #555; } .node.active { color: #7c3aed; font-weight: bold; } .node.done { color: #34d399; } .node.failed { color: #f87171; }
.desc { font-size: 13px; color: #aaa; margin-bottom: 10px; }
.item { padding: 4px 0; font-size: 13px; }
</style>
