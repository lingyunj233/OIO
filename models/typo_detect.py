"""
Typo & Spelling Detection Module
=================================
Detects spelling errors and typos in both English and Chinese emails.

For English: uses pyspellchecker + custom word list
For Chinese: uses a curated dictionary of common typos, homophones,
             and frequently confused characters.

When a correction is ambiguous (multiple candidates), the system
generates an interactive advice card asking the user to choose.
"""

import re

# =============================================
# English Spell Checking
# =============================================

try:
    from spellchecker import SpellChecker
    _spellchecker = SpellChecker()
    # Add common proper nouns / tech terms so they don't flag
    _spellchecker.word_frequency.load_words([
        'api', 'apis', 'url', 'urls', 'html', 'css', 'js', 'json', 'xml',
        'http', 'https', 'smtp', 'imap', 'pdf', 'csv', 'xlsx', 'pptx', 'docx',
        'gmail', 'outlook', 'linkedin', 'facebook', 'instagram', 'twitter',
        'wifi', 'bluetooth', 'ios', 'android', 'macos', 'linux', 'ubuntu',
        'async', 'frontend', 'backend', 'fullstack', 'devops', 'signup', 'login',
        'username', 'email', 'timestamp', 'timezone', 'dataset', 'workflow',
        'onboarding', 'offboarding', 'startup', 'ecommerce', 'fintech',
        'ok', 'btw', 'fyi', 'asap', 'rsvp', 'etc', 'e.g', 'i.e',
        'gonna', 'wanna', 'gotta',  # informal but not typos
        'cc', 'bcc', 'fwd', 're',   # email terms
        'hi', 'hey', 'haha', 'hmm', 'lol', 'omg',
    ])
    HAS_SPELLCHECKER = True
except ImportError:
    HAS_SPELLCHECKER = False


# =============================================
# Chinese Common Typos / Confused Characters
# =============================================

# Format: { wrong_char_or_phrase: [correct_option_1, correct_option_2, ...] }
# If only 1 option → auto-correct suggestion
# If 2+ options → ask user to choose

CHINESE_TYPO_MAP = {
    # Homophones (同音字混淆)
    '的得': ['的', '得'],          # structural particle confusion
    '在再': ['在', '再'],          # zai confusion
    '做作': ['做', '作'],          # zuo confusion
    '那哪': ['那', '哪'],          # na confusion

    # Common single-char errors
    '以经': ['已经'],
    '在见': ['再见'],
    '在次': ['再次'],
    '在三': ['再三'],
    '在也': ['再也'],
    '因该': ['应该'],
    '应为': ['因为'],
    '以后': [],  # valid, skip
    '做为': ['作为'],
    '座位': [],  # valid, skip
    '必需': [],  # valid (必需品), but often confused with 必须
    '以为': [],  # valid, skip
    '在线': [],  # valid, skip

    # Common phrase-level errors
    '迫不急待': ['迫不及待'],
    '按装': ['安装'],
    '按排': ['安排'],
    '报复': [],  # valid, skip (revenge)
    '抱歉': [],  # valid
    '走头无路': ['走投无路'],
    '名符其实': ['名副其实'],
    '一愁莫展': ['一筹莫展'],
    '穿流不息': ['川流不息'],
    '甘败下风': ['甘拜下风'],
    '默守成规': ['墨守成规'],
    '一如继往': ['一如既往'],
    '再接再励': ['再接再厉'],
    '珠连壁合': ['珠联璧合'],
    '草管人命': ['草菅人命'],
    '豆付': ['豆腐'],
    '幅射': ['辐射'],
    '反应': [],  # valid (reaction), often confused with 反映 (reflect)

    # Common 的/地/得 confusion patterns
    # These are detected by context rules below, not by simple lookup
}

# Patterns for 的/地/得 misuse detection
# 的 → before nouns (adjective + 的 + noun)
# 地 → before verbs (adverb + 地 + verb)
# 得 → after verbs (verb + 得 + complement)

