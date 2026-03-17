<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="brand-card">
        <div class="brand-mark">Z</div>
        <div class="brand-copy">
          <strong>Zoe 医疗助手</strong>
          <span>智能分诊与就诊陪伴</span>
        </div>
      </div>

      <div v-if="currentUser" class="user-info">
        <span class="user-label">当前用户</span>
        <strong>{{ currentUser.username }}</strong>
      </div>

      <div v-if="currentUser" class="action-group">
        <el-button class="new-chat-button" @click="newChat">+ 新会话</el-button>
        <el-button class="compress-memory-button" @click="compressMemory" :loading="isCompressing">
          压缩记忆
        </el-button>
      </div>

      <div v-if="currentUser" class="sessions-panel">
        <div class="sessions-header">
          <span>历史会话</span>
          <el-button text size="small" @click="loadSessions" :disabled="isSessionsLoading">刷新</el-button>
        </div>
        <div class="sessions-list" v-loading="isSessionsLoading">
          <button
            v-for="session in sessions"
            :key="session.memoryId"
            class="session-item"
            :class="{ active: String(session.memoryId) === String(uuid) }"
            @click="openSession(session.memoryId)"
          >
            <div class="session-title">{{ session.title || '新会话' }}</div>
            <div class="session-meta">
              <span>{{ session.turns }} 轮</span>
              <span>{{ formatTime(session.updatedAt) }}</span>
            </div>
          </button>
          <div v-if="!sessions.length && !isSessionsLoading" class="empty-sessions">暂无历史会话</div>
        </div>
      </div>

      <el-button v-if="currentUser" class="logout-button" @click="logout">退出登录</el-button>
    </aside>

    <div class="main-content">
      <div v-if="!currentUser" class="auth-wrapper">
        <el-card class="auth-card">
          <h3>{{ authMode === 'login' ? '欢迎回来' : '创建账户' }}</h3>
          <el-input v-model="authForm.username" placeholder="用户名" class="auth-input" />
          <el-input v-model="authForm.password" placeholder="密码（至少6位）" show-password class="auth-input" />
          <el-input
            v-if="authMode === 'register'"
            v-model="authForm.confirmPassword"
            placeholder="确认密码"
            show-password
            class="auth-input"
          />
          <el-button type="primary" class="auth-btn" @click="submitAuth" :loading="isAuthSubmitting">
            {{ authMode === 'login' ? '登录' : '注册' }}
          </el-button>
          <el-button text class="auth-switch" @click="switchAuthMode">
            {{ authMode === 'login' ? '没有账号？去注册' : '已有账号？去登录' }}
          </el-button>
        </el-card>
      </div>

      <div class="chat-container" v-loading="isSessionOpening">
        <template v-if="currentUser">
          <div class="chat-head">
            <div>
              <h2>智能问诊会话</h2>
              <p>描述症状后可直接查询科室与号源</p>
            </div>
            <span class="session-badge">会话ID: {{ uuid }}</span>
          </div>

          <div class="message-list" ref="messaggListRef">
            <div
              v-for="(message, index) in messages"
              :key="index"
              :class="message.isUser ? 'message user-message' : 'message bot-message'"
            >
              <span class="avatar">{{ message.isUser ? '我' : 'Z' }}</span>
              <span class="message-content">
                <span v-html="message.content"></span>
                <span class="loading-dots" v-if="message.isThinking || message.isTyping">
                  <span class="dot"></span>
                  <span class="dot"></span>
                </span>
              </span>
            </div>
          </div>

          <div class="input-container">
            <el-input
              v-model="inputMessage"
              placeholder="请输入你的症状、就诊需求或预约问题"
              @keyup.enter="sendMessage"
            />
            <el-button @click="sendMessage" :disabled="isSending" type="primary">发送</el-button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue';
import axios from 'axios';
import { v4 as uuidv4 } from 'uuid';
import { ElMessage } from 'element-plus';

