<template>
  <div class="app-bg">
    <!-- 动态背景光斑 -->
    <div class="bg-blob bg-blob-1"></div>
    <div class="bg-blob bg-blob-2"></div>
    <div class="bg-blob bg-blob-3"></div>

    <div class="container">
      <h1>🧳 TripPlanner</h1>
      <p class="subtitle">5 Node LangGraph · 实时进度 · 8 维用户画像</p>

      <!-- 画像面板 -->
      <div class="glass-card" v-if="!planning">
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

      <!-- 进度面板 — 流动文案 -->
      <div class="progress-panel" v-if="planning">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
        </div>
        <div class="flow-messages">
          <TransitionGroup name="flow-msg">
            <div v-for="msg in progressMessages" :key="msg.id"
                 :class="['flow-msg', msg.state]">
              <span class="msg-icon" v-if="msg.state === 'active'">
                <span class="pulse-dot"></span>
              </span>
              <span class="msg-icon" v-else-if="msg.state === 'done'">✅</span>
              <span class="msg-icon" v-else-if="msg.state === 'failed'">⚠️</span>
              <span class="msg-body">{{ msg.text }}</span>
            </div>
          </TransitionGroup>
        </div>
      </div>

      <!-- 表单 -->
      <div class="glass-card" v-if="!planning">
        <h2>📍 规划行程</h2>
        <div class="form-row">
          <div class="fg"><label>出发地</label><input v-model="form.origin" placeholder="上海"></div>
          <div class="fg"><label>目的地</label><input v-model="form.city" placeholder="成都"></div>
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
        <div class="glass-card">
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
        <div class="glass-card" v-if="result.weather_info?.length">
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
        <div class="glass-card day-card" v-for="(d,i) in result.days" :key="i">
          <h2>📅 第{{ i+1 }}天 — {{ d.date }}</h2>
          <p class="desc">{{ d.description }}</p>
          <div class="item" v-if="d.hotel">🏨 <strong>{{ d.hotel.name }}</strong> · {{ d.hotel.price_range }} · ¥{{ d.hotel.estimated_cost }}</div>
          <div class="item" v-for="a in d.attractions" :key="a.name">🏛 {{ a.name }} <span class="hint">{{ a.description }}</span></div>
          <div class="item" v-for="m in d.meals" :key="m.name">🍽 {{ m.name }} <span class="hint">¥{{ m.estimated_cost }}</span></div>
        </div>
        <div class="glass-card" v-if="result.overall_suggestions">
          <h2>💡 建议</h2>
          <div class="sugg" v-html="result.overall_suggestions.replace(/\n/g,'<br>')"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick } from 'vue'

const API = 'http://localhost:8000'
const form = reactive({ origin: '上海', city: '北京', startDate: '', days: 3, prefs: [], transportMode: '高铁' })
const planning = ref(false), result = ref(null), errors = ref([]), progressPct = ref(0)
const profile = ref({ ready: false, trip_count: 0 })

// ── 流动文案状态机 ──
const flowState = reactive({
  attraction: 'pending', hotel: 'pending',
  memory: 'pending', planner: 'pending', connected: 'pending'
})

// 每个阶段的文案模板 — 带入真实城市名
const stageMessages = {
  connected:  { start: (city) => `🔗 正在连接服务器...`, done: null },
  attraction: { start: (city) => `📍 正在搜索${city}的景点...`,  done: (city) => `✅ 景点搜索完成`, failed: (city) => `⚠️ 景点搜索失败，使用降级数据` },
  hotel:      { start: (city) => `🏨 正在搜索${city}酒店...`,  done: (city) => `✅ 酒店搜索完成`, failed: (city) => `⚠️ 酒店搜索失败，使用降级数据` },
  memory:     { start: (city) => `🧠 正在加载用户画像...`,    done: (city) => `✅ 画像加载完成` },
  planner:    { start: (city) => `📋 正在生成${city}旅行计划...`, done: (city) => `🎉 计划生成完毕！` },
}

