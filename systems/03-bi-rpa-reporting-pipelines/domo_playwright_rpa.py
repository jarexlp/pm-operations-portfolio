# -*- coding: utf-8 -*-
"""
Headless BI Portal RPA Extractor (Playwright + Chromium + Pandas)

Automates recurring extraction of multi-hundred-thousand-row detailed reports
from enterprise BI portals without manual analyst downloads:
1. Launches Playwright persistent browser context with enterprise SSO session.
2. Detects MFA/SSO expiration cleanly and alerts operator when renewal needed.
3. Opens Controls drawer -> forces 'All Time' date range -> selects Detailed Report.
4. Verifies expanded modal card title to prevent extracting summary cards by mistake.
5. Streams CSV download, strips banner warning rows, applies configurable filters,
   and publishes normalized CSVs + triggers downstream Star Schema rebuild.

Sanitized portfolio edition: target URL and output directories read from env/JSON.
"""

import datetime
import json
import os
import pathlib
import subprocess
import sys
import time

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

load_dotenv()

BASE_DIR = pathlib.Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_rpa.json"

REQUIRED_DETAILED_COLUMNS = [
    "person id",
    "student status",
    "1up manager",
    "course name",
    "ops geo",
]


def load_config() -> dict:
    default_config = {
        "domo_url": os.getenv(
            "DOMO_APP_STUDIO_URL",
            "https://your-org.domo.com/app-studio/your_app_id/pages/your_page_id",
        ),
        "output_folder": os.getenv("HUB_BASE_DIR", str(BASE_DIR / "exports")),
        "output_prefix": "Enterprise_LMS_Detailed_Report",
        "headless": True,
        "timeout_seconds": 600,
        "browser_profile_dir": os.getenv("DOMO_BROWSER_PROFILE_DIR", str(BASE_DIR / ".browser_profile")),
        "filters": {
            "ops_geo": "LATAM",
            "student_status": "ALL",
            "course_name_contains": "CORE_PROGRAM",
        },
    }
    if CONFIG_FILE.exists():
        try:
            user_cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            default_config.update(user_cfg)
        except Exception as exc:
            print(f"[!] Warning reading config_rpa.json: {exc}")
    return default_config


def is_valid_detailed_report(df: pd.DataFrame | None) -> bool:
    if df is None or len(df) == 0:
        return False
    col_names = [str(c).lower().strip() for c in df.columns]
    matches = sum(1 for req in REQUIRED_DETAILED_COLUMNS if any(req in c for c in col_names))
    return matches >= 3 and len(df.columns) >= 10


def clean_and_load_file(file_path: pathlib.Path) -> pd.DataFrame | None:
    """Load Excel/CSV export and strip leading BI banner warning header row if present."""
    p = pathlib.Path(file_path)
    try:
        if p.suffix.lower() in [".xlsx", ".xls"]:
            preview = pd.read_excel(p, nrows=2)
            first_col = str(preview.columns[0]).lower()
            if "warning" in first_col or "not all the data is shown" in first_col:
                return pd.read_excel(p, header=1)
            return pd.read_excel(p)
        if p.suffix.lower() == ".csv":
            preview = pd.read_csv(p, nrows=2, encoding="utf-8", on_bad_lines="skip")
            first_col = str(preview.columns[0]).lower()
            if "warning" in first_col or "not all the data is shown" in first_col:
                return pd.read_csv(p, header=1, encoding="utf-8", on_bad_lines="skip", low_memory=False)
            return pd.read_csv(p, encoding="utf-8", on_bad_lines="skip", low_memory=False)
    except Exception as exc:
        print(f"[!] Failed loading {file_path}: {exc}")
    return None


def find_best_column(columns, candidates: list[str]) -> str | None:
    for cand in candidates:
        for col in columns:
            if col.strip().lower() == cand.lower():
                return col
    for cand in candidates:
        for col in columns:
            if cand.lower() in col.strip().lower():
                return col
    return None


def apply_dataframe_filters(df: pd.DataFrame | None, filters: dict) -> pd.DataFrame | None:
    if df is None or len(df) == 0:
        return df
    filtered_df = df.copy()
    ops_geo_target = filters.get("ops_geo", "").strip()
    course_target = filters.get("course_name_contains", "").strip()
    status_target = filters.get("student_status", "").strip()

    if ops_geo_target and ops_geo_target.upper() != "ALL":
        matched_col = find_best_column(filtered_df.columns, ["Ops Geo", "ops_geo", "geography", "geo"])
        if matched_col:
            filtered_df = filtered_df[
                filtered_df[matched_col].astype(str).str.strip().str.upper() == ops_geo_target.upper()
            ]

    if course_target:
        matched_course_col = find_best_column(filtered_df.columns, ["Course Name", "course_name", "course", "activity"])
        matched_id_col = find_best_column(filtered_df.columns, ["Course ID", "course_id", "id", "code"])
        if matched_course_col:
            mask = filtered_df[matched_course_col].astype(str).str.contains(course_target, case=False, na=False)
            if matched_id_col:
                mask = mask | filtered_df[matched_id_col].astype(str).str.contains(course_target, case=False, na=False)
            filtered_df = filtered_df[mask]

    if status_target and status_target.upper() != "ALL":
        matched_status_col = find_best_column(filtered_df.columns, ["Student Status", "student_status", "status"])
        if matched_status_col:
            filtered_df = filtered_df[
                filtered_df[matched_status_col].astype(str).str.contains(status_target, case=False, na=False)
            ]

    print(f"[*] Filter result: {len(df):,} -> {len(filtered_df):,} rows.")
    return filtered_df