const messaggListRef = ref();
const isSending = ref(false);
const isCompressing = ref(false);
const isAuthSubmitting = ref(false);
const isSessionsLoading = ref(false);
const isSessionOpening = ref(false);
const uuid = ref('');
const inputMessage = ref('');
const messages = ref([]);
const sessions = ref([]);
const currentUser = ref(null);
const authMode = ref('login');
const authForm = ref({
  username: '',
  password: '',
  confirmPassword: '',
});

onMounted(async () => {
  loadAuthUser();
  watch(messages, () => scrollToBottom(), { deep: true });
  if (currentUser.value) {
    initUUID();
    await loadSessions();
    await openSession(uuid.value, true);
  }
});

const scrollToBottom = () => {
  if (messaggListRef.value) {
    messaggListRef.value.scrollTop = messaggListRef.value.scrollHeight;
  }
};

const hello = () => {
  if (!currentUser.value) return;
  sendRequest('你好');
};

const sendMessage = () => {
  if (!currentUser.value) {
    ElMessage.warning('请先登录');
    return;
  }
  if (inputMessage.value.trim()) {
    sendRequest(inputMessage.value.trim());
    inputMessage.value = '';
  }
};

const sendRequest = (message) => {
  isSending.value = true;
  messages.value.push({
    isUser: true,
    content: message,
    isTyping: false,
    isThinking: false,
  });

  const botMsg = {
    isUser: false,
    content: '',
    isTyping: true,
    isThinking: false,
  };
  messages.value.push(botMsg);
  const lastMsg = messages.value[messages.value.length - 1];
  scrollToBottom();

  axios
    .post(
      '/api/zoe/chat',
      { userId: currentUser.value.userId, memoryId: String(uuid.value), message },
      {
        responseType: 'stream',
        onDownloadProgress: (e) => {
          const fullText = e.event.target.responseText;
          const newText = fullText.substring(lastMsg.content.length);
          lastMsg.content += newText;
          scrollToBottom();
        },
      }
    )
    .then(() => {
      messages.value.at(-1).isTyping = false;
      loadSessions();
      isSending.value = false;
    })
    .catch((error) => {
      console.error('流式错误:', error);
      messages.value.at(-1).content = '请求失败，请重试';
      messages.value.at(-1).isTyping = false;
      isSending.value = false;
    });
};

const initUUID = () => {
  let storedUUID = localStorage.getItem(memoryKey());
  if (!storedUUID) {
    storedUUID = String(uuidToNumber(uuidv4()));
    localStorage.setItem(memoryKey(), storedUUID);
  }
  uuid.value = String(storedUUID);
};

const memoryKey = () => {
  return currentUser.value ? `chat_memory_${currentUser.value.userId}` : 'user_uuid';
};

const uuidToNumber = (value) => {
  let number = 0;
  for (let i = 0; i < value.length && i < 6; i++) {
    const hexValue = value[i];
    number = number * 16 + (parseInt(hexValue, 16) || 0);
  }
  return number % 1000000;
};

const newChat = async () => {
  const nextId = String(uuidToNumber(uuidv4()));
  uuid.value = nextId;
  localStorage.setItem(memoryKey(), nextId);
  messages.value = [];
  hello();
  await loadSessions();
};

const compressMemory = () => {
  isCompressing.value = true;
  axios
    .post('/api/zoe/memory/compress', { userId: currentUser.value.userId, memoryId: String(uuid.value) })
    .then((res) => {
      const data = res.data || {};
      messages.value.push({
        isUser: false,
        content: `记忆压缩完成：长期记忆条数 ${data.long_term_facts_count ?? 0}`,
        isTyping: false,
        isThinking: false,
      });
      scrollToBottom();
    })
    .catch((error) => {
      console.error('压缩记忆失败:', error);
      messages.value.push({
        isUser: false,
        content: '记忆压缩失败，请稍后重试',
        isTyping: false,
        isThinking: false,
      });
      scrollToBottom();
    })
    .finally(() => {
      isCompressing.value = false;
    });
};