// 计算当前应显示的文案序列
const progressMessages = computed(() => {
  const city = form.city || '目的地'
  const msgs = []
  const order = ['attraction', 'hotel', 'memory', 'planner']
  
  for (const node of order) {
    const s = flowState[node]
    if (s === 'active') {
      msgs.push({ id: node + '-active', text: stageMessages[node].start(city), state: 'active' })
      break // 只显示当前进行中的一项
    } else if (s === 'done') {
      msgs.push({ id: node + '-done', text: stageMessages[node].done(city), state: 'done' })
    } else if (s === 'failed') {
      msgs.push({ id: node + '-failed', text: stageMessages[node].failed(city), state: 'failed' })
    }
    // pending 的不显示
  }
  
  // 如果所有都完成了
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

function toggle(v) { const i = form.prefs.indexOf(v); i >= 0 ? form.prefs.splice(i, 1) : form.prefs.push(v) }

onMounted(async () => {
  const today = new Date();
  form.startDate = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  try { const r = await fetch(`${API}/api/profile`); profile.value = await r.json() } catch {}
})

const nodeOrder = ['attraction', 'hotel', 'memory', 'planner']
const progressSteps = [15, 35, 55, 70]  // 最后一步只到 70%，等 fetch 返回才跳 100%

async function startPlan() {
  planning.value = true; result.value = null; errors.value = []; progressPct.value = 0
  // 重置流动状态
  Object.keys(flowState).forEach(k => flowState[k] = 'pending')

  // 发起 POST 请求（实际后端调用）
  const payload = {
    origin: form.origin,
    city: form.city,
    days: form.days,
    start_date: form.startDate,
    transport_mode: form.transportMode,
    preferences: form.prefs,
  }

  const fetchPromise = fetch(`${API}/api/trip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(async r => {
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`)
    const data = await r.json()
    // 将 intercity_transport 映射为 intercity（匹配模板引用）
    if (data.intercity_transport) {
      data.intercity = {
        mode: data.intercity_transport.mode,
        distance_km: data.intercity_transport.distance_km,
        distance_category: data.intercity_transport.distance_category,
        estimated_cost: data.intercity_transport.estimated_cost,
        duration_hours: data.intercity_transport.duration_hours,
      }
    }
    return data
  })

  // 立即激活第一个阶段
  flowState[nodeOrder[0]] = 'active'

  let step = 1
  const timer = setInterval(() => {
    if (step > nodeOrder.length) {
      clearInterval(timer)
      return
    }
    // 前一个阶段标记为完成
    flowState[nodeOrder[step - 1]] = 'done'
    progressPct.value = progressSteps[step - 1]

    // 激活下一个阶段——但 planner 始终 active 直到 fetch 返回
    if (step < nodeOrder.length) {
      flowState[nodeOrder[step]] = 'active'
    }
    step++
  }, 4000)  // 4 秒一步，匹配真实后端耗时

  try {
    const data = await fetchPromise
    clearInterval(timer)
    // 确保所有阶段标记为完成
    nodeOrder.forEach(n => { flowState[n] = 'done' })
    result.value = data
    errors.value = data.errors || []
    progressPct.value = 100
    setTimeout(() => { planning.value = false }, 800)
    loadProfile()
  } catch (err) {
    clearInterval(timer)
    // 将当前 active 的阶段标记为 failed
    nodeOrder.forEach(n => { if (flowState[n] === 'active') flowState[n] = 'failed' })
    errors.value = ['请求失败: ' + err.message]
    planning.value = false
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
/* ── 全局重置 ── */
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  color: #e0e0e0;
  min-height: 100vh;
  overflow-x: hidden;
}

/* ── 动态背景 ── */
.app-bg {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0a1a 0%, #120b24 30%, #0a1628 60%, #0f0a1a 100%);
  position: relative;
  overflow: hidden;
}

/* 浮动光斑 */
.bg-blob {
  position: fixed;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.15;
  pointer-events: none;
  z-index: 0;
}
.bg-blob-1 { width: 500px; height: 500px; background: #7c3aed; top: -100px; left: -100px; animation: floatBlob 20s ease-in-out infinite; }
.bg-blob-2 { width: 400px; height: 400px; background: #3b82f6; top: 50%; right: -50px; animation: floatBlob 25s ease-in-out infinite reverse; }
.bg-blob-3 { width: 350px; height: 350px; background: #f59e0b; bottom: -80px; left: 30%; animation: floatBlob 18s ease-in-out infinite 5s; }

@keyframes floatBlob {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -50px) scale(1.1); }
  66% { transform: translate(-20px, 20px) scale(0.9); }
}

/* ── 容器 ── */
.container {
  max-width: 780px;
  margin: 0 auto;
  padding: 30px 20px 60px;
  position: relative;
  z-index: 1;
}

h1 {
  text-align: center;
  padding: 30px 0 10px;
  font-size: 32px;
  background: linear-gradient(135deg, #a78bfa, #60a5fa, #34d399);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.subtitle { text-align: center; font-size: 13px; color: #555; margin-bottom: 30px; letter-spacing: 0.5px; }

/* ── 毛玻璃卡片 ── */
.glass-card {
  background: rgba(255, 255, 255, 0.03);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 26px 28px;
  margin-bottom: 18px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  transition: all 0.3s ease;
}
.glass-card:hover {
  border-color: rgba(255, 255, 255, 0.15);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.08);
}
.glass-card h2 { font-size: 16px; margin-bottom: 14px; color: #a78bfa; font-weight: 600; }

/* ── 表单 ── */
.form-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.fg { flex: 1; min-width: 90px; } .fg.sm { flex: 0 0 80px; }
.fg label { display: block; font-size: 11px; color: #777; margin-bottom: 4px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }
.fg input, .fg select {
  width: 100%; padding: 10px 14px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  color: #e0e0e0;
  font-size: 14px;
  transition: all 0.2s;
}
.fg input:focus, .fg select:focus {
  outline: none;
  border-color: rgba(124, 58, 237, 0.5);
  box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.1);
}

.dim-label { font-size: 11px; color: #777; margin: 14px 0 6px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }
.tags { display: flex; gap: 6px; flex-wrap: wrap; }
.tag {
  padding: 6px 14px; border-radius: 20px; font-size: 12px; cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #888;
  user-select: none;
  transition: all 0.2s;
  backdrop-filter: blur(4px);
}
.tag:hover { border-color: rgba(124, 58, 237, 0.3); color: #bbb; }
.tag.active { background: linear-gradient(135deg, #7c3aed, #6d28d9); color: #fff; border-color: #7c3aed; box-shadow: 0 2px 8px rgba(124, 58, 237, 0.3); }

.btn {
  width: 100%; padding: 14px;
  background: linear-gradient(135deg, #7c3aed, #3b82f6);
  border: none; border-radius: 10px;
  color: #fff; font-size: 16px; font-weight: 600;
  cursor: pointer; margin-top: 16px;
  transition: all 0.3s;
  letter-spacing: 0.5px;
}
.btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 8px 25px rgba(124, 58, 237, 0.3); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ── 进度面板 ── */
.progress-panel { margin-bottom: 30px; }

.progress-bar {
  height: 4px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 20px;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #7c3aed, #3b82f6, #34d399);
  background-size: 200% 100%;
  animation: progressShimmer 2s ease-in-out infinite;
  border-radius: 2px;
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes progressShimmer {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

/* ── 流动文案 ── */
.flow-messages {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.flow-msg {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-radius: 10px;
  font-size: 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  transition: all 0.4s ease;
}

.flow-msg.active {
  background: rgba(124, 58, 237, 0.1);
  border-color: rgba(124, 58, 237, 0.3);
  box-shadow: 0 0 20px rgba(124, 58, 237, 0.1);
}
.flow-msg.done { color: #34d399; }
.flow-msg.failed { color: #f87171; background: rgba(248, 113, 113, 0.08); }

.msg-icon { flex-shrink: 0; width: 20px; display: flex; align-items: center; justify-content: center; font-size: 14px; }

/* 脉冲点 */
.pulse-dot {
  width: 8px; height: 8px;
  background: #a78bfa;
  border-radius: 50%;
  display: inline-block;
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; box-shadow: 0 0 0 0 rgba(167, 139, 250, 0.4); }
  50% { transform: scale(1.3); opacity: 0.7; box-shadow: 0 0 0 8px rgba(167, 139, 250, 0); }
}

.msg-body {
  flex: 1;
  line-height: 1.4;
}

/* TransitionGroup 动画 */
.flow-msg-enter-active {
  transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}
.flow-msg-leave-active {
  transition: all 0.3s ease-in;
}
.flow-msg-enter-from {
  opacity: 0;
  transform: translateY(-10px);
}
.flow-msg-leave-to {
  opacity: 0;
  transform: translateX(20px);
}

/* ── 画像 ── */
.profile-building { text-align: center; padding: 20px; color: #888; }
.counter { font-size: 38px; background: linear-gradient(135deg, #7c3aed, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 700; margin: 8px 0; }
.hint { font-size: 13px; } .hint-sub { font-size: 12px; color: #a78bfa; margin-top: 6px; }
.profile-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }
.pdim { background: rgba(255, 255, 255, 0.03); border-radius: 10px; padding: 12px; border: 1px solid rgba(255, 255, 255, 0.05); }
.plabel { font-size: 11px; color: #777; margin-bottom: 4px; }
.pval { font-size: 13px; color: #a78bfa; font-weight: 600; }

/* ── 降级 ── */
.fallback { background: rgba(255, 165, 0, 0.06); border: 1px solid rgba(255, 165, 0, 0.2); border-radius: 10px; padding: 14px 18px; margin-bottom: 16px; backdrop-filter: blur(10px); }
.ftitle { font-weight: 600; color: #ffa500; margin-bottom: 6px; }
.fitem { font-size: 12px; color: #e0c080; padding: 2px 0; }

/* ── 结果 ── */
.ic { font-size: 13px; color: #a78bfa; margin: 6px 0; padding: 8px 12px; background: rgba(255, 255, 255, 0.03); border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.05); }
.meta { font-size: 13px; color: #888; margin-top: 6px; }
.total { font-size: 20px; font-weight: 700; color: #34d399; }
.budget-bar { display: flex; height: 6px; border-radius: 3px; overflow: hidden; margin: 10px 0; }
.blegend { display: flex; gap: 16px; font-size: 12px; color: #888; flex-wrap: wrap; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 4px; }
.weather { display: flex; gap: 10px; flex-wrap: wrap; }
.wday { background: rgba(255, 255, 255, 0.03); padding: 10px 14px; border-radius: 10px; text-align: center; min-width: 80px; border: 1px solid rgba(255, 255, 255, 0.05); }
.wdate { font-size: 11px; color: #888; } .wicon { font-size: 26px; margin: 4px 0; } .wtemp { font-size: 14px; font-weight: 600; } .wdesc { font-size: 11px; color: #aaa; }
.day-card { border-left: 3px solid #7c3aed; }
.desc { font-size: 13px; color: #aaa; margin-bottom: 12px; line-height: 1.6; }
.item { padding: 5px 0; font-size: 13px; }
.sugg { font-size: 13px; color: #aaa; line-height: 1.8; padding: 12px; background: rgba(255, 255, 255, 0.03); border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.05); }
</style>
