# Linux 安装并登录 IBKR Gateway 全流程（Paper / Live 通用）

本文记录在 Linux 服务器上安装、登录并跑通 Interactive Brokers IB Gateway 的完整流程，包含 noVNC 图形环境、IBC 自动登录、SSH 隧道、API 端口和常见踩坑。

这套流程 **Paper 和 Live 是一样的**：都需要 Linux 图形环境、IB Gateway、IBC、2FA、API 设置。区别只在于登录模式、账号密码和 API 端口：

| 模式 | Gateway 登录模式 | IBC `TradingMode` | 默认 API 端口 | 账号 |
| --- | --- | --- | --- | --- |
| Paper | `Paper Trading` | `paper` | `4002` | Paper Trading user / paper password |
| Live | `Live Trading` | `live` | `4001` | 主账户 live user / live password |

Live 会连接真实账户并可能产生真实交易，正式跑策略前务必确认订单逻辑、风控、账户权限和 API 端口。

## 目标架构

```text
本地浏览器
  -> SSH 隧道 6080
  -> 服务器 noVNC
  -> Xvfb 虚拟桌面
  -> IB Gateway 图形登录窗口
  -> IBC 自动填用户名密码
  -> IB Gateway API
       Paper: 4002
       Live:  4001
```

IB Gateway 虽然叫 Gateway，但它不是纯命令行服务。登录、协议确认、2FA、API 设置这些步骤都依赖图形界面，所以 Linux 服务器上需要准备一个虚拟桌面。

## 1. SSH 登录服务器

私钥登录必须使用 `-i` 参数：

```bash
chmod 600 aif2.pem
ssh -i aif2.pem root@服务器IP
```

如果要同时转发 noVNC 和 IB Gateway API 端口，Paper 示例：

```bash
ssh -L 6080:127.0.0.1:6080 -L 4002:127.0.0.1:4002 -i aif2.pem root@服务器IP
```

Live 示例：

```bash
ssh -L 6080:127.0.0.1:6080 -L 4001:127.0.0.1:4001 -i aif2.pem root@服务器IP
```

本地浏览器访问：

```text
http://127.0.0.1:6080/vnc.html
```

### SSH 踩坑

- `-i` 是 identity file，也就是私钥文件。
- `-l` 是 login user，不是私钥文件。
- 私钥权限如果是 `0644`，SSH 会提示 `UNPROTECTED PRIVATE KEY FILE` 并忽略私钥。
- 如果 `ssh -vvv` 显示私钥已经发送，但服务器继续要求密码，说明服务端不认这把 key，常见原因是 key 不匹配、登录用户不对、服务器重装后丢了 `authorized_keys`。

排查 key 是否被服务端接受：

```bash
ssh -vvv -i aif2.pem root@服务器IP
```

日志里如果看到：

```text
Trying private key: aif2.pem
we sent a publickey packet, wait for reply
Authentications that can continue: publickey,password
Next authentication method: password
```

说明本地私钥能读取，但服务器不接受。

可以尝试其他常见用户：

```bash
ssh -i aif2.pem fwd@服务器IP
ssh -i aif2.pem ubuntu@服务器IP
ssh -i aif2.pem debian@服务器IP
```

## 2. 安装 Linux 图形环境

IB Gateway 在无图形界面的服务器上直接启动会报：

```text
java.awt.HeadlessException:
No X11 DISPLAY variable was set
```

安装虚拟桌面和 noVNC：

```bash
apt update
apt install -y xvfb x11vnc fluxbox novnc websockify
```

启动虚拟桌面：

```bash
Xvfb :1 -screen 0 1280x900x24 &
export DISPLAY=:1
fluxbox &
x11vnc -display :1 -forever -shared -nopw -listen 127.0.0.1 -rfbport 5901 &
websockify --web=/usr/share/novnc/ 6080 127.0.0.1:5901 &
```

本地建立 SSH 隧道：

```bash
ssh -L 6080:127.0.0.1:6080 -i aif2.pem root@服务器IP
```

浏览器打开：

```text
http://127.0.0.1:6080/vnc.html
```

### noVNC 踩坑

- `5901` 是 VNC 协议端口，浏览器不能直接打开。
- `6080` 是 noVNC 的 HTTP 端口，浏览器打开这个。
- 如果浏览器提示 `ERR_CONNECTION_REFUSED`，说明本地 SSH 隧道没开，或者服务器上的 `websockify` 没跑。

检查进程：

