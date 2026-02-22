from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any, Dict, List, Set, Tuple

import numpy as np
import pandas as pd
from pm4py import read_ocel2_json, write_ocel2_json
from pm4py.algo.discovery.dfg import algorithm as dfg_discovery
from pm4py.filtering import filter_ocel_events
from pm4py.objects.ocel.util.flattening import flatten
from pm4py.visualization.dfg import visualizer as dfg_vis


DATA_ROOT = "./Data/EVAL3-data/"
MAPPING_PATH = "./3_Comparison_instance/mappings.json"
OUT_DIR = "./Results/EVAL3-dfg-similarity/"

os.environ["PATH"] += os.pathsep + 'C:\\Program Files\\Graphviz\\bin'

# ----------------------------
# DFG extraction
# ----------------------------

def dfg_from_eventlog(event_log) -> Tuple[Set[str], Set[Tuple[str, str]], Dict[Tuple[str, str], float]]:
    """
    Binary DFG using PM4Py:
      nodes = activity labels present
      edges = directly-follows pairs present
    """
    if isinstance(event_log, pd.DataFrame):
        ts_col = "time:timestamp" if "time:timestamp" in event_log.columns else None
        if ts_col and not pd.api.types.is_datetime64_any_dtype(event_log[ts_col]):
            event_log = event_log.copy()
            event_log[ts_col] = pd.to_datetime(event_log[ts_col], errors="coerce", utc=True)

    dfg_raw = dfg_discovery.apply(event_log, variant=dfg_discovery.Variants.FREQUENCY)
    if isinstance(dfg_raw, tuple):
        dfg_raw = dfg_raw[0]

    nodes: Set[str] = set()
    edges: Set[Tuple[str, str]] = set()
    for (a, b) in dfg_raw.keys():
        aa = str(a)
        bb = str(b)
        edges.add((aa, bb))
        nodes.add(aa)
        nodes.add(bb)

    return nodes, edges, dfg_raw


# ----------------------------
# Set-based PRF1 (fixed conventions)
# ----------------------------

def prf1_from_sets(true_set: Set[Any], pred_set: Set[Any]) -> Tuple[int, int, int, float, float, float]:
    """
    Fixed conventions:
    - TP = |intersection|
    - FP = |pred - true|
    - FN = |true - pred|
    - If both sets empty -> P=R=F1=1 (perfect match of 'nothing')
    - Else: standard definitions; if denom 0 -> 0
    """
    tp = len(true_set & pred_set)
    fp = len(pred_set - true_set)
    fn = len(true_set - pred_set)

    if tp == 0 and fp == 0 and fn == 0:
        return tp, fp, fn, 1.0, 1.0, 1.0

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return tp, fp, fn, precision, recall, f1


# ----------------------------
# Mapping utilities
# ----------------------------

def map_pred_dfg_to_original_space(
    pred_nodes: Set[str],
    pred_edges: Set[Tuple[str, str]],
    pred_to_orig_evt: Dict[str, str],
) -> Tuple[Set[str], Set[Tuple[str, str]], Set[str]]:
    """
    Map predicted nodes/edges to original event type labels.
    Additional predicted event types (not found in pred_to_orig_evt) are DROPPED
    (accounted for by reporting; not penalized).
    Returns mapped nodes, mapped edges, dropped_nodes.
    """
    dropped = {n for n in pred_nodes if n not in pred_to_orig_evt}
    kept = pred_nodes - dropped

    mapped_nodes = {pred_to_orig_evt[n] for n in kept}
    mapped_edges = {
        (pred_to_orig_evt[a], pred_to_orig_evt[b])
        for (a, b) in pred_edges
        if a in pred_to_orig_evt and b in pred_to_orig_evt
    }

    return mapped_nodes, mapped_edges, dropped


def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)


def save_dfg_png(dfg: Dict[Tuple[str, str], float], event_log, path: str) -> None:
    if not dfg:
        return
    gviz = dfg_vis.apply(
        dfg,
        log=event_log,
        variant=dfg_vis.Variants.FREQUENCY,
        parameters={"format": "png"},
    )
    gviz.graph_attr["dpi"] = "300"
    dfg_vis.save(gviz, path)


