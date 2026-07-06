"""Browser app — private web search."""

from __future__ import annotations

import json, re, urllib.parse, urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)
from plugins.shinsekai_chat_phone.styles import (
    get_surface, ON_SURFACE, ON_SURFACE_VARIANT, OUTLINE_VARIANT,
)


class BrowserApp(QWidget):
    on_back = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._history: list[str] = []; self._load_history()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)

        tb = QWidget(); tb.setFixedHeight(48); tb.setStyleSheet("background: transparent;")
        tl = QHBoxLayout(tb); tl.setContentsMargins(4,0,12,0)
        b = QPushButton("←"); b.clicked.connect(self.on_back.emit)
        b.setStyleSheet("QPushButton { background: transparent; color: #FFB3BA; border: none; font-size: 18px; padding: 6px 10px; font-weight: 600; }")
        t = QLabel("浏览器"); t.setStyleSheet(f"color: {ON_SURFACE}; font-size: 17px; font-weight: 500;")
        tl.addWidget(b); tl.addWidget(t, 1); layout.addWidget(tb)

        sbar = QWidget(); sbar.setStyleSheet(f"background: {get_surface()}; padding: 8px;")
        sl = QHBoxLayout(sbar); sl.setContentsMargins(12,4,12,4); sl.setSpacing(8)
        self._inp = QLineEdit(); self._inp.setPlaceholderText("搜索网页...")
        self._inp.setStyleSheet(f"QLineEdit {{ background: {OUTLINE_VARIANT}; color: {ON_SURFACE}; border: none; border-radius: 20px; padding: 10px 16px; font-size: 13px; }} QLineEdit:focus {{ border: 1px solid #FFB3BA; }}")
        self._inp.returnPressed.connect(self._search)
        go = QPushButton("搜索")
        go.setStyleSheet("QPushButton { background: #FFB3BA; color: white; border-radius: 16px; padding: 8px 16px; font-size: 12px; font-weight: 600; border: none; }")
        go.clicked.connect(self._search)
        sl.addWidget(self._inp,1); sl.addWidget(go); layout.addWidget(sbar)

        self._content = QTextEdit(); self._content.setReadOnly(True)
        self._content.setStyleSheet("QTextEdit { background: white; color: #3C2A2A; border: none; font-size: 13px; padding: 12px; }")
        self._content.setHtml("<p style='color:#8A7A7A; text-align:center; padding-top:40px;'>输入关键词搜索网页</p>")
        layout.addWidget(self._content, 1)

        self._history_bar = QWidget()
        self._history_bar.setStyleSheet(f"background: {get_surface()}; border-top: 1px solid {OUTLINE_VARIANT};")
        self._history_bar.setMaximumHeight(36)
        self._history_layout = QHBoxLayout(self._history_bar)
        self._history_layout.setContentsMargins(8,4,8,4); self._history_layout.setSpacing(4)
        hl = QLabel("历史:"); hl.setStyleSheet(f"color: {ON_SURFACE_VARIANT}; font-size: 10px; font-weight: 500; background: transparent;")
        self._history_layout.addWidget(hl); self._history_layout.addStretch()
        self._update_history_ui()
        layout.addWidget(self._history_bar)

    def _search(self):
        q = self._inp.text().strip()
        if not q: return
        if q not in self._history: self._history.insert(0, q)
        if len(self._history) > 20: self._history.pop()
        self._save_history(); self._update_history_ui()
        self._content.setHtml(f"<p style='color:#8A7A7A; text-align:center; padding-top:40px;'>搜索中: {q}...</p>")
        # Use LLM for search (separate API call, not ChatUI)
        self._thread = _LLMSearchThread(q)
        self._thread.finished.connect(self._on_result)
        self._thread.start()

    def _on_result(self, html: str): self._content.setHtml(html)

    def _load_history(self):
        try:
            p = Path("data/plugins/com.shinsekai.chat_phone/browser_history.json")
            if p.is_file(): self._history = json.loads(p.read_text(encoding="utf-8"))
        except Exception: self._history = []

    def _save_history(self):
        try:
            p = Path("data/plugins/com.shinsekai.chat_phone/browser_history.json")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self._history, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception: pass

    def _update_history_ui(self):
        for i in reversed(range(self._history_layout.count())):
            w = self._history_layout.itemAt(i).widget()
            if w and getattr(w, 'is_history_btn', False): w.deleteLater()
        for q in self._history[:5]:
            btn = QPushButton(q); btn.is_history_btn = True
            btn.setStyleSheet("QPushButton { background: #F0E8E8; color: #3C2A2A; border-radius: 10px; padding: 2px 8px; font-size: 10px; border: none; max-height: 22px; } QPushButton:hover { background: #E0D5D5; }")
            btn.clicked.connect(lambda checked, query=q: (self._inp.setText(query), self._search()))
            self._history_layout.addWidget(btn)

    def _search_history(self, query: str): self._inp.setText(query); self._search()

    def closeEvent(self, e):
        if self._thread and self._thread.isRunning(): self._thread.quit(); self._thread.wait()
        super().closeEvent(e)


