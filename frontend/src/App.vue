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

          <!-- 👤 多租户身份切换器 (面向面试工程化隔离演示) -->
          <div class="user-tenant-picker" title="切换租户身份，体验严格的会话、足迹与私有缓存隔离">
            <span class="user-pill-icon">👤</span>
            <select v-model="userId" @change="onUserChange" class="tenant-select">
              <option value="demo_traveler">演示租户 (demo)</option>
              <option value="alice_explorer">探索者 Alice</option>
              <option value="bob_foodie">美食家 Bob</option>
            </select>
          </div>

          <!-- 💖 旅行体温画像抽屉入口 -->
          <button class="btn-lifestyle" @click="isLifestyleDrawerOpen = true" title="查看并配置个性化旅行体温画像">
            <span>💖 旅行体温</span>
            <span class="lifestyle-badge">{{ paceLabel(userLifestyle.travel_pace) }}</span>
          </button>

          <!-- 👣 我的足迹抽屉入口 -->
          <button class="btn-footprints" @click="isFootprintDrawerOpen = true" title="查看并管理我的历史游览足迹">
            <span>👣 我的足迹</span>
            <span v-if="userFootprints.length" class="footprint-badge">{{ userFootprints.length }}</span>
          </button>

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
                  <span v-if="msg.isInterrupted" class="badge-status-pill badge-stopped">⏹️ 已中途停止</span>
                  <span v-if="msg.isSteered" class="badge-status-pill badge-steered">⚡ 已中途转向</span>
                  <span v-if="msg.isSteeringAction" class="badge-status-pill badge-steering-prompt">⚡ 中途改口</span>
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
              @click="applyQuickPrompt(p)"
            >
              {{ p }}
            </button>
          </div>

          <!-- 输入区：支持中途抢占转向 (Mid-turn Steering) -->
          <div class="chat-input-area">
            <textarea
              v-model="inputQuery"
              class="chat-input"
              rows="2"
              :placeholder="isStreaming ? '⚡ 正在流式规划中... 可随时输入新想法打断或改口！' : '输入旅行意图（如：我想去北京玩3天，预算5000元，必须去故宫，平时一直吃辣）...'"
              @keydown.enter.prevent="handleEnter"
            ></textarea>
            <div class="input-actions-group">
              <button
                v-if="isStreaming"
                class="btn-interrupt"
                title="立即停止当前生成"
                @click="interruptCurrentGeneration"
              >
                ⏹️ 停止生成
              </button>
              <button
                class="btn-send"
                :class="{ 'btn-steer': isStreaming && inputQuery.trim() }"
                :disabled="!inputQuery.trim() && !isStreaming"
                @click="submitUserMessage"
              >
                <span v-if="isStreaming && inputQuery.trim()">⚡ 抢占改口 🚀</span>
                <span v-else-if="isStreaming">
                  <span class="loading-spin"></span> 规划中...
                </span>
                <span v-else>发送 🚀</span>
              </button>
            </div>
          </div>
        </section>

        <!-- ════════ 右栏：三轨需求与实时行程看板 ════════ -->
        <section class="right-column glass-panel">
          <div class="panel-header">
            <div class="panel-title-group">
              <span class="icon">🧭</span>
              <span class="panel-main-title">空间探索与定制看板</span>
            </div>
            <!-- Pi 风格看板与动态地图双重视图切换器 -->
            <div class="view-switch-tabs">
              <button
                :class="['tab-btn', activeRightTab === 'board' ? 'active' : '']"
                @click="activeRightTab = 'board'"
              >
                📋 分日详情看板
              </button>
              <button
                :class="['tab-btn', activeRightTab === 'map' ? 'active' : '']"
                @click="activeRightTab = 'map'"
              >
                🗺️ 空间探索地图
                <span v-if="mapActionsCount > 0" class="tab-action-badge">{{ mapActionsCount }}</span>
              </button>
            </div>
            <div class="panel-actions" v-if="currentPlan">
              <span class="plan-version-badge">版本 v{{ currentPlan.version_id || 1 }}</span>
            </div>
          </div>

          <div v-show="activeRightTab === 'board'" class="board-scrollable">
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

            <!-- 💖 Pi 伴随式体温关怀卡片 -->
            <div v-if="currentPlan && currentPlan.lifestyle_care" class="lifestyle-care-card">
              <div class="care-header">
                <div class="care-title">
                  <span class="care-icon">🌡️</span>
                  <span>Pi 伴随式体温关怀</span>
                </div>
                <span class="care-pill">生理耐受度与生物钟自适应</span>
              </div>
              <div class="care-body">
                <p class="care-text">{{ currentPlan.lifestyle_care }}</p>
                <div v-if="currentPlan.lifestyle_profile" class="care-tags">
                  <span class="care-tag">
                    🏃 每日步数舒适圈: {{ currentPlan.lifestyle_profile.daily_walking_limit_km || 8 }}km
                  </span>
                  <span class="care-tag">
                    ⏰ 首站出发作息: {{ currentPlan.lifestyle_profile.morning_person ? '08:30 晨光早游' : '10:30 自然醒慢行' }}
                  </span>
                  <span class="care-tag">
                    👥 同行角色: {{ companionLabel(currentPlan.lifestyle_profile.companion_type) }}
                  </span>
                </div>
              </div>
            </div>

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
                    <span v-if="day.telemetry && day.telemetry.total_distance_km" class="day-walking-tag" :class="{ 'warning': day.telemetry.is_walking_exceeded }">
                      🚶 徒步 {{ day.telemetry.total_distance_km }}km (限 {{ day.telemetry.walking_limit_km }}km)
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

                <!-- 步数舒适度与体温关怀提示 -->
                <div v-if="day.telemetry && day.telemetry.pacing_hint" class="day-pacing-strip" :class="{ 'warning': day.telemetry.is_walking_exceeded }">
                  <span class="pacing-icon">{{ day.telemetry.is_walking_exceeded ? '⚠️' : '👟' }}</span>
                  <span class="pacing-text">{{ day.telemetry.pacing_hint }}</span>
                </div>

                <!-- 景点列表 (2-Opt 最优时序) -->
                <div class="attractions-timeline">
                  <div
                    v-for="(attr, aIdx) in day.attractions"
                    :key="aIdx"
                    class="timeline-item"
                  >
                    <div class="timeline-dot"></div>
                    <div :class="['attraction-card', isPoiVisited(attr.name) ? 'visited-card' : '']">
                      <div class="attr-header">
                        <div class="attr-name-wrap">
                          <span class="attr-name">{{ attr.name }}</span>
                          <span v-if="isItemLocked(attr.name)" class="lock-indicator" title="用户锁定项">🔒 锁定</span>
                          <span v-if="isPoiVisited(attr.name)" class="visited-indicator" title="已录入您的历史足迹库">👣 已打卡</span>
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
                          <!-- 💎 在地秘境 Badge -->
                          <span
                            v-if="attr.is_hidden_gem || attr.category === '在地秘境'"
                            class="gem-badge"
                            title="在地秘境：避开人潮的本地高美学私藏"
                          >
                            💎 在地秘境
                          </span>
                          <!-- 🧭 在空间地图中定位 -->
                          <button
                            class="btn-locate-map"
                            @click.stop="focusPoiOnMap(attr)"
                            title="在空间探索地图中定位此地"
                          >
                            🧭 空间定位
                          </button>
                          <!-- 👣 游览打卡/足迹标记按钮 -->
                          <button
                            :class="['btn-footprint-tag', isPoiVisited(attr.name) ? 'is-visited' : '']"
                            :title="isPoiVisited(attr.name) ? '点击取消打卡' : '标记已去过，下次规划该城市将自动避开'"
                            @click.stop="toggleFootprint(attr.name, currentPlan?.city || getSlotValue('city') || '北京')"
                          >
                            {{ isPoiVisited(attr.name) ? '✓ 已打卡' : '👣 去过?' }}
                          </button>
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

                      <!-- 💎 秘境推荐理由 -->
                      <div v-if="attr.reason" class="attr-gem-reason">
                        ✨ <strong>秘境特色</strong>：{{ attr.reason }}
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

          <!-- 视图 B：Pi 风格 Agent as Map Controller 动态空间地图与在地探索中枢 -->
          <div v-show="activeRightTab === 'map'" class="map-scrollable">
            <!-- 地图控制顶栏 -->
            <div class="map-control-bar">
              <div class="viewport-info">
                <span class="vp-icon">📍</span>
                <span class="vp-text">
                  视口: <strong>{{ mapViewport.city || getSlotValue('city') || '全国' }}</strong>
                  <span class="vp-coord" v-if="mapViewport.center && mapViewport.center.length >= 2">
                    ({{ Number(mapViewport.center[0]).toFixed(3) }}, {{ Number(mapViewport.center[1]).toFixed(3) }})
                  </span>
                  · 缩放: Lv.{{ mapViewport.zoom || 12 }}
                </span>
              </div>
              <div class="map-layer-toggles">
                <label class="layer-toggle" title="切换路径折线显示">
                  <input type="checkbox" v-model="mapLayers.routes" />
                  <span>路线</span>
                </label>
                <label class="layer-toggle" title="切换 Minimax 酒店 15min 步行等时圈显示">
                  <input type="checkbox" v-model="mapLayers.isochrone" />
                  <span>等时圈</span>
                </label>
                <label class="layer-toggle" title="切换在地秘境打卡点显示">
                  <input type="checkbox" v-model="mapLayers.gems" />
                  <span>💎 秘境</span>
                </label>
              </div>
            </div>

            <!-- SVG 交互式空间地图画布 -->
            <div class="svg-map-wrapper">
              <svg
                class="vector-map-canvas"
                viewBox="0 0 800 460"
                preserveAspectRatio="xMidYMid meet"
              >
                <defs>
                  <!-- 网格图案 -->
                  <pattern id="mapGrid" width="40" height="40" patternUnits="userSpaceOnUse">
                    <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255, 255, 255, 0.05)" stroke-width="1"/>
                  </pattern>
                  <!-- 酒店等时圈径向渐变 -->
                  <radialGradient id="isochroneGrad" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stop-color="rgba(56, 189, 248, 0.28)" />
                    <stop offset="70%" stop-color="rgba(56, 189, 248, 0.08)" />
                    <stop offset="100%" stop-color="rgba(56, 189, 248, 0)" />
                  </radialGradient>
                  <!-- 秘境发光微光 -->
                  <radialGradient id="gemGrad" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stop-color="rgba(244, 114, 182, 0.6)" />
                    <stop offset="100%" stop-color="rgba(244, 114, 182, 0)" />
                  </radialGradient>
                </defs>

                <!-- 背景网格与底色 -->
                <rect width="800" height="460" fill="#0c121e" rx="12" />
                <rect width="800" height="460" fill="url(#mapGrid)" rx="12" />

                <!-- 罗盘指示器 -->
                <g class="compass-rose" transform="translate(750, 45)">
                  <circle r="18" fill="rgba(15, 23, 42, 0.7)" stroke="rgba(255, 255, 255, 0.15)" stroke-width="1" />
                  <polygon points="0,-14 4,-2 0,0 -4,-2" fill="#ef4444" />
                  <polygon points="0,14 4,2 0,0 -4,2" fill="#94a3b8" />
                  <text y="-18" text-anchor="middle" font-size="9" fill="#f87171" font-weight="bold">N</text>
                </g>

                <!-- 比例尺 -->
                <g class="map-scale" transform="translate(30, 435)">
                  <line x1="0" y1="0" x2="60" y2="0" stroke="rgba(255, 255, 255, 0.4)" stroke-width="2" />
                  <line x1="0" y1="-4" x2="0" y2="4" stroke="rgba(255, 255, 255, 0.4)" stroke-width="2" />
                  <line x1="60" y1="-4" x2="60" y2="4" stroke="rgba(255, 255, 255, 0.4)" stroke-width="2" />
                  <text x="30" y="-6" text-anchor="middle" font-size="10" fill="rgba(255, 255, 255, 0.5)">~5 km</text>
                </g>

                <!-- 1. Minimax 酒店 15min 步行等时圈 -->
                <g v-if="mapLayers.isochrone && projectedMapData.isochroneCircle" class="isochrone-group">
                  <circle
                    :cx="projectedMapData.isochroneCircle.cx"
                    :cy="projectedMapData.isochroneCircle.cy"
                    :r="projectedMapData.isochroneCircle.r"
                    fill="url(#isochroneGrad)"
                    stroke="#38bdf8"
                    stroke-width="1.5"
                    stroke-dasharray="4,4"
                    class="pulsing-isochrone-ring"
                  />
                  <text
                    :x="projectedMapData.isochroneCircle.cx"
                    :y="projectedMapData.isochroneCircle.cy + projectedMapData.isochroneCircle.r + 14"
                    text-anchor="middle"
                    fill="#38bdf8"
                    font-size="10"
                    font-weight="bold"
                    class="map-svg-label"
                  >
                    🚶 15min 步行商圈 (3km)
                  </text>
                </g>

                <!-- 2. 日程 2-Opt 路径折线 -->
                <g v-if="mapLayers.routes">
                  <g v-for="r in projectedMapData.routes" :key="'route-' + r.day" class="route-line-group">
                    <path
                      :d="r.path"
                      fill="none"
                      :stroke="r.color"
                      stroke-width="3.5"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      class="animated-route-path"
                    />
                  </g>
                </g>

                <!-- 3. Minimax 酒店中心点 -->
                <g
                  v-if="projectedMapData.hotelNode"
                  class="map-node hotel-node"
                  :transform="`translate(${projectedMapData.hotelNode.x}, ${projectedMapData.hotelNode.y})`"
                  @click="selectMapPoi({ name: projectedMapData.hotelNode.name, category: 'Minimax 商圈酒店', type: 'hotel', price: '含在预算', note: '极小化每日通勤中心' })"
                >
                  <circle r="16" fill="rgba(14, 165, 233, 0.2)" class="beacon-pulse" />
                  <circle r="12" fill="#0284c7" stroke="#38bdf8" stroke-width="2" />
                  <text y="4" text-anchor="middle" font-size="12">🏨</text>
                  <text y="-16" text-anchor="middle" fill="#7dd3fc" font-size="11" font-weight="bold" class="map-node-label">
                    {{ projectedMapData.hotelNode.name }}
                  </text>
                </g>

                <!-- 4. 景点 POI 节点 -->
                <g v-if="mapLayers.pois">
                  <g
                    v-for="(p, pIdx) in projectedMapData.poiNodes"
                    :key="'poi-' + pIdx"
                    class="map-node poi-node"
                    :transform="`translate(${p.x}, ${p.y})`"
                    @click="selectMapPoi(p)"
                  >
                    <!-- 悬浮微光 -->
                    <circle r="15" fill="rgba(255, 255, 255, 0.08)" />
                    <!-- 主圆点 -->
                    <circle
                      r="10"
                      :fill="isItemLocked(p.name) ? '#f59e0b' : (isPoiVisited(p.name) ? '#10b981' : '#3b82f6')"
                      stroke="#ffffff"
                      stroke-width="1.5"
                    />
                    <!-- 编号标签 -->
                    <text y="3.5" text-anchor="middle" fill="#ffffff" font-size="8.5" font-weight="bold">
                      {{ p.day }}-{{ p.order }}
                    </text>
                    <!-- 文本名称 -->
                    <text
                      y="20"
                      text-anchor="middle"
                      fill="#e2e8f0"
                      font-size="10.5"
                      font-weight="500"
                      class="map-node-label"
                    >
                      {{ p.name }}
                    </text>
                  </g>
                </g>

                <!-- 5. 在地秘境脉冲节点 (Pi Serendipity Spotlight) -->
                <g v-if="mapLayers.gems">
                  <g
                    v-for="(g, gIdx) in projectedMapData.gemNodes"
                    :key="'gem-' + gIdx"
                    class="map-node gem-node"
                    :transform="`translate(${g.x}, ${g.y})`"
                    @click="selectMapPoi(g)"
                  >
                    <circle r="22" fill="url(#gemGrad)" class="gem-pulse" />
                    <circle r="13" fill="#be185d" stroke="#f472b6" stroke-width="2" />
                    <text y="4" text-anchor="middle" font-size="11">💎</text>
                    <text y="-17" text-anchor="middle" fill="#f472b6" font-size="10.5" font-weight="bold" class="map-node-label">
                      {{ g.name }}
                    </text>
                  </g>
                </g>
              </svg>

              <!-- 悬浮选定节点详情浮层 (Interactive POI Inspector) -->
              <Transition name="fade">
                <div v-if="selectedMapNode" class="poi-inspector-overlay">
                  <div class="inspector-card glass-panel">
                    <div class="inspector-header">
                      <div class="inspector-title">
                        <span class="inspector-icon">{{ selectedMapNode.type === 'gem' ? '💎' : (selectedMapNode.type === 'hotel' ? '🏨' : '📍') }}</span>
                        <strong>{{ selectedMapNode.name }}</strong>
                        <span v-if="selectedMapNode.type === 'gem'" class="badge-gem">在地秘境</span>
                        <span v-if="isPoiVisited(selectedMapNode.name)" class="badge-visited">✓ 已打卡</span>
                      </div>
                      <button class="btn-close-inspector" @click="selectedMapNode = null">✕</button>
                    </div>
                    <div class="inspector-body">
                      <div v-if="selectedMapNode.reason" class="inspector-reason">
                        ✨ <strong>秘境特色</strong>：{{ selectedMapNode.reason }}
                      </div>
                      <div class="inspector-meta-row">
                        <span v-if="selectedMapNode.rating" class="meta-tag">⭐ {{ selectedMapNode.rating }}分</span>
                        <span v-if="selectedMapNode.arrive_time" class="meta-tag">⏰ {{ selectedMapNode.arrive_time }} - {{ selectedMapNode.depart_time }}</span>
                        <span v-if="selectedMapNode.price !== undefined" class="meta-tag">🎫 ¥{{ selectedMapNode.price }}</span>
                        <span v-if="selectedMapNode.walking_minutes" class="meta-tag">🚶 {{ selectedMapNode.walking_minutes }}min 步行商圈</span>
                      </div>
                    </div>
                  </div>
                </div>
              </Transition>
            </div>

            <!-- Agent as Map Controller 实时调度事件流面板 (Controller Feed) -->
            <div class="map-action-feed-box">
              <div class="feed-header">
                <span class="feed-icon">🤖</span>
                <span class="feed-title">Agent 地图控制器实时调度记录 (Agent as Map Controller)</span>
                <span class="feed-count">{{ mapActionFeed.length }} 条动作</span>
              </div>
              <div class="feed-list" v-if="mapActionFeed.length">
                <div v-for="(act, idx) in mapActionFeed" :key="idx" class="feed-item">
                  <span class="feed-badge">{{ act.badge }} {{ act.action }}</span>
                  <span class="feed-detail">{{ act.detail }}</span>
                  <span class="feed-time">{{ act.time }}</span>
                </div>
              </div>
              <div v-else class="feed-empty">
                暂无地图控制动作。在左侧发送规划需求，Agent 将实时接管视口并绘制 2-Opt 最优空间路径。
              </div>
            </div>
          </div>
        </section>
      </main>

      <!-- ════════ 全息足迹图谱抽屉 (Footprint Drawer) ════════ -->
      <Transition name="fade">
        <div v-if="isFootprintDrawerOpen" class="drawer-overlay" @click.self="isFootprintDrawerOpen = false">
          <div class="footprint-drawer glass-panel">
            <div class="drawer-header">
              <div class="drawer-title">
                <span class="drawer-icon">👣</span>
                <span>我的历史游览足迹</span>
                <span class="drawer-badge">{{ userFootprints.length }} 处已打卡</span>
              </div>
              <button class="btn-close-drawer" @click="isFootprintDrawerOpen = false" title="关闭">✕</button>
            </div>

            <div class="drawer-sub">
              💡 <strong>智能避开机制</strong>：下次规划同城行程时，Harness 将自动过滤已打卡名胜，为您推荐全新未游览景点（除非在对话中显式锁定）。
            </div>

            <!-- 城市分组足迹列表 -->
            <div class="drawer-body">
              <div v-if="Object.keys(groupedFootprints).length === 0" class="empty-footprints">
                <span class="empty-icon">🗺️</span>
                <p class="empty-text">暂无已打卡游览足迹</p>
                <span class="empty-sub">在右侧行程卡片中点击“去过?”打卡，或在下方手动录入历史去过的景点。</span>
              </div>

              <div v-for="(pois, cityName) in groupedFootprints" :key="cityName" class="city-footprint-group">
                <div class="city-group-header">
                  <span class="city-icon">📍</span>
                  <span class="city-name">{{ cityName }}</span>
                  <span class="city-count">{{ pois.length }} 处名胜</span>
                </div>
                <div class="city-poi-chips">
                  <div v-for="item in pois" :key="item.id || item.poi_name" class="footprint-chip">
                    <span class="chip-name">{{ item.poi_name }}</span>
                    <button class="btn-remove-chip" @click="removeFootprintItem(item)" title="移除此足迹，后续规划可重新推荐">✕</button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 手动录入打卡区 -->
            <div class="drawer-footer">
              <div class="manual-input-title">➕ 手动录入历史足迹：</div>
              <div class="manual-input-row">
                <input v-model="newFootprintCity" class="input-city" placeholder="城市 (如 北京)" />
                <input v-model="newFootprintPoi" class="input-poi" placeholder="景点名称 (如 故宫博物院)" @keydown.enter="addManualFootprint" />
                <button class="btn-add-footprint" :disabled="isAddingFootprint || !newFootprintPoi.trim()" @click="addManualFootprint">
                  {{ isAddingFootprint ? '录入中...' : '+ 立即打卡' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </Transition>

      <!-- ════════ 旅行体温画像与伴随关怀抽屉 (Lifestyle Drawer) ════════ -->
      <Transition name="fade">
        <div v-if="isLifestyleDrawerOpen" class="drawer-overlay" @click.self="isLifestyleDrawerOpen = false">
          <div class="lifestyle-drawer glass-panel">
            <div class="drawer-header">
              <div class="drawer-title">
                <span class="drawer-icon">💖</span>
                <span>旅行体温画像与伴随关怀</span>
                <span class="lifestyle-drawer-badge">{{ paceLabel(userLifestyle.travel_pace) }}</span>
              </div>
              <button class="btn-close-drawer" @click="isLifestyleDrawerOpen = false" title="关闭">✕</button>
            </div>

            <div class="lifestyle-drawer-sub">
              🌡️ <strong>生理节律与耐受度白盒化</strong>：Harness 依据该画像自适应调整每日首站时间、计算徒步距离上限并进行关怀提示。
            </div>

            <div class="drawer-body">
              <!-- 1. 旅行节奏 -->
              <div class="form-group">
                <label class="form-label">🏃 旅行节奏偏好：</label>
                <div class="pace-options">
                  <div
                    class="pace-card"
                    :class="{ active: userLifestyle.travel_pace === 'relaxed' }"
                    @click="userLifestyle.travel_pace = 'relaxed'"
                  >
                    <div class="card-title">🐢 松弛慢调</div>
                    <div class="card-desc">每日少景点、留足茶歇放空</div>
                  </div>
                  <div
                    class="pace-card"
                    :class="{ active: userLifestyle.travel_pace === 'balanced' }"
                    @click="userLifestyle.travel_pace = 'balanced'"
                  >
                    <div class="card-title">⚖️ 均衡深度</div>
                    <div class="card-desc">兼顾打卡与体验、张弛有度</div>
                  </div>
                  <div
                    class="pace-card"
                    :class="{ active: userLifestyle.travel_pace === 'intense' }"
                    @click="userLifestyle.travel_pace = 'intense'"
                  >
                    <div class="card-title">⚡ 特种兵充沛</div>
                    <div class="card-desc">早出晚归、密集探索拉满</div>
                  </div>
                </div>
              </div>

              <!-- 2. 作息与生物钟 -->
              <div class="form-group">
                <label class="form-label">⏰ 作息习惯与首站出发：</label>
                <div class="morning-options">
                  <div
                    class="morning-card"
                    :class="{ active: !userLifestyle.morning_person }"
                    @click="userLifestyle.morning_person = false"
                  >
                    <div class="card-title">☀️ 松弛晚起 (10:30 出发)</div>
                    <div class="card-desc">睡到自然醒，从容午前后出发</div>
                  </div>
                  <div
                    class="morning-card"
                    :class="{ active: userLifestyle.morning_person }"
                    @click="userLifestyle.morning_person = true"
                  >
                    <div class="card-title">🌅 晨起早游 (08:30 出发)</div>
                    <div class="card-desc">早鸟早市，清晨避开人流高峰</div>
                  </div>
                </div>
              </div>

              <!-- 3. 每日步行耐受度上限 -->
              <div class="form-group">
                <div class="slider-header">
                  <label class="form-label">🚶 每日步行耐受红线：</label>
                  <span class="slider-val">{{ userLifestyle.daily_walking_limit_km }} km / 天</span>
                </div>
                <input
                  type="range"
                  min="4.0"
                  max="18.0"
                  step="0.5"
                  v-model.number="userLifestyle.daily_walking_limit_km"
                  class="km-slider"
                />
                <div class="slider-hint">
                  <span v-if="userLifestyle.daily_walking_limit_km <= 6.5">🍃 轻度舒适：适合老幼同行、推车漫步或休养型旅游</span>
                  <span v-else-if="userLifestyle.daily_walking_limit_km <= 10.5">👟 标准健康：适合常规自由行与城市探店</span>
                  <span v-else>🧗 特训健步：高强度体力耐受，能走能逛不觉累</span>
                </div>
              </div>

              <!-- 4. 同行伙伴特征 -->
              <div class="form-group">
                <label class="form-label">👥 出行伙伴画像：</label>
                <div class="companion-chips">
                  <button
                    v-for="item in companionList"
                    :key="item.key"
                    class="btn-companion-chip"
                    :class="{ active: userLifestyle.companion_type === item.key }"
                    @click="userLifestyle.companion_type = item.key"
                  >
                    <span>{{ item.icon }} {{ item.label }}</span>
                  </button>
                </div>
              </div>

              <!-- 5. 关怀细分标签 -->
              <div class="form-group">
                <label class="form-label">🏷️ 专项关怀偏好：</label>
                <div class="care-chips">
                  <button
                    v-for="tag in availableCareTags"
                    :key="tag.key"
                    class="btn-care-chip"
                    :class="{ active: userLifestyle.special_needs?.includes(tag.key) }"
                    @click="toggleSpecialNeed(tag.key)"
                  >
                    {{ tag.label }}
                  </button>
                </div>
              </div>
            </div>

            <!-- 抽屉底部保存操作栏 -->
            <div class="drawer-footer">
              <div class="invalidation-notice">
                ⚡ <strong>定向缓存失效</strong>：保存后将自动清除该租户私有缓存，下轮规划将按新时序与体能线重算。
              </div>
              <button
                class="btn-save-lifestyle"
                :disabled="isSavingLifestyle"
                @click="saveUserLifestyle"
              >
                {{ isSavingLifestyle ? '正在同步画像...' : '💾 保存体温画像并同步记忆' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick } from 'vue'

// ── 多租户身份与会话状态定义 ──
const userId = ref(localStorage.getItem('tp_user_id') || 'demo_traveler')
const sessionId = ref(localStorage.getItem('tp_session_id') || ('sess_' + Math.random().toString(36).slice(2, 10)))
localStorage.setItem('tp_session_id', sessionId.value)
localStorage.setItem('tp_user_id', userId.value)

// ── 生活方式体温画像状态 (Lifestyle & Wellness) ──
const isLifestyleDrawerOpen = ref(false)
const isSavingLifestyle = ref(false)
const userLifestyle = ref({
  user_id: userId.value,
  travel_pace: 'balanced',
  morning_person: false,
  daily_walking_limit_km: 8.0,
  companion_type: 'couple',
  special_needs: [],
  aesthetic_taste: [],
})

const companionList = [
  { key: 'solo', icon: '🎒', label: '独行自由' },
  { key: 'couple', icon: '🥂', label: '情侣伴侣' },
  { key: 'family_with_kids', icon: '🧸', label: '亲子家庭' },
  { key: 'elderly', icon: '👵', label: '长辈同行' },
  { key: 'pet_lover', icon: '🐾', label: '携宠漫步' },
]

const availableCareTags = [
  { key: 'tea_breaks', label: '☕ 午后茶歇' },
  { key: 'avoid_crowds', label: '🧘 避开拥挤' },
  { key: 'stroller_friendly', label: '👶 推车友好' },
  { key: 'barrier_free', label: '♿ 无障碍通道' },
  { key: 'night_market', label: '🍢 市井烟火' },
  { key: 'historic_streets', label: '🏛️ 老街慢步' },
]

function paceLabel(pace) {
  const map = {
    relaxed: '松弛慢调',
    balanced: '均衡深度',
    intense: '特种兵充沛',
  }
  return map[pace] || '均衡深度'
}

function companionLabel(comp) {
  const map = {
    solo: '独行自由',
    couple: '情侣伴侣',
    family_with_kids: '亲子家庭',
    elderly: '长辈同行',
    pet_lover: '携宠漫步',
  }
  return map[comp] || '自由同游'
}

function toggleSpecialNeed(tag) {
  if (!userLifestyle.value.special_needs) {
    userLifestyle.value.special_needs = []
  }
  const list = userLifestyle.value.special_needs
  const idx = list.indexOf(tag)
  if (idx >= 0) {
    list.splice(idx, 1)
  } else {
    list.push(tag)
  }
}

async function loadUserLifestyle() {
  try {
    const res = await fetch(`/api/user/${userId.value}/lifestyle`)
    if (res.ok) {
      const data = await res.json()
      userLifestyle.value = {
        ...userLifestyle.value,
        ...data,
        morning_person: Boolean(data.morning_person),
        daily_walking_limit_km: Number(data.daily_walking_limit_km || 8.0),
        special_needs: Array.isArray(data.special_needs) ? data.special_needs : [],
        aesthetic_taste: Array.isArray(data.aesthetic_taste) ? data.aesthetic_taste : [],
      }
    }
  } catch (e) {
    console.error('加载生活方式画像失败', e)
  }
}

async function saveUserLifestyle() {
  isSavingLifestyle.value = true
  try {
    const payload = {
      travel_pace: userLifestyle.value.travel_pace,
      morning_person: Boolean(userLifestyle.value.morning_person),
      daily_walking_limit_km: Number(userLifestyle.value.daily_walking_limit_km),
      companion_type: userLifestyle.value.companion_type,
      special_needs: userLifestyle.value.special_needs,
      aesthetic_taste: userLifestyle.value.aesthetic_taste,
    }
    const res = await fetch(`/api/user/${userId.value}/lifestyle`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.lifestyle) {
        userLifestyle.value = {
          ...userLifestyle.value,
          ...data.lifestyle,
          morning_person: Boolean(data.lifestyle.morning_person),
        }
      }
      isLifestyleDrawerOpen.value = false
    }
  } catch (e) {
    console.error('保存生活方式画像失败', e)
  } finally {
    isSavingLifestyle.value = false
  }
}

// ── 足迹管理状态 ──
const userFootprints = ref([])
const isFootprintDrawerOpen = ref(false)
const newFootprintCity = ref('北京')
const newFootprintPoi = ref('')
const isAddingFootprint = ref(false)

const groupedFootprints = computed(() => {
  const map = {}
  for (const f of userFootprints.value) {
    const c = f.city || '其他城市'
    if (!map[c]) map[c] = []
    map[c].push(f)
  }
  return map
})

async function loadUserFootprints() {
  try {
    const res = await fetch(`/api/user/${userId.value}/footprint`)
    if (res.ok) {
      const data = await res.json()
      userFootprints.value = data.footprints || []
    }
  } catch (e) {
    console.error('加载用户足迹失败', e)
  }
}

function isPoiVisited(poiName) {
  if (!poiName) return false
  return userFootprints.value.some(f => f.poi_name === poiName)
}

async function toggleFootprint(poiName, city) {
  if (!poiName) return
  const targetCity = city || currentPlan.value?.city || getSlotValue('city') || '北京'
  const alreadyVisited = isPoiVisited(poiName)
  try {
    if (alreadyVisited) {
      const res = await fetch(`/api/user/${userId.value}/footprint`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ poi_name: poiName, city: targetCity }),
      })
      if (res.ok) {
        userFootprints.value = userFootprints.value.filter(f => f.poi_name !== poiName)
      }
    } else {
      const res = await fetch(`/api/user/${userId.value}/footprint`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ poi_name: poiName, city: targetCity }),
      })
      if (res.ok) {
        userFootprints.value.unshift({
          id: Date.now(),
          user_id: userId.value,
          poi_name: poiName,
          city: targetCity,
          visited_at: new Date().toISOString(),
        })
      }
    }
  } catch (e) {
    console.error('打卡操作失败', e)
  }
}

