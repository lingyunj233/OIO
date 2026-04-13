"""
OIO Email Reply Generator
=========================
Analyzes incoming email using the 4-dimension framework
(Epistemic, Deontic, Volitional, Doxastic) and generates
reply options with different tones.

Supports two modes:
  1. Reply Mode: Analyze received email → generate reply options
  2. Guardian Mode: Analyze user's own draft → flag risky phrasing

Each analysis card has an 'id' field so the frontend can select
specific advice cards and request a regenerated reply incorporating them.
"""

import re

from models.marker_data import (
    CONFLICT_MARKERS, CLOSED_STANCE_MARKERS, OPENNESS_MARKERS,
    PRESSURE_MARKERS, ABSOLUTE_MARKERS, count_markers
)
from models.scoring import score_dimensions
from models.typo_detect import detect_typos


# =============================================
# Name Extraction
# =============================================

def extract_sender_name(email_text):
    """
    Extract sender's name from email signature/sign-off.
    Looks for common patterns like:
      - "Best regards,\nJohn"
      - "Thanks,\nMary Smith"
      - "Sincerely,\n张三"
      - Lines at the very end that look like a name
    Returns the extracted name or None.
    """
    if not email_text or not email_text.strip():
        return None

    lines = [l.strip() for l in email_text.strip().split('\n') if l.strip()]
    if not lines:
        return None

    # Common sign-off keywords (EN + ZH)
    signoff_keywords = [
        'regards', 'best regards', 'kind regards', 'warm regards',
        'sincerely', 'yours sincerely', 'yours truly',
        'thanks', 'thank you', 'many thanks', 'cheers', 'best',
        'respectfully', 'with appreciation',
        '此致', '敬上', '谢谢', '感谢', '致敬', '顺祝', '此致敬礼',
        'best wishes', 'take care',
    ]

    # Strategy 1: Look for "sign-off,\n Name" pattern
    for i, line in enumerate(lines):
        line_lower = line.lower().rstrip(',').rstrip('，').strip()
        if line_lower in signoff_keywords:
            # The name is likely on the next non-empty line(s)
            for j in range(i + 1, min(i + 3, len(lines))):
                candidate = lines[j].strip()
                # Skip email addresses, phone numbers, URLs, job titles with common keywords
                if '@' in candidate or candidate.startswith('http') or candidate.startswith('+'):
                    continue
                if any(skip in candidate.lower() for skip in ['tel:', 'phone:', 'email:', 'mobile:', '电话', '邮箱']):
                    continue
                # Check if it looks like a name (short, no punctuation overload)
                if len(candidate) <= 40 and not candidate.endswith(('.', '。')):
                    # Could be "John Smith" or "张三" or "Dr. Jane Lee"
                    return candidate
            break

    # Strategy 2: Check last 1-3 lines for standalone name
    # (email ends with just a name, no sign-off keyword)
    for i in range(len(lines) - 1, max(len(lines) - 4, -1), -1):
        candidate = lines[i].strip().rstrip(',').rstrip('，')
        # Skip if it looks like a sentence or email body
        if len(candidate) > 30:
            continue
        if any(c in candidate for c in ['@', ':', 'http', '?', '!', '？', '！']):
            continue
        # Check if it's a plausible name: 1-4 words for English, 2-4 chars for Chinese
        words = candidate.split()
        chinese_chars = sum(1 for c in candidate if '\u4e00' <= c <= '\u9fff')
        if chinese_chars >= 2 and chinese_chars <= 4 and len(candidate) <= 6:
            return candidate
        if 1 <= len(words) <= 4 and all(w[0].isupper() or w[0] == '-' for w in words if w):
            # Looks like a capitalized name
            return candidate

    # Strategy 3: Check "From:" or "发件人:" header
    for line in lines[:5]:  # Usually at the top
        from_match = re.match(r'(?:From|发件人)[：:]\s*(.+)', line, re.IGNORECASE)
        if from_match:
            name_part = from_match.group(1).strip()
            # If it contains an email in angle brackets, extract the name before it
            bracket_match = re.match(r'(.+?)\s*<', name_part)
            if bracket_match:
                return bracket_match.group(1).strip().strip('"').strip("'")
            if '@' not in name_part:
                return name_part

    return None


# =============================================
# Additional Marker Sets (for richer analysis)
# =============================================

HEDGING_MARKERS = {
    'en': ['perhaps', 'maybe', 'might', 'possibly', 'it seems', 'i think',
           'in my opinion', 'from my perspective', 'i believe', 'could be'],
    'zh': ['也许', '可能', '或许', '我觉得', '我认为', '似乎', '看起来', '个人认为']
}

FORMALITY_MARKERS = {
    'en': ['dear', 'sincerely', 'regards', 'respectfully', 'hereby',
           'kindly', 'pursuant', 'acknowledge', 'appreciate', 'accordingly'],
    'zh': ['尊敬的', '此致', '敬上', '谨此', '特此', '烦请', '承蒙', '贵方']
}

INFORMAL_MARKERS = {
    'en': ['hey', 'gonna', 'wanna', 'btw', 'lol', 'tbh', 'fyi',
           'no worries', 'cool', 'awesome', 'yeah', 'nope', 'stuff'],
    'zh': ['哈哈', '嗯嗯', '咋', '啥', '挺好', '没事', '行吧', '随你']
}

QUESTION_MARKERS = {
    'en': ['?', 'could you', 'would you', 'can you', 'do you', 'is it',
           'what do you think', 'how about', 'shall we', 'are you'],
    'zh': ['？', '吗', '呢', '能否', '是否', '怎么样', '可以吗', '好吗']
}

EMOTIONAL_MARKERS = {
    'en': ['disappointed', 'frustrated', 'upset', 'concerned', 'worried',
           'surprised', 'confused', 'appreciate', 'grateful', 'pleased',
           'sorry', 'apologize', 'regret', 'unfortunately', 'delighted'],
    'zh': ['失望', '沮丧', '担心', '困惑', '感谢', '抱歉', '遗憾',
           '高兴', '感激', '不满', '焦虑', '无奈']
}

PASSIVE_AGGRESSIVE_MARKERS = {
    'en': ['as i mentioned', 'per my last email', 'as previously stated',
           'i already told you', 'as you should know', 'going forward',
           'just to be clear', 'with all due respect', 'no offense but',
           'as per usual', 'once again'],
    'zh': ['我之前说过', '上次已经说了', '再说一遍', '你应该知道',
           '不是说过了吗', '恕我直言', '话说回来']
}


# =============================================
# Shared Analysis Helpers
# =============================================

