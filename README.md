# u20vpn

`u20vpn` 是一个面向 Ubuntu 20.04 的最小可用三层 VPN 隧道工具。它使用 Linux TUN 设备收发 IP 包，通过 UDP 转发，并用预共享密钥派生出的 ChaCha20-Poly1305 会话密钥保护数据。

适合学习、实验环境或小规模自建内网访问。生产环境建议优先使用 WireGuard 或 OpenVPN。

## 安装

### 方式 A：deb 包（推荐，Ubuntu 20.04）

```bash
sudo dpkg -i dist/u20vpn_0.1.0_arm64.deb
u20vpn --help
```

自包含包：程序与 Python 依赖装在 `/usr/lib/u20vpn/`，命令全局可用，
无需 pip 与虚拟环境。完整使用说明见
[docs/u20vpn-deb安装使用说明.md](docs/u20vpn-deb安装使用说明.md)。

### 方式 B：源码 + venv（开发）

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip iproute2 iptables curl ca-certificates

python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .
```

### 重新打包 deb

修改源码后执行：

```bash
bash scripts/build-deb.sh
```

产物为 `dist/u20vpn_<版本>_<架构>.deb`。当前包为 arm64 架构；
x86_64 目标机需要在对应架构环境运行同一脚本。

## 功能

- 服务端/客户端两种运行模式
- 基于 `/dev/net/tun` 的三层 IP 隧道
- UDP 传输，支持客户端 NAT 后主动连接
- 预共享密钥认证与加密
- 可选自动配置 TUN 地址、MTU 和接口状态
- 提供路由/NAT 辅助脚本

## Clash 订阅代理模式

如果你已有 Clash 订阅链接，`u20vpn` 负责安装辅助、生成配置和提供本地节点界面。

> 当前部署状态：订阅节点全为 anytls 协议，mihomo 内核无法完成握手，
> 已切换为 sing-box（1.13.18）方案（见下一节），mihomo 服务已停用。
> 以下 mihomo 流程保留作为兼容方案参考。

### 1. 安装项目环境

见顶部「安装」章节（deb 包或 venv 均可）。

### 2. 安装 mihomo 内核

```bash
sudo bash scripts/install-mihomo-ubuntu20.sh
```

### 3. 保存订阅链接

```bash
sudo mkdir -p /etc/mihomo
sudo sh -c 'printf "%s\n" "你的Clash订阅链接" > /etc/mihomo/subscription.url'
sudo chmod 600 /etc/mihomo/subscription.url
```

### 4. 生成配置并启动

使用绝对路径可以避免 `sudo: u20vpn: command not found`（venv 环境）：

```bash
sudo "$(pwd)/.venv/bin/u20vpn" clash init \
  --subscription-file /etc/mihomo/subscription.url \
  --config /etc/mihomo/config.yaml \
  --service /etc/systemd/system/mihomo.service

sudo systemctl daemon-reload
sudo systemctl enable --now mihomo
```

> deb 安装时可直接使用全局命令 `u20vpn clash init ...`。

### 5. 验证连接

```bash
systemctl is-enabled mihomo
systemctl is-active mihomo
sudo ss -ltnp | grep -E '7890|9090|mihomo' || true
curl -x http://127.0.0.1:7890 https://www.gstatic.com/generate_204 -I
```

正常应看到 `enabled`、`active`，并且 `curl` 返回 `HTTP/2 204`。

### 6. 节点界面

```bash
sudo "$(pwd)/.venv/bin/u20vpn" clash ui --config /etc/mihomo/config.yaml
```

deb 安装时直接使用 `u20vpn clash ui --config /etc/mihomo/config.yaml`。

浏览器打开：

```text
http://127.0.0.1:7895/
```

界面支持查看代理组、切换节点和测速。

### 7. 终端代理环境变量与开机自动选节点

```bash
# 终端走代理（写入 ~/.bashrc，排除 localhost/内网段）
bash scripts/setup-terminal-proxy.sh on

# 开机自动切换固定节点（配合 systemd ExecStartPost）
sudo install -m 0755 scripts/mihomo-select-node.sh /usr/local/bin/mihomo-select-node.sh
```

完整文档见 [docs/clash-mihomo-ubuntu20.md](docs/clash-mihomo-ubuntu20.md)。

## 手动订阅 + sing-box 方案（mihomo 不兼容时的回退）

如果你的订阅节点全部是 `anytls` 等协议，而 mihomo 与这些节点握手失败
（表现为所有节点测速失败、代理秒断），可以改用手动订阅 + sing-box 内核。
实测 sing-box 1.13 对相同节点可正常使用，且保留 7890 代理端口、
9090 Clash 兼容 API 和 7895 节点界面，日常使用方式不变。

```bash
# 1. 下载订阅并生成配置
#    首次部署：--secret 自定一段控制器密钥；
#    后续更新：从现有配置读取，保持 UI 密钥不变。
SECRET=$(sudo python3 -c \
  "import json;print(json.load(open('/etc/singbox/config.json'))['experimental']['clash_api']['secret'])" \
  2>/dev/null || echo "你的控制器密钥")
