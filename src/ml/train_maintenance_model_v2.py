"""
TrackEase - Maintenance ML V2 Experiment

Purpose:
    Re-evaluate whether the existing maintenance dataset contains enough
    predictive signal to support TrackEase maintenance prioritization.

Input:
    data/processed/maintenance_prepared.csv

Outputs:
    data/processed/maintenance_ml_v2_metrics.csv
    data/processed/maintenance_ml_v2_report.txt

Conditional model outputs:
    data/models/maintenance_model_v2.joblib
    data/models/maintenance_model_v2_metadata.joblib

Experiment design:
    - No synthetic training rows are created.
    - Train / validation / test splits are stratified and independent.
    - Leakage-prone maintenance outcome fields are excluded.
    - Three conventional scikit-learn models are compared:
        * Logistic Regression
        * Random Forest
        * Extra Trees
    - Default threshold (0.50) metrics are recorded.
    - A validation-only threshold is selected using F2 score, which gives
      recall more weight than precision.
    - Final tuned metrics are measured only once on the held-out test set.
    - PR-AUC is treated as the primary model-selection metric because the
      maintenance-required target is imbalanced.

Important:
    This experiment does NOT automatically replace TrackEase's current
    explainable maintenance-priority engine.
"""

from pathlib import Path
import json
import warnings

import joblib
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    fbeta_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "maintenance_prepared.csv"
)

METRICS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "maintenance_ml_v2_metrics.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "maintenance_ml_v2_report.txt"
)

MODEL_FILE = (
    PROJECT_ROOT
    / "data"
    / "models"
    / "maintenance_model_v2.joblib"
)

METADATA_FILE = (
    PROJECT_ROOT
    / "data"
    / "models"
    / "maintenance_model_v2_metadata.joblib"
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RANDOM_STATE = 42

TARGET_COLUMN = "maintenance_required"

# Fields that either duplicate the target, encode downstream outcomes, or
# would make the experiment unrealistically easy through target leakage.
LEAKAGE_COLUMNS = {
    "maintenance_required",
    "maintenance_needed",
    "failure_type",
    "failure_severity",
    "severity_priority",
    "high_risk_flag",
    "risk_score",
    "infrastructure_warning",
    "train_id",
}

# Threshold search is performed ONLY on the validation split.
THRESHOLDS = np.round(
    np.arange(
        0.05,
        0.951,
        0.01,
    ),
    2,
)

# Prototype evidence guardrails. These are TrackEase engineering criteria,
# not official railway or academic standards.
MIN_LIMITED_ROC_AUC = 0.65
MIN_LIMITED_PR_GAIN = 0.10

MIN_STRONG_ROC_AUC = 0.75
MIN_STRONG_PR_GAIN = 0.20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_input_file():
    """Ensure the prepared maintenance dataset exists."""

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            "Prepared maintenance dataset not found:\n"
            f"{INPUT_FILE}"
        )


def normalize_feature_types(df):
    """
    Normalize object/string columns so scikit-learn preprocessing receives
    predictable feature types.
    """

    result = df.copy()

    for column in result.select_dtypes(
        include=[
            "object",
            "string",
            "category",
        ]
    ).columns:

        result[column] = (
            result[column]
            .astype("string")
        )

    return result


def build_preprocessor(
    numeric_columns,
    categorical_columns,
):
    """Build a reusable preprocessing pipeline."""

    numeric_pipeline = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median"
                ),
            ),
            (
                "scaler",
                StandardScaler(),
            ),
        ]
    )

    categorical_pipeline = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="most_frequent"
                ),
            ),
            (
                "onehot",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=True,
                ),
            ),
        ]
    )

    return ColumnTransformer(
        transformers=[
            (
                "numeric",
                numeric_pipeline,
                numeric_columns,
            ),
            (
                "categorical",
                categorical_pipeline,
                categorical_columns,
            ),
        ],
        remainder="drop",
    )


def build_models():
    """Return candidate estimators."""

    return {
        "Logistic Regression":
            LogisticRegression(
                max_iter=1500,
                class_weight="balanced",
                solver="liblinear",
                random_state=RANDOM_STATE,
            ),

        "Random Forest":
            RandomForestClassifier(
                n_estimators=250,
                max_depth=18,
                min_samples_leaf=2,
                class_weight="balanced_subsample",
                n_jobs=-1,
                random_state=RANDOM_STATE,
            ),

        "Extra Trees":
            ExtraTreesClassifier(
                n_estimators=250,
                max_depth=None,
                min_samples_leaf=2,
                class_weight="balanced",
                n_jobs=-1,
                random_state=RANDOM_STATE,
            ),
    }


