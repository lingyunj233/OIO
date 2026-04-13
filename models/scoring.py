"""
OIO Scoring Engine
==================
Uses the fine-tuned DistilBert model (trained_model/) for 4-dimension scoring:
  LABEL_0 = Epistemic   (possibility/ability openness)
  LABEL_1 = Deontic     (permission/obligation openness)
  LABEL_2 = Volitional  (will/autonomy)
  LABEL_3 = Doxastic    (belief justification)

Falls back to keyword counting if the model is not available.
"""

import os

from models.marker_data import (
    CONFLICT_MARKERS, CLOSED_STANCE_MARKERS, OPENNESS_MARKERS,
    INITIATIVE_MARKERS, PRESSURE_MARKERS, ABSOLUTE_MARKERS,
    count_markers
)

# ===== Model Loading =====
_model = None
_tokenizer = None
_model_loaded = False
_model_attempted = False

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', 'trained_model')
if not os.path.exists(MODEL_DIR):
    # Try relative to app root
    MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'trained_model')


def _load_model():
    """Attempt to load the DistilBert model. Only tries once."""
    global _model, _tokenizer, _model_loaded, _model_attempted
    if _model_attempted:
        return _model_loaded
    _model_attempted = True

    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification

        if not os.path.exists(os.path.join(MODEL_DIR, 'config.json')):
            print(f"  [OIO] Model not found at {MODEL_DIR}, using keyword fallback")
            return False

        _tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        _model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
        _model.eval()
        _model_loaded = True
        print(f"  [OIO] DistilBert model loaded from {MODEL_DIR}")
        return True
    except ImportError:
        print("  [OIO] torch/transformers not installed, using keyword fallback")
        return False
    except Exception as e:
        print(f"  [OIO] Model load error: {e}, using keyword fallback")
        return False


def predict_dimensions(text):
    """
    Predict 4-dimension scores for a single text using the DistilBert model.

    Returns:
        dict with keys: epistemic, deontic, volitional, doxastic (each 0.0-1.0)
        or None if model is not available
    """
    if not _load_model():
        return None

    import torch

    inputs = _tokenizer(
        text,
        return_tensors='pt',
        truncation=True,
        max_length=512,
        padding=True
    )

    with torch.no_grad():
        outputs = _model(**inputs)
        scores = outputs.logits.squeeze().tolist()

    # Clamp to 0-1 range (regression model may output outside)
    if isinstance(scores, float):
        scores = [scores, 0.5, 0.5, 0.5]

    scores = [max(0.0, min(1.0, s)) for s in scores]

    return {
        'epistemic': round(scores[0], 2),
        'deontic': round(scores[1], 2),
        'volitional': round(scores[2], 2),
        'doxastic': round(scores[3], 2)
    }


def predict_dimensions_batch(sentences):
    """
    Predict 4-dimension scores for multiple sentences.

    Returns:
        list of dicts, each with keys: epistemic, deontic, volitional, doxastic
        or None if model is not available
    """
    if not _load_model() or not sentences:
        return None

    import torch

    inputs = _tokenizer(
        sentences,
        return_tensors='pt',
        truncation=True,
        max_length=512,
        padding=True
    )

    with torch.no_grad():
        outputs = _model(**inputs)
        all_scores = outputs.logits.tolist()

    results = []
    for scores in all_scores:
        scores = [max(0.0, min(1.0, s)) for s in scores]
        results.append({
            'epistemic': round(scores[0], 2),
            'deontic': round(scores[1], 2),
            'volitional': round(scores[2], 2),
            'doxastic': round(scores[3], 2)
        })
    return results


def _dimensions_to_oio(dim_scores):
    """
    Convert 4-dimension scores to OIO display scores (0-100).

    Mapping:
      Openness    = mean(epistemic, deontic) — how open to alternatives and others
      Initiative  = volitional — how self-driven vs externally driven
      Objectivity = doxastic — how evidence-based and revisable
    """
    openness = ((dim_scores['epistemic'] + dim_scores['deontic']) / 2) * 100
    initiative = dim_scores['volitional'] * 100
    objectivity = dim_scores['doxastic'] * 100

    return {
        'openness': round(openness),
        'initiative': round(initiative),
        'objectivity': round(objectivity)
    }


# ===== Main Scoring Functions =====

