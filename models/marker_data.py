CONFLICT_MARKERS = {
    'en': ['but you', 'wrong', 'never', 'always', 'fault', 'blame', 'stupid',
           'ridiculous', 'impossible', 'disagree', 'no way', 'hate', 'terrible',
           'waste of time', 'not my problem', 'your fault', 'should have'],
    'zh': ['你错了', '不可能', '从来不', '总是', '怪你', '废话', '浪费时间',
           '你应该', '难道', '凭什么', '不行', '没用', '别管']
}

CLOSED_STANCE_MARKERS = {
    'en': ['i don\'t care', 'whatever', 'fine', 'doesn\'t matter',
           'not interested', 'end of discussion', 'period', 'that\'s final',
           'i said no', 'no but', 'yeah but'],
    'zh': ['随便', '无所谓', '不关我事', '就这样', '不想说了', '没什么好说的',
           '算了', '我不管']
}

OPENNESS_MARKERS = {
    'en': ['what do you think', 'how about', 'maybe we could', 'i wonder',
           'let\'s try', 'another option', 'perspective', 'open to',
           'thoughts on', 'suggestion', 'consider', 'explore',
           'what if', 'how do you feel', 'i appreciate'],
    'zh': ['你觉得', '怎么样', '也许可以', '我在想', '试试看', '另一个选择',
           '你的想法', '考虑一下', '如果我们', '感谢', '欣赏']
}

INITIATIVE_MARKERS = {
    'en': ['i\'ll take care', 'let me', 'i can', 'i volunteer',
           'how can i help', 'i propose', 'why don\'t we', 'shall we',
           'i\'d like to', 'next step', 'action item', 'i\'ll do'],
    'zh': ['我来', '让我', '我可以', '我提议', '我们来', '下一步',
           '我负责', '我帮你', '我主动']
}

PRESSURE_MARKERS = {
    'en': ['asap', 'urgent', 'immediately', 'right now', 'hurry',
           'no time', 'deadline', 'pressure', 'stressed', 'overwhelmed',
           'can\'t handle', 'too much'],
    'zh': ['紧急', '马上', '立刻', '快点', '来不及', '压力', '受不了',
           '太多了', '赶紧']
}

ABSOLUTE_MARKERS = {
    'en': ['always', 'never', 'everyone', 'nobody', 'all', 'none',
           'must', 'definitely', 'absolutely', 'obviously', 'clearly'],
    'zh': ['总是', '从来', '所有人', '没有人', '一定', '肯定', '明显', '当然']
}


def count_markers(text, marker_dict):
    """Count how many markers appear in text."""
    text_lower = text.lower()
    count = 0
    matched = []
    for lang in marker_dict:
        for marker in marker_dict[lang]:
            if marker in text_lower:
                count += 1
                matched.append(marker)
    return count, matched