async function addManualFootprint() {
  if (!newFootprintPoi.value.trim()) return
  isAddingFootprint.value = true
  try {
    const city = newFootprintCity.value.trim() || '北京'
    const poi = newFootprintPoi.value.trim()
    const res = await fetch(`/api/user/${userId.value}/footprint`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ poi_name: poi, city }),
    })
    if (res.ok) {
      await loadUserFootprints()
      newFootprintPoi.value = ''
    }
  } catch (e) {
    console.error('手动添加足迹失败', e)
  } finally {
    isAddingFootprint.value = false
  }
}

async function removeFootprintItem(item) {
  try {
    const res = await fetch(`/api/user/${userId.value}/footprint`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ poi_name: item.poi_name, city: item.city }),
    })
    if (res.ok) {
      userFootprints.value = userFootprints.value.filter(
        f => f.id !== item.id && !(f.poi_name === item.poi_name && f.city === item.city)
      )
    }
  } catch (e) {
    console.error('移除足迹失败', e)
  }
}

function onUserChange() {
  localStorage.setItem('tp_user_id', userId.value)
  resetSession()
  loadUserFootprints()
  loadUserLifestyle()
}

const mouseX = ref(0)
const mouseY = ref(0)

const inputQuery = ref('')
const isStreaming = ref(false)
const activeAbortController = ref(null)
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

