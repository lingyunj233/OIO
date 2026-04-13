"""
OIO Bot Replies - Uses 4-dimension model
"""

from models.scoring import score_dimensions
from models.marker_data import CONFLICT_MARKERS, PRESSURE_MARKERS, count_markers

BASIC_REPLIES = {
    'hello': "Hello! I'm the OIO Assistant. Send me any message and I'll analyze its communication dynamics.",
    'hi': "Hi there! Send me a message and I'll show you how OIO analyzes communication patterns.",
    'help': "How to use OIO: Send any message and watch the right panel for real-time analysis. Paste a difficult email or message to get dimension scores. Switch to Email mode (top bar) to generate reply options.",
    'what is oio': "OIO analyzes communication across four FFCM dimensions: Epistemic (open vs rigid), Deontic (inviting vs directive), Volitional (self-initiated vs externally driven), Doxastic (evidence-based vs assumption-driven).",
    'thanks': "You're welcome! Keep experimenting.",
    'bye': "Goodbye! Awareness of communication dynamics is the first step to better outcomes.",
}


def get_bot_reply(message):
    msg_lower = message.lower().strip()
    for key in BASIC_REPLIES:
        if key in msg_lower:
            return BASIC_REPLIES[key]

    dims = score_dimensions(message)
    parts = []
    parts.append("Scores: Ep: %s  De: %s  Vo: %s  Dx: %s" % (dims['epistemic'], dims['deontic'], dims['volitional'], dims['doxastic']))

    insights = []
    if dims['epistemic'] < 0.35:
        insights.append('Low epistemic openness. Adding "perhaps" or "it seems" can make your point more persuasive.')
    elif dims['epistemic'] > 0.7:
        insights.append("Good epistemic openness. You're leaving room for alternatives.")
    if dims['deontic'] < 0.35:
        insights.append('Directive deontic tone. Try "would you consider..." for better results.')
    elif dims['deontic'] > 0.7:
        insights.append("Permissive and inviting language. This creates psychological safety.")
    if dims['volitional'] > 0.7:
        insights.append("Strong volitional signal. You're clearly self-initiated.")
    elif dims['volitional'] < 0.3:
        insights.append("Message feels externally driven. Consider proposing your own next step.")
    if dims['doxastic'] < 0.35:
        insights.append('Low doxastic grounding. Try "Based on [X], I think..."')

    conflict_count, matched = count_markers(message, CONFLICT_MARKERS)
    if conflict_count >= 1:
        insights.append("Conflict markers detected (%s)." % ', '.join(matched[:2]))
    pressure_count, matched = count_markers(message, PRESSURE_MARKERS)
    if pressure_count >= 1:
        insights.append("Urgency language detected (%s)." % ', '.join(matched[:2]))

    if insights:
        parts.append(' '.join(insights))
    else:
        parts.append("Balanced and neutral. No strong signals detected.")

    return '\n\n'.join(parts)