const loadAuthUser = () => {
  const raw = localStorage.getItem('auth_user');
  if (!raw) return;
  try {
    currentUser.value = JSON.parse(raw);
  } catch {
    localStorage.removeItem('auth_user');
  }
};

const loadSessions = async () => {
  if (!currentUser.value) return;
  isSessionsLoading.value = true;
  try {
    const res = await axios.get('/api/zoe/sessions', {
      params: { userId: currentUser.value.userId },
    });
    sessions.value = (res.data?.sessions || []).map((item) => ({
      memoryId: String(item.memoryId),
      title: item.title,
      turns: item.turns || 0,
      updatedAt: item.updatedAt,
    }));
  } catch (error) {
    console.error('加载会话列表失败:', error);
    ElMessage.error('加载历史会话失败');
  } finally {
    isSessionsLoading.value = false;
  }
};

const openSession = async (memoryId, silent = false) => {
  if (!currentUser.value || !memoryId) return;
  uuid.value = String(memoryId);
  localStorage.setItem(memoryKey(), uuid.value);
  isSessionOpening.value = true;
  try {
    const res = await axios.get(`/api/zoe/sessions/${uuid.value}`, {
      params: { userId: currentUser.value.userId },
    });
    messages.value = (res.data?.messages || []).map((m) => ({
      isUser: !!m.isUser,
      content: m.content || '',
      isTyping: false,
      isThinking: false,
    }));
    if (!messages.value.length) {
      hello();
    }
  } catch {
    messages.value = [];
    if (!silent) {
      ElMessage.warning('会话不存在，已为你创建新会话');
    }
    hello();
  } finally {
    isSessionOpening.value = false;
  }
};

const formatTime = (value) => {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const switchAuthMode = () => {
  authMode.value = authMode.value === 'login' ? 'register' : 'login';
};

const submitAuth = async () => {
  if (!authForm.value.username || !authForm.value.password) {
    ElMessage.warning('请输入用户名和密码');
    return;
  }
  if (authMode.value === 'register' && authForm.value.password !== authForm.value.confirmPassword) {
    ElMessage.warning('两次输入密码不一致');
    return;
  }
  isAuthSubmitting.value = true;
  try {
    const api = authMode.value === 'login' ? '/api/auth/login' : '/api/auth/register';
    const res = await axios.post(api, {
      username: authForm.value.username,
      password: authForm.value.password,
    });
    currentUser.value = res.data;
    localStorage.setItem('auth_user', JSON.stringify(res.data));
    initUUID();
    messages.value = [];
    await loadSessions();
    await openSession(uuid.value, true);
    ElMessage.success(authMode.value === 'login' ? '登录成功' : '注册成功');
  } catch (err) {
    console.error(err);
    ElMessage.error('认证失败，请检查用户名和密码');
  } finally {
    isAuthSubmitting.value = false;
  }
};

const logout = () => {
  localStorage.removeItem('auth_user');
  if (currentUser.value) {
    localStorage.removeItem(`chat_memory_${currentUser.value.userId}`);
  }
  messages.value = [];
  sessions.value = [];
  currentUser.value = null;
};
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  background:
    radial-gradient(circle at 10% 10%, rgba(26, 188, 156, 0.16), transparent 35%),
    radial-gradient(circle at 85% 18%, rgba(245, 166, 35, 0.16), transparent 36%),
    #f6f8f3;
}

.sidebar {
  width: 300px;
  background: linear-gradient(170deg, #fdfdf8, #eef4ea);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  border-right: 1px solid #d7ded1;
}

.brand-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border-radius: 14px;
  background: #ffffffcc;
  border: 1px solid #dbe7d4;
}

.brand-mark {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #11998e, #38ef7d);
  color: #fff;
  font-weight: 800;
  font-size: 18px;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.brand-copy strong {
  color: #1f3a2f;
}

.brand-copy span {
  font-size: 12px;
  color: #5a6b61;
}

.user-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #ffffffa8;
}

.user-label {
  font-size: 12px;
  color: #6f8076;
}

.action-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.action-group :deep(.el-button + .el-button) {
  margin-left: 0;
}