// ── Pi 风格地图与在地探索状态 (Agent as Map Controller) ──
const activeRightTab = ref('board') // 'board' | 'map'
const mapActionsCount = ref(0)
const mapViewport = ref({ city: '北京', center: [116.407, 39.904], zoom: 12, title: '' })
const mapIsochrone = ref(null) // { hotel_name, coords, radius_km, walking_minutes }
const mapRoutes = ref([]) // [ { day_number, polyline, color, poi_names } ]
const mapSpotlights = ref([]) // [ { poi, coords, tag, category, reason } ]
const mapActionFeed = ref([]) // [ { time, action, badge, detail } ]
const selectedMapNode = ref(null)
const mapLayers = reactive({ routes: true, isochrone: true, gems: true, pois: true })

function selectMapPoi(poi) {
  selectedMapNode.value = poi
}

function focusPoiOnMap(attr) {
  activeRightTab.value = 'map'
  selectedMapNode.value = {
    name: attr.name,
    category: attr.category || (attr.is_hidden_gem ? '在地秘境' : '精选景点'),
    price: attr.price || attr.ticket_price || 0,
    rating: attr.rating,
    arrive_time: attr.arrive_time,
    depart_time: attr.depart_time,
    reason: attr.reason,
    type: attr.is_hidden_gem ? 'gem' : 'attraction',
  }
}

