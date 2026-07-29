<template>
  <div class="app-root">
    <!-- 背景装饰 -->
    <div class="bg-decoration">
      <div class="blob blob-1"></div>
      <div class="blob blob-2"></div>
      <div class="blob blob-3"></div>
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
        <el-tag v-if="sessionId" type="info" effect="dark" round size="small">
          会话 {{ sessionId.slice(0, 8) }}
        </el-tag>
      </div>
    </header>

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
            <el-button
              class="start-btn"
              :loading="isWaiting"
              @click="startSession"
            >
              <el-icon v-if="!isWaiting" style="margin-right: 8px"><Promotion /></el-icon>
              {{ isWaiting ? '创作中...' : '开始创作' }}
            </el-button>
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
          <div v-if="options.length && !isWaiting" class="options-bar">
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
          <div v-if="humanApproval === 'pending'" class="approval-panel">
            <div class="approval-header">
              <el-icon><Select /></el-icon>
              <span>人工审核</span>
            </div>
            <p class="approval-desc">当前剧情需要你的确认</p>
            <div class="approval-actions">
              <button class="btn-approve" @click="sendApproval('approved')">通过</button>
              <button class="btn-reject" @click="showRejectionInput = true">驳回</button>
            </div>
            <transition name="fade">
              <div v-if="showRejectionInput" class="rejection-box">
                <el-input
                  v-model="rejectionFeedback"
                  type="textarea"
                  :rows="3"
                  placeholder="输入修改意见..."
                />
                <button class="btn-submit" @click="sendApproval('rejected')">提交意见</button>
              </div>
            </transition>
          </div>
        </transition>

        <!-- 输入区 -->
        <div v-if="showInput" class="input-area">
          <div class="input-row">
            <input
              v-model="userInput"
              class="text-input"
              placeholder="输入 A/B/C 选择选项，或自由输入扮演角色..."
              :disabled="isWaiting"
              @keydown.enter.prevent="sendUserInput"
            />
            <button class="send-btn" :disabled="isWaiting || !userInput.trim()" @click="sendUserInput">
              <el-icon><Promotion /></el-icon>
            </button>
          </div>
          <div class="action-bar">
            <button class="action-btn btn-back" :disabled="!canBacktrack || isWaiting" @click="backtrack">
              <el-icon><Back /></el-icon>
              <span>回退</span>
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

    <footer class="app-footer">
      <span>交互式多 Agent 小说创作系统</span>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Promotion, Back, Reading, Loading,
  Compass, ArrowDown, Select, Document, CircleClose,
} from '@element-plus/icons-vue'
import { createSession, streamAction } from './api/client.js'

const currentPhase = ref('start')
const initialRequest = ref('')
const userInput = ref('')
const messages = ref([])
const options = ref([])
const isWaiting = ref(false)
const sessionId = ref('')
const worldSetting = ref({ worldSetting: '', characters: [], rules: '' })
const humanApproval = ref(null)
const showRejectionInput = ref(false)
const rejectionFeedback = ref('')
const worldExpanded = ref(true)
const chatLog = ref(null)

// ── SSE 流式相关状态 ──
const streamingMsgIndex = ref(null)   // 当前打字机气泡在 messages 中的索引
const streamingTarget = ref('')       // 打字机目标完整文本
const streamStatus = ref('')          // 当前节点进度提示
let typeTimer = null                  // 打字机定时器

const showInput = computed(() => currentPhase.value !== 'start' && currentPhase.value !== 'done')
const canBacktrack = computed(() =>
  currentPhase.value === 'story_progressing' && messages.value.some(m => m.type === 'system')
)

function toggleWorld() {
  worldExpanded.value = !worldExpanded.value
}

