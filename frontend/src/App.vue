<template>
  <div class="app-bg" @mousemove="onMouseMove">
    <!-- 鼠标追踪光晕 -->
    <div class="cursor-spotlight" :style="{ '--mx': mouseX + 'px', '--my': mouseY + 'px' }"></div>

    <!-- 浮动星空粒子 -->
    <div class="stars">
      <span v-for="i in 30" :key="i" class="star" :style="starStyle(i)"></span>
    </div>

    <!-- 背景色彩渐变微光 -->
    <div class="bg-blob bg-blob-1"></div>
    <div class="bg-blob bg-blob-2"></div>
    <div class="bg-blob bg-blob-3"></div>

    <div class="copilot-container">
      <!-- 顶部 Header -->
      <header class="app-header">
        <div class="header-left">
          <div class="logo-icon">🧳</div>
          <div>
            <h1 class="header-title">TripPlanner <span class="badge-copilot">Co-pilot</span></h1>
            <p class="header-sub">三 Agent 状态机协作 · 双工 RAG 时效核验 · Redis 局部复用 · 闭环自愈</p>
          </div>
        </div>
        <div class="header-right">
          <!-- ⚡ Sovereign Harness 独占极速引擎 -->
          <div class="engine-badge" title="独占规划调度引擎：Sovereign Harness">
            <span class="engine-pill">⚡ Sovereign Harness 极速内核</span>
          </div>

          <span class="session-badge" title="当前会话 ID">
            <span class="pulse-dot"></span> {{ sessionId.slice(0, 8) }}...
          </span>
          <button class="btn-new-session" @click="resetSession" title="新建会话">
            <span>+ 新会话</span>
          </button>
        </div>
      </header>

      <!-- 双栏协作主体 -->
      <main class="copilot-main">
        <!-- ════════ 左栏：多轮对话与意图澄清中枢 ════════ -->
        <section class="left-column glass-panel">
          <div class="panel-header">
            <div class="panel-title">
              <span class="icon">💬</span> 智能旅行顾问
            </div>
            <div class="panel-subtitle">支持意图追问澄清、偏好改口、景点锁定与自然交互</div>
          </div>

          <!-- 对话消息流 -->
          <div class="chat-history" ref="chatHistoryRef">
            <div v-for="msg in messages" :key="msg.id" :class="['chat-bubble-wrap', msg.role]">
              <div class="bubble-avatar">
                {{ msg.role === 'user' ? '👤' : '🤖' }}
              </div>
              <div class="bubble-body">
                <!-- 思考进度折叠区 -->
                <div v-if="msg.thinking && msg.thinking.length" class="thinking-box">
                  <div class="thinking-header" @click="msg.isThinkingOpen = !msg.isThinkingOpen">
                    <span class="thinking-spinner" v-if="msg.isStreaming"></span>
                    <span class="thinking-icon" v-else>🧠</span>
                    <span class="thinking-title">思考过程 ({{ msg.thinking.length }} 步)</span>
                    <span class="thinking-toggle">{{ msg.isThinkingOpen ? '收起 ▲' : '展开 ▼' }}</span>
                  </div>
                  <Transition name="expand">
                    <div v-if="msg.isThinkingOpen" class="thinking-content">
                      <div v-for="(t, idx) in msg.thinking" :key="idx" class="thinking-step">
                        <span class="step-num">{{ idx + 1 }}</span>
                        <span class="step-text">{{ t.detail || t }}</span>
                      </div>
                    </div>
                  </Transition>
                </div>

                <!-- 消息富文本渲染 -->
                <div class="bubble-text" v-html="renderMarkdown(msg.content)"></div>

                <!-- 未决澄清交互卡片 -->
                <div v-if="msg.clarification" class="clarification-card">
                  <div class="clarification-header">
                    <span class="card-icon">❓</span>
                    <span class="card-title">{{ msg.clarification.prompt_text }}</span>
                  </div>
                  <div class="clarification-options">
                    <button
                      v-for="opt in msg.clarification.options"
                      :key="opt.option_id"
                      class="btn-option-chip"
                      :disabled="isStreaming"
                      @click="handleOptionSelect(opt)"
                    >
                      <span class="chip-label">{{ opt.label }}</span>
                      <span class="chip-arrow">→</span>
                    </button>
                  </div>
                </div>

                <div class="bubble-meta">
                  <span class="bubble-time">{{ msg.time }}</span>
                </div>
              </div>
            </div>

            <!-- 流式思考临时占位 -->
            <div v-if="isStreaming && currentThinking.length && (!messages.length || messages[messages.length-1].role === 'user')" class="chat-bubble-wrap assistant">
              <div class="bubble-avatar">🤖</div>
              <div class="bubble-body">
                <div class="thinking-box">
                  <div class="thinking-header">
                    <span class="thinking-spinner"></span>
                    <span class="thinking-title">Agent 正在执行与核验...</span>
                  </div>
                  <div class="thinking-content">
                    <div v-for="(t, idx) in currentThinking" :key="idx" class="thinking-step">
                      <span class="step-num">{{ idx + 1 }}</span>
                      <span class="step-text">{{ t.detail || t }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 快捷 Prompt 标签 -->
          <div class="quick-prompts">
            <span class="prompt-hint">快捷提示：</span>
            <button
              v-for="(p, i) in quickPrompts"
              :key="i"
              class="btn-quick-chip"
              :disabled="isStreaming"
              @click="applyQuickPrompt(p)"
            >
              {{ p }}
            </button>
          </div>

          <!-- 输入区 -->
          <div class="chat-input-area">
            <textarea
              v-model="inputQuery"
              class="chat-input"
              rows="2"
              placeholder="输入旅行意图（如：我想去北京玩3天，预算5000元，必须去故宫，平时一直吃辣）..."
              :disabled="isStreaming"
              @keydown.enter.prevent="handleEnter"
            ></textarea>
            <button
              class="btn-send"
              :disabled="isStreaming || !inputQuery.trim()"
              @click="submitUserMessage"
            >
              <span v-if="isStreaming" class="loading-spin"></span>
              <span v-else>发送 🚀</span>
            </button>
          </div>
        </section>

        <!-- ════════ 右栏：三轨需求与实时行程看板 ════════ -->
        <section class="right-column glass-panel">
          <div class="panel-header">
            <div class="panel-title">
              <span class="icon">🗺️</span> 实时定制行程看板
            </div>
            <div class="panel-actions" v-if="currentPlan">
              <span class="plan-version-badge">版本 v{{ currentPlan.version_id || 1 }}</span>
            </div>
          </div>

          <div class="board-scrollable">
            <!-- 1. 当前三轨有效需求卡片 -->
            <div class="effective-reqs-card">
              <div class="reqs-title">
                <span>📋 当前生效需求画像</span>
                <span class="reqs-sub">单次与长期偏好已严格解耦</span>
              </div>
              <div class="reqs-grid">
                <div class="req-item">
                  <span class="req-label">目的地</span>
                  <span class="req-val highlight">{{ getSlotValue('city') || '待澄清' }}</span>
                </div>
                <div class="req-item">
                  <span class="req-label">游玩天数</span>
                  <span class="req-val">{{ getSlotValue('days') ? getSlotValue('days') + ' 天' : '待确定' }}</span>
                </div>
                <div class="req-item">
                  <span class="req-label">出发日期</span>
                  <span class="req-val">{{ getSlotValue('start_date') || '近期自选' }}</span>
                </div>
                <div class="req-item">
                  <span class="req-label">总预算</span>
                  <span class="req-val">¥{{ getSlotValue('budget_total') || '无明确限制' }}</span>
                </div>
              </div>

              <!-- 显式锁定景点列表 -->
              <div v-if="lockedItems.length" class="locked-section">
                <span class="locked-label">🔒 显式锁定项（自愈严格保护）：</span>
                <div class="locked-chips">
                  <span v-for="item in lockedItems" :key="item" class="locked-chip">
                    🔒 {{ item }}
                  </span>
                </div>
              </div>

              <!-- 偏好标签 -->
              <div v-if="getPreferences().length" class="prefs-section">
                <span class="prefs-label">🏷️ 已识别风格偏好：</span>
                <div class="pref-chips">
                  <span v-for="p in getPreferences()" :key="p" class="pref-chip">
                    {{ p }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 2. 算法白盒度量证明卡片 -->
            <div v-if="currentPlan && currentPlan.algorithm_telemetry" class="telemetry-card">
              <div class="telemetry-header">
                <span class="telemetry-icon">🧮</span>
                <span class="telemetry-title">算法白盒规划证明</span>
                <span class="telemetry-tag">K-Means · Minimax · 2-Opt</span>
              </div>
              <div class="telemetry-body">
                <div class="telemetry-row">
                  <span class="t-badge">K-Means</span>
                  <span class="t-text">
                    候选点共 {{ currentPlan.algorithm_telemetry.kmeans?.total_pois || 0 }} 处，按地理质心划分为 {{ currentPlan.algorithm_telemetry.kmeans?.days || 0 }} 天均衡空间簇
                  </span>
                </div>
                <div class="telemetry-row">
                  <span class="t-badge">Minimax</span>
                  <span class="t-text">
                    极小化每日首站通勤与极远距离：选定【{{ currentPlan.algorithm_telemetry.minimax_hotel?.hotel_name || '商圈优选酒店' }}】
                  </span>
                </div>
                <div v-if="currentPlan.algorithm_telemetry.route_2opt?.total_saved_km" class="telemetry-row">
                  <span class="t-badge green">2-Opt TSP</span>
                  <span class="t-text highlight-green">
                    局部搜索完成路径收敛，累计为您的行程优化缩短约 <strong>{{ currentPlan.algorithm_telemetry.route_2opt.total_saved_km }} km</strong> 绕路
                  </span>
                </div>
              </div>
            </div>

            <!-- 3. 自愈优化提示横幅 -->
            <Transition name="fade">
              <div v-if="attemptedActions.length" class="self-healing-banner">
                <div class="banner-header">
                  <span class="banner-icon">⚡</span>
                  <span class="banner-title">Repair Agent 已完成自愈优化：</span>
                </div>
                <ul class="banner-list">
                  <li v-for="(act, idx) in attemptedActions" :key="idx">{{ act }}</li>
                </ul>
              </div>
            </Transition>

            <!-- 4. 行程分日详情列表 -->
            <div v-if="currentPlan && currentPlan.days && currentPlan.days.length" class="itinerary-days">
              <div
                v-for="day in currentPlan.days"
                :key="day.day_index"
                class="day-card"
              >
                <div class="day-card-header">
                  <div class="day-badge">Day {{ day.day_index + 1 }}</div>
                  <div class="day-date">{{ day.date || '' }}</div>
                  <div class="day-meta">
                    门票 ¥{{ day.total_ticket || 0 }} · 游览 {{ (day.attractions || []).length }} 景点
                    <span v-if="day.telemetry && day.telemetry.saved_km > 0" class="day-saved-tag">
                      ⚡ 节省 {{ day.telemetry.saved_km }}km
                    </span>
                  </div>
                </div>

                <!-- 高德官方气象与出行提示 -->
                <div v-if="day.weather" class="day-weather-strip">
                  <div class="weather-main">
                    <span class="weather-icon">🌤️</span>
                    <span class="weather-condition">{{ day.weather.weather || '晴' }}</span>
                    <span class="weather-temp">{{ day.weather.temp_range || '' }}</span>
                    <span class="weather-wind">{{ day.weather.wind || '' }}</span>
                    <span class="weather-source-badge">{{ day.weather.source_label || '⭐ 高德天气' }}</span>
                  </div>
                  <div v-if="day.weather.tip" class="weather-tip">
                    💡 {{ day.weather.tip }}
                  </div>
                </div>

                <!-- 景点列表 (2-Opt 最优时序) -->
                <div class="attractions-timeline">
                  <div
                    v-for="(attr, aIdx) in day.attractions"
                    :key="aIdx"
                    class="timeline-item"
                  >
                    <div class="timeline-dot"></div>
                    <div class="attraction-card">
                      <div class="attr-header">
                        <div class="attr-name-wrap">
                          <span class="attr-name">{{ attr.name }}</span>
                          <span v-if="isItemLocked(attr.name)" class="lock-indicator" title="用户锁定项">🔒 锁定</span>
                        </div>
                        <div class="attr-badges">
                          <!-- 高德官方真实评分 -->
                          <span v-if="attr.rating" class="amap-score-badge" title="高德官方权威真实评分">
                            ⭐ {{ attr.rating }}
                          </span>
                          <!-- 国家级景区等级 -->
                          <span v-if="attr.level" class="amap-level-badge" title="国家景区评级">
                            🏷️ {{ attr.level }}
                          </span>
                          <!-- 营业核验 Badge -->
                          <span
                            v-if="attr.place_fact"
                            :class="['fact-badge', getFactClass(attr.place_fact)]"
                          >
                            {{ getFactLabel(attr.place_fact) }}
                          </span>
                          <span class="ticket-tag">¥{{ attr.price || attr.ticket_price || 0 }}</span>
                        </div>
                      </div>

                      <div class="attr-meta">
                        <span v-if="attr.arrive_time" class="meta-item time-tag">
                          ⏰ 游览时序: {{ attr.arrive_time }} - {{ attr.depart_time }}
                        </span>
                        <span v-if="attr.distance_km" class="meta-item">
                          🚗 距上站: {{ attr.distance_km }} km
                        </span>
                        <span class="meta-item">⏱ 建议时长: {{ attr.visit_minutes || 90 }} 分钟</span>
                        <span v-if="attr.open_time || (attr.place_fact && attr.place_fact.opening_hours)" class="meta-item time-open">
                          🕒 营业: {{ attr.open_time || attr.place_fact.opening_hours }}
                        </span>
                        <span v-if="attr.business_area" class="meta-item area-tag">
                          🏞️ {{ attr.business_area }}
                        </span>
                      </div>

                      <!-- 📍 详细门牌地址 -->
                      <div v-if="attr.address" class="attr-address-line">
                        <span class="addr-icon">📍</span>
                        <span class="addr-text">{{ attr.address }}</span>
                      </div>

                      <!-- 真实 Web RAG: 实时联网活数据 (Tavily 搜索引擎实时提取) -->
                      <div v-if="attr.guide_tips" class="tavily-tips-box">
                        <div class="tavily-badge-header">
                          <span class="tavily-badge-pill">🌐 Tavily 搜索引擎实时提取</span>
                          <span class="tavily-badge-hint">全网实时活数据 · 来源白盒溯源</span>
                        </div>
                        <div v-if="attr.guide_tips.booking_policy" class="tavily-line">
                          <span class="tavily-tag booking">[🌐 互联网搜索] 🎫 实时票务</span>
                          <span class="tavily-text">{{ attr.guide_tips.booking_policy }}</span>
                        </div>
                        <div v-for="(tip, tIdx) in (attr.guide_tips.tips || []).slice(0, 2)" :key="tIdx" class="tavily-line">
                          <span class="tavily-tag tip">[🌐 互联网搜索] 💡 避坑建议</span>
                          <span class="tavily-text">{{ tip }}</span>
                        </div>
                      </div>

                      <!-- 预约与抢票政策 (静态兜底) -->
                      <div v-else-if="attr.place_fact && attr.place_fact.booking_policy" class="booking-notice">
                        <span class="b-icon">🎫</span>
                        <span class="b-text">{{ attr.place_fact.booking_policy }}</span>
                      </div>

                      <!-- 双工 RAG: 攻略心得与避坑机位 (本地兜底) -->
                      <div v-if="!attr.guide_tips && attr.guides && attr.guides.length" class="guides-box">
                        <div v-for="(g, gIdx) in attr.guides" :key="gIdx" class="guide-item">
                          <span class="guide-tag">💡 {{ g.tag || '攻略' }}</span>
                          <span class="guide-text">{{ g.text }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 🏨 当日住宿推荐 (Minimax 极小化通勤选址) -->
                <div v-if="day.hotel && day.hotel.name" class="day-hotel-card">
                  <div class="hotel-header">
                    <div class="hotel-title-wrap">
                      <span class="hotel-icon">🏨</span>
                      <span class="hotel-name">{{ day.hotel.name }}</span>
                      <span class="hotel-type-badge">{{ day.hotel.hotel_type || '舒适型' }}</span>
                    </div>
                    <span class="hotel-price">{{ day.hotel.price_range || '¥400/晚' }}</span>
                  </div>
                  <div class="hotel-sub">
                    <span class="minimax-tag">📍 Minimax 极小化通勤选址</span>
                    <span v-if="day.hotel.address" class="hotel-address">{{ day.hotel.address }}</span>
                  </div>
                </div>

                <!-- 🍜 当地 4.0+ 精选美食推荐 -->
                <div v-if="day.meals && day.meals.length" class="day-meals-card">
                  <div class="meals-card-header">
                    <span class="meals-icon">🍜</span>
                    <span class="meals-title">当地精选美食 (高德 4.0+ 评分 / 地道名吃)</span>
                  </div>
                  <div class="meals-list">
                    <div v-for="(m, mIdx) in day.meals" :key="mIdx" class="meal-badge-item">
                      <div class="meal-slot-label">
                        {{ m.type === 'breakfast' ? '🌅 早餐' : m.type === 'lunch' ? '☀️ 午餐' : '🌙 晚餐' }}
                      </div>
                      <div class="meal-info">
                        <div class="meal-top">
                          <span class="meal-name">{{ m.name }}</span>
                          <span class="meal-score">⭐ {{ m.rating || 4.6 }}</span>
                        </div>
                        <div class="meal-detail">{{ m.description }}</div>
                      </div>
                      <div class="meal-price">¥{{ m.estimated_cost || 35 }}</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 空状态 -->
            <div v-else class="empty-plan-placeholder">
              <div class="empty-icon">📍</div>
              <div class="empty-title">等待行程生成中...</div>
              <div class="empty-sub">在左侧对话框告诉顾问您的目的地或点击选项，系统将在此即时渲染最优日内路线与事实核验结果。</div>
            </div>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'

// ── 状态定义 ──
const sessionId = ref(localStorage.getItem('tp_session_id') || ('sess_' + Math.random().toString(36).slice(2, 10)))
localStorage.setItem('tp_session_id', sessionId.value)

const mouseX = ref(0)
const mouseY = ref(0)

const inputQuery = ref('')
const isStreaming = ref(false)
const chatHistoryRef = ref(null)

const messages = ref([
  {
    id: 1,
    role: 'assistant',
    content: '👋 您好！我是您的智能旅行定制顾问 **TripPlanner Co-pilot**。\n\n我能帮您规划最优行程路线、核查景区周一闭馆与预约规则、智能规避时间窗超限与预算超支。请问您计划去哪座城市旅行呢？',
    thinking: [],
    clarification: null,
    time: '刚刚',
  }
])

const currentThinking = ref([])
const effectiveRequirements = ref({ slots: {}, locked_items: [], revision_id: 1 })
const currentPlan = ref(null)
const lockedItems = ref([])
const attemptedActions = ref([])

const quickPrompts = [
  '我想去北京玩3天，预算5000元',
  '必须去故宫和天坛，平时一直吃辣',
  '2026年8月24日去北京玩2天，锁定故宫博物院',
  '去上海玩2天，预算控制在2000以内',
]

// ── 鼠标光晕与星空 ──
function onMouseMove(e) {
  mouseX.value = e.clientX
  mouseY.value = e.clientY
}

function starStyle(i) {
  const x = (i * 37) % 100
  const y = (i * 61) % 100
  const delay = ((i * 13) % 40) / 10
  return {
    left: `${x}%`,
    top: `${y}%`,
    animationDelay: `${delay}s`,
  }
}

// ── 需求槽位安全读取 ──
function getSlotValue(key) {
  const slots = effectiveRequirements.value.slots || {}
  const slot = slots[key]
  return slot ? slot.value : null
}

function getPreferences() {
  const prefs = getSlotValue('preferences')
  return Array.isArray(prefs) ? prefs : []
}

function isItemLocked(name) {
  if (!name) return false
  return lockedItems.value.some(l => name.includes(l) || l.includes(name))
}

function getFactClass(fact) {
  if (!fact) return ''
  const st = fact.verification_status
  if (st === 'VERIFIED') return 'verified'
  if (st === 'CONFLICT') return 'conflict'
  return 'unverified'
}

function getFactLabel(fact) {
  if (!fact) return '待核验'
  const st = fact.verification_status
  if (st === 'VERIFIED') return '✅ 官方核验开放'
  if (st === 'CONFLICT') return '⚠️ 闭馆冲突(已自愈)'
  return '❓ 待确认'
}

// ── 简单轻量 Markdown 解析 ──
function renderMarkdown(text) {
  if (!text) return ''
  let html = text
    .replace(/^### (.*$)/gim, '<h3>$1</h3>')
    .replace(/^#### (.*$)/gim, '<h4>$1</h4>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^> \[\!TIP\]/gim, '<div class="md-alert tip"><strong>💡 系统自愈提示</strong>')
    .replace(/^> \[\!WARNING\]/gim, '<div class="md-alert warn"><strong>⚠️ 人工复核建议</strong>')
    .replace(/^> (.*$)/gim, '<div class="md-quote">$1</div>')
    .replace(/\n\n/g, '<br/><br/>')
    .replace(/\n/g, '<br/>')
  return html
}

function scrollToBottom() {
  nextTick(() => {
    if (chatHistoryRef.value) {
      chatHistoryRef.value.scrollTop = chatHistoryRef.value.scrollHeight
    }
  })
}

// ── 发送消息核心 (SSE Stream) ──
async function sendChatRequest(text, actionPayload = null) {
  if (isStreaming.value) return
  isStreaming.value = true
  currentThinking.value = []

  // 1. 若为用户文字输入，推入对话气泡
  if (text) {
    messages.value.push({
      id: Date.now(),
      role: 'user',
      content: text,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    })
  } else if (actionPayload) {
    messages.value.push({
      id: Date.now(),
      role: 'user',
      content: `选择选项：${actionPayload.value || JSON.stringify(actionPayload)}`,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    })
  }
  inputQuery.value = ''
  scrollToBottom()

  // 2. 准备助手消息占位
  const assistantMsg = reactive({
    id: Date.now() + 1,
    role: 'assistant',
    content: '',
    thinking: [],
    clarification: null,
    isThinkingOpen: true,
    isStreaming: true,
    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  })
  messages.value.push(assistantMsg)
  scrollToBottom()

  try {
    const endpoint = '/api/session/chat'
    const payload = {
      session_id: sessionId.value,
      input_text: text || '',
      action_type: actionPayload ? 'SET_SLOT' : null,
      action_payload: actionPayload,
      engine: 'harness',
    }

    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() // 保留未完成部分

      for (const chunk of chunks) {
        if (!chunk.trim()) continue
        const lines = chunk.split('\n')
        let eventName = ''
        let eventData = ''

        for (const line of lines) {
          if (line.startsWith('event:')) {
            eventName = line.replace('event:', '').trim()
          } else if (line.startsWith('data:')) {
            eventData = line.replace('data:', '').trim()
          }
        }

        if (!eventName || !eventData) continue

        let parsed
        try {
          parsed = JSON.parse(eventData)
        } catch {
          parsed = eventData
        }

        // 处理各通道事件
        if (eventName === 'thinking') {
          assistantMsg.thinking.push(parsed)
          currentThinking.value.push(parsed)
          scrollToBottom()
        } else if (eventName === 'tool_start') {
          const tName = parsed.tool || 'algorithm'
          const info = { step: 'tool_start', detail: `🛠️ 调度算法: ${tName}` }
          assistantMsg.thinking.push(info)
          currentThinking.value.push(info)
          scrollToBottom()
        } else if (eventName === 'tool_end') {
          const tSummary = parsed.summary || ''
          const tMs = parsed.duration_ms !== undefined ? ` (${parsed.duration_ms}ms)` : ''
          const info = { step: 'tool_end', detail: `✅ 完成: ${tSummary}${tMs}` }
          assistantMsg.thinking.push(info)
          currentThinking.value.push(info)
          scrollToBottom()
        } else if (eventName === 'invariant_violation') {
          const vList = parsed.violations || []
          const info = { step: 'invariant_violation', detail: `🛡️ 不变式拦截: ${vList.join('; ')}` }
          assistantMsg.thinking.push(info)
          currentThinking.value.push(info)
          scrollToBottom()
        } else if (eventName === 'clarification') {
          assistantMsg.clarification = parsed
          scrollToBottom()
        } else if (eventName === 'message' || eventName === 'message_delta') {
          const txt = parsed.delta !== undefined ? parsed.delta : (parsed.content || parsed)
          if (eventName === 'message_delta') {
            assistantMsg.content = (assistantMsg.content || '') + txt
          } else {
            assistantMsg.content = txt
          }
          scrollToBottom()
          saveSessionCache()
        } else if (eventName === 'plan_version') {
          currentPlan.value = parsed.plan || parsed
          if (parsed.locked_items) {
            lockedItems.value = parsed.locked_items
          }
          saveSessionCache()
          fetchSessionState()
        } else if (eventName === 'done') {
          assistantMsg.isStreaming = false
          assistantMsg.isThinkingOpen = false
          saveSessionCache()
        }
      }
    }
  } catch (err) {
    console.error('SSE 流式接收异常:', err)
    assistantMsg.content += `\n\n*(网络或接口异常: ${err.message})*`
    assistantMsg.isStreaming = false
  } finally {
    isStreaming.value = false
    saveSessionCache()
    scrollToBottom()
  }
}

function submitUserMessage() {
  const query = inputQuery.value.trim()
  if (!query) return
  sendChatRequest(query)
}

function handleEnter(e) {
  if (!e.shiftKey) {
    submitUserMessage()
  }
}

function handleOptionSelect(opt) {
  if (opt.payload) {
    sendChatRequest('', opt.payload)
  }
}

function applyQuickPrompt(text) {
  inputQuery.value = text
  submitUserMessage()
}

const CACHE_KEY_PREFIX = 'tp_state_'

// ── 本地快照持久化与双轨恢复 ──
function saveSessionCache() {
  try {
    const cachePayload = {
      messages: messages.value,
      effectiveRequirements: effectiveRequirements.value,
      currentPlan: currentPlan.value,
      lockedItems: lockedItems.value,
      attemptedActions: attemptedActions.value,
      updatedAt: Date.now(),
    }
    localStorage.setItem(CACHE_KEY_PREFIX + sessionId.value, JSON.stringify(cachePayload))
  } catch (e) {
    console.warn('保存会话本地快照失败:', e)
  }
}

function loadSessionCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY_PREFIX + sessionId.value)
    if (!raw) return false
    const parsed = JSON.parse(raw)
    if (parsed.messages && parsed.messages.length) {
      messages.value = parsed.messages
    }
    if (parsed.effectiveRequirements) {
      effectiveRequirements.value = parsed.effectiveRequirements
    }
    if (parsed.currentPlan) {
      currentPlan.value = parsed.currentPlan
    }
    if (parsed.lockedItems) {
      lockedItems.value = parsed.lockedItems
    }
    if (parsed.attemptedActions) {
      attemptedActions.value = parsed.attemptedActions
    }
    return true
  } catch (e) {
    console.warn('读取会话本地快照失败:', e)
    return false
  }
}

function clearSessionCache() {
  try {
    localStorage.removeItem(CACHE_KEY_PREFIX + sessionId.value)
  } catch (e) {}
}

// ── 查询三轨状态快照与断点同步 ──
async function fetchSessionState() {
  try {
    const isHarness = selectedEngine.value === 'harness'
    const endpoint = isHarness ? `/api/harness/session/${sessionId.value}/state` : `/api/session/${sessionId.value}/state`
    const res = await fetch(endpoint)
    if (!res.ok) return
    const data = await res.json()
    if (data.status === 'new') {
      return
    }

    const reqs = data.effective_requirements || data.requirements
    if (reqs && Object.keys(reqs).length) {
      effectiveRequirements.value = reqs
    }
    if (data.current_plan) {
      currentPlan.value = data.current_plan
    }
    if (data.locked_items && data.locked_items.length) {
      lockedItems.value = data.locked_items
    }
    if (data.attempted_actions && data.attempted_actions.length) {
      attemptedActions.value = data.attempted_actions
    }

    // 若本地消息流为空但服务端有消息，从服务端消息还原
    if ((!messages.value || messages.value.length <= 1) && data.messages && data.messages.length) {
      messages.value = data.messages.map((m, idx) => ({
        id: idx + 1,
        role: m.role || 'user',
        content: m.content || '',
        thinking: [],
        clarification: null,
        time: '先前记录',
      }))
    }

    // 若服务端存在未决的澄清提示，恢复挂起卡片
    if (data.pending_clarification) {
      const lastMsg = messages.value[messages.value.length - 1]
      if (lastMsg && lastMsg.role === 'assistant') {
        lastMsg.clarification = data.pending_clarification
      } else {
        messages.value.push({
          id: Date.now(),
          role: 'assistant',
          content: '请先完成以下信息的确认：',
          clarification: data.pending_clarification,
          time: '刚刚',
        })
      }
    }

    saveSessionCache()
    scrollToBottom()
  } catch (e) {
    console.warn('获取会话状态失败:', e)
  }
}

function resetSession() {
  clearSessionCache()
  const newId = 'sess_' + Math.random().toString(36).slice(2, 10)
  sessionId.value = newId
  localStorage.setItem('tp_session_id', newId)
  effectiveRequirements.value = { slots: {}, locked_items: [], revision_id: 1 }
  currentPlan.value = null
  lockedItems.value = []
  attemptedActions.value = []
  messages.value = [
    {
      id: Date.now(),
      role: 'assistant',
      content: '新会话已开启！请问您这次计划去哪里旅行呢？',
      thinking: [],
      clarification: null,
      time: '刚刚',
    }
  ]
  saveSessionCache()
}

onMounted(async () => {
  // 1. 本地快照秒级回填 (0ms 首屏无白屏)
  loadSessionCache()
  scrollToBottom()

  // 2. 异步服务端状态同步与断点核验
  await fetchSessionState()
})
</script>

<style scoped>
/* ── 全局与布局变量 ── */
.app-bg {
  min-height: 100vh;
  background: radial-gradient(circle at 50% 10%, #131929 0%, #090d16 100%);
  color: #f1f5f9;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  position: relative;
  overflow-x: hidden;
}

.cursor-spotlight {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  pointer-events: none;
  background: radial-gradient(600px circle at var(--mx, -999px) var(--my, -999px), rgba(99, 102, 241, 0.08), transparent 80%);
  z-index: 1;
}

.stars {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
}
.star {
  position: absolute;
  width: 2px;
  height: 2px;
  background: white;
  border-radius: 50%;
  opacity: 0.3;
  animation: twinkle 4s infinite ease-in-out;
}
@keyframes twinkle {
  0%, 100% { opacity: 0.2; transform: scale(1); }
  50% { opacity: 0.8; transform: scale(1.5); }
}

.bg-blob {
  position: fixed;
  filter: blur(100px);
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
  opacity: 0.35;
}
.bg-blob-1 { width: 450px; height: 450px; background: #4f46e5; top: -100px; left: -100px; }
.bg-blob-2 { width: 400px; height: 400px; background: #06b6d4; bottom: -80px; right: -80px; }
.bg-blob-3 { width: 350px; height: 350px; background: #ec4899; top: 40%; left: 35%; opacity: 0.15; }

.copilot-container {
  position: relative;
  z-index: 2;
  max-width: 1560px;
  margin: 0 auto;
  padding: 16px 24px;
  display: flex;
  flex-direction: column;
  height: 100vh;
  box-sizing: border-box;
}

/* ── 顶部 Header ── */
.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 14px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.logo-icon {
  font-size: 32px;
}
.header-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  background: linear-gradient(135deg, #ffffff 0%, #a5b4fc 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  display: flex;
  align-items: center;
  gap: 8px;
}
.badge-copilot {
  font-size: 11px;
  font-weight: 600;
  background: linear-gradient(135deg, #4f46e5, #06b6d4);
  color: white;
  padding: 2px 8px;
  border-radius: 12px;
  letter-spacing: 0.5px;
  -webkit-text-fill-color: initial;
}
.header-sub {
  margin: 2px 0 0 0;
  font-size: 12px;
  color: #94a3b8;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.engine-badge {
  display: flex;
  align-items: center;
}
.engine-pill {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(168, 85, 247, 0.2));
  border: 1px solid rgba(168, 85, 247, 0.45);
  color: #c084fc;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 9999px;
  box-shadow: 0 0 10px rgba(168, 85, 247, 0.15);
}
.session-badge {
  font-size: 12px;
  color: #cbd5e1;
  background: rgba(255, 255, 255, 0.06);
  padding: 4px 10px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.pulse-dot {
  width: 6px;
  height: 6px;
  background: #10b981;
  border-radius: 50%;
  box-shadow: 0 0 8px #10b981;
}
.btn-new-session {
  background: rgba(99, 102, 241, 0.18);
  border: 1px solid rgba(99, 102, 241, 0.4);
  color: #c7d2fe;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-new-session:hover {
  background: rgba(99, 102, 241, 0.35);
  color: white;
}

/* ── 主体双栏布局 ── */
.copilot-main {
  display: grid;
  grid-template-columns: 46% 54%;
  gap: 18px;
  flex: 1;
  min-height: 0;
}

.glass-panel {
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  padding: 12px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: #f8fafc;
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-subtitle {
  font-size: 12px;
  color: #64748b;
}
.plan-version-badge {
  font-size: 11px;
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 2px 8px;
  border-radius: 10px;
}

/* ── 左栏：聊天气泡流 ── */
.left-column {
  position: relative;
}
.chat-history {
  flex: 1;
  overflow-y: auto;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.chat-bubble-wrap {
  display: flex;
  gap: 12px;
  max-width: 90%;
}
.chat-bubble-wrap.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}
.bubble-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.bubble-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.chat-bubble-wrap.user .bubble-body {
  align-items: flex-end;
}
.bubble-text {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
}
.chat-bubble-wrap.user .bubble-text {
  background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%);
  color: white;
  border-bottom-right-radius: 2px;
}
.chat-bubble-wrap.assistant .bubble-text {
  background: rgba(30, 41, 59, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #e2e8f0;
  border-bottom-left-radius: 2px;
}
.bubble-meta {
  font-size: 11px;
  color: #64748b;
  padding: 0 4px;
}

/* ── 思考进度折叠区 ── */
.thinking-box {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(99, 102, 241, 0.25);
  border-radius: 10px;
  margin-bottom: 8px;
  overflow: hidden;
}
.thinking-header {
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 12px;
  color: #a5b4fc;
}
.thinking-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid #6366f1;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.thinking-title {
  flex: 1;
  font-weight: 500;
}
.thinking-toggle {
  font-size: 11px;
  opacity: 0.7;
}
.thinking-content {
  padding: 8px 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  background: rgba(0, 0, 0, 0.2);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.thinking-step {
  font-size: 12px;
  color: #94a3b8;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.step-num {
  font-size: 10px;
  background: rgba(99, 102, 241, 0.3);
  color: #c7d2fe;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

/* ── 澄清选择卡片 ── */
.clarification-card {
  background: rgba(30, 41, 59, 0.9);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 10px;
  padding: 12px;
  margin-top: 6px;
}
.clarification-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  color: #fbbf24;
  font-size: 13px;
  font-weight: 500;
}
.clarification-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.btn-option-chip {
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.35);
  color: #fde68a;
  padding: 6px 12px;
  border-radius: 20px;
  font-size: 13px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}
.btn-option-chip:hover:not(:disabled) {
  background: rgba(245, 158, 11, 0.3);
  transform: translateY(-1px);
}
.btn-option-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── 快捷 Prompt ── */
.quick-prompts {
  padding: 8px 18px;
  display: flex;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}
.prompt-hint {
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
}
.btn-quick-chip {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}
.btn-quick-chip:hover {
  background: rgba(99, 102, 241, 0.2);
  border-color: rgba(99, 102, 241, 0.4);
  color: #e0e7ff;
}

/* ── 输入区 ── */
.chat-input-area {
  padding: 12px 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  gap: 10px;
  align-items: flex-end;
  background: rgba(15, 23, 42, 0.4);
}
.chat-input {
  flex: 1;
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #f8fafc;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 14px;
  resize: none;
  outline: none;
  font-family: inherit;
  transition: border-color 0.2s;
}
.chat-input:focus {
  border-color: #6366f1;
}
.btn-send {
  background: linear-gradient(135deg, #4f46e5 0%, #06b6d4 100%);
  color: white;
  border: none;
  padding: 10px 18px;
  border-radius: 10px;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  transition: opacity 0.2s;
  height: 42px;
}
.btn-send:hover:not(:disabled) {
  opacity: 0.9;
}
.btn-send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ── 右栏：看板部分 ── */
.board-scrollable {
  flex: 1;
  overflow-y: auto;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 1. 三轨需求画像卡片 */
.effective-reqs-card {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 14px 16px;
}
.reqs-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  color: #f1f5f9;
  margin-bottom: 12px;
}
.reqs-sub {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 400;
}
.reqs-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.req-item {
  background: rgba(15, 23, 42, 0.6);
  padding: 8px 10px;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.req-label {
  font-size: 11px;
  color: #64748b;
}
.req-val {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
}
.req-val.highlight {
  color: #38bdf8;
}

.locked-section, .prefs-section {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.locked-label, .prefs-label {
  font-size: 12px;
  color: #94a3b8;
}
.locked-chips, .pref-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.locked-chip {
  background: rgba(239, 68, 68, 0.15);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.3);
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
}
.pref-chip {
  background: rgba(16, 185, 129, 0.15);
  color: #6ee7b7;
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
}

/* 2. 自愈优化条 */
.self-healing-banner {
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: 10px;
  padding: 10px 14px;
}
.banner-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #34d399;
  margin-bottom: 6px;
}
.banner-list {
  margin: 0;
  padding-left: 20px;
  font-size: 12px;
  color: #a7f3d0;
  line-height: 1.5;
}

/* 3. 分日行程卡片 */
.itinerary-days {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.day-card {
  background: rgba(30, 41, 59, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 14px;
}
.day-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 12px;
}
.day-badge {
  background: linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%);
  color: white;
  padding: 4px 10px;
  border-radius: 6px;
  font-weight: 700;
  font-size: 13px;
}
.day-date {
  font-size: 13px;
  font-weight: 500;
  color: #cbd5e1;
}
.day-meta {
  margin-left: auto;
  font-size: 12px;
  color: #64748b;
}

.attractions-timeline {
  display: flex;
  flex-direction: column;
  gap: 10px;
  position: relative;
  padding-left: 12px;
}
.timeline-item {
  position: relative;
}
.timeline-dot {
  position: absolute;
  left: -12px;
  top: 14px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #38bdf8;
  box-shadow: 0 0 6px #38bdf8;
}
.attraction-card {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 10px 12px;
}
.attr-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.attr-name-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
}
.attr-name {
  font-size: 14px;
  font-weight: 600;
  color: #f8fafc;
}
.lock-indicator {
  font-size: 11px;
  color: #f87171;
  background: rgba(239, 68, 68, 0.1);
  padding: 1px 4px;
  border-radius: 4px;
}
.attr-badges {
  display: flex;
  align-items: center;
  gap: 6px;
}
.amap-score-badge {
  background: rgba(234, 179, 8, 0.15);
  color: #facc15;
  border: 1px solid rgba(234, 179, 8, 0.4);
  font-size: 11px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
}
.amap-level-badge {
  background: rgba(168, 85, 247, 0.15);
  color: #c084fc;
  border: 1px solid rgba(168, 85, 247, 0.35);
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
}
.fact-badge {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
}
.fact-badge.verified {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.3);
}
.fact-badge.conflict {
  background: rgba(239, 68, 68, 0.15);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.3);
}
.fact-badge.unverified {
  background: rgba(245, 158, 11, 0.15);
  color: #fde68a;
  border: 1px solid rgba(245, 158, 11, 0.3);
}
.ticket-tag {
  font-size: 12px;
  font-weight: 600;
  color: #e2e8f0;
}

.attr-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 4px;
  flex-wrap: wrap;
}
.attr-meta .time-open {
  color: #38bdf8;
}
.attr-meta .area-tag {
  color: #a78bfa;
}

.attr-address-line {
  font-size: 11px;
  color: #94a3b8;
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 6px;
}
.addr-icon {
  font-size: 12px;
}
.addr-text {
  color: #cbd5e1;
}

.booking-notice {
  background: rgba(245, 158, 11, 0.08);
  border-left: 3px solid #f59e0b;
  padding: 4px 8px;
  border-radius: 0 4px 4px 0;
  font-size: 12px;
  color: #fde68a;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.guides-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}
.guide-item {
  font-size: 12px;
  line-height: 1.4;
  color: #cbd5e1;
}
.guide-tag {
  color: #38bdf8;
  font-weight: 600;
  margin-right: 4px;
}

.tavily-tips-box {
  background: rgba(14, 165, 233, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 6px;
  padding: 8px 10px;
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tavily-badge-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
  padding-bottom: 5px;
  border-bottom: 1px dashed rgba(56, 189, 248, 0.2);
}
.tavily-badge-pill {
  font-size: 11px;
  font-weight: 700;
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.15);
  padding: 2px 7px;
  border-radius: 4px;
  border: 1px solid rgba(56, 189, 248, 0.35);
  letter-spacing: 0.3px;
}
.tavily-badge-hint {
  font-size: 10px;
  color: #64748b;
}
.tavily-line {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  line-height: 1.45;
}
.tavily-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
  font-weight: 600;
  flex-shrink: 0;
}
.tavily-tag.booking {
  background: rgba(245, 158, 11, 0.2);
  color: #fde68a;
  border: 1px solid rgba(245, 158, 11, 0.35);
}
.tavily-tag.tip {
  background: rgba(14, 165, 233, 0.2);
  color: #7dd3fc;
  border: 1px solid rgba(56, 189, 248, 0.35);
}
.tavily-text {
  color: #cbd5e1;
  word-break: break-all;
}

/* 空状态 */
.empty-plan-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 60px 20px;
  color: #64748b;
}
.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
  opacity: 0.5;
}
.empty-title {
  font-size: 16px;
  font-weight: 600;
  color: #94a3b8;
  margin-bottom: 6px;
}
.empty-sub {
  font-size: 13px;
  max-width: 360px;
  line-height: 1.5;
}

/* ── 算法白盒度量卡片 ── */
.telemetry-card {
  background: rgba(14, 165, 233, 0.06);
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 12px;
  padding: 12px 16px;
  margin-bottom: 16px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}
.telemetry-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.telemetry-icon {
  font-size: 16px;
}
.telemetry-title {
  font-size: 13px;
  font-weight: 700;
  color: #38bdf8;
  letter-spacing: 0.5px;
}
.telemetry-tag {
  margin-left: auto;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(56, 189, 248, 0.15);
  color: #bae6fd;
  border: 1px solid rgba(56, 189, 248, 0.3);
}
.telemetry-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.telemetry-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  line-height: 1.5;
}
.t-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
  white-space: nowrap;
  margin-top: 2px;
}
.t-badge.green {
  background: rgba(16, 185, 129, 0.2);
  color: #6ee7b7;
}
.t-text {
  color: #cbd5e1;
}
.highlight-green {
  color: #6ee7b7;
}
.day-saved-tag {
  margin-left: 8px;
  font-size: 11px;
  color: #34d399;
  background: rgba(16, 185, 129, 0.15);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.time-tag {
  color: #38bdf8 !important;
  font-weight: 600;
}

/* ── 住宿推荐卡片 ── */
.day-hotel-card {
  margin-top: 12px;
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 10px;
  padding: 10px 14px;
  transition: all 0.2s ease;
}
.day-hotel-card:hover {
  border-color: rgba(56, 189, 248, 0.4);
  background: rgba(30, 41, 59, 0.8);
}
.hotel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.hotel-title-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
}
.hotel-icon {
  font-size: 16px;
}
.hotel-name {
  font-size: 13px;
  font-weight: 600;
  color: #f1f5f9;
}
.hotel-type-badge {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.3);
}
.hotel-price {
  font-size: 12px;
  font-weight: 700;
  color: #38bdf8;
}
.hotel-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #94a3b8;
}
.minimax-tag {
  color: #a7f3d0;
  background: rgba(16, 185, 129, 0.12);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}