// ── 矢量空间地图几何投影算法 (SVG Normalizer) ──
const projectedMapData = computed(() => {
  const points = []

  // 1. 酒店中心
  if (mapIsochrone.value && mapIsochrone.value.coords && mapIsochrone.value.coords.length >= 2) {
    points.push({
      lng: parseFloat(mapIsochrone.value.coords[0]),
      lat: parseFloat(mapIsochrone.value.coords[1]),
      type: 'hotel',
    })
  }

  // 2. 日程景点
  if (currentPlan.value && currentPlan.value.days) {
    currentPlan.value.days.forEach((d) => {
      ;(d.attractions || []).forEach((a, idx) => {
        if (a.lng && a.lat) {
          points.push({
            lng: parseFloat(a.lng),
            lat: parseFloat(a.lat),
            name: a.name,
            day: d.day_number || d.day_index + 1,
            order: idx + 1,
            price: a.price || a.ticket_price || 0,
            rating: a.rating,
            is_hidden_gem: a.is_hidden_gem || a.category === '在地秘境',
            reason: a.reason,
            arrive_time: a.arrive_time,
            depart_time: a.depart_time,
            type: 'attraction',
          })
        }
      })
    })
  }

  // 3. 在地秘境打卡点
  mapSpotlights.value.forEach((s) => {
    if (s.coords && s.coords.length === 2) {
      points.push({
        lng: parseFloat(s.coords[0]),
        lat: parseFloat(s.coords[1]),
        name: s.poi,
        tag: s.tag || '在地秘境',
        reason: s.reason,
        category: s.category,
        type: 'gem',
      })
    }
  })

  // 若无点，兜底使用当前视口中心
  if (points.length === 0) {
    const c = mapViewport.value.center || [116.407, 39.904]
    points.push({ lng: parseFloat(c[0]), lat: parseFloat(c[1]), name: mapViewport.value.city || '城市中心', type: 'center' })
  }

  const lngs = points.map(p => p.lng)
  const lats = points.map(p => p.lat)

  let minLng = Math.min(...lngs)
  let maxLng = Math.max(...lngs)
  let minLat = Math.min(...lats)
  let maxLat = Math.max(...lats)

  const padLng = Math.max((maxLng - minLng) * 0.25, 0.06)
  const padLat = Math.max((maxLat - minLat) * 0.25, 0.04)

  minLng -= padLng
  maxLng += padLng
  minLat -= padLat
  maxLat += padLat

  const width = 800
  const height = 460
  const padding = 55

  function project(lng, lat) {
    const x = padding + ((lng - minLng) / (maxLng - minLng)) * (width - 2 * padding)
    const y = height - (padding + ((lat - minLat) / (maxLat - minLat)) * (height - 2 * padding))
    return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 }
  }

  // 酒店节点与等时圈投影
  let hotelNode = null
  let isochroneCircle = null
  if (mapIsochrone.value && mapIsochrone.value.coords && mapIsochrone.value.coords.length >= 2) {
    const hp = project(mapIsochrone.value.coords[0], mapIsochrone.value.coords[1])
    hotelNode = {
      ...hp,
      name: mapIsochrone.value.hotel_name || '商圈核心酒店',
      walking_minutes: mapIsochrone.value.walking_minutes || 15,
      radius_km: mapIsochrone.value.radius_km || 3.0,
    }
    const rKm = mapIsochrone.value.radius_km || 3.0
    const pixelR = Math.max(35, Math.min(130, ((rKm / 111.0) / (maxLat - minLat)) * (height - 2 * padding)))
    isochroneCircle = { cx: hp.x, cy: hp.y, r: Math.round(pixelR) }
  }

  // 路线折线投影
  const dayColors = ['#38bdf8', '#34d399', '#fbbf24', '#f472b6', '#a78bfa']
  const routes = mapRoutes.value.map((r, rIdx) => {
    const coords = (r.polyline || []).map(pt => project(pt[0], pt[1]))
    let pathStr = ''
    if (coords.length > 0) {
      pathStr = `M ${coords[0].x} ${coords[0].y}`
      for (let i = 1; i < coords.length; i++) {
        pathStr += ` L ${coords[i].x} ${coords[i].y}`
      }
    }
    return {
      day: r.day_number || rIdx + 1,
      color: r.color || dayColors[rIdx % dayColors.length],
      path: pathStr,
      points: coords,
    }
  })

  // 景点节点投影
  const poiNodes = points
    .filter(p => p.type === 'attraction')
    .map(p => {
      const pos = project(p.lng, p.lat)
      return { ...p, ...pos }
    })

  // 在地秘境投影
  const gemNodes = points
    .filter(p => p.type === 'gem')
    .map(p => {
      const pos = project(p.lng, p.lat)
      return { ...p, ...pos }
    })

  return {
    hotelNode,
    isochroneCircle,
    routes,
    poiNodes,
    gemNodes,
  }
})

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

