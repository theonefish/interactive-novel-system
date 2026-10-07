<template>
  <!-- three.js 背景画布：漂浮的 3D 纸张，纯装饰层，不拦截任何交互 -->
  <canvas ref="canvasEl" class="paper-scene"></canvas>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import * as THREE from 'three'

const canvasEl = ref(null)

// three.js 运行时对象统一挂在这里，方便卸载时逐一释放，避免 WebGL 上下文泄漏
let renderer = null
let scene = null
let camera = null
let papers = []        // 漂浮纸张网格列表
let rafId = 0          // requestAnimationFrame 句柄
let mouseX = 0         // 归一化后的鼠标偏移（-1 ~ 1），用于视差
let mouseY = 0

// 与页面纸质风格一致的配色（比页面底色更浅，避免抢内容视觉焦点）
const PAPER_COLORS = [0xfdfaf2, 0xfaf3e3, 0xfdf6dd] // 米白 / 牛皮纸 / 便签黄
const ACCENT_COLOR = 0xa63d2f                       // 朱砂红点缀（小书签）

// 生成一张微微卷曲的纸：在平面网格上按正弦波抬高顶点，模拟纸张自然弯曲
function createCurledPlane(width, height, segX, segY) {
  const geometry = new THREE.PlaneGeometry(width, height, segX, segY)
  const posAttr = geometry.attributes.position
  for (let i = 0; i < posAttr.count; i++) {
    const x = posAttr.getX(i)
    const y = posAttr.getY(i)
    // 沿宽度方向做轻微拱起，纸张两端下垂，中间鼓起
    posAttr.setZ(i, Math.sin((x / width) * Math.PI) * 0.35 + Math.sin((y / height) * Math.PI) * 0.08)
  }
  geometry.computeVertexNormals()
  return geometry
}

// 初始化场景：相机、灯光、纸张
function initScene() {
  const width = window.innerWidth
  const height = window.innerHeight

  scene = new THREE.Scene()

  camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 100)
  camera.position.set(0, 0, 14)

  renderer = new THREE.WebGLRenderer({
    canvas: canvasEl.value,
    alpha: true,      // 透明背景，露出底下的 CSS 纸张色
    antialias: true,
  })
  renderer.setSize(width, height)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)) // 限制倍率，高 DPI 屏下控制填充率开销

  // 灯光：环境光保证整体亮度（偏低会让纸片显脏），方向光负责卷曲处的明暗立体感
  scene.add(new THREE.AmbientLight(0xfff6e8, 1.6))
  const keyLight = new THREE.DirectionalLight(0xffe8c8, 1.1)
  keyLight.position.set(6, 8, 10)
  scene.add(keyLight)
  const rimLight = new THREE.DirectionalLight(0xd8c8a8, 0.5)
  rimLight.position.set(-8, -4, 6)
  scene.add(rimLight)

  // 共享几何体与材质，避免为每张纸重复创建 GPU 资源
  // 半透明材质：让纸张像淡淡的水印沉在内容后方，只保留若隐若现的立体感
  const paperGeometry = createCurledPlane(2.2, 2.9, 12, 12)
  const bookmarkGeometry = new THREE.BoxGeometry(0.25, 1.1, 0.05)
  const paperMaterials = PAPER_COLORS.map(
    (color) => new THREE.MeshStandardMaterial({
      color, roughness: 0.9, metalness: 0, side: THREE.DoubleSide,
      transparent: true, opacity: 0.3,
    })
  )
  const accentMaterial = new THREE.MeshStandardMaterial({
    color: ACCENT_COLOR, roughness: 0.7, transparent: true, opacity: 0.25,
  })

  // 4 张纸 + 2 枚书签，少量点缀在画面四周偏后方，中间区域留给正文内容
  const random = (min, max) => min + Math.random() * (max - min)
  for (let i = 0; i < 6; i++) {
    const isBookmark = i >= 4
    const mesh = new THREE.Mesh(
      isBookmark ? bookmarkGeometry : paperGeometry,
      isBookmark ? accentMaterial : paperMaterials[i % paperMaterials.length]
    )
    // 水平方向刻意避开中央：随机落在左侧或右侧
    const side = Math.random() < 0.5 ? -1 : 1
    mesh.position.set(side * random(7, 13), random(-6, 6), random(-11, -5))
    mesh.rotation.set(random(-0.5, 0.5), random(-0.6, 0.6), random(-0.4, 0.4))
    // 每张纸记录自己的漂浮参数，动画时按不同相位错开，避免整齐划一
    mesh.userData = {
      floatSpeed: random(0.15, 0.4),
      floatPhase: random(0, Math.PI * 2),
      spinSpeed: random(-0.08, 0.08),
      baseY: mesh.position.y,
    }
    mesh.scale.setScalar(isBookmark ? random(0.6, 0.9) : random(0.5, 0.8))
    scene.add(mesh)
    papers.push(mesh)
  }
}

// 每帧更新：纸张缓慢漂浮自转 + 相机跟随鼠标做微小视差
function animate(clockStartTime) {
  const elapsed = (performance.now() - clockStartTime) / 1000

  for (const mesh of papers) {
    const { floatSpeed, floatPhase, spinSpeed, baseY } = mesh.userData
    mesh.position.y = baseY + Math.sin(elapsed * floatSpeed + floatPhase) * 0.6
    mesh.rotation.z += spinSpeed * 0.01
    mesh.rotation.x += spinSpeed * 0.004
  }

  // 视差：相机向鼠标反方向轻微位移，产生空间纵深错觉
  camera.position.x += (mouseX * 1.2 - camera.position.x) * 0.03
  camera.position.y += (-mouseY * 0.8 - camera.position.y) * 0.03
  camera.lookAt(0, 0, 0)

  renderer.render(scene, camera)
  rafId = requestAnimationFrame(() => animate(clockStartTime))
}

function onMouseMove(e) {
  mouseX = (e.clientX / window.innerWidth) * 2 - 1
  mouseY = (e.clientY / window.innerHeight) * 2 - 1
}

function onResize() {
  if (!renderer || !camera) return
  camera.aspect = window.innerWidth / window.innerHeight
  camera.updateProjectionMatrix()
  renderer.setSize(window.innerWidth, window.innerHeight)
}

// 页面切到后台时暂停渲染，避免无谓的 GPU 占用
function onVisibilityChange() {
  if (document.hidden) {
    cancelAnimationFrame(rafId)
  } else {
    cancelAnimationFrame(rafId)
    rafId = requestAnimationFrame(() => animate(startTime))
  }
}

let startTime = 0

onMounted(() => {
  initScene()
  startTime = performance.now()
  rafId = requestAnimationFrame(() => animate(startTime))
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('resize', onResize)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(rafId)
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('resize', onResize)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  // 释放 GPU 资源：几何体、材质、渲染器上下文逐一销毁
  for (const mesh of papers) {
    mesh.geometry.dispose()
    if (Array.isArray(mesh.material)) mesh.material.forEach((m) => m.dispose())
    else mesh.material.dispose()
  }
  papers = []
  renderer?.dispose()
  renderer = null
  scene = null
  camera = null
})
</script>

<style scoped>
.paper-scene {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  pointer-events: none; /* 装饰层不拦截鼠标事件 */
}
</style>
