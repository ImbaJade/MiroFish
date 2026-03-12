import request from '../api'

const TOKEN_KEY = 'mirofish_auth_token'

export const login = async ({ username, password }) => {
  const response = await request.post('/api/auth/login', {
    username,
    password
  })

  const payload = response?.data ?? response
  const token = payload?.token || payload?.data?.token
  if (!token) {
    return {
      success: false,
      message: '登录失败：未获取到令牌'
    }
  }

  localStorage.setItem(TOKEN_KEY, token)
  return { success: true }
}

export const logout = () => {
  localStorage.removeItem(TOKEN_KEY)
}

export const getToken = () => localStorage.getItem(TOKEN_KEY)

export const isAuthenticated = () => Boolean(getToken())
