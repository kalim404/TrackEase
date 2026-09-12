"""
TrackEase - Maintenance Requirement Model Training

Purpose:
    Train the first TrackEase predictive-maintenance model.

Target:
    maintenance_required

The model predicts whether maintenance is required from equipment,
condition, environmental and operational features.

Outputs:
    data/models/maintenance_requirement_model.joblib
    data/models/maintenance_model_metadata.joblib
    data/processed/maintenance_model_metrics.txt

Important:
    - Post-failure / target-derived fields are excluded to reduce leakage.
    - Raw data is never modified.
"""

from pathlib import Path

import joblib
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


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

MODEL_DIR = (
    PROJECT_ROOT
    / "data"
    / "models"
)

MODEL_FILE = (
    MODEL_DIR
    / "maintenance_requirement_model.joblib"
)

METADATA_FILE = (
    MODEL_DIR
    / "maintenance_model_metadata.joblib"
)

METRICS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "maintenance_model_metrics.txt"
)


TARGET_COLUMN = "maintenance_required"


# ---------------------------------------------------------------------------
# Columns intentionally excluded from training
# ---------------------------------------------------------------------------

LEAKAGE_COLUMNS = [
    # Target itself
    "maintenance_required",

    # TrackEase copy / transformations of target or post-event labels
    "maintenance_needed",
    "failure_type",
    "failure_severity",
    "severity_priority",
    "high_risk_flag",

    # Source risk score may already encode maintenance/failure logic.
    # We exclude it so the model learns from underlying conditions.
    "risk_score",

    # Derived rule-based planning indicator.
    "infrastructure_warning",

    # Source identifier, not a meaningful predictive feature.
    "train_id",
]


# ---------------------------------------------------------------------------
# Main training pipeline
# ---------------------------------------------------------------------------

