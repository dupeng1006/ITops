/**
 * 任务轮询组合式函数：2s 间隔轮询任务详情直至 success/failed。
 * 用法：const { job, polling, start, stop } = useJobPolling()
 */
import { ref, onUnmounted } from 'vue'
import api from '../api'

export function useJobPolling(intervalMs = 2000) {
  const job = ref(null)
  const polling = ref(false)
  let timer = null

  async function refresh(jobId) {
    const resp = await api.get(`/recon/jobs/${jobId}`, { params: { log_tail: 80 } })
    job.value = resp.data
    if (resp.data.status === 'success' || resp.data.status === 'failed') {
      stop()
    }
    return resp.data
  }

  function start(jobId) {
    stop()
    polling.value = true
    refresh(jobId).catch(() => stop())
    timer = setInterval(() => {
      refresh(jobId).catch(() => stop())
    }, intervalMs)
  }

  function stop() {
    polling.value = false
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  onUnmounted(stop)
  return { job, polling, start, stop, refresh }
}