.new-chat-button {
  width: 100%;
  margin-top: 4px;
  background: linear-gradient(120deg, #0ba360, #3cba92);
  color: white;
  border: none;
}

.compress-memory-button {
  width: 100%;
  background: linear-gradient(120deg, #f2994a, #f2c94c);
  color: white;
  border: none;
}

.logout-button {
  width: 100%;
  margin-top: auto;
}

.sessions-panel {
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 12px;
  border-radius: 14px;
  background: #ffffffc9;
  border: 1px solid #dbe7d4;
}

.sessions-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #365242;
  font-weight: 700;
}

.sessions-list {
  margin-top: 8px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.session-item {
  border: 1px solid #d4dfd0;
  background: #f8fbf6;
  border-radius: 10px;
  padding: 10px;
  cursor: pointer;
  text-align: left;
}

.session-item.active {
  border-color: #19a974;
  box-shadow: 0 0 0 2px #19a97426;
  background: #ecf9f2;
}

.session-title {
  font-size: 13px;
  font-weight: 600;
  color: #2f4a3a;
  display: -webkit-box;
  line-clamp: 1;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.session-meta {
  margin-top: 4px;
  font-size: 11px;
  color: #738577;
  display: flex;
  justify-content: space-between;
}

.empty-sessions {
  font-size: 12px;
  color: #7b8a80;
  padding: 8px 4px;
}

.auth-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.auth-card {
  width: 360px;
  border-radius: 16px;
  border: 1px solid #d9e5d3;
}

.auth-input {
  margin: 10px 0;
}

.auth-btn {
  width: 100%;
  margin-top: 8px;
}

.auth-switch {
  margin-top: 8px;
}

.main-content {
  flex: 1;
  padding: 18px;
  overflow-y: auto;
}

.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  border-radius: 18px;
  background: #ffffffde;
  border: 1px solid #dbe5d5;
  padding: 14px;
}

.chat-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.chat-head h2 {
  margin: 0;
  color: #2d4537;
}

.chat-head p {
  margin: 3px 0 0;
  color: #6e7f73;
  font-size: 13px;
}

.session-badge {
  font-size: 12px;
  color: #527363;
  padding: 8px 10px;
  border-radius: 999px;
  background: #eff8f2;
  border: 1px solid #cfe2d6;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  border: 1px solid #d8e4d3;
  border-radius: 14px;
  background-color: #fcfffb;
  margin-bottom: 15px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.message {
  padding: 10px 14px;
  border-radius: 12px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.message-content {
  font-size: 15px;
  line-height: 1.5;
  word-break: break-word;
}

.user-message {
  max-width: 82%;
  background: #ddf4e6;
  align-self: flex-end;
}

.bot-message {
  max-width: 82%;
  background: #f3f8fb;
  align-self: flex-start;
}

.avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
  color: #2c4638;
  background: #c9e7d6;
  flex-shrink: 0;
}

.loading-dots {
  padding-left: 5px;
}

.dot {
  display: inline-block;
  margin-left: 5px;
  width: 8px;
  height: 8px;
  background-color: #4c6f5c;
  border-radius: 50%;
  animation: pulse 1.2s infinite ease-in-out both;
}

.dot:nth-child(2) {
  animation-delay: -0.6s;
}

@keyframes pulse {
  0%,
  100% {
    transform: scale(0.6);
    opacity: 0.4;
  }

  50% {
    transform: scale(1);
    opacity: 1;
  }
}

.input-container {
  display: flex;
  align-items: center;
  gap: 10px;
}

.input-container .el-input {
  flex: 1;
}

.input-container .el-button {
  height: 40px;
  font-size: 14px;
}

@media (max-width: 980px) {
  .app-layout {
    flex-direction: column;
    height: auto;
    min-height: 100vh;
  }

  .sidebar {
    width: auto;
    border-right: none;
    border-bottom: 1px solid #d7ded1;
  }

  .sessions-panel {
    max-height: 220px;
  }

  .main-content {
    padding: 10px;
  }

  .chat-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
}
</style>
