<template>
  <div class="app-root">
    <!-- 背景装饰：three.js 漂浮纸张 + 纸张纹理 -->
    <PaperScene />
    <div class="bg-decoration">
      <div class="paper-grain"></div>
    </div>

    <!-- 顶部导航 -->
    <header class="app-header">
      <div class="header-left">
        <div class="logo-icon">
          <el-icon><Reading /></el-icon>
        </div>
        <div class="header-titles">
          <div class="header-title">交互式小说创作系统</div>
          <div class="header-subtitle">多 Agent 协作 · 对话驱动 · 实时共创</div>
        </div>
      </div>
      <div class="header-right">
        <template v-if="sessionId && currentPhase !== 'start'">
          <el-tag :type="phaseTagType(currentPhase)" effect="dark" round size="small">
            {{ phaseLabel(currentPhase) }}
          </el-tag>
          <el-tag type="info" effect="dark" round size="small">轮次 {{ currentTurn }}</el-tag>
          <el-tag type="info" effect="dark" round size="small">段落 {{ currentSegmentCount }}</el-tag>
        </template>
        <el-tag v-if="sessionId" type="info" effect="dark" round size="small">
          会话 {{ sessionId.slice(0, 8) }}
        </el-tag>
        <el-button class="collapse-btn" text @click="sidebarCollapsed = !sidebarCollapsed">
          <el-icon><Fold v-if="!sidebarCollapsed" /><Expand v-else /></el-icon>
        </el-button>
      </div>
    </header>

    <div class="app-body">
      <SessionSidebar
        v-show="!sidebarCollapsed"
        :sessions="sessions"
        :current-session-id="sessionId"
        @select="onSelectSession"
        @create="onCreate"
        @rename="onRename"
        @delete="onDelete"
        @resume="onResume"
      />

    <main class="app-main">
      <!-- 初始输入界面 -->
      <transition name="fade" mode="out-in">
        <div v-if="currentPhase === 'start'" key="start" class="start-screen">
          <div class="start-hero">
            <h1 class="hero-title">开始你的故事</h1>
            <p class="hero-desc">
              描述你想创作的故事背景，AI 团队将为你构建世界观并推进剧情
            </p>
          </div>
          <div class="start-form">
            <el-input
              v-model="initialRequest"
              type="textarea"
              :rows="6"
              placeholder="例如：末日废土，主角是个带着女儿寻找绿洲的父亲..."
              :disabled="isWaiting"
              class="start-textarea"
            />
            <!-- 参考资料上传：文件入库后 AI 创作时自动 RAG 检索引用 -->
            <div class="upload-section">
              <div class="upload-header">
                <span class="upload-label">
                  <el-icon><Paperclip /></el-icon>
                  参考资料（可选）
                </span>
                <button class="upload-btn" :disabled="uploading" @click="triggerUpload">
                  {{ uploading ? '上传入库中...' : '上传文件' }}
                </button>
                <input
                  ref="fileInput"
                  type="file"
                  accept=".txt,.md,.pdf,.docx,.csv"
                  style="display: none"
                  @change="onFileSelected"
                />
              </div>
              <p class="upload-tip">支持 txt / md / pdf / docx / csv，上传后 AI 创作时将自动检索引用</p>
              <div v-if="knowledgeFiles.length" class="file-list">
                <div v-for="f in knowledgeFiles" :key="f.filename" class="file-item">
                  <span class="file-name">{{ f.filename }}</span>
                  <span class="file-size">{{ formatSize(f.size) }}</span>
                </div>
              </div>
            </div>
            <Button3D
              class="start-btn"
              type="primary"
              :disabled="isWaiting"
              @click="startSession"
            >
              <el-icon v-if="!isWaiting"><Promotion /></el-icon>
              {{ isWaiting ? '创作中...' : '开始创作' }}
            </Button3D>
          </div>
        </div>
      </transition>

      <!-- 创作主界面 -->
      <div v-if="currentPhase !== 'start'" class="chat-container">
        <!-- 世界观面板 -->
        <transition name="slide-down">
          <div v-if="worldSetting.worldSetting" class="world-panel">
            <div class="panel-header" @click="toggleWorld">
              <span class="panel-title">
                <el-icon><Compass /></el-icon>
                世界观设定
              </span>
              <el-icon class="toggle-icon" :class="{ collapsed: !worldExpanded }">
                <ArrowDown />
              </el-icon>
            </div>
            <transition name="expand">
              <div v-show="worldExpanded" class="panel-body">
                <p class="world-text">{{ worldSetting.worldSetting }}</p>

                <div v-if="worldSetting.characters && worldSetting.characters.length" class="char-list">
                  <div class="sub-title">角色设定</div>
                  <div class="char-cards">
                    <div
                      v-for="(c, idx) in worldSetting.characters"
                      :key="idx"
                      class="char-card"
                    >
                      <div class="char-avatar">{{ (c.name || '?').charAt(0) }}</div>
                      <div class="char-info">
                        <div class="char-name">{{ c.name || '未知角色' }}</div>
                        <div class="char-tags">
                          <span v-if="c.role" class="char-tag">{{ c.role }}</span>
                          <span v-if="c.personality" class="char-tag">{{ c.personality }}</span>
                        </div>
                        <div v-if="c.description" class="char-desc">{{ c.description }}</div>
                      </div>
                    </div>
                  </div>
                </div>

                <div v-if="worldSetting.rules" class="rules-box">
                  <span class="rules-label">核心规则</span>
                  <span class="rules-text">{{ worldSetting.rules }}</span>
                </div>
              </div>
            </transition>
          </div>
        </transition>

        <!-- 完整小说面板 -->
        <transition name="slide-down">
          <div v-if="showFinalOutput" class="final-panel">
            <div class="panel-header" @click="toggleFinal">
              <span class="panel-title">
                <el-icon><DocumentChecked /></el-icon>
                完整小说
              </span>
              <el-icon class="toggle-icon" :class="{ collapsed: !finalExpanded }">
                <ArrowDown />
              </el-icon>
            </div>
            <transition name="expand">
              <div v-show="finalExpanded" class="panel-body final-body">
                <div class="final-text" v-html="escapeHtml(finalOutput)"></div>
              </div>
            </transition>
          </div>
        </transition>

        <!-- 聊天日志 -->
        <div ref="chatLog" class="chat-log">
          <template v-for="(msg, idx) in messages" :key="idx">
            <div :class="['msg', msg.type]">
              <div class="msg-meta">
                <span v-if="msg.type === 'system'" class="msg-tag tag-system">第 {{ msg.turn }} 轮</span>
                <span v-else-if="msg.type === 'final'" class="msg-tag tag-final">小说完成</span>
                <span v-else-if="msg.type === 'notice'" class="msg-tag tag-notice">系统提示</span>
                <span v-else-if="msg.type === 'user'" class="msg-tag tag-user">你</span>
              </div>
              <div class="msg-body" :class="{ streaming: msg.streaming }" v-html="escapeHtml(msg.text)"></div>
            </div>
          </template>

          <div v-if="isWaiting" class="typing-indicator">
            <div class="typing-dots">
              <span></span><span></span><span></span>
            </div>
            <span class="typing-text">{{ streamStatus || 'AI 正在创作中' }}</span>
          </div>
        </div>

        <!-- 选项栏 -->
        <transition name="slide-up">
          <div v-if="options.length && !isWaiting && !isReviewPending" class="options-bar">
            <button
              v-for="opt in options"
              :key="opt.id"
              class="option-card"
              @click="sendUserInput(opt.id)"
            >
              <div class="option-id">{{ opt.id }}</div>
              <div class="option-content">
                <div class="option-text">{{ opt.text }}</div>
                <div class="option-tags">
                  <span v-if="opt.hint" class="opt-hint">{{ opt.hint }}</span>
                  <span
                    v-if="opt.risk_level && opt.risk_level !== 'custom'"
                    :class="['opt-risk', riskClass(opt.risk_level)]"
                  >
                    {{ riskLabel(opt.risk_level) }}
                  </span>
                </div>
              </div>
            </button>
          </div>
        </transition>

        <!-- 人工审核 -->
        <transition name="slide-up">
          <div v-if="isReviewPending" class="approval-panel">
            <div class="approval-header">
              <el-icon><Select /></el-icon>
              <span>{{ reviewTitle }}</span>
            </div>
            <p class="approval-desc">{{ review.question || '当前内容需要你的确认' }}</p>
            <div v-if="typeof review.score === 'number'" class="approval-meta">
              <span class="approval-score">评分 {{ review.score }}</span>
              <span v-if="review.suggestion" class="approval-suggestion">{{ review.suggestion }}</span>
            </div>
            <ul v-if="review.issues && review.issues.length" class="approval-issues">
              <li v-for="(issue, idx) in review.issues" :key="idx">{{ issue }}</li>
            </ul>
            <div class="approval-actions">
              <Button3D
                class="btn-approve"
                type="success"
                :disabled="isWaiting"
                @click="sendApproval('approved')"
              >
                {{ isWaiting ? '提交中…' : '通过' }}
              </Button3D>
              <Button3D
                class="btn-reject"
                type="danger"
                :disabled="isWaiting"
                @click="openRejection"
              >
                {{ rejectLabel }}
              </Button3D>
            </div>
            <transition name="fade">
              <div v-if="showRejectionInput" class="rejection-box">
                <p class="rejection-hint">{{ rejectionHint }}</p>
                <el-input
                  v-model="rejectionFeedback"
                  type="textarea"
                  :rows="3"
                  :disabled="isWaiting"
                  :placeholder="rejectionPlaceholder"
                />
                <button class="btn-submit" :disabled="isWaiting" @click="sendApproval('rejected')">
                  {{ isWaiting ? '提交中…' : '提交' }}
                </button>
              </div>
            </transition>
          </div>
        </transition>

        <!-- 输入区 -->
        <div v-if="showInput && !isReviewPending" class="input-area">
          <div class="input-row">
            <input
              v-model="userInput"
              class="text-input"
              placeholder="输入 A/B/C 选择选项，或自由输入扮演角色..."
              :disabled="isWaiting"
              @keydown.enter.prevent="sendUserInput()"
            />
            <button class="send-btn" :disabled="isWaiting || !userInput.trim()" @click="sendUserInput()">
              <el-icon><Promotion /></el-icon>
            </button>
          </div>
          <div class="action-bar">
            <button class="action-btn btn-back" :disabled="!canBacktrack || isWaiting" @click="backtrack">
              <el-icon><Back /></el-icon>
              <span>回退</span>
            </button>
            <button class="action-btn btn-regen" :disabled="!canRegenerate || isWaiting" @click="regenerate">
              <el-icon><RefreshRight /></el-icon>
              <span>重新生成剧情</span>
            </button>
            <button class="action-btn btn-finish" :disabled="isWaiting" @click="sendUserInput('生成全文')">
              <el-icon><Document /></el-icon>
              <span>生成全文</span>
            </button>
            <button class="action-btn btn-end" :disabled="isWaiting" @click="sendUserInput('结束')">
              <el-icon><CircleClose /></el-icon>
              <span>结束</span>
            </button>
          </div>
        </div>
      </div>
    </main>
    </div>

    <footer class="app-footer">
      <span>交互式多 Agent 小说创作系统</span>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Promotion, Back, Reading, Loading,
  Compass, ArrowDown, Select, Document, CircleClose,
  Fold, Expand, DocumentChecked, Paperclip, RefreshRight,
} from '@element-plus/icons-vue'
import {
  createSession, streamAction, getSession,
  listSessions, updateSession, deleteSession, resumeSession,
  uploadKnowledgeFile, listKnowledgeFiles,
} from './api/client.js'
import SessionSidebar from './components/SessionSidebar.vue'
import PaperScene from './components/PaperScene.vue'
import Button3D from './components/Button3D.vue'

