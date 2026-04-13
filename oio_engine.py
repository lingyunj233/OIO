"""
OIO Engine - Main Analysis Entry Point
Uses DistilBert 4-dimension model for context-aware suggestions.
"""

from models.scoring import score_oio, score_dimensions, detect_frame, predict_dimensions_batch
from models.marker_data import CONFLICT_MARKERS, PRESSURE_MARKERS, count_markers
from models import suggestion_content as SC


def ai_assistant_analyze(messages_context, current_user_id=None, show_scores=False):
    suggestions = []
    if not messages_context:
        return [SC.WELCOME]

    my_msgs = [m for m in messages_context[-15:] if m.get('is_me') or m.get('sender_id') == current_user_id]
    their_msgs = [m for m in messages_context[-15:] if not (m.get('is_me') or m.get('sender_id') == current_user_id)]
    my_text = ' '.join([m.get('content', '') for m in my_msgs])
    their_text = ' '.join([m.get('content', '') for m in their_msgs])

    my_oio = score_oio(my_msgs)
    their_oio = score_oio(their_msgs)

    if show_scores:
        suggestions.append({
            'label': 'OIO Scores (Debug)', 'type': 'dual_score', 'source': 'both',
            'my_scores': my_oio, 'their_scores': their_oio,
            'my_msg_count': len(my_msgs), 'their_msg_count': len(their_msgs),
        })

    my_dims = _avg_dimensions([m.get('content', '') for m in my_msgs])
    their_dims = _avg_dimensions([m.get('content', '') for m in their_msgs])

    if my_dims and my_dims['epistemic'] < 0.35:
        suggestions.append(SC.EPISTEMIC_LOW_SELF)
    if their_dims and their_dims['epistemic'] < 0.35:
        suggestions.append(SC.EPISTEMIC_LOW_OTHER)
    if my_dims and their_dims and my_dims['epistemic'] > 0.65 and their_dims['epistemic'] > 0.65:
        suggestions.append(SC.EPISTEMIC_HIGH)

    if my_dims and my_dims['deontic'] < 0.35:
        suggestions.append(SC.DEONTIC_LOW_SELF)
    if their_dims and their_dims['deontic'] < 0.35:
        suggestions.append(SC.DEONTIC_LOW_OTHER)
    if my_dims and their_dims and my_dims['deontic'] > 0.65 and their_dims['deontic'] > 0.65:
        suggestions.append(SC.DEONTIC_HIGH)

    if my_dims and my_dims['volitional'] < 0.35 and len(my_msgs) > 2:
        suggestions.append(SC.VOLITIONAL_LOW_SELF)
    if their_dims and their_dims['volitional'] < 0.35 and len(their_msgs) > 2:
        suggestions.append(SC.VOLITIONAL_LOW_OTHER)
    if my_dims and my_dims['volitional'] > 0.7:
        suggestions.append(SC.VOLITIONAL_HIGH)

    if my_dims and my_dims['doxastic'] < 0.35:
        suggestions.append(SC.DOXASTIC_LOW_SELF)
    if their_dims and their_dims['doxastic'] < 0.35:
        suggestions.append(SC.DOXASTIC_LOW_OTHER)

    if their_dims and their_dims['epistemic'] < 0.3 and their_dims['deontic'] < 0.3:
        suggestions.append(SC.CONFLICT_ESCALATION)
    elif (my_dims and their_dims and abs(my_dims['deontic'] - their_dims['deontic']) > 0.4 and abs(my_dims['volitional'] - their_dims['volitional']) > 0.3):
        suggestions.append(SC.POWER_IMBALANCE)

    pressure_count, _ = count_markers(my_text + ' ' + their_text, PRESSURE_MARKERS)
    if pressure_count >= 2:
        suggestions.append(SC.PRESSURE)

    if messages_context:
        last = messages_context[-1]
        if '?' in last.get('content', '') and not last.get('is_me'):
            suggestions.append(SC.QUESTION_REPLY)

    if (my_dims and their_dims and my_dims['epistemic'] > 0.6 and their_dims['epistemic'] > 0.6
        and my_dims['volitional'] > 0.5 and their_dims['volitional'] > 0.5
        and not any(s.get('type') in ['warning', 'caution'] for s in suggestions)):
        suggestions.append(SC.HEALTHY_DIALOGUE)

    if my_dims or their_dims:
        dim_card = _build_dimension_card(my_dims, their_dims, len(my_msgs), len(their_msgs))
        suggestions.insert(0 if not show_scores else 1, dim_card)

    real_suggestions = [s for s in suggestions if s.get('type') not in ['dual_score', 'dimension_summary']]
    if len(real_suggestions) == 0:
        avg_openness = 'N/A'
        if my_dims and their_dims:
            avg = (my_dims['epistemic'] + their_dims['epistemic'] + my_dims['deontic'] + their_dims['deontic']) / 4
            avg_openness = f'{avg:.2f}'
        suggestions.append(SC.get_fallback(len(messages_context), avg_openness))

    return suggestions


def _avg_dimensions(texts):
    texts = [t for t in texts if t.strip()]
    if not texts:
        return None
    batch = predict_dimensions_batch(texts)
    if batch:
        return {k: sum(r[k] for r in batch) / len(batch) for k in ['epistemic', 'deontic', 'volitional', 'doxastic']}
    return score_dimensions(' '.join(texts))


def _build_dimension_card(my_dims, their_dims, my_count, their_count):
    lines = []
    if my_dims and my_count > 0:
        lines.append(f'You ({my_count} msgs): Ep {my_dims["epistemic"]:.2f} | De {my_dims["deontic"]:.2f} | Vo {my_dims["volitional"]:.2f} | Dx {my_dims["doxastic"]:.2f}')
    if their_dims and their_count > 0:
        lines.append(f'Them ({their_count} msgs): Ep {their_dims["epistemic"]:.2f} | De {their_dims["deontic"]:.2f} | Vo {their_dims["volitional"]:.2f} | Dx {their_dims["doxastic"]:.2f}')
    if not lines:
        lines.append('Waiting for more messages to analyze...')
    return {'label': 'FFCM Dimensions', 'type': 'dimension_summary', 'source': 'both', 'text': chr(10).join(lines)}
