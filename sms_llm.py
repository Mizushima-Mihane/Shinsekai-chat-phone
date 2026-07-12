"""SMS-only LLM — direct API call, no ChatUI, no TTS."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger("chat_phone.sms_llm")


def send_sms_llm(character: str, character_setting: str, user_text: str,
                 sms_history: list[str] | None, callback) -> None:
    """Send an SMS via direct LLM call in background thread."""
    def _run():
        try:
            reply = _call_llm(character, character_setting, user_text, sms_history or [])
            callback(reply)
        except Exception as e:
            logger.warning("SMS LLM failed: %s", e)
            callback(f"[{character}正在忙，稍后回复]")

    t = threading.Thread(target=_run, daemon=True, name="sms-llm")
    t.start()


def _call_llm(character: str, setting: str, text: str, history: list[str],
              story_context: str = "", initiate: bool = False) -> str:
    """Make a minimal LLM API call for an SMS.

    ``story_context`` (optional) is a short digest of the recent main-story
    dialogue, so the SMS can stay coherent with what just happened in the plot.

    ``initiate=False`` (默认)：回复模式——把 ``text`` 当成对方发来的短信，让角色回复。
    ``initiate=True``：主动发起模式——角色【主动】给对方发短信，``text`` 是对这条短信的
    写作要求（而不是对方的来信）。用于开场未知短信/主动短信，避免生成出「你联系了我」这类
    把玩家当成主动方的反向措辞。
    """
    from config.config_manager import ConfigManager

    cm = ConfigManager()
    cfg = cm.config.api_config
    provider = cfg.llm_provider or "ChatGPT"
    api_key = (cfg.llm_api_key or {}).get(provider, "")
    base_url = cfg.llm_base_url or ""
    model = (cfg.llm_model or {}).get(provider, "") if isinstance(cfg.llm_model, dict) else ""

    if not api_key:
        return f"请先在设置中配置{provider}的API Key"

    kwargs = cm.merged_llm_factory_kwargs(provider, {
        "llm_provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    })

    from llm.llm_manager import LLMAdapterFactory
    adapter = LLMAdapterFactory.create_adapter(**kwargs)

    hist_text = ""
    if history:
        hist_text = "之前的短信记录：\n" + "\n".join(history[-10:]) + "\n\n"

    story_text = ""
    if story_context:
        story_text = (
            f"当前剧情最近发生的事（你和对方刚刚的当面互动）：\n{story_context}\n\n"
            f"发短信时请自然地承接剧情——可以呼应刚才发生的事、当时的气氛或情绪。\n\n"
        )

    if initiate:
        system_prompt = (
            f"你正在扮演{character}。以下是{character}的设定：\n{setting}\n\n"
            f"{story_text}"
            f"{hist_text}"
            f"你现在要【主动】给对方发一条手机短信——是你主动发起联系，不是对方来找你。"
            f"请以{character}的身份，按下面的写作要求写这条短信，一两句话即可。"
            f"注意视角：短信是【你发给对方】的，不要写成好像对方先联系了你。"
            f"直接输出短信正文，不要加任何前缀后缀或格式。"
        )
        user_prompt = f"这条主动短信的写作要求：{text}"
    else:
        system_prompt = (
            f"你正在扮演{character}。以下是{character}的设定：\n{setting}\n\n"
            f"{story_text}"
            f"{hist_text}"
            f"有人通过短信给{character}发了消息。"
            f"请以{character}的身份结合上下文简短回复，一两句话即可。"
            f"直接输出回复文字，不要加任何前缀后缀或格式。"
        )
        user_prompt = f"短信内容：{text}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = adapter.chat(messages, stream=False, response_format={'type': 'text'})
        # Extract text from ChatCompletion object
        try:
            reply = result.choices[0].message.content or ""
        except Exception:
            reply = str(result or "")
        # Clean common formatting artifacts
        reply = reply.replace(f"{character}：", "").replace(f"{character}:", "").strip()
        reply = reply.replace("短信内容：", "").replace("回复：", "").strip()
        reply = reply.strip("「」『』\"\"''（）()【】[]")
        return reply or f"[{character}已读]"
    except Exception as e:
        logger.warning("SMS LLM error: %s", e)
        return f"[发送失败: {e}]"
