# Boss直聘批量私信工具

基于 Playwright 的浏览器自动化脚本，支持向 Boss直聘用户批量发送私信。

---

## 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## 快速上手

### 第一步：登录并保存 Cookie

```bash
python boss_sender.py --save-cookies
```

浏览器会自动打开，**手动扫码登录**后脚本自动保存 Cookie（存为 `cookies.json`），无需每次重新登录。

---

### 第二步：添加目标用户

**方式一：直接添加单个或多个用户链接**

```bash
python boss_sender.py --add "https://www.zhipin.com/resume/aabbcc112233.html"
python boss_sender.py --add "https://www.zhipin.com/resume/aaa.html" "https://www.zhipin.com/resume/bbb.html"
```

**方式二：从文件批量导入**

```bash
python boss_sender.py --add-file new_users.txt
```

`new_users.txt` 每行一个链接，`#` 开头的行为注释。

**方式三：直接编辑 `users.txt`**

打开 `users.txt`，每行填入一个用户链接即可。

---

### 第三步：配置消息内容

编辑 `config.json`，修改 `message` 字段：

```json
{
  "message": "你好，我看了你的简历，觉得你的背景很适合我们团队，想和你聊聊，方便的话请回复我。",
  "delay_min": 8,
  "delay_max": 20
}
```

也可以通过命令行临时覆盖消息（不修改文件）：

```bash
python boss_sender.py --send --message "您好！我们有一个非常适合您的机会，欢迎聊聊。"
```

---

### 第四步：发送消息

```bash
python boss_sender.py --send
```

脚本会自动跳过已发送的用户，每条消息之间随机等待 8-20 秒（可在 `config.json` 中调整）。

---

## 常用命令

| 命令 | 说明 |
|------|------|
| `--save-cookies` | 打开浏览器登录，保存 Cookie |
| `--add URL [URL...]` | 添加用户到 users.txt |
| `--add-file FILE` | 从文件批量添加用户 |
| `--send` | 向所有未发送用户发送消息 |
| `--status` | 查看发送统计（成功/失败/待发送） |
| `--retry-failed` | 重试所有失败的用户，配合 `--send` 使用 |
| `--headless` | 无头模式（不显示浏览器窗口） |
| `--message "..."` | 临时指定消息内容 |

---

## 配置说明（config.json）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `message` | 示例招呼语 | 发送的消息内容 |
| `delay_min` | `8` | 每条消息之间的最小等待秒数 |
| `delay_max` | `20` | 每条消息之间的最大等待秒数 |
| `cookies_file` | `cookies.json` | Cookie 存储路径 |
| `users_file` | `users.txt` | 用户列表文件 |
| `log_file` | `sent.log` | 发送记录文件（防止重复发送） |
| `headless` | `false` | 是否无头模式 |
| `timeout` | `30000` | 页面超时（毫秒） |

---

## 用户链接格式

`users.txt` 支持以下格式：

- **简历页 URL**：`https://www.zhipin.com/resume/xxxxxxxxxxxxxxxx.html`
- **候选人主页 URL**：`https://www.zhipin.com/candidate/xxxxxxxxxxxxxxxx.html`
- **已有聊天的 IM 用户 ID**：直接填写数字或字符串 ID

---

## 注意事项

1. **Cookie 有效期**：Cookie 通常有效数天，失效后重新运行 `--save-cookies` 即可。
2. **发送频率**：建议 `delay_min` 不低于 5 秒，避免触发平台风控。
3. **幂等性**：`sent.log` 记录已发送用户，重复运行不会重复发送。
4. **失败重试**：先运行 `--retry-failed`，再运行 `--send`。