const currentPhase = ref('start')
const initialRequest = ref('')
const userInput = ref('')
const messages = ref([])
const options = ref([])
const isWaiting = ref(false)
const sessionId = ref('')
const worldSetting = ref({ worldSetting: '', characters: [], rules: '' })
const humanApproval = ref(null)
const review = ref(null)               // 人工审核载荷（kind/question/score/issues...）
const showRejectionInput = ref(false)
const rejectionFeedback = ref('')
const worldExpanded = ref(true)
const chatLog = ref(null)

// ── 多会话管理状态 ──
const sessions = ref([])
const sidebarCollapsed = ref(false)
const currentTurn = ref(0)
const currentSegmentCount = ref(0)
const finalOutput = ref('')            // 完整小说全文
const finalExpanded = ref(true)        // 完整小说面板展开/收起

// ── SSE 流式相关状态 ──
const streamingMsgIndex = ref(null)   // 当前打字机气泡在 messages 中的索引
const streamingTarget = ref('')       // 打字机目标完整文本
const streamStatus = ref('')          // 当前节点进度提示
let typeTimer = null                  // 打字机定时器

// ── 参考文件上传状态 ──
const knowledgeFiles = ref([])        // 已上传的参考文件列表
const uploading = ref(false)          // 上传中标记（按钮置灰 + 文案切换）
const fileInput = ref(null)           // 隐藏的 file input 引用