function escapeHtml(text) {
  if (!text) return ''
  return text
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
  if (data.world_setting) worldSetting.value.worldSetting = data.world_setting
  if (data.characters) worldSetting.value.characters = data.characters
  if (data.rules) worldSetting.value.rules = data.rules
  options.value = data.options?.length ? data.options : []
  if (data.final_output) {
    messages.value.push({ type: 'final', text: data.final_output })
    currentPhase.value = 'done'
    options.value = []
  }
  if (data.phase === 'done') options.value = []
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
  let action = input
  if (action === undefined || action === null) {
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

async function sendApproval(decision) {
  let action = decision
  let display = decision === 'approved' ? '审核通过' : '审核驳回'
  if (decision === 'rejected') {
    action = rejectionFeedback.value.trim() || '驳回'
    display = `审核驳回：${action}`
  }
  showRejectionInput.value = false
  rejectionFeedback.value = ''
  runStream(action, display)
}

function applyResponse(data) {
  currentPhase.value = data.phase || 'processing'
  humanApproval.value = data.human_approval || null
  if (data.world_setting) worldSetting.value.worldSetting = data.world_setting
  if (data.characters) worldSetting.value.characters = data.characters
  if (data.rules) worldSetting.value.rules = data.rules
  if (data.segment) {
    messages.value.push({ type: 'system', turn: data.turn, text: data.segment })
  }
  options.value = data.options?.length ? data.options : []
  if (data.final_output) {
    messages.value.push({ type: 'final', text: data.final_output })
    currentPhase.value = 'done'
    options.value = []
  }
  if (data.critique) {
    messages.value.push({ type: 'notice', text: `内部评审：${data.critique}` })
  }
  if (data.phase === 'done') options.value = []
  nextTick(scrollToBottom)
}

function scrollToBottom() {
  if (chatLog.value) chatLog.value.scrollTop = chatLog.value.scrollHeight
}

watch(messages, scrollToBottom, { deep: true })
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
</style>

<style scoped>
.app-root {
  min-height: 100vh;
  background: #0f172a;
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow-x: hidden;
}

/* ─── 背景装饰 ─── */
.bg-decoration {
  position: fixed;
  inset: 0;
  overflow: hidden;
  z-index: 0;
  pointer-events: none;
}

.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.25;
  animation: blob-float 20s ease-in-out infinite;
}

.blob-1 {
  width: 500px;
  height: 500px;
  background: #6366f1;
  top: -100px;
  left: -100px;
}

.blob-2 {
  width: 400px;
  height: 400px;
  background: #8b5cf6;
  bottom: -50px;
  right: 10%;
  animation-delay: -7s;
}

.blob-3 {
  width: 350px;
  height: 350px;
  background: #ec4899;
  top: 40%;
  right: -80px;
  animation-delay: -14s;
}

@keyframes blob-float {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(60px, -40px) scale(1.1); }
  66% { transform: translate(-40px, 30px) scale(0.9); }
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
  background: rgba(15, 23, 42, 0.8);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(99, 102, 241, 0.15);
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
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 12px;
  font-size: 22px;
  color: #fff;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.4);
}

.header-title {
  font-size: 20px;
  font-weight: 700;
  color: #f1f5f9;
  letter-spacing: 0.5px;
}

.header-subtitle {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}

/* ─── 主内容 ─── */
.app-main {
  flex: 1;
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px 20px;
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
  background: linear-gradient(135deg, #818cf8 0%, #c084fc 50%, #f472b6 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 12px;
}

.hero-desc {
  color: #94a3b8;
  font-size: 15px;
}

.start-form {
  width: 100%;
  background: rgba(30, 41, 59, 0.6);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(99, 102, 241, 0.15);
  border-radius: 20px;
  padding: 28px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.start-textarea :deep(.el-textarea__inner) {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(99, 102, 241, 0.2);
  border-radius: 12px;
  color: #e2e8f0;
  font-size: 15px;
  line-height: 1.8;
  padding: 16px;
  resize: none;
}

.start-textarea :deep(.el-textarea__inner):focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
}

.start-textarea :deep(.el-textarea__inner)::placeholder {
  color: #475569;
}

.start-btn {
  width: 100%;
  margin-top: 20px;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
  border-radius: 12px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none;
  color: #fff;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.start-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 12px 36px rgba(99, 102, 241, 0.5);
}

.start-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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
  background: rgba(30, 41, 59, 0.6);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(99, 102, 241, 0.15);
  border-radius: 16px;
  overflow: hidden;
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
  background: rgba(99, 102, 241, 0.08);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #c7d2fe;
}

.toggle-icon {
  transition: transform 0.3s;
  color: #64748b;
}

.toggle-icon.collapsed {
  transform: rotate(-90deg);
}

