# Ubuntu 20.04 使用 Clash 订阅和 mihomo

这份文档是当前推荐的安装和使用流程。适用于你手里有 Clash 订阅链接，需要在 Ubuntu 20.04 上使用较新协议节点并能手动切换节点的场景。

mihomo 是 Clash.Meta 的后续内核，常见的 VLESS/Reality、Hysteria2、TUIC、Trojan、Shadowsocks、WireGuard 等协议由 mihomo 负责支持。`u20vpn clash ...` 只负责生成配置、安装服务和提供一个简单本地节点界面。

## 目录

- `7890`：本机 HTTP/SOCKS mixed 代理端口
- `9090`：mihomo external-controller API
- `7895`：u20vpn 本地节点界面
- `/etc/mihomo/config.yaml`：mihomo 配置
- `/etc/mihomo/subscription.url`：你的 Clash 订阅链接，必须保密

## 1. 准备项目环境

进入项目目录：

```bash
cd ~/Ubuntu20.04VPN开发
```

安装 Python 和虚拟环境：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip iproute2 iptables curl ca-certificates

python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .
```

确认 `u20vpn` 命令可用：

```bash
ls -l .venv/bin/u20vpn
"$(pwd)/.venv/bin/u20vpn" --help
```

如果 `sudo .venv/bin/u20vpn` 提示 `command not found`，使用绝对路径：

```bash
sudo "$(pwd)/.venv/bin/u20vpn" --help
```

## 2. 安装 mihomo 内核

```bash
sudo bash scripts/install-mihomo-ubuntu20.sh
```

脚本会从 MetaCubeX/mihomo 的 GitHub 最新 release 自动选择当前 CPU 架构的 Linux `.gz` 二进制，并安装到：

```text
/usr/local/bin/mihomo
```

确认：

```bash
ls -l /usr/local/bin/mihomo
/usr/local/bin/mihomo -v
```

## 3. 保存 Clash 订阅链接

不要把订阅链接提交到 Git，也不要贴到公开终端记录里。建议保存成 root 可读文件：

```bash
sudo mkdir -p /etc/mihomo
sudo sh -c 'printf "%s\n" "你的Clash订阅链接" > /etc/mihomo/subscription.url'
sudo chmod 600 /etc/mihomo/subscription.url
```

支持这两类输入：

```text
https://example.com/sub?token=...
clash://install-config?url=...
```

不支持直接把单个节点链接当订阅导入，例如 `vless://`、`ss://`、`trojan://`。这种情况需要先转换成 Clash YAML 订阅或配置。

## 4. 生成 mihomo 配置和 systemd 服务

```bash
sudo "$(pwd)/.venv/bin/u20vpn" clash init \
  --subscription-file /etc/mihomo/subscription.url \
  --config /etc/mihomo/config.yaml \
  --service /etc/systemd/system/mihomo.service
```

生成内容：

- `/etc/mihomo/config.yaml`
- `/etc/systemd/system/mihomo.service`
- `/etc/mihomo/providers/`

默认行为：

- 开启 TUN 模式
- 本机 mixed 代理监听 `127.0.0.1:7890`
- 控制 API 监听 `127.0.0.1:9090`
- 不默认使用 `GEOIP` 规则，避免首次启动卡在 MMDB 下载
- 局域网地址直连，其余流量走 `PROXY`

## 5. 启动和设置开机自启

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo
```

确认状态：

```bash
systemctl is-enabled mihomo
systemctl is-active mihomo
sudo systemctl status mihomo --no-pager
```

正常应看到：

```text
enabled
active
```

确认端口监听：

```bash
sudo ss -ltnp | grep -E '7890|9090|mihomo' || true
```

测试代理：

```bash
curl -x http://127.0.0.1:7890 https://www.gstatic.com/generate_204 -I
```

正常会看到类似：

```text
HTTP/1.1 200 Connection established
HTTP/2 204
```

## 6. 打开节点切换界面

临时运行：

```bash
cd ~/Ubuntu20.04VPN开发
sudo "$(pwd)/.venv/bin/u20vpn" clash ui --config /etc/mihomo/config.yaml
```

浏览器打开：

```text
http://127.0.0.1:7895/
```

界面功能：

- 查看代理组
- 查看当前节点
- 点击 `选用` 切换节点
- 点击 `测速` 测试当前代理组里的节点延迟

如果通过 SSH 连接远程 Ubuntu，没有桌面浏览器，可以做端口转发：

```bash
ssh -L 7895:127.0.0.1:7895 xkme@你的Ubuntu机器IP
```

然后在本机浏览器打开：

```text
http://127.0.0.1:7895/
```

## 7. 节点界面开机自启

复制服务文件：

```bash
cd ~/Ubuntu20.04VPN开发
sudo cp examples/u20vpn-mihomo-ui.service /etc/systemd/system/u20vpn-mihomo-ui.service
```

如果项目不在 `/opt/u20vpn`，把 service 里的路径替换成当前项目路径：

```bash
sudo sed -i "s#/opt/u20vpn#$(pwd)#g" /etc/systemd/system/u20vpn-mihomo-ui.service
```

启动并设置自启：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now u20vpn-mihomo-ui
```