def analyze_email(text):
    """Analyze incoming email content and return OIO dimension signals + suggestions."""
    analysis = []

    conflict_count, conflict_matched = count_markers(text, CONFLICT_MARKERS)
    pressure_count, pressure_matched = count_markers(text, PRESSURE_MARKERS)
    absolute_count, absolute_matched = count_markers(text, ABSOLUTE_MARKERS)
    closed_count, closed_matched = count_markers(text, CLOSED_STANCE_MARKERS)
    open_count, open_matched = count_markers(text, OPENNESS_MARKERS)
    hedging_count, hedging_matched = count_markers(text, HEDGING_MARKERS)
    formal_count, formal_matched = count_markers(text, FORMALITY_MARKERS)
    informal_count, informal_matched = count_markers(text, INFORMAL_MARKERS)
    question_count, question_matched = count_markers(text, QUESTION_MARKERS)
    emotional_count, emotional_matched = count_markers(text, EMOTIONAL_MARKERS)
    passive_agg_count, passive_agg_matched = count_markers(text, PASSIVE_AGGRESSIVE_MARKERS)

    # === Conflict detection ===
    if conflict_count >= 2:
        analysis.append({
            'id': 'conflict_high',
            'label': 'Conflict Signals Detected',
            'type': 'warning',
            'source': 'sender',
            'text': 'This email contains confrontational language (' + ', '.join(conflict_matched[:3]) + '). Avoid matching the tone — respond with measured, specific language.',
            'advice': 'Use de-escalating language. Acknowledge their frustration without being defensive.'
        })
    elif conflict_count == 1:
        analysis.append({
            'id': 'conflict_mild',
            'label': 'Mild Tension',
            'type': 'caution',
            'source': 'sender',
            'text': 'Slight tension detected (' + conflict_matched[0] + '). Acknowledge their concern before presenting your perspective.',
            'advice': 'Start with acknowledgment before your main point.'
        })

    # === Passive-aggressive detection ===
    if passive_agg_count >= 1:
        analysis.append({
            'id': 'passive_aggressive',
            'label': 'Passive-Aggressive Signals',
            'type': 'caution',
            'source': 'sender',
            'text': 'Phrases like "' + '", "'.join(passive_agg_matched[:2]) + '" may indicate frustration or impatience. Stay factual and avoid defensiveness.',
            'advice': 'Respond directly to the substance, not the tone. Avoid echoing passive-aggressive patterns.'
        })

    # === Pressure detection ===
    if pressure_count >= 1:
        analysis.append({
            'id': 'pressure',
            'label': 'Urgency / Pressure',
            'type': 'warning',
            'source': 'sender',
            'text': 'The sender is creating time pressure (' + ', '.join(pressure_matched[:2]) + '). Set a realistic timeline in your reply rather than accepting rushed deadlines.',
            'advice': 'Set a clear, realistic timeline instead of accepting urgency passively.'
        })

    # === Absolute language ===
    if absolute_count >= 1:
        analysis.append({
            'id': 'absolute',
            'label': 'Absolute Language',
            'type': 'nudge',
            'source': 'sender',
            'text': 'The sender uses generalizations (' + ', '.join(absolute_matched[:3]) + '). Respond with specifics and examples rather than matching their absolutes.',
            'advice': 'Counter with specific data points and concrete examples.'
        })

    # === Closed stance ===
    if closed_count >= 1:
        analysis.append({
            'id': 'closed_stance',
            'label': 'Closed Stance',
            'type': 'caution',
            'source': 'sender',
            'text': 'The sender appears to be shutting down discussion (' + ', '.join(closed_matched[:2]) + '). Try reopening dialogue with an open question.',
            'advice': 'Ask an open-ended question to invite continued dialogue.'
        })

    # === Power dynamics ===
    directive_markers = {
        'en': ['you must', 'you need to', 'you should', 'i expect', 'i require',
               'make sure', 'ensure that', 'i need you to', 'do not', 'report to me'],
        'zh': ['你必须', '你需要', '你应该', '我要求', '确保', '不要', '向我汇报']
    }
    directive_count, directive_matched = count_markers(text, directive_markers)
    if directive_count >= 1:
        analysis.append({
            'id': 'power_asymmetry',
            'label': 'Power Asymmetry',
            'type': 'caution',
            'source': 'sender',
            'text': 'Directive language detected (' + ', '.join(directive_matched[:2]) + '). The sender may be asserting authority. Respond professionally while maintaining your position.',
            'advice': 'Acknowledge their authority while clearly stating your professional perspective.'
        })

    # === Emotional tone ===
    negative_emotions = ['disappointed', 'frustrated', 'upset', 'concerned', 'worried',
                         'confused', 'sorry', 'apologize', 'regret', 'unfortunately',
                         '失望', '沮丧', '担心', '困惑', '抱歉', '遗憾', '不满', '焦虑', '无奈']
    positive_emotions = ['appreciate', 'grateful', 'pleased', 'delighted',
                         '感谢', '感激', '高兴']
    neg_emo = [m for m in emotional_matched if m in negative_emotions]
    pos_emo = [m for m in emotional_matched if m in positive_emotions]

    if len(neg_emo) >= 1:
        analysis.append({
            'id': 'negative_emotion',
            'label': 'Emotional Undertone',
            'type': 'nudge',
            'source': 'sender',
            'text': 'The sender expresses negative emotions (' + ', '.join(neg_emo[:2]) + '). Show empathy first, then address the substance.',
            'advice': 'Lead with empathy: validate their feelings before problem-solving.'
        })
    if len(pos_emo) >= 1:
        analysis.append({
            'id': 'positive_emotion',
            'label': 'Positive Sentiment',
            'type': 'positive',
            'source': 'sender',
            'text': 'The sender expresses positive feelings (' + ', '.join(pos_emo[:2]) + '). Reciprocate warmth to strengthen the relationship.',
            'advice': 'Mirror their positive tone and build on the goodwill.'
        })

    # === Formality mismatch detection ===
    if formal_count >= 2 and informal_count == 0:
        analysis.append({
            'id': 'high_formality',
            'label': 'Formal Register',
            'type': 'nudge',
            'source': 'sender',
            'text': 'The sender uses highly formal language (' + ', '.join(formal_matched[:2]) + '). Match their register — an overly casual reply may seem dismissive.',
            'advice': 'Match the sender\'s formality level. Use professional greetings and closings.'
        })
    elif informal_count >= 2 and formal_count == 0:
        analysis.append({
            'id': 'low_formality',
            'label': 'Casual Register',
            'type': 'nudge',
            'source': 'sender',
            'text': 'The sender uses casual language (' + ', '.join(informal_matched[:2]) + '). You can be slightly less formal — but stay professional.',
            'advice': 'Adopt a friendly but professional tone. Avoid being overly stiff.'
        })

    # === Question handling strategy ===
    if question_count >= 2:
        analysis.append({
            'id': 'multiple_questions',
            'label': 'Multiple Questions Detected',
            'type': 'nudge',
            'source': 'sender',
            'text': str(question_count) + ' questions found in this email. Address each one clearly to avoid back-and-forth.',
            'advice': 'Structure your reply with numbered responses to each question.'
        })
    elif question_count == 1:
        analysis.append({
            'id': 'single_question',
            'label': 'Question Requires Response',
            'type': 'nudge',
            'source': 'sender',
            'text': 'The sender asked a direct question. Make sure your reply clearly answers it.',
            'advice': 'Answer the question directly at the start, then add context.'
        })

    # === Collaborative signals ===
    if open_count >= 1:
        analysis.append({
            'id': 'collaborative',
            'label': 'Collaborative Tone',
            'type': 'positive',
            'source': 'sender',
            'text': 'The sender is being open and collaborative (' + ', '.join(open_matched[:2]) + '). Match their energy — propose next steps or share your thoughts.',
            'advice': 'Match their collaborative energy with concrete proposals.'
        })

    # === Hedging / Uncertainty ===
    if hedging_count >= 2:
        analysis.append({
            'id': 'hedging',
            'label': 'Uncertainty Signals',
            'type': 'nudge',
            'source': 'sender',
            'text': 'The sender hedges frequently (' + ', '.join(hedging_matched[:2]) + '). They may be unsure or testing the waters. Offer clarity and concrete options.',
            'advice': 'Provide clear, decisive guidance to help them move forward.'
        })

    # === 4-Dimension Model Analysis ===
    dims = score_dimensions(text)

    # Build human-readable dimension insights (NO raw scores in text)
    dim_insights = []
    dim_advice_parts = []

    if dims['epistemic'] < 0.4:
        dim_insights.append('The sender sounds very certain and closed to alternatives.')
        dim_advice_parts.append('Gently introduce other possibilities to broaden the conversation.')
    elif dims['epistemic'] > 0.65:
        dim_insights.append('The sender is exploring and open to ideas.')
        dim_advice_parts.append('Match their openness — share your own thoughts freely.')

    if dims['deontic'] < 0.4:
        dim_insights.append('The sender uses directive language, setting obligations.')
        dim_advice_parts.append('Acknowledge their expectations while asserting your boundaries.')
    elif dims['deontic'] > 0.65:
        dim_insights.append('The sender is permissive and inviting your input.')
        dim_advice_parts.append('Take the opportunity to contribute your perspective.')

    if dims['volitional'] < 0.4:
        dim_insights.append('The sender seems externally driven rather than self-motivated.')
        dim_advice_parts.append('Help them by providing clear direction and next steps.')

    if dims['doxastic'] < 0.4:
        dim_insights.append('The sender makes claims without much supporting evidence.')
        dim_advice_parts.append('Ask for specifics or provide your own evidence-based response.')

    if dim_insights:
        analysis.append({
            'id': 'ffcm_dims',
            'label': 'Communication Pattern',
            'type': 'nudge',
            'source': 'sender',
            'text': ' '.join(dim_insights),
            'advice': ' '.join(dim_advice_parts),
            '_debug_scores': {
                'epistemic': dims['epistemic'],
                'deontic': dims['deontic'],
                'volitional': dims['volitional'],
                'doxastic': dims['doxastic'],
            },
        })

    # === Email length / effort signal ===
    word_count = len(text.split())
    if word_count > 200:
        analysis.append({
            'id': 'long_email',
            'label': 'Detailed Email',
            'type': 'nudge',
            'source': 'sender',
            'text': 'This is a lengthy email (' + str(word_count) + ' words). The sender has invested significant effort. Match their effort level in your reply.',
            'advice': 'Write a thorough response addressing all points. A short reply may seem dismissive.'
        })
    elif word_count < 30:
        analysis.append({
            'id': 'short_email',
            'label': 'Brief Message',
            'type': 'nudge',
            'source': 'sender',
            'text': 'This is a very brief email (' + str(word_count) + ' words). Keep your reply concise and direct.',
            'advice': 'Match their brevity — get to the point quickly.'
        })
    elif word_count >= 30 and word_count <= 200:
        analysis.append({
            'id': 'medium_email',
            'label': 'Standard Length',
            'type': 'info',
            'source': 'sender',
            'text': 'This email is a standard length (' + str(word_count) + ' words).',
            'advice': 'Respond with a similar level of detail.'
        })

    # =======================================================
    # Always-applicable strategy cards (appear for ANY email)
    # =======================================================

    # -- Response structure advice --
    analysis.append({
        'id': 'strategy_structured',
        'label': 'Structure Your Reply',
        'type': 'strategy',
        'source': 'strategy',
        'text': 'A well-structured reply is easier to read and more likely to get a clear response.',
        'advice': 'Use a clear format: greeting → acknowledgment → main points → next steps → closing.'
    })

    # -- Relationship building --
    analysis.append({
        'id': 'strategy_rapport',
        'label': 'Build Rapport',
        'type': 'strategy',
        'source': 'strategy',
        'text': 'Small rapport-building phrases strengthen professional relationships over time.',
        'advice': 'Add a brief personal touch (e.g., "Hope your week is going well") or reference a previous positive interaction.'
    })

    # -- Clarity & next steps --
    analysis.append({
        'id': 'strategy_next_steps',
        'label': 'Clarify Next Steps',
        'type': 'strategy',
        'source': 'strategy',
        'text': 'Emails without clear next steps often lead to more back-and-forth.',
        'advice': 'End with a specific action item, deadline, or question to move things forward.'
    })

    # -- Provide your context --
    analysis.append({
        'id': 'strategy_add_context',
        'label': 'Add Your Details',
        'type': 'strategy',
        'source': 'strategy',
        'text': 'Make the reply more specific by adding your own context — times, places, preferences.',
        'advice': 'Use the input box below to add details like meeting times, locations, or specific requests that should be included in your reply.',
        'has_user_input': True,
    })

    # Fallback removed — we always have strategy cards now

    return analysis


