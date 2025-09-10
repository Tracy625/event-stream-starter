#!/usr/bin/env python
"""
HuggingFace sentiment threshold calibration tool.

Reads golden labeled samples, runs batch predictions via HfClient,
grid searches threshold combinations, and outputs calibration reports.
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any
from pathlib import Path


def load_golden_data(filepath: str) -> Tuple[List[str], List[str], int]:
    """
    Load golden sentiment data from JSONL file.
    
    Returns:
        (texts, labels, failed_count)
    """
    texts = []
    labels = []
    failed = 0
    
    try:
        with open(filepath, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    if 'text' in data and 'label' in data:
                        label = data['label'].lower()
                        if label in ['pos', 'neu', 'neg']:
                            texts.append(data['text'])
                            labels.append(label)
                        else:
                            failed += 1
                    else:
                        failed += 1
                except json.JSONDecodeError:
                    failed += 1
                except Exception:
                    failed += 1
                    
    except FileNotFoundError:
        print(f"Error: File {filepath} not found")
        sys.exit(1)
    
    return texts, labels, failed


def compute_confusion_matrix(y_true: List[str], y_pred: List[str]) -> List[List[int]]:
    """
    Compute 3x3 confusion matrix for sentiment classification.
    
    Matrix layout: rows=actual, cols=predicted
    Order: pos, neu, neg
    """
    labels = ['pos', 'neu', 'neg']
    label_to_idx = {label: i for i, label in enumerate(labels)}
    
    matrix = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    
    for true, pred in zip(y_true, y_pred):
        true_idx = label_to_idx[true]
        pred_idx = label_to_idx[pred]
        matrix[true_idx][pred_idx] += 1
    
    return matrix


def compute_metrics(y_true: List[str], y_pred: List[str]) -> Dict[str, Any]:
    """
    Compute per-class and aggregate metrics.
    
    Returns dict with:
    - per_class: {label: {precision, recall, f1}}
    - macro_f1, macro_precision, macro_recall
    - micro_f1
    - confusion: 3x3 matrix
    """
    labels = ['pos', 'neu', 'neg']
    confusion = compute_confusion_matrix(y_true, y_pred)
    
    # Per-class metrics
    per_class = {}
    for i, label in enumerate(labels):
        tp = confusion[i][i]
        fp = sum(confusion[j][i] for j in range(3) if j != i)
        fn = sum(confusion[i][j] for j in range(3) if j != i)
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        
        per_class[label] = {
            'precision': round(precision, 4),
            'recall': round(recall, 4),
            'f1': round(f1, 4)
        }
    
    # Macro averages
    macro_precision = sum(per_class[label]['precision'] for label in labels) / 3
    macro_recall = sum(per_class[label]['recall'] for label in labels) / 3
    macro_f1 = sum(per_class[label]['f1'] for label in labels) / 3
    
    # Micro F1 (overall accuracy-based)
    total_correct = sum(confusion[i][i] for i in range(3))
    total = sum(sum(row) for row in confusion)
    micro_f1 = total_correct / total if total > 0 else 0.0
    
    return {
        'per_class': per_class,
        'macro_precision': round(macro_precision, 4),
        'macro_recall': round(macro_recall, 4),
        'macro_f1': round(macro_f1, 4),
        'micro_f1': round(micro_f1, 4),
        'confusion': confusion
    }


def compute_youden_j(metrics: Dict[str, Any]) -> float:
    """
    Compute Youden's J statistic for multi-class.
    J = (avg_sensitivity + avg_specificity) - 1
    
    For 3-class: average of per-class (recall + spec - 1)
    """
    confusion = metrics['confusion']
    labels = ['pos', 'neu', 'neg']
    
    j_values = []
    for i in range(3):
        # Sensitivity = Recall for class i
        tp = confusion[i][i]
        fn = sum(confusion[i][j] for j in range(3) if j != i)
        sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        
        # Specificity for class i (correct rejections / all negatives)
        tn = sum(confusion[j][k] for j in range(3) for k in range(3) if j != i and k != i)
        fp = sum(confusion[j][i] for j in range(3) if j != i)
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
        
        j_values.append(sensitivity + specificity - 1)
    
    return round(sum(j_values) / 3, 4)


def apply_thresholds(scores: List[float], pos_thresh: float, neg_thresh: float) -> List[str]:
    """
    Apply thresholds to scores to get predicted labels.
    
    score >= pos_thresh -> 'pos'
    score <= neg_thresh -> 'neg'
    else -> 'neu'
    """
    predictions = []
    for score in scores:
        if score >= pos_thresh:
            predictions.append('pos')
        elif score <= neg_thresh:
            predictions.append('neg')
        else:
            predictions.append('neu')
    return predictions


def grid_search(scores: List[float], true_labels: List[str]) -> List[Dict[str, Any]]:
    """
    Grid search over threshold combinations.
    
    Returns list of threshold configs with metrics, sorted by macro_f1 desc.
    """
    results = []
    
    # Define grid
    pos_thresholds = [round(0.10 + i * 0.05, 2) for i in range(9)]  # 0.10 to 0.50
    neg_thresholds = [round(-0.50 + i * 0.05, 2) for i in range(9)]  # -0.50 to -0.10
    
    for pos_thresh in pos_thresholds:
        for neg_thresh in neg_thresholds:
            # Skip extreme overlaps where pos_thresh <= -neg_thresh
            if pos_thresh <= -neg_thresh:
                continue
            
            # Apply thresholds
            predictions = apply_thresholds(scores, pos_thresh, neg_thresh)
            
            # Compute metrics
            metrics = compute_metrics(true_labels, predictions)
            youden_j = compute_youden_j(metrics)
            
            results.append({
                'pos_thresh': pos_thresh,
                'neg_thresh': neg_thresh,
                'macro_f1': metrics['macro_f1'],
                'macro_recall': metrics['macro_recall'],
                'macro_precision': metrics['macro_precision'],
                'micro_f1': metrics['micro_f1'],
                'youden_j': youden_j,
                'per_class': metrics['per_class'],
                'confusion': metrics['confusion']
            })
    
    # Sort by macro_f1 desc, then by macro_recall desc
    results.sort(key=lambda x: (-x['macro_f1'], -x['macro_recall']))
    
    return results


def main():
    """Main calibration workflow."""
    parser = argparse.ArgumentParser(description='HuggingFace sentiment threshold calibration')
    parser.add_argument('--file', type=str, default='data/golden_sentiment.jsonl',
                       help='Golden labeled data file (JSONL)')
    parser.add_argument('--report', type=str, default='reports',
                       help='Report output directory')
    parser.add_argument('--backend', type=str, default='hf', choices=['hf', 'rules'],
                       help='Backend to use for predictions')
    
    args = parser.parse_args()
    
    # Load golden data
    print(f"Loading golden data from {args.file}...")
    texts, true_labels, failed_read = load_golden_data(args.file)
    
    if not texts:
        print("Error: No valid samples found in golden data")
        sys.exit(1)
    
    print(f"Loaded {len(texts)} samples, {failed_read} failed reads")
    
    # Check minimum sample requirement
    insufficient_data = len(texts) < 100
    if insufficient_data:
        print(f"Warning: Insufficient samples ({len(texts)} < 100), results may be unreliable")
    
    # Run predictions using HfClient
    print(f"Running predictions with backend={args.backend}...")
    
    if args.backend == 'hf':
        from api.services.hf_client import HfClient
        client = HfClient(backend='local')  # Use local for stability
        results = client.predict_sentiment_batch(texts)
    else:  # rules backend
        from api.filter import analyze_sentiment
        os.environ["SENTIMENT_BACKEND"] = "rules"
        results = []
        for text in texts:
            label, score = analyze_sentiment(text)
            results.append({
                'label': label,
                'score': score,
                'probs': None
            })
    
    # Filter out degraded predictions
    valid_indices = []
    scores = []
    valid_labels = []
    pred_failed = 0
    
    for i, result in enumerate(results):
        if 'degrade' in result:
            pred_failed += 1
        else:
            valid_indices.append(i)
            # Compute score from probabilities if available
            if result.get('probs'):
                score = result['probs']['pos'] - result['probs']['neg']
            else:
                score = result['score']
            scores.append(score)
            valid_labels.append(true_labels[i])
    
    if pred_failed > 0:
        print(f"Filtered {pred_failed} degraded predictions")
    
    if not scores:
        print("Error: No valid predictions to evaluate")
        sys.exit(1)
    
    print(f"Evaluating on {len(scores)} valid samples")
    
    # Grid search for best thresholds
    print("Running grid search for optimal thresholds...")
    search_results = grid_search(scores, valid_labels)
    
    if not search_results:
        print("Error: Grid search produced no results")
        sys.exit(1)
    
    # Get best and top-k results
    best = search_results[0]
    topk = search_results[:min(5, len(search_results))]
    
    # Prepare report
    timestamp = datetime.utcnow()
    date_str = timestamp.strftime('%Y%m%d')
    
    # Get model info
    model_id = os.getenv('HF_MODEL', 'cardiffnlp/twitter-roberta-base-sentiment')
    
    report = {
        'meta': {
            'generated_at': timestamp.isoformat() + 'Z',
            'model': model_id,
            'backend': args.backend,
            'samples': len(texts),
            'failed_read': failed_read,
            'pred_failed': pred_failed,
            'insufficient_data': insufficient_data,
            'grid': {
                'pos': [round(0.10 + i * 0.05, 2) for i in range(9)],
                'neg': [round(-0.50 + i * 0.05, 2) for i in range(9)]
            }
        },
        'best': {
            'pos_thresh': best['pos_thresh'],
            'neg_thresh': best['neg_thresh'],
            'macro_f1': best['macro_f1'],
            'macro_recall': best['macro_recall'],
            'youden_j': best['youden_j'],
            'per_class': best['per_class'],
            'confusion': best['confusion']
        },
        'topk': [
            {
                'pos': r['pos_thresh'],
                'neg': r['neg_thresh'],
                'macro_f1': r['macro_f1'],
                'macro_recall': r['macro_recall'],
                'youden_j': r['youden_j']
            }
            for r in topk
        ]
    }
    
    # Create report directory if needed
    report_dir = Path(args.report)
    report_dir.mkdir(parents=True, exist_ok=True)
    
    # Write JSON report
    json_path = report_dir / f'hf_calibration_{date_str}.json'
    with open(json_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"Written JSON report to {json_path}")
    
    # Write env.patch only if sufficient data
    if not insufficient_data:
        env_path = report_dir / f'hf_calibration_{date_str}.env.patch'
        with open(env_path, 'w') as f:
            f.write(f"# Suggested thresholds from hf_calibrate ({timestamp.strftime('%Y-%m-%d')})\n")
            f.write(f"SENTIMENT_POS_THRESH={best['pos_thresh']}\n")
            f.write(f"SENTIMENT_NEG_THRESH={best['neg_thresh']}\n")
        print(f"Written env patch to {env_path}")
    
    # Print summary
    print("\n=== Calibration Summary ===")
    print(f"Samples: {len(texts)} total, {len(scores)} evaluated")
    print(f"Failed reads: {failed_read}, Degraded predictions: {pred_failed}")
    if not insufficient_data:
        print(f"Best thresholds: pos={best['pos_thresh']}, neg={best['neg_thresh']}")
        print(f"Best Macro-F1: {best['macro_f1']:.4f}")
        print(f"Per-class F1: pos={best['per_class']['pos']['f1']:.4f}, "
              f"neu={best['per_class']['neu']['f1']:.4f}, "
              f"neg={best['per_class']['neg']['f1']:.4f}")
    else:
        print("Insufficient data for reliable threshold recommendation")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())