```bash
ps aux | grep -E 'Xvfb|x11vnc|websockify|fluxbox' | grep -v grep
```

## 3. 安装并启动 IB Gateway

安装 IB Gateway 后，常见路径类似：

```text
/home/fwd/Jts/ibgateway/
```

查看版本目录：

```bash
ls /home/fwd/Jts/ibgateway/
```

例如看到：

```text
1045
```

手动启动：

```bash
su - fwd
export DISPLAY=:1
/home/fwd/Jts/ibgateway/1045/ibgateway
```

如果不知道版本号，也可以：

```bash
export DISPLAY=:1
/home/fwd/Jts/ibgateway/*/ibgateway
```

### IB Gateway 踩坑

- `/home/fwd/Jts/ibgateway/` 是目录，不能直接执行。
- 需要执行版本目录里的 `ibgateway` 文件。
- 版本号需要记住，后面 IBC 配置要匹配，比如 `1045`。

## 4. 选择 Paper 或 Live 登录

Gateway 界面里的基础选择：

```text
API Type = IB API
Trading Mode = Paper Trading 或 Live Trading
```

Paper 和 Live 的安装、显示、IBC 启动流程相同，只是登录模式和账号不同。

### Paper 登录

IBKR Paper Trading 用户不一定默认开好。如果 Paper 登录时看到：

```text
You have selected the Paper Trading Mode, but the specified user does not have a Paper Trading user associated with it.
To create a Paper Trading user, please go to the Account Management.
```

说明当前用户名没有关联 Paper Trading 用户。

进入 IBKR Client Portal：

```text
Settings -> Account Configuration -> Paper Trading Account
```

在这里创建 Paper Trading Account / Paper Trading User，或者重置 paper 密码。

Paper 登录时：

```text
API Type = IB API
Trading Mode = Paper Trading
Username = paper username
Password = paper password
```

### Paper 账户踩坑

- `edemo` 是 IBKR 演示账号，不是你的 Paper 用户。
- 主账户用户名不一定能直接登录 Paper。
- Paper 密码可能和主账户密码不同。
- 刚创建 Paper Trading User 后可能需要等一会儿才生效，官方一般说正常业务情况下 24 小时内完成。

### Live 登录

Live 登录使用主账户的 live 用户名和密码：

```text
API Type = IB API
Trading Mode = Live Trading
Username = live username
Password = live password
```

Live 不需要创建 Paper Trading User，但可能会遇到实盘权限、协议确认、市场数据权限、交易许可、风险披露等弹窗。第一次跑 Live 建议打开 noVNC 盯一下，确认没有弹窗卡住。

### Live 踩坑

- Live 默认 API 端口通常是 `4001`，不要误连到 Paper 的 `4002`。
- Live 账户会产生真实交易，策略测试不要误用 `TradingMode=live`。
- Live 首次登录可能要确认协议、风险提示或账户通知。
- 如果你在同一台机器上同时跑 Paper 和 Live，要确保端口、配置文件、日志目录和 `clientId` 不冲突。

## 5. 安装并配置 IBC

IBC 用来自动启动 Gateway、填写用户名密码、点击登录。它不能绕过 IBKR Mobile 2FA。

配置文件常见路径：

```text
/home/fwd/ibc/config.ini
```

也可能是你自己指定的，例如：

```text
/home/fwd/ibkr/config/ibc-paper.ini
/home/fwd/ibkr/config/ibc-live.ini
```

Paper 至少需要配置：

```ini
IbLoginId=你的paper用户名
IbPassword=你的paper密码
TradingMode=paper
```

Live 至少需要配置：

```ini
IbLoginId=你的live用户名
IbPassword=你的live密码
TradingMode=live
```

保护配置文件：

```bash
chmod 600 /home/fwd/ibc/config.ini
```

如果使用 `/opt/ibc/gatewaystart.sh`，确认版本号匹配：

```bash
nano /opt/ibc/gatewaystart.sh
```

确保：

```bash
TWS_MAJOR_VRSN=1045
```

给脚本执行权限：

```bash
chmod +x /opt/ibc/*.sh /opt/ibc/scripts/*.sh
```

启动 IBC：

```bash
su - fwd
export DISPLAY=:1
/opt/ibc/gatewaystart.sh
```

或者明确使用 bash：

```bash
export DISPLAY=:1
bash /opt/ibc/gatewaystart.sh
```

不要使用：

```bash
sh /opt/ibc/gatewaystart.sh
```