# =============================================
# Guardian: Analyze user's own draft
# =============================================

def analyze_draft(draft_text):
    """
    Guardian: Analyze user's own reply draft for risky phrasing,
    tone issues, and areas for improvement.
    """
    analysis = []

    conflict_count, conflict_matched = count_markers(draft_text, CONFLICT_MARKERS)
    pressure_count, pressure_matched = count_markers(draft_text, PRESSURE_MARKERS)
    absolute_count, absolute_matched = count_markers(draft_text, ABSOLUTE_MARKERS)
    closed_count, closed_matched = count_markers(draft_text, CLOSED_STANCE_MARKERS)
    open_count, open_matched = count_markers(draft_text, OPENNESS_MARKERS)
    passive_agg_count, passive_agg_matched = count_markers(draft_text, PASSIVE_AGGRESSIVE_MARKERS)
    hedging_count, hedging_matched = count_markers(draft_text, HEDGING_MARKERS)
    emotional_count, emotional_matched = count_markers(draft_text, EMOTIONAL_MARKERS)

    # === RISK FLAGS ===

    if conflict_count >= 2:
        analysis.append({
            'id': 'tg_conflict_high',
            'label': 'Risky Phrasing Detected',
            'type': 'warning',
            'source': 'self',
            'text': 'Your draft contains confrontational language (' + ', '.join(conflict_matched[:3]) + '). This may escalate the situation and damage the relationship.',
            'advice': 'Replace confrontational phrases with neutral, fact-based language.',
            'fix_type': 'soften_conflict'
        })
    elif conflict_count == 1:
        analysis.append({
            'id': 'tg_conflict_mild',
            'label': 'Tone Alert',
            'type': 'caution',
            'source': 'self',
            'text': 'Your draft has a slightly tense phrase (' + conflict_matched[0] + '). Consider softening to maintain professionalism.',
            'advice': 'Rephrase the tense expression with a more neutral alternative.',
            'fix_type': 'soften_conflict'
        })

    if passive_agg_count >= 1:
        analysis.append({
            'id': 'tg_passive_agg',
            'label': 'Passive-Aggressive Risk',
            'type': 'warning',
            'source': 'self',
            'text': 'Phrases like "' + '", "'.join(passive_agg_matched[:2]) + '" can come across as passive-aggressive. This damages trust over time.',
            'advice': 'Be direct instead of using indirect frustration. State what you need clearly.',
            'fix_type': 'remove_passive_agg'
        })

    if absolute_count >= 1:
        analysis.append({
            'id': 'tg_absolute',
            'label': 'Overgeneralization',
            'type': 'caution',
            'source': 'self',
            'text': 'Your draft uses absolute terms (' + ', '.join(absolute_matched[:3]) + '). This can make you sound inflexible and may weaken your argument.',
            'advice': 'Replace absolutes with qualified statements (e.g., "often" instead of "always").',
            'fix_type': 'qualify_absolutes'
        })

    if pressure_count >= 1:
        analysis.append({
            'id': 'tg_pressure',
            'label': 'Unnecessary Urgency',
            'type': 'caution',
            'source': 'self',
            'text': 'Your draft creates urgency (' + ', '.join(pressure_matched[:2]) + '). Unless truly time-sensitive, this may feel pushy.',
            'advice': 'Replace urgent language with clear deadlines and reasoning.',
            'fix_type': 'reduce_pressure'
        })

    if closed_count >= 1:
        analysis.append({
            'id': 'tg_closed',
            'label': 'Shutting Down Dialogue',
            'type': 'warning',
            'source': 'self',
            'text': 'Your draft may shut down discussion (' + ', '.join(closed_matched[:2]) + '). This can damage future collaboration.',
            'advice': 'Add an open-ended question or invitation for further input.',
            'fix_type': 'open_dialogue'
        })

    # Directive language
    directive_markers = {
        'en': ['you must', 'you need to', 'you should', 'i expect', 'i require',
               'make sure', 'ensure that', 'i need you to', 'do not', 'report to me'],
        'zh': ['你必须', '你需要', '你应该', '我要求', '确保', '不要', '向我汇报']
    }
    directive_count, directive_matched = count_markers(draft_text, directive_markers)
    if directive_count >= 1:
        analysis.append({
            'id': 'tg_directive',
            'label': 'Overly Directive Tone',
            'type': 'caution',
            'source': 'self',
            'text': 'Your draft uses commanding language (' + ', '.join(directive_matched[:2]) + '). This may come across as imposing, especially cross-culturally.',
            'advice': 'Reframe directives as collaborative requests or suggestions.',
            'fix_type': 'soften_directives'
        })

    # === STYLE FEEDBACK ===

    # Over-hedging
    if hedging_count >= 3:
        analysis.append({
            'id': 'tg_over_hedging',
            'label': 'Too Much Hedging',
            'type': 'nudge',
            'source': 'self',
            'text': 'Your draft hedges too much (' + ', '.join(hedging_matched[:3]) + '). This can undermine your credibility and make you seem unsure.',
            'advice': 'Remove some qualifiers. State your position more clearly.',
            'fix_type': 'reduce_hedging'
        })

    # Missing greeting/closing
    text_lower = draft_text.lower().strip()
    has_greeting = any(text_lower.startswith(g) for g in
        ['hi', 'hello', 'dear', 'hey', 'good morning', 'good afternoon',
         '您好', '你好', '尊敬的', 'hi ', 'hello '])
    has_closing = any(c in text_lower[-60:] for c in
        ['regards', 'best', 'sincerely', 'thanks', 'thank you', 'cheers',
         '此致', '敬上', '谢谢', '感谢'])

    if not has_greeting:
        analysis.append({
            'id': 'tg_no_greeting',
            'label': 'Missing Greeting',
            'type': 'nudge',
            'source': 'self',
            'text': 'Your draft starts without a greeting. Adding one creates a warmer, more professional impression.',
            'advice': 'Add a brief greeting like "Hi [Name]," or "Dear [Name],".',
            'fix_type': 'add_greeting'
        })

    if not has_closing:
        analysis.append({
            'id': 'tg_no_closing',
            'label': 'Missing Sign-off',
            'type': 'nudge',
            'source': 'self',
            'text': 'Your draft ends abruptly without a sign-off. A brief closing improves tone.',
            'advice': 'Add a closing like "Best regards," or "Thanks,".',
            'fix_type': 'add_closing'
        })

    # Word count feedback
    word_count = len(draft_text.split())
    if word_count > 300:
        analysis.append({
            'id': 'tg_too_long',
            'label': 'Email May Be Too Long',
            'type': 'nudge',
            'source': 'self',
            'text': 'Your draft is ' + str(word_count) + ' words. Long emails are often skimmed. Consider tightening.',
            'advice': 'Cut redundant sentences. Front-load the key message.',
            'fix_type': 'shorten'
        })

    # === POSITIVE SIGNALS ===
    if open_count >= 1:
        analysis.append({
            'id': 'tg_open_positive',
            'label': 'Good Collaborative Tone',
            'type': 'positive',
            'source': 'self',
            'text': 'Your draft uses open, collaborative language (' + ', '.join(open_matched[:2]) + '). This builds trust and invites dialogue.',
            'advice': 'Keep this collaborative tone throughout.'
        })

    # === FFCM Dimension check ===
    dims = score_dimensions(draft_text)
    dim_issues = []
    if dims['epistemic'] < 0.4:
        dim_issues.append('rigid certainty — consider showing openness to alternatives')
    if dims['deontic'] < 0.4:
        dim_issues.append('overly directive — consider using more inviting language')
    if dims['volitional'] < 0.4:
        dim_issues.append('passive tone — consider showing more initiative')
    if dims['doxastic'] < 0.4:
        dim_issues.append('unsupported claims — consider adding reasoning or evidence')

    if dim_issues:
        analysis.append({
            'id': 'tg_ffcm',
            'label': 'Communication Balance',
            'type': 'nudge',
            'source': 'self',
            'text': 'Areas to improve: ' + '; '.join(dim_issues) + '.',
            'advice': 'Adjust your draft to address the flagged communication patterns.',
            'fix_type': 'balance_dims'
        })

    # === Typo / Spelling Detection ===
    typo_cards = detect_typos(draft_text)
    analysis.extend(typo_cards)

    # Fallback
    if not analysis:
        analysis.append({
            'id': 'tg_clean',
            'label': 'Draft Looks Professional',
            'type': 'positive',
            'source': 'self',
            'text': 'No major tone risks detected. Your draft maintains a professional, balanced tone.',
            'advice': 'Your draft is ready to send.'
        })

    return analysis