def score_oio(messages):
    """
    Score a set of messages on Openness, Initiative, Objectivity.
    Each score is 0-100.

    Uses DistilBert model if available, otherwise falls back to keyword counting.
    """
    if not messages:
        return {'openness': 50, 'initiative': 50, 'objectivity': 50}

    sentences = [m.get('content', '') for m in messages if m.get('content', '').strip()]
    if not sentences:
        return {'openness': 50, 'initiative': 50, 'objectivity': 50}

    # Try model-based scoring
    batch_results = predict_dimensions_batch(sentences)
    if batch_results:
        # Average across all sentences
        avg = {
            'epistemic': sum(r['epistemic'] for r in batch_results) / len(batch_results),
            'deontic': sum(r['deontic'] for r in batch_results) / len(batch_results),
            'volitional': sum(r['volitional'] for r in batch_results) / len(batch_results),
            'doxastic': sum(r['doxastic'] for r in batch_results) / len(batch_results),
        }
        return _dimensions_to_oio(avg)

    # Fallback: keyword counting
    text = ' '.join(sentences)

    open_count, _ = count_markers(text, OPENNESS_MARKERS)
    closed_count, _ = count_markers(text, CLOSED_STANCE_MARKERS)
    openness = min(100, max(0, 50 + (open_count * 12) - (closed_count * 15)))

    init_count, _ = count_markers(text, INITIATIVE_MARKERS)
    initiative = min(100, max(0, 40 + (init_count * 15)))

    conflict_count, _ = count_markers(text, CONFLICT_MARKERS)
    absolute_count, _ = count_markers(text, ABSOLUTE_MARKERS)
    objectivity = min(100, max(0, 70 - (conflict_count * 12) - (absolute_count * 8)))

    return {
        'openness': openness,
        'initiative': initiative,
        'objectivity': objectivity
    }


def score_dimensions(text):
    """
    Score a single text on the 4 FFCM dimensions.
    Returns dict with epistemic, deontic, volitional, doxastic (0.0-1.0).

    Used by email_reply and other modules that need raw dimension scores.
    """
    result = predict_dimensions(text)
    if result:
        return result

    # Fallback: rough keyword-based estimation
    open_count, _ = count_markers(text, OPENNESS_MARKERS)
    closed_count, _ = count_markers(text, CLOSED_STANCE_MARKERS)
    init_count, _ = count_markers(text, INITIATIVE_MARKERS)
    abs_count, _ = count_markers(text, ABSOLUTE_MARKERS)

    epistemic = min(1.0, max(0.0, 0.5 + (open_count * 0.1) - (abs_count * 0.12)))
    deontic = min(1.0, max(0.0, 0.5 + (open_count * 0.08) - (closed_count * 0.1)))
    volitional = min(1.0, max(0.0, 0.4 + (init_count * 0.15)))
    doxastic = min(1.0, max(0.0, 0.5 - (abs_count * 0.1)))

    return {
        'epistemic': round(epistemic, 2),
        'deontic': round(deontic, 2),
        'volitional': round(volitional, 2),
        'doxastic': round(doxastic, 2)
    }


def detect_frame(messages):
    """
    Detect the FFCM relational frame of the conversation.
    Uses model dimensions if available, otherwise keyword counting.
    """
    if not messages:
        return None

    sentences = [m.get('content', '') for m in messages[-10:] if m.get('content', '').strip()]
    if not sentences:
        return None

    # Try model-based detection
    batch_results = predict_dimensions_batch(sentences)
    if batch_results:
        avg_ep = sum(r['epistemic'] for r in batch_results) / len(batch_results)
        avg_de = sum(r['deontic'] for r in batch_results) / len(batch_results)

        # Epistemic < 0.3 = rigid truth frame, > 0.6 = flexible
        if avg_ep < 0.3:
            truth_frame = 'rigid'
        elif avg_ep < 0.6:
            truth_frame = 'moderate'
        else:
            truth_frame = 'flexible'

        # Deontic < 0.3 = competitive (obligating), > 0.6 = cooperative (permissive)
        if avg_de < 0.3:
            intention = 'competitive'
        elif avg_de < 0.6:
            intention = 'neutral'
        else:
            intention = 'cooperative'

        return {'truth_frame': truth_frame, 'intention': intention}

    # Fallback: keyword counting
    text = ' '.join(sentences)
    abs_count, _ = count_markers(text, ABSOLUTE_MARKERS)
    conflict_count, _ = count_markers(text, CONFLICT_MARKERS)
    open_count, _ = count_markers(text, OPENNESS_MARKERS)

    if abs_count >= 3:
        truth_frame = 'rigid'
    elif abs_count >= 1:
        truth_frame = 'moderate'
    else:
        truth_frame = 'flexible'

    if conflict_count > open_count:
        intention = 'competitive'
    elif open_count > conflict_count:
        intention = 'cooperative'
    else:
        intention = 'neutral'

    return {'truth_frame': truth_frame, 'intention': intention}