// ── 发送消息核心 (SSE Stream，支持中途抢占与改口转向 Mid-turn Steering) ──
async function sendChatRequest(text, actionPayload = null) {
  const isSteering = isStreaming.value

  // 若当前已有在途流式任务，立即执行客户端 Abort 并向后端协调器发送抢占中断信号
  if (isSteering) {
    if (activeAbortController.value) {
      try {
        activeAbortController.value.abort()
      } catch (e) {
        console.warn('Abort previous stream error:', e)
      }
      activeAbortController.value = null
    }

    // 异步向后端协调器广播打断信号
    fetch('/api/session/interrupt', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': userId.value,
      },
      body: JSON.stringify({
        session_id: sessionId.value,
        user_id: userId.value,
        reason: 'steered_by_user',
        steering_input: text || '',
      }),
    }).catch((e) => console.warn('Interrupt notification failed:', e))

    // 标记上一条助手的流式消息为已中途转向
    const lastAssistant = [...messages.value].reverse().find((m) => m.role === 'assistant')
    if (lastAssistant) {
      lastAssistant.isSteered = true
      lastAssistant.isStreaming = false
    }
  }

  isStreaming.value = true
  currentThinking.value = []

  // 1. 若为用户文字输入或动作，推入对话气泡
  if (text) {
    messages.value.push({
      id: Date.now(),
      role: 'user',
      content: text,
      isSteeringAction: isSteering,
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
    isInterrupted: false,
    isSteered: false,
    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  })
  messages.value.push(assistantMsg)
  scrollToBottom()

  const abortController = new AbortController()
  activeAbortController.value = abortController

  try {
    const endpoint = '/api/session/chat'
    const payload = {
      session_id: sessionId.value,
      user_id: userId.value,
      input_text: text || '',
      action_type: actionPayload ? 'SET_SLOT' : null,
      action_payload: actionPayload,
      engine: 'harness',
    }

    const res = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': userId.value,
      },
      body: JSON.stringify(payload),
      signal: abortController.signal,
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
        } else if (eventName === 'map_action') {
          mapActionsCount.value++
          const act = parsed.action
          const d = parsed.data || {}
          const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

          if (act === 'FLY_TO') {
            mapViewport.value = {
              city: d.city || '未知城市',
              center: d.center || [116.407, 39.904],
              zoom: d.zoom || 12,
              title: d.title || `定位至【${d.city}】`,
            }
            mapActionFeed.value.unshift({
              time: nowStr,
              action: 'FLY_TO',
              badge: '✈️',
              detail: `镜头飞越至【${d.city}】全局视口 (缩放: Lv.${d.zoom || 12})`,
            })
          } else if (act === 'SHOW_ISOCHRONE') {
            mapIsochrone.value = d
            mapActionFeed.value.unshift({
              time: nowStr,
              action: 'SHOW_ISOCHRONE',
              badge: '⭕',
              detail: `展开【${d.hotel_name || '商圈酒店'}】15min 步行等时圈 (${d.radius_km || 3}km)`,
            })
          } else if (act === 'DRAW_ROUTE') {
            const existingIdx = mapRoutes.value.findIndex(r => r.day_number === d.day_number)
            if (existingIdx >= 0) {
              mapRoutes.value[existingIdx] = d
            } else {
              mapRoutes.value.push(d)
            }
            mapActionFeed.value.unshift({
              time: nowStr,
              action: 'DRAW_ROUTE',
              badge: '⚡',
              detail: `Day ${d.day_number} 2-Opt 路径收敛 (${(d.polyline || []).length} 处节点)`,
            })
          } else if (act === 'SPOTLIGHT_POI') {
            if (!mapSpotlights.value.some(s => s.poi === d.poi)) {
              mapSpotlights.value.push(d)
            }
            mapActionFeed.value.unshift({
              time: nowStr,
              action: 'SPOTLIGHT_POI',
              badge: '💎',
              detail: `发现在地秘境 · ${d.poi} (${d.reason || d.tag})`,
            })
          }
          if (mapActionFeed.value.length > 25) {
            mapActionFeed.value.pop()
          }
          saveSessionCache()
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
        } else if (eventName === 'preempted') {
          assistantMsg.isInterrupted = true
          assistantMsg.isStreaming = false
          const pDetail = parsed.detail || '⚡ 任务已响应中途改口抢占并安全交出执行权'
          assistantMsg.thinking.push({ step: 'preempted', detail: pDetail })
          scrollToBottom()
        } else if (eventName === 'done') {
          assistantMsg.isStreaming = false
          assistantMsg.isThinkingOpen = false
          saveSessionCache()
        }
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      console.log('前序规划流已被外部主动停止或抢占')
      assistantMsg.isStreaming = false
      assistantMsg.isInterrupted = true
    } else {
      console.error('SSE 流式接收异常:', err)
      assistantMsg.content += `\n\n*(网络或接口异常: ${err.message})*`
      assistantMsg.isStreaming = false
    }
  } finally {
    if (activeAbortController.value === abortController) {
      activeAbortController.value = null
      isStreaming.value = false
    }
    saveSessionCache()
    scrollToBottom()
  }
}