def train_model():
    """Train and save the TrackEase maintenance requirement model."""

    print("=" * 72)
    print("TrackEase - Maintenance Requirement Model Training")
    print("=" * 72)

    print("\nInput:")
    print(f"  {INPUT_FILE}")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Prepared maintenance data not found:\n{INPUT_FILE}"
        )

    print("  ✓ Found")

    # -----------------------------------------------------------------------
    # Load data
    # -----------------------------------------------------------------------

    df = pd.read_csv(INPUT_FILE)

    print(f"\nRows loaded    : {len(df):,}")
    print(f"Columns loaded : {len(df.columns)}")

    if TARGET_COLUMN not in df.columns:
        raise ValueError(
            f"Target column '{TARGET_COLUMN}' not found."
        )

    # -----------------------------------------------------------------------
    # Target
    # -----------------------------------------------------------------------

    y = (
        pd.to_numeric(
            df[TARGET_COLUMN],
            errors="coerce",
        )
        .fillna(0)
        .astype(int)
    )

    # -----------------------------------------------------------------------
    # Feature matrix
    # -----------------------------------------------------------------------

    columns_to_drop = [
        column
        for column in LEAKAGE_COLUMNS
        if column in df.columns
    ]

    X = df.drop(
        columns=columns_to_drop
    ).copy()

    print(f"\nFeatures used : {len(X.columns)}")

    print("\nTarget distribution:")
    print(y.value_counts().sort_index().to_string())

    # -----------------------------------------------------------------------
    # Detect feature types
    # -----------------------------------------------------------------------

    categorical_columns = (
        X.select_dtypes(
            include=[
                "object",
                "string",
                "category",
            ]
        )
        .columns
        .tolist()
    )

    numeric_columns = [
        column
        for column in X.columns
        if column not in categorical_columns
    ]

    print(
        f"\nNumeric features     : "
        f"{len(numeric_columns)}"
    )

    print(
        f"Categorical features : "
        f"{len(categorical_columns)}"
    )

    # -----------------------------------------------------------------------
    # Preprocessing
    # -----------------------------------------------------------------------

    numeric_pipeline = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median"
                ),
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
                "encoder",
                OneHotEncoder(
                    handle_unknown="ignore"
                ),
            ),
        ]
    )

    preprocessor = ColumnTransformer(
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
        ]
    )

    # -----------------------------------------------------------------------
    # Model
    # -----------------------------------------------------------------------

    classifier = RandomForestClassifier(
        n_estimators=150,
        max_depth=18,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )

    model = Pipeline(
        steps=[
            (
                "preprocessor",
                preprocessor,
            ),
            (
                "classifier",
                classifier,
            ),
        ]
    )

    # -----------------------------------------------------------------------
    # Train/test split
    # -----------------------------------------------------------------------

    X_train, X_test, y_train, y_test = (
        train_test_split(
            X,
            y,
            test_size=0.20,
            random_state=42,
            stratify=y,
        )
    )

    print(
        f"\nTraining rows : "
        f"{len(X_train):,}"
    )

    print(
        f"Testing rows  : "
        f"{len(X_test):,}"
    )

    # -----------------------------------------------------------------------
    # Train
    # -----------------------------------------------------------------------

    print(
        "\nTraining Random Forest model..."
    )

    model.fit(
        X_train,
        y_train,
    )

    print("  ✓ Training complete")

    # -----------------------------------------------------------------------
    # Predictions
    # -----------------------------------------------------------------------

    predictions = model.predict(
        X_test
    )

    probabilities = model.predict_proba(
        X_test
    )[:, 1]

    # -----------------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------------

    accuracy = accuracy_score(
        y_test,
        predictions,
    )

    precision = precision_score(
        y_test,
        predictions,
        zero_division=0,
    )

    recall = recall_score(
        y_test,
        predictions,
        zero_division=0,
    )

    f1 = f1_score(
        y_test,
        predictions,
        zero_division=0,
    )

    roc_auc = roc_auc_score(
        y_test,
        probabilities,
    )

    matrix = confusion_matrix(
        y_test,
        predictions,
    )

    report = classification_report(
        y_test,
        predictions,
        digits=4,
        zero_division=0,
    )

    # -----------------------------------------------------------------------
    # Save model
    # -----------------------------------------------------------------------

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    joblib.dump(
        model,
        MODEL_FILE,
    )

    metadata = {
        "target_column": TARGET_COLUMN,
        "feature_columns": X.columns.tolist(),
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
        "excluded_columns": columns_to_drop,
        "training_rows": len(X_train),
        "testing_rows": len(X_test),
        "random_state": 42,
    }

    joblib.dump(
        metadata,
        METADATA_FILE,
    )

    # -----------------------------------------------------------------------
    # Metrics report
    # -----------------------------------------------------------------------

    metrics_text = f"""
========================================================================
TrackEase Maintenance Requirement Model Report
========================================================================

DATASET
------------------------------------------------------------------------
Total records       : {len(df):,}
Training records    : {len(X_train):,}
Testing records     : {len(X_test):,}
Features used       : {len(X.columns)}

MODEL
------------------------------------------------------------------------
Algorithm           : Random Forest Classifier
Trees               : 150
Maximum depth       : 18
Class balancing     : balanced

TEST METRICS
------------------------------------------------------------------------
Accuracy            : {accuracy:.4f}
Precision           : {precision:.4f}
Recall              : {recall:.4f}
F1 Score            : {f1:.4f}
ROC-AUC             : {roc_auc:.4f}

CONFUSION MATRIX
------------------------------------------------------------------------
{matrix}

CLASSIFICATION REPORT
------------------------------------------------------------------------
{report}

LEAKAGE PREVENTION
------------------------------------------------------------------------
Excluded columns:
{chr(10).join(f"- {column}" for column in columns_to_drop)}

NOTES
------------------------------------------------------------------------
The model predicts maintenance requirement from condition, sensor,
environmental and operational features.

failure_type, failure_severity, TrackEase target-derived fields and
risk_score were deliberately excluded from model inputs.

This model supports maintenance prioritization. It does not directly
select railway block timings.
""".strip()

    METRICS_FILE.write_text(
        metrics_text,
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console result
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("MODEL TRAINING COMPLETE")
    print("=" * 72)

    print(f"\nAccuracy  : {accuracy:.4f}")
    print(f"Precision : {precision:.4f}")
    print(f"Recall    : {recall:.4f}")
    print(f"F1 Score  : {f1:.4f}")
    print(f"ROC-AUC   : {roc_auc:.4f}")

    print("\nConfusion matrix:")
    print(matrix)

    print("\nOutputs:")
    print(f"  {MODEL_FILE}")
    print(f"  {METADATA_FILE}")
    print(f"  {METRICS_FILE}")

    print(
        "\nTarget-derived fields were excluded "
        "to reduce data leakage."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    train_model()