.hotel-address {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 美食推荐卡片 ── */
.day-meals-card {
  margin-top: 10px;
  background: rgba(24, 24, 27, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 10px;
  padding: 10px 14px;
}
.meals-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.meals-icon {
  font-size: 15px;
}
.meals-title {
  font-size: 12px;
  font-weight: 600;
  color: #fb923c;
}
.meals-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.meal-badge-item {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255, 255, 255, 0.03);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
}
.meal-slot-label {
  font-size: 11px;
  font-weight: 600;
  color: #fdba74;
  white-space: nowrap;
}
.meal-info {
  flex: 1;
  min-width: 0;
}
.meal-top {
  display: flex;
  align-items: center;
  gap: 8px;
}
.meal-name {
  font-weight: 600;
  color: #f8fafc;
}
.meal-score {
  font-size: 11px;
  color: #facc15;
  font-weight: 700;
}
.meal-detail {
  font-size: 11px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meal-price {
  font-size: 11px;
  font-weight: 600;
  color: #e2e8f0;
  white-space: nowrap;
}

/* ── 每日高德天气胶囊 ── */
.day-weather-strip {
  margin: 10px 16px 6px 16px;
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.12) 0%, rgba(59, 130, 246, 0.06) 100%);
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.weather-main {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #38bdf8;
}
.weather-icon {
  font-size: 16px;
}
.weather-temp {
  color: #fb923c;
  font-weight: 700;
}
.weather-wind {
  color: #94a3b8;
  font-size: 12px;
}
.weather-source-badge {
  margin-left: auto;
  font-size: 11px;
  background: rgba(56, 189, 248, 0.18);
  color: #7dd3fc;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.weather-tip {
  font-size: 12px;
  color: #cbd5e1;
  line-height: 1.4;
  padding-left: 24px;
}

/* ── 响应式适配 ── */
@media (max-width: 1024px) {
  .copilot-main {
    grid-template-columns: 1fr;
    height: auto;
  }
  .copilot-container {
    height: auto;
  }
  .left-column, .right-column {
    height: 700px;
  }
}
</style>