// 与后端 server.py 的 REVIEW_KINDS 保持一致：只有这些中断才需要弹出审核面板
const REVIEW_KINDS = ['setting_confirm', 'setting_review', 'segment_review']

const isReviewPending = computed(() => humanApproval.value === 'pending' && !!review.value)

const reviewTitle = computed(() => {
  const kind = review.value?.kind
  if (kind === 'setting_confirm') return '世界观确认'
  if (kind === 'setting_review') return '世界观审核'
  if (kind === 'segment_review') return '剧情审核'
  return '人工审核'
})

// 世界观确认阶段用「修改世界观」，其它审核阶段用「驳回」
const rejectLabel = computed(() => (review.value?.kind === 'setting_confirm' ? '修改世界观' : '驳回'))

const rejectionHint = computed(() => (
  review.value?.kind === 'setting_confirm'
    ? '可填写修改要求，AI 会据此重做世界观；不填则直接重新生成。'
    : '可填写修改意见，AI 会据此重写。'
))

const rejectionPlaceholder = computed(() => (
  review.value?.kind === 'setting_confirm'
    ? '例如：改成蒸汽朋克背景，主角换成一位中年女性侦探'
    : '输入修改意见...'
))

const showInput = computed(() => currentPhase.value !== 'start' && currentPhase.value !== 'done')
const showFinalOutput = computed(() => currentPhase.value === 'done' && finalOutput.value)
const canBacktrack = computed(() =>
  currentPhase.value === 'story_progressing' && messages.value.some(m => m.type === 'system')
)
// 已有剧情片段时才允许「重新生成剧情」（首段还没生成了没什么可重写）
const canRegenerate = computed(() =>
  currentPhase.value === 'story_progressing' && messages.value.some(m => m.type === 'system')
)

function toggleWorld() {
  worldExpanded.value = !worldExpanded.value
}

function toggleFinal() {
  finalExpanded.value = !finalExpanded.value
}

function escapeHtml(text) {
  if (text == null) return ''
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
}

function riskLabel(level) {
  const map = { safe: '安全', medium: '中等', risky: '危险', 安全: '安全', 中等: '中等', 危险: '危险' }
  return map[level] || level
}

function riskClass(level) {
  if (['safe', '安全'].includes(level)) return 'risk-safe'
  if (['medium', '中等'].includes(level)) return 'risk-medium'
  if (['risky', '危险'].includes(level)) return 'risk-risky'
  return 'risk-default'
}

async function startSession() {
  if (!initialRequest.value.trim()) {
    ElMessage.warning('请输入创作需求')
    return
  }
  isWaiting.value = true
  try {
    const { data } = await createSession(initialRequest.value.trim())
    sessionId.value = data.session_id
    currentTurn.value = 0
    currentSegmentCount.value = 0
    // 先拉取会话列表，确保侧栏及时显示新会话，再更新主区
    await loadSessions()
    applyResponse(data)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '启动失败，请检查后端服务')
  } finally {
    isWaiting.value = false
  }
}

function nodeLabel(node) {
  const map = {
    supervisor: 'AI 正在调度…',
    world_builder: 'AI 正在构建世界观…',
    story_driver: 'AI 正在创作剧情…',
    critic: 'AI 正在审校…',
    integrator: 'AI 正在整合全文…',
  }
  return map[node] || 'AI 正在创作中…'
}

// 打字机：将 fullText 逐字填充到索引为 index 的气泡
function typeWriter(index, fullText) {
  if (typeTimer) { clearInterval(typeTimer); typeTimer = null }
  const msg = messages.value[index]
  if (!msg) return
  streamingTarget.value = fullText
  msg.text = ''
  let i = 0
  const total = Math.min(1400, Math.max(400, fullText.length * 4))
  const step = Math.max(1, Math.ceil(fullText.length / (total / 16)))
  typeTimer = setInterval(() => {
    if (i >= fullText.length) {
      clearInterval(typeTimer)
      typeTimer = null
      msg.text = fullText
      return
    }
    msg.text += fullText.slice(i, i + step)
    i += step
    scrollToBottom()
  }, 16)
}

// 后端返回 error（例如世界观构建失败）时，明确提示用户，而不是静默跳过
function showBackendError(data) {
  if (!data || !data.error) return
  ElMessage.error(data.error)
  const text = `⚠️ ${data.error}`
  const last = messages.value[messages.value.length - 1]
  if (!last || last.text !== text) messages.value.push({ type: 'notice', text })
}

// 流结束后收尾
function finishStream() {
  isWaiting.value = false
  if (typeTimer) { clearInterval(typeTimer); typeTimer = null }
  if (streamingMsgIndex.value != null) {
    const msg = messages.value[streamingMsgIndex.value]
    if (msg) {
      if (streamingTarget.value) msg.text = streamingTarget.value
      msg.streaming = false
    }
  }
  streamingMsgIndex.value = null
  streamingTarget.value = ''
  nextTick(scrollToBottom)
}

