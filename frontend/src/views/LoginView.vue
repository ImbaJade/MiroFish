<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="title">MiroFish 登录</h1>
      <p class="subtitle">请先登录后再访问模拟平台</p>

      <form class="login-form" @submit.prevent="handleLogin">
        <label class="field-label" for="username">用户名</label>
        <input
          id="username"
          v-model.trim="form.username"
          class="field-input"
          type="text"
          placeholder="请输入用户名"
          autocomplete="username"
        />

        <label class="field-label" for="password">密码</label>
        <input
          id="password"
          v-model="form.password"
          class="field-input"
          type="password"
          placeholder="请输入密码"
          autocomplete="current-password"
        />

        <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

        <button class="submit-btn" type="submit">登录</button>
      </form>

      <p class="tips">账号密码由后端 .env 中 AUTH_USERNAME / AUTH_PASSWORD 配置</p>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login } from '../utils/auth'

const router = useRouter()
const route = useRoute()

const form = reactive({
  username: '',
  password: ''
})

const errorMessage = ref('')

const handleLogin = async () => {
  errorMessage.value = ''

  try {
    const result = await login({
      username: form.username,
      password: form.password
    })

    if (!result.success) {
      errorMessage.value = result.message
      return
    }

    const redirectPath = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    router.push(redirectPath)
  } catch (error) {
    errorMessage.value = error?.message || '登录失败，请稍后重试'
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #111111 0%, #2c2c2c 100%);
  padding: 24px;
}

.login-card {
  width: 100%;
  max-width: 420px;
  background: #ffffff;
  border: 2px solid #000000;
  border-radius: 12px;
  padding: 32px;
  box-shadow: 10px 10px 0 #000000;
}

.title {
  font-size: 30px;
  font-weight: 700;
  margin-bottom: 8px;
}

.subtitle {
  color: #666666;
  margin-bottom: 24px;
}

.login-form {
  display: flex;
  flex-direction: column;
}

.field-label {
  font-weight: 600;
  margin-bottom: 8px;
}

.field-input {
  width: 100%;
  border: 2px solid #000000;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 16px;
  font-size: 14px;
}

.field-input:focus {
  outline: none;
  box-shadow: 0 0 0 3px rgba(255, 149, 0, 0.3);
}

.error-text {
  color: #e53935;
  font-size: 14px;
  margin-bottom: 14px;
}

.submit-btn {
  border: 2px solid #000000;
  background: #ff9500;
  color: #000000;
  border-radius: 8px;
  padding: 12px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
}

.submit-btn:hover {
  background: #ff8a00;
}

.tips {
  margin-top: 16px;
  color: #777777;
  font-size: 13px;
}
</style>