// ── 用户主动打断当前流式生成 (Interrupt Current Generation) ──
async function interruptCurrentGeneration() {
  if (!isStreaming.value) return

  if (activeAbortController.value) {
    try {
      activeAbortController.value.abort()
    } catch (e) {
      console.warn('Abort error:', e)
    }
    activeAbortController.value = null
  }
  isStreaming.value = false

  const lastAssistant = [...messages.value].reverse().find((m) => m.role === 'assistant')
  if (lastAssistant) {
    lastAssistant.isInterrupted = true
    lastAssistant.isStreaming = false
    lastAssistant.thinking.push({ step: 'interrupted', detail: '⏹️ 用户已手动停止本次生成' })
  }

  try {
    await fetch('/api/session/interrupt', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': userId.value,
      },
      body: JSON.stringify({
        session_id: sessionId.value,
        user_id: userId.value,
        reason: 'stopped_by_user',
      }),
    })
  } catch (err) {
    console.warn('发送停止请求失败:', err)
  }
  saveSessionCache()
  scrollToBottom()
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

// ── 本地快照持久化与双轨恢复 (按租户命名空间严格隔离) ──
function getCacheKey() {
  return `tp_state_${userId.value}_${sessionId.value}`
}

function saveSessionCache() {
  try {
    const cachePayload = {
      messages: messages.value,
      effectiveRequirements: effectiveRequirements.value,
      currentPlan: currentPlan.value,
      lockedItems: lockedItems.value,
      attemptedActions: attemptedActions.value,
      mapViewport: mapViewport.value,
      mapIsochrone: mapIsochrone.value,
      mapRoutes: mapRoutes.value,
      mapSpotlights: mapSpotlights.value,
      mapActionFeed: mapActionFeed.value,
      mapActionsCount: mapActionsCount.value,
      updatedAt: Date.now(),
    }
    localStorage.setItem(getCacheKey(), JSON.stringify(cachePayload))
  } catch (e) {
    console.warn('保存会话本地快照失败:', e)
  }
}

function loadSessionCache() {
  try {
    const raw = localStorage.getItem(getCacheKey())
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
    if (parsed.mapViewport) mapViewport.value = parsed.mapViewport
    if (parsed.mapIsochrone) mapIsochrone.value = parsed.mapIsochrone
    if (parsed.mapRoutes) mapRoutes.value = parsed.mapRoutes
    if (parsed.mapSpotlights) mapSpotlights.value = parsed.mapSpotlights
    if (parsed.mapActionFeed) mapActionFeed.value = parsed.mapActionFeed
    if (parsed.mapActionsCount) mapActionsCount.value = parsed.mapActionsCount
    return true
  } catch (e) {
    console.warn('读取会话本地快照失败:', e)
    return false
  }
}

function clearSessionCache() {
  try {
    localStorage.removeItem(getCacheKey())
  } catch (e) {}
}

// ── 查询三轨状态快照与断点同步 ──
async function fetchSessionState() {
  try {
    const endpoint = `/api/session/${sessionId.value}/state`
    const res = await fetch(endpoint, {
      headers: {
        'X-User-Id': userId.value,
      },
    })
    if (res.status === 403) {
      console.warn('当前会话不属于该租户，重置为新会话')
      resetSession()
      return
    }
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
  mapActionsCount.value = 0
  mapRoutes.value = []
  mapIsochrone.value = null
  mapSpotlights.value = []
  mapActionFeed.value = []
  selectedMapNode.value = null
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

  // 2. 加载租户历史足迹与生活方式体温画像
  await Promise.all([loadUserFootprints(), loadUserLifestyle()])

  // 3. 异步服务端状态同步与断点核验
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

/* ── 中途打断与改口操作按钮群 (Mid-turn Steering & Preemption) ── */
.input-actions-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.btn-interrupt {
  background: rgba(239, 68, 68, 0.16);
  border: 1px solid rgba(239, 68, 68, 0.45);
  color: #fca5a5;
  padding: 10px 14px;
  border-radius: 10px;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  height: 42px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
  white-space: nowrap;
}
.btn-interrupt:hover {
  background: rgba(239, 68, 68, 0.3);
  color: #ffffff;
  border-color: #ef4444;
  transform: translateY(-1px);
}
.btn-send.btn-steer {
  background: linear-gradient(135deg, #f59e0b 0%, #ef4444 100%);
  box-shadow: 0 0 14px rgba(245, 158, 11, 0.4);
  animation: pulse-steer-glow 1.8s infinite;
}
@keyframes pulse-steer-glow {
  0%, 100% {
    box-shadow: 0 0 10px rgba(245, 158, 11, 0.4);
  }
  50% {
    box-shadow: 0 0 20px rgba(239, 68, 68, 0.7);
  }
}
.badge-status-pill {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 9999px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.badge-stopped {
  background: rgba(239, 68, 68, 0.18);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.35);
}
.badge-steered {
  background: rgba(245, 158, 11, 0.2);
  color: #fde68a;
  border: 1px solid rgba(245, 158, 11, 0.45);
}
.badge-steering-prompt {
  background: rgba(168, 85, 247, 0.2);
  color: #e9d5ff;
  border: 1px solid rgba(168, 85, 247, 0.45);
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
.day-walking-tag {
  margin-left: 8px;
  font-size: 11px;
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.25);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}
.day-walking-tag.warning {
  color: #f87171;
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.35);
}

.day-pacing-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(56, 189, 248, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 6px;
  padding: 6px 10px;
  margin-top: 6px;
  font-size: 12px;
  color: #bae6fd;
}
.day-pacing-strip.warning {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.3);
  color: #fca5a5;
}
.pacing-icon {
  font-size: 14px;
}
.pacing-text {
  line-height: 1.4;
}

/* ── 💖 Pi 伴随式体温关怀卡片 ── */
.lifestyle-care-card {
  margin-bottom: 16px;
  background: linear-gradient(135deg, rgba(244, 63, 94, 0.12) 0%, rgba(139, 92, 246, 0.08) 100%);
  border: 1px solid rgba(244, 63, 94, 0.3);
  border-radius: 12px;
  padding: 14px 18px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
  position: relative;
  overflow: hidden;
}
.lifestyle-care-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
  background: linear-gradient(180deg, #f43f5e, #ec4899);
}
.care-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.care-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: #fda4af;
}
.care-icon {
  font-size: 16px;
}
.care-pill {
  font-size: 10px;
  color: #f472b6;
  background: rgba(244, 63, 94, 0.15);
  border: 1px solid rgba(244, 63, 94, 0.3);
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 500;
}
.care-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.care-text {
  font-size: 13px;
  line-height: 1.55;
  color: #fce7f3;
  margin: 0;
}
.care-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}
.care-tag {
  font-size: 11px;
  color: #e0e7ff;
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
  padding: 2px 8px;
  border-radius: 6px;
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
}