// 用最终状态快照更新界面（不重复推送本轮正文气泡）
function applyFinal(data) {
  currentPhase.value = data.phase || 'processing'
  humanApproval.value = data.human_approval || null
  review.value = data.human_approval === 'pending' ? (data.review || null) : null
  showRejectionInput.value = false
  if (data.world_setting) worldSetting.value.worldSetting = data.world_setting
  if (data.characters) worldSetting.value.characters = data.characters
  if (data.rules) worldSetting.value.rules = data.rules
  if (data.turn != null) currentTurn.value = data.turn
  if (data.segment_count != null) currentSegmentCount.value = data.segment_count
  options.value = data.options?.length ? data.options : []
  if (data.final_output) {
    finalOutput.value = data.final_output
    messages.value.push({ type: 'final', text: data.final_output })
    currentPhase.value = 'done'
    options.value = []
  }
  if (data.phase === 'done') options.value = []
  showBackendError(data)
  if (streamingMsgIndex.value != null) {
    const mi = streamingMsgIndex.value
    const msg = messages.value[mi]
    if (msg) {
      if (!msg.text && data.segment && data.phase !== 'done') msg.text = data.segment
      msg.streaming = false
      if (!msg.text) messages.value.splice(mi, 1)  // 移除空气泡（如生成全文/结束）
    }
  }
  nextTick(scrollToBottom)
}

// 通过 SSE 驱动图执行，实时推送 token / 节点进度，正文打字机渲染
function runStream(action, displayText) {
  if (isWaiting.value) return  // 上一次请求还没结束，忽略重复点击
  messages.value.push({ type: 'user', text: displayText })
  const idx = messages.value.length
  messages.value.push({ type: 'system', turn: 0, text: '', streaming: true })
  streamingMsgIndex.value = idx
  isWaiting.value = true
  streamStatus.value = 'AI 正在创作中…'

  const es = streamAction(sessionId.value, action)

  es.addEventListener('node_start', (e) => {
    try {
      const d = JSON.parse(e.data)
      if (d.node) streamStatus.value = nodeLabel(d.node)
    } catch (_) {}
  })

  es.addEventListener('node_end', (e) => {
    try {
      const d = JSON.parse(e.data)
      if (d.node === 'story_driver' && d.output?.current_segment) {
        const msg = messages.value[streamingMsgIndex.value]
        if (msg) {
          msg.turn = d.output.current_turn || msg.turn
          typeWriter(streamingMsgIndex.value, d.output.current_segment)
        }
      }
      if (d.node) streamStatus.value = nodeLabel(d.node)
    } catch (_) {}
  })

  es.addEventListener('token', (e) => {
    try {
      const d = JSON.parse(e.data)
      if (d.node) streamStatus.value = nodeLabel(d.node)
    } catch (_) {}
  })

  es.addEventListener('interrupt', (e) => {
    try {
      const d = JSON.parse(e.data)
      if (d && REVIEW_KINDS.includes(d.kind)) {
        review.value = d
        humanApproval.value = 'pending'
      }
    } catch (_) {}
  })

  es.addEventListener('final', (e) => {
    try { applyFinal(JSON.parse(e.data)) } catch (_) {}
  })

  es.addEventListener('error', (e) => {
    try {
      const d = JSON.parse(e.data || '{}')
      if (d.error) ElMessage.error(d.error)
    } catch (_) {}
  })

  es.addEventListener('done', () => {
    es.close()
    finishStream()
  })

  es.onerror = () => {
    es.close()
    isWaiting.value = false
    if (typeTimer) { clearInterval(typeTimer); typeTimer = null }
    streamingMsgIndex.value = null
    ElMessage.error('流式连接失败，请检查后端服务')
  }
}

function sendUserInput(input) {
  if (isWaiting.value) return  // 生成中，忽略重复提交
  let action = input
  if (typeof action !== 'string' || action === '') {
    action = userInput.value.trim()
    if (!action) return
  }
  const display = action
  userInput.value = ''
  runStream(action, display)
}

async function backtrack() {
  await sendUserInput('回到上一步')
}

// 重新生成当前这段剧情（后端会丢弃当前片段并用同一轮次重写）
async function regenerate() {
  await sendUserInput('重新生成剧情')
}

// 展开「修改/驳回」输入框（生成中不可再展开）
function openRejection() {
  if (isWaiting.value) return
  showRejectionInput.value = true
}

async function sendApproval(decision) {
  if (isWaiting.value) return  // 已在生成中，忽略重复点击
  const isSetting = review.value?.kind === 'setting_confirm'
  let action = decision
  let display = decision === 'approved' ? (isSetting ? '确认世界观' : '审核通过') : '审核驳回'
  if (decision === 'rejected') {
    action = rejectionFeedback.value.trim() || '驳回'
    display = `${isSetting ? '世界观修改要求' : '审核驳回'}：${action}`
  }
  showRejectionInput.value = false
  rejectionFeedback.value = ''
  runStream(action, display)
}

function applyResponse(data) {
  currentPhase.value = data.phase || 'processing'
  humanApproval.value = data.human_approval || null
  review.value = data.human_approval === 'pending' ? (data.review || null) : null
  showRejectionInput.value = false
  if (data.world_setting) worldSetting.value.worldSetting = data.world_setting
  if (data.characters) worldSetting.value.characters = data.characters
  if (data.rules) worldSetting.value.rules = data.rules
  if (data.segment) {
    messages.value.push({ type: 'system', turn: data.turn, text: data.segment })
    currentSegmentCount.value += 1
  }
  if (data.turn != null) currentTurn.value = data.turn
  options.value = data.options?.length ? data.options : []
  if (data.final_output) {
    finalOutput.value = data.final_output
    messages.value.push({ type: 'final', text: data.final_output })
    currentPhase.value = 'done'
    options.value = []
  }
  if (data.critique) {
    messages.value.push({ type: 'notice', text: `内部评审：${data.critique}` })
  }
  if (data.phase === 'done') options.value = []
  showBackendError(data)
  nextTick(scrollToBottom)
}

function scrollToBottom() {
  if (chatLog.value) chatLog.value.scrollTop = chatLog.value.scrollHeight
}