def trigger_powerbi_refresh() -> None:
    pbi_script = BASE_DIR / "build_powerbi_dataset.py"
    if pbi_script.exists():
        print("[*] Refreshing downstream Power BI CSV feeds...")
        try:
            subprocess.run([sys.executable, str(pbi_script)], check=True)
        except Exception as exc:
            print(f"[!] Downstream refresh warning: {exc}")


def save_dataframe_to_csv(df: pd.DataFrame | None, output_folder: str, prefix: str, filters: dict | None = None):
    if df is None or len(df) == 0:
        return None
    if filters:
        df = apply_dataframe_filters(df, filters)

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    out_dir = pathlib.Path(output_folder)
    if not out_dir.is_absolute():
        out_dir = (BASE_DIR / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    file_daily = out_dir / f"{prefix}_{today_str}.csv"
    file_latest = out_dir / f"{prefix}_Latest.csv"
    df.to_csv(file_daily, index=False, encoding="utf-8-sig")
    df.to_csv(file_latest, index=False, encoding="utf-8-sig")
    print(f"[OK] Saved {len(df):,} rows -> {file_daily.name} & {file_latest.name}")

    trigger_powerbi_refresh()
    return file_daily


def run_downloader() -> bool:
    config = load_config()
    target_url = config["domo_url"]
    profile_dir = pathlib.Path(config["browser_profile_dir"])
    profile_dir.mkdir(parents=True, exist_ok=True)
    filters = config.get("filters", {})

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=config.get("headless", True),
            accept_downloads=True,
            downloads_path=str(BASE_DIR),
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
            no_viewport=True,
        )
        page = context.new_page()
        page.goto(target_url, wait_until="domcontentloaded", timeout=90000)
        time.sleep(6)

        sign_in_btn = page.locator("button:has-text('SIGN IN'), a:has-text('SIGN IN')").last
        if sign_in_btn.is_visible():
            sign_in_btn.click(force=True)
            time.sleep(12)

        if "login.microsoftonline.com" in page.url or "login.live.com" in page.url:
            print("[!] SSO session expired (MFA required). Run interactive session renewal first.")
            context.close()
            return False

        # Set Controls drawer filter to All Time
        try:
            ctrl_btn = page.locator("[data-ui-test_control-nav-item='controls'], button:has-text('Controls')").first
            ctrl_btn.click(force=True)
            time.sleep(3)
            all_time_opt = page.locator("div:has-text('All Time'), [role='menuitem']:has-text('All Time')").last
            if all_time_opt.is_visible():
                all_time_opt.click(force=True)
                time.sleep(3)
            ctrl_btn.click(force=True)
            time.sleep(3)
        except Exception as exc:
            print(f"[!] All Time filter warning: {exc}")

        # Switch tab & verify modal header before downloading
        try:
            det_btn = page.locator("button:has-text('Detailed Report')").last
            det_btn.scroll_into_view_if_needed(timeout=10000)
            det_btn.click(force=True)
            time.sleep(6)

            exp_btn = page.locator("button[aria-label*='Expand' i], button[title*='Expand' i]").first
            exp_btn.click(force=True)
            time.sleep(4)
            modal_titles = page.locator("h1, h2, h3, [class*='ModalTitle'], [class*='headerTitle']").all_inner_texts()
            if not any("detailed" in str(t).lower() for t in modal_titles):
                print(f"[!] Unexpected modal header {modal_titles}; aborting export.")
                context.close()
                return False
        except Exception as exc:
            print(f"[!] Failed isolating Detailed Report modal: {exc}")
            context.close()
            return False

        dots_btns = [d for d in page.locator("button[aria-label*='Menu' i], button:has(i.icon-dots-horizontal)").all() if d.is_visible()]
        if not dots_btns:
            context.close()
            return False
        dots_btns[-1].click(force=True)
        time.sleep(2)

        export_opts = [e for e in page.locator("div[class*='MenuItem']:has-text('Export'), div[class*='contentText']:has-text('Export')").all() if e.is_visible()]
        if export_opts:
            export_opts[-1].click(force=True)
            csv_btn = page.locator("#export-csv, button:has-text('CSV'), [data-ui-test-export-button-csv]").first
            csv_btn.wait_for(state="visible", timeout=10000)

            temp_path = BASE_DIR / "temp_portal_download.csv"
            with page.expect_download(timeout=900000) as download_info:
                csv_btn.click(force=True)
            download_info.value.save_as(str(temp_path))

            df = clean_and_load_file(temp_path)
            if is_valid_detailed_report(df):
                save_dataframe_to_csv(df, config["output_folder"], config["output_prefix"], filters=filters)
                if temp_path.exists():
                    temp_path.unlink()
                context.close()
                return True

        context.close()
        return False


if __name__ == "__main__":
    run_downloader()
