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
 * 创建 SSE 流式连接（用户操作驱动）
 * @param {string} sessionId 会话 ID
 * @param {string} action 用户操作/输入，将作为 Command(resume=action) 传递给后端
 */
export function streamAction(sessionId, action = '') {
  const params = new URLSearchParams({ action })
  return new EventSource(`/api/sessions/${sessionId}/stream?${params.toString()}`)
}

export default api