// ── 多会话管理 ──
function phaseLabel(phase) {
  if (['done', 'completed', 'finished'].includes(phase)) return '已完成'
  if (['story_progressing', 'story_driver', 'plotting'].includes(phase)) return '剧情推进'
  if (['start', ''].includes(phase)) return '世界观构建'
  return '世界观构建'
}

function phaseTagType(phase) {
  if (['done', 'completed', 'finished'].includes(phase)) return 'success'
  if (['story_progressing', 'story_driver', 'plotting'].includes(phase)) return 'warning'
  return 'primary'
}

async function loadSessions() {
  try {
    const { data } = await listSessions()
    sessions.value = Array.isArray(data) ? data : []
  } catch (_) {
    sessions.value = []
  }
}

function resetWorkspace() {
  sessionId.value = ''
  currentPhase.value = 'start'
  messages.value = []
  options.value = []
  worldSetting.value = { worldSetting: '', characters: [], rules: '' }
  humanApproval.value = null
  review.value = null
  showRejectionInput.value = false
  rejectionFeedback.value = ''
  currentTurn.value = 0
  currentSegmentCount.value = 0
  finalOutput.value = ''
  finalExpanded.value = true
  initialRequest.value = ''
  if (typeTimer) { clearInterval(typeTimer); typeTimer = null }
  streamingMsgIndex.value = null
  streamingTarget.value = ''
}

async function onSelectSession(id) {
  if (!id || id === sessionId.value) return
  isWaiting.value = true
  try {
    const { data } = await getSession(id)
    // 清空旧状态再加载该会话完整状态
    messages.value = []
    options.value = []
    worldSetting.value = { worldSetting: '', characters: [], rules: '' }
    humanApproval.value = null
    review.value = null
    showRejectionInput.value = false
    rejectionFeedback.value = ''
    finalOutput.value = ''
    finalExpanded.value = true
    if (typeTimer) { clearInterval(typeTimer); typeTimer = null }
    streamingMsgIndex.value = null
    streamingTarget.value = ''
    sessionId.value = id
    currentTurn.value = data.turn ?? 0
    currentSegmentCount.value = data.segment_count ?? 0
    applyResponse(data)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '加载会话失败')
  } finally {
    isWaiting.value = false
  }
}

function onCreate() {
  resetWorkspace()
}

async function onRename(id, newTitle) {
  try {
    await updateSession(id, newTitle)
    const s = sessions.value.find(x => x.session_id === id)
    if (s) s.title = newTitle
    ElMessage.success('已重命名')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '重命名失败')
  }
}

async function onDelete(id) {
  try {
    await deleteSession(id)
    sessions.value = sessions.value.filter(x => x.session_id !== id)
    if (id === sessionId.value) {
      // 删除当前会话：切换到列表第一个或回到初始界面
      if (sessions.value.length) {
        onSelectSession(sessions.value[0].session_id)
      } else {
        resetWorkspace()
      }
    }
    ElMessage.success('已删除')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '删除失败')
  }
}

async function onResume(id) {
  if (!id) return
  isWaiting.value = true
  try {
    const { data } = await resumeSession(id)
    // 清空旧状态，加载续写产生的新会话
    messages.value = []
    options.value = []
    worldSetting.value = { worldSetting: '', characters: [], rules: '' }
    humanApproval.value = null
    review.value = null
    showRejectionInput.value = false
    rejectionFeedback.value = ''
    finalOutput.value = ''
    finalExpanded.value = true
    if (typeTimer) { clearInterval(typeTimer); typeTimer = null }
    streamingMsgIndex.value = null
    streamingTarget.value = ''
    sessionId.value = data.session_id
    currentTurn.value = data.turn ?? 0
    currentSegmentCount.value = data.segment_count ?? 0
    await loadSessions()
    applyResponse(data)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '续写失败')
  } finally {
    isWaiting.value = false
  }
}

// ── 参考文件上传 ──

// 点击"上传文件"按钮：触发隐藏的 file input 打开文件选择框
function triggerUpload() {
  fileInput.value?.click()
}

// 用户选好文件后调用：上传到后端入库，成功后刷新文件列表
async function onFileSelected(e) {
  const file = e.target.files?.[0]
  e.target.value = '' // 清空选择，允许下次重复选择同一文件
  if (!file) return
  uploading.value = true
  try {
    const { data } = await uploadKnowledgeFile(file)
    ElMessage.success(`「${data.filename}」已入库 ${data.chunks} 个片段`)
    await loadKnowledgeFiles()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '上传失败，请检查文件格式')
  } finally {
    uploading.value = false
  }
}

// 拉取已上传的参考文件列表
async function loadKnowledgeFiles() {
  try {
    const { data } = await listKnowledgeFiles()
    knowledgeFiles.value = Array.isArray(data) ? data : []
  } catch (_) {
    knowledgeFiles.value = []
  }
}

// 文件大小格式化：1024 以下显示 B，再往上 KB / MB
function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

onMounted(() => {
  loadSessions()
  loadKnowledgeFiles()
})

watch(messages, scrollToBottom, { deep: true })
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  /* 纸质风格：优先使用衬线字体，营造印刷书籍的观感 */
  font-family: 'Noto Serif SC', 'Source Han Serif SC', 'Songti SC', 'SimSun', Georgia, serif;
  /* 纸张底色放在 body 上，让 .app-root 保持透明，露出下层 three.js 画布 */
  background: #efe7d6;
}
</style>

<style scoped>
.app-root {
  min-height: 100vh;
  background: transparent;
  color: #43392a;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow-x: hidden;
}

/* ─── 背景装饰：宣纸纹理 ─── */
.bg-decoration {
  position: fixed;
  inset: 0;
  overflow: hidden;
  z-index: 0;
  pointer-events: none;
}

.paper-grain {
  position: absolute;
  inset: 0;
  /* feTurbulence 噪点模拟纸张纤维，叠在暖米色底上形成宣纸质感 */
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='240'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  opacity: 0.05;
}

