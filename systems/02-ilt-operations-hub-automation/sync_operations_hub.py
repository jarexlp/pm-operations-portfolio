# -*- coding: utf-8 -*-
"""
Master Operations Hub Synchronizer & Compliance Engine

Maintains unified SharePoint / OneDrive operational datasets across 9-12
automated workflows:
1. Operations_Calendar.csv/.xlsx  (Schedule + live enrollment + quorum risk radar)
2. Leader_Backlog.csv/.xlsx       (9,098 target leaders + sequential prereq unlock)
3. Registrations_Ledger.csv/.xlsx (Self-service enrollment audit log)
4. Completions_Master.csv/.xlsx   (Accredited completions from LMS / HRIS)
5. Alert_Log, Outreach_Log & Operations_KPI_Summary

Sanitized portfolio edition: paths loaded cleanly via environment variables with
zero hardcoded corporate endpoints or personally identifiable files.
"""

import datetime
import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(os.getenv("HUB_BASE_DIR", "./data/source_exports"))
PUBLISH_DIR = Path(os.getenv("HUB_PUBLISH_DIR", "./data/published_hub"))

SRC_COMPLETIONS = BASE_DIR / "completions_master.xlsx"
SRC_BACKLOG = BASE_DIR / "target_leader_backlog.xlsx"
SRC_CALENDAR = BASE_DIR / "operations_calendar_template.xlsx"


def ensure_publish_dir() -> None:
    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[*] Target directory ready: {PUBLISH_DIR}")