def comparison_sets_creator(dataset_folder: str, extracted_relpath: str) -> None:
    # Creation of comparison folder
    comparison_folder = os.path.join(dataset_folder, "Comparison_sets/")
    textual_event_descriptions_folder = os.path.join(dataset_folder, "Textual_descriptions/Event_reports/")
    os.makedirs(comparison_folder, exist_ok=True)

    # Copy extracted logs file into comparison folder
    extracted_log_source_file = os.path.join(dataset_folder, extracted_relpath)
    if not os.path.isfile(extracted_log_source_file):
        raise FileNotFoundError(f"Extracted log not found: {extracted_log_source_file}")
    extracted_log_destination_file = os.path.join(dataset_folder, "Comparison_sets/extracted_log.json")
    shutil.copy(extracted_log_source_file, extracted_log_destination_file)
    with open(extracted_log_destination_file, 'r') as file:
        extracted_log_json = json.load(file)

    # Find event_ids that should be compared
    idxs = []
    pattern = r'OCEL_subset_event_(.+?)_textual_report\.txt'
    for filename in os.listdir(textual_event_descriptions_folder):
        match = re.match(pattern, filename)
        if match:
            # Extract the event_id and add it to the list
            event_id = match.group(1)  # Convert the extracted ID to an integer
            idxs.append(str(event_id))

    # Create subset (max_logs) of original log and copy it to the comparison folder as well
    for filename in os.listdir(dataset_folder):
        if filename.endswith(".json") or filename.endswith(".jsonocel"):
            filepath = os.path.join(dataset_folder, filename)
            ocel = read_ocel2_json(filepath)
            break

    filtered_original_log = filter_ocel_events(ocel, idxs)
    output_filepath = os.path.join(comparison_folder, "original_log.json")
    write_ocel2_json(filtered_original_log, output_filepath)
    with open(output_filepath, 'r') as file:
        original_log_json = json.load(file)

    return original_log_json, extracted_log_json


# ----------------------------
# Main evaluation
# ----------------------------

