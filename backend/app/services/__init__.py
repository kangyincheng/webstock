"""Services 层：把现有 *Page/*Analyzer 中纯业务/无 Tkinter 的逻辑统一包一层。

设计原则：
  - 所有方法只接受 JSON-serialisable 参数，返回 dict / list[dict] / 纯数据结构。
  - 不依赖 tkinter / GUI。
  - 长任务统一支持 progress_callback(callable) 用于 WebSocket 推送。
"""