# =============================================
# Key Point Extraction
# =============================================

def _extract_key_points(text):
    """Extract simple key points from email for reply context."""
    sentences = []
    for sep in ['. ', '? ', '! ', '.\n', '?\n', '!\n']:
        text = text.replace(sep, sep[0] + '|||')
    parts = [s.strip() for s in text.split('|||') if s.strip()]

    questions = [s for s in parts if '?' in s]
    actions = [s for s in parts if any(w in s.lower() for w in
        ['please', 'need', 'could you', 'would you', 'can you', 'let me know',
         'send', 'provide', 'update', 'confirm', 'schedule', 'arrange',
         '请', '需要', '能否', '麻烦', '确认', '安排', '发送'])]

    return questions[:3], actions[:3]


# =============================================
# Reply Generation (Mode 1: Reply to Email)
# =============================================

def generate_email_replies(email_content, selected_advice_ids=None, user_name=None, custom_context=None):
    """
    Main entry point. Analyzes email and generates 3 reply options.
    When selected_advice_ids is provided, replies are significantly
    restructured to incorporate the selected advice.

    user_name: the logged-in user's display name (for sign-offs)
    custom_context: user-provided details (times, places, etc.) to embed in replies
    """
    analysis = analyze_email(email_content)
    questions, actions = _extract_key_points(email_content)

    # Detect language
    chinese_chars = sum(1 for c in email_content if '\u4e00' <= c <= '\u9fff')
    is_chinese = chinese_chars > len(email_content) * 0.15

    # Extract sender name from email signature
    sender_name = extract_sender_name(email_content)

    # Determine the situation
    conflict_count, _ = count_markers(email_content, CONFLICT_MARKERS)
    pressure_count, _ = count_markers(email_content, PRESSURE_MARKERS)
    is_tense = conflict_count >= 1 or pressure_count >= 1

    # Build advice context from selected cards
    advice_context = _build_advice_context(analysis, selected_advice_ids)

    # Inject user's custom context text
    if custom_context:
        advice_context['user_context_text'] = custom_context.strip()
        advice_context['add_context'] = True

    # Name context for greetings/closings
    names = {
        'sender': sender_name,
        'user': user_name,
    }

    if is_chinese:
        replies = _generate_chinese_replies(email_content, questions, actions, is_tense, advice_context, names)
    else:
        replies = _generate_english_replies(email_content, questions, actions, is_tense, advice_context, names)

    # Strip _debug_scores from analysis unless debug mode
    clean_analysis = []
    for card in analysis:
        c = dict(card)
        debug_scores = c.pop('_debug_scores', None)
        if debug_scores:
            c['_debug_scores'] = debug_scores  # keep but frontend decides visibility
        clean_analysis.append(c)

    return {
        'analysis': clean_analysis,
        'replies': replies,
        'applied_advice': selected_advice_ids or [],
        'detected_sender': sender_name
    }


def _build_advice_context(analysis, selected_ids):
    """Build a context dict from selected advice cards to modify reply generation."""
    if not selected_ids:
        return {}

    context = {
        'de_escalate': False,
        'set_timeline': False,
        'use_specifics': False,
        'open_question': False,
        'assert_position': False,
        'match_collaborative': False,
        'balance_dims': False,
        'empathize_first': False,
        'match_formality': False,
        'be_casual': False,
        'answer_questions': False,
        'handle_passive_agg': False,
        'provide_clarity': False,
        'match_effort': False,
        'be_brief': False,
        'mirror_positive': False,
        # Strategy context flags
        'structured': False,
        'rapport': False,
        'next_steps': False,
        'add_context': False,
        'user_context_text': '',
    }

    for card in analysis:
        if card.get('id') in selected_ids:
            cid = card['id']
            if cid in ('conflict_high', 'conflict_mild'):
                context['de_escalate'] = True
            elif cid == 'pressure':
                context['set_timeline'] = True
            elif cid == 'absolute':
                context['use_specifics'] = True
            elif cid == 'closed_stance':
                context['open_question'] = True
            elif cid == 'power_asymmetry':
                context['assert_position'] = True
            elif cid == 'collaborative':
                context['match_collaborative'] = True
            elif cid == 'ffcm_dims':
                context['balance_dims'] = True
            elif cid == 'negative_emotion':
                context['empathize_first'] = True
            elif cid == 'positive_emotion':
                context['mirror_positive'] = True
            elif cid == 'high_formality':
                context['match_formality'] = True
            elif cid == 'low_formality':
                context['be_casual'] = True
            elif cid in ('multiple_questions', 'single_question'):
                context['answer_questions'] = True
            elif cid == 'passive_aggressive':
                context['handle_passive_agg'] = True
            elif cid == 'hedging':
                context['provide_clarity'] = True
            elif cid == 'long_email':
                context['match_effort'] = True
            elif cid == 'short_email':
                context['be_brief'] = True
            # Strategy cards
            elif cid == 'strategy_structured':
                context['structured'] = True
            elif cid == 'strategy_rapport':
                context['rapport'] = True
            elif cid == 'strategy_next_steps':
                context['next_steps'] = True
            elif cid == 'strategy_add_context':
                context['add_context'] = True

    return context