### IBC 踩坑

- `gatewaystart.sh` 是 bash 脚本，用 `sh` 跑会报 `[[: not found`。
- `/opt/ibc/scripts/*.sh` 没执行权限会报 `no execute permission for scripts in /opt/ibc/scripts`。
- 如果进程参数里出现 `--user= --pw=`，说明 IBC 没读到用户名密码。
- 如果 IBC 显示 `Running GATEWAY 1019`，但实际安装版本是 `1045`，需要把 `TWS_MAJOR_VRSN` 改成实际版本。
- Paper 和 Live 可以复用同一个 Gateway 安装，但建议使用不同的 IBC 配置文件，避免把 `TradingMode` 或密码写混。

## 6. 处理 2FA

即使 IBC 自动填用户名密码，IBKR Mobile 的 2FA 仍然需要手动确认。

正常流程：

```text
IBC 自动启动 Gateway
-> 自动选择 Paper 或 Live
-> 自动填用户名密码
-> 自动点击登录
-> 手机收到 IBKR Mobile 推送
-> 手动 approve
-> 登录成功
```

IBC 不能绕过 2FA。首次登录、协议确认、密码错误、Gateway 更新、异常弹窗等情况，仍然需要打开 noVNC 看界面。

## 7. 开启 API

登录 IB Gateway 后进入：

```text
Configure -> Settings -> API -> Settings
```

勾选：

```text
Enable ActiveX and Socket Clients
```

Gateway 默认 API 端口通常是：

```text
Paper: 4002
Live:  4001
```

如果程序在服务器上运行，Paper 连接：

```text
127.0.0.1:4002
```

Live 连接：

```text
127.0.0.1:4001
```

如果程序在本地 Mac 上运行，Paper 开 SSH 隧道：

```bash
ssh -L 4002:127.0.0.1:4002 -i aif2.pem root@服务器IP
```

Live 开 SSH 隧道：

```bash
ssh -L 4001:127.0.0.1:4001 -i aif2.pem root@服务器IP
```

然后本地程序连接对应端口：

```text
Paper: 127.0.0.1:4002
Live:  127.0.0.1:4001
```

## 8. 常用排查命令

查看 Gateway / IBC / Java 进程：

```bash
ps aux | grep -E 'ibgateway|ibc|IBC|java' | grep -v grep
```

查看 IBC 日志：

```bash
ls -lt /home/fwd/ibc/logs/ | head
tail -n 120 /home/fwd/ibc/logs/最新日志文件
```

清理重复进程：

```bash
pkill -f ibgateway
pkill -f ibcstart
pkill -f IBC.jar
pkill -f twslaunch
```

重新启动：

```bash
su - fwd
export DISPLAY=:1
/opt/ibc/gatewaystart.sh
```

检查 noVNC 相关进程：

```bash
ps aux | grep -E 'Xvfb|x11vnc|websockify|fluxbox' | grep -v grep
```

## 9. 一次完整启动流程

服务器上：

```bash
su - fwd
export DISPLAY=:1
/opt/ibc/gatewaystart.sh
```

本地如需观察界面：

```bash
ssh -L 6080:127.0.0.1:6080 -i aif2.pem root@服务器IP
```

浏览器：

```text
http://127.0.0.1:6080/vnc.html
```

本地如需连接 IB API，Paper：

```bash
ssh -L 4002:127.0.0.1:4002 -i aif2.pem root@服务器IP
```

Live：

```bash
ssh -L 4001:127.0.0.1:4001 -i aif2.pem root@服务器IP
```

程序连接 Paper：

```text
host = 127.0.0.1
port = 4002
clientId = 1
```

程序连接 Live：

```text
host = 127.0.0.1
port = 4001
clientId = 1
```

## 总结

第一次需要 noVNC，是为了给远程 Linux 提供一个可见的图形桌面，并处理首次登录、账户模式、协议确认和 API 设置。后续 IBC 配好以后，正常启动不需要浏览器手动登录，脚本会自动操作 Gateway。

但需要记住：

- 2FA 仍然需要手机确认。
- 弹异常窗口时仍然需要 noVNC 排查。
- Paper 和 Live 流程相同，但账号、`TradingMode` 和端口不同。
- Paper 账户、Paper 密码和主账户不是一回事；Live 使用主账户。
- IBC 的 Gateway 版本号必须和实际安装目录一致。
- 如果程序在本地跑，需要 SSH 隧道转发对应端口：Paper `4002`，Live `4001`。