/* ── 多租户身份选择器 ── */
.user-tenant-picker {
  display: flex;
  align-items: center;
  background: rgba(30, 41, 59, 0.7);
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 8px;
  padding: 3px 8px;
  gap: 4px;
}
.user-pill-icon {
  font-size: 13px;
}
.tenant-select {
  background: transparent;
  border: none;
  color: #e2e8f0;
  font-size: 12px;
  font-weight: 500;
  outline: none;
  cursor: pointer;
}
.tenant-select option {
  background: #0f172a;
  color: #f1f5f9;
}

/* ── 旅行体温画像顶部按钮 ── */
.btn-lifestyle {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(244, 63, 94, 0.12);
  border: 1px solid rgba(244, 63, 94, 0.35);
  color: #fda4af;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-lifestyle:hover {
  background: rgba(244, 63, 94, 0.25);
  color: #ffe4e6;
  box-shadow: 0 0 10px rgba(244, 63, 94, 0.3);
}
.lifestyle-badge {
  background: rgba(244, 63, 94, 0.85);
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
  border-radius: 10px;
  padding: 1px 6px;
}

/* ── 我的足迹顶部按钮 ── */
.btn-footprints {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.4);
  color: #6ee7b7;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-footprints:hover {
  background: rgba(16, 185, 129, 0.3);
  color: #a7f3d0;
  box-shadow: 0 0 10px rgba(16, 185, 129, 0.3);
}
.footprint-badge {
  background: #10b981;
  color: #064e3b;
  font-size: 11px;
  font-weight: 700;
  border-radius: 10px;
  padding: 1px 6px;
}

/* ── 景点卡片足迹微交互 ── */
.visited-indicator {
  font-size: 11px;
  color: #34d399;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}
.attraction-card.visited-card {
  border-color: rgba(16, 185, 129, 0.35);
  background: rgba(6, 78, 59, 0.12);
  box-shadow: inset 0 0 12px rgba(16, 185, 129, 0.08);
}
.btn-footprint-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #cbd5e1;
}
.btn-footprint-tag:hover {
  background: rgba(16, 185, 129, 0.2);
  border-color: #10b981;
  color: #34d399;
}
.btn-footprint-tag.is-visited {
  background: rgba(16, 185, 129, 0.25);
  border-color: rgba(16, 185, 129, 0.6);
  color: #6ee7b7;
  font-weight: 600;
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.3);
}