def _generate_english_replies(email_content, questions, actions, is_tense, advice_context=None, names=None):
    """Generate 3 English reply options, substantially adjusted by selected advice."""
    replies = []
    ctx = advice_context or {}
    has_advice = any(ctx.values())
    names = names or {}
    sender = names.get('sender')
    user = names.get('user')
    # Build greeting and sign-off with real names
    greeting_name = sender if sender else '[Name]'
    signoff_name = ('\n' + user) if user else ''

    # Build question responses
    q_response = ''
    if questions and ctx.get('answer_questions'):
        # Structured question answering
        q_response = '\n\n'
        for i, q in enumerate(questions, 1):
            q_short = q.strip()[:80]
            q_response += str(i) + '. Regarding "' + q_short + '..." — [your answer here]\n'
    elif questions:
        q_response = '\n\nRegarding your question'
        if len(questions) > 1:
            q_response += 's'
        q_response += ': I will look into this and get back to you with a clear answer.'

    a_response = ''
    if actions:
        a_response = '\n\nI have noted the action items and will follow up accordingly.'

    # ============================================
    # Build reply structure based on advice context
    # ============================================

    # --- FORMAL ---
    formal_parts = []

    # Opening
    if ctx.get('de_escalate'):
        formal_parts.append('Hi ' + greeting_name + ',\n\nThank you for raising this. I take your concerns seriously and want to work through this together constructively.')
    elif ctx.get('empathize_first'):
        formal_parts.append('Hi ' + greeting_name + ',\n\nThank you for sharing how you feel about this. I understand this has been a difficult situation, and I want to make sure we address it properly.')
    elif ctx.get('handle_passive_agg'):
        formal_parts.append('Hi ' + greeting_name + ',\n\nThank you for your follow-up. I want to make sure we are aligned and moving forward productively.')
    elif ctx.get('mirror_positive'):
        formal_parts.append('Hi ' + greeting_name + ',\n\nThank you so much for your kind words and positive feedback. It means a great deal.')
    elif ctx.get('match_formality'):
        formal_parts.append('Dear ' + greeting_name + ',\n\nThank you for your correspondence. I have carefully reviewed the contents and wish to respond as follows.')
    elif ctx.get('match_collaborative'):
        formal_parts.append('Hi ' + greeting_name + ',\n\nThank you for your thoughtful email and collaborative approach. I appreciate you inviting input.')
    else:
        formal_parts.append('Hi ' + greeting_name + ',\n\nThank you for your email. I appreciate you taking the time to share this.')

    # Body
    if ctx.get('de_escalate'):
        formal_parts.append('Rather than focusing on where things went wrong, I would like to propose a path forward that addresses everyone\'s concerns.')
    elif ctx.get('assert_position'):
        formal_parts.append('I appreciate the guidance. Having reviewed this matter carefully, I would like to share my professional perspective.\n\n[State your position with supporting evidence/reasoning]')
    elif ctx.get('provide_clarity'):
        formal_parts.append('To provide you with a clear direction, here is my recommendation:\n\n[Provide decisive, specific guidance]')
    elif ctx.get('match_effort'):
        formal_parts.append('I have given your detailed message the thorough consideration it deserves. Allow me to address each point:')
    elif ctx.get('be_brief'):
        formal_parts.append('Understood.')
    else:
        formal_parts.append('I have reviewed the details and would like to share my thoughts below.')

    formal_parts.append(q_response)
    formal_parts.append(a_response)

    if ctx.get('set_timeline'):
        formal_parts.append('Regarding timing: I want to handle this properly rather than rush to a suboptimal outcome. I propose the following timeline:\n- [Step 1]: by [date]\n- [Step 2]: by [date]\n- Final resolution: by [date]')

    if ctx.get('use_specifics'):
        formal_parts.append('Let me be specific rather than speak in generalities:\n- [Point 1 with data/evidence]\n- [Point 2 with data/evidence]')

    if ctx.get('open_question'):
        formal_parts.append('I value your perspective on this. Could we explore some alternative approaches together?')

    # Balance FFCM dims — adjust tone to be more balanced
    if ctx.get('balance_dims'):
        formal_parts.append('I want to ensure we approach this with both clarity and openness. While I have a perspective to share, I am equally interested in understanding yours.')

    # Strategy: rapport building
    if ctx.get('rapport'):
        formal_parts.append('I hope things are going well on your end. I always appreciate our exchanges.')

    # Strategy: user-provided context (times, locations, specifics)
    user_ctx = ctx.get('user_context_text', '')
    if user_ctx:
        formal_parts.append(user_ctx)

    # Strategy: next steps
    if ctx.get('next_steps'):
        formal_parts.append('To keep things moving, here are the next steps I propose:\n- [Action 1] — by [date]\n- [Action 2] — by [date]\nPlease let me know if this works for you.')

    # Closing
    if ctx.get('match_formality'):
        formal_parts.append('I remain at your disposal for any further discussion.\n\nRespectfully yours,' + signoff_name)
    elif ctx.get('be_brief'):
        formal_parts.append('Best regards,' + signoff_name)
    else:
        formal_parts.append('Please let me know if you would like to discuss further.\n\nBest regards,' + signoff_name)

    replies.append({
        'tone': 'Formal',
        'text': '\n\n'.join([p for p in formal_parts if p.strip()])
    })

    # --- NEUTRAL ---
    neutral_parts = []

    if ctx.get('de_escalate'):
        neutral_parts.append('Hi ' + greeting_name + ',\n\nThanks for your message. I hear you, and I think we can work this out.')
    elif ctx.get('empathize_first'):
        neutral_parts.append('Hi ' + greeting_name + ',\n\nThanks for being open about how this has been affecting you. I get it.')
    elif ctx.get('handle_passive_agg'):
        neutral_parts.append('Hi ' + greeting_name + ',\n\nGot it. Let me address the core issue directly so we can move forward.')
    elif ctx.get('mirror_positive'):
        neutral_parts.append('Hi ' + greeting_name + ',\n\nThanks so much — that really made my day!')
    elif ctx.get('be_casual'):
        neutral_parts.append('Hey ' + greeting_name + ',\n\nThanks for the heads up.')
    elif ctx.get('match_collaborative'):
        neutral_parts.append('Hi ' + greeting_name + ',\n\nThanks for sharing — great points all around.')
    else:
        neutral_parts.append('Hi ' + greeting_name + ',\n\nThanks for reaching out.')

    if ctx.get('de_escalate'):
        neutral_parts.append('Here is what I suggest: let\'s focus on the solution rather than the problem. Here\'s my take:')
    elif ctx.get('provide_clarity'):
        neutral_parts.append('Here is where I land on this:\n\n[Clear, direct recommendation]')
    elif ctx.get('be_brief'):
        neutral_parts.append('Quick thoughts:')
    else:
        neutral_parts.append('Here are my thoughts on this.')

    neutral_parts.append(q_response)
    neutral_parts.append(a_response)

    if ctx.get('set_timeline'):
        neutral_parts.append('On timing — let\'s be realistic. I can have [X] ready by [date]. Does that work?')
    if ctx.get('use_specifics'):
        neutral_parts.append('Specifically: [detail 1], [detail 2].')
    if ctx.get('open_question'):
        neutral_parts.append('What do you think would work best here?')
    if ctx.get('assert_position'):
        neutral_parts.append('That said, here is my honest take: [your position]. I think this because [reason].')
    if ctx.get('balance_dims'):
        neutral_parts.append('I want to keep this balanced — here is my view, but I am curious about yours too.')
    if ctx.get('rapport'):
        neutral_parts.append('By the way, hope everything is going well!')
    user_ctx = ctx.get('user_context_text', '')
    if user_ctx:
        neutral_parts.append(user_ctx)
    if ctx.get('next_steps'):
        neutral_parts.append('Next steps:\n- [Action 1] by [date]\n- [Action 2] by [date]\nLet me know if that works.')

    neutral_parts.append('Let me know what you think.\n\nBest,' + signoff_name)

    replies.append({
        'tone': 'Neutral',
        'text': '\n\n'.join([p for p in neutral_parts if p.strip()])
    })

    # --- EMPATHETIC ---
    empathetic_parts = []

    if ctx.get('de_escalate'):
        empathetic_parts.append('Hi ' + greeting_name + ',\n\nThank you for being direct about this — I can tell this matters a lot to you, and it matters to me too. I want us to find a way forward that feels right for both of us.')
    elif ctx.get('empathize_first'):
        empathetic_parts.append('Hi ' + greeting_name + ',\n\nI really appreciate you telling me how you feel. That takes courage, and I want you to know I take it seriously.')
    elif ctx.get('handle_passive_agg'):
        empathetic_parts.append('Hi ' + greeting_name + ',\n\nI sense some frustration in your message, and I understand — this has been a process. Let me address things head-on so we can get to a better place.')
    elif ctx.get('mirror_positive'):
        empathetic_parts.append('Hi ' + greeting_name + ',\n\nThis truly made my day — thank you for the kind words! It is wonderful to know that our collaboration is going well.')
    elif ctx.get('match_collaborative'):
        empathetic_parts.append('Hi ' + greeting_name + ',\n\nI love the collaborative direction you are taking. Let me build on that.')
    else:
        empathetic_parts.append('Hi ' + greeting_name + ',\n\nThanks so much for this — I really appreciate you keeping me in the loop.')

    if ctx.get('de_escalate'):
        empathetic_parts.append('I\'ve been thinking about this, and here is what I believe would work for everyone:')
    elif ctx.get('match_effort'):
        empathetic_parts.append('I can see the effort you put into this email, and I want to respond with equal thought:')
    else:
        empathetic_parts.append('Let me share a few thoughts.')

    empathetic_parts.append(q_response)
    empathetic_parts.append(a_response)

    if ctx.get('set_timeline'):
        empathetic_parts.append('I know timing is on your mind. How about this: I will [action] by [date], and we can check in then to see how things stand?')
    if ctx.get('use_specifics'):
        empathetic_parts.append('To be concrete about it: [specific detail 1], [specific detail 2].')
    if ctx.get('open_question'):
        empathetic_parts.append('I would genuinely love to hear your perspective on this — what feels like the right path to you?')
    if ctx.get('assert_position'):
        empathetic_parts.append('I want to be transparent about my view: I believe [position] because [reason]. But I am open to being persuaded otherwise.')
    if ctx.get('balance_dims'):
        empathetic_parts.append('I think it is important we both feel heard here. I will share my perspective, and I would love to hear yours as well.')
    if ctx.get('rapport'):
        empathetic_parts.append('On a personal note — I hope everything is going well. I really enjoy working with you.')
    user_ctx = ctx.get('user_context_text', '')
    if user_ctx:
        empathetic_parts.append(user_ctx)
    if ctx.get('next_steps'):
        empathetic_parts.append('Here is what I think we should do next:\n- [Action 1] by [date]\n- [Action 2] by [date]\nDoes this feel right to you?')

    empathetic_parts.append('I am happy to jump on a quick call if that would be easier. Thanks again.\n\nWarmly,' + signoff_name)

    replies.append({
        'tone': 'Empathetic',
        'text': '\n\n'.join([p for p in empathetic_parts if p.strip()])
    })

    return replies


