<template>
  <aside class="session-sidebar">
    <!-- 顶部新建按钮 -->
    <div class="sidebar-header">
      <el-button class="create-btn" @click="emit('create')">
        <el-icon><Plus /></el-icon>
        <span>新建创作</span>
      </el-button>
    </div>

    <!-- 会话列表 -->
    <el-scrollbar class="session-list-scroll">
      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.session_id"
          :class="['session-card', { active: s.session_id === currentSessionId }]"
          @click="emit('select', s.session_id)"
        >
          <div class="card-main">
            <div class="card-title" :title="s.title">{{ s.title || '未命名创作' }}</div>

            <div class="card-tags">
              <el-tag
                :type="phaseTagType(s.current_phase)"
                effect="dark"
                size="small"
                round
              >
                {{ phaseLabel(s.current_phase) }}
              </el-tag>
              <span class="mini-tag">轮次 {{ s.current_turn ?? 0 }}</span>
              <span class="mini-tag">段落 {{ s.segment_count ?? 0 }}</span>
            </div>

            <div class="card-footer">
              <span class="card-time">{{ formatTime(s.updated_at) }}</span>
              <el-button
                v-if="isDone(s.current_phase)"
                class="resume-btn"
                size="small"
                type="primary"
                @click.stop="emit('resume', s.session_id)"
              >
                <el-icon><EditPen /></el-icon>
                <span>续写</span>
              </el-button>
            </div>
          </div>

          <!-- 更多操作 -->
          <el-dropdown
            class="card-more"
            trigger="click"
            @click.stop
            @command="onCommand($event, s)"
          >
            <el-icon class="more-icon"><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename">
                  <el-icon><Edit /></el-icon>重命名
                </el-dropdown-item>
                <el-dropdown-item command="delete" divided>
                  <el-icon><Delete /></el-icon>删除
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <!-- 重命名 popover -->
          <el-popover
            :visible="renamingId === s.session_id"
            placement="right"
            :width="240"
            trigger="manual"
          >
            <template #reference>
              <span class="rename-anchor"></span>
            </template>
            <div class="rename-box">
              <el-input
                v-model="renameValue"
                size="small"
                placeholder="输入新标题"
                @keydown.enter="confirmRename(s)"
              />
              <div class="rename-actions">
                <el-button size="small" @click="cancelRename">取消</el-button>
                <el-button size="small" type="primary" @click="confirmRename(s)">确定</el-button>
              </div>
            </div>
          </el-popover>

          <!-- 删除确认 -->
          <el-popconfirm
            :visible="deletingId === s.session_id"
            title="确认删除该创作？"
            width="220"
            @confirm="confirmDelete(s)"
            @cancel="deletingId = ''"
          >
            <template #reference>
              <span class="delete-anchor"></span>
            </template>
          </el-popconfirm>
        </div>

        <div v-if="!sessions.length" class="empty-tip">暂无创作，点击上方新建</div>
      </div>
    </el-scrollbar>
  </aside>
</template>

<script setup>
import { ref } from 'vue'
import { Plus, MoreFilled, Edit, Delete, EditPen } from '@element-plus/icons-vue'

defineProps({
  sessions: { type: Array, default: () => [] },
  currentSessionId: { type: String, default: '' },
})

const emit = defineEmits(['select', 'create', 'rename', 'delete', 'resume'])

const renamingId = ref('')
const renameValue = ref('')
const deletingId = ref('')

function isDone(phase) {
  return ['done', 'completed', 'finished'].includes(phase)
}

function phaseLabel(phase) {
  if (['done', 'completed', 'finished'].includes(phase)) return '已完成'
  if (['story_progressing', 'story_driver', 'plotting'].includes(phase)) return '剧情推进'
  return '世界观构建'
}

function phaseTagType(phase) {
  if (['done', 'completed', 'finished'].includes(phase)) return 'success'
  if (['story_progressing', 'story_driver', 'plotting'].includes(phase)) return 'warning'
  return 'primary'
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  const now = Date.now()
  const diff = now - d.getTime()
  const day = 86400000
  if (diff < day && d.getDate() === new Date(now).getDate()) {
    return `今天 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  if (diff < 2 * day) return '昨天'
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function onCommand(cmd, s) {
  if (cmd === 'rename') {
    renamingId.value = s.session_id
    renameValue.value = s.title || ''
  } else if (cmd === 'delete') {
    deletingId.value = s.session_id
  }
}

function confirmRename(s) {
  const t = renameValue.value.trim()
  if (t) emit('rename', s.session_id, t)
  cancelRename()
}

function cancelRename() {
  renamingId.value = ''
  renameValue.value = ''
}

function confirmDelete(s) {
  emit('delete', s.session_id)
  deletingId.value = ''
}
</script>

<style scoped>
.resume-btn {
  margin-left: auto;
}
</style>
