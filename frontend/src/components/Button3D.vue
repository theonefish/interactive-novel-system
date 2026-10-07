<template>
  <!-- three.js 立体按钮：真实挤压出的圆角模型，悬停倾斜、按下沉降 -->
  <button
    ref="hostEl"
    class="btn3d"
    :class="[`btn3d--${type}`, { 'btn3d--disabled': disabled }]"
    :disabled="disabled"
    @click="onClick"
  >
    <span ref="canvasHostEl" class="btn3d-canvas"></span>
    <span ref="labelEl" class="btn3d-label">
      <slot />
    </span>
  </button>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import * as THREE from 'three'

const props = defineProps({
  type: { type: String, default: 'primary' },   // primary / success / danger
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['click'])

const hostEl = ref(null)
const canvasHostEl = ref(null)
const labelEl = ref(null)

// 三种按钮主题色：与页面纸质风格呼应，凸起明暗由灯光生成
const THEME = {
  primary: 0xa63d2f, // 朱砂
  success: 0x3f603a, // 墨绿
  danger: 0xfbeee9,  // 浅纸
}

const isHover = ref(false)
const isPressed = ref(false)

let renderer = null
let scene = null
let camera = null
let mesh = null
let rafId = 0
let resizeObserver = null

function onClick() {
  if (!props.disabled && !props.loading) emit('click')
}

// 按当前主题与按钮尺寸重建模型（主题色或宽度变化时调用）
function buildMesh() {
  if (!scene || !hostEl.value) return
  if (mesh) {
    scene.remove(mesh)
    mesh.geometry.dispose()
    mesh.material.dispose()
    mesh = null
  }
  const rect = hostEl.value.getBoundingClientRect()
  if (rect.width === 0 || rect.height === 0) return

  const themeColor = THEME[props.type] || THEME.primary
  // 世界单位：宽度固定 10，高度按按钮实际宽高比换算，模型正好铺满按钮
  const worldW = 10
  const worldH = (rect.height / rect.width) * worldW

  // 方形实体砖：BoxGeometry 直角六面，无圆角无隆起
  // MeshBasicMaterial 不受光照影响，六个面颜色完全一致；
  // 立体感来自悬停/按下时的倾斜透视（能看到侧面厚度），而非明暗渐变
  const geometry = new THREE.BoxGeometry(worldW, worldH, 1.1)
  mesh = new THREE.Mesh(
    geometry,
    new THREE.MeshBasicMaterial({ color: themeColor })
  )
  scene.add(mesh)
}

function initScene() {
  const rect = hostEl.value.getBoundingClientRect()
  scene = new THREE.Scene()

  // 透视相机：倾斜时能呈现真实的近大远小纵深，方形砖块的立体感更自然
  // 固定距离 20，按模型高度反推 FOV，使视野恰好贴合按钮（模型宽固定 10、高按实际宽高比换算）
  const worldH = (rect.height / rect.width) * 10
  const camDist = 20
  const fovDeg = (2 * Math.atan(worldH / 2 / camDist) * 180) / Math.PI
  camera = new THREE.PerspectiveCamera(fovDeg, rect.width / rect.height, 0.1, 100)
  camera.position.set(0, 0, camDist)
  camera.lookAt(0, 0, 0)

  renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setSize(rect.width, rect.height)
  canvasHostEl.value.appendChild(renderer.domElement)

  buildMesh()
}

// 每帧根据悬停/按下状态平滑插值目标姿态
function animate() {
  if (mesh) {
    // 目标姿态：静止微倾露出厚度边缘 → 悬停抬起迎向视线 → 按下沉降
    // 各面颜色一致，倾斜只呈现方形轮廓纵深，不会出现深浅色块
    const targetRotX = isPressed.value ? 0.05 : isHover.value ? -0.04 : 0.09
    const targetRotY = isPressed.value ? 0 : isHover.value ? 0.06 : -0.1
    const targetZ = isPressed.value ? -0.35 : isHover.value ? 0.45 : 0
    mesh.rotation.x += (targetRotX - mesh.rotation.x) * 0.12
    mesh.rotation.y += (targetRotY - mesh.rotation.y) * 0.12
    mesh.position.z += (targetZ - mesh.position.z) * 0.12

    // 禁用态：模型变暗（材质颜色整体压暗）
    const dim = props.disabled ? 0.45 : 1
    const mat = mesh.material
    if (mat.userData.baseColor === undefined) mat.userData.baseColor = mat.color.clone()
    mat.color.copy(mat.userData.baseColor).multiplyScalar(dim)
  }
  renderer.render(scene, camera)
  rafId = requestAnimationFrame(animate)
}

function onEnter() { if (!props.disabled) isHover.value = true }
function onLeave() { isHover.value = false; isPressed.value = false }
function onDown() { if (!props.disabled) isPressed.value = true }
function onUp() { isPressed.value = false }

onMounted(() => {
  initScene()
  rafId = requestAnimationFrame(animate)
  hostEl.value.addEventListener('pointerenter', onEnter)
  hostEl.value.addEventListener('pointerleave', onLeave)
  hostEl.value.addEventListener('pointerdown', onDown)
  hostEl.value.addEventListener('pointerup', onUp)
  // 监听尺寸变化（如侧栏折叠导致布局变化）重建透视相机视野与模型
  resizeObserver = new ResizeObserver(() => {
    if (!renderer || !hostEl.value || !camera) return
    const rect = hostEl.value.getBoundingClientRect()
    if (rect.width === 0 || rect.height === 0) return
    renderer.setSize(rect.width, rect.height)
    // 按新宽高比重算 FOV，保持视野贴合按钮（与 initScene 中一致的算法）
    const worldH = (rect.height / rect.width) * 10
    const camDist = 20
    camera.fov = (2 * Math.atan(worldH / 2 / camDist) * 180) / Math.PI
    camera.aspect = rect.width / rect.height
    camera.updateProjectionMatrix()
    buildMesh()
  })
  resizeObserver.observe(hostEl.value)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(rafId)
  resizeObserver?.disconnect()
  if (hostEl.value) {
    hostEl.value.removeEventListener('pointerenter', onEnter)
    hostEl.value.removeEventListener('pointerleave', onLeave)
    hostEl.value.removeEventListener('pointerdown', onDown)
    hostEl.value.removeEventListener('pointerup', onUp)
  }
  if (mesh) {
    mesh.geometry.dispose()
    mesh.material.dispose()
  }
  renderer?.dispose()
  renderer = null
  scene = null
  camera = null
  mesh = null
})

// 主题切换时重建模型颜色
watch(() => props.type, buildMesh)
</script>

<style scoped>
.btn3d {
  position: relative;
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  cursor: pointer;
  font-family: inherit;
  overflow: hidden;
  border-radius: 0; /* 方形：与 BoxGeometry 直角轮廓一致 */
}

.btn3d--disabled {
  cursor: not-allowed;
}

/* three.js 画布铺满按钮底层 */
.btn3d-canvas {
  position: absolute;
  inset: 0;
  z-index: 0;
}

.btn3d-canvas :deep(canvas) {
  display: block;
  width: 100% !important;
  height: 100% !important;
}

/* 文字浮在模型之上 */
.btn3d-label {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #f8f1e2;
  letter-spacing: 2px;
  pointer-events: none;
}

.btn3d--danger .btn3d-label {
  color: #a63d2f;
}
</style>