/* ─── 顶部导航 ─── */
.app-header {
  position: relative;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  height: 72px;
  background: rgba(250, 245, 233, 0.92);
  border-bottom: 1px solid #d9cdb4;
  box-shadow: 0 2px 10px rgba(96, 74, 44, 0.08);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.logo-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 朱红印章质感的 logo 底板 */
  background: #a63d2f;
  border-radius: 8px;
  font-size: 22px;
  color: #f8f1e2;
  box-shadow: 0 2px 6px rgba(166, 61, 47, 0.35), inset 0 0 0 2px rgba(248, 241, 226, 0.35);
}

.header-title {
  font-size: 20px;
  font-weight: 700;
  color: #3d3223;
  letter-spacing: 1px;
}

.header-subtitle {
  font-size: 12px;
  color: #8d7c62;
  margin-top: 2px;
  letter-spacing: 0.5px;
}

/* ─── 主内容 ─── */
.app-body {
  flex: 1;
  display: flex;
  min-height: 0;
  position: relative;
  z-index: 1;
}

.app-main {
  flex: 1;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px 20px;
  min-width: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.collapse-btn {
  color: #6b5d47;
  padding: 6px;
  border: 1px solid #d9cdb4;
  border-radius: 8px;
  background: rgba(255, 252, 244, 0.8);
}

.collapse-btn:hover {
  color: #a63d2f;
  background: #f3e8d8;
}

/* ─── 初始界面 ─── */
.start-screen {
  width: 100%;
  max-width: 640px;
  margin-top: 60px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.start-hero {
  text-align: center;
  margin-bottom: 40px;
}

.hero-title {
  font-size: 36px;
  font-weight: 800;
  color: #3d3223;
  letter-spacing: 4px;
  margin-bottom: 12px;
  position: relative;
  display: inline-block;
}

/* 标题下的朱砂笔触下划线 */
.hero-title::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -8px;
  transform: translateX(-50%);
  width: 72px;
  height: 4px;
  background: #a63d2f;
  border-radius: 2px;
  opacity: 0.85;
}

.hero-desc {
  color: #7d6c52;
  font-size: 15px;
  margin-top: 8px;
}

.start-form {
  width: 100%;
  /* 一张铺开的稿纸：微透明，隐约透出背景里漂浮的 3D 纸张 */
  background: rgba(251, 246, 234, 0.88);
  border: 1px solid #ddd0b6;
  border-radius: 6px;
  padding: 28px;
  box-shadow: 0 10px 30px rgba(96, 74, 44, 0.12), 0 2px 6px rgba(96, 74, 44, 0.08);
}

.start-textarea :deep(.el-textarea__inner) {
  background: #fffdf6;
  border: 1px solid #d9cdb4;
  border-radius: 6px;
  color: #43392a;
  font-size: 15px;
  font-family: inherit;
  line-height: 1.9;
  padding: 16px;
  resize: none;
  box-shadow: inset 0 1px 3px rgba(96, 74, 44, 0.06);
}

.start-textarea :deep(.el-textarea__inner):focus {
  border-color: #a63d2f;
  box-shadow: 0 0 0 3px rgba(166, 61, 47, 0.1);
}

.start-textarea :deep(.el-textarea__inner)::placeholder {
  color: #b3a488;
}

/* 开始创作按钮：外观由 Button3D 的 three.js 模型渲染，这里只定尺寸与文字 */
.start-btn {
  width: 100%;
  margin-top: 20px;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
}

/* ─── 参考资料上传区 ─── */
.upload-section {
  margin-top: 18px;
  background: #f5edda;
  border: 1px dashed #c8b78f;
  border-radius: 6px;
  padding: 14px 16px;
}

.upload-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.upload-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #7a5c2e;
}

.upload-btn {
  padding: 7px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid #b99b6d;
  background: #fffdf6;
  color: #7a5c2e;
  font-family: inherit;
  transition: all 0.2s;
}

.upload-btn:hover:not(:disabled) {
  background: #f3e8d8;
  border-color: #a63d2f;
  color: #a63d2f;
}

.upload-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.upload-tip {
  margin-top: 8px;
  font-size: 12px;
  color: #9c8a6b;
}

.file-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fffdf6;
  border: 1px solid #e0d5bd;
  border-radius: 6px;
  padding: 8px 12px;
}

.file-name {
  font-size: 13px;
  color: #5a4c38;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  font-size: 12px;
  color: #9c8a6b;
  flex-shrink: 0;
  margin-left: 12px;
}