确认：

```bash
systemctl is-enabled u20vpn-mihomo-ui
systemctl is-active u20vpn-mihomo-ui
sudo systemctl status u20vpn-mihomo-ui --no-pager
```

## 8. 常用命令

重启 mihomo：

```bash
sudo systemctl restart mihomo
```

查看 mihomo 日志：

```bash
journalctl -u mihomo -n 120 --no-pager -l
```

实时查看 mihomo 日志：

```bash
journalctl -u mihomo -f
```

重启节点界面：

```bash
sudo systemctl restart u20vpn-mihomo-ui
```

只生成配置到标准输出：

```bash
"$(pwd)/.venv/bin/u20vpn" clash render-config --subscription-file /etc/mihomo/subscription.url
```

不开 TUN，只作为本机 HTTP/SOCKS 代理：

```bash
sudo "$(pwd)/.venv/bin/u20vpn" clash init \
  --subscription-file /etc/mihomo/subscription.url \
  --no-tun
```

允许局域网设备使用你的代理：

```bash
sudo "$(pwd)/.venv/bin/u20vpn" clash init \
  --subscription-file /etc/mihomo/subscription.url \
  --allow-lan
```

`--allow-lan` 会让 mixed 代理监听所有网卡，只有在你信任当前局域网时才建议打开。

## 9. 排错

### 所有节点测速失败、代理秒断（anytls 订阅）

如果你的订阅节点全部是 `anytls` 协议，而 mihomo 测速全部失败、代理连接 0.5 秒
左右就断开，即使换成最新稳定版 mihomo 也一样，说明当前 mihomo 版本与你的节点
服务端存在 anytls 兼容性问题。此时可回退到手动订阅 + sing-box 内核方案，
代理端口（7890）、控制器（9090）和节点界面（7895）保持不变，见
[manual-subscription-singbox.md](manual-subscription-singbox.md)。

> 排查要点：直接抓包看 `tcp port <节点端口>`，若 TLS 握手成功、客户端发出
> anytls 应用数据后服务器直接 FIN 关闭连接，即为协议不兼容；用 sing-box
> 相同参数可正常连通即可确认。

### `sudo: .venv/bin/u20vpn: command not found`

原因通常是当前目录不对、虚拟环境没安装项目，或者 `sudo` 解析相对路径失败。

处理：

```bash
cd ~/Ubuntu20.04VPN开发
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
sudo "$(pwd)/.venv/bin/u20vpn" --help
```

### `curl: (7) Failed to connect to 127.0.0.1 port 7890`

说明 `7890` 没监听。先看服务和端口：

```bash
sudo systemctl status mihomo --no-pager
sudo ss -ltnp | grep -E '7890|9090|mihomo' || true
journalctl -u mihomo -n 120 --no-pager -l
```

如果日志卡在 `Can't find MMDB, start download`，说明配置里还有 `GEOIP` 规则导致启动时下载数据库。重新生成当前版本配置，或临时把规则改成：

```yaml
rules:
  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve
  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve
  - IP-CIDR,169.254.0.0/16,DIRECT,no-resolve
  - MATCH,PROXY
```

然后：

```bash
sudo systemctl restart mihomo
```

### UI 终端出现 `BrokenPipeError`

这是浏览器刷新页面或取消测速请求时产生的日志噪音，不影响代理连接。当前版本已经静默忽略这类客户端断开。更新代码后重启 UI：

```bash
sudo systemctl restart u20vpn-mihomo-ui
```

如果是临时运行，按 `Ctrl+C` 停止后重新执行：

```bash
sudo "$(pwd)/.venv/bin/u20vpn" clash ui --config /etc/mihomo/config.yaml
```

### 不知道当前是否已经自启

```bash
systemctl is-enabled mihomo
systemctl is-active mihomo
```

输出 `enabled` 和 `active` 就表示当前运行且开机自启。

## 10. 安全注意

- `/etc/mihomo/subscription.url` 和 `/etc/mihomo/config.yaml` 包含订阅信息，不要公开。
- 默认 UI 只监听 `127.0.0.1:7895`，不要改成 `0.0.0.0` 暴露到公网。
- `--allow-lan` 会把代理端口开放给局域网，只有信任局域网时使用。
- 请只在你有权限的网络中使用，并遵守当地法律法规和网络管理要求。
