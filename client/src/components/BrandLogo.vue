<template>
  <img class="brand-logo" :src="src" :style="{ height: height + 'px' }" alt="Allianz 安联" />
</template>

<script setup>
// Allianz 品牌 Logo（官方图片，透明底）
// variant='white' 白色版（深蓝顶栏）；variant='blue' 蓝色版（浅色背景/登录页）
import { computed } from 'vue'
import logoWhite from '../assets/logo-white.png'
import logoBlue from '../assets/logo-blue.png'

const props = defineProps({
  variant: { type: String, default: 'white' },
  height: { type: Number, default: 30 },
})
const src = computed(() => (props.variant === 'blue' ? logoBlue : logoWhite))
</script>

<style scoped>
.brand-logo { display: block; user-select: none; }
</style>
