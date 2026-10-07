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
  // AI 生成世界观+第一段剧情耗时较长（约3-4分钟），放宽到 5 分钟
  return api.post('/sessions', { user_request: userRequest }, { timeout: 300000 })
}

/**
 * 发送用户操作
 * @param {string} sessionId 会话 ID
 * @param {string} action 操作类型/用户输入
 * @param {string} payload 可选自定义输入
 */
export function sendAction(sessionId, action, payload = null) {
  // 生成剧情耗时较长，放宽到 5 分钟
  return api.post(`/sessions/${sessionId}/action`, {
    action,
    payload,
  }, { timeout: 300000 })
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
  // 续写需生成新剧情，放宽到 5 分钟
  return api.post(`/sessions/${sessionId}/resume`, {}, { timeout: 300000 })
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

/**
 * 上传参考文件到知识库（后端会解析并入库 Chroma 向量库）
 * @param {File} file 用户选择的文件对象
 */
export function uploadKnowledgeFile(file) {
  const formData = new FormData()
  formData.append('file', file)
  // 入库时每个片段都要调 embedding 接口，大文件耗时较长，放宽超时
  return api.post('/knowledge/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
  })
}

/**
 * 获取已上传的参考文件列表
 * @returns {Promise} 返回 {filename, size} 数组
 */
export function listKnowledgeFiles() {
  return api.get('/knowledge/files')
}

export default api