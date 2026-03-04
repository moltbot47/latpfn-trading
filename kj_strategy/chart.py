"""Interactive Plotly chart generation with full setup markup."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from kj_strategy.setup import KJSetup

CHART_DIR = "reports/kj_charts"


def generate_chart(
    setup: KJSetup,
    df: pd.DataFrame,
    context_bars: int = 50,
    output_dir: str = CHART_DIR,
) -> str:
    """
    Generate an interactive Plotly HTML chart with full KJ setup markup.

    Returns path to the saved HTML file.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Determine chart range
    swing_start = min(setup.swing_high.index, setup.swing_low.index)
    chart_start = max(0, swing_start - context_bars // 3)
    chart_end = min(len(df), setup.entry_bar_index + context_bars)
    if setup.bars_to_exit:
        chart_end = min(len(df), setup.entry_bar_index + setup.bars_to_exit + 20)

    chart_df = df.iloc[chart_start:chart_end]
    price_range = chart_df["High"].max() - chart_df["Low"].min()
    offset_unit = price_range * 0.03  # consistent spacing unit for annotations

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.8, 0.2],
        vertical_spacing=0.02,
    )

    # Candlestick chart
    fig.add_trace(
        go.Candlestick(
            x=chart_df.index,
            open=chart_df["Open"],
            high=chart_df["High"],
            low=chart_df["Low"],
            close=chart_df["Close"],
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1, col=1,
    )

    # ── Collect pattern-relevant timestamps for volume spike alignment ──
    pattern_timestamps = set()
    if setup.patterns:
        best = setup.patterns[0]
        pattern_timestamps.add(best.timestamp)
        if best.metadata:
            prior_ts = best.metadata.get("prior_timestamp")
            if prior_ts is not None:
                pattern_timestamps.add(prior_ts)
    # Also include entry timestamp
    entry_ts = df.index[setup.entry_bar_index]
    pattern_timestamps.add(entry_ts)

    # ── Volume bars with spike highlighting ──
    if "Volume" in chart_df.columns:
        vol_vals = chart_df["Volume"].values.astype(float)
        vol_avg = np.mean(vol_vals[vol_vals > 0]) if np.any(vol_vals > 0) else 1.0
        spike_threshold = vol_avg * 1.5

        colors = []
        for c, o, v in zip(chart_df["Close"], chart_df["Open"], vol_vals):
            if v >= spike_threshold:
                colors.append("rgba(255,215,0,0.95)")  # gold for spikes
            elif c >= o:
                colors.append("#26a69a")
            else:
                colors.append("#ef5350")

        fig.add_trace(
            go.Bar(
                x=chart_df.index,
                y=chart_df["Volume"],
                marker_color=colors,
                opacity=0.6,
                name="Volume",
                showlegend=False,
            ),
            row=2, col=1,
        )

        # Volume average line
        fig.add_hline(
            y=vol_avg,
            line_dash="dot",
            line_color="rgba(255,255,255,0.3)",
            line_width=1,
            annotation_text="avg",
            annotation_position="right",
            annotation_font_size=9,
            annotation_font_color="rgba(255,255,255,0.4)",
            row=2, col=1,
        )

        # Label volume spikes near the pattern locations (both tops/bottoms + entry)
        labeled_count = 0
        for ts, v in zip(chart_df.index, vol_vals):
            if v < spike_threshold:
                continue
            # Check proximity to any pattern-relevant timestamp (within ~10 bars = 50 min)
            near_pattern = any(
                abs((ts - pts).total_seconds()) < 3600 for pts in pattern_timestamps
            )
            if near_pattern and labeled_count < 4:
                fig.add_annotation(
                    x=ts, y=v,
                    text=f"<b>{v/vol_avg:.1f}x</b> vol",
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1.2,
                    arrowcolor="gold",
                    ay=-30,
                    font=dict(size=10, color="gold"),
                    bgcolor="rgba(0,0,0,0.85)",
                    bordercolor="gold",
                    borderwidth=1,
                    row=2, col=1,
                )
                labeled_count += 1

    # ── Fibonacci levels ──
    fib_colors = {
        "0.0": "rgba(128,128,128,0.3)",
        "23.6": "rgba(255,235,59,0.4)",
        "38.2": "rgba(255,152,0,0.6)",
        "50.0": "rgba(244,67,54,0.6)",
        "61.8": "rgba(156,39,176,0.6)",
        "78.6": "rgba(63,81,181,0.4)",
        "100.0": "rgba(128,128,128,0.3)",
    }

    for level_key, price in setup.fib_levels.levels.items():
        is_active = level_key == setup.active_fib_level
        color = fib_colors.get(level_key, "rgba(128,128,128,0.3)")
        width = 2.5 if is_active else 1

        fig.add_hline(
            y=price,
            line_dash="dash" if not is_active else "solid",
            line_color=color,
            line_width=width,
            annotation_text=f"Fib {level_key}%: {price:.2f}" if is_active else f"{level_key}%",
            annotation_position="right",
            annotation_font_size=10 if not is_active else 12,
            annotation_font_color=color,
            row=1, col=1,
        )

    # Active Fib zone shading
    zone_lo, zone_hi = setup.fib_levels.zone(setup.active_fib_level)
    fig.add_hrect(
        y0=zone_lo, y1=zone_hi,
        fillcolor="rgba(255,193,7,0.15)",
        line_width=0,
        row=1, col=1,
    )

    # ── Swing markers ──
    fig.add_trace(
        go.Scatter(
            x=[setup.swing_high.timestamp],
            y=[setup.swing_high.price],
            mode="markers+text",
            marker=dict(symbol="triangle-down", size=14, color="red"),
            text=["SH"],
            textposition="top center",
            name="Swing High",
            showlegend=False,
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=[setup.swing_low.timestamp],
            y=[setup.swing_low.price],
            mode="markers+text",
            marker=dict(symbol="triangle-up", size=14, color="green"),
            text=["SL"],
            textposition="bottom center",
            name="Swing Low",
            showlegend=False,
        ),
        row=1, col=1,
    )

    # ── Entry line ──
    fig.add_hline(
        y=setup.entry_price,
        line_dash="dot",
        line_color="cyan",
        line_width=2,
        annotation_text=f"Entry: {setup.entry_price:.2f}",
        annotation_position="left",
        annotation_font_color="cyan",
        row=1, col=1,
    )

    # ── Stop loss line ──
    fig.add_hline(
        y=setup.stop_loss,
        line_dash="dot",
        line_color="red",
        line_width=2,
        annotation_text=f"SL: {setup.stop_loss:.2f}",
        annotation_position="left",
        annotation_font_color="red",
        row=1, col=1,
    )

    # ── Take profit line ──
    fig.add_hline(
        y=setup.take_profit,
        line_dash="dot",
        line_color="lime",
        line_width=2,
        annotation_text=f"TP: {setup.take_profit:.2f}",
        annotation_position="left",
        annotation_font_color="lime",
        row=1, col=1,
    )

    # ── Pattern annotation + double top/bottom markers ──
    if setup.patterns:
        best = setup.patterns[0]

        # Double top/bottom: mark BOTH tops/bottoms with bold markers
        if best.pattern_type in ("double_top", "double_bottom") and best.metadata:
            meta = best.metadata
            prior_ts = meta.get("prior_timestamp")
            prior_price = meta.get("prior_price")
            current_price = meta.get("current_price")

            is_top = best.pattern_type == "double_top"
            marker_color = "#FF00FF"  # bright magenta

            # 1st touch — circle marker with label offset AWAY from price
            if prior_ts is not None and prior_price is not None:
                fig.add_trace(
                    go.Scatter(
                        x=[prior_ts],
                        y=[prior_price],
                        mode="markers",
                        marker=dict(
                            symbol="circle-open",
                            size=22,
                            color=marker_color,
                            line=dict(width=3, color=marker_color),
                        ),
                        name="1st Touch",
                        showlegend=False,
                        hovertext=f"1st {'Top' if is_top else 'Bottom'}: {prior_price:,.2f}",
                    ),
                    row=1, col=1,
                )
                # Label offset above for tops, below for bottoms
                fig.add_annotation(
                    x=prior_ts,
                    y=prior_price + (offset_unit * 2.5 if is_top else -offset_unit * 2.5),
                    text=f"<b>1st {'Top' if is_top else 'Bottom'}</b><br>{prior_price:,.2f}",
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1.2,
                    arrowwidth=2,
                    arrowcolor=marker_color,
                    ax=0,
                    ay=-40 if is_top else 40,
                    font=dict(size=12, color=marker_color),
                    bgcolor="rgba(0,0,0,0.85)",
                    bordercolor=marker_color,
                    borderwidth=2,
                    row=1, col=1,
                )

            # 2nd touch — circle marker with label
            cur_price = current_price or (zone_hi if is_top else zone_lo)
            fig.add_trace(
                go.Scatter(
                    x=[best.timestamp],
                    y=[cur_price],
                    mode="markers",
                    marker=dict(
                        symbol="circle-open",
                        size=22,
                        color=marker_color,
                        line=dict(width=3, color=marker_color),
                    ),
                    name="2nd Touch",
                    showlegend=False,
                    hovertext=f"2nd {'Top' if is_top else 'Bottom'}: {cur_price:,.2f}",
                ),
                row=1, col=1,
            )
            fig.add_annotation(
                x=best.timestamp,
                y=cur_price + (offset_unit * 2.5 if is_top else -offset_unit * 2.5),
                text=f"<b>2nd {'Top' if is_top else 'Bottom'}</b><br>{cur_price:,.2f}",
                showarrow=True,
                arrowhead=2,
                arrowsize=1.2,
                arrowwidth=2,
                arrowcolor=marker_color,
                ax=0,
                ay=-40 if is_top else 40,
                font=dict(size=12, color=marker_color),
                bgcolor="rgba(0,0,0,0.85)",
                bordercolor=marker_color,
                borderwidth=2,
                row=1, col=1,
            )

            # Horizontal connecting line between the two touches
            if prior_ts is not None and prior_price is not None and current_price is not None:
                fig.add_trace(
                    go.Scatter(
                        x=[prior_ts, best.timestamp],
                        y=[prior_price, current_price],
                        mode="lines",
                        line=dict(color=marker_color, width=2.5, dash="dash"),
                        showlegend=False,
                        hoverinfo="skip",
                    ),
                    row=1, col=1,
                )

            # Pattern name label — positioned BELOW for tops, ABOVE for bottoms
            # Offset it well away from the double top/bottom markers so no overlap
            label_y = (
                cur_price - offset_unit * 3 if is_top
                else cur_price + offset_unit * 3
            )
            fig.add_annotation(
                x=best.timestamp,
                y=label_y,
                text=f"<b>{best.pattern_type.replace('_', ' ').title()}</b> ({best.confidence:.0%})",
                showarrow=True,
                arrowhead=0,
                arrowwidth=1.5,
                arrowcolor="yellow",
                ax=0,
                ay=30 if is_top else -30,
                font=dict(size=11, color="yellow"),
                bgcolor="rgba(0,0,0,0.8)",
                bordercolor="yellow",
                borderwidth=1,
                row=1, col=1,
            )

        else:
            # Non-double-top/bottom patterns: label arrow at the zone
            fig.add_annotation(
                x=best.timestamp,
                y=zone_lo if setup.trend_direction == "bullish" else zone_hi,
                text=f"<b>{best.pattern_type.replace('_', ' ').title()}</b><br>({best.confidence:.0%})",
                showarrow=True,
                arrowhead=2,
                arrowsize=1.5,
                arrowwidth=2,
                arrowcolor="yellow",
                font=dict(size=11, color="yellow"),
                bgcolor="rgba(0,0,0,0.7)",
                bordercolor="yellow",
                row=1, col=1,
            )

    # ── Entry candle circle ──
    entry_idx = setup.entry_bar_index
    if 0 <= entry_idx < len(df):
        entry_high = float(df["High"].iloc[entry_idx])
        entry_low = float(df["Low"].iloc[entry_idx])
        entry_mid = (entry_high + entry_low) / 2

        # Large glowing circle around the entry candle
        fig.add_trace(
            go.Scatter(
                x=[entry_ts],
                y=[entry_mid],
                mode="markers",
                marker=dict(
                    symbol="circle-open",
                    size=45,
                    color="cyan",
                    line=dict(width=4, color="cyan"),
                ),
                name="Entry Candle",
                showlegend=False,
                hovertext=f"ENTRY @ {setup.entry_price:,.2f}",
            ),
            row=1, col=1,
        )
        # Second outer ring for glow effect
        fig.add_trace(
            go.Scatter(
                x=[entry_ts],
                y=[entry_mid],
                mode="markers",
                marker=dict(
                    symbol="circle-open",
                    size=55,
                    color="rgba(0,255,255,0.3)",
                    line=dict(width=2, color="rgba(0,255,255,0.3)"),
                ),
                showlegend=False,
                hoverinfo="skip",
            ),
            row=1, col=1,
        )
        # ENTRY label below the circle, offset so it doesn't overlap
        fig.add_annotation(
            x=entry_ts,
            y=entry_low - offset_unit * 2.5,
            text="<b>ENTRY</b>",
            showarrow=True,
            arrowhead=2,
            arrowsize=1.5,
            arrowwidth=2,
            arrowcolor="cyan",
            ax=0,
            ay=30,
            font=dict(size=14, color="cyan", family="Arial Black"),
            bgcolor="rgba(0,0,0,0.85)",
            bordercolor="cyan",
            borderwidth=2,
            row=1, col=1,
        )

    # ── Outcome badge ──
    if setup.outcome:
        badge_color = (
            "lime" if setup.outcome == "win"
            else "red" if setup.outcome == "loss"
            else "gray"
        )
        rr_text = f"{setup.actual_rr:+.1f}R" if setup.actual_rr is not None else ""
        fig.add_annotation(
            text=f"<b>{setup.outcome.upper()} {rr_text}</b>",
            xref="paper", yref="paper",
            x=0.98, y=0.98,
            showarrow=False,
            font=dict(size=16, color=badge_color),
            bgcolor="rgba(0,0,0,0.8)",
            bordercolor=badge_color,
            borderwidth=2,
        )

    # ── Classification badge ──
    fig.add_annotation(
        text=f"<b>{setup.classification.upper()}</b> ({setup.textbook_score:.0f}/100)",
        xref="paper", yref="paper",
        x=0.02, y=0.98,
        showarrow=False,
        font=dict(
            size=14,
            color="gold" if setup.classification == "textbook" else "silver",
        ),
        bgcolor="rgba(0,0,0,0.8)",
        bordercolor="gold" if setup.classification == "textbook" else "silver",
        borderwidth=2,
    )

    # ── Layout ──
    title = (
        f"{setup.instrument} — KJ {setup.trend_direction.title()} Setup @ "
        f"Fib {setup.active_fib_level}% | R:R {setup.reward_risk_ratio:.1f}:1"
    )
    fig.update_layout(
        title=title,
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        height=750,
        margin=dict(l=60, r=120, t=50, b=30),
    )

    # Save
    date_str = setup.entry_timestamp.strftime("%Y%m%d_%H%M") if setup.entry_timestamp else "unknown"
    filename = f"{setup.instrument}_{setup.setup_id}_{date_str}.html"
    path = os.path.join(output_dir, filename)
    fig.write_html(path)

    setup.chart_path = path
    return path