.panel-body {
  padding: 0 20px 20px;
}

.world-text {
  color: #cbd5e1;
  font-size: 14px;
  line-height: 1.9;
  background: rgba(99, 102, 241, 0.06);
  padding: 16px;
  border-radius: 12px;
  border-left: 3px solid #6366f1;
}

.sub-title {
  font-size: 13px;
  font-weight: 600;
  color: #94a3b8;
  margin: 18px 0 12px;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.char-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.char-card {
  display: flex;
  gap: 14px;
  background: rgba(15, 23, 42, 0.5);
  padding: 14px;
  border-radius: 12px;
  border: 1px solid rgba(99, 102, 241, 0.1);
}

.char-avatar {
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 10px;
  font-size: 18px;
  font-weight: 700;
  color: #fff;
}

.char-info {
  flex: 1;
}

.char-name {
  font-size: 15px;
  font-weight: 600;
  color: #e2e8f0;
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
  color: #a5b4fc;
  background: rgba(99, 102, 241, 0.15);
  padding: 2px 8px;
  border-radius: 6px;
}

.char-desc {
  font-size: 13px;
  color: #64748b;
  line-height: 1.6;
}

.rules-box {
  margin-top: 16px;
  background: rgba(245, 158, 11, 0.08);
  border-left: 3px solid #f59e0b;
  padding: 14px;
  border-radius: 0 12px 12px 0;
}

.rules-label {
  font-size: 12px;
  font-weight: 600;
  color: #f59e0b;
  text-transform: uppercase;
  letter-spacing: 1px;
  display: block;
  margin-bottom: 4px;
}

.rules-text {
  font-size: 14px;
  color: #cbd5e1;
  line-height: 1.7;
}

/* ─── 聊天日志 ─── */
.chat-log {
  background: rgba(30, 41, 59, 0.5);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(99, 102, 241, 0.1);
  border-radius: 16px;
  padding: 24px;
  min-height: 300px;
  max-height: 56vh;
  overflow-y: auto;
}

.chat-log::-webkit-scrollbar {
  width: 6px;
}

.chat-log::-webkit-scrollbar-track {
  background: transparent;
}

.chat-log::-webkit-scrollbar-thumb {
  background: rgba(99, 102, 241, 0.3);
  border-radius: 10px;
}

.chat-log::-webkit-scrollbar-thumb:hover {
  background: rgba(99, 102, 241, 0.5);
}

/* ─── 消息气泡 ─── */
.msg {
  margin-bottom: 18px;
  padding: 16px 18px;
  border-radius: 16px;
  animation: msg-in 0.3s ease-out;
}

@keyframes msg-in {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

.msg.system {
  background: rgba(30, 41, 59, 0.8);
  border: 1px solid rgba(99, 102, 241, 0.1);
  margin-right: 50px;
  border-bottom-left-radius: 4px;
}

.msg.user {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(139, 92, 246, 0.2));
  border: 1px solid rgba(99, 102, 241, 0.3);
  margin-left: 50px;
  border-bottom-right-radius: 4px;
}

.msg.notice {
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.25);
}

.msg.final {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(52, 211, 153, 0.15));
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.msg-meta {
  margin-bottom: 8px;
}

.msg-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 6px;
  letter-spacing: 0.5px;
}