def _generate_chinese_replies(email_content, questions, actions, is_tense, advice_context=None, names=None):
    """Generate 3 Chinese reply options, substantially adjusted by selected advice."""
    replies = []
    ctx = advice_context or {}
    names = names or {}
    sender = names.get('sender')
    user = names.get('user')
    greeting_name = sender if sender else '[对方姓名]'
    signoff_name = ('\n' + user) if user else ''

    q_response = ''
    if questions and ctx.get('answer_questions'):
        q_response = '\n\n'
        for i, q in enumerate(questions, 1):
            q_short = q.strip()[:40]
            q_response += str(i) + '. 关于"' + q_short + '…"——[您的回答]\n'
    elif questions:
        q_response = '\n\n关于您提到的问题，我会尽快确认后回复您。'

    a_response = ''
    if actions:
        a_response = '\n\n我已记录相关事项，会尽快跟进。'

    # --- FORMAL ---
    formal_parts = []
    if ctx.get('de_escalate'):
        formal_parts.append(greeting_name + '您好，\n\n感谢您的反馈。我非常重视您提出的问题，希望我们能一起理性地找到解决方案。')
        formal_parts.append('与其追究过去的问题，不如让我们聚焦在如何改进上。以下是我的建议：')
    elif ctx.get('empathize_first'):
        formal_parts.append(greeting_name + '您好，\n\n感谢您坦诚地表达您的感受。我理解这个情况给您带来的困扰，我会认真对待。')
        formal_parts.append('关于此事，我有以下想法：')
    elif ctx.get('assert_position'):
        formal_parts.append(greeting_name + '您好，\n\n感谢您的指导和关注。')
        formal_parts.append('经过仔细考虑，我想分享一下我的专业判断：\n\n[阐述您的立场及理由]')
    elif ctx.get('match_collaborative'):
        formal_parts.append(greeting_name + '您好，\n\n感谢您的来信和开放的合作态度。')
        formal_parts.append('在您的思路基础上，我有以下补充：')
    else:
        formal_parts.append(greeting_name + '您好，\n\n感谢您的来信。')
        formal_parts.append('我已仔细查看了相关内容，以下是我的想法。')

    formal_parts.append(q_response)
    formal_parts.append(a_response)

    if ctx.get('set_timeline'):
        formal_parts.append('关于时间安排，为确保质量，建议按以下节奏推进：\n- [步骤1]：[日期]前完成\n- [步骤2]：[日期]前完成')
    if ctx.get('use_specifics'):
        formal_parts.append('具体来说：\n- [要点1及数据支撑]\n- [要点2及数据支撑]')
    if ctx.get('open_question'):
        formal_parts.append('非常希望听听您的想法——您觉得怎样的方案最合适？')
    if ctx.get('balance_dims'):
        formal_parts.append('我希望我们能以开放和清晰的态度讨论此事。以下是我的看法，也非常期待您的意见。')
    if ctx.get('rapport'):
        formal_parts.append('希望您一切顺利。一直以来很高兴能与您共事。')
    user_ctx = ctx.get('user_context_text', '')
    if user_ctx:
        formal_parts.append(user_ctx)
    if ctx.get('next_steps'):
        formal_parts.append('建议后续步骤如下：\n- [步骤1]：[日期]前完成\n- [步骤2]：[日期]前完成\n请您确认是否可行。')

    formal_parts.append('如有需要进一步讨论，请随时告知。\n\n此致' + signoff_name)
    replies.append({'tone': 'Formal', 'text': '\n\n'.join([p for p in formal_parts if p.strip()])})

    # --- NEUTRAL ---
    neutral_parts = []
    if ctx.get('de_escalate'):
        neutral_parts.append(greeting_name + '，\n\n收到，我理解您的顾虑。让我们一起想办法解决。')
        neutral_parts.append('我的建议是：')
    elif ctx.get('empathize_first'):
        neutral_parts.append(greeting_name + '，\n\n收到。我能感受到这对您的影响，谢谢您的坦诚。')
        neutral_parts.append('简单说说我的想法：')
    elif ctx.get('handle_passive_agg'):
        neutral_parts.append(greeting_name + '，\n\n收到。让我直接说一下核心问题，这样我们能更快推进。')
    elif ctx.get('match_collaborative'):
        neutral_parts.append(greeting_name + '，\n\n收到，谢谢分享，想法很好。')
        neutral_parts.append('在此基础上，我来说说我的看法。')
    else:
        neutral_parts.append(greeting_name + '，\n\n收到，谢谢。')
        neutral_parts.append('简单说说我的想法。')

    neutral_parts.append(q_response)
    neutral_parts.append(a_response)

    if ctx.get('set_timeline'):
        neutral_parts.append('关于时间——我觉得[日期]完成比较现实，你觉得呢？')
    if ctx.get('use_specifics'):
        neutral_parts.append('具体来说：[细节1]、[细节2]。')
    if ctx.get('assert_position'):
        neutral_parts.append('说实话，我的看法是：[您的立场]。原因是[理由]。')
    if ctx.get('balance_dims'):
        neutral_parts.append('我想保持平衡——说说我的看法，也想听听你的。')
    if ctx.get('rapport'):
        neutral_parts.append('对了，希望你最近一切顺利！')
    user_ctx = ctx.get('user_context_text', '')
    if user_ctx:
        neutral_parts.append(user_ctx)
    if ctx.get('next_steps'):
        neutral_parts.append('接下来我建议：\n- [事项1] [日期]前完成\n- [事项2] [日期]前完成\n你看行不行？')
    if ctx.get('open_question'):
        neutral_parts.append('你觉得怎么样？\n\n' + (user if user else ''))
    else:
        neutral_parts.append('有想法随时沟通。\n\n' + (user if user else ''))

    replies.append({'tone': 'Neutral', 'text': '\n\n'.join([p for p in neutral_parts if p.strip()])})

    # --- EMPATHETIC ---
    empathetic_parts = []
    if ctx.get('de_escalate'):
        empathetic_parts.append(greeting_name + '，\n\n非常感谢您的坦诚——我能感受到这件事对您的重要性，我同样很重视。希望我们能一起找到双方都满意的方案。')
        empathetic_parts.append('我仔细想了想，觉得这样或许可行：')
    elif ctx.get('empathize_first'):
        empathetic_parts.append(greeting_name + '，\n\n谢谢您告诉我您的感受。我完全理解，这确实不容易。')
        empathetic_parts.append('让我来分享一些想法，看看怎么能改善这个情况：')
    elif ctx.get('mirror_positive'):
        empathetic_parts.append(greeting_name + '，\n\n太感谢您的肯定了——这让我非常开心！很高兴我们的合作进展顺利。')
    elif ctx.get('match_collaborative'):
        empathetic_parts.append(greeting_name + '，\n\n非常欣赏您开放合作的态度！在您的想法上，我有一些补充。')
    else:
        empathetic_parts.append(greeting_name + '，\n\n非常感谢您的来信，很高兴收到您的消息。')
        empathetic_parts.append('分享一些我的想法。')

    empathetic_parts.append(q_response)
    empathetic_parts.append(a_response)

    if ctx.get('set_timeline'):
        empathetic_parts.append('我知道时间很重要。这样吧——我在[日期]前完成[事项]，届时我们再碰一下？')
    if ctx.get('use_specifics'):
        empathetic_parts.append('具体来说：[细节1]、[细节2]。')
    if ctx.get('open_question'):
        empathetic_parts.append('您觉得什么方向最合适？我很想听听您的想法。')
    if ctx.get('balance_dims'):
        empathetic_parts.append('我觉得我们双方的想法都很重要。我先分享我的看法，也非常期待听到您的。')
    if ctx.get('rapport'):
        empathetic_parts.append('顺便说一句——一直很高兴能和您合作，希望您最近一切都好！')
    user_ctx = ctx.get('user_context_text', '')
    if user_ctx:
        empathetic_parts.append(user_ctx)
    if ctx.get('next_steps'):
        empathetic_parts.append('我觉得接下来可以这样：\n- [事项1] [日期]前完成\n- [事项2] [日期]前完成\n您觉得这样可以吗？')

    empathetic_parts.append('如果方便的话，我们可以约个时间聊一下。再次感谢！\n\n' + (user if user else ''))
    replies.append({'tone': 'Empathetic', 'text': '\n\n'.join([p for p in empathetic_parts if p.strip()])})

    return replies


