# AI女友 / AI Girlfriend Companion Prototype

一个可离线运行的 2D 探索陪伴型游戏原型。当前版本使用纯 HTML/CSS/JavaScript 实现，可在 macOS 浏览器和 Android 手机浏览器中运行，也可以作为 PWA 添加到主屏幕。

## 运行

```bash
cd /home/fwd/work/ai-games-gf/games/ai-gf
python3 -m http.server 4173
```

打开：

```text
http://localhost:4173
```

## 测试

```bash
npm test
```

## 当前功能

- 按 Godot 风格拆成根场景、世界场景和 UI 场景
- 2D 探索地图和镜头跟随
- 键盘、摇杆、点击移动
- 林栖跟随和任务推进
- 纸飞机、长椅、喷泉、照片墙等任务节点
- 冲刺和拍照解锁
- 记忆、羁绊和任务记录
- `localStorage` 自动存档
- Service Worker 离线缓存
- 2D 游戏规格文档：`docs/2D_GAME_SPEC.md`
- 运行时烟测：模拟移动、互动、解锁和拍照

## 后续方向

- 扩展连续地图和更多区域
- 增加更多 NPC、路线和约会事件
- 加入更细的表情和动作反馈
- 用 Capacitor 打包 Android APK
- 用 Tauri 或 Electron 打包 macOS App