.tag-system { background: rgba(99, 102, 241, 0.2); color: #a5b4fc; }
.tag-final { background: rgba(16, 185, 129, 0.2); color: #34d399; }
.tag-notice { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
.tag-user { background: rgba(139, 92, 246, 0.25); color: #c4b5fd; }

.msg-body {
  font-size: 15px;
  line-height: 1.9;
  color: #e2e8f0;
  white-space: pre-wrap;
}

.msg-body.streaming::after {
  content: '▍';
  display: inline-block;
  margin-left: 2px;
  color: #818cf8;
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
  background: rgba(99, 102, 241, 0.08);
  border-radius: 16px;
  width: fit-content;
}

.typing-dots {
  display: flex;
  gap: 4px;
}

.typing-dots span {
  width: 8px;
  height: 8px;
  background: #818cf8;
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
  color: #818cf8;
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
  background: rgba(30, 41, 59, 0.8);
  border: 1px solid rgba(99, 102, 241, 0.15);
  border-radius: 14px;
  padding: 0;
  cursor: pointer;
  transition: all 0.2s;
  overflow: hidden;
  text-align: left;
  color: inherit;
  font-family: inherit;
}

.option-card:hover {
  border-color: rgba(99, 102, 241, 0.4);
  background: rgba(99, 102, 241, 0.08);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.15);
}

.option-id {
  width: 44px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(99, 102, 241, 0.15);
  font-size: 20px;
  font-weight: 800;
  color: #818cf8;
}

.option-content {
  flex: 1;
  padding: 14px 16px;
}

.option-text {
  font-size: 14px;
  color: #e2e8f0;
  line-height: 1.6;
  margin-bottom: 6px;
}

.option-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.opt-hint {
  font-size: 11px;
  color: #64748b;
  background: rgba(100, 116, 139, 0.15);
  padding: 2px 8px;
  border-radius: 6px;
}

.opt-risk {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
}

.risk-safe { background: rgba(16, 185, 129, 0.2); color: #34d399; }
.risk-medium { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
.risk-risky { background: rgba(239, 68, 68, 0.2); color: #f87171; }
.risk-default { background: rgba(100, 116, 139, 0.2); color: #94a3b8; }

/* ─── 人工审核 ─── */
.approval-panel {
  background: rgba(30, 41, 59, 0.8);
  border: 1px solid rgba(99, 102, 241, 0.2);
  border-radius: 16px;
  padding: 20px;
  backdrop-filter: blur(16px);
}

.approval-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #c7d2fe;
  margin-bottom: 8px;
}

.approval-desc {
  font-size: 14px;
  color: #94a3b8;
  margin-bottom: 16px;
}

.approval-actions {
  display: flex;
  gap: 12px;
}

.btn-approve, .btn-reject, .btn-submit {
  padding: 10px 24px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
  font-family: inherit;
}

.btn-approve {
  background: linear-gradient(135deg, #10b981, #34d399);
  color: #fff;
}

.btn-approve:hover {
  box-shadow: 0 6px 20px rgba(16, 185, 129, 0.4);
  transform: translateY(-1px);
}

.btn-reject {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.btn-reject:hover {
  background: rgba(239, 68, 68, 0.25);
  transform: translateY(-1px);
}

.rejection-box {
  margin-top: 16px;
}

.rejection-box :deep(.el-textarea__inner) {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 10px;
  color: #e2e8f0;
  font-size: 14px;
  padding: 12px;
  margin-bottom: 12px;
}

.rejection-box :deep(.el-textarea__inner):focus {
  border-color: #ef4444;
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.1);
}

.btn-submit {
  background: linear-gradient(135deg, #ef4444, #f87171);
  color: #fff;
}

.btn-submit:hover {
  box-shadow: 0 6px 20px rgba(239, 68, 68, 0.4);
  transform: translateY(-1px);
}

/* ─── 输入区 ─── */
.input-area {
  background: rgba(30, 41, 59, 0.7);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(99, 102, 241, 0.15);
  border-radius: 16px;
  padding: 18px;
}

.input-row {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

.text-input {
  flex: 1;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(99, 102, 241, 0.2);
  border-radius: 12px;
  padding: 12px 16px;
  color: #e2e8f0;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.text-input::placeholder {
  color: #475569;
}

.text-input:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.send-btn {
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none;
  border-radius: 12px;
  color: #fff;
  font-size: 20px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.send-btn:hover:not(:disabled) {
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
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
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  font-family: inherit;
  transition: all 0.2s;
  color: #cbd5e1;
}

.btn-back {
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.25);
  color: #fbbf24;
}

.btn-back:hover:not(:disabled) {
  background: rgba(245, 158, 11, 0.2);
  border-color: rgba(245, 158, 11, 0.4);
}

.btn-finish {
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.25);
  color: #a5b4fc;
}

.btn-finish:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.2);
  border-color: rgba(99, 102, 241, 0.4);
}

.btn-end {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.25);
  color: #f87171;
}

.btn-end:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.2);
  border-color: rgba(239, 68, 68, 0.4);
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
  color: #475569;
  border-top: 1px solid rgba(99, 102, 241, 0.08);
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