/* ─── 创作界面 ─── */
.chat-container {
  width: 100%;
  max-width: 900px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* ─── 世界观面板 ─── */
.world-panel {
  background: rgba(251, 246, 234, 0.88);
  border: 1px solid #ddd0b6;
  border-radius: 6px;
  overflow: hidden;
  box-shadow: 0 4px 14px rgba(96, 74, 44, 0.08);
}

/* ─── 完整小说面板 ─── */
.final-panel {
  background: #f6f3e4;
  border: 1px solid #c3cbae;
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 18px;
  box-shadow: 0 4px 14px rgba(96, 74, 44, 0.1);
}

.final-panel .panel-header:hover {
  background: rgba(63, 96, 58, 0.06);
}

.final-body {
  max-height: 48vh;
  overflow-y: auto;
}

.final-body::-webkit-scrollbar {
  width: 6px;
}

.final-body::-webkit-scrollbar-track {
  background: transparent;
}

.final-body::-webkit-scrollbar-thumb {
  background: rgba(63, 96, 58, 0.35);
  border-radius: 10px;
}

.final-body::-webkit-scrollbar-thumb:hover {
  background: rgba(63, 96, 58, 0.55);
}

.final-text {
  color: #3a3527;
  font-size: 15px;
  line-height: 2.1;
  white-space: pre-wrap;
  background: #fffdf4;
  padding: 24px 28px;
  border-radius: 4px;
  border: 1px solid #e3dcc2;
  /* 稿纸横线：淡墨横格线 */
  background-image: repeating-linear-gradient(
    to bottom,
    transparent,
    transparent 31px,
    rgba(120, 100, 70, 0.08) 31px,
    rgba(120, 100, 70, 0.08) 32px
  );
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.panel-header:hover {
  background: rgba(166, 61, 47, 0.05);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #7a3b2c;
  letter-spacing: 1px;
}

.toggle-icon {
  transition: transform 0.3s;
  color: #9c8a6b;
}

.toggle-icon.collapsed {
  transform: rotate(-90deg);
}

.panel-body {
  padding: 0 20px 20px;
}

.world-text {
  color: #5a4c38;
  font-size: 14px;
  line-height: 1.95;
  background: #f5edda;
  padding: 16px;
  border-radius: 4px;
  border-left: 3px solid #a63d2f;
}

.sub-title {
  font-size: 13px;
  font-weight: 600;
  color: #7a5c2e;
  margin: 18px 0 12px;
  letter-spacing: 2px;
}

.char-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.char-card {
  display: flex;
  gap: 14px;
  background: #fffdf6;
  padding: 14px;
  border-radius: 6px;
  border: 1px solid #e0d5bd;
}

.char-avatar {
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 角色头像做成小印章 */
  background: #a63d2f;
  border-radius: 6px;
  font-size: 18px;
  font-weight: 700;
  color: #f8f1e2;
  box-shadow: inset 0 0 0 2px rgba(248, 241, 226, 0.3);
}

.char-info {
  flex: 1;
}

.char-name {
  font-size: 15px;
  font-weight: 600;
  color: #3d3223;
  margin-bottom: 4px;
}

.char-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.char-tag {
  font-size: 12px;
  color: #7a5c2e;
  background: #f1e6cf;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid #ddcaa4;
}

.char-desc {
  font-size: 13px;
  color: #8d7c62;
  line-height: 1.7;
}

.rules-box {
  margin-top: 16px;
  background: #f7efdb;
  border-left: 3px solid #9c6b1f;
  padding: 14px;
  border-radius: 0 6px 6px 0;
}

.rules-label {
  font-size: 12px;
  font-weight: 600;
  color: #9c6b1f;
  letter-spacing: 2px;
  display: block;
  margin-bottom: 4px;
}

.rules-text {
  font-size: 14px;
  color: #5a4c38;
  line-height: 1.8;
}

/* ─── 聊天日志 ─── */
.chat-log {
  background: rgba(251, 246, 234, 0.88);
  border: 1px solid #ddd0b6;
  border-radius: 6px;
  padding: 24px;
  min-height: 300px;
  max-height: 56vh;
  overflow-y: auto;
  box-shadow: 0 4px 14px rgba(96, 74, 44, 0.08);
}

.chat-log::-webkit-scrollbar {
  width: 6px;
}

.chat-log::-webkit-scrollbar-track {
  background: transparent;
}

.chat-log::-webkit-scrollbar-thumb {
  background: rgba(122, 92, 46, 0.3);
  border-radius: 10px;
}

.chat-log::-webkit-scrollbar-thumb:hover {
  background: rgba(122, 92, 46, 0.5);
}

/* ─── 消息气泡 ─── */
.msg {
  margin-bottom: 18px;
  padding: 16px 18px;
  border-radius: 6px;
  animation: msg-in 0.3s ease-out;
}

@keyframes msg-in {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

.msg.system {
  /* AI 正文：像印在纸上的一段文字 */
  background: #fffdf6;
  border: 1px solid #e0d5bd;
  border-left: 3px solid #7a5c2e;
  margin-right: 50px;
  box-shadow: 0 2px 6px rgba(96, 74, 44, 0.06);
}

.msg.user {
  /* 用户输入：淡黄便签纸 */
  background: #fdf3d3;
  border: 1px solid #e3d193;
  margin-left: 50px;
  box-shadow: 0 2px 6px rgba(96, 74, 44, 0.08);
}

.msg.notice {
  /* 内部评审：红笔批注 */
  background: #fbeee9;
  border: 1px solid #e6c0b3;
  border-left: 3px solid #a63d2f;
}

.msg.final {
  background: #eef2e2;
  border: 1px solid #c3cbae;
  border-left: 3px solid #3f603a;
}

.msg-meta {
  margin-bottom: 8px;
}

.msg-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 4px;
  letter-spacing: 1px;
}

.tag-system { background: #f1e6cf; color: #7a5c2e; border: 1px solid #ddcaa4; }
.tag-final { background: #dde7cd; color: #3f603a; border: 1px solid #b8c8a0; }
.tag-notice { background: #f3dcd3; color: #a63d2f; border: 1px solid #ddb4a5; }
.tag-user { background: #f3e5b6; color: #8a6a14; border: 1px solid #ddc98b; }

.msg-body {
  font-size: 15px;
  line-height: 1.95;
  color: #43392a;
  white-space: pre-wrap;
}

.msg-body.streaming::after {
  content: '▍';
  display: inline-block;
  margin-left: 2px;
  color: #a63d2f;
  animation: caret-blink 1s step-end infinite;
  vertical-align: baseline;
}

@keyframes caret-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ─── 打字指示器 ─── */
.typing-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 18px;
  background: #f5edda;
  border: 1px dashed #c8b78f;
  border-radius: 6px;
  width: fit-content;
}

.typing-dots {
  display: flex;
  gap: 4px;
}

.typing-dots span {
  width: 8px;
  height: 8px;
  background: #a63d2f;
  border-radius: 50%;
  animation: dot-bounce 1.4s ease-in-out infinite;
}

.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dot-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-8px); opacity: 1; }
}

.typing-text {
  font-size: 13px;
  color: #7a3b2c;
}

/* ─── 选项栏 ─── */
.options-bar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

.option-card {
  display: flex;
  align-items: stretch;
  gap: 0;
  background: #fffdf6;
  border: 1px solid #ddd0b6;
  border-radius: 6px;
  padding: 0;
  cursor: pointer;
  transition: all 0.2s;
  overflow: hidden;
  text-align: left;
  color: inherit;
  font-family: inherit;
  box-shadow: 0 2px 6px rgba(96, 74, 44, 0.06);
}

.option-card:hover {
  border-color: #a63d2f;
  background: #fdf9ee;
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(166, 61, 47, 0.15);
}

.option-id {
  width: 44px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 选项编号做成朱印 */
  background: #a63d2f;
  font-size: 20px;
  font-weight: 800;
  color: #f8f1e2;
}

.option-content {
  flex: 1;
  padding: 14px 16px;
}

.option-text {
  font-size: 14px;
  color: #43392a;
  line-height: 1.7;
  margin-bottom: 6px;
}

.option-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.opt-hint {
  font-size: 11px;
  color: #8d7c62;
  background: #f1ead9;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid #e0d5bd;
}

.opt-risk {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
}

.risk-safe { background: #dde7cd; color: #3f603a; border: 1px solid #b8c8a0; }
.risk-medium { background: #f5e8c8; color: #9c6b1f; border: 1px solid #e0cb94; }
.risk-risky { background: #f3dcd3; color: #a63d2f; border: 1px solid #ddb4a5; }
.risk-default { background: #eee7d6; color: #7d6c52; border: 1px solid #dcd2ba; }

/* ─── 人工审核 ─── */
.approval-panel {
  background: #fbf6ea;
  border: 1px solid #ddd0b6;
  border-left: 4px solid #a63d2f;
  border-radius: 6px;
  padding: 20px;
  box-shadow: 0 4px 14px rgba(96, 74, 44, 0.1);
}

.approval-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #7a3b2c;
  margin-bottom: 8px;
  letter-spacing: 1px;
}

.approval-desc {
  font-size: 14px;
  color: #8d7c62;
  margin-bottom: 16px;
}

.approval-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px;
  font-size: 13px;
  color: #7d6c52;
  margin-bottom: 12px;
}

.approval-score {
  font-weight: 600;
  color: #a63d2f;
}

.approval-issues {
  margin: 0 0 16px 18px;
  font-size: 13px;
  color: #7d6c52;
  line-height: 1.7;
}

.approval-actions {
  display: flex;
  gap: 12px;
}

.btn-approve, .btn-reject {
  border-radius: 0; /* 方形 3D 按钮 */
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 1px;
}

/* 通过 / 驳回：外观交给 Button3D 的 3D 模型，这里只定宽高 */
.btn-approve {
  width: 100px;
  height: 42px;
}

.btn-reject {
  width: 100px;
  height: 42px;
}

.rejection-box {
  margin-top: 16px;
}

.rejection-hint {
  font-size: 13px;
  color: #8d7c62;
  line-height: 1.6;
  margin-bottom: 8px;
}

.rejection-box :deep(.el-textarea__inner) {
  background: #fffdf6;
  border: 1px solid #d9cdb4;
  border-radius: 6px;
  color: #43392a;
  font-size: 14px;
  font-family: inherit;
  padding: 12px;
  margin-bottom: 12px;
}

.rejection-box :deep(.el-textarea__inner):focus {
  border-color: #a63d2f;
  box-shadow: 0 0 0 3px rgba(166, 61, 47, 0.1);
}

.btn-submit {
  padding: 10px 24px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  font-family: inherit;
  letter-spacing: 1px;
  background: #a63d2f;
  color: #f8f1e2;
}

.btn-submit:hover:not(:disabled) {
  box-shadow: 0 6px 16px rgba(166, 61, 47, 0.35);
  transform: translateY(-1px);
}

.btn-submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
}

/* ─── 输入区 ─── */
.input-area {
  background: rgba(251, 246, 234, 0.88);
  border: 1px solid #ddd0b6;
  border-radius: 6px;
  padding: 18px;
  box-shadow: 0 4px 14px rgba(96, 74, 44, 0.08);
}

.input-row {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

.text-input {
  flex: 1;
  background: #fffdf6;
  border: 1px solid #d9cdb4;
  border-radius: 6px;
  padding: 12px 16px;
  color: #43392a;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
  box-shadow: inset 0 1px 3px rgba(96, 74, 44, 0.06);
}

.text-input::placeholder {
  color: #b3a488;
}

.text-input:focus {
  border-color: #a63d2f;
  box-shadow: 0 0 0 3px rgba(166, 61, 47, 0.1);
}

.send-btn {
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  background: #a63d2f;
  border: none;
  border-radius: 6px;
  color: #f8f1e2;
  font-size: 20px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.send-btn:hover:not(:disabled) {
  box-shadow: 0 6px 16px rgba(166, 61, 47, 0.35);
  transform: translateY(-1px);
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.action-bar {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  font-family: inherit;
  transition: all 0.2s;
}

.btn-back {
  background: #f7efdb;
  border-color: #ddc98b;
  color: #9c6b1f;
}

.btn-back:hover:not(:disabled) {
  background: #f3e5c0;
  border-color: #9c6b1f;
}

.btn-regen {
  background: #eef3ea;
  border-color: #b9cdb0;
  color: #3f603a;
}

.btn-regen:hover:not(:disabled) {
  background: #e2ebdb;
  border-color: #3f603a;
}

.btn-finish {
  background: #f1e6cf;
  border-color: #d3bd93;
  color: #7a5c2e;
}

.btn-finish:hover:not(:disabled) {
  background: #ead9ba;
  border-color: #7a5c2e;
}

.btn-end {
  background: #fbeee9;
  border-color: #ddb4a5;
  color: #a63d2f;
}

.btn-end:hover:not(:disabled) {
  background: #f6e1d9;
  border-color: #a63d2f;
}

.action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ─── 底部 ─── */
.app-footer {
  position: relative;
  z-index: 1;
  text-align: center;
  padding: 16px;
  font-size: 12px;
  color: #9c8a6b;
  letter-spacing: 1px;
  border-top: 1px solid #d9cdb4;
  background: rgba(250, 245, 233, 0.7);
}

/* ─── 过渡动画 ─── */
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

.slide-down-enter-active, .slide-down-leave-active {
  transition: all 0.3s ease;
}

.slide-down-enter-from {
  opacity: 0;
  transform: translateY(-10px);
}

.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.slide-up-enter-active, .slide-up-leave-active {
  transition: all 0.3s ease;
}

.slide-up-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.slide-up-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

.expand-enter-active, .expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.expand-enter-from, .expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-enter-to, .expand-leave-from {
  opacity: 1;
  max-height: 1000px;
}
</style>
