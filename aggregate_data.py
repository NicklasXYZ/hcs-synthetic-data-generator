import os
import json
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

pd.set_option("display.max_rows", None)


def load_data(data_dir):
    # Ensure the directory exists
    if not os.path.isdir(data_dir):
        raise FileNotFoundError(f"Directory not found: {data_dir}")

    json_path = os.path.join(data_dir, "events_full.json")

    # Ensure the file exists
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"File not found: {json_path}")

    # Optionally check if the file is readable
    if not os.access(json_path, os.R_OK):
        raise PermissionError(f"File is not readable: {json_path}")

    # Load and return the data
    with open(json_path) as f:
        events = json.load(f)
    return pd.DataFrame(events)


def create_histogram_data(data_dir: str, aggregation_interval=24):
    df = load_data(data_dir=data_dir)

    # Flexible datetime handling - use 'start' or 'timestamp'
    if "start" in df.columns and "timestamp" in df.columns:
        df["datetime"] = pd.to_datetime(df["start"].fillna(df["timestamp"]))
    elif "start" in df.columns:
        df["datetime"] = pd.to_datetime(df["start"])
    elif "timestamp" in df.columns:
        df["datetime"] = pd.to_datetime(df["timestamp"])
    else:
        raise ValueError("No time column found - need either 'start' or 'timestamp'")

    # Calculate 'aggregation-interval'-hour period number since simulation start
    hours = 12
    base_time = df["datetime"].min()
    df["period"] = (
        (df["datetime"] - base_time).dt.total_seconds() // (aggregation_interval * 3600)
    ).astype(int)

    # Group by patient-practitioner-period
    grouped = df.groupby(["patient_id", "practitioner_id", "period"])

    aggregates = []
    for (patient_id, practitioner_id, period), group in grouped:
        period_start = base_time + pd.Timedelta(hours=aggregation_interval * period)
        period_end = period_start + pd.Timedelta(hours=aggregation_interval)

        # Event type checks - consider only finished appointments
        # has_appt = ((group['type'] == 'Appointment') &
        #           (group['status'] == 'finished')).any()
        has_appt = (group["type"] == "Appointment").any()
        has_obs = (group["type"] == "Observation").any()
        has_enc = (group["type"] == "Encounter").any()

        # Handle AuditEvents with flexible data access
        has_btg = False
        has_care = False
        if "data" in group.columns:
            audit_events = group[group["type"] == "AuditEvent"]
            if not audit_events.empty:
                has_btg = (
                    audit_events["data"]
                    .apply(lambda x: x.get("purpose") == "BTG")
                    .any()
                )
                has_care = (
                    audit_events["data"]
                    .apply(lambda x: x.get("purpose") == "CAREMGT")
                    .any()
                )

        aggregates.append(
            {
                "patient_id": patient_id,
                "practitioner_id": practitioner_id,
                "period": period,
                "period_start": period_start,
                "period_end": period_end,
                "has_appointment": has_appt,
                "has_observation": has_obs,
                "has_encounter": has_enc,
                "has_btg_access": has_btg,
                "has_care_access": has_care,
            }
        )

    aggregates_df = pd.DataFrame(aggregates)

    # Add table IDs and labels
    aggregates_df["table_id"] = aggregates_df.apply(calculate_table_id, axis=1)
    aggregates_df["label"] = aggregates_df.apply(determine_label, axis=1)
    return aggregates_df


def calculate_table_id(row):
    """Calculate table ID (0-16) with CARE access handling"""
    a = row["has_appointment"]
    o = row["has_observation"]
    e = row["has_encounter"]
    b = row["has_btg_access"]
    c = row["has_care_access"]

    # Decision tree for table IDs
    # if not a and not o and not e and not b and not c: return 0
    if not a and not o and not e and not b and c:
        return 1
    if not a and not o and not e and b:
        return 2
    if not a and not o and e and not b:
        return 3
    if not a and not o and e and b:
        return 4
    if not a and o and not e and not b:
        return 5
    if not a and o and not e and b:
        return 6
    if not a and o and e and not b:
        return 7
    if not a and o and e and b:
        return 8
    if a and not o and not e and not b:
        return 9
    if a and not o and not e and b:
        return 10
    if a and not o and e and not b:
        return 11
    if a and not o and e and b:
        return 12
    if a and o and not e and not b:
        return 13
    if a and o and not e and b:
        return 14
    if a and o and e and not b:
        return 15
    if a and o and e and b:
        return 16
    raise ValueError(f"Unhandled combination: a={a}, o={o}, e={e}, b={b}, c={c}")


def determine_label(row):
    table_id = row["table_id"]
    # Anomaly cases (based on classification table)
    if table_id in [1, 3, 5, 7, 10]:
        return "Anomaly"
    return "Normal"


def plot_distribution(df):
    # Get counts and ensure full 0-16 range
    count_data = df.groupby(["table_id", "label"]).size()
    id_counts = count_data.unstack(fill_value=0).reindex(range(1, 17), fill_value=0)

    # Ensure both label columns exist
    for col in ["Normal", "Anomaly"]:
        if col not in id_counts:
            id_counts[col] = 0

    plt.figure(figsize=(14, 7))
    ax = plt.gca()
    colors = {"Normal": "#4CAF50", "Anomaly": "#F44336"}

    # Plot stacked bars
    x = id_counts.index
    bottom = np.zeros(len(x))
    for label, color in colors.items():
        counts = id_counts.get(label, np.zeros(len(x)))
        ax.bar(
            x,
            counts,
            bottom=bottom,
            color=color,
            label=label,
            edgecolor="white",
            width=0.8,
        )
        bottom += counts

    # Customize plot
    plt.title("Classification Distribution", fontsize=14)
    plt.xlabel("Table ID (1-16)", fontsize=12)
    plt.ylabel("Count", fontsize=12)
    plt.xticks(range(1, 17))
    max_count = df["table_id"].value_counts().sort_index()
    plt.ylim([0, max_count.max() + 25])
    plt.grid(axis="y", linestyle="--", alpha=0.75)

    # Add legend and value labels
    ax.legend(title="Classification:")
    for table_id in x:
        total = id_counts.loc[table_id].sum()
        if total > 0:  # Only label if count > 0
            plt.text(
                table_id, total + 0.1, str(total), ha="center", va="bottom", fontsize=9
            )

    plt.tight_layout()
    plt.savefig("./classification_distribution.png", dpi=300)
    plt.show()


# Run analysis
aggregation_interval = 12
data_dir = "./docs/data"
result_df = create_histogram_data(
    data_dir=data_dir, aggregation_interval=aggregation_interval
)
# plot_distribution(result_df)

# Print summary statistics
print("\n=== Classification Summary ===")
print(result_df["label"].value_counts())
print("\n=== Detailed Table ID Distribution ===")
print(result_df["table_id"].value_counts().sort_index())

# Save results
result_df.to_csv(f"{data_dir}/labeled_events_full-{aggregation_interval}H.csv", index=False)

sorted_counts = result_df["table_id"].value_counts().sort_index().to_frame()
sorted_counts = sorted_counts.reset_index()
sorted_counts["label"] = sorted_counts.apply(determine_label, axis=1)
sorted_counts.to_json(
    f"{data_dir}/histogram_data-{aggregation_interval}H.json", index=False
)