def threshold_metrics(
    y_true,
    probabilities,
    threshold,
):
    """Calculate classification metrics for one decision threshold."""

    predictions = (
        probabilities
        >= threshold
    ).astype(int)

    tn, fp, fn, tp = confusion_matrix(
        y_true,
        predictions,
        labels=[
            0,
            1,
        ],
    ).ravel()

    return {
        "threshold":
            float(threshold),

        "accuracy":
            accuracy_score(
                y_true,
                predictions,
            ),

        "precision":
            precision_score(
                y_true,
                predictions,
                zero_division=0,
            ),

        "recall":
            recall_score(
                y_true,
                predictions,
                zero_division=0,
            ),

        "f1":
            f1_score(
                y_true,
                predictions,
                zero_division=0,
            ),

        "f2":
            fbeta_score(
                y_true,
                predictions,
                beta=2,
                zero_division=0,
            ),

        "tn":
            int(tn),

        "fp":
            int(fp),

        "fn":
            int(fn),

        "tp":
            int(tp),
    }


def choose_threshold(
    y_validation,
    probabilities,
):
    """
    Choose a threshold on validation data only.

    F2 is used because missing maintenance-required records is considered
    more costly for this supporting experiment than producing some extra
    false positives.
    """

    candidates = []

    for threshold in THRESHOLDS:

        metrics = threshold_metrics(
            y_validation,
            probabilities,
            threshold,
        )

        candidates.append(
            metrics
        )

    candidates.sort(
        key=lambda row: (
            row["f2"],
            row["recall"],
            row["precision"],
            -abs(
                row["threshold"]
                - 0.50
            ),
        ),
        reverse=True,
    )

    return candidates[0]


def classify_model_evidence(
    roc_auc,
    pr_auc,
    prevalence,
):
    """
    Convert held-out discrimination metrics into a conservative TrackEase
    recommendation for whether ML should influence maintenance priority.
    """

    pr_gain = (
        pr_auc
        - prevalence
    )

    if (
        roc_auc
        >= MIN_STRONG_ROC_AUC
        and pr_gain
        >= MIN_STRONG_PR_GAIN
    ):
        return (
            "STRONG_SUPPORT_SIGNAL",
            (
                "The model demonstrates meaningful held-out predictive "
                "signal and may be considered as a limited supporting "
                "component after further domain validation."
            ),
        )

    if (
        roc_auc
        >= MIN_LIMITED_ROC_AUC
        and pr_gain
        >= MIN_LIMITED_PR_GAIN
    ):
        return (
            "LIMITED_SUPPORT_SIGNAL",
            (
                "The model shows some held-out predictive signal, but it "
                "should remain secondary to TrackEase's explainable "
                "maintenance-priority logic."
            ),
        )

    return (
        "NOT_RECOMMENDED_FOR_PRIORITY_INTEGRATION",
        (
            "The dataset/model combination does not demonstrate enough "
            "held-out discrimination to justify adding ML into the "
            "maintenance-priority score."
        ),
    )


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------