DE_PATTERNS = {
    # adverb + 的 + verb → should be 地
    'adv_de_verb': [
        (r'(快速|慢慢|安静|仔细|认真|努力|积极|消极|悄悄|渐渐|轻轻|狠狠|深深|高高|远远|偷偷|默默)的(\w)', 'de_to_di'),
    ],
    # verb + 的 + complement → should be 得
    'verb_de_comp': [
        (r'(跑|走|说|做|写|看|听|吃|喝|睡|想|学|玩|飞|唱|跳|笑|哭)的(很|非常|特别|太|不|好|快|慢|多|少|高|低|大|远)', 'de_to_de2'),
    ],
}


def _edit_distance(a, b):
    """Simple Levenshtein edit distance."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]


def _detect_english_typos(text):
    """
    Detect English spelling errors.
    Returns list of dicts: { word, position, candidates, is_ambiguous }

    Ambiguity is determined by edit distance: if the best candidate is
    clearly closer than the second, it's treated as a clear fix.
    Only truly ambiguous cases (two candidates with the same edit distance)
    are flagged for user choice.
    """
    if not HAS_SPELLCHECKER:
        return []

    results = []

    word_pattern = re.compile(r"[a-zA-Z']+")

    for match in word_pattern.finditer(text):
        word = match.group()
        pos = match.start()

        # Skip very short words, ALL CAPS acronyms
        if len(word) <= 2:
            continue
        if word.isupper() and len(word) <= 6:
            continue
        # Skip words that start with uppercase mid-sentence (likely proper nouns)
        if word[0].isupper() and pos > 0 and text[pos - 1] not in '.!?\n':
            continue

        word_lower = word.lower()

        if word_lower in _spellchecker:
            continue

        unknown = _spellchecker.unknown([word_lower])
        if not unknown:
            continue

        candidates = list(_spellchecker.candidates(word_lower) or [])
        candidates = [c for c in candidates if c != word_lower]

        if not candidates:
            continue

        # Sort candidates by edit distance, then by word frequency
        candidates.sort(key=lambda c: (
            _edit_distance(word_lower, c),
            -(_spellchecker.word_usage_frequency(c) or 0)
        ))

        # Also check the spellchecker's own best guess
        correction = _spellchecker.correction(word_lower)
        if correction and correction != word_lower:
            if correction in candidates:
                candidates.remove(correction)
            candidates.insert(0, correction)

        candidates = candidates[:5]

        # Determine ambiguity: only ambiguous if top 2 candidates have
        # the SAME edit distance (truly confusable)
        is_ambiguous = False
        if len(candidates) >= 2:
            d1 = _edit_distance(word_lower, candidates[0])
            d2 = _edit_distance(word_lower, candidates[1])
            is_ambiguous = (d1 == d2)

        results.append({
            'word': word,
            'position': pos,
            'candidates': candidates,
            'is_ambiguous': is_ambiguous,
        })

    return results


def _detect_chinese_typos(text):
    """
    Detect Chinese typos and commonly confused characters.
    Returns list of dicts: { word, position, candidates, is_ambiguous, rule }
    """
    results = []

    # Check phrase-level typos
    for wrong, corrections in CHINESE_TYPO_MAP.items():
        if not corrections:  # skip valid phrases
            continue
        idx = text.find(wrong)
        while idx != -1:
            results.append({
                'word': wrong,
                'position': idx,
                'candidates': corrections,
                'is_ambiguous': len(corrections) > 1,
                'rule': 'common_typo',
            })
            idx = text.find(wrong, idx + len(wrong))

    # Check 的/地/得 misuse
    for rule_name, patterns in DE_PATTERNS.items():
        for pattern, fix_type in patterns:
            for m in re.finditer(pattern, text):
                wrong_de = '的'
                correct_de = '地' if fix_type == 'de_to_di' else '得'
                context = m.group()
                results.append({
                    'word': context,
                    'position': m.start(),
                    'candidates': [context.replace('的', correct_de)],
                    'is_ambiguous': False,
                    'rule': 'de_confusion',
                    'explanation': f'此处「的」应为「{correct_de}」',
                })

    return results


def detect_typos(text):
    """
    Main entry point. Detects typos in mixed English/Chinese text.
    Returns structured analysis cards for the advice sidebar.
    """
    if not text or not text.strip():
        return []

    # Detect language mix
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total_alpha = sum(1 for c in text if c.isalpha())
    is_mostly_chinese = chinese_chars > total_alpha * 0.3 if total_alpha > 0 else chinese_chars > 0

    en_typos = _detect_english_typos(text)
    zh_typos = _detect_chinese_typos(text) if is_mostly_chinese or chinese_chars > 0 else []

    cards = []

    # === Build advice cards for English typos ===
    # Group clear fixes vs ambiguous ones
    clear_en = [t for t in en_typos if not t['is_ambiguous']]
    ambig_en = [t for t in en_typos if t['is_ambiguous']]

    if clear_en:
        fix_list = ', '.join([
            f'"{t["word"]}" → "{t["candidates"][0]}"' for t in clear_en[:6]
        ])
        cards.append({
            'id': 'typo_en_auto',
            'label': f'Spelling Error{"s" if len(clear_en) > 1 else ""} ({len(clear_en)})',
            'type': 'warning',
            'source': 'self',
            'text': f'Found likely typo{"s" if len(clear_en) > 1 else ""}: {fix_list}',
            'advice': 'Apply the suggested corrections to fix spelling errors.',
            'fix_type': 'fix_typos',
            'typo_fixes': {t['word']: t['candidates'][0] for t in clear_en},
        })

    for t in ambig_en:
        options = ' / '.join([f'"{c}"' for c in t['candidates'][:4]])
        cards.append({
            'id': f'typo_en_ambig_{t["position"]}',
            'label': f'Unclear Spelling: "{t["word"]}"',
            'type': 'nudge',
            'source': 'self',
            'text': f'"{t["word"]}" doesn\'t look right. Did you mean: {options}?',
            'advice': f'Choose the correct spelling for "{t["word"]}".',
            'fix_type': 'ask_typo',
            'typo_options': {t['word']: t['candidates'][:4]},
        })

    # === Build advice cards for Chinese typos ===
    clear_zh = [t for t in zh_typos if not t['is_ambiguous']]
    ambig_zh = [t for t in zh_typos if t['is_ambiguous']]

    if clear_zh:
        fix_list = ', '.join([
            f'"{t["word"]}" → "{t["candidates"][0]}"' for t in clear_zh[:6]
        ])
        explanation = ''
        de_fixes = [t for t in clear_zh if t.get('rule') == 'de_confusion']
        if de_fixes:
            explanation = ' (' + '; '.join([t.get('explanation', '') for t in de_fixes if t.get('explanation')]) + ')'

        cards.append({
            'id': 'typo_zh_auto',
            'label': f'错别字检测 ({len(clear_zh)}处)',
            'type': 'warning',
            'source': 'self',
            'text': f'发现可能的错别字：{fix_list}{explanation}',
            'advice': '建议修正上述错别字。',
            'fix_type': 'fix_typos',
            'typo_fixes': {t['word']: t['candidates'][0] for t in clear_zh},
        })

    for t in ambig_zh:
        options = ' / '.join([f'「{c}」' for c in t['candidates'][:4]])
        cards.append({
            'id': f'typo_zh_ambig_{t["position"]}',
            'label': f'用字确认：「{t["word"]}」',
            'type': 'nudge',
            'source': 'self',
            'text': f'「{t["word"]}」可能有误。您是想说：{options}？',
            'advice': f'请确认「{t["word"]}」的正确写法。',
            'fix_type': 'ask_typo',
            'typo_options': {t['word']: t['candidates'][:4]},
        })

    return cards
