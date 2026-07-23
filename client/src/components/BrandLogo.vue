<template>
  <div class="brand-logo" :style="{ color, fontSize: fontSize + 'px' }">
    <span class="brand-word">Allianz</span>
    <svg class="brand-emblem" viewBox="0 0 36 36" aria-hidden="true">
      <circle cx="18" cy="18" r="15.2" fill="none" stroke="currentColor" stroke-width="3" />
      <line x1="11.5" y1="10.5" x2="11.5" y2="25.5" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" />
      <line x1="18" y1="8.5" x2="18" y2="27.5" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" />
      <line x1="24.5" y1="10.5" x2="24.5" y2="25.5" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" />
    </svg>
  </div>
</template>

<script setup>
// Allianz 品牌 Logo：字标 + 圆环三立柱徽标（内联 SVG，不依赖外部图片）
// color 默认白色（用于深蓝顶栏），登录页等浅色背景可传 '#005EB8'
defineProps({
  color: { type: String, default: '#ffffff' },
  fontSize: { type: Number, default: 20 },
})
</script>

<style scoped>
.brand-logo {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  line-height: 1;
}
.brand-word {
  font-family: 'Helvetica Neue', Arial, sans-serif;
  font-weight: 700;
  font-style: italic;
  letter-spacing: 1px;
}
.brand-emblem {
  width: 1.2em;
  height: 1.2em;
  display: block;
}
</style>