def evaluate_pair(
    orig_path: str,
    pred_path: str,
    mapping_entry: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    dataset = mapping_entry.get("dataset")
    variant = mapping_entry.get("variant")
    dataset_name = f"{dataset}_{variant}"

    obj_map: Dict[str, str] = mapping_entry.get("object_type_mapping", {}) or {}
    evt_map_orig_to_pred: Dict[str, str] = mapping_entry.get("event_type_mapping", {}) or {}

    # Load OCELs
    ocel_true = read_ocel2_json(orig_path)
    ocel_pred = read_ocel2_json(pred_path)

    true_obj_counts_series = ocel_true.objects["ocel:type"].astype(str).value_counts()
    pred_obj_counts_series = ocel_pred.objects["ocel:type"].astype(str).value_counts()

    true_obj_types = set(true_obj_counts_series.index.astype(str))
    pred_obj_types = set(pred_obj_counts_series.index.astype(str))

    obj_map = {str(k): str(v) for k, v in obj_map.items()}
    evt_map_orig_to_pred = {str(k): str(v) for k, v in evt_map_orig_to_pred.items()}
    evt_map_pred_to_orig = {v: k for k, v in evt_map_orig_to_pred.items()}

    mapped_pred_types = set(obj_map.values())
    additional_pred_types = sorted(list(pred_obj_types - mapped_pred_types))

    true_obj_counts = true_obj_counts_series.to_dict()

    metrics_rows = []

    # Aggregation containers (original object types only)
    macro_combined = []
    macro_node = []
    macro_edge = []
    weighted_combined_sum = 0.0
    weighted_node_sum = 0.0
    weighted_edge_sum = 0.0
    total_weight = 0.0

    # Evaluate per ORIGINAL object type (no penalty for additional predicted object types)
    for orig_type in sorted(true_obj_types):
        weight = float(true_obj_counts.get(orig_type, 0))
        pred_type = obj_map.get(orig_type, None)

        # Missing mapping => score 0 (penalized via macro/weighted aggregation)
        if not pred_type:
            metrics_rows.append({
                "dataset": dataset_name,
                "orig_object_type": orig_type,
                "pred_object_type": "",
                "status": "missing_object_type_mapping",
                "weight_obj_instances": int(weight),
                "n_true_nodes": 0, "n_pred_nodes_mapped": 0, "n_pred_nodes_dropped_additional": 0,
                "node_tp": 0, "node_fp": 0, "node_fn": 0, "node_precision": 0.0, "node_recall": 0.0, "node_f1": 0.0,
                "n_true_edges": 0, "n_pred_edges_mapped": 0,
                "edge_tp": 0, "edge_fp": 0, "edge_fn": 0, "edge_precision": 0.0, "edge_recall": 0.0, "edge_f1": 0.0,
                "combined_f1": 0.0
            })
            macro_combined.append(0.0); macro_node.append(0.0); macro_edge.append(0.0)
            if weight > 0:
                total_weight += weight
            continue

        # Mapped pred type missing in predicted OCEL => score 0
        if pred_type not in pred_obj_types:
            metrics_rows.append({
                "dataset": dataset_name,
                "orig_object_type": orig_type,
                "pred_object_type": pred_type,
                "status": "mapped_object_type_missing_in_pred",
                "weight_obj_instances": int(weight),
                "n_true_nodes": 0, "n_pred_nodes_mapped": 0, "n_pred_nodes_dropped_additional": 0,
                "node_tp": 0, "node_fp": 0, "node_fn": 0, "node_precision": 0.0, "node_recall": 0.0, "node_f1": 0.0,
                "n_true_edges": 0, "n_pred_edges_mapped": 0,
                "edge_tp": 0, "edge_fp": 0, "edge_fn": 0, "edge_precision": 0.0, "edge_recall": 0.0, "edge_f1": 0.0,
                "combined_f1": 0.0
            })
            macro_combined.append(0.0); macro_node.append(0.0); macro_edge.append(0.0)
            if weight > 0:
                total_weight += weight
            continue

        # Flatten
        log_true = flatten(ocel_true, orig_type)
        log_pred = flatten(ocel_pred, pred_type)

        # Build DFGs
        true_nodes, true_edges, true_dfg = dfg_from_eventlog(log_true)
        pred_nodes, pred_edges, pred_dfg = dfg_from_eventlog(log_pred)

        # Map predicted labels back to original label space; drop additional predicted event types
        mapped_pred_nodes, mapped_pred_edges, dropped_pred_nodes = map_pred_dfg_to_original_space(
            pred_nodes, pred_edges, evt_map_pred_to_orig
        )

        safe_dataset = safe_filename(dataset or "dataset")
        safe_variant = safe_filename(variant or "variant")
        safe_orig = safe_filename(orig_type)
        viz_dir = os.path.join(OUT_DIR, safe_dataset, safe_variant)
        os.makedirs(viz_dir, exist_ok=True)
        true_out = os.path.join(viz_dir, f"{safe_orig}__dfg_true.png")
        pred_out = os.path.join(viz_dir, f"{safe_orig}__dfg_pred.png")
        save_dfg_png(true_dfg, log_true, true_out)
        save_dfg_png(pred_dfg, log_pred, pred_out)

        # Node metrics
        node_tp, node_fp, node_fn, node_p, node_r, node_f1 = prf1_from_sets(true_nodes, mapped_pred_nodes)
        # Edge metrics
        edge_tp, edge_fp, edge_fn, edge_p, edge_r, edge_f1 = prf1_from_sets(true_edges, mapped_pred_edges)

        # Combined DFG similarity (fixed)
        combined_f1 = 0.5 * (node_f1 + edge_f1)

        metrics_rows.append({
            "dataset": dataset_name,
            "orig_object_type": orig_type,
            "pred_object_type": pred_type,
            "status": "matched",
            "weight_obj_instances": int(weight),
            "n_true_nodes": len(true_nodes),
            "n_pred_nodes_mapped": len(mapped_pred_nodes),
            "n_pred_nodes_dropped_additional": len(dropped_pred_nodes),
            "node_tp": node_tp, "node_fp": node_fp, "node_fn": node_fn,
            "node_precision": node_p, "node_recall": node_r, "node_f1": node_f1,
            "n_true_edges": len(true_edges),
            "n_pred_edges_mapped": len(mapped_pred_edges),
            "edge_tp": edge_tp, "edge_fp": edge_fp, "edge_fn": edge_fn,
            "edge_precision": edge_p, "edge_recall": edge_r, "edge_f1": edge_f1,
            "combined_f1": combined_f1
        })

        macro_combined.append(combined_f1)
        macro_node.append(node_f1)
        macro_edge.append(edge_f1)

        if weight > 0:
            total_weight += weight
            weighted_combined_sum += combined_f1 * weight
            weighted_node_sum += node_f1 * weight
            weighted_edge_sum += edge_f1 * weight

    macro_combined_f1 = float(np.mean(macro_combined)) if macro_combined else 0.0
    macro_node_f1 = float(np.mean(macro_node)) if macro_node else 0.0
    macro_edge_f1 = float(np.mean(macro_edge)) if macro_edge else 0.0

    weighted_combined_f1 = float(weighted_combined_sum / total_weight) if total_weight > 0 else 0.0
    weighted_node_f1 = float(weighted_node_sum / total_weight) if total_weight > 0 else 0.0
    weighted_edge_f1 = float(weighted_edge_sum / total_weight) if total_weight > 0 else 0.0

    summary_row = {
        "dataset": dataset_name,
        "n_original_object_types": len(true_obj_types),
        "n_pred_object_types": len(pred_obj_types),
        "n_additional_pred_object_types_excluded": len(additional_pred_types),
        "macro_node_f1": macro_node_f1,
        "macro_edge_f1": macro_edge_f1,
        "macro_combined_f1": macro_combined_f1,
        "weighted_node_f1": weighted_node_f1,
        "weighted_edge_f1": weighted_edge_f1,
        "weighted_combined_f1": weighted_combined_f1,
        "total_weight_obj_instances": int(total_weight),
    }

    print(
        f"[{dataset_name}] macro_combined_f1={macro_combined_f1:.3f} "
        f"weighted_combined_f1={weighted_combined_f1:.3f} "
        f"(additional pred obj types excluded: {len(additional_pred_types)})"
    )

    return metrics_rows, summary_row


def main():    
    os.makedirs(OUT_DIR, exist_ok=True)


    with open(MAPPING_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    mappings = cfg.get("mappings")

    if not os.path.isdir(DATA_ROOT):
        raise FileNotFoundError(f"Data root not found: {DATA_ROOT}")

    all_metrics_rows: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []

    for entry in mappings:
        dataset = entry.get("dataset")
        variant = entry.get("variant")
        if not dataset:
            raise ValueError("Mapping entry missing dataset name.")

        dataset_folder = os.path.join(DATA_ROOT, str(dataset), "Test_data")
        extracted_relpath = f"Extracted_logs/{variant}-results/final_event_log.json"
        
        comparison_sets_creator(dataset_folder, extracted_relpath=extracted_relpath)

        orig_path = os.path.join(dataset_folder, "Comparison_sets", "original_log.json")
        pred_path = os.path.join(dataset_folder, "Comparison_sets", "extracted_log.json")
        if not (os.path.isfile(orig_path) and os.path.isfile(pred_path)):
            raise FileNotFoundError(
                f"Comparison set files missing for {dataset} {variant}: {orig_path}, {pred_path}"
            )

        metrics_rows, summary_row = evaluate_pair(orig_path, pred_path, entry)
        all_metrics_rows.extend(metrics_rows)
        summary_rows.append(summary_row)

    metrics_df = pd.DataFrame(all_metrics_rows)
    metrics_df.to_csv(os.path.join(OUT_DIR, "object_type_metrics.csv"), index=False)

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(os.path.join(OUT_DIR, "dataset_summary.csv"), index=False)


if __name__ == "__main__":
    main()
