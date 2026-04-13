"""
OIO Suggestion Card Content - Dimension-aware
"""

WELCOME = {'label': 'OIO Ready', 'type': 'info', 'source': 'both', 'text': 'Start chatting - OIO will analyze the communication dynamics and provide real-time guidance.'}

EPISTEMIC_LOW_SELF = {'label': 'Rigid Certainty Detected', 'type': 'nudge', 'source': 'self', 'text': "Your language leaves little room for alternatives. Try hedging: \"It seems like...\" or \"One possibility is...\" to invite dialogue."}
EPISTEMIC_LOW_OTHER = {'label': 'Sender Shows Rigid Certainty', 'type': 'caution', 'source': 'other', 'text': "They are presenting their view as the only truth. Respond with specifics: \"Based on what I've seen...\""}
EPISTEMIC_HIGH = {'label': 'Good Openness', 'type': 'positive', 'source': 'both', 'text': 'The conversation is exploratory - both sides are open to possibilities. Build on this with concrete proposals.'}

DEONTIC_LOW_SELF = {'label': 'Directive Tone', 'type': 'nudge', 'source': 'self', 'text': 'Your language sounds obligating. Try reframing as invitations: "Would you consider..." or "How about we..."'}
DEONTIC_LOW_OTHER = {'label': 'Power Pressure From Sender', 'type': 'warning', 'source': 'other', 'text': 'The other person is using directive language. Acknowledge their request, then state your position: "I understand. From my perspective..."'}
DEONTIC_HIGH = {'label': 'Collaborative Space', 'type': 'positive', 'source': 'both', 'text': 'The communication feels permissive and inviting - good conditions for brainstorming. Propose options.'}

VOLITIONAL_LOW_SELF = {'label': 'Take More Initiative', 'type': 'nudge', 'source': 'self', 'text': "You seem to be reacting rather than initiating. Try: \"I'll take care of [X]\" or \"Let me suggest...\""}
VOLITIONAL_LOW_OTHER = {'label': 'Other Party Is Passive', 'type': 'info', 'source': 'other', 'text': 'The other person seems to be going along without asserting preferences. Ask: "What would work best for you?"'}
VOLITIONAL_HIGH = {'label': 'Strong Initiative', 'type': 'positive', 'source': 'self', 'text': 'You are actively driving the conversation with self-initiated proposals - this builds trust.'}

DOXASTIC_LOW_SELF = {'label': 'Check Your Assumptions', 'type': 'nudge', 'source': 'self', 'text': 'Your statements may rest on unquestioned assumptions. Try: "Based on [evidence]..." or "I think this because..."'}
DOXASTIC_LOW_OTHER = {'label': 'Ungrounded Claims', 'type': 'caution', 'source': 'other', 'text': 'The other person is making claims without clear justification. Ask: "Could you share what led you to that conclusion?"'}

CONFLICT_ESCALATION = {'label': 'Escalation Risk', 'type': 'warning', 'source': 'both', 'text': "Low epistemic openness combined with directive language - this often leads to escalation. Try: \"Let's step back and look at this from both angles.\""}
POWER_IMBALANCE = {'label': 'Power Dynamics at Play', 'type': 'caution', 'source': 'both', 'text': 'One side is directing while the other is compliant. Assert your view: "I see it differently because..." or invite input: "What do you think?"'}
HEALTHY_DIALOGUE = {'label': 'Healthy Communication', 'type': 'positive', 'source': 'both', 'text': 'High openness and balanced autonomy - this is constructive dialogue. Keep building on shared understanding.'}
QUESTION_REPLY = {'label': 'They Asked a Question', 'type': 'reply', 'source': 'self', 'text': 'A question was asked. Acknowledge their point before sharing your view: "Good question. I think..."'}
PRESSURE = {'label': 'Urgency Detected', 'type': 'warning', 'source': 'both', 'text': 'Rushed language detected. Quick decisions under pressure often lead to mistakes. Set a realistic timeline.'}

def get_fallback(msg_count, dim_summary=None):
    text = f'{msg_count} messages analyzed - conversation appears balanced.'
    if dim_summary:
        text += f' Avg openness: {dim_summary}.'
    return {'label': 'Conversation Overview', 'type': 'info', 'source': 'both', 'text': text}
