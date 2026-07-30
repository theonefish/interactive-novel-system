import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
  headers: {
    'Content-Type': 'application/json',
  },
})

/**
 * 创建新会话
 * @param {string} userRequest 用户创作需求
 */
export function createSession(userRequest) {
  return api.post('/sessions', { user_request: userRequest })
}

/**
 * 发送用户操作
 * @param {string} sessionId 会话 ID
 * @param {string} action 操作类型/用户输入
 * @param {string} payload 可选自定义输入
 */
export function sendAction(sessionId, action, payload = null) {
  return api.post(`/sessions/${sessionId}/action`, {
    action,
    payload,
  })
}

/**
 * 获取会话状态
 * @param {string} sessionId 会话 ID
 */
export function getSession(sessionId) {
  return api.get(`/sessions/${sessionId}`)
}

/**
 * 获取会话列表
 * @returns {Promise} 返回会话摘要数组
 */
export function listSessions() {
  return api.get('/sessions')
}

/**
 * 更新会话标题
 * @param {string} sessionId 会话 ID
 * @param {string} title 新标题
 */
export function updateSession(sessionId, title) {
  return api.patch(`/sessions/${sessionId}`, { title })
}

/**
 * 删除会话
 * @param {string} sessionId 会话 ID
 */
export function deleteSession(sessionId) {
  return api.delete(`/sessions/${sessionId}`)
}

/**
 * 续写已完成会话
 * @param {string} sessionId 已完成会话 ID
 */
export function resumeSession(sessionId) {
  return api.post(`/sessions/${sessionId}/resume`)
}

/**
 * 创建 SSE 流式连接（用户操作驱动）
 * @param {string} sessionId 会话 ID
 * @param {string} action 用户操作/输入，将作为 Command(resume=action) 传递给后端
 */
export function streamAction(sessionId, action = '') {
  const params = new URLSearchParams({ action })
  return new EventSource(`/api/sessions/${sessionId}/stream?${params.toString()}`)
}

/**
 * 获取长期记忆列表
 * @returns {Promise} 返回记忆摘要数组
 */
export function listMemories() {
  return api.get('/memories')
}

/**
 * 获取单个长期记忆详情
 * @param {string} memoryId 记忆 ID
 */
export function getMemory(memoryId) {
  return api.get(`/memories/${memoryId}`)
}

export default api