class _LLMSearchThread(QThread):
    finished = Signal(str)
    def __init__(self, query: str): super().__init__(); self._query = query
    def run(self):
        try:
            result = _llm_search(self._query)
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit(f"<p style='color:#FF8A80;'>搜索失败: {e}</p>")


def _llm_search(query: str) -> str:
    """Use LLM API to search — bypasses ChatUI entirely."""
    from config.config_manager import ConfigManager
    cm = ConfigManager()
    cfg = cm.config.api_config
    provider = cfg.llm_provider or "ChatGPT"
    api_key = (cfg.llm_api_key or {}).get(provider, "")
    base_url = cfg.llm_base_url or ""
    model = (cfg.llm_model or {}).get(provider, "") if isinstance(cfg.llm_model, dict) else ""
    if not api_key:
        return "<p style='color:#FF8A80;'>请先在设置中配置API Key</p>"
    kwargs = cm.merged_llm_factory_kwargs(provider, {
        "llm_provider": provider, "api_key": api_key, "base_url": base_url, "model": model,
    })
    from llm.llm_manager import LLMAdapterFactory
    adapter = LLMAdapterFactory.create_adapter(**kwargs)
    prompt = f"请搜索并回答以下问题，给出准确详细的答案。问题：{query}"
    messages = [{"role": "user", "content": prompt}]
    try:
        result = adapter.chat(messages, stream=False, response_format={'type': 'text'})
        try:
            text = (result.choices[0].message.content or "").strip()
        except Exception:
            text = str(result or "").strip()
        # Format for display
        formatted = text.replace("\n", "<br>").replace("**", "<b>").replace("**", "</b>")
        return f"<h3 style='color:#3C2A2A;'>{query}</h3><p style='font-size:14px; line-height:1.6;'>{formatted}</p>"
    except Exception as e:
        return f"<p style='color:#FF8A80;'>搜索失败: {e}</p>"


def _fetch(query: str) -> str:
    parts = [f"<h3 style='color:#3C2A2A;'>{query}</h3>"]
    # Try Bing first (better in CN)
    try:
        bing_url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(bing_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            results = re.findall(r'<li class="b_algo"[^>]*>.*?<h2[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>([^<]+)</a>.*?<p[^>]*>([^<]+)</p>', html, re.DOTALL)
            if results:
                parts.append("<ul>")
                for href, title, snippet in results[:8]:
                    parts.append(f"<li style='margin:8px 0;'><a href='{href}' style='color:#FFB3BA;'>{title.strip()}</a><br><span style='color:#555;'>{snippet.strip()}</span></li>")
                parts.append("</ul>")
                return "".join(parts)
    except Exception: pass
    try:
        url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            results = re.findall(r'<a[^>]*class="result-link"[^>]*>([^<]+)</a>.*?<td[^>]*class="result-snippet"[^>]*>([^<]+)</td>', html, re.DOTALL)
            if results:
                parts.append("<ul>")
                for title, snippet in results[:6]:
                    parts.append(f"<li style='margin:8px 0;'><b>{title.strip()}</b><br><span style='color:#555;'>{snippet.strip()}</span></li>")
                parts.append("</ul>")
                return "".join(parts)
    except Exception: pass
    try:
        wiki_url = "https://zh.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action":"query","list":"search","srsearch":query,"format":"json","srlimit":"5"})
        req2 = urllib.request.Request(wiki_url, headers={"User-Agent": "Shinsekai/1.0"})
        with urllib.request.urlopen(req2, timeout=8) as r2:
            data = json.loads(r2.read().decode("utf-8"))
            wr = data.get("query",{}).get("search",[])
            if wr:
                parts.append("<ul>")
                for w in wr[:5]:
                    parts.append(f"<li style='margin:8px 0;'><b>{w['title']}</b><br><span style='color:#555;'>{w.get('snippet','')}</span></li>")
                parts.append("</ul>")
                return "".join(parts)
    except Exception: pass
    parts.append("<p style='color:#8A7A7A; padding-top:20px;'>未找到结果，换个关键词试试。</p>")
    return "".join(parts)
