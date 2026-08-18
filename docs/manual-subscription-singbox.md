# 手动订阅 + sing-box 方案

## 背景

当前订阅（`https://api.efanyunapi.com/clash/500336/O4LPUKMPLd`）的 99 个节点
全部为 **anytls** 协议。实测 mihomo（alpha-3315457 与 v1.19.29 稳定版）均无法
与这些节点完成 anytls 握手（TLS 成功后服务器直接断开），而 sing-box 1.13.18
使用相同节点参数可正常工作。因此代理内核改用 sing-box，保留 7890 代理端口、
9090 Clash 兼容 API 和 7895 节点界面。

## 使用步骤

### 1. 手动下载订阅

```bash
sudo mkdir -p /etc/singbox
curl -fsSL "https://api.efanyunapi.com/clash/500336/O4LPUKMPLd" \
  -o /tmp/subscription-clash.yaml
sudo mv /tmp/subscription-clash.yaml /etc/singbox/subscription-clash.yaml
sudo chmod 600 /etc/singbox/subscription-clash.yaml
```

订阅更新时重复这一步即可（节点变化后重新生成配置并重启服务）。
也可以跳过手动下载，直接用 `--subscription-url` 让转换脚本自行下载（见下）。

### 2. 生成 sing-box 配置

```bash
cd ~/Documents/Ubuntu20.04VPN开发
SECRET=$(sudo grep -E '^secret' /etc/mihomo/config.yaml | awk '{print $2}' | tr -d '"')

# 方式 A：从本地订阅文件生成
sudo .venv/bin/python scripts/manual-subscription-to-singbox.py \
  --subscription /etc/singbox/subscription-clash.yaml \
  --output /etc/singbox/config.json \
  --secret "$SECRET"

# 方式 B：直接从订阅 URL 下载并生成
sudo .venv/bin/python scripts/manual-subscription-to-singbox.py \
  --subscription-url "https://api.efanyunapi.com/clash/500336/O4LPUKMPLd" \
  --output /etc/singbox/config.json \
  --secret "$SECRET"

sudo /usr/local/bin/sing-box check -c /etc/singbox/config.json
```

> 控制器密钥沿用 `/etc/mihomo/config.yaml` 里的 secret，
> 这样 `u20vpn clash ui` 无需任何改动。

### 3. 启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl start sing-box
sudo systemctl start u20vpn-mihomo-ui
```

> 注意：不要同时启动 `mihomo` 和 `sing-box`，两者都监听 7890/9090 会冲突。
> 当前 mihomo 已停用（`mihomo.alpha-3315457` 备份在
> `/usr/local/bin/mihomo.alpha-3315457`，当前 `/usr/local/bin/mihomo` 为 v1.19.29）。

### 4. 验证

```bash
curl -x http://127.0.0.1:7890 https://www.gstatic.com/generate_204 -I   # 期望 204
curl -x http://127.0.0.1:7890 https://www.google.com -I                  # 期望 200
```

浏览器打开 `http://127.0.0.1:7895/` 可查看代理组、切换节点、测速。

## 文件清单

| 路径 | 说明 |
|---|---|
| `/usr/local/bin/sing-box` | sing-box 1.13.18 内核 |
| `/etc/singbox/subscription-clash.yaml` | 手动下载的订阅文件 |
| `/etc/singbox/config.json` | 生成的 sing-box 配置 |
| `/etc/systemd/system/sing-box.service` | sing-box 服务（默认不自启） |
| `scripts/manual-subscription-to-singbox.py` | 订阅 -> sing-box 配置转换脚本 |
| `examples/u20vpn-singbox.service` | 服务模板 |
