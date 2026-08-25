import axios from 'axios'
import { message } from 'ant-design-vue'

// 开发期由 Vite 代理转发 (/api -> FastAPI :8000)，生产期同源部署
const http = axios.create({
  baseURL: '/',
  timeout: 30000,
})

// 响应拦截：统一解包 { code, message, data }
http.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === 'object' && 'code' in body && body.code !== 200) {
      message.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message || '请求失败'))
    }
    return body
  },
  (err) => {
    const msg = err.response?.data?.message || err.message || '网络错误'
    message.error(msg)
    return Promise.reject(err)
  }
)

export default http
