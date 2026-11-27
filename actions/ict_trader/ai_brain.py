"""
Dual AI Brain — Groq for speed, Gemini for depth.
Handles all AI-powered market analysis decisions.
"""

import json
import traceback
from pathlib import Path


class AIBrain:
    """Dual-AI market analysis brain using Groq (fast) + Gemini (deep)."""

    def __init__(self, gemini_key: str = "", groq_key: str = ""):
        self.gemini_key     = gemini_key
        self.groq_key       = groq_key
        self._groq_client   = None
        self._gemini_client = None

    # ── Groq Client ──────────────────────────────────────────────────────
    def _get_groq(self):
        if not self._groq_client and self.groq_key:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=self.groq_key)
                print("[ICT-BRAIN] Groq client ready")
            except Exception as e:
                print(f"[ICT-BRAIN] Groq init failed: {e}")
        return self._groq_client

    # ── Gemini Client ─────────────────────────────────────────────────────
    def _get_gemini(self):
        if not self._gemini_client and self.gemini_key:
            try:
                from google import genai as gai
                self._gemini_client = gai.Client(api_key=self.gemini_key)
                print("[ICT-BRAIN] Gemini client ready")
            except Exception as e:
                print(f"[ICT-BRAIN] Gemini init failed: {e}")
        return self._gemini_client

    # ── Fast Analysis via Groq ───────────────────────────────────────────
    def fast_analyze(self, prompt: str, max_tokens: int = 2000) -> str:
        """Fast analysis via Groq — used for quick structure reads."""
        client = self._get_groq()
        if not client:
            print("[ICT-BRAIN] Groq unavailable — falling back to Gemini")
            return self.deep_analyze(prompt, max_tokens)
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an elite ICT/SMC institutional trader AI. "
                            "Analyze price action using Smart Money Concepts: "
                            "Break of Structure (BOS), Change of Character (CHoCH), "
                            "Market Structure Shift (MSS), Order Blocks, "
                            "Fair Value Gaps (FVG), Supply/Demand zones, "
                            "Liquidity sweeps, Inducements, Premium/Discount arrays. "
                            "ALWAYS respond in valid JSON only. "
                            "Never include markdown code blocks. "
                            "Be extremely precise with price levels. "
                            "Never hallucinate data."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.1,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[ICT-BRAIN] Groq error: {e}")
            return self.deep_analyze(prompt, max_tokens)

    # ── Deep Analysis via Gemini ─────────────────────────────────────────
    def deep_analyze(self, prompt: str, max_tokens: int = 2000) -> str:
        """Deep analysis via Gemini — used for multi-TF confluence."""
        client = self._get_gemini()
        if not client:
            return '{"error": "No AI client available"}'
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "system_instruction": (
                        "You are an elite ICT/SMC institutional trader AI. "
                        "Analyze price action using Smart Money Concepts. "
                        "BOS, CHoCH, MSS, Order Blocks, FVG, Supply/Demand, "
                        "Liquidity sweeps, Inducements, Premium/Discount. "
                        "ALWAYS respond in valid JSON format only. "
                        "Never wrap in markdown. Be precise with price levels."
                    ),
                    "temperature": 0.1,
                    "max_output_tokens": max_tokens,
                },
            )
            return response.text.strip()
        except Exception as e:
            print(f"[ICT-BRAIN] Gemini error: {e}")
            return f'{{"error": "{str(e)}"}}'

    # ── Analyze Candle Data ──────────────────────────────────────────────
    def analyze_candles(
        self, candles: list, timeframe: str, symbol: str
    ) -> dict:
        """Analyze candle data for full ICT market structure."""
        if not candles or len(candles) < 20:
            return {
                "error": "Insufficient candle data",
                "bias": "neutral",
                "confidence": 0,
                "trend": "ranging",
                "current_price": 0,
                "supply_zones": [],
                "demand_zones": [],
                "fvg": [],
                "structure": {
                    "swing_highs": [],
                    "swing_lows": [],
                    "bos_events": [],
                    "choch_events": [],
                    "mss_events": [],
                },
                "liquidity": {"buy_side": [], "sell_side": []},
                "inducements": [],
                "premium_discount": {},
            }

        # Use last 150 candles to stay within token limits
        sample = candles[-150:]
        candle_text = self._format_candles(sample)
        current_price = self._get_close(candles[-1])

        prompt = f"""Analyze this {symbol} {timeframe} price data for ICT/SMC structure.
Current price: {current_price}

CANDLE DATA (index 0 = oldest, last = most recent):
{candle_text}

Return ONLY valid JSON — no markdown, no explanation:
{{
    "trend": "bullish",
    "trend_strength": 7,
    "bias": "bullish",
    "confidence": 72,
    "current_price": {current_price},
    "structure": {{
        "swing_highs": [
            {{"price": 0.0, "index": 0, "type": "HH", "significant": true}}
        ],
        "swing_lows": [
            {{"price": 0.0, "index": 0, "type": "HL", "significant": true}}
        ],
        "bos_events": [
            {{"type": "bullish", "level": 0.0, "index": 0, "confirmed": true}}
        ],
        "choch_events": [
            {{"type": "bullish", "level": 0.0, "index": 0}}
        ],
        "mss_events": [
            {{"type": "bullish", "level": 0.0, "index": 0, "displacement": true}}
        ]
    }},
    "supply_zones": [
        {{
            "high": 0.0, "low": 0.0, "origin_index": 0,
            "type": "fresh", "strength": 8, "is_order_block": true
        }}
    ],
    "demand_zones": [
        {{
            "high": 0.0, "low": 0.0, "origin_index": 0,
            "type": "fresh", "strength": 9, "is_order_block": true
        }}
    ],
    "fvg": [
        {{"high": 0.0, "low": 0.0, "index": 0, "type": "bullish", "filled": false}}
    ],
    "liquidity": {{
        "buy_side":  [{{"level": 0.0, "type": "EQH", "swept": false}}],
        "sell_side": [{{"level": 0.0, "type": "EQL", "swept": false}}]
    }},
    "inducements": [
        {{"level": 0.0, "type": "bullish", "taken": false, "index": 0}}
    ],
    "premium_discount": {{
        "equilibrium": 0.0,
        "premium_zone": 0.0,
        "discount_zone": 0.0,
        "current_position": "discount"
    }}
}}

Fill ALL price values with REAL numbers from the candle data above.
Identify the most recent and relevant structure only."""

        # Try Groq first (faster), fall back to Gemini
        raw = self.fast_analyze(prompt, max_tokens=2500)
        result = self._parse_json(raw)

        # If parse failed or low quality, try Gemini
        if result.get("error") or result.get("confidence", 0) < 10:
            print("[ICT-BRAIN] Groq result poor — trying Gemini...")
            raw = self.deep_analyze(prompt, max_tokens=2500)
            result = self._parse_json(raw)

        return result

    # ── Multi-TF Confluence ──────────────────────────────────────────────
    def multi_tf_confluence(
        self,
        htf_analysis: dict,
        ltf_analysis: dict,
        htf_tf: str,
        ltf_tf: str,
        symbol: str,
    ) -> dict:
        """Find multi-timeframe confluence for high-probability entries."""
        prompt = f"""You are analyzing {symbol} for an ICT multi-timeframe entry.

HTF ({htf_tf}) ANALYSIS SUMMARY:
- Trend: {htf_analysis.get('trend', 'unknown')}
- Bias: {htf_analysis.get('bias', 'neutral')}
- Confidence: {htf_analysis.get('confidence', 0)}%
- Current Price: {htf_analysis.get('current_price', 0)}
- Supply zones: {len(htf_analysis.get('supply_zones', []))}
- Demand zones: {len(htf_analysis.get('demand_zones', []))}
- Recent BOS: {htf_analysis.get('structure', {}).get('bos_events', [])[-2:]}
- Recent MSS: {htf_analysis.get('structure', {}).get('mss_events', [])[-2:]}
- Premium/Discount: {htf_analysis.get('premium_discount', {})}

LTF ({ltf_tf}) ANALYSIS SUMMARY:
- Trend: {ltf_analysis.get('trend', 'unknown')}
- Bias: {ltf_analysis.get('bias', 'neutral')}
- Confidence: {ltf_analysis.get('confidence', 0)}%
- Recent MSS: {ltf_analysis.get('structure', {}).get('mss_events', [])[-2:]}
- Recent CHoCH: {ltf_analysis.get('structure', {}).get('choch_events', [])[-2:]}

HTF Demand zones: {json.dumps(htf_analysis.get('demand_zones', [])[:3])}
HTF Supply zones: {json.dumps(htf_analysis.get('supply_zones', [])[:3])}
HTF Liquidity: {json.dumps(htf_analysis.get('liquidity', {}))}
LTF FVGs: {json.dumps(ltf_analysis.get('fvg', [])[:3])}

Return ONLY valid JSON — no markdown:
{{
    "confluence_score": 75,
    "trade_direction": "long",
    "htf_bias": "bullish",
    "ltf_confirmation": true,
    "reasoning": "HTF bullish with demand zone untested, LTF confirmed MSS bullish",
    "entry_zones": [
        {{
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit_1": 0.0,
            "take_profit_2": 0.0,
            "take_profit_3": 0.0,
            "risk_reward": 2.5,
            "type": "demand_retest",
            "confidence": 78,
            "reasoning": "Price retesting HTF demand OB with LTF MSS confirmation"
        }}
    ],
    "key_levels": {{
        "resistance": [0.0],
        "support": [0.0],
        "poi": [
            {{"price": 0.0, "type": "demand_ob", "importance": "critical"}}
        ]
    }},
    "invalidation": {{
        "price": 0.0,
        "reason": "Price closes below demand zone"
    }},
    "narrative": "Smart money accumulated longs in the 4H demand OB. LTF shows MSS confirming bullish intent. Looking for entries in the 15m FVG within the HTF demand zone."
}}

Use real price values from the analysis data above."""

        # Use Gemini for deep confluence analysis
        raw = self.deep_analyze(prompt, max_tokens=3000)
        result = self._parse_json(raw)

        # Fallback: try Groq
        if result.get("error") or not result.get("entry_zones"):
            print("[ICT-BRAIN] Gemini confluence failed — trying Groq...")
            raw = self.fast_analyze(prompt, max_tokens=2500)
            result = self._parse_json(raw)

        return result

    # ── Vision Analysis ──────────────────────────────────────────────────
    def analyze_chart_image(
        self, image_path: str, symbol: str, timeframe: str
    ) -> dict:
        """Analyze chart screenshot using Gemini Vision."""
        try:
            from pathlib import Path as _Path

            client = self._get_gemini()
            if not client:
                return {"error": "No Gemini client", "confidence": 0}

            img_path = _Path(image_path)
            if not img_path.exists() or img_path.stat().st_size < 2000:
                print(f"[ICT-BRAIN] Image too small or missing: {image_path}")
                return {"error": "Invalid image", "confidence": 0}

            img_data = img_path.read_bytes()
            suffix   = img_path.suffix.lower()
            mime     = {
                ".png":  "image/png",
                ".jpg":  "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
            }.get(suffix, "image/png")

            prompt = f"""You are an elite ICT/SMC analyst looking at a 
{symbol} {timeframe} TradingView chart screenshot.

Read ALL price levels DIRECTLY from the Y-axis price scale visible on 
the right side of the chart. Use the exact numbers shown.

Identify institutional footprints and return ONLY valid JSON 
(absolutely no markdown, no code blocks, no explanation):

{{
    "trend": "bullish",
    "trend_strength": 7,
    "bias": "bullish",
    "confidence": 80,
    "current_price": 2650.50,
    "structure": {{
        "swing_highs": [
            {{"price": 2680.0, "index": 95, "type": "HH", "significant": true}},
            {{"price": 2665.0, "index": 70, "type": "LH", "significant": false}}
        ],
        "swing_lows": [
            {{"price": 2620.0, "index": 80, "type": "HL", "significant": true}},
            {{"price": 2600.0, "index": 50, "type": "LL", "significant": false}}
        ],
        "bos_events": [
            {{"type": "bullish", "level": 2660.0, "index": 90, "confirmed": true}}
        ],
        "choch_events": [
            {{"type": "bullish", "level": 2645.0, "index": 85}}
        ],
        "mss_events": [
            {{"type": "bullish", "level": 2655.0, "index": 92, "displacement": true}}
        ]
    }},
    "supply_zones": [
        {{
            "high": 2685.0, "low": 2678.0,
            "origin_index": 60,
            "type": "fresh",
            "strength": 8,
            "is_order_block": true
        }}
    ],
    "demand_zones": [
        {{
            "high": 2635.0, "low": 2628.0,
            "origin_index": 40,
            "type": "fresh",
            "strength": 9,
            "is_order_block": true
        }}
    ],
    "fvg": [
        {{
            "high": 2658.0, "low": 2652.0,
            "index": 88,
            "type": "bullish",
            "filled": false
        }}
    ],
    "liquidity": {{
        "buy_side":  [{{"level": 2682.0, "type": "EQH", "swept": false}}],
        "sell_side": [{{"level": 2622.0, "type": "EQL", "swept": false}}]
    }},
    "inducements": [
        {{"level": 2648.0, "type": "bullish", "taken": true, "index": 82}}
    ],
    "premium_discount": {{
        "equilibrium": 2652.5,
        "premium_zone": 2668.0,
        "discount_zone": 2637.0,
        "current_position": "discount"
    }}
}}

Critical rules:
1. Use REAL price numbers from the chart Y-axis
2. Identify ALL visible supply and demand zones (order blocks)
3. Mark BOS where structure was broken with a strong candle
4. Mark CHoCH where trend changed direction
5. Mark MSS where displacement candle broke structure
6. Find FVGs (gaps between candle 1 high and candle 3 low, or vice versa)
7. Identify equal highs/lows as liquidity targets
8. Note any inducement levels (false breaks that trapped traders)"""

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime, "data": img_data}},
                    ]
                }],
                config={"temperature": 0.05, "max_output_tokens": 3000},
            )

            result = self._parse_json(response.text)
            if result and not result.get("error"):
                print(
                    f"[ICT-BRAIN] ✅ Vision: bias={result.get('bias')} "
                    f"confidence={result.get('confidence')}%"
                )
            return result

        except Exception as e:
            print(f"[ICT-BRAIN] Vision failed: {e}")
            traceback.print_exc()
            return {"error": str(e), "confidence": 0}

    # ── Decision Engine ──────────────────────────────────────────────────
    def decide_entry(
        self,
        confluence: dict,
        current_price: float,
        symbol: str,
    ) -> dict:
        """Final entry decision from confluence data."""
        entries = confluence.get("entry_zones", [])
        direction = confluence.get("trade_direction", "no_trade")
        score = confluence.get("confluence_score", 0)

        if not entries or direction == "no_trade" or score < 55:
            return {
                "execute": False,
                "reason": f"Score {score}/100 below threshold or no direction",
            }

        best = entries[0]
        risk = abs(
            best.get("entry_price", 0) - best.get("stop_loss", 0)
        )
        reward = abs(
            best.get("take_profit_1", 0) - best.get("entry_price", 0)
        )
        rr = round(reward / risk, 2) if risk > 0 else 0

        return {
            "execute":    rr >= 1.5 and score >= 55,
            "direction":  direction,
            "entry_price": best.get("entry_price", 0),
            "stop_loss":   best.get("stop_loss", 0),
            "tp1":         best.get("take_profit_1", 0),
            "tp2":         best.get("take_profit_2", 0),
            "tp3":         best.get("take_profit_3", 0),
            "risk_reward": rr,
            "confidence":  score,
            "entry_type":  best.get("type", ""),
            "reasoning":   best.get("reasoning", ""),
        }

    # ── Utilities ────────────────────────────────────────────────────────
    def _format_candles(self, candles: list) -> str:
        """Format candles as readable text for AI prompt."""
        lines = []
        for i, c in enumerate(candles):
            try:
                if isinstance(c, dict):
                    o = float(c.get("open",  0))
                    h = float(c.get("high",  0))
                    l = float(c.get("low",   0))
                    cl = float(c.get("close", 0))
                    v = float(c.get("volume", 0))
                else:
                    o, h, l, cl = (
                        float(c[0]), float(c[1]),
                        float(c[2]), float(c[3]),
                    )
                    v = float(c[4]) if len(c) > 4 else 0
                lines.append(
                    f"{i:3d}: O={o:.5f} H={h:.5f} "
                    f"L={l:.5f} C={cl:.5f} V={v:.0f}"
                )
            except Exception:
                continue
        return "\n".join(lines)

    def _parse_json(self, text: str) -> dict:
        """Robust JSON extraction from AI response."""
        if not text:
            return {"error": "Empty response"}

        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strip markdown
        import re
        patterns = [
            r"```json\s*([\s\S]*?)```",
            r"```\s*([\s\S]*?)```",
            r"(\{[\s\S]*\})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue

        # Try to fix common JSON issues
        try:
            cleaned = re.sub(r",\s*}", "}", text)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            match = re.search(r"(\{[\s\S]*\})", cleaned)
            if match:
                return json.loads(match.group(1))
        except Exception:
            pass

        return {"error": "JSON parse failed", "raw": text[:300]}

    # ── Candle Accessors ─────────────────────────────────────────────────
    @staticmethod
    def _get_close(candle) -> float:
        if isinstance(candle, dict):
            return float(candle.get("close", 0))
        return float(candle[3]) if len(candle) > 3 else 0.0