# =============================================
# Guardian: Improve user's draft
# =============================================

def improve_draft(draft_text, selected_advice_ids=None):
    """Guardian entry point."""
    analysis = analyze_draft(draft_text)

    chinese_chars = sum(1 for c in draft_text if '\u4e00' <= c <= '\u9fff')
    is_chinese = chinese_chars > len(draft_text) * 0.15

    fixes = _build_fix_instructions(analysis, selected_advice_ids)

    # Collect typo fixes from selected advice cards
    typo_replacements = _collect_typo_fixes(analysis, selected_advice_ids)

    if is_chinese:
        improved = _improve_chinese_draft(draft_text, fixes, typo_replacements)
    else:
        improved = _improve_english_draft(draft_text, fixes, typo_replacements)

    return {
        'analysis': analysis,
        'improved_versions': improved,
        'applied_advice': selected_advice_ids or []
    }


def _build_fix_instructions(analysis, selected_ids):
    """Extract fix types from selected advice cards."""
    if not selected_ids:
        return [card.get('fix_type') for card in analysis
                if card.get('fix_type') and card.get('type') != 'positive'
                and card.get('fix_type') != 'ask_typo']  # Don't auto-apply ambiguous typos

    return [card.get('fix_type') for card in analysis
            if card.get('id') in selected_ids and card.get('fix_type')]


def _collect_typo_fixes(analysis, selected_ids):
    """Collect typo word→replacement mappings from relevant advice cards."""
    replacements = {}

    for card in analysis:
        # Auto-fix typos are applied by default (or when explicitly selected)
        if card.get('fix_type') == 'fix_typos':
            if not selected_ids or card.get('id') in selected_ids:
                typo_fixes = card.get('typo_fixes', {})
                replacements.update(typo_fixes)

        # Ambiguous typos only apply when user explicitly selects them
        if card.get('fix_type') == 'ask_typo' and selected_ids:
            if card.get('id') in selected_ids:
                typo_options = card.get('typo_options', {})
                # Use the first candidate as the fix
                for wrong, options in typo_options.items():
                    if options:
                        replacements[wrong] = options[0]

    return replacements


def _capitalize_sentences(text):
    """
    Ensure every sentence starts with a capital letter.
    Handles: . ! ? followed by space(s) and a lowercase letter.
    Also capitalizes the very first letter of the text.
    """
    if not text:
        return text

    # Capitalize first character of text
    result = list(text)
    # Find first alpha character and capitalize it
    for i, c in enumerate(result):
        if c.isalpha():
            result[i] = c.upper()
            break

    # Capitalize after sentence-ending punctuation
    i = 0
    while i < len(result):
        if result[i] in '.!?':
            # Skip past punctuation and whitespace to find next alpha char
            j = i + 1
            while j < len(result) and result[j] in ' \t':
                j += 1
            if j < len(result) and result[j].isalpha() and result[j].islower():
                result[j] = result[j].upper()
        # Also handle newline starts
        elif result[i] == '\n':
            j = i + 1
            while j < len(result) and result[j] in ' \t\n':
                j += 1
            if j < len(result) and result[j].isalpha() and result[j].islower():
                # Only capitalize if previous non-whitespace was a sentence ender
                # or this is clearly a new paragraph
                k = i - 1
                while k >= 0 and result[k] in ' \t':
                    k -= 1
                if k >= 0 and result[k] in '.!?\n':
                    result[j] = result[j].upper()
        i += 1

    return ''.join(result)