sudo python3 /usr/share/u20vpn/examples/manual-subscription-to-singbox.py \
  --subscription-url "你的Clash订阅链接" \
  --output /etc/singbox/config.json \
  --secret "$SECRET"

# 2. 安装内核并启动
sudo install -m 0755 /path/to/sing-box /usr/local/bin/sing-box
sudo cp /usr/share/u20vpn/examples/u20vpn-singbox.service \
        /etc/systemd/system/sing-box.service
sudo cp /usr/share/u20vpn/examples/u20vpn-mihomo-ui.service \
        /etc/systemd/system/u20vpn-mihomo-ui.service
sudo systemctl daemon-reload
sudo systemctl enable --now sing-box u20vpn-mihomo-ui

# 3. 验证
curl -x http://127.0.0.1:7890 https://www.gstatic.com/generate_204 -I  # 期望 204
```

> 源码开发环境下，把上面的 `/usr/share/u20vpn/examples/...` 换成
> `scripts/manual-subscription-to-singbox.py` 与 `examples/u20vpn-*.service` 即可。

完整说明见 [docs/manual-subscription-singbox.md](docs/manual-subscription-singbox.md)。

> 注意：`sing-box` 和 `mihomo` 都监听 7890/9090，不要同时启动两个服务。

## 自研 TUN/UDP 隧道模式

下面是本项目自带的最小 VPN 隧道模式，主要适合学习和实验。生产使用建议优先走上面的订阅模式，或使用 WireGuard/OpenVPN。

> 以下命令假设已通过顶部「安装」章节完成部署：deb 安装用全局命令
> `u20vpn`，venv 开发环境用 `.venv/bin/u20vpn`。

生成共享密钥，并把同一个文件复制到服务端和客户端：

```bash
u20vpn gen-key | sudo tee /etc/u20vpn.psk >/dev/null
sudo chmod 600 /etc/u20vpn.psk
```

### 快速运行

假设：

- 服务端公网 IP：`SERVER_PUBLIC_IP`
- 服务端隧道地址：`10.88.0.1/24`
- 客户端隧道地址：`10.88.0.2/24`
- UDP 监听端口：`51888`

服务端：

```bash
sudo u20vpn run \
  --mode server \
  --listen 0.0.0.0:51888 \
  --secret-file /etc/u20vpn.psk \
  --tun u20vpn0 \
  --address 10.88.0.1/24 \
  --setup
```

客户端：

```bash
sudo u20vpn run \
  --mode client \
  --remote SERVER_PUBLIC_IP:51888 \
  --secret-file /etc/u20vpn.psk \
  --tun u20vpn0 \
  --address 10.88.0.2/24 \
  --setup
```

连接后测试：

```bash
ping 10.88.0.1
```

### 让客户端全局走 VPN

服务端开启 IP 转发和 NAT，假设服务端出口网卡是 `eth0`：

```bash
sudo scripts/server-nat-up.sh eth0 10.88.0.0/24
```
客户端把默认路由切到隧道，假设服务端公网 IP 是 `SERVER_PUBLIC_IP`，原网关是 `192.168.1.1`，原出口网卡是 `eth0`：

```bash
sudo scripts/client-route-all-up.sh SERVER_PUBLIC_IP 192.168.1.1 eth0
```

恢复客户端默认路由：

```bash
sudo scripts/client-route-all-down.sh 192.168.1.1 eth0
```

关闭服务端 NAT：

```bash
sudo scripts/server-nat-down.sh eth0 10.88.0.0/24
```

### 配置文件运行

服务端：

```bash
sudo u20vpn run --config examples/server.json
```

客户端：

```bash
sudo u20vpn run --config examples/client.json --remote SERVER_PUBLIC_IP:51888
```

命令行参数会覆盖配置文件中的同名字段。

### systemd 示例

复制示例配置和密钥后：

```bash
sudo mkdir -p /etc/u20vpn
sudo cp examples/server.json /etc/u20vpn/server.json
sudo cp examples/u20vpn-server.service /etc/systemd/system/u20vpn-server.service
sudo systemctl daemon-reload
sudo systemctl enable --now u20vpn-server
```

客户端同理可使用 `examples/u20vpn-client.service`。

## 文档索引

- [docs/u20vpn-deb安装使用说明.md](docs/u20vpn-deb安装使用说明.md)：deb 包安装、
  订阅代理模式与隧道模式的完整使用说明（随 deb 包分发）
- [docs/clash-mihomo-ubuntu20.md](docs/clash-mihomo-ubuntu20.md)：mihomo 订阅模式详细说明
- [docs/manual-subscription-singbox.md](docs/manual-subscription-singbox.md)：
  sing-box 回退方案详细说明

## 安全说明

这个项目实现的是一个小型 VPN 隧道，便于理解和二次开发，但没有 WireGuard/OpenVPN 那样完整的安全审计、密钥轮换、漫游、拥塞控制和大规模多客户端能力。请只在你有权限的网络中使用，并遵守当地法律法规和网络管理要求。
