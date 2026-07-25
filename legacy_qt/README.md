# legacy_qt — 旧 Qt 手机 UI（归档，休眠）

现役实现是 **React 手机**（`../frontend/dist/index.html` + `../webface.py` + `../phone_core.py`）。
本目录是移植前的 PySide6/Qt 实现，**保留但不再作为现役运行栈**。

## 何时会被加载
仅当宿主存在 Qt GUI 时（`plugin.py` 的 `_qt_ui_active()` 为真），`build_widget` 才会从这里拉起
`PhoneWidget`。Tauri / React 桌面模式（E:\work）下 `_qt_ui_active()` 恒为假，本目录一行不执行。

## 注意
- 这些文件彼此之间用绝对 import（`plugins.shinsekai_chat_phone.<module>`）互相引用，归档时**未逐个改内部路径**。
  因此即便 Qt 模式被拉起，`PhoneWidget` 的内部 import 也会失败，`build_widget` 会回退成 📱 占位图标——这是预期行为（旧栈已退役）。
- 仍留在上层的 `styles.py` / `settings_app.py` / `music_app.py` / `sms_llm.py` / `avatar_manager.py`
  被 React 侧复用，**不要移动**。
- 上层 `plugin.py` / `settings_app.py` 中指向本目录的 5 处 import 已更新为 `...legacy_qt.<module>`。

## 如何恢复原状
把本目录所有 `*.py` 移回上层 `shinsekai_chat_phone/`，再把那 5 处 import 里的 `.legacy_qt.` 去掉即可。

## 清单（21 个文件）
- 主容器 / 桌面：`phone_widget` `home_screen`
- 主动监控（已被 `../proactive_core.py` 取代）：`proactive_monitor`
- Qt app：`phone_app` `messages_app` `contacts_app` `group_chat_app` `moments_app` `browser_app` `voice_memo_app` `camera_app`
- Qt view：`chat_view` `call_view` `video_call_view` `contact_list_view`
- 数据存储（React 走 `../phone_core.py` 读写同一批 JSON，不用这些类）：`message_store` `contact_store` `group_store` `moments_store`
- 其它：`sound_fx` `freq_config_ui`
