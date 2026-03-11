"""Rule-based text formatter for multi-purpose output modes."""

from __future__ import annotations

import re
from typing import Callable, Optional

from .config import DEFAULT_MODE


class FormatterError(ValueError):
    """Raised when formatter input or mode is invalid."""


class TextFormatter:
    """
    Rule-based formatter for MVP.

    Modes:
    - raw: minimal cleanup only
    - clean: conversational text -> readable sentence style
    - cursor: implementation-request friendly text
    - minutes: meeting-note friendly text
    """

    SUPPORTED_MODES = {"raw", "clean", "cursor", "minutes"}

    def __init__(self, default_mode: str = DEFAULT_MODE) -> None:
        if default_mode not in self.SUPPORTED_MODES:
            raise FormatterError(f"Unsupported default mode: {default_mode}")
        self.default_mode = default_mode
        self._mode_handlers: dict[str, Callable[[str], str]] = {
            "raw": self._format_raw,
            "clean": self._format_clean,
            "cursor": self._format_cursor,
            "minutes": self._format_minutes,
        }

    def format_text(
        self,
        text: str | None,
        mode: str | None = None,
        *,
        prompt: str | None = None,
        is_partial: bool = False,
    ) -> str:
        """
        Format text by mode.

        Args:
            text: Input text to format.
            mode: One of raw/clean/cursor/minutes. Falls back to default_mode.
            prompt: Optional user prompt that guides formatting (rule-based in MVP).
            is_partial: True when formatting partial/in-progress text (be conservative).

        Returns:
            Formatted text.
        """
        normalized = self._normalize_input(text)
        if not normalized:
            return ""

        prompt_value = self._normalize_input(prompt)
        selected_mode = (mode or self.default_mode).strip().lower()
        handler = self._mode_handlers.get(selected_mode)
        if handler is None:
            raise FormatterError(
                f"Unsupported mode: {selected_mode}. "
                f"Supported modes: {', '.join(sorted(self.SUPPORTED_MODES))}"
            )

        base = handler(normalized)
        if not prompt_value:
            return base

        # MVP: rule-based prompt application.
        # If prompt contains an explicit template placeholder, use it.
        if "{text}" in prompt_value:
            return prompt_value.replace("{text}", base).strip()

        # Otherwise, infer a light formatting preference from prompt keywords.
        inferred = self._infer_mode_from_prompt(prompt_value) or selected_mode
        if inferred != selected_mode:
            inferred_handler = self._mode_handlers.get(inferred)
            if inferred_handler is not None:
                base = inferred_handler(normalized)

        # For partial, avoid heavy re-structuring; keep it readable but stable.
        if is_partial:
            return self._format_partial_stable(base, prompt_value)
        return self._format_prompted(base, prompt_value)

    def _normalize_input(self, text: str | None) -> str:
        if text is None:
            return ""
        value = str(text).strip()
        # Normalize line endings and tabs first.
        value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
        return value

    def _infer_mode_from_prompt(self, prompt: str) -> Optional[str]:
        p = prompt.lower()
        # Japanese / English keyword heuristics (conservative).
        if any(k in prompt for k in ("議事録", "minutes", "決定事項", "ネクストアクション", "要点")):
            return "minutes"
        if any(k in prompt for k in ("箇条書き", "bullet", "リスト")):
            return "clean"  # keep natural text, bulletize separately
        if any(k in prompt for k in ("実装", "cursor", "コード", "修正", "タスク")):
            return "cursor"
        return None

    def _format_partial_stable(self, text: str, prompt: str) -> str:
        # Keep prompt influence minimal for partial updates to reduce flicker.
        if any(k in prompt for k in ("箇条書き", "bullet", "リスト")):
            lines = self._split_into_lines(text)
            if not lines:
                return text
            # Keep up to a few bullets for partial.
            bullets = self._to_requirement_bullets(lines)[:6]
            if bullets:
                return "\n".join(f"- {b}" for b in bullets).strip()
        return text.strip()

    def _format_prompted(self, text: str, prompt: str) -> str:
        # Default behavior: show prompt as a "format spec" header only if it looks like a template.
        # Otherwise just return the formatted text (prompt influences mode inference above).
        if any(k in prompt for k in ("箇条書き", "bullet", "リスト")):
            lines = self._split_into_lines(text)
            if not lines:
                return text.strip()
            bullets = []
            for line in lines:
                for s in self._split_sentences(line):
                    v = s.strip(" ・-").rstrip("。")
                    if v:
                        bullets.append(v)
            if bullets:
                return "\n".join(f"- {b}" for b in bullets).strip()
        if any(k in prompt for k in ("フォーマット", "形式", "出力", "テンプレ", "template")):
            return f"指示:\n{prompt.strip()}\n\n{text.strip()}".strip()
        return text.strip()

    def _format_raw(self, text: str) -> str:
        # Keep original content as much as possible, normalize only excess spaces.
        text = re.sub(r"[ ]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _format_clean(self, text: str) -> str:
        text = self._remove_fillers(text)
        text = self._normalize_japanese_phrases(text)
        text = self._compact_whitespace(text)
        text = self._normalize_punctuation_ja(text)
        text = self._split_long_text_by_punctuation(text, max_chars=90)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _format_cursor(self, text: str) -> str:
        clean = self._format_clean(text)
        if not clean:
            return ""

        lines = self._split_into_lines(clean)
        bullets = self._to_requirement_bullets(lines)

        # If classification does not find enough actionable points,
        # keep a compact request body instead of forcing noisy bullets.
        if not bullets:
            body = clean
        else:
            body = "\n".join(f"- {item}" for item in bullets)

        return (
            "実装依頼:\n"
            f"{body}\n\n"
            "完了条件:\n"
            "- 要件を満たす実装になっていること\n"
            "- 例外系を考慮していること\n"
            "- 変更点が説明可能であること"
        ).strip()

    def _format_minutes(self, text: str) -> str:
        clean = self._format_clean(text)
        if not clean:
            return ""

        sentences = self._split_sentences(clean)
        decisions: list[str] = []
        issues: list[str] = []
        actions: list[str] = []
        others: list[str] = []

        for sentence in sentences:
            s = sentence.strip(" ・-")
            if not s:
                continue
            if self._is_decision_sentence(s):
                decisions.append(s)
            elif self._is_issue_sentence(s):
                issues.append(s)
            elif self._is_action_sentence(s):
                actions.append(s)
            else:
                others.append(s)

        if others:
            # Keep unclassified notes as issues to preserve useful context.
            issues.extend(others)

        return (
            f"決定事項\n{self._render_section(decisions)}\n\n"
            f"課題\n{self._render_section(issues)}\n\n"
            f"ネクストアクション\n{self._render_section(actions)}"
        ).strip()

    def _remove_fillers(self, text: str) -> str:
        # Keep this conservative to avoid deleting meaningful words.
        filler_pattern = (
            r"(?:(?<=^)|(?<=[\s、。,.!?]))"
            r"(えーと|えっと|えー|あのー|あの|そのー|その|まあ|なんか|えっとですね)"
            r"(?=[\s、。,.!?]|$)"
        )
        text = re.sub(filler_pattern, " ", text)
        return text

    def _normalize_japanese_phrases(self, text: str) -> str:
        phrase_rules: list[tuple[str, str]] = [
            (r"この処理を非同期にしたい", "この処理を非同期化したい"),
            (r"非同期にしたい", "非同期化したい"),
            (r"できるだけ", "なるべく"),
        ]
        updated = text
        for src, dst in phrase_rules:
            updated = re.sub(src, dst, updated)
        return updated

    def _compact_whitespace(self, text: str) -> str:
        text = re.sub(r"[ ]{2,}", " ", text)
        text = re.sub(r"[ ]*\n[ ]*", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _normalize_punctuation_ja(self, text: str) -> str:
        text = text.replace("，", "、").replace("．", "。")
        text = text.replace(",", "、").replace(".", "。")
        text = re.sub(r"[!?]+", "。", text)
        # Remove duplicated punctuation marks.
        text = re.sub(r"[、]{2,}", "、", text)
        text = re.sub(r"[。]{2,}", "。", text)

        # Add sentence ending punctuation when text seems plain.
        stripped = text.strip()
        if stripped and stripped[-1] not in {"。", "！", "？", "!", "?"}:
            text = stripped + "。"
        return text

    def _split_long_text_by_punctuation(self, text: str, max_chars: int) -> str:
        sentences = self._split_sentences(text)
        if not sentences:
            return text

        wrapped_lines: list[str] = []
        current = ""
        for sentence in sentences:
            if not current:
                current = sentence
                continue
            if len(current) + len(sentence) <= max_chars:
                current += sentence
            else:
                wrapped_lines.append(current)
                current = sentence
        if current:
            wrapped_lines.append(current)
        return "\n".join(wrapped_lines)

    def _split_sentences(self, text: str) -> list[str]:
        fragments = re.split(r"(?<=[。!?！？])\s*", text)
        return [f.strip() for f in fragments if f and f.strip()]

    def _split_into_lines(self, text: str) -> list[str]:
        lines = [line.strip(" -・") for line in text.split("\n")]
        return [line for line in lines if line]

    def _to_requirement_bullets(self, lines: list[str]) -> list[str]:
        bullets: list[str] = []
        for line in lines:
            normalized = line
            normalized = re.sub(r"^(お願い|できれば|可能なら)", "", normalized).strip()
            normalized = re.sub(r"(したいです|したい|してほしいです|してほしい)$", "する", normalized)
            normalized = re.sub(r"(お願いします|お願いしたいです)$", "", normalized).strip()

            if not normalized:
                continue

            # Prefer short actionable bullet lines.
            if len(normalized) > 120:
                split_items = re.split(r"[、,]", normalized)
                for item in split_items:
                    item = item.strip()
                    if item:
                        bullets.append(self._ensure_imperative_style(item))
            else:
                bullets.append(self._ensure_imperative_style(normalized))
        return bullets

    def _ensure_imperative_style(self, text: str) -> str:
        value = text.strip().rstrip("。")
        replacements = {
            "したい": "する",
            "ほしい": "する",
            "ください": "する",
            "できるように": "可能にする",
        }
        for src, dst in replacements.items():
            value = value.replace(src, dst)
        return value

    def _is_decision_sentence(self, text: str) -> bool:
        keywords = ("決定", "採用", "方針", "確定", "合意", "決まり", "実施する")
        return any(k in text for k in keywords)

    def _is_issue_sentence(self, text: str) -> bool:
        keywords = ("課題", "懸念", "問題", "未対応", "不明", "難しい", "不足", "詰まって")
        return any(k in text for k in keywords)

    def _is_action_sentence(self, text: str) -> bool:
        keywords = ("対応", "実施", "やる", "確認", "調査", "作成", "連携", "共有", "次回")
        return any(k in text for k in keywords)

    def _render_section(self, items: list[str]) -> str:
        if not items:
            return "- なし"
        return "\n".join(f"- {item.rstrip('。')}。" for item in items)