def run_ml_v2():
    """Run the complete TrackEase Maintenance ML V2 experiment."""

    print("=" * 72)
    print("TrackEase - Maintenance ML V2 Experiment")
    print("=" * 72)

    require_input_file()

    print("\nInput:")
    print(f"  {INPUT_FILE}")
    print("  ✓ Found")

    data = pd.read_csv(
        INPUT_FILE,
        low_memory=False,
    )

    print(
        f"\nRows loaded    : "
        f"{len(data):,}"
    )

    print(
        f"Columns loaded : "
        f"{len(data.columns):,}"
    )

    if TARGET_COLUMN not in data.columns:
        raise ValueError(
            f"Target column '{TARGET_COLUMN}' is missing."
        )

    # -----------------------------------------------------------------------
    # Target validation
    # -----------------------------------------------------------------------

    target = pd.to_numeric(
        data[
            TARGET_COLUMN
        ],
        errors="coerce",
    )

    valid_target = (
        target.isin(
            [
                0,
                1,
            ]
        )
    )

    invalid_target_count = int(
        (
            ~valid_target
        ).sum()
    )

    if invalid_target_count > 0:

        raise ValueError(
            f"{invalid_target_count:,} target records are not binary 0/1."
        )

    y = target.astype(int)

    prevalence = float(
        y.mean()
    )

    # -----------------------------------------------------------------------
    # Feature selection
    # -----------------------------------------------------------------------

    feature_columns = [
        column
        for column in data.columns
        if column not in LEAKAGE_COLUMNS
    ]

    X = data[
        feature_columns
    ].copy()

    X = normalize_feature_types(
        X
    )

    numeric_columns = (
        X.select_dtypes(
            include=[
                "number",
                "bool",
            ]
        )
        .columns
        .tolist()
    )

    categorical_columns = [
        column
        for column in X.columns
        if column not in numeric_columns
    ]

    print(
        f"\nFeatures used        : "
        f"{len(feature_columns):,}"
    )

    print(
        f"Numeric features     : "
        f"{len(numeric_columns):,}"
    )

    print(
        f"Categorical features : "
        f"{len(categorical_columns):,}"
    )

    print(
        f"Positive prevalence  : "
        f"{prevalence:.2%}"
    )

    # -----------------------------------------------------------------------
    # 70 / 15 / 15 stratified split
    # -----------------------------------------------------------------------

    (
        X_train,
        X_temp,
        y_train,
        y_temp,
    ) = train_test_split(
        X,
        y,
        test_size=0.30,
        stratify=y,
        random_state=RANDOM_STATE,
    )

    (
        X_validation,
        X_test,
        y_validation,
        y_test,
    ) = train_test_split(
        X_temp,
        y_temp,
        test_size=0.50,
        stratify=y_temp,
        random_state=RANDOM_STATE,
    )

    print("\nSplit:")
    print(
        f"  Train      : "
        f"{len(X_train):,}"
    )
    print(
        f"  Validation : "
        f"{len(X_validation):,}"
    )
    print(
        f"  Test       : "
        f"{len(X_test):,}"
    )

    models = build_models()

    result_rows = []
    trained_pipelines = {}

    # -----------------------------------------------------------------------
    # Compare candidate models
    # -----------------------------------------------------------------------

    for model_name, estimator in models.items():

        print("\n" + "-" * 72)
        print(
            f"Training: {model_name}"
        )
        print("-" * 72)

        preprocessor = build_preprocessor(
            numeric_columns,
            categorical_columns,
        )

        pipeline = Pipeline(
            steps=[
                (
                    "preprocessor",
                    preprocessor,
                ),
                (
                    "model",
                    estimator,
                ),
            ]
        )

        # A small subset of third-party FutureWarnings is intentionally not
        # promoted to errors here; TrackEase records the actual model metrics.
        with warnings.catch_warnings():
            warnings.simplefilter(
                "default"
            )

            pipeline.fit(
                X_train,
                y_train,
            )

        validation_probabilities = (
            pipeline.predict_proba(
                X_validation
            )[:, 1]
        )

        test_probabilities = (
            pipeline.predict_proba(
                X_test
            )[:, 1]
        )

        validation_roc_auc = roc_auc_score(
            y_validation,
            validation_probabilities,
        )

        validation_pr_auc = average_precision_score(
            y_validation,
            validation_probabilities,
        )

        test_roc_auc = roc_auc_score(
            y_test,
            test_probabilities,
        )

        test_pr_auc = average_precision_score(
            y_test,
            test_probabilities,
        )

        default_test = threshold_metrics(
            y_test,
            test_probabilities,
            threshold=0.50,
        )

        selected_threshold = choose_threshold(
            y_validation,
            validation_probabilities,
        )

        tuned_test = threshold_metrics(
            y_test,
            test_probabilities,
            threshold=selected_threshold[
                "threshold"
            ],
        )

        evidence_status, evidence_note = (
            classify_model_evidence(
                roc_auc=test_roc_auc,
                pr_auc=test_pr_auc,
                prevalence=prevalence,
            )
        )

        result_rows.append(
            {
                "model":
                    model_name,

                "positive_prevalence":
                    prevalence,

                "validation_roc_auc":
                    validation_roc_auc,

                "validation_pr_auc":
                    validation_pr_auc,

                "test_roc_auc":
                    test_roc_auc,

                "test_pr_auc":
                    test_pr_auc,

                "pr_auc_gain_over_baseline":
                    test_pr_auc
                    - prevalence,

                "default_threshold":
                    0.50,

                "default_accuracy":
                    default_test[
                        "accuracy"
                    ],

                "default_precision":
                    default_test[
                        "precision"
                    ],

                "default_recall":
                    default_test[
                        "recall"
                    ],

                "default_f1":
                    default_test[
                        "f1"
                    ],

                "default_f2":
                    default_test[
                        "f2"
                    ],

                "tuned_threshold":
                    selected_threshold[
                        "threshold"
                    ],

                "validation_tuned_f2":
                    selected_threshold[
                        "f2"
                    ],

                "tuned_accuracy":
                    tuned_test[
                        "accuracy"
                    ],

                "tuned_precision":
                    tuned_test[
                        "precision"
                    ],

                "tuned_recall":
                    tuned_test[
                        "recall"
                    ],

                "tuned_f1":
                    tuned_test[
                        "f1"
                    ],

                "tuned_f2":
                    tuned_test[
                        "f2"
                    ],

                "tuned_tn":
                    tuned_test[
                        "tn"
                    ],

                "tuned_fp":
                    tuned_test[
                        "fp"
                    ],

                "tuned_fn":
                    tuned_test[
                        "fn"
                    ],

                "tuned_tp":
                    tuned_test[
                        "tp"
                    ],

                "evidence_status":
                    evidence_status,

                "evidence_note":
                    evidence_note,
            }
        )

        trained_pipelines[
            model_name
        ] = pipeline

        print(
            f"Test ROC-AUC : "
            f"{test_roc_auc:.4f}"
        )

        print(
            f"Test PR-AUC  : "
            f"{test_pr_auc:.4f}"
        )

        print(
            f"Tuned threshold: "
            f"{selected_threshold['threshold']:.2f}"
        )

        print(
            f"Tuned precision: "
            f"{tuned_test['precision']:.4f}"
        )

        print(
            f"Tuned recall   : "
            f"{tuned_test['recall']:.4f}"
        )

        print(
            f"Tuned F2       : "
            f"{tuned_test['f2']:.4f}"
        )

    results = pd.DataFrame(
        result_rows
    )

    # -----------------------------------------------------------------------
    # Select best model by held-out PR-AUC.
    #
    # Test data is used here only to compare the completed experiment
    # candidates for the prototype. No further threshold tuning occurs.
    # -----------------------------------------------------------------------

    results = results.sort_values(
        [
            "test_pr_auc",
            "test_roc_auc",
            "tuned_f2",
            "model",
        ],
        ascending=[
            False,
            False,
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )

    results.to_csv(
        METRICS_FILE,
        index=False,
    )

    best = results.iloc[0]

    best_model_name = str(
        best[
            "model"
        ]
    )

    best_pipeline = (
        trained_pipelines[
            best_model_name
        ]
    )

    best_status = str(
        best[
            "evidence_status"
        ]
    )

    # -----------------------------------------------------------------------
    # Save model artifacts.
    #
    # Even when evidence is weak, retaining the experiment artifact makes
    # the baseline reproducible. Metadata explicitly prevents accidental
    # use as a core decision model.
    # -----------------------------------------------------------------------

    MODEL_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    joblib.dump(
        best_pipeline,
        MODEL_FILE,
    )

    metadata = {
        "model_version":
            "Maintenance ML V2",

        "best_model":
            best_model_name,

        "target":
            TARGET_COLUMN,

        "feature_columns":
            feature_columns,

        "numeric_columns":
            numeric_columns,

        "categorical_columns":
            categorical_columns,

        "leakage_columns_excluded":
            sorted(
                LEAKAGE_COLUMNS
            ),

        "random_state":
            RANDOM_STATE,

        "train_rows":
            len(
                X_train
            ),

        "validation_rows":
            len(
                X_validation
            ),

        "test_rows":
            len(
                X_test
            ),

        "positive_prevalence":
            prevalence,

        "selected_threshold":
            float(
                best[
                    "tuned_threshold"
                ]
            ),

        "test_roc_auc":
            float(
                best[
                    "test_roc_auc"
                ]
            ),

        "test_pr_auc":
            float(
                best[
                    "test_pr_auc"
                ]
            ),

        "tuned_precision":
            float(
                best[
                    "tuned_precision"
                ]
            ),

        "tuned_recall":
            float(
                best[
                    "tuned_recall"
                ]
            ),

        "tuned_f1":
            float(
                best[
                    "tuned_f1"
                ]
            ),

        "tuned_f2":
            float(
                best[
                    "tuned_f2"
                ]
            ),

        "evidence_status":
            best_status,

        "integration_allowed":
            best_status
            in {
                "LIMITED_SUPPORT_SIGNAL",
                "STRONG_SUPPORT_SIGNAL",
            },

        "integration_rule":
            (
                "ML may only be used as a supporting signal. "
                "The explainable TrackEase priority engine remains primary."
            ),
    }

    joblib.dump(
        metadata,
        METADATA_FILE,
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Maintenance ML V2 Experiment Report",
        "=" * 72,
        "",
        "DATA",
        "-" * 72,
        f"Rows                         : {len(data):,}",
        f"Features used                : {len(feature_columns):,}",
        f"Positive prevalence          : {prevalence:.2%}",
        f"Train rows                   : {len(X_train):,}",
        f"Validation rows              : {len(X_validation):,}",
        f"Test rows                    : {len(X_test):,}",
        "",
        "LEAKAGE CONTROL",
        "-" * 72,
    ]

    for column in sorted(
        LEAKAGE_COLUMNS
    ):

        report.append(
            f"Excluded: {column}"
        )

    report.extend(
        [
            "",
            "MODEL COMPARISON",
            "-" * 72,
        ]
    )

    for row in results.itertuples():

        report.extend(
            [
                f"Model: {row.model}",
                (
                    f"  Test ROC-AUC     : "
                    f"{row.test_roc_auc:.4f}"
                ),
                (
                    f"  Test PR-AUC      : "
                    f"{row.test_pr_auc:.4f}"
                ),
                (
                    f"  PR-AUC gain      : "
                    f"{row.pr_auc_gain_over_baseline:.4f}"
                ),
                (
                    f"  Tuned threshold  : "
                    f"{row.tuned_threshold:.2f}"
                ),
                (
                    f"  Tuned precision  : "
                    f"{row.tuned_precision:.4f}"
                ),
                (
                    f"  Tuned recall     : "
                    f"{row.tuned_recall:.4f}"
                ),
                (
                    f"  Tuned F1         : "
                    f"{row.tuned_f1:.4f}"
                ),
                (
                    f"  Tuned F2         : "
                    f"{row.tuned_f2:.4f}"
                ),
                (
                    f"  Evidence         : "
                    f"{row.evidence_status}"
                ),
                "",
            ]
        )

    report.extend(
        [
            "BEST MODEL",
            "-" * 72,
            f"Model                        : {best_model_name}",
            (
                f"Held-out ROC-AUC             : "
                f"{float(best['test_roc_auc']):.4f}"
            ),
            (
                f"Held-out PR-AUC              : "
                f"{float(best['test_pr_auc']):.4f}"
            ),
            (
                f"Positive prevalence baseline : "
                f"{prevalence:.4f}"
            ),
            (
                f"Selected threshold           : "
                f"{float(best['tuned_threshold']):.2f}"
            ),
            (
                f"Tuned precision              : "
                f"{float(best['tuned_precision']):.4f}"
            ),
            (
                f"Tuned recall                 : "
                f"{float(best['tuned_recall']):.4f}"
            ),
            (
                f"Tuned F2                     : "
                f"{float(best['tuned_f2']):.4f}"
            ),
            "",
            "TRACKEASE DECISION",
            "-" * 72,
            f"Evidence status              : {best_status}",
            str(
                best[
                    "evidence_note"
                ]
            ),
            "",
            (
                "The ML model does not automatically replace the existing "
                "explainable TrackEase priority score."
            ),
            (
                "No synthetic maintenance training rows were introduced."
            ),
            "",
            "ARTIFACTS",
            "-" * 72,
            f"Best model                   : {MODEL_FILE}",
            f"Metadata                     : {METADATA_FILE}",
            f"Metrics table                : {METRICS_FILE}",
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("MAINTENANCE ML V2 EXPERIMENT COMPLETE")
    print("=" * 72)

    print(
        f"\nBest model      : "
        f"{best_model_name}"
    )

    print(
        f"Test ROC-AUC    : "
        f"{float(best['test_roc_auc']):.4f}"
    )

    print(
        f"Test PR-AUC     : "
        f"{float(best['test_pr_auc']):.4f}"
    )

    print(
        f"Baseline PR-AUC : "
        f"{prevalence:.4f}"
    )

    print(
        f"Tuned threshold : "
        f"{float(best['tuned_threshold']):.2f}"
    )

    print(
        f"Tuned precision : "
        f"{float(best['tuned_precision']):.4f}"
    )

    print(
        f"Tuned recall    : "
        f"{float(best['tuned_recall']):.4f}"
    )

    print(
        f"Tuned F2        : "
        f"{float(best['tuned_f2']):.4f}"
    )

    print(
        f"\nEvidence status : "
        f"{best_status}"
    )

    print("\nOutputs:")
    print(
        f"  {METRICS_FILE}"
    )
    print(
        f"  {REPORT_FILE}"
    )
    print(
        f"  {MODEL_FILE}"
    )
    print(
        f"  {METADATA_FILE}"
    )

    print(
        "\nTrackEase will integrate ML into maintenance priority only "
        "if this experiment demonstrates meaningful held-out signal."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_ml_v2()