def _improve_english_draft(draft_text, fixes, typo_replacements=None):
    """Generate improved versions of English draft."""
    improved = []
    typo_replacements = typo_replacements or {}

    # Apply typo fixes to base text first
    base_text = draft_text
    if typo_replacements:
        for wrong, correct in typo_replacements.items():
            # Case-insensitive replace while preserving original case pattern
            import re as _re
            pattern = _re.compile(_re.escape(wrong), _re.IGNORECASE)
            base_text = pattern.sub(correct, base_text)

    # Version 1: Professionally Polished
    polished = base_text

    if 'soften_conflict' in fixes:
        replacements = {
            'but you': 'however, I notice that',
            'your fault': 'an area we should revisit',
            'not my problem': 'outside my current scope',
            'waste of time': 'less productive than hoped',
            'should have': 'could have',
            'fault': 'area for improvement',
            'blame': 'responsibility',
            'stupid': 'unclear',
            'ridiculous': 'surprising',
            'impossible': 'challenging',
        }
        for old, new in replacements.items():
            polished = polished.replace(old, new)
            polished = polished.replace(old.capitalize(), new.capitalize())

    if 'remove_passive_agg' in fixes:
        replacements = {
            'as i mentioned': 'to clarify',
            'per my last email': 'following up on our conversation',
            'as previously stated': 'to reiterate',
            'i already told you': 'as we discussed',
            'as you should know': 'for reference',
            'just to be clear': 'to make sure we are aligned',
            'with all due respect': 'I want to share a different perspective',
            'no offense but': 'I want to be transparent:',
            'once again': 'to follow up',
        }
        for old, new in replacements.items():
            polished = polished.replace(old, new)
            polished = polished.replace(old.capitalize(), new.capitalize())

    if 'qualify_absolutes' in fixes:
        replacements = {
            'always': 'often',
            'never': 'rarely',
            'everyone': 'many people',
            'nobody': 'few people',
            'it is obviously': 'it appears',
            'it\'s obviously': 'it appears',
            'obviously ': 'apparently ',
            'definitely': 'likely',
            'absolutely': 'strongly',
        }
        for old, new in replacements.items():
            polished = polished.replace(old, new)
            polished = polished.replace(old.capitalize(), new.capitalize())

    if 'soften_directives' in fixes:
        replacements = {
            'you must': 'would you consider',
            'you need to': 'it would help if you could',
            'you should': 'you might want to',
            'i expect': 'I would appreciate',
            'i require': 'it would be helpful to have',
            'make sure': 'it would be great to',
            'do not': 'it may be better to avoid',
            'i need you to': 'could you please',
        }
        for old, new in replacements.items():
            polished = polished.replace(old, new)
            polished = polished.replace(old.capitalize(), new.capitalize())

    if 'reduce_pressure' in fixes:
        replacements = {
            'asap': 'at your earliest convenience',
            'urgent': 'important',
            'immediately': 'as soon as feasible',
            'right now': 'when you have a moment',
            'hurry': 'prioritize',
        }
        for old, new in replacements.items():
            polished = polished.replace(old, new)
            polished = polished.replace(old.upper(), new.capitalize())

    if 'open_dialogue' in fixes:
        if not any(q in polished for q in ['?', 'what do you think', 'how do you feel']):
            polished += '\n\nI would love to hear your thoughts on this.'

    if 'reduce_hedging' in fixes:
        replacements = {
            'i think maybe': 'I recommend',
            'perhaps we could possibly': 'I suggest we',
            'it might be that': 'I believe',
            'i was wondering if maybe': 'I would like to',
        }
        for old, new in replacements.items():
            polished = polished.replace(old, new)

    if 'add_greeting' in fixes:
        if not any(polished.lower().startswith(g) for g in ['hi', 'hello', 'dear', 'hey', 'good']):
            polished = 'Hi [Name],\n\n' + polished

    if 'add_closing' in fixes:
        if not any(c in polished.lower()[-60:] for c in ['regards', 'best', 'sincerely', 'thanks', 'cheers']):
            polished = polished.rstrip() + '\n\nBest regards'

    polished = _capitalize_sentences(polished)
    improved.append({
        'tone': 'Polished',
        'text': polished,
        'description': 'Your draft with risky phrasing softened and tone improved.'
    })

    # Version 2: More Diplomatic
    diplomatic = base_text
    # Apply all text replacements from polished
    if 'soften_conflict' in fixes or 'soften_directives' in fixes or 'qualify_absolutes' in fixes or 'remove_passive_agg' in fixes:
        diplomatic = polished  # Start from polished version
        # Add diplomatic framing
        lines = diplomatic.split('\n')
        # Insert empathy after greeting
        insert_pos = 1 if lines[0].lower().startswith(('hi', 'hello', 'dear', 'hey')) else 0
        diplomatic_opener = 'I value our working relationship and want to make sure we stay aligned on this.'
        lines.insert(insert_pos, '\n' + diplomatic_opener + '\n')
        diplomatic = '\n'.join(lines)

        if not diplomatic.rstrip().endswith('?'):
            diplomatic = diplomatic.rstrip() + '\n\nWould you be open to discussing this further?'

    diplomatic = _capitalize_sentences(diplomatic)
    improved.append({
        'tone': 'Diplomatic',
        'text': diplomatic,
        'description': 'A more diplomatic version that prioritizes relationship preservation.'
    })

    # Version 3: Confident
    confident = base_text
    if 'reduce_hedging' in fixes:
        replacements = {
            'perhaps': '',
            'maybe': '',
            'i think': 'I recommend',
            'possibly': '',
            'might': 'will',
            'i believe': 'I am confident that',
        }
        for old, new in replacements.items():
            confident = confident.replace(old, new)
            confident = confident.replace(old.capitalize(), new.capitalize() if new else '')
        confident = ' '.join(confident.split())  # Clean up extra spaces

    if 'reduce_pressure' in fixes:
        replacements = {
            'asap': 'at your earliest convenience',
            'urgent': 'important',
            'immediately': 'as soon as feasible',
            'right now': 'when you have a moment',
        }
        for old, new in replacements.items():
            confident = confident.replace(old, new)
            confident = confident.replace(old.upper(), new.capitalize())

    if 'add_greeting' in fixes:
        if not any(confident.lower().startswith(g) for g in ['hi', 'hello', 'dear', 'hey', 'good']):
            confident = 'Hi [Name],\n\n' + confident

    if 'add_closing' in fixes:
        if not any(c in confident.lower()[-60:] for c in ['regards', 'best', 'sincerely', 'thanks', 'cheers']):
            confident = confident.rstrip() + '\n\nBest regards'

    confident = _capitalize_sentences(confident)
    improved.append({
        'tone': 'Confident',
        'text': confident,
        'description': 'Your draft with a clear, confident but not aggressive tone.'
    })

    return improved


def _improve_chinese_draft(draft_text, fixes, typo_replacements=None):
    """Generate improved versions of Chinese draft."""
    improved = []
    typo_replacements = typo_replacements or {}

    # Apply typo fixes to base text first
    base_text = draft_text
    if typo_replacements:
        for wrong, correct in typo_replacements.items():
            base_text = base_text.replace(wrong, correct)

    # Version 1: Polished
    polished = base_text
    if 'soften_conflict' in fixes:
        replacements = {
            '你错了': '这个地方可能需要再确认一下',
            '不可能': '这个方案有些挑战',
            '废话': '这个角度可以再考虑',
            '浪费时间': '效率可能还可以提升',
            '凭什么': '请问依据是什么',
            '没用': '效果可能需要调整',
            '别管': '让我们先聚焦在',
        }
        for old, new in replacements.items():
            polished = polished.replace(old, new)

    if 'remove_passive_agg' in fixes:
        replacements = {
            '我之前说过': '补充说明一下',
            '上次已经说了': '再确认一下',
            '再说一遍': '重新梳理一下',
            '你应该知道': '供参考',
            '不是说过了吗': '让我再解释一下',
            '恕我直言': '坦诚地说',
        }
        for old, new in replacements.items():
            polished = polished.replace(old, new)

    if 'qualify_absolutes' in fixes:
        replacements = {
            '总是': '经常', '从来不': '很少', '从来': '很少',
            '所有人': '大部分人', '没有人': '很少有人',
            '肯定': '很可能', '明显': '看起来', '当然': '通常来说',
        }
        for old, new in replacements.items():
            polished = polished.replace(old, new)

    if 'soften_directives' in fixes:
        replacements = {
            '你必须': '建议您可以', '你需要': '希望您能',
            '你应该': '您可以考虑', '我要求': '我希望', '不要': '建议避免',
        }
        for old, new in replacements.items():
            polished = polished.replace(old, new)

    if 'reduce_pressure' in fixes:
        replacements = {
            '紧急': '重要', '马上': '尽快', '立刻': '在方便的时候',
            '快点': '请优先处理', '赶紧': '烦请尽快',
        }
        for old, new in replacements.items():
            polished = polished.replace(old, new)

    if 'add_greeting' in fixes:
        if not any(polished.startswith(g) for g in ['您好', '你好', '尊敬的', 'Hi', 'Hello']):
            polished = '您好，\n\n' + polished

    if 'add_closing' in fixes:
        if not any(c in polished[-20:] for c in ['此致', '敬上', '谢谢', '感谢', '顺祝']):
            polished = polished.rstrip() + '\n\n谢谢'

    if 'open_dialogue' in fixes:
        if '？' not in polished[-30:] and '?' not in polished[-30:]:
            polished += '\n\n不知道您对此有什么想法？'

    improved.append({
        'tone': 'Polished',
        'text': polished,
        'description': '优化了措辞和语气，更加专业得体。'
    })

    # Version 2: Diplomatic
    diplomatic = polished  # Start from polished
    if any(f in fixes for f in ['soften_conflict', 'soften_directives', 'remove_passive_agg']):
        lines = diplomatic.split('\n')
        insert_pos = 1 if any(lines[0].startswith(g) for g in ['您好', '你好', '尊敬的']) else 0
        lines.insert(insert_pos, '\n我很珍惜我们的合作关系，希望能在这个问题上达成共识。\n')
        diplomatic = '\n'.join(lines)

        if '？' not in diplomatic[-30:]:
            diplomatic += '\n\n您觉得这样的方向可以吗？'

    improved.append({
        'tone': 'Diplomatic',
        'text': diplomatic,
        'description': '更加外交化的版本，注重维护关系。'
    })

    # Version 3: Confident
    confident = base_text
    if 'reduce_hedging' in fixes:
        replacements = {
            '也许': '', '可能': '', '或许': '',
            '我觉得': '我认为', '似乎': '', '看起来': '',
        }
        for old, new in replacements.items():
            confident = confident.replace(old, new)
        confident = ''.join(confident.split('  '))

    if 'reduce_pressure' in fixes:
        replacements = {'紧急': '重要', '马上': '尽快', '立刻': '在方便的时候'}
        for old, new in replacements.items():
            confident = confident.replace(old, new)

    if 'add_greeting' in fixes:
        if not any(confident.startswith(g) for g in ['您好', '你好', '尊敬的']):
            confident = '您好，\n\n' + confident

    if 'add_closing' in fixes:
        if not any(c in confident[-20:] for c in ['此致', '敬上', '谢谢', '感谢']):
            confident = confident.rstrip() + '\n\n谢谢'

    improved.append({
        'tone': 'Confident',
        'text': confident,
        'description': '清晰自信但不具攻击性的版本。'
    })

    return improved
