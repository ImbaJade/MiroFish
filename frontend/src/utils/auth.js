const TOKEN_KEY = 'mirofish_auth_token'

export const login = ({ username, password }) => {
  const validUsername = 'admin'
  const validPassword = 'MiroFish123'

  if (username !== validUsername || password !== validPassword) {
    return {
      success: false,
      message: '用户名或密码错误'
    }
  }

  const authToken = `mirofish-${Date.now()}`
  localStorage.setItem(TOKEN_KEY, authToken)

  return {
    success: true
  }
}

export const logout = () => {
  localStorage.removeItem(TOKEN_KEY)
}

export const isAuthenticated = () => {
  return Boolean(localStorage.getItem(TOKEN_KEY))
}
