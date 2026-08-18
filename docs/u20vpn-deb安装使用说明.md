# u20vpn deb 包安装使用说明

适用对象：Ubuntu 20.04（focal）及其 arm64 衍生系统的 u20vpn deb 安装包。

- 包名：`u20vpn`（当前版本 0.1.0）
- 产物：`u20vpn_0.1.0_arm64.deb`
- 特性：自包含，Python 依赖（cryptography 41.0.7 等）装在
  `/usr/lib/u20vpn/`，无需 pip、不依赖系统 python3-cryptography。

---

## 1. 安装 / 升级 / 卸载

```bash
# 安装
sudo dpkg -i u20vpn_0.1.0_arm64.deb

# 升级（同名新包直接覆盖安装）
sudo dpkg -i u20vpn_0.1.1_arm64.deb

# 卸载
sudo dpkg -r u20vpn
```

安装后验证：

```bash
u20vpn --help          # 应输出 gen-key / clash / run 三个子命令
```

安装内容一览：

| 路径 | 说明 |
|---|---|
| `/usr/bin/u20vpn` | 全局命令入口 |
| `/usr/lib/u20vpn/` | 程序与私有 Python 依赖 |
| `/usr/share/u20vpn/examples/` | 服务模板、配置示例与辅助脚本 |

---

## 2. 用法一：自研 TUN/UDP 隧道（实验/内网互访）

需要 root 权限与内核 TUN 支持（容器环境一般没有 `/dev/net/tun`）。

```bash
# 生成预共享密钥（两端同一把）
u20vpn gen-key | sudo tee /etc/u20vpn/secret.key >/dev/null
sudo chmod 600 /etc/u20vpn/secret.key

# 服务端（公网机器，放行 UDP 51888）
sudo u20vpn run --mode server --listen 0.0.0.0:51888 \
  --secret-file /etc/u20vpn/secret.key --address 10.88.0.1/24 --setup

# 客户端
sudo u20vpn run --mode client --remote 服务器IP:51888 \
  --secret-file /etc/u20vpn/secret.key --address 10.88.0.2/24 --setup

# 服务端开启 NAT，让客户端借服务器上网（可选）
sudo bash /usr/share/u20vpn/examples/server-nat-up.sh
```

---

## 3. 用法二：Clash 订阅代理模式（日常推荐）

架构：**sing-box 内核负责代理转发，u20vpn 负责订阅转换与节点界面**。

```
订阅链接 ──> manual-subscription-to-singbox.py ──> /etc/singbox/config.json
                                                          │
                                                    sing-box 服务
                          ┌───────────────────────────────┼────────────────┐
                    7890 混合代理                  9090 Clash 兼容 API  7895 节点界面
                 （系统代理指向这里）              （供 UI 调用）      （浏览器打开切换节点）
```

> 背景：当前订阅节点全为 anytls 协议，mihomo 内核无法握手，
> 因此内核固定使用 sing-box（当前 1.13.18）。mihomo 与 sing-box
> 同时监听 7890/9090，**两者绝不能同时启动**。

### 3.1 首次部署

```bash
# ① 安装 u20vpn deb（见第 1 节）

# ② 安装 sing-box 内核
sudo install -m 0755 /path/to/sing-box /usr/local/bin/sing-box

# ③ 准备目录与订阅文件
sudo mkdir -p /etc/singbox
curl -fsSL "你的Clash订阅链接" -o /tmp/subscription-clash.yaml
sudo mv /tmp/subscription-clash.yaml /etc/singbox/subscription-clash.yaml
sudo chmod 600 /etc/singbox/subscription-clash.yaml

# ④ 生成 sing-box 配置（控制器密钥可先随机生成一段，UI 会读配置里的 secret）
sudo python3 /usr/share/u20vpn/examples/manual-subscription-to-singbox.py \
  --subscription /etc/singbox/subscription-clash.yaml \
  --output /etc/singbox/config.json \
  --secret "你的控制器密钥"
sudo /usr/local/bin/sing-box check -c /etc/singbox/config.json

# ⑤ 安装服务并启动
sudo cp /usr/share/u20vpn/examples/u20vpn-singbox.service \
        /etc/systemd/system/sing-box.service
sudo cp /usr/share/u20vpn/examples/u20vpn-mihomo-ui.service \
        /etc/systemd/system/u20vpn-mihomo-ui.service
sudo systemctl daemon-reload
sudo systemctl enable --now sing-box u20vpn-mihomo-ui
```

### 3.2 订阅更新（节点变化后）

```bash
# 重新拉订阅
curl -fsSL "你的Clash订阅链接" -o /tmp/subscription-clash.yaml
sudo mv /tmp/subscription-clash.yaml /etc/singbox/subscription-clash.yaml

# 重新生成配置（secret 从现有 sing-box 配置读取，保持 UI 密钥不变）
SECRET=$(sudo python3 -c \
  "import json;print(json.load(open('/etc/singbox/config.json'))['experimental']['clash_api']['secret'])")
sudo python3 /usr/share/u20vpn/examples/manual-subscription-to-singbox.py \
  --subscription /etc/singbox/subscription-clash.yaml \
  --output /etc/singbox/config.json \
  --secret "$SECRET"

sudo /usr/local/bin/sing-box check -c /etc/singbox/config.json
sudo systemctl restart sing-box
```

### 3.3 日常使用

- **浏览器打开节点界面**：`http://127.0.0.1:7895/`
  可查看代理组、切换节点、延迟测速。
- **设置系统代理**：HTTP/SOCKS 混合代理指向 `127.0.0.1:7890`。
- **验证连通性**：

```bash
curl -x http://127.0.0.1:7890 https://www.gstatic.com/generate_204 -I  # 期望 204
curl -x http://127.0.0.1:7890 https://www.google.com -I                 # 期望 200
```

### 3.4 服务管理

```bash
systemctl status sing-box u20vpn-mihomo-ui
sudo systemctl restart sing-box           # 重启代理内核
sudo systemctl restart u20vpn-mihomo-ui   # 重启节点界面
sudo systemctl stop mihomo                # 确保 mihomo 不抢占 7890/9090
```

---

## 4. 常见问题

| 现象 | 处理 |
|---|---|
| 节点全部测速失败、代理秒断 | 多为 anytls 节点遇到 mihomo 内核，改用 sing-box 方案（见 3.1） |
| 7890 端口被占用 | 确认 `mihomo.service` 已停止，不要与 sing-box 同时启动 |
| `curl` 返回 000 | 依次检查 `sing-box.service` 状态、`config.json` 校验、订阅是否过期 |
| TUN 模式报 `No such file or directory` | 容器环境无 `/dev/net/tun`，请在实体机/目标板验证隧道模式 |
| UI 打不开但代理正常 | 检查 `u20vpn-mihomo-ui.service` 与 7895 端口 |

---

## 5. 重新打包 deb

修改源码后，在项目目录执行：

```bash
bash scripts/build-deb.sh
# 产物: dist/u20vpn_<版本>_<架构>.deb
```

脚本从本地 `.venv` 复制依赖，因此打包前先确保 `.venv` 中已执行
`pip install -e .`。当前包为 arm64 架构；x86_64 目标机需要在
对应架构环境运行同一脚本。