def sync_completions() -> set[str]:
    """Normalize accredited completions and return composite matching keys."""
    print("\n--- 1. PROCESSING COMPLETIONS MASTER ---")
    if not SRC_COMPLETIONS.exists():
        print(f"[!] Source completions file not found: {SRC_COMPLETIONS}")
        return set()

    df_comp = pd.read_excel(SRC_COMPLETIONS)
    cols_expected = [
        "Title", "EmployeeID", "Leader_Name", "Persona",
        "Country", "Site", "Client", "Completion_Date",
        "Status", "Source", "Unique_Key",
    ]
    available_cols = [c for c in cols_expected if c in df_comp.columns]
    df_clean = df_comp[available_cols].copy()

    df_clean["EmployeeID"] = df_clean["EmployeeID"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    df_clean["Title"] = df_clean["Title"].astype(str).str.strip()
    df_clean["Status"] = "Completed"

    df_clean.to_csv(PUBLISH_DIR / "Completions_Master.csv", index=False, encoding="utf-8")
    df_clean.to_excel(PUBLISH_DIR / "Completions_Master.xlsx", index=False, engine="openpyxl")
    print(f"[OK] Completions_Master synced: {len(df_clean):,} records.")

    return set(df_clean["EmployeeID"] + "___" + df_clean["Title"])


def sync_registrations() -> tuple[dict[str, int], dict[str, str]]:
    """Load active registrations ledger and count seats occupied per session."""
    print("\n--- 2. PROCESSING REGISTRATIONS LEDGER ---")
    out_csv = PUBLISH_DIR / "Registrations_Ledger.csv"
    out_xlsx = PUBLISH_DIR / "Registrations_Ledger.xlsx"

    if out_xlsx.exists():
        df_reg = pd.read_excel(out_xlsx, dtype=str)
    elif out_csv.exists():
        df_reg = pd.read_csv(out_csv, dtype=str)
    else:
        reg_cols = [
            "RegistrationID", "EmployeeID", "Leader_Name", "UserEmail",
            "SessionID", "Course_Name", "Event_Date", "Language",
            "Status", "Registration_Date", "Modified_By",
        ]
        df_reg = pd.DataFrame(columns=reg_cols)

    df_reg.to_csv(out_csv, index=False, encoding="utf-8")
    df_reg.to_excel(out_xlsx, index=False, engine="openpyxl")

    session_counts: dict[str, int] = {}
    enrolled_dict: dict[str, str] = {}
    if len(df_reg) > 0 and {"Status", "SessionID", "EmployeeID", "Course_Name"}.issubset(df_reg.columns):
        active_mask = df_reg["Status"].fillna("").str.strip().str.upper().isin(["REGISTERED", "INSCRITO", "ACTIVE"])
        active_reg = df_reg[active_mask]
        session_counts = active_reg["SessionID"].fillna("").str.strip().value_counts().to_dict()
        for _, row in active_reg.iterrows():
            key = f"{str(row['EmployeeID']).strip()}___{str(row['Course_Name']).strip()}"
            enrolled_dict[key] = str(row.get("SessionID", "")).strip()

    print(f"[OK] Registrations_Ledger synced ({len(df_reg):,} total rows).")
    return session_counts, enrolled_dict


def sync_backlog(completed_keys: set[str], enrolled_dict: dict[str, str]) -> None:
    """Reconcile target leader backlog, purge inactive/exempt roles, unlock cascade stages."""
    print("\n--- 3. PROCESSING TARGET LEADER BACKLOG ---")
    if not SRC_BACKLOG.exists():
        print(f"[!] Backlog source file not found: {SRC_BACKLOG}")
        return

    df_backlog = pd.read_excel(SRC_BACKLOG, sheet_name=0)
    df_backlog["EmployeeID"] = df_backlog["EmployeeID"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    df_backlog["Title"] = df_backlog["Title"].astype(str).str.strip()

    # Purge terminated IDs and out-of-scope executive roles deterministically
    payload_file = BASE_DIR / "daily_sync_payload.json"
    if payload_file.exists():
        term_eids = set(json.loads(payload_file.read_text(encoding="utf-8")).get("terminated_eids", []))
        df_backlog = df_backlog[~df_backlog["EmployeeID"].isin(term_eids)].copy()
    if "Job_Title" in df_backlog.columns:
        df_backlog = df_backlog[
            ~df_backlog["Job_Title"].astype(str).str.contains("Manager|Director|VP|President|Advisor", case=False, na=False)
        ].copy()

    # Reconcile against accredited completions and active registrations
    keys = df_backlog["EmployeeID"] + "___" + df_backlog["Title"]
    mask_completed = keys.isin(completed_keys)
    df_backlog.loc[mask_completed, "Status"] = "Completed"
    df_backlog.loc[mask_completed, "Status_Detail"] = "Accredited via LMS / HRIS Sync"

    for key, sess_id in enrolled_dict.items():
        mask_enrolled = (keys == key) & (df_backlog["Status"] != "Completed")
        df_backlog.loc[mask_enrolled, "Status"] = "Enrolled"
        df_backlog.loc[mask_enrolled, "Status_Detail"] = f"Registered in session {sess_id}"

    # Sequential stage unlocking (Pre-Req SPO -> Stage F1 -> Stage F2 -> Stage F3)
    stage_unlock_rules = [
        ("Stage F1", "Pre-Req (SPO)", "Pre-requisite SPO completed"),
        ("Stage F2", "Stage F1", "Stage F1 completed"),
        ("Stage F3", "Stage F2", "Stage F2 completed"),
    ]
    for target_stage, prereq_token, detail_msg in stage_unlock_rules:
        unlocked_eids = {k.split("___")[0] for k in completed_keys if prereq_token in k}
        mask_unlock = (
            (df_backlog["Title"] == target_stage)
            & (df_backlog["EmployeeID"].isin(unlocked_eids))
            & (df_backlog["Status"].isin(["Blocked", "Bloqueado"]))
        )
        df_backlog.loc[mask_unlock, "Status"] = "Pending"
        df_backlog.loc[mask_unlock, "Status_Detail"] = detail_msg

    df_backlog.to_csv(PUBLISH_DIR / "Leader_Backlog.csv", index=False, encoding="utf-8")
    df_backlog.to_excel(PUBLISH_DIR / "Leader_Backlog.xlsx", index=False, engine="openpyxl")
    print(f"[OK] Leader_Backlog synced: {len(df_backlog):,} rows | Breakdown: {df_backlog['Status'].value_counts().to_dict()}")


def sync_calendar(session_counts: dict[str, int]) -> pd.DataFrame | None:
    """Recalculate live enrollment capacity and compute D-14 / D-7 Quorum Risk."""
    print("\n--- 4. PROCESSING OPERATIONS CALENDAR & QUORUM RISK ---")
    existing_cal = PUBLISH_DIR / "Operations_Calendar.xlsx"
    source_cal = existing_cal if existing_cal.exists() else SRC_CALENDAR
    if not source_cal.exists():
        print("[!] No calendar file found.")
        return None

    df_cal = pd.read_excel(source_cal)
    for idx, row in df_cal.iterrows():
        code = str(row["Code"]).strip()
        if code in session_counts:
            df_cal.at[idx, "Current_Enrollment"] = int(session_counts[code])

    df_cal["Current_Enrollment"] = df_cal["Current_Enrollment"].fillna(0).astype(int)
    df_cal["Max_Capacity"] = 40
    df_cal["Quorum_Target"] = 20
    df_cal["Quorum_Gap"] = (df_cal["Quorum_Target"] - df_cal["Current_Enrollment"]).clip(lower=0)
    df_cal["Available_Seats"] = (df_cal["Max_Capacity"] - df_cal["Current_Enrollment"]).clip(lower=0)

    today = datetime.date.today()
    risk_levels = []
    for _, row in df_cal.iterrows():
        try:
            diff_days = (pd.to_datetime(row["Event_Date"]).date() - today).days
        except Exception:
            diff_days = 999
        cur = row["Current_Enrollment"]
        if cur < 20 and diff_days <= 7:
            risk_levels.append("RED")
        elif cur < 20 and 8 <= diff_days <= 14:
            risk_levels.append("YELLOW")
        else:
            risk_levels.append("HEALTHY")

    df_cal["Risk_Level"] = risk_levels
    if "SessionID" not in df_cal.columns and "Code" in df_cal.columns:
        df_cal["SessionID"] = df_cal["Code"]

    df_cal.to_csv(PUBLISH_DIR / "Operations_Calendar.csv", index=False, encoding="utf-8")
    df_cal.to_excel(PUBLISH_DIR / "Operations_Calendar.xlsx", index=False, engine="openpyxl")
    print(f"[OK] Operations_Calendar synced: {len(df_cal)} sessions | Risk: {df_cal['Risk_Level'].value_counts().to_dict()}")
    return df_cal


def sync_alerts(df_cal: pd.DataFrame) -> None:
    """Emit idempotent RED/YELLOW alert records to drive manager & candidate outreach."""
    print("\n--- 5. PROCESSING ALERT LOG ---")
    alerts = df_cal[df_cal["Risk_Level"].isin(["RED", "YELLOW"])].copy()
    today = datetime.date.today().isoformat()
    alert_rows = [
        {
            "Alert_ID": f"ALT-{r['Code']}-{today}",
            "Session_ID": r["Code"],
            "Course_Name": r["Course"],
            "Language": r["Language"],
            "Event_Date": r["Event_Date"],
            "Start_Time": r["Start_Time"],
            "Instructor_Name": r.get("Instructor_Full_Name", ""),
            "Current_Enrollment": r["Current_Enrollment"],
            "Target_Min_Enrollment": r["Quorum_Target"],
            "Enrollment_Gap": r["Quorum_Gap"],
            "Risk_Level": r["Risk_Level"],
            "Alert_Status": "Active",
            "Required_Action": f"Trigger Candidate Outreach: {r['Quorum_Gap']} seats needed for quorum.",
            "Alert_Date": today,
            "Unique_Alert_Key": f"{r['Code']}_{r['Event_Date']}_{r['Risk_Level']}",
        }
        for _, r in alerts.iterrows()
    ]
    df_alerts = pd.DataFrame(alert_rows)
    df_alerts.to_csv(PUBLISH_DIR / "Alert_Log.csv", index=False, encoding="utf-8")
    df_alerts.to_excel(PUBLISH_DIR / "Alert_Log.xlsx", index=False, engine="openpyxl")
    print(f"[OK] Alert_Log updated: {len(df_alerts)} active alerts.")


def sync_kpi_summary(df_cal: pd.DataFrame) -> None:
    """Publish executive roll-up workbook consumed by M365 Copilot Control Tower."""
    print("\n--- 6. GENERATING EXECUTIVE KPI SUMMARY ---")
    backlog_csv = PUBLISH_DIR / "Leader_Backlog.csv"
    df_bl = pd.read_csv(backlog_csv, dtype=str) if backlog_csv.exists() else pd.DataFrame()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    summary_metrics = [
        {"Metric": "Last_Sync_Timestamp", "Value": now_str},
        {"Metric": "Total_Scheduled_Sessions", "Value": len(df_cal)},
        {"Metric": "Critical_Risk_RED", "Value": int((df_cal["Risk_Level"] == "RED").sum())},
        {"Metric": "Warning_Risk_YELLOW", "Value": int((df_cal["Risk_Level"] == "YELLOW").sum())},
        {"Metric": "Healthy_Sessions", "Value": int((df_cal["Risk_Level"] == "HEALTHY").sum())},
        {"Metric": "Total_Backlog_Records", "Value": len(df_bl)},
        {"Metric": "Eligible_Pending", "Value": int((df_bl["Status"] == "Pending").sum()) if len(df_bl) else 0},
        {"Metric": "Prerequisite_Blocked", "Value": int((df_bl["Status"] == "Blocked").sum()) if len(df_bl) else 0},
        {"Metric": "Completed_Records", "Value": int((df_bl["Status"] == "Completed").sum()) if len(df_bl) else 0},
    ]
    df_sum = pd.DataFrame(summary_metrics)

    df_country = pd.DataFrame()
    if len(df_bl) > 0 and "Country_Code" in df_bl.columns:
        df_country = df_bl.groupby(["Country_Code", "Status"]).size().unstack(fill_value=0).reset_index()

    with pd.ExcelWriter(PUBLISH_DIR / "Operations_KPI_Summary.xlsx", engine="openpyxl") as writer:
        df_sum.to_excel(writer, sheet_name="KPI_Executive_Summary", index=False)
        if len(df_country) > 0:
            df_country.to_excel(writer, sheet_name="Backlog_By_Country", index=False)
    print("[OK] Operations_KPI_Summary.xlsx published.")


def main() -> None:
    print("=" * 65)
    print(f"OPERATIONS HUB MASTER SYNC | {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 65)
    ensure_publish_dir()
    completed_keys = sync_completions()
    session_counts, enrolled_dict = sync_registrations()
    sync_backlog(completed_keys, enrolled_dict)
    df_cal = sync_calendar(session_counts)
    if df_cal is not None:
        sync_alerts(df_cal)
        sync_kpi_summary(df_cal)
    print("\n[SUCCESS] Hub synchronization complete.")


if __name__ == "__main__":
    main()
