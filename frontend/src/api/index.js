import axios from 'axios'

const TOKEN_KEY = 'mirofish_auth_token'

const resolveBaseURL = () => {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim()
  if (configured) return configured

  // 纯内网/离线部署默认走同源，由网关或 Nginx 统一转发 /api
  // 若前后端分端口部署，请显式设置 VITE_API_BASE_URL（如 http://<host>:5001）
  return ''
}

// 创建axios实例
const service = axios.create({
  baseURL: resolveBaseURL(),
  timeout: 300000, // 5分钟超时（本体生成可能需要较长时间）
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
service.interceptors.request.use(
  config => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => {
    console.error('Request error:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器（容错重试机制）
service.interceptors.response.use(
  response => {
    const res = response.data
    
    // 如果返回的状态码不是success，则抛出错误
    if (!res.success && res.success !== undefined) {
      console.error('API Error:', res.error || res.message || 'Unknown error')
      return Promise.reject(new Error(res.error || res.message || 'Error'))
    }
    
    return res
  },
  error => {
    console.error('Response error:', error)

    const backendErrorMessage =
      error?.response?.data?.error ||
      error?.response?.data?.message

    if (error?.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (window.location.pathname !== '/login') {
        const redirect = encodeURIComponent(window.location.pathname + window.location.search)
        window.location.href = `/login?redirect=${redirect}`
      }
    }
    
    // 处理超时
    if (error.code === 'ECONNABORTED' && error.message.includes('timeout')) {
      console.error('Request timeout')
    }
    
    // 处理网络错误
    if (error.message === 'Network Error') {
      const isApiPath = typeof error?.config?.url === 'string' && error.config.url.startsWith('/api/')
      const configured = import.meta.env.VITE_API_BASE_URL?.trim()
      if (isApiPath && !configured) {
        error.message = '网络错误：无法连接后端 API。当前使用同源 /api，请确认网关已转发 /api，或设置 VITE_API_BASE_URL。'
      }
      console.error('Network error - please check your connection')
    }

    if (backendErrorMessage) {
      error.message = backendErrorMessage
    }
    
    return Promise.reject(error)
  }
)

// 带重试的请求函数
export const requestWithRetry = async (requestFn, maxRetries = 3, delay = 1000) => {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await requestFn()
    } catch (error) {
      if (i === maxRetries - 1) throw error
      
      console.warn(`Request failed, retrying (${i + 1}/${maxRetries})...`)
      await new Promise(resolve => setTimeout(resolve, delay * Math.pow(2, i)))
    }
  }
}

export default service