/* ── 全息足迹图谱抽屉 (Footprint Drawer) ── */
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(8px);
  z-index: 999;
  display: flex;
  justify-content: flex-end;
}
.footprint-drawer {
  width: 440px;
  max-width: 90vw;
  height: 100vh;
  border-radius: 0;
  border-left: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(15, 23, 42, 0.92);
  box-shadow: -10px 0 30px rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
}
.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.drawer-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 700;
  color: #f8fafc;
}
.drawer-badge {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 12px;
  border: 1px solid rgba(16, 185, 129, 0.4);
}
.btn-close-drawer {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: all 0.2s;
}
.btn-close-drawer:hover {
  color: #f8fafc;
  background: rgba(255, 255, 255, 0.1);
}
.drawer-sub {
  padding: 10px 20px;
  font-size: 12px;
  line-height: 1.5;
  color: #94a3b8;
  background: rgba(16, 185, 129, 0.06);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.drawer-sub strong {
  color: #34d399;
}
.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.empty-footprints {
  text-align: center;
  padding: 40px 20px;
  color: #94a3b8;
}
.empty-footprints .empty-icon {
  font-size: 40px;
  display: block;
  margin-bottom: 12px;
}
.empty-footprints .empty-text {
  font-size: 15px;
  font-weight: 600;
  color: #cbd5e1;
  margin-bottom: 6px;
}
.empty-footprints .empty-sub {
  font-size: 12px;
  color: #64748b;
}
.city-footprint-group {
  background: rgba(30, 41, 59, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  padding: 12px 14px;
}
.city-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}
.city-name {
  font-weight: 600;
  color: #f1f5f9;
  font-size: 14px;
}
.city-count {
  font-size: 12px;
  color: #94a3b8;
}
.city-poi-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.footprint-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(16, 185, 129, 0.35);
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  color: #e2e8f0;
}
.footprint-chip .chip-name {
  font-weight: 500;
}
.btn-remove-chip {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 12px;
  cursor: pointer;
  padding: 0 2px;
  transition: color 0.15s;
}
.btn-remove-chip:hover {
  color: #f87171;
}
.drawer-footer {
  padding: 16px 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(15, 23, 42, 0.8);
}
.manual-input-title {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 8px;
  font-weight: 500;
}
.manual-input-row {
  display: flex;
  gap: 8px;
}
.input-city {
  width: 90px;
  background: rgba(30, 41, 59, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  padding: 6px 10px;
  color: #f8fafc;
  font-size: 12px;
  outline: none;
}
.input-poi {
  flex: 1;
  background: rgba(30, 41, 59, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  padding: 6px 10px;
  color: #f8fafc;
  font-size: 12px;
  outline: none;
}
.input-city:focus, .input-poi:focus {
  border-color: #10b981;
}
.btn-add-footprint {
  background: #10b981;
  border: none;
  color: #064e3b;
  font-weight: 600;
  font-size: 12px;
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}
.btn-add-footprint:hover:not(:disabled) {
  background: #34d399;
}
.btn-add-footprint:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── 旅行体温画像与伴随关怀抽屉 (Lifestyle Drawer) ── */
.lifestyle-drawer {
  width: 480px;
  max-width: 92vw;
  height: 100vh;
  border-radius: 0;
  border-left: 1px solid rgba(244, 63, 94, 0.25);
  background: rgba(15, 23, 42, 0.94);
  box-shadow: -10px 0 35px rgba(0, 0, 0, 0.7);
  display: flex;
  flex-direction: column;
}
.lifestyle-drawer-badge {
  background: rgba(244, 63, 94, 0.2);
  color: #fda4af;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 12px;
  border: 1px solid rgba(244, 63, 94, 0.4);
}
.lifestyle-drawer-sub {
  padding: 10px 20px;
  font-size: 12px;
  line-height: 1.5;
  color: #cbd5e1;
  background: rgba(244, 63, 94, 0.08);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.lifestyle-drawer-sub strong {
  color: #fda4af;
}

/* 抽屉内部表单组件 */
.lifestyle-drawer .drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.form-label {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
}
.pace-options {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.pace-card {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  padding: 10px 8px;
  cursor: pointer;
  text-align: center;
  transition: all 0.2s ease;
}
.pace-card:hover {
  border-color: rgba(244, 63, 94, 0.4);
  background: rgba(30, 41, 59, 0.8);
}
.pace-card.active {
  border-color: #f43f5e;
  background: rgba(244, 63, 94, 0.18);
  box-shadow: 0 0 10px rgba(244, 63, 94, 0.25);
}
.pace-card .card-title {
  font-size: 12px;
  font-weight: 700;
  color: #f1f5f9;
  margin-bottom: 4px;
}
.pace-card .card-desc {
  font-size: 10px;
  color: #94a3b8;
  line-height: 1.3;
}

.morning-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.morning-card {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.morning-card:hover {
  border-color: rgba(244, 63, 94, 0.4);
  background: rgba(30, 41, 59, 0.8);
}
.morning-card.active {
  border-color: #f43f5e;
  background: rgba(244, 63, 94, 0.18);
  box-shadow: 0 0 10px rgba(244, 63, 94, 0.25);
}
.morning-card .card-title {
  font-size: 12px;
  font-weight: 700;
  color: #f1f5f9;
  margin-bottom: 4px;
}
.morning-card .card-desc {
  font-size: 11px;
  color: #94a3b8;
}

.slider-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.slider-val {
  font-size: 14px;
  font-weight: 700;
  color: #fda4af;
  font-family: monospace;
}
.km-slider {
  width: 100%;
  accent-color: #f43f5e;
  cursor: pointer;
  margin: 4px 0;
}
.slider-hint {
  font-size: 11px;
  color: #94a3b8;
}

.companion-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.btn-companion-chip {
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  padding: 6px 12px;
  color: #cbd5e1;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-companion-chip:hover {
  border-color: rgba(244, 63, 94, 0.4);
  color: #f8fafc;
}
.btn-companion-chip.active {
  background: rgba(244, 63, 94, 0.2);
  border-color: #f43f5e;
  color: #fda4af;
  font-weight: 600;
}

.care-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.btn-care-chip {
  background: rgba(30, 41, 59, 0.4);
  border: 1px dashed rgba(148, 163, 184, 0.25);
  border-radius: 6px;
  padding: 4px 10px;
  color: #94a3b8;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-care-chip:hover {
  border-color: rgba(244, 63, 94, 0.4);
  color: #e2e8f0;
}
.btn-care-chip.active {
  background: rgba(244, 63, 94, 0.15);
  border-color: #f43f5e;
  border-style: solid;
  color: #fda4af;
  font-weight: 600;
}

.invalidation-notice {
  font-size: 11px;
  line-height: 1.4;
  color: #94a3b8;
  margin-bottom: 10px;
}
.invalidation-notice strong {
  color: #f59e0b;
}
.btn-save-lifestyle {
  width: 100%;
  background: linear-gradient(135deg, #f43f5e 0%, #e11d48 100%);
  border: none;
  border-radius: 8px;
  padding: 10px;
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-save-lifestyle:hover:not(:disabled) {
  opacity: 0.95;
  box-shadow: 0 0 14px rgba(244, 63, 94, 0.4);
}
.btn-save-lifestyle:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ══════════════════════════════════════════════════════════════
   Pi 风格：双重视图切换器 (Tabs) & 在地秘境 (Serendipity Gems)
   ══════════════════════════════════════════════════════════════ */
.panel-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-main-title {
  font-size: 15px;
  font-weight: 700;
  color: #f8fafc;
}

.view-switch-tabs {
  display: flex;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 3px;
  gap: 4px;
}
.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  padding: 5px 12px;
  border-radius: 6px;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.tab-btn:hover {
  color: #f1f5f9;
  background: rgba(255, 255, 255, 0.05);
}
.tab-btn.active {
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.25), rgba(99, 102, 241, 0.25));
  color: #38bdf8;
  font-weight: 600;
  border: 1px solid rgba(56, 189, 248, 0.4);
  box-shadow: 0 0 10px rgba(56, 189, 248, 0.2);
}
.tab-action-badge {
  background: #38bdf8;
  color: #0f172a;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 10px;
}

/* 💎 在地秘境 Badge 与理由 */
.gem-badge {
  background: linear-gradient(135deg, rgba(244, 114, 182, 0.25), rgba(217, 70, 239, 0.25));
  border: 1px solid rgba(244, 114, 182, 0.6);
  color: #f472b6;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 6px;
  box-shadow: 0 0 8px rgba(244, 114, 182, 0.25);
  animation: gemBadgeGlow 3s ease-in-out infinite alternate;
}
@keyframes gemBadgeGlow {
  0% { box-shadow: 0 0 6px rgba(244, 114, 182, 0.2); }
  100% { box-shadow: 0 0 12px rgba(244, 114, 182, 0.5); }
}

.attr-gem-reason {
  margin-top: 6px;
  padding: 8px 12px;
  border-radius: 6px;
  background: linear-gradient(90deg, rgba(244, 114, 182, 0.1), rgba(168, 85, 247, 0.05));
  border-left: 3px solid #f472b6;
  font-size: 12px;
  line-height: 1.5;
  color: #fbcfe8;
}
.attr-gem-reason strong {
  color: #f472b6;
}

.btn-locate-map {
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.35);
  color: #38bdf8;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-locate-map:hover {
  background: rgba(56, 189, 248, 0.25);
  border-color: #38bdf8;
  box-shadow: 0 0 8px rgba(56, 189, 248, 0.3);
}

/* ══════════════════════════════════════════════════════════════
   Pi 风格：Agent as Map Controller 空间探索动态地图
   ══════════════════════════════════════════════════════════════ */
.map-scrollable {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  padding: 16px;
}

.map-control-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(15, 23, 42, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 8px 14px;
}
.viewport-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #cbd5e1;
}
.vp-icon {
  font-size: 14px;
}
.vp-coord {
  color: #64748b;
  font-family: monospace;
  font-size: 11px;
}
.map-layer-toggles {
  display: flex;
  gap: 12px;
}
.layer-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #94a3b8;
  cursor: pointer;
}
.layer-toggle input {
  accent-color: #38bdf8;
  cursor: pointer;
}

/* SVG 地图容器 */
.svg-map-wrapper {
  position: relative;
  background: #0c121e;
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: inset 0 0 30px rgba(0, 0, 0, 0.8), 0 8px 24px rgba(0, 0, 0, 0.4);
}
.vector-map-canvas {
  width: 100%;
  height: 460px;
  display: block;
}

/* 动态动画 */
.animated-route-path {
  stroke-dasharray: 8, 5;
  animation: dashFlow 20s linear infinite;
  filter: drop-shadow(0 0 4px currentColor);
}
@keyframes dashFlow {
  from {
    stroke-dashoffset: 400;
  }
  to {
    stroke-dashoffset: 0;
  }
}

.pulsing-isochrone-ring {
  animation: isochronePulse 3s ease-in-out infinite alternate;
}
@keyframes isochronePulse {
  0% {
    stroke-opacity: 0.5;
    stroke-width: 1.2px;
  }
  100% {
    stroke-opacity: 1;
    stroke-width: 2.2px;
  }
}

.beacon-pulse {
  animation: beaconWave 2s cubic-bezier(0, 0.2, 0.8, 1) infinite;
}
@keyframes beaconWave {
  0% {
    r: 12;
    opacity: 0.8;
  }
  100% {
    r: 26;
    opacity: 0;
  }
}

.gem-pulse {
  animation: gemWave 2.5s ease-in-out infinite alternate;
}
@keyframes gemWave {
  0% {
    r: 16;
    opacity: 0.4;
  }
  100% {
    r: 28;
    opacity: 0.9;
  }
}

.map-node {
  cursor: pointer;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.map-node:hover {
  transform: scale(1.18);
}
.map-node-label {
  pointer-events: none;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.9);
}
.map-svg-label {
  pointer-events: none;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.9);
}

/* POI 详情浮层 */
.poi-inspector-overlay {
  position: absolute;
  bottom: 14px;
  left: 14px;
  right: 14px;
  z-index: 20;
}
.inspector-card {
  padding: 12px 16px;
  background: rgba(15, 23, 42, 0.92);
  border: 1px solid rgba(56, 189, 248, 0.4);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.7);
  border-radius: 8px;
}
.inspector-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.inspector-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #f8fafc;
}
.badge-gem {
  background: rgba(244, 114, 182, 0.25);
  color: #f472b6;
  border: 1px solid rgba(244, 114, 182, 0.5);
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
}
.badge-visited {
  background: rgba(16, 185, 129, 0.25);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.5);
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
}
.btn-close-inspector {
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  font-size: 14px;
  padding: 0 4px;
}
.btn-close-inspector:hover {
  color: #f8fafc;
}
.inspector-reason {
  font-size: 12px;
  color: #fbcfe8;
  margin-bottom: 6px;
  background: rgba(244, 114, 182, 0.1);
  padding: 4px 8px;
  border-radius: 4px;
}
.inspector-meta-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.meta-tag {
  font-size: 11px;
  background: rgba(255, 255, 255, 0.08);
  padding: 2px 6px;
  border-radius: 4px;
  color: #cbd5e1;
}

/* Agent 地图调度记录 Feed */
.map-action-feed-box {
  background: rgba(15, 23, 42, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 12px 14px;
}
.feed-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 8px;
}
.feed-count {
  margin-left: auto;
  font-size: 11px;
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.15);
  padding: 1px 6px;
  border-radius: 10px;
}
.feed-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 120px;
  overflow-y: auto;
}
.feed-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  background: rgba(255, 255, 255, 0.03);
  padding: 4px 8px;
  border-radius: 4px;
  border-left: 2px solid #38bdf8;
}
.feed-badge {
  font-family: monospace;
  font-weight: 600;
  color: #7dd3fc;
  white-space: nowrap;
}
.feed-detail {
  flex: 1;
  color: #cbd5e1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.feed-time {
  font-size: 10px;
  color: #64748b;
  font-family: monospace;
}
.feed-empty {
  font-size: 11px;
  color: #64748b;
  text-align: center;
  padding: 12px 0;
}